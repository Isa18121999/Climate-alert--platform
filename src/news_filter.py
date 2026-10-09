"""Strict Peru climate-news filtering helpers."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable
from urllib.parse import urlparse

# ============================================================
# TÉRMINOS CLIMÁTICOS PERMITIDOS
# ============================================================
# Se utilizan para comprobar que una noticia realmente trata sobre
# clima, meteorología, hidrología o una emergencia relacionada.
PERU_CLIMATE_TERMS = (
    "lluvia", "lluvias", "precipit", "inund", "desborde", "huaico", "huayco",
    "tormenta", "crecida", "caudal", "quebrada", "deslizamiento", "rio", "río",
    "senamhi", "fenomeno el nino", "fenómeno el niño", "el nino costero", "el niño costero",
    "ciclon", "ciclón", "meteorolog", "meteorológ", "temperatura", "oleaje", "granizo",
    "helada", "friaje", "viento fuerte", "vientos fuertes", "temperatura extrema", "enfen",
)

# ============================================================
# SEÑALES QUE IDENTIFICAN A PERÚ
# ============================================================
# Incluye el país, regiones y ciudades peruanas. También se consideran
# instituciones oficiales como SENAMHI e INDECI.
PERU_SIGNALS = (
    "perú", "peru", "senamhi", "indeci", "lima", "callao", "piura", "tumbes", "chiclayo",
    "lambayeque", "la libertad", "trujillo", "ancash", "áncash", "huánuco", "huanuco",
    "pasco", "junín", "junin", "ica", "arequipa", "moquegua", "tacna", "cusco", "cuzco",
    "puno", "ayacucho", "apurímac", "apurimac", "huancavelica", "amazonas", "cajamarca",
    "san martín", "san martin", "ucayali", "madre de dios", "loreto",
)

# ============================================================
# CONTENIDO GENÉRICO BLOQUEADO
# ============================================================
# Estas palabras permiten descartar noticias que no corresponden al
# objetivo del proyecto, aunque provengan de un medio peruano.
GENERIC_TERMS = (
    "horoscopo", "horóscopo", "deportes", "entretenimiento", "farándula", "farandula",
    "informativa", "política", "politica", "elecciones", "congreso", "partido político",
    "partido politico", "ideológica", "ideologica", "seguridad y habitación",
)

# ============================================================
# DOMINIOS DE MEDIOS PERUANOS APROBADOS
# ============================================================
# La lista limita las noticias a fuentes periodísticas peruanas conocidas.
ALLOWED_PERU_DOMAINS = (
    ".rpp.pe", "rpp.pe", ".elcomercio.pe", "elcomercio.pe", ".larepublica.pe", "larepublica.pe",
    ".andina.pe", "andina.pe", ".gestion.pe", "gestion.pe", ".peru21.pe", "peru21.pe",
)


def is_peruvian_climate_article(article: dict[str, Any]) -> bool:
    """Determina si una noticia cumple los criterios de Perú y clima."""
    # Se combinan título, descripción, resumen y categoría para tener
    # más información disponible antes de aceptar o rechazar la noticia.
    text = " ".join(str(article.get(k) or "") for k in ("title", "description", "summary", "category")).lower()
    if not any(term in text for term in PERU_CLIMATE_TERMS):
        return False

    # Se obtiene tanto el nombre de la fuente como su dominio web.
    source = str(article.get("source") or article.get("publisher") or "").lower()
    url = str(article.get("url") or article.get("link") or "")
    host = urlparse(url).netloc.lower()
    allowed = any(host == d.lstrip(".") or host.endswith(d) for d in ALLOWED_PERU_DOMAINS)
    named = any(name in source for name in ("rpp", "el comercio", "la república", "la republica", "andina", "gestión", "gestion", "perú21", "peru21", "senamhi"))

    # Approved Peruvian media/SENAMHI is itself a Peru signal. This avoids
    # dropping valid Peru climate headlines that omit the word "Perú".
    peru_signal = any(term in text for term in PERU_SIGNALS) or allowed or named
    if not peru_signal:
        return False

    # Se descarta cualquier contenido clasificado como genérico.
    if any(term in text for term in GENERIC_TERMS):
        return False
    return allowed or named


def filter_peruvian_climate_articles(articles: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Filtra noticias, elimina duplicados y añade metadatos de Perú."""
    result, seen = [], set()
    for article in articles:
        if not is_peruvian_climate_article(article):
            continue
        url = str(article.get("url") or article.get("link") or "")
        title = str(article.get("title") or "").strip()
        # La URL identifica normalmente una noticia de forma única; si no
        # existe, se utiliza el título como identificador alternativo.
        key = url or title.lower()
        if not key or key in seen:
            continue
        seen.add(key)
        item = dict(article)
        item["country"], item["region"] = "PE", "Perú"
        result.append(item)
    return result


def sort_newest_first(articles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Ordena las noticias desde la publicación más reciente."""
    def stamp(article: dict[str, Any]) -> float:
        # Se prueban distintos nombres porque cada fuente puede devolver
        # la fecha de publicación con una clave diferente.
        value = article.get("published_at") or article.get("published") or article.get("date")
        if not value:
            return 0.0
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except Exception:
            # Una fecha no válida se coloca al final de la lista.
            return 0.0
    return sorted(articles, key=stamp, reverse=True)
