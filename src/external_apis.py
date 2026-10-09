from __future__ import annotations

import html
import json
import os
import re
from datetime import datetime, timezone
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

# ============================================================
# FUENTES METEOROLÓGICAS E HIDROLÓGICAS
# ============================================================
# Las URLs pueden configurarse mediante variables de entorno para
# facilitar el despliegue en AWS o Render.
OPEN_METEO_FORECAST = os.getenv("OPEN_METEO_FORECAST", "https://api.open-meteo.com/v1/forecast")
OPEN_METEO_FLOOD = os.getenv("OPEN_METEO_FLOOD", "https://flood-api.open-meteo.com/v1/flood")

# Términos necesarios para considerar que una noticia trata un fenómeno climático.
PERU_CLIMATE_TERMS = (
    "lluvia", "lluvias", "precipit", "inund", "desborde", "huaico", "huayco",
    "tormenta", "crecida", "caudal", "quebrada", "deslizamiento", "río", "rio", "senamhi",
    "fenómeno el niño", "fenomeno el nino", "el niño costero", "el nino costero", "ciclón", "ciclon",
    "meteorológ", "meteorolog", "temperatura", "oleaje", "granizo", "helada", "friaje",
    "viento fuerte", "vientos fuertes", "enfen",
)

# Regiones, ciudades e instituciones que funcionan como señales de Perú.
PERU_SIGNALS = (
    "perú", "peru", "senamhi", "indeci", "lima", "callao", "piura", "tumbes", "chiclayo",
    "lambayeque", "la libertad", "trujillo", "ancash", "áncash", "huánuco", "huanuco", "pasco",
    "junín", "junin", "ica", "arequipa", "moquegua", "tacna", "cusco", "cuzco", "puno",
    "ayacucho", "apurímac", "apurimac", "huancavelica", "amazonas", "cajamarca", "san martín",
    "san martin", "ucayali", "madre de dios", "loreto",
)

# Contenido que debe excluirse aunque proceda de un medio peruano.
GENERIC_TERMS = (
    "horóscopo", "horoscopo", "deportes", "entretenimiento", "farándula", "farandula", "informativa",
    "política", "politica", "elecciones", "congreso", "partido político", "partido politico",
    "ideológica", "ideologica", "seguridad y habitación",
)

# Fuentes periodísticas peruanas aprobadas para la sección de noticias.
PERU_MEDIA = ("rpp.pe", "elcomercio.pe", "larepublica.pe", "andina.pe", "gestion.pe", "peru21.pe")


def _get_json(url: str, params: dict, timeout: int = 8) -> dict:
    """Realiza una petición GET y convierte la respuesta JSON en diccionario."""
    query = urlencode({k: v for k, v in params.items() if v is not None})
    request = Request(f"{url}?{query}", headers={"User-Agent": "ClimateAlertPlatform/1.0"})
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def weather(lat: float, lon: float) -> dict:
    """Obtiene las condiciones meteorológicas actuales y horarias."""
    data = _get_json(OPEN_METEO_FORECAST, {
        "latitude": lat, "longitude": lon,
        "current": "temperature_2m,relative_humidity_2m,precipitation,rain,showers,weather_code,wind_speed_10m",
        "hourly": "rain,precipitation_probability", "forecast_days": 1, "timezone": "UTC",
    })
    return {"source": "Open-Meteo", "source_url": OPEN_METEO_FORECAST,
            "fetched_at": datetime.now(timezone.utc).isoformat(), "location": {"lat": lat, "lon": lon},
            "current": data.get("current", {}), "hourly": data.get("hourly", {})}


def flood(lat: float, lon: float) -> dict:
    """Obtiene información hidrológica diaria para la ubicación indicada."""
    data = _get_json(OPEN_METEO_FLOOD, {
        "latitude": lat, "longitude": lon,
        "daily": "river_discharge,river_discharge_mean,river_discharge_max",
        "forecast_days": 7, "timezone": "UTC",
    })
    return {"source": "Open-Meteo Flood API / GloFAS", "source_url": OPEN_METEO_FLOOD,
            "fetched_at": datetime.now(timezone.utc).isoformat(), "location": {"lat": lat, "lon": lon},
            "daily": data.get("daily", {}), "daily_units": data.get("daily_units", {})}


def _allowed_peru_source(url: str, source: str) -> bool:
    """Comprueba que la URL o fuente pertenece a un medio peruano permitido."""
    host = urlparse(url).netloc.lower()
    source = source.lower()
    return any(host == d or host.endswith("." + d) for d in PERU_MEDIA) or any(d in source for d in PERU_MEDIA)


def _clean_text(value: str) -> str:
    """Limpia etiquetas HTML y espacios repetidos de un texto RSS."""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", value or "")).strip()


def _rss_image(item: ET.Element, description: str = "") -> str | None:
    """Extract an RSS image without trusting arbitrary HTML as the image itself."""
    # Se revisan etiquetas estándar de RSS/Media RSS para obtener la imagen.
    for child in item.iter():
        tag = child.tag.split("}")[-1].lower() if isinstance(child.tag, str) else ""
        if tag in {"content", "thumbnail", "image", "enclosure"}:
            url = (child.attrib.get("url") or child.attrib.get("href") or "").strip()
            if url.startswith(("https://", "http://")):
                return html.unescape(url)

    # Como respaldo, se busca una imagen dentro de la descripción HTML.
    match = re.search(r'<img[^>]+src=["\'](https?://[^"\']+)["\']', description or "", re.I)
    return html.unescape(match.group(1)) if match else None


