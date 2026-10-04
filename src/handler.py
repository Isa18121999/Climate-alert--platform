from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import boto3

from risk_engine import evaluate_risk
from external_apis import flood, news, weather
from senamhi import senamhi_alerts


measurements = boto3.resource("dynamodb").Table(os.environ["MEASUREMENTS_TABLE"])
alerts = boto3.resource("dynamodb").Table(os.environ["ALERTS_TABLE"])
sns = boto3.client("sns")


def response(status: int, body: dict) -> dict:
    return {
        "statusCode": status,
        "headers": {"content-type": "application/json"},
        "body": json.dumps(body, default=str),
    }


def _body(event: dict) -> dict:
    raw = event.get("body") or "{}"
    return json.loads(raw) if isinstance(raw, str) else raw


def app(event: dict, _context) -> dict:
    if event.get("action") == "monitor":
        return run_monitor()

    request_http = event.get("requestContext", {}).get("http", {})
    method = request_http.get("method", "")
    path = event.get("rawPath") or request_http.get("path", "")
    route_key = event.get("routeKey", "")
    route = route_key if route_key and route_key != "$default" else f"{method} {path}"

    try:
        if route.startswith("POST /measurements"):
            return ingest_measurement(_body(event))
        if route.startswith("GET /measurements"):
            return list_items(measurements)
        if route.startswith("GET /alerts"):
            return list_items(alerts)
        if route.startswith("GET /official-alerts"):
            return response(200, senamhi_alerts())
        if route.startswith("GET /health"):
            return response(200, {"status": "ok", "provider": "AWS", "environment": "production"})
        if route.startswith("GET /weather"):
            params = event.get("queryStringParameters") or {}
            lat = float(params.get("lat", "-5.1945"))
            lon = float(params.get("lon", "-80.6328"))
            return response(200, weather(lat, lon))
        if route.startswith("GET /flood"):
            params = event.get("queryStringParameters") or {}
            lat = float(params.get("lat", "-5.1945"))
            lon = float(params.get("lon", "-80.6328"))
            return response(200, flood(lat, lon))
        if route.startswith("GET /news"):
            params = event.get("queryStringParameters") or {}
            query = params.get("q", "Peru inundación lluvias El Niño")
            return response(200, news(query))
        return response(404, {"message": "Ruta no encontrada"})
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        return response(400, {"message": str(exc)})
    except Exception as exc:  # pragma: no cover - safety net for Lambda
        print(f"Unhandled error: {exc}")
        return response(500, {"message": "Error interno"})


def ingest_measurement(data: dict) -> dict:
    station_id = str(data["station_id"])
    rain = float(data["rain_mm_h"])
    river = float(data["river_level_m"])
    timestamp = data.get("timestamp") or datetime.now(timezone.utc).isoformat()
    result = evaluate_risk(rain, river)
    measurement_id = f"{timestamp}#{uuid.uuid4().hex[:8]}"

    location = data.get("location", {}) or {}
    if isinstance(location, dict):
        location = {
            key: Decimal(str(value)) if isinstance(value, float) else value
            for key, value in location.items()
        }

    item = {
        "station_id": station_id,
        "measurement_id": measurement_id,
        "timestamp": timestamp,
        "rain_mm_h": Decimal(str(rain)),
        "river_level_m": Decimal(str(river)),
        "risk_level": result.level,
        "risk_score": result.score,
        "risk_reasons": result.reasons,
        "location": location,
    }
    measurements.put_item(Item=item)

    if result.level in {"ALTO", "CRITICO"}:
        alert_id = f"{timestamp}#{uuid.uuid4().hex[:8]}"
        alert = {
            "station_id": station_id,
            "alert_id": alert_id,
            "timestamp": timestamp,
            "level": result.level,
            "message": f"Riesgo {result.level}: {', '.join(result.reasons)}",
        }
        alerts.put_item(Item=alert)
        topic_arn = os.getenv("SNS_TOPIC_ARN")
        if topic_arn:
            sns.publish(
                TopicArn=topic_arn,
                Subject=f"Alerta {result.level} - {station_id}",
                Message=json.dumps(alert, ensure_ascii=False),
            )

    item["measurement_id"] = measurement_id
    return response(201, {"measurement": item})



