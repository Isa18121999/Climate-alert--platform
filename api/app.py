from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from uuid import uuid4
from urllib.parse import urlparse, urljoin

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

# Fuentes permitidas: únicamente medios peruanos y fuentes oficiales peruanas.
PERU_MEDIA_DOMAINS = (
    "rpp.pe", "elcomercio.pe", "larepublica.pe", "andina.pe", "gestion.pe", "peru21.pe",
    "atv.pe", "tvperu.gob.pe", "canaln.pe", "americatv.com.pe", "senamhi.gob.pe", "web2.senamhi.gob.pe",
    "gob.pe", "indeci.gob.pe", "mtc.gob.pe", "cultura.gob.pe",
)

# Una noticia entra solamente si trata un fenómeno/alerta climático concreto.
CLIMATE_TERMS = (
    "alerta", "aviso meteorológico", "aviso meteorologico", "lluvia", "lluvias", "precipit",
    "inund", "desborde", "huaico", "huayco", "tormenta", "crecida", "caudal", "quebrada",
    "deslizamiento", "río", "rio", "senamhi", "ciclón", "ciclon", "meteorológ", "meteorolog",
    "temperatura extrema", "ola de calor", "oleaje", "granizo", "helada", "friaje", "viento fuerte",
    "vientos fuertes", "fenómeno el niño", "fenomeno el nino", "el niño costero", "el nino costero",
    "hidrológ", "hidrolog", "precipitaciones intensas", "lluvias intensas", "lluvia extrema",
)

# Bloqueo explícito de contenido que no pertenece a Climate Alert.
GENERIC_TERMS = (
    "horóscopo", "horoscopo", "deportes", "entretenimiento", "farándula", "farandula", "informativa",
    "elecciones", "votación", "votacion", "partido", "fútbol", "futbol", "congreso", "candidato",
    "candidata", "campaña electoral", "espectáculo", "espectaculo", "celebridades",
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


def _news_severity(title: str, description: str = "") -> str:
    text = f"{title} {description}".lower()
    if any(term in text for term in (
        "desborde", "inundación", "inundacion", "huaico", "huayco", "evacuación", "evacuacion",
        "damnificados", "afectados", "emergencia", "río se desborda", "rio se desborda",
    )):
        return "CRÍTICA"
    if any(term in text for term in (
        "lluvia extrema", "lluvias intensas", "precipitaciones intensas", "alerta", "aviso meteorológico",
        "aviso meteorologico", "activación de quebrada", "activacion de quebrada", "caudal", "crecida",
        "tormenta", "ciclón", "ciclon", "fenómeno el niño", "fenomeno el nino", "el niño costero",
        "el nino costero", "viento fuerte", "vientos fuertes", "oleaje",
    )):
        return "ALTA"
    if any(term in text for term in ("lluvia", "lluvias", "precipitación", "precipitacion", "llovizna")):
        return "MEDIA"
    return "INFORMATIVA"


def _add_article(articles: list[dict], seen: set[str], title: str, link: str, source_label: str,
                 description: str = "", pub_date: str | None = None, category: str = "") -> None:
    title = BeautifulSoup(title or "", "html.parser").get_text(" ", strip=True)
    description = BeautifulSoup(description or "", "html.parser").get_text(" ", strip=True)
    link = link.strip()
    if not title or not link or not _allowed_peru_source(link):
        return
    if not _is_climate_article(title, description, category):
        return
    severity = _news_severity(title, description)
    if severity == "INFORMATIVA":
        return
    key = link.lower().split("#", 1)[0]
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
        "published_at": pub_date,
        "description": description,
        "summary": description[:500],
        "socialimage": None,
        "country": "PE",
        "region": "Perú",
        "category": "Clima",
        "severity": severity,
    })


def _parse_tolerant_feed(content: bytes, source_label: str, articles: list[dict], seen: set[str]) -> None:
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


def _parse_source_page(content: bytes, page_url: str, source_label: str,
                       articles: list[dict], seen: set[str]) -> None:
    soup = BeautifulSoup(content, "html.parser")
    for anchor in soup.find_all("a", href=True):
        title = anchor.get_text(" ", strip=True)
        href = urljoin(page_url, anchor.get("href", "").strip())
        _add_article(articles, seen, title, href, source_label)
        if len(articles) >= 40:
            break


def _fetch(url: str, timeout: int = 6) -> bytes:
    r = requests.get(url, timeout=timeout, headers={
        "User-Agent": "ClimateAlertPlatform/1.0 (+academic-project)",
        "Accept-Language": "es-PE,es;q=0.9",
    })
    r.raise_for_status()
    return r.content