def _is_climate_item(title: str, description: str = "", category: str = "", source: str = "", url: str = "") -> bool:
    """Determina si un elemento RSS cumple los criterios estrictos del proyecto."""
    text = f"{title} {description} {category}".lower()
    if not any(term in text for term in PERU_CLIMATE_TERMS):
        return False

    # Una fuente peruana confiable cuenta como señal de ubicación nacional.
    trusted_source = _allowed_peru_source(url, source) or "senamhi" in source.lower()
    peru_signal = any(term in text for term in PERU_SIGNALS) or trusted_source
    if not peru_signal:
        return False
    return not any(term in text for term in GENERIC_TERMS)


def _significance(title: str, description: str = "") -> str:
    """Clasifica la relevancia de una noticia según el fenómeno mencionado."""
    text = f"{title} {description}".lower()
    if re.search(r"desborde|inundaci[oó]n|huaico|huayco|r[ií]o .*desborda|emergencia|evacuaci[oó]n|damnificad", text):
        return "CRITICA"
    if re.search(r"lluvia extrema|lluvias intensas|precipitaciones intensas|alerta|activaci[oó]n de quebrada|caudal|crecida|tormenta|cicl[oó]n|el ni[nñ]o costero|fen[oó]meno el ni[nñ]o|pron[oó]stico", text):
        return "ALTA"
    if re.search(r"lluvia|lluvias|precipitaci[oó]n|meteorolog|temperatura", text):
        return "MEDIA"
    return "INFORMATIVA"


def _peruvian_climate_rss(query: str) -> dict:
    """Consulta RSS de medios peruanos y devuelve solo noticias climáticas válidas."""
    feeds = [
        ("RPP", "https://rpp.pe/rss-titulares.xml"),
        ("El Comercio", "https://elcomercio.pe/arc/outboundfeeds/rss/category/peru/?outputType=xml"),
        ("El Comercio Lima", "https://elcomercio.pe/arc/outboundfeeds/rss/category/lima/?outputType=xml"),
    ]
    articles, seen = [], set()
    errors = []

    # Cada fuente se procesa de forma independiente para que un fallo
    # de un RSS no impida consultar los demás medios.
    for source_label, feed_url in feeds:
        try:
            request = Request(feed_url, headers={"User-Agent": "ClimateAlertPlatform/1.0 (+academic-project)"})
            with urlopen(request, timeout=10) as response:
                root = ET.fromstring(response.read())

            # Cada <item> representa una noticia del feed RSS.
            for item in root.findall(".//item"):
                title = _clean_text(item.findtext("title") or "")
                link = (item.findtext("link") or "").strip()
                description_raw = item.findtext("description") or ""
                description = _clean_text(description_raw)
                pub_date = item.findtext("pubDate")
                category = " ".join(x.text or "" for x in item.findall("category"))

                # Se aplican primero los filtros de contenido y fuente.
                if not title or not link or not _is_climate_item(title, description, category, source_label, link):
                    continue
                if not _allowed_peru_source(link, source_label):
                    continue

                # Evita mostrar dos veces la misma noticia si aparece en más de un feed.
                key = link.lower()
                if key in seen:
                    continue
                seen.add(key)

                articles.append({
                    "title": title, "url": link, "domain": source_label, "source": source_label,
                    "language": "es", "seendate": pub_date, "published_at": pub_date,
                    "description": description, "summary": description,
                    "socialimage": _rss_image(item, description_raw),
                    "image_url": _rss_image(item, description_raw),
                    "country": "PE", "region": "Perú",
                    "category": category or "Clima", "severity": _significance(title, description),
                })
                if len(articles) >= 20:
                    break
        except Exception as exc:
            errors.append(f"{source_label}: {exc}")
        if len(articles) >= 20:
            break

    # Las noticias más recientes aparecen primero.
    articles.sort(key=lambda a: str(a.get("published_at") or ""), reverse=True)
    return {
        "source": "RSS medios peruanos", "source_url": "https://rpp.pe/rss-titulares.xml",
        "fetched_at": datetime.now(timezone.utc).isoformat(), "query": query,
        "articles": articles[:20],
        "source_update_note": "Solo noticias climáticas relevantes de Perú. Se exige fenómeno climático/emergencia y una señal de Perú o una fuente peruana aprobada. Se excluyen noticias políticas, internacionales, genéricas y de categoría Informativa.",
        "warnings": errors,
    }


def news(query: str = "Perú alerta climática lluvias inundaciones desbordes huaicos SENAMHI El Niño Costero") -> dict:
    """Return only relevant Peru climate/emergency news from approved Peruvian RSS feeds."""
    # Se delega la consulta al procesador RSS y se conserva una respuesta
    # informativa incluso cuando temporalmente no hay artículos disponibles.
    result = _peruvian_climate_rss(query)
    if result.get("articles"):
        return result
    result["source_update_note"] = (
        "No hay noticias climáticas relevantes de Perú disponibles en los RSS consultados en este momento. "
        "No se muestran noticias internacionales, políticas, genéricas ni de categoría Informativa."
    )
    return result
