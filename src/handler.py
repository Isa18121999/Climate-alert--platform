from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import boto3

from risk_engine import evaluate_risk
from external_apis import flood, news, weather


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
    route = event.get("routeKey") or f"{event.get('requestContext', {}).get('http', {}).get('method', '')} {event.get('rawPath', '')}"
    try:
        if route.startswith("POST /measurements"):
            return ingest_measurement(_body(event))
        if route.startswith("GET /measurements"):
            return list_items(measurements)
        if route.startswith("GET /alerts"):
            return list_items(alerts)
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

    item = {
        "station_id": station_id,
        "measurement_id": measurement_id,
        "timestamp": timestamp,
        "rain_mm_h": Decimal(str(rain)),
        "river_level_m": Decimal(str(river)),
        "risk_level": result.level,
        "risk_score": result.score,
        "risk_reasons": result.reasons,
        "location": data.get("location", {}),
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


def list_items(table) -> dict:
    result = table.scan(Limit=50)
    items = sorted(result.get("Items", []), key=lambda x: str(x.get("timestamp", "")), reverse=True)
    return response(200, {"items": items[:50]})
