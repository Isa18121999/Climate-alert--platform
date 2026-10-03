from __future__ import annotations

import os
from datetime import datetime, timezone
from uuid import uuid4

import requests
from flask import Flask, jsonify, request
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

OPEN_METEO_FORECAST = os.getenv("OPEN_METEO_FORECAST", "https://api.open-meteo.com/v1/forecast")
OPEN_METEO_FLOOD = os.getenv("OPEN_METEO_FLOOD", "https://flood-api.open-meteo.com/v1/flood")
GDELT_DOC = os.getenv("GDELT_DOC", "https://api.gdeltproject.org/api/v2/doc/doc")

measurements: list[dict] = []
alerts: list[dict] = []


def get_json(url: str, params: dict, timeout: int = 10) -> dict:
    r = requests.get(url, params=params, timeout=timeout, headers={"User-Agent": "climate-alert-platform/1.0"})
    r.raise_for_status()
    return r.json()


def risk(rain: float, river: float) -> tuple[str, list[str]]:
    reasons = []
    if rain >= 50:
        reasons.append("lluvia >= 50 mm/h")
    elif rain >= 35:
        reasons.append("lluvia >= 35 mm/h")
    elif rain >= 20:
        reasons.append("lluvia >= 20 mm/h")

    if river >= 5:
        reasons.append("nivel de río >= 5 m")
    elif river >= 4:
        reasons.append("nivel de río >= 4 m")
    elif river >= 3:
        reasons.append("nivel de río >= 3 m")

    if rain >= 50 or river >= 5:
        return "CRITICO", reasons
    if rain >= 35 or river >= 4 or len(reasons) >= 2:
        return "ALTO", reasons
    if rain >= 20 or river >= 3:
        return "MEDIO", reasons
    return "BAJO", reasons


@app.get("/")
def health():
    return jsonify({"status": "ok", "service": "climate-alert-platform-api"})


@app.get("/health")
def health_check():
    return jsonify({"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()})


@app.get("/weather")
def weather():
    lat = float(request.args.get("lat", "-5.1945"))
    lon = float(request.args.get("lon", "-80.6328"))
    data = get_json(
        OPEN_METEO_FORECAST,
        {
            "latitude": lat,
            "longitude": lon,
            "current": "temperature_2m,relative_humidity_2m,precipitation,rain,wind_speed_10m",
            "forecast_days": 1,
            "timezone": "UTC",
        },
    )
    return jsonify({
        "source": "Open-Meteo Weather API",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "location": {"lat": lat, "lon": lon},
        **data,
    })


@app.get("/flood")
def flood():
    lat = float(request.args.get("lat", "-5.1945"))
    lon = float(request.args.get("lon", "-80.6328"))
    data = get_json(
        OPEN_METEO_FLOOD,
        {
            "latitude": lat,
            "longitude": lon,
            "daily": "river_discharge,river_discharge_max",
            "forecast_days": 7,
            "timezone": "UTC",
        },
    )
    return jsonify({
        "source": "Open-Meteo Flood API / GloFAS",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "location": {"lat": lat, "lon": lon},
        **data,
    })


@app.get("/news")
def news():
    query = request.args.get("q", "Peru inundación lluvias El Niño")
    data = get_json(
        GDELT_DOC,
        {
            "query": query,
            "mode": "ArtList",
            "format": "json",
            "maxrecords": 12,
            "sort": "HybridRel",
            "timespan": "15min",
            "sourcelang": "Spanish",
        },
        timeout=15,
    )
    return jsonify({
        "source": "GDELT DOC 2.0",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "query": query,
        "articles": data.get("articles", []),
    })


@app.post("/measurements")
def create_measurement():
    data = request.get_json(force=True)
    station_id = str(data.get("station_id", "WEB-001"))
    rain_mm_h = float(data["rain_mm_h"])
    river_level_m = float(data["river_level_m"])
    level, reasons = risk(rain_mm_h, river_level_m)

    item = {
        "id": str(uuid4()),
        "station_id": station_id,
        "timestamp": data.get("timestamp", datetime.now(timezone.utc).isoformat()),
        "rain_mm_h": rain_mm_h,
        "river_level_m": river_level_m,
        "risk_level": level,
        "risk_reasons": reasons,
        "location": data.get("location", {}),
    }
    measurements.insert(0, item)

    if level in {"ALTO", "CRITICO"}:
        alerts.insert(0, {
            "id": str(uuid4()),
            "station_id": station_id,
            "timestamp": item["timestamp"],
            "level": level,
            "message": f"Riesgo {level}: {', '.join(reasons)}",
        })

    return jsonify({"measurement": item}), 201


@app.get("/measurements")
def list_measurements():
    return jsonify({"items": measurements[:50]})


@app.get("/alerts")
def list_alerts():
    return jsonify({"items": alerts[:50]})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")))
