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
    # GDELT Article List RSS is a rolling live feed updated every minute.
    # We filter the feed locally because the DOC JSON endpoint may rate-limit bursts.
    url = os.getenv("GDELT_GAL_RSS", "https://data.gdeltproject.org/gdeltv3/gal/feed.rss")
    request = Request(
        url,
        headers={"User-Agent": "propuesta1-alerta-temprana/1.0"},
    )
    with urlopen(request, timeout=10) as response:
        root = ET.fromstring(response.read())

    terms = [x.strip().lower() for x in query.replace(",", " ").split() if x.strip()]
    articles = []
    for item in root.findall(".//item"):
        title = item.findtext("title") or ""
        link = item.findtext("link") or ""
        source = item.find("source")
        source_name = source.text if source is not None else None
        haystack = title.lower()
        link_lower = link.lower()
        climate_terms = (
            "lluvia", "lluvias", "precipit", "inund", "desborde",
            "huaico", "huayco", "tormenta", "caudal", "quebrada",
            "río", "rio", "el niño", "el nino"
        )
        peru_terms = ("peru", "perú", "senamhi", ".pe/", ".pe")
        has_climate = any(term in haystack for term in climate_terms)
        has_peru = any(
            term in haystack or term in link_lower or term in (source_name or "").lower()
            for term in peru_terms
        )
        if not has_climate or not has_peru:
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
        "source": "GDELT Article List RSS (fallback)",
        "source_url": url,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "query": query,
        "articles": articles,
        "source_update_note": "Fallback a GDELT Article List RSS. El feed tiene una ventana móvil de aproximadamente 15 minutos y se actualiza cada 60 segundos.",
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


def news(query: str = "Peru inundación lluvias El Niño") -> dict:
    errors = []

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
                "sourcelang": "spanish",
            },
            timeout=10,
        )
        articles = []
        for item in data.get("articles", []):
            articles.append(
                {
                    "title": item.get("title"),
                    "url": item.get("url"),
                    "domain": item.get("domain"),
                    "language": item.get("language"),
                    "seendate": item.get("seendate"),
                    "socialimage": item.get("socialimage"),
                }
            )
        if articles:
            return {
                "source": "GDELT DOC 2.0",
                "source_url": GDELT_DOC,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "query": query,
                "articles": articles,
                "source_update_note": "GDELT se utiliza como fuente principal de monitoreo de noticias.",
            }
        errors.append("GDELT sin resultados")
    except Exception as exc:
        errors.append(f"GDELT: {exc}")

    try:
        return _google_news_rss(query)
    except Exception as exc:
        errors.append(f"Google News RSS: {exc}")

    try:
        fallback = _gdelt_live_rss(query)
        fallback["source_update_note"] = (
            "Respaldo final de GDELT Article List RSS. "
            + "; ".join(errors)
        )
        return fallback
    except Exception as exc:
        errors.append(f"GDELT RSS: {exc}")

    return {
        "source": "News fallback",
        "source_url": GDELT_DOC,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "query": query,
        "articles": [],
        "source_update_note": "No fue posible consultar las fuentes de noticias: " + "; ".join(errors),
    }
