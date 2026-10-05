from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from uuid import uuid4
from urllib.parse import urlparse

import requests
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
from flask import Flask, jsonify, request
from flask_cors import CORS

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "src"))
from senamhi import senamhi_alerts

app = Flask(__name__)
CORS(app)

OPEN_METEO_FORECAST = os.getenv("OPEN_METEO_FORECAST", "https://api.open-meteo.com/v1/forecast")
OPEN_METEO_FLOOD = os.getenv("OPEN_METEO_FLOOD", "https://flood-api.open-meteo.com/v1/flood")
DEFAULT_LAT = float(os.getenv("DEFAULT_LAT", "-5.1945"))
DEFAULT_LON = float(os.getenv("DEFAULT_LON", "-80.6328"))
DEFAULT_STATION_ID = os.getenv("DEFAULT_STATION_ID", "PIURA-DEMO")

measurements: list[dict] = []
alerts: list[dict] = []
official_alert_cache: list[dict] = []

PERU_MEDIA_DOMAINS = (
    "rpp.pe", "elcomercio.pe", "larepublica.pe", "andina.pe", "gestion.pe", "peru21.pe",
)
CLIMATE_TERMS = (
    "alerta", "lluvia", "lluvias", "precipit", "inund", "desborde", "huaico", "huayco",
    "tormenta", "crecida", "caudal", "quebrada", "deslizamiento", "río", "rio", "senamhi",
    "ciclón", "ciclon", "meteorológ", "meteorolog", "temperatura extrema", "ola de calor",
    "oleaje", "granizo", "helada", "friaje", "viento fuerte", "fenómeno el niño", "fenomeno el nino",
)
GENERIC_TERMS = (
    "horóscopo", "horoscopo", "deportes", "entretenimiento", "farándula", "farandula", "informativa",
    "elecciones", "votación", "votacion", "partido", "fútbol", "futbol",
)


def get_json(url: str, params: dict, timeout: int = 10) -> dict:
    r = requests.get(url, params=params, timeout=timeout, headers={"User-Agent": "climate-alert-platform/1.0"})
    r.raise_for_status()
    return r.json()


def _allowed_peru_source(url: str) -> bool:
    host = urlparse(url).netloc.lower().split(":")[0]
    return any(host == domain or host.endswith("." + domain) for domain in PERU_MEDIA_DOMAINS)


def _is_climate_article(title: str, description: str = "", category: str = "") -> bool:
    text = f"{title} {description} {category}".lower()
    return any(term in text for term in CLIMATE_TERMS) and not any(term in text for term in GENERIC_TERMS)


def _add_article(articles: list[dict], seen: set[str], title: str, link: str, source_label: str, description: str = "", pub_date: str | None = None, category: str = "") -> None:
    title = BeautifulSoup(title, "html.parser").get_text(" ", strip=True)
    description = BeautifulSoup(description, "html.parser").get_text(" ", strip=True)
    link = link.strip()
    if not title or not link or not _allowed_peru_source(link):
        return
    if not _is_climate_article(title, description, category):
        return
    key = link.lower()
    if key in seen:
        return
    seen.add(key)
    articles.append({
        "title": title,
        "url": link,
        "domain": source_label,
        "source": source_label,
        "language": "es",
        "seendate": pub_date,
        "socialimage": None,
        "country": "PE",
        "region": "Perú",
        "category": category or "Clima",
    })


def _parse_tolerant_feed(content: bytes, source_label: str, articles: list[dict], seen: set[str]) -> None:
    """Parse malformed RSS without allowing one bad XML token to empty all news."""
    try:
        root = ET.fromstring(content)
        items = root.findall(".//item")
        for item in items:
            _add_article(
                articles, seen,
                item.findtext("title") or "",
                item.findtext("link") or "",
                source_label,
                item.findtext("description") or "",
                item.findtext("pubDate"),
                " ".join(x.text or "" for x in item.findall("category")),
            )
        return
    except ET.ParseError:
        pass

    # BeautifulSoup's XML parser is more tolerant of malformed entities.
    soup = BeautifulSoup(content, "xml")
    for item in soup.find_all("item"):
        _add_article(
            articles, seen,
            item.find("title").get_text(" ", strip=True) if item.find("title") else "",
            item.find("link").get_text(" ", strip=True) if item.find("link") else "",
            source_label,
            item.find("description").get_text(" ", strip=True) if item.find("description") else "",
            item.find("pubDate").get_text(" ", strip=True) if item.find("pubDate") else None,
            " ".join(x.get_text(" ", strip=True) for x in item.find_all("category")),
        )


