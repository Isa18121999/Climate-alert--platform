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


def _google_news_rss(query: str) -> dict:
    # Public RSS search feed; used as a fallback when GDELT rate-limits requests.
    params = {
        "q": f"{query} when:1h",
        "hl": "es-419",
        "gl": "PE",
        "ceid": "PE:es-419",
    }
    xml_url = GOOGLE_NEWS_RSS
    query_string = urlencode(params)
    request = Request(
        f"{xml_url}?{query_string}",
        headers={"User-Agent": "propuesta1-alerta-temprana/1.0"},
    )
    with urlopen(request, timeout=10) as response:
        root = ET.fromstring(response.read())

    articles = []
    for item in root.findall(".//item")[:20]:
        source = item.find("source")
        articles.append({
            "title": item.findtext("title"),
            "url": item.findtext("link"),
            "domain": source.text if source is not None else None,
            "language": "es",
            "seendate": item.findtext("pubDate"),
            "socialimage": None,
        })

    return {
        "source": "Google News RSS (fallback)",
        "source_url": f"{xml_url}?{query_string}",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "query": query,
        "articles": articles,
        "source_update_note": "Fuente alternativa activada cuando GDELT responde con limitación de solicitudes (HTTP 429).",
    }


def news(query: str = "Peru inundación lluvias El Niño") -> dict:
    if NEWS_PROVIDER == "newsapi" and NEWS_API_KEY:
        data = _get_json(
            NEWS_API_URL,
            {
                "q": query,
                "from": datetime.now(timezone.utc).date().isoformat(),
                "sortBy": "publishedAt",
                "language": "es",
                "pageSize": 20,
            },
        )
        articles = [
            {
                "title": x.get("title"),
                "url": x.get("url"),
                "domain": (x.get("source") or {}).get("name"),
                "language": "es",
                "seendate": x.get("publishedAt"),
                "socialimage": x.get("urlToImage"),
            }
            for x in data.get("articles", [])
        ]
        return {
            "source": "News API",
            "source_url": NEWS_API_URL,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "query": query,
            "articles": articles,
            "source_update_note": "La interfaz consulta cada minuto; la disponibilidad y latencia dependen del plan y de las fuentes indexadas.",
        }

    try:
        data = _get_json(
            GDELT_DOC,
            {
                "query": query,
                "mode": "ArtList",
                "format": "json",
                "maxrecords": 20,
                "sort": "HybridRel",
                "timespan": "15min",
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
        return {
            "source": "GDELT DOC 2.0",
            "source_url": GDELT_DOC,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "query": query,
            "articles": articles,
            "source_update_note": "GDELT se utiliza como fuente principal de monitoreo de noticias.",
        }
    except HTTPError as exc:
        if exc.code == 429:
            return _google_news_rss(query)
        raise
