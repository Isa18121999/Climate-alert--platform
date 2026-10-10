from __future__ import annotations

import json
import os
import smtplib
from email.message import EmailMessage

from kafka import KafkaConsumer

KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
KAFKA_ALERT_TOPIC = os.getenv("KAFKA_ALERT_TOPIC", "climate-alerts")
KAFKA_GROUP_ID = os.getenv("KAFKA_GROUP_ID", "climate-alert-notifications")


def _send_email(event: dict) -> None:
    host = os.getenv("SMTP_HOST")
    port = int(os.getenv("SMTP_PORT", "587"))
    username = os.getenv("SMTP_USERNAME")
    password = os.getenv("SMTP_PASSWORD")
    sender = os.getenv("ALERT_EMAIL_FROM") or username
    recipient = os.getenv("ALERT_EMAIL_TO")
    if not all([host, username, password, sender, recipient]):
        print("EMAIL: SMTP no configurado; se omite el envío.")
        return

    severity = event.get("severity") or "SIN ESPECIFICAR"
    title = event.get("title") or "Alerta climática"
    region = event.get("region") or "Perú"
    source = event.get("source") or "Climate Alert Platform"

    message = EmailMessage()
    message["Subject"] = f"[{severity}] {title}"
    message["From"] = sender
    message["To"] = recipient
    message.set_content(
        f"Alerta climática\n\n"
        f"Severidad: {severity}\n"
        f"Título: {title}\n"
        f"Región: {region}\n"
        f"Fuente: {source}\n\n"
        "Este mensaje fue generado mediante Apache Kafka por Climate Alert Platform."
    )

    with smtplib.SMTP(host, port, timeout=20) as server:
        server.starttls()
        server.login(username, password)
        server.send_message(message)
    print(f"EMAIL enviado a {recipient}")


def _send_sms(event: dict) -> None:
    """SMS opcional mediante Twilio. Kafka sigue siendo el intermediario del evento."""
    sid = os.getenv("TWILIO_ACCOUNT_SID")
    token = os.getenv("TWILIO_AUTH_TOKEN")
    from_number = os.getenv("TWILIO_FROM_NUMBER")
    to_number = os.getenv("ALERT_SMS_TO")
    if not all([sid, token, from_number, to_number]):
        print("SMS: Twilio no configurado; se omite el envío.")
        return

    try:
        from twilio.rest import Client
    except ImportError:
        print("SMS: instala twilio para habilitar el envío.")
        return

    severity = event.get("severity") or "SIN ESPECIFICAR"
    title = event.get("title") or "Alerta climática"
    region = event.get("region") or "Perú"
    body = f"[{severity}] {title} - {region}. Climate Alert Platform"
    Client(sid, token).messages.create(body=body[:1500], from_=from_number, to=to_number)
    print(f"SMS enviado a {to_number}")


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

        # Política del proyecto: todas las alertas se procesan por correo;
        # SMS se reserva para niveles altos/críticos.
        try:
            _send_email(event)
        except Exception as exc:
            print(f"EMAIL ERROR: {exc}")

        if severity in {"ROJO", "CRÍTICA", "CRITICA", "CRITICO", "CRÍTICO", "ALTA", "NARANJA"}:
            try:
                _send_sms(event)
            except Exception as exc:
                print(f"SMS ERROR: {exc}")


if __name__ == "__main__":
    consume()
