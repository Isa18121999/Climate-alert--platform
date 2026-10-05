from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from uuid import uuid4

import requests
import xml.etree.ElementTree as ET
import xml.etree.ElementTree as ET
from flask import Flask, jsonify, request
from flask_cors import CORS

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "src"))
from senamhi import senamhi_alerts

app = Flask(__name__)
CORS(app)

OPEN_METEO_FORECAST = os.getenv("OPEN_METEO_FORECAST", "https://api.open-meteo.com/v1/forecast")
OPEN_METEO_FLOOD = os.getenv("OPEN_METEO_FLOOD", "https://flood-api.open-meteo.com/v1/flood")
GDELT_DOC = os.getenv("GDELT_DOC", "https://api.gdeltproject.org/api/v2/doc/doc")
DEFAULT_LAT = float(os.getenv("DEFAULT_LAT", "-5.1945"))
DEFAULT_LON = float(os.getenv("DEFAULT_LON", "-80.6328"))
DEFAULT_STATION_ID = os.getenv("DEFAULT_STATION_ID", "PIURA-DEMO")

measurements: list[dict] = []
alerts: list[dict] = []
official_alert_cache: list[dict] = []


def get_json(url: str, params: dict, timeout: int = 10) -> dict:
    r = requests.get(url, params=params, timeout=timeout, headers={"User-Agent": "climate-alert-platform/1.0"})
    r.raise_for_status()
    return r.json()


def google_news_rss(query: str) -> list[dict]:
    r = requests.get(
        "https://news.google.com/rss/search",
        params={"q": query, "hl": "es-419", "gl": "PE", "ceid": "PE:es-419"},
        timeout=10,
        headers={"User-Agent": "climate-alert-platform/1.0"},
    )
    r.raise_for_status()
    root = ET.fromstring(r.content)
    articles = []
    for item in root.findall(".//item"):
        title = item.findtext("title") or ""
        link = item.findtext("link") or ""
        pub_date = item.findtext("pubDate")
        source = item.find("source")
        source_name = source.text if source is not None else None
        if title and link:
            articles.append({
                "title": title,
                "url": link,
                "domain": source_name,
                "language": "es",
                "seendate": pub_date,
                "socialimage": None,
            })
        if len(articles) >= 20:
            break
    return articles


def gdelt_live_news(query: str) -> list[dict]:
    r = requests.get(
        "https://data.gdeltproject.org/gdeltv3/gal/feed.rss",
        timeout=8,
        headers={"User-Agent": "climate-alert-platform/1.0"},
    )
    r.raise_for_status()
    root = ET.fromstring(r.content)
    articles=[]
    for item in root.findall(".//item"):
        title=item.findtext("title") or ""
        link=item.findtext("link") or ""
        source=item.find("source")
        source_name=source.text if source is not None else None
        haystack=(title+" "+link+" "+(source_name or "")).lower()
        markers=("perú","peru",".pe/","lima","piura","arequipa","trujillo","cusco")
        if title and link and any(x in haystack for x in markers):
            articles.append({
                "title":title,"url":link,"domain":source_name,
                "language":"es","seendate":item.findtext("pubDate"),
                "socialimage":None,
            })
        if len(articles)>=20:
            break
    return articles


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
    return jsonify({
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "provider": "Render",
        "environment": "demo",
    })


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
    query = request.args.get("q", "Perú alerta climática lluvias inundaciones desbordes huaicos SENAMHI")

    try:
        articles = gdelt_live_news(query)
        if articles:
            return jsonify({
                "source": "GDELT Live RSS",
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "query": query,
                "articles": articles,
            })
    except Exception as exc:
        print(f"GDELT Live RSS: {exc}")

    try:
        articles = google_news_rss(query)
        if articles:
            return jsonify({
                "source": "Google News RSS",
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "query": query,
                "articles": articles,
            })
    except Exception as exc:
        print(f"Google News RSS: {exc}")

    return jsonify({
        "source": "News fallback",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "query": query,
        "articles": [],
        "source_update_note": "No se encontraron noticias disponibles en este momento.",
    })



@app.get("/official-alerts")
def official_alerts_route():
    global official_alert_cache
    result = senamhi_alerts()
    official_alert_cache = result.get("alerts", [])
    return jsonify(result)


@app.get("/monitor")
def monitor():
    lat = float(request.args.get("lat", DEFAULT_LAT))
    lon = float(request.args.get("lon", DEFAULT_LON))
    station_id = request.args.get("station_id", DEFAULT_STATION_ID)

    weather_data = get_json(
        OPEN_METEO_FORECAST,
        {
            "latitude": lat,
            "longitude": lon,
            "current": "temperature_2m,relative_humidity_2m,precipitation,rain,wind_speed_10m",
            "forecast_days": 1,
            "timezone": "UTC",
        },
    )
    flood_data = get_json(
        OPEN_METEO_FLOOD,
        {
            "latitude": lat,
            "longitude": lon,
            "daily": "river_discharge,river_discharge_max",
            "forecast_days": 7,
            "timezone": "UTC",
        },
    )

    current = weather_data.get("current") or {}
    daily = flood_data.get("daily") or {}
    rain_mm_h = float(current.get("rain") or 0)
    discharge = (daily.get("river_discharge") or [0])[0]
    river_value = float(discharge or 0)
    level, reasons = risk(rain_mm_h, river_value)

    created = []
    if level in {"ALTO", "CRITICO"}:
        bucket = datetime.now(timezone.utc).strftime("%Y%m%d%H")
        alert_id = f"risk-{station_id}-{bucket}"
        if not any(x.get("id") == alert_id for x in alerts):
            item = {
                "id": alert_id,
                "station_id": station_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "level": level,
                "alert_type": "RIESGO_CALCULADO",
                "official": False,
                "source": "Climate Alert Platform",
                "message": f"Riesgo {level}: {', '.join(reasons)}",
                "rain_mm_h": rain_mm_h,
                "river_level_m": river_value,
                "location": {"lat": lat, "lon": lon},
            }
            alerts.insert(0, item)
            created.append(item)

    official = senamhi_alerts()
    for item in official.get("alerts", []):
        alert_id = f"official-{item['id']}"
        if not any(x.get("id") == alert_id for x in alerts):
            stored = {**item, "id": alert_id, "alert_type": item.get("type", "AVISO_OFICIAL")}
            alerts.insert(0, stored)
            created.append(stored)

    return jsonify({
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "location": {"lat": lat, "lon": lon},
        "risk": {
            "level": level,
            "rain_mm_h": rain_mm_h,
            "river_level_m": river_value,
            "reasons": reasons,
        },
        "official_alerts": official.get("alerts", []),
        "created_alerts": created,
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
            "alert_type": "RIESGO_CALCULADO",
            "official": False,
            "source": "Climate Alert Platform",
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
