"""Strict Peru climate-news filtering helpers."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable
from urllib.parse import urlparse

PERU_CLIMATE_TERMS = ("alerta", "lluvia", "lluvias", "precipit", "inund", "desborde", "huaico", "huayco", "tormenta", "crecida", "caudal", "quebrada", "deslizamiento", "rio", "río", "senamhi", "fenomeno el nino", "fenómeno el niño", "ciclon", "ciclón", "meteorolog", "meteorológ", "temperatura extrema", "oleaje", "granizo", "helada", "friaje")
GENERIC_TERMS = ("horoscopo", "horóscopo", "deportes", "entretenimiento", "farándula", "farandula", "informativa")
ALLOWED_PERU_DOMAINS = (".rpp.pe", "rpp.pe", ".elcomercio.pe", "elcomercio.pe", ".larepublica.pe", "larepublica.pe", ".andina.pe", "andina.pe", ".gestion.pe", "gestion.pe", ".peru21.pe", "peru21.pe")


def is_peruvian_climate_article(article: dict[str, Any]) -> bool:
    text = " ".join(str(article.get(k) or "") for k in ("title", "description", "summary", "category")).lower()
    if not any(term in text for term in PERU_CLIMATE_TERMS):
        return False
    if any(term in text for term in GENERIC_TERMS):
        return False
    source = str(article.get("source") or article.get("publisher") or "").lower()
    url = str(article.get("url") or article.get("link") or "")
    host = urlparse(url).netloc.lower()
    allowed = any(host == d.lstrip(".") or host.endswith(d) for d in ALLOWED_PERU_DOMAINS)
    named = any(name in source for name in ("rpp", "el comercio", "la república", "la republica", "andina", "gestión", "gestion", "perú21", "peru21"))
    return allowed or named


def filter_peruvian_climate_articles(articles: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    result, seen = [], set()
    for article in articles:
        if not is_peruvian_climate_article(article):
            continue
        url = str(article.get("url") or article.get("link") or "")
        title = str(article.get("title") or "").strip()
        key = url or title.lower()
        if not key or key in seen:
            continue
        seen.add(key)
        item = dict(article)
        item["country"], item["region"] = "PE", "Perú"
        result.append(item)
    return result


def sort_newest_first(articles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def stamp(article: dict[str, Any]) -> float:
        value = article.get("published_at") or article.get("published") or article.get("date")
        if not value:
            return 0.0
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except Exception:
            return 0.0
    return sorted(articles, key=stamp, reverse=True)
