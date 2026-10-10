from __future__ import annotations

import json
import os
from datetime import datetime, timezone

try:
    from kafka import KafkaProducer
except ImportError:  # pragma: no cover
    KafkaProducer = None


KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "")
KAFKA_ALERT_TOPIC = os.getenv("KAFKA_ALERT_TOPIC", "climate-alerts")


def _producer():
    if not KAFKA_BOOTSTRAP_SERVERS or KafkaProducer is None:
        return None
    kwargs = {
        "bootstrap_servers": [x.strip() for x in KAFKA_BOOTSTRAP_SERVERS.split(",") if x.strip()],
        "value_serializer": lambda value: json.dumps(value, ensure_ascii=False).encode("utf-8"),
        "retries": 3,
    }
    username = os.getenv("KAFKA_USERNAME")
    password = os.getenv("KAFKA_PASSWORD")
    security_protocol = os.getenv("KAFKA_SECURITY_PROTOCOL")
    sasl_mechanism = os.getenv("KAFKA_SASL_MECHANISM")
    if username and password:
        kwargs.update({"sasl_plain_username": username, "sasl_plain_password": password})
    if security_protocol:
        kwargs["security_protocol"] = security_protocol
    if sasl_mechanism:
        kwargs["sasl_mechanism"] = sasl_mechanism
    return KafkaProducer(**kwargs)


def publish_alert(alert: dict) -> bool:
    """Publica una alerta en Kafka. Si Kafka no está configurado, no rompe la API."""
    producer = _producer()
    if producer is None:
        return False
    event = {
        "event": "CLIMATE_ALERT",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "severity": alert.get("severity") or alert.get("level") or alert.get("risk_level"),
        "title": alert.get("title") or alert.get("message") or alert.get("alert_type", "Alerta climática"),
        "region": alert.get("region") or alert.get("location", {}).get("region"),
        "source": alert.get("source", "Climate Alert Platform"),
        "alert": alert,
    }
    try:
        producer.send(KAFKA_ALERT_TOPIC, event)
        producer.flush(timeout=5)
        return True
    except Exception as exc:
        print(f"KAFKA PUBLISH ERROR: {exc}")
        return False
    finally:
        try:
            producer.close()
        except Exception:
            pass