def _parse_source_page(content: bytes, source_label: str, articles: list[dict], seen: set[str]) -> None:
    """Fallback for publishers that serve an HTML page instead of valid RSS."""
    soup = BeautifulSoup(content, "html.parser")
    for anchor in soup.find_all("a", href=True):
        title = anchor.get_text(" ", strip=True)
        href = anchor.get("href", "").strip()
        if href.startswith("/"):
            host = "rpp.pe" if source_label == "RPP" else "elcomercio.pe"
            href = f"https://{host}{href}"
        _add_article(articles, seen, title, href, source_label)
        if len(articles) >= 10:
            break


def peruvian_climate_rss_news() -> list[dict]:
    feeds = [
        ("RPP", "https://rpp.pe/rss-titulares.xml", "https://rpp.pe/fenomenoelnino"),
        ("El Comercio", "https://elcomercio.pe/arc/outboundfeeds/rss/category/peru/?outputType=xml", "https://elcomercio.pe/noticias/senamhi/"),
        ("El Comercio Lima", "https://elcomercio.pe/arc/outboundfeeds/rss/category/lima/?outputType=xml", "https://elcomercio.pe/noticias/senamhi/"),
    ]
    articles: list[dict] = []
    seen: set[str] = set()

    for source_label, feed_url, page_url in feeds:
        try:
            r = requests.get(feed_url, timeout=5, headers={"User-Agent": "ClimateAlertPlatform/1.0 (+academic-project)"})
            r.raise_for_status()
            _parse_tolerant_feed(r.content, source_label, articles, seen)
        except Exception as exc:
            print(f"RSS {source_label}: {exc}")

        if len(articles) < 5:
            try:
                r = requests.get(page_url, timeout=5, headers={"User-Agent": "ClimateAlertPlatform/1.0 (+academic-project)"})
                r.raise_for_status()
                _parse_source_page(r.content, source_label, articles, seen)
            except Exception as exc:
                print(f"PAGE {source_label}: {exc}")

        if len(articles) >= 10:
            break

    return articles[:20]


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
    return jsonify({"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat(), "provider": "Render", "environment": "demo"})


@app.get("/weather")
def weather():
    lat = float(request.args.get("lat", "-5.1945"))
    lon = float(request.args.get("lon", "-80.6328"))
    data = get_json(OPEN_METEO_FORECAST, {"latitude": lat, "longitude": lon, "current": "temperature_2m,relative_humidity_2m,precipitation,rain,wind_speed_10m", "forecast_days": 1, "timezone": "UTC"})
    return jsonify({"source": "Open-Meteo Weather API", "fetched_at": datetime.now(timezone.utc).isoformat(), "location": {"lat": lat, "lon": lon}, **data})


@app.get("/flood")
def flood():
    lat = float(request.args.get("lat", "-5.1945"))
    lon = float(request.args.get("lon", "-80.6328"))
    data = get_json(OPEN_METEO_FLOOD, {"latitude": lat, "longitude": lon, "daily": "river_discharge,river_discharge_max", "forecast_days": 7, "timezone": "UTC"})
    return jsonify({"source": "Open-Meteo Flood API / GloFAS", "fetched_at": datetime.now(timezone.utc).isoformat(), "location": {"lat": lat, "lon": lon}, **data})


@app.get("/news")
def news():
    query = request.args.get("q", "Perú alerta climática lluvias inundaciones desbordes huaicos SENAMHI")
    articles = peruvian_climate_rss_news()
    return jsonify({"source": "RSS y páginas de medios peruanos", "fetched_at": datetime.now(timezone.utc).isoformat(), "query": query, "articles": articles, "source_update_note": "Noticias climáticas recientes de medios peruanos." if articles else "No se encontraron noticias climáticas válidas en las fuentes peruanas configuradas."})


@app.get("/official-alerts")
def official_alerts_route():
    global official_alert_cache
    result = senamhi_alerts()
    official_alert_cache = result.get("alerts", [])
    return jsonify(result)


@app.get("/monitor")
def monitor():
    lat = float(request.args.get("lat", DEFAULT_LAT)); lon = float(request.args.get("lon", DEFAULT_LON)); station_id = request.args.get("station_id", DEFAULT_STATION_ID)
    weather_data = get_json(OPEN_METEO_FORECAST, {"latitude": lat, "longitude": lon, "current": "temperature_2m,relative_humidity_2m,precipitation,rain,wind_speed_10m", "forecast_days": 1, "timezone": "UTC"})
    flood_data = get_json(OPEN_METEO_FLOOD, {"latitude": lat, "longitude": lon, "daily": "river_discharge,river_discharge_max", "forecast_days": 7, "timezone": "UTC"})
    current = weather_data.get("current") or {}; daily = flood_data.get("daily") or {}
    rain_mm_h = float(current.get("rain") or 0); river_value = float((daily.get("river_discharge") or [0])[0] or 0); level, reasons = risk(rain_mm_h, river_value)
    created = []
    if level in {"ALTO", "CRITICO"}:
        bucket = datetime.now(timezone.utc).strftime("%Y%m%d%H"); alert_id = f"risk-{station_id}-{bucket}"
        if not any(x.get("id") == alert_id for x in alerts):
            item = {"id": alert_id, "station_id": station_id, "timestamp": datetime.now(timezone.utc).isoformat(), "level": level, "alert_type": "RIESGO_CALCULADO", "official": False, "source": "Climate Alert Platform", "message": f"Riesgo {level}: {', '.join(reasons)}", "rain_mm_h": rain_mm_h, "river_level_m": river_value, "location": {"lat": lat, "lon": lon}}
            alerts.insert(0, item); created.append(item)
    official = senamhi_alerts()
    for item in official.get("alerts", []):
        alert_id = f"official-{item['id']}"
        if not any(x.get("id") == alert_id for x in alerts):
            stored = {**item, "id": alert_id, "alert_type": item.get("type", "AVISO_OFICIAL")}; alerts.insert(0, stored); created.append(stored)
    return jsonify({"checked_at": datetime.now(timezone.utc).isoformat(), "location": {"lat": lat, "lon": lon}, "risk": {"level": level, "rain_mm_h": rain_mm_h, "river_level_m": river_value, "reasons": reasons}, "official_alerts": official.get("alerts", []), "created_alerts": created})


@app.post("/measurements")
def create_measurement():
    data = request.get_json(force=True); station_id = str(data.get("station_id", "WEB-001")); rain_mm_h = float(data["rain_mm_h"]); river_level_m = float(data["river_level_m"]); level, reasons = risk(rain_mm_h, river_level_m)
    item = {"id": str(uuid4()), "station_id": station_id, "timestamp": data.get("timestamp", datetime.now(timezone.utc).isoformat()), "rain_mm_h": rain_mm_h, "river_level_m": river_level_m, "risk_level": level, "risk_reasons": reasons, "location": data.get("location", {})}; measurements.insert(0, item)
    if level in {"ALTO", "CRITICO"}: alerts.insert(0, {"id": str(uuid4()), "station_id": station_id, "timestamp": item["timestamp"], "level": level, "alert_type": "RIESGO_CALCULADO", "official": False, "source": "Climate Alert Platform", "message": f"Riesgo {level}: {', '.join(reasons)}"})
    return jsonify({"measurement": item}), 201


@app.get("/measurements")
def list_measurements():
    return jsonify({"items": measurements[:50]})


@app.get("/alerts")
def list_alerts():
    return jsonify({"items": alerts[:50]})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")))
