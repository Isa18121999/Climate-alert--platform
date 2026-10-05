import json
import os
import urllib.request
import urllib.error
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError

SNS_TOPIC_ARN = os.environ["SNS_TOPIC_ARN"]
API_BASE_URL = os.environ["API_BASE_URL"].rstrip("/")
TABLE_NAME = os.environ.get("TABLE_NAME", "climate-alert-sent")

sns = boto3.client("sns")
dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(TABLE_NAME)


def get_json(path: str) -> dict:
    request = urllib.request.Request(
        f"{API_BASE_URL}{path}",
        headers={"User-Agent": "ClimateAlertAWSLambda/1.0"},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def already_sent(alert_key: str) -> bool:
    try:
        response = table.get_item(Key={"alert_key": alert_key}, ConsistentRead=True)
        return "Item" in response
    except ClientError as exc:
        print(f"DynamoDB read error: {exc}")
        raise


def mark_sent(alert_key: str) -> bool:
    try:
        table.put_item(
            Item={
                "alert_key": alert_key,
                "sent_at": datetime.now(timezone.utc).isoformat(),
            },
            ConditionExpression="attribute_not_exists(alert_key)",
        )
        return True
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            return False
        raise


def publish_alert(alert: dict, kind: str) -> dict:
    alert_id = str(alert.get("id") or alert.get("alert_id") or "unknown")
    alert_key = f"{kind}:{alert_id}"

    if already_sent(alert_key):
        return {"status": "duplicate", "alert_key": alert_key}

    level = str(alert.get("level") or alert.get("risk_level") or "").upper()
    title = str(alert.get("title") or alert.get("name") or alert.get("alert_type") or "Alerta climática")
    message = str(alert.get("message") or alert.get("description") or title)
    source = str(alert.get("source") or ("SENAMHI" if kind == "official" else "Climate Alert Platform"))

    subject = f"Climate Alert Perú | {level or 'ALERTA'}"
    body = (
        f"ALERTA CLIMÁTICA EN PERÚ\n\n"
        f"Tipo: {kind}\n"
        f"Nivel: {level or 'No especificado'}\n"
        f"Evento: {title}\n"
        f"Mensaje: {message}\n"
        f"Fuente: {source}\n"
        f"Fecha de envío: {datetime.now(timezone.utc).isoformat()}\n\n"
        f"Esta notificación fue generada por Climate Alert Platform."
    )

    # Reserva la clave antes del envío para evitar duplicados si EventBridge ejecuta
    # la Lambda dos veces de forma concurrente. Si SNS falla, eliminamos la marca.
    if not mark_sent(alert_key):
        return {"status": "duplicate", "alert_key": alert_key}

    try:
        result = sns.publish(
            TopicArn=SNS_TOPIC_ARN,
            Subject=subject[:100],
            Message=body,
            MessageAttributes={
                "country": {"DataType": "String", "StringValue": "PE"},
                "alert_kind": {"DataType": "String", "StringValue": kind},
                "severity": {"DataType": "String", "StringValue": level or "UNKNOWN"},
            },
        )
        return {"status": "sent", "alert_key": alert_key, "message_id": result.get("MessageId")}
    except Exception:
        table.delete_item(Key={"alert_key": alert_key})
        raise


def active_official_alerts(payload: dict) -> list[dict]:
    items = payload.get("alerts") or []
    return [
        item for item in items
        if item.get("status") == "ACTUAL" or item.get("is_current") is True
    ]


def main(event, context):
    results = []

    try:
        monitor = get_json("/monitor")
        risk_data = monitor.get("risk") or {}
        risk_level = str(risk_data.get("level") or "").upper()

        # Riesgo calculado: solo FUERTE/EXTREMA genera notificación externa.
        # BAJA/MODERADA permanece visible en el dashboard sin enviar correo.
        if risk_level in {"ALTO", "CRITICO"}:
            risk_alert = {
                "id": f"aws-risk-{datetime.now(timezone.utc).strftime('%Y%m%d%H')}",
                "level": "EXTREMA" if risk_level == "CRITICO" else "FUERTE",
                "alert_type": "RIESGO_CALCULADO",
                "message": "; ".join(risk_data.get("reasons") or []) or f"Riesgo {risk_level}",
                "source": "Climate Alert Platform",
            }
            results.append(publish_alert(risk_alert, "risk"))

        # Avisos oficiales: únicamente los que SENAMHI marca como ACTUAL.
        official_payload = get_json("/official-alerts")
        for alert in active_official_alerts(official_payload):
            results.append(publish_alert(alert, "official"))

    except (urllib.error.URLError, TimeoutError) as exc:
        print(f"API request error: {exc}")
        raise

    return {
        "status": "ok",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "notifications": results,
    }


def lambda_handler(event, context):
    return main(event, context)