def peruvian_climate_rss_news() -> list[dict]:
    # Fuentes periodísticas peruanas + páginas oficiales de SENAMHI.
    sources = [
        ("SENAMHI", "https://www.senamhi.gob.pe/?p=prediccion", None),
        ("SENAMHI", "https://www.senamhi.gob.pe/?p=fenomeno-el-nino", None),
        ("SENAMHI Avisos", "https://www.senamhi.gob.pe/?p=avisos", None),
        ("RPP", "https://rpp.pe/rss-titulares.xml", "https://rpp.pe/fenomenoelnino"),
        ("El Comercio", "https://elcomercio.pe/arc/outboundfeeds/rss/category/peru/?outputType=xml", "https://elcomercio.pe/noticias/senamhi/"),
        ("El Comercio Lima", "https://elcomercio.pe/arc/outboundfeeds/rss/category/lima/?outputType=xml", "https://elcomercio.pe/noticias/senamhi/"),
    ]
    articles: list[dict] = []
    seen: set[str] = set()

    for source_label, feed_or_page, fallback_page in sources:
        try:
            content = _fetch(feed_or_page)
            if feed_or_page.endswith(".xml"):
                _parse_tolerant_feed(content, source_label, articles, seen)
            else:
                _parse_source_page(content, feed_or_page, source_label, articles, seen)
        except Exception as exc:
            print(f"NEWS {source_label} {feed_or_page}: {exc}")

        if fallback_page and len(articles) < 10:
            try:
                content = _fetch(fallback_page)
                _parse_source_page(content, fallback_page, source_label, articles, seen)
            except Exception as exc:
                print(f"NEWS FALLBACK {source_label}: {exc}")

        if len(articles) >= 40:
            break

    def sort_key(item: dict):
        value = item.get("published_at") or item.get("seendate") or ""
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except Exception:
            try:
                from email.utils import parsedate_to_datetime
                return parsedate_to_datetime(value).timestamp()
            except Exception:
                return 0

    articles.sort(key=sort_key, reverse=True)
    return articles[:20]


def risk(rain: float, river: float) -> tuple[str, list[str]]:
    reasons = []
    if rain >= 50: reasons.append("lluvia >= 50 mm/h")
    elif rain >= 35: reasons.append("lluvia >= 35 mm/h")
    elif rain >= 20: reasons.append("lluvia >= 20 mm/h")
    if river >= 5: reasons.append("nivel de río >= 5 m")
    elif river >= 4: reasons.append("nivel de río >= 4 m")
    elif river >= 3: reasons.append("nivel de río >= 3 m")
    if rain >= 50 or river >= 5: return "CRITICO", reasons
    if rain >= 35 or river >= 4 or len(reasons) >= 2: return "ALTO", reasons
    if rain >= 20 or river >= 3: return "MEDIO", reasons
    return "BAJO", reasons


@app.get("/")
def health():
    return jsonify({"status": "ok", "service": "climate-alert-platform-api"})


@app.get("/health")
def health_check():
    return jsonify({"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat(), "provider": "Render", "environment": "demo"})


@app.get("/weather")
def weather():
    lat = float(request.args.get("lat", "-5.1945")); lon = float(request.args.get("lon", "-80.6328"))
    data = get_json(OPEN_METEO_FORECAST, {"latitude": lat, "longitude": lon, "current": "temperature_2m,relative_humidity_2m,precipitation,rain,wind_speed_10m", "forecast_days": 1, "timezone": "UTC"})
    return jsonify({"source": "Open-Meteo Weather API", "fetched_at": datetime.now(timezone.utc).isoformat(), "location": {"lat": lat, "lon": lon}, **data})


@app.get("/flood")
def flood():
    lat = float(request.args.get("lat", "-5.1945")); lon = float(request.args.get("lon", "-80.6328"))
    data = get_json(OPEN_METEO_FLOOD, {"latitude": lat, "longitude": lon, "daily": "river_discharge,river_discharge_max", "forecast_days": 7, "timezone": "UTC"})
    return jsonify({"source": "Open-Meteo Flood API / GloFAS", "fetched_at": datetime.now(timezone.utc).isoformat(), "location": {"lat": lat, "lon": lon}, **data})


@app.get("/news")
def news():
    query = request.args.get("q", "Perú alerta climática lluvias inundaciones desbordes huaicos SENAMHI")
    articles = peruvian_climate_rss_news()
    return jsonify({
        "source": "SENAMHI + medios peruanos (RPP y El Comercio)",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "query": query,
        "articles": articles,
        "source_update_note": "Solo noticias climáticas relevantes de Perú. Se excluyen internacionales, genéricas, políticas, deportes, entretenimiento y categoría Informativa."
            if articles else "No se encontraron noticias climáticas válidas en las fuentes peruanas configuradas."
    })


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
def list_measurements(): return jsonify({"items": measurements[:50]})


@app.get("/alerts")
def list_alerts(): return jsonify({"items": alerts[:50]})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")))
