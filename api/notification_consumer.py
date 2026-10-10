from __future__ import annotations

import json
import os

import boto3
from kafka import KafkaConsumer

KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
KAFKA_ALERT_TOPIC = os.getenv("KAFKA_ALERT_TOPIC", "climate-alerts")
KAFKA_GROUP_ID = os.getenv("KAFKA_GROUP_ID", "climate-alert-notifications")


def _aws_client(service: str):
    """Create an AWS client using environment credentials or the AWS SDK credential chain."""
    return boto3.client(
        service,
        region_name=os.getenv("AWS_REGION", "us-east-1"),
    )


def _send_email(event: dict) -> None:
    """Send the Kafka alert through Amazon SES."""
    sender = os.getenv("ALERT_EMAIL_FROM")
    recipient = os.getenv("ALERT_EMAIL_TO")
    if not sender or not recipient:
        print("EMAIL: Amazon SES no configurado; se omite el envío.")
        return

    severity = event.get("severity") or "SIN ESPECIFICAR"
    title = event.get("title") or "Alerta climática"
    region = event.get("region") or "Perú"
    source = event.get("source") or "Climate Alert Platform"

    subject = f"[{severity}] {title}"
    body = (
        "Alerta climática\n\n"
        f"Severidad: {severity}\n"
        f"Título: {title}\n"
        f"Región: {region}\n"
        f"Fuente: {source}\n\n"
        "Este mensaje fue generado mediante Apache Kafka por Climate Alert Platform."
    )

    _aws_client("ses").send_email(
        Source=sender,
        Destination={"ToAddresses": [recipient]},
        Message={
            "Subject": {"Data": subject, "Charset": "UTF-8"},
            "Body": {"Text": {"Data": body, "Charset": "UTF-8"}},
        },
    )
    print(f"SES: email enviado a {recipient}")


def _send_sms(event: dict) -> None:
    """Send high-severity Kafka alerts through Amazon SNS."""
    recipient = os.getenv("ALERT_SMS_TO")
    if not recipient:
        print("SMS: Amazon SNS no configurado; se omite el envío.")
        return

    severity = str(event.get("severity") or "").upper()
    title = event.get("title") or "Alerta climática"
    region = event.get("region") or "Perú"
    body = f"[{severity}] {title} - {region}. Climate Alert Platform"

    _aws_client("sns").publish(
        PhoneNumber=recipient,
        Message=body[:1600],
    )
    print(f"SNS: SMS enviado a {recipient}")


def consume() -> None:
    consumer = KafkaConsumer(
        KAFKA_ALERT_TOPIC,
        bootstrap_servers=[x.strip() for x in KAFKA_BOOTSTRAP_SERVERS.split(",") if x.strip()],
        group_id=KAFKA_GROUP_ID,
        auto_offset_reset="latest",
        enable_auto_commit=True,
        value_deserializer=lambda value: json.loads(value.decode("utf-8")),
    )
    print(f"Escuchando Kafka topic={KAFKA_ALERT_TOPIC} brokers={KAFKA_BOOTSTRAP_SERVERS}")

    for record in consumer:
        event = record.value
        print(f"ALERTA RECIBIDA: {json.dumps(event, ensure_ascii=False)}")
        severity = str(event.get("severity") or "").upper()

        # El correo recibe todas las alertas publicadas en Kafka.
        try:
            _send_email(event)
        except Exception as exc:
            print(f"SES ERROR: {exc}")

        # SMS para alertas NARANJA/ROJO; AMARILLO no genera SMS.
        if severity in {"ROJO", "NARANJA"}:
            try:
                _send_sms(event)
            except Exception as exc:
                print(f"SNS ERROR: {exc}")


if __name__ == "__main__":
    consume()
