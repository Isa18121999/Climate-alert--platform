from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

OPEN_METEO_FORECAST = os.getenv("OPEN_METEO_FORECAST", "https://api.open-meteo.com/v1/forecast")
OPEN_METEO_FLOOD = os.getenv("OPEN_METEO_FLOOD", "https://flood-api.open-meteo.com/v1/flood")

PERU_CLIMATE_TERMS = (
    "alerta", "lluvia", "lluvias", "precipit", "inund", "desborde", "huaico", "huayco",
    "tormenta", "crecida", "caudal", "quebrada", "deslizamiento", "río", "rio", "senamhi",
    "fenómeno el niño", "fenomeno el nino", "el niño costero", "el nino costero", "ciclón", "ciclon",
    "meteorológ", "meteorolog", "temperatura extrema", "oleaje", "granizo", "helada", "friaje",
)
GENERIC_TERMS = ("horóscopo", "horoscopo", "deportes", "entretenimiento", "farándula", "farandula", "informativa")
PERU_MEDIA = ("rpp.pe", "elcomercio.pe", "larepublica.pe", "andina.pe", "gestion.pe", "peru21.pe")


def _get_json(url: str, params: dict, timeout: int = 8) -> dict:
    query = urlencode({k: v for k, v in params.items() if v is not None})
    request = Request(f"{url}?{query}", headers={"User-Agent": "ClimateAlertPlatform/1.0"})
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def weather(lat: float, lon: float) -> dict:
    data = _get_json(OPEN_METEO_FORECAST, {
        "latitude": lat, "longitude": lon,
        "current": "temperature_2m,relative_humidity_2m,precipitation,rain,showers,weather_code,wind_speed_10m",
        "hourly": "rain,precipitation_probability", "forecast_days": 1, "timezone": "UTC",
    })
    return {"source": "Open-Meteo", "source_url": OPEN_METEO_FORECAST,
            "fetched_at": datetime.now(timezone.utc).isoformat(), "location": {"lat": lat, "lon": lon},
            "current": data.get("current", {}), "hourly": data.get("hourly", {})}


def flood(lat: float, lon: float) -> dict:
    data = _get_json(OPEN_METEO_FLOOD, {
        "latitude": lat, "longitude": lon,
        "daily": "river_discharge,river_discharge_mean,river_discharge_max",
        "forecast_days": 7, "timezone": "UTC",
    })
    return {"source": "Open-Meteo Flood API / GloFAS", "source_url": OPEN_METEO_FLOOD,
            "fetched_at": datetime.now(timezone.utc).isoformat(), "location": {"lat": lat, "lon": lon},
            "daily": data.get("daily", {}), "daily_units": data.get("daily_units", {})}


def _allowed_peru_source(url: str, source: str) -> bool:
    host = urlparse(url).netloc.lower()
    source = source.lower()
    return any(host == d or host.endswith("." + d) for d in PERU_MEDIA) or any(d in source for d in PERU_MEDIA)


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", value or "")).strip()


def _is_climate_item(title: str, description: str = "", category: str = "") -> bool:
    text = f"{title} {description} {category}".lower()
    return any(term in text for term in PERU_CLIMATE_TERMS) and not any(term in text for term in GENERIC_TERMS)


def _significance(title: str, description: str = "") -> str:
    text = f"{title} {description}".lower()
    if re.search(r"desborde|inundaci[oó]n|huaico|huayco|r[ií]o .*desborda|emergencia|evacuaci[oó]n|damnificad", text):
        return "CRITICA"
    if re.search(r"lluvia extrema|lluvias intensas|precipitaciones intensas|alerta|activaci[oó]n de quebrada|caudal|crecida|tormenta|cicl[oó]n|el ni[nñ]o costero|fen[oó]meno el ni[nñ]o|pron[oó]stico", text):
        return "ALTA"
    if re.search(r"lluvia|lluvias|precipitaci[oó]n|meteorolog|temperatura extrema", text):
        return "MEDIA"
    return "INFORMATIVA"


def _peruvian_climate_rss(query: str) -> dict:
    feeds = [
        ("RPP", "https://rpp.pe/rss-titulares.xml"),
        ("El Comercio", "https://elcomercio.pe/arc/outboundfeeds/rss/category/peru/?outputType=xml"),
        ("El Comercio Lima", "https://elcomercio.pe/arc/outboundfeeds/rss/category/lima/?outputType=xml"),
    ]
    articles, seen = [], set()
    errors = []
    for source_label, feed_url in feeds:
        try:
            request = Request(feed_url, headers={"User-Agent": "ClimateAlertPlatform/1.0 (+academic-project)"})
            with urlopen(request, timeout=10) as response:
                root = ET.fromstring(response.read())
            for item in root.findall(".//item"):
                title = _clean_text(item.findtext("title") or "")
                link = (item.findtext("link") or "").strip()
                description = _clean_text(item.findtext("description") or "")
                pub_date = item.findtext("pubDate")
                category = " ".join(x.text or "" for x in item.findall("category"))
                if not title or not link or not _is_climate_item(title, description, category):
                    continue
                if not _allowed_peru_source(link, source_label):
                    continue
                key = link.lower()
                if key in seen:
                    continue
                seen.add(key)
                articles.append({
                    "title": title, "url": link, "domain": source_label, "source": source_label,
                    "language": "es", "seendate": pub_date, "published_at": pub_date,
                    "description": description, "summary": description,
                    "socialimage": None, "country": "PE", "region": "Perú",
                    "category": category or "Clima", "severity": _significance(title, description),
                })
                if len(articles) >= 20:
                    break
        except Exception as exc:
            errors.append(f"{source_label}: {exc}")
        if len(articles) >= 20:
            break

    articles.sort(key=lambda a: str(a.get("published_at") or ""), reverse=True)
    return {
        "source": "RSS medios peruanos", "source_url": "https://rpp.pe/rss-titulares.xml",
        "fetched_at": datetime.now(timezone.utc).isoformat(), "query": query,
        "articles": articles[:20],
        "source_update_note": "Solo noticias climáticas de Perú. Se excluyen noticias internacionales, genéricas y de categoría Informativa.",
        "warnings": errors,
    }


def news(query: str = "Perú alerta climática lluvias inundaciones desbordes huaicos SENAMHI El Niño Costero") -> dict:
    """Return only Peru climate/emergency news from approved Peruvian RSS feeds."""
    result = _peruvian_climate_rss(query)
    if result.get("articles"):
        return result
    result["source_update_note"] = (
        "No hay noticias climáticas peruanas disponibles en los RSS consultados en este momento. "
        "No se muestran noticias internacionales, genéricas ni de categoría Informativa."
    )
    return result