def run_monitor() -> dict:
    lat = float(os.getenv("DEFAULT_LAT", "-5.1945"))
    lon = float(os.getenv("DEFAULT_LON", "-80.6328"))
    station_id = os.getenv("DEFAULT_STATION_ID", "PIURA-001")

    weather_data = weather(lat, lon)
    flood_data = flood(lat, lon)
    current = weather_data.get("current") or {}
    daily = flood_data.get("daily") or {}
    rain = float(current.get("rain") or 0)
    river_values = daily.get("river_discharge") or [0]
    river = float(river_values[0] or 0)

    result = evaluate_risk(rain, river)
    created = []

    # Registrar cada monitoreo programado en DynamoDB para que el historial
    # de mediciones no dependa únicamente de envíos manuales desde el dashboard.
    measurement_id = f"{datetime.now(timezone.utc).isoformat()}#{uuid.uuid4().hex[:8]}"
    measurement = {
        "station_id": station_id,
        "measurement_id": measurement_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "rain_mm_h": Decimal(str(rain)),
        "river_level_m": Decimal(str(river)),
        "risk_level": result.level,
        "risk_score": result.score,
        "risk_reasons": result.reasons,
        "location": {
            "lat": Decimal(str(lat)),
            "lon": Decimal(str(lon)),
        },
        "source": "monitor_automatico",
    }
    try:
        measurements.put_item(Item=measurement)
    except Exception as exc:
        print(f"No se pudo guardar la medición automática: {exc}")

    if result.level in {"ALTO", "CRITICO"}:
        bucket = datetime.now(timezone.utc).strftime("%Y%m%d%H")
        alert_id = f"risk-{station_id}-{bucket}"
        alert = {
            "station_id": station_id,
            "alert_id": alert_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": result.level,
            "alert_type": "RIESGO_CALCULADO",
            "official": False,
            "source": "Climate Alert Platform",
            "message": f"Riesgo {result.level}: {', '.join(result.reasons)}",
            "rain_mm_h": Decimal(str(rain)),
            "river_level_m": Decimal(str(river)),
        }
        try:
            alerts.put_item(Item=alert, ConditionExpression="attribute_not_exists(alert_id)")
            created.append(alert)
            topic_arn = os.getenv("SNS_TOPIC_ARN")
            if topic_arn:
                sns.publish(
                    TopicArn=topic_arn,
                    Subject=f"Alerta {result.level} - {station_id}",
                    Message=json.dumps(alert, default=str, ensure_ascii=False),
                )
        except Exception as exc:
            if "ConditionalCheckFailed" not in str(exc):
                raise

    official = senamhi_alerts()
    for item in official.get("alerts", []):
        alert_id = f"official-{item['id']}"
        alert = {
            "station_id": station_id,
            "alert_id": alert_id,
            "timestamp": item.get("issued_at") or datetime.now(timezone.utc).isoformat(),
            "level": item.get("level", "INFORMACION"),
            "alert_type": item.get("type", "AVISO_OFICIAL"),
            "official": True,
            "source": item.get("source", "SENAMHI"),
            "title": item.get("title"),
            "number": item.get("number"),
            "start_at": item.get("start_at"),
            "end_at": item.get("end_at"),
            "url": item.get("url"),
            "message": item.get("title", "Aviso oficial SENAMHI"),
        }
        try:
            alerts.put_item(Item=alert, ConditionExpression="attribute_not_exists(alert_id)")
            created.append(alert)
            topic_arn = os.getenv("SNS_TOPIC_ARN")
            if topic_arn:
                sns.publish(
                    TopicArn=topic_arn,
                    Subject=f"Aviso SENAMHI {alert['level']}",
                    Message=json.dumps(alert, ensure_ascii=False),
                )
        except Exception as exc:
            if "ConditionalCheckFailed" not in str(exc):
                raise

    return response(200, {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "location": {"lat": lat, "lon": lon},
        "risk": {
            "level": result.level,
            "rain_mm_h": rain,
            "river_level_m": river,
            "reasons": result.reasons,
        },
        "official_alerts": official.get("alerts", []),
        "created_alerts": created,
    })


def list_items(table) -> dict:
    result = table.scan(Limit=50)
    items = sorted(result.get("Items", []), key=lambda x: str(x.get("timestamp", "")), reverse=True)
    return response(200, {"items": items[:50]})
