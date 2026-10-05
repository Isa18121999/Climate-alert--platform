from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import xml.etree.ElementTree as ET

OPEN_METEO_FORECAST = os.getenv("OPEN_METEO_FORECAST", "https://api.open-meteo.com/v1/forecast")
OPEN_METEO_FLOOD = os.getenv("OPEN_METEO_FLOOD", "https://flood-api.open-meteo.com/v1/flood")
GDELT_DOC = os.getenv("GDELT_DOC", "https://api.gdeltproject.org/api/v2/doc/doc")
NEWS_PROVIDER = os.getenv("NEWS_PROVIDER", "gdelt").lower()
NEWS_API_URL = os.getenv("NEWS_API_URL", "https://newsapi.org/v2/everything")
NEWS_API_KEY = os.getenv("NEWS_API_KEY")
GOOGLE_NEWS_RSS = os.getenv("GOOGLE_NEWS_RSS", "https://news.google.com/rss/search")


def _get_json(url: str, params: dict, timeout: int = 8) -> dict:
    query = urlencode({k: v for k, v in params.items() if v is not None})
    request = Request(f"{url}?{query}", headers={"User-Agent": "propuesta1-alerta-temprana/1.0"})
    with urlopen(request, timeout=timeout) as response:  # nosec B310 - endpoint is configurable and HTTPS by default
        return json.loads(response.read().decode("utf-8"))


def weather(lat: float, lon: float) -> dict:
    data = _get_json(
        OPEN_METEO_FORECAST,
        {
            "latitude": lat,
            "longitude": lon,
            "current": "temperature_2m,relative_humidity_2m,precipitation,rain,showers,weather_code,wind_speed_10m",
            "hourly": "rain,precipitation_probability",
            "forecast_days": 1,
            "timezone": "UTC",
        },
    )
    return {
        "source": "Open-Meteo",
        "source_url": OPEN_METEO_FORECAST,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "location": {"lat": lat, "lon": lon},
        "current": data.get("current", {}),
        "hourly": data.get("hourly", {}),
    }


def flood(lat: float, lon: float) -> dict:
    data = _get_json(
        OPEN_METEO_FLOOD,
        {
            "latitude": lat,
            "longitude": lon,
            "daily": "river_discharge,river_discharge_mean,river_discharge_max",
            "forecast_days": 7,
            "timezone": "UTC",
        },
    )
    return {
        "source": "Open-Meteo Flood API / GloFAS",
        "source_url": OPEN_METEO_FLOOD,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "location": {"lat": lat, "lon": lon},
        "daily": data.get("daily", {}),
        "daily_units": data.get("daily_units", {}),
    }


def _gdelt_live_rss(query: str) -> dict:
    # Feed de noticias de GDELT actualizado continuamente.
    url = os.getenv("GDELT_GAL_RSS", "https://data.gdeltproject.org/gdeltv3/gal/feed.rss")
    request = Request(
        url,
        headers={"User-Agent": "ClimateAlertPlatform/1.0"},
    )
    with urlopen(request, timeout=8) as response:
        root = ET.fromstring(response.read())

    articles = []
    for item in root.findall(".//item"):
        title = item.findtext("title") or ""
        link = item.findtext("link") or ""
        source = item.find("source")
        source_name = source.text if source is not None else None
        haystack = (title + " " + link + " " + (source_name or "")).lower()

        peru_markers = ("perú", "peru", ".pe/", ".pe", "lima", "piura", "arequipa", "trujillo", "cusco")
        if not any(term in haystack for term in peru_markers):
            continue

        articles.append({
            "title": title,
            "url": link,
            "domain": source_name,
            "language": "es",
            "seendate": item.findtext("pubDate"),
            "socialimage": None,
        })
        if len(articles) >= 20:
            break

    return {
        "source": "GDELT Live RSS",
        "source_url": url,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "query": query,
        "articles": articles,
        "source_update_note": "Noticias nacionales recientes desde el feed de GDELT.",
    }


def _google_news_rss(query: str) -> dict:
    params = {
        "q": query,
        "hl": "es-419",
        "gl": "PE",
        "ceid": "PE:es-419",
    }
    query_string = urlencode(params)
    url = f"{GOOGLE_NEWS_RSS}?{query_string}"
    request = Request(
        url,
        headers={"User-Agent": "propuesta1-alerta-temprana/1.0"},
    )
    with urlopen(request, timeout=10) as response:
        root = ET.fromstring(response.read())

    articles = []
    for item in root.findall(".//item"):
        title = item.findtext("title") or ""
        link = item.findtext("link") or ""
        pub_date = item.findtext("pubDate")
        source = item.find("source")
        source_name = source.text if source is not None else None
        if not title or not link:
            continue
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

    return {
        "source": "Google News RSS",
        "source_url": url,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "query": query,
        "articles": articles,
        "source_update_note": "Respaldo de noticias mediante Google News RSS para mantener visible información reciente cuando GDELT no responde.",
    }


def news(query: str = "Perú") -> dict:
    errors = []

    # Priorizar el feed en vivo: evita el 429 frecuente de GDELT DOC.
    try:
        live = _gdelt_live_rss(query)
        if live.get("articles"):
            return live
        errors.append("GDELT Live RSS sin resultados")
    except Exception as exc:
        errors.append(f"GDELT Live RSS: {exc}")

    try:
        return _google_news_rss(query)
    except Exception as exc:
        errors.append(f"Google News RSS: {exc}")

    try:
        data = _get_json(
            GDELT_DOC,
            {
                "query": query,
                "mode": "ArtList",
                "format": "json",
                "maxrecords": 20,
                "sort": "HybridRel",
                "timespan": "24h",
                "sourcelang": "Spanish",
            },
            timeout=8,
        )
        articles = [{
            "title": item.get("title"),
            "url": item.get("url"),
            "domain": item.get("domain"),
            "language": item.get("language"),
            "seendate": item.get("seendate"),
            "socialimage": item.get("socialimage"),
        } for item in data.get("articles", [])]
        if articles:
            return {
                "source": "GDELT DOC 2.0",
                "source_url": GDELT_DOC,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "query": query,
                "articles": articles,
                "source_update_note": "GDELT DOC como respaldo.",
            }
        errors.append("GDELT DOC sin resultados")
    except Exception as exc:
        errors.append(f"GDELT DOC: {exc}")

    return {
        "source": "News fallback",
        "source_url": GDELT_DOC,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "query": query,
        "articles": [],
        "source_update_note": "No se pudo consultar ninguna fuente: " + "; ".join(errors),
    }
