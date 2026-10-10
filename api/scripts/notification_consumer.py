from __future__ import annotations

import json
import os
import smtplib
from email.message import EmailMessage

from kafka import KafkaConsumer
import requests

BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "")
TOPIC = os.getenv("KAFKA_ALERT_TOPIC", "climate-alerts")
GROUP = os.getenv("KAFKA_CONSUMER_GROUP", "climate-alert-notifications")


def send_email(event: dict) -> None:
    host = os.getenv("SMTP_HOST")
    port = int(os.getenv("SMTP_PORT", "587"))
    username = os.getenv("SMTP_USERNAME")
    password = os.getenv("SMTP_PASSWORD")
    recipient = os.getenv("ALERT_EMAIL_TO")
    if not all([host, username, password, recipient]):
        print("EMAIL: SMTP no configurado; se omite envío")
        return
    severity = event.get("severity", "ALERTA")
    title = event.get("title", "Alerta climática")
    message = event.get("alert", {}).get("message", title)
    mail = EmailMessage()
    mail["Subject"] = f"[{severity}] {title}"
    mail["From"] = username
    mail["To"] = recipient
    mail.set_content(f"Alerta climática\n\nSeveridad: {severity}\nTítulo: {title}\nDetalle: {message}\nFuente: {event.get('source', 'Climate Alert Platform')}\n")
    with smtplib.SMTP(host, port, timeout=20) as smtp:
        smtp.starttls()
        smtp.login(username, password)
        smtp.send_message(mail)


def send_sms(event: dict) -> None:
    url = os.getenv("SMS_API_URL")
    token = os.getenv("SMS_API_TOKEN")
    to = os.getenv("SMS_TO")
    if not all([url, token, to]):
        print("SMS: proveedor no configurado; se omite envío")
        return
    severity = event.get("severity", "ALERTA")
    title = event.get("title", "Alerta climática")
    text = f"[{severity}] {title}"
    response = requests.post(url, json={"to": to, "message": text}, headers={"Authorization": f"Bearer {token}"}, timeout=20)
    response.raise_for_status()


def main() -> None:
    if not BOOTSTRAP:
        raise RuntimeError("KAFKA_BOOTSTRAP_SERVERS no está configurado")
    consumer = KafkaConsumer(
        TOPIC,
        bootstrap_servers=[x.strip() for x in BOOTSTRAP.split(",") if x.strip()],
        group_id=GROUP,
        auto_offset_reset="latest",
        enable_auto_commit=True,
        value_deserializer=lambda value: json.loads(value.decode("utf-8")),
    )
    print(f"Kafka consumer activo: topic={TOPIC}, group={GROUP}")
    for record in consumer:
        event = record.value
        severity = str(event.get("severity", "")).upper()
        try:
            # Política: ROJO -> email + SMS; NARANJA -> email; AMARILLO -> dashboard/Kafka.
            if severity == "ROJO":
                send_email(event)
                send_sms(event)
            elif severity == "NARANJA":
                send_email(event)
        except Exception as exc:
            print(f"NOTIFICATION ERROR: {exc}")


if __name__ == "__main__":
    main()
