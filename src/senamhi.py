from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Iterable

import requests
from bs4 import BeautifulSoup

SENAMHI_ALERTS_URL = "https://web2.senamhi.gob.pe/?p=avisos"
SENAMHI_SHORT_TERM_RAIN_URL = "https://www.senamhi.gob.pe/servicios/main.php?dp=lima&p=aviso-24H"

MONTHS_ES = {
    "ene": 1, "enero": 1, "feb": 2, "febrero": 2, "mar": 3, "marzo": 3,
    "abr": 4, "abril": 4, "may": 5, "mayo": 5, "jun": 6, "junio": 6,
    "jul": 7, "julio": 7, "ago": 8, "agosto": 8, "sep": 9, "sept": 9, "septiembre": 9,
    "oct": 10, "octubre": 10, "nov": 11, "noviembre": 11, "dic": 12, "diciembre": 12,
}


def _parse_datetime(value: str) -> datetime | None:
    if not value:
        return None
    text = value.strip().lower()
    text = re.sub(r"[–—]", "-", text)
    text = re.sub(r"\bhoras?\b", "", text)
    text = re.sub(r"\s+", " ", text).strip()

    # Formatos ISO/numéricos usados por la tabla nacional de SENAMHI.
    for fmt in (
        "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M",
        "%d-%m-%Y %H:%M:%S", "%d-%m-%Y %H:%M",
        "%d/%m/%Y", "%d-%m-%Y",
        "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M",
        "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M",
        "%Y-%m-%d",
    ):
        try:
            return datetime.strptime(text[:19], fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass

    # Formatos de Aviso 24h, por ejemplo:
    # "Lunes 6 julio 2026 - 13:00 horas"
    # "6 julio 2026 - 13:00"
    match = re.search(
        r"(?:lunes|martes|miércoles|miercoles|jueves|viernes|sábado|sabado|domingo)?\s*"
        r"(\d{1,2})\s+(?:de\s+)?([a-záéíóú]+)\s+(?:de\s+)?(\d{4})"
        r"(?:\s*[-,]\s*(\d{1,2}):(\d{2}))?",
        text,
    )
    if match:
        day, month_name, year, hour, minute = match.groups()
        month = MONTHS_ES.get(month_name)
        if month:
            return datetime(
                int(year), month, int(day), int(hour or 0), int(minute or 0),
                tzinfo=timezone.utc,
            )
    return None


def _alert_status(alert: dict, now: datetime) -> str:
    start = _parse_datetime(alert.get("start_at", ""))
    end = _parse_datetime(alert.get("end_at", ""))

    if start and end:
        if start <= now <= end:
            return "ACTUAL"
        if now < start:
            return "PROXIMO"
        return "PASADO"

    if start:
        duration = str(alert.get("duration", "")).lower()
        if "24" in duration:
            inferred_end = start + __import__("datetime").timedelta(hours=24)
            if start <= now <= inferred_end:
                return "ACTUAL"
            if now < start:
                return "PROXIMO"
            return "PASADO"
        # Avisos sin fin explícito: se consideran próximos o actuales,
        # pero nunca se convierten en históricos sin evidencia temporal.
        return "ACTUAL" if start <= now else "PROXIMO"

    # Si sólo conocemos el fin, podemos clasificarlo como pasado con seguridad.
    if end:
        return "PASADO" if end < now else "ACTUAL"

    return "SIN_FECHA"


RELEVANT_TERMS = (
    "lluvia",
    "precipit",
    "inund",
    "crecida",
    "desborde",
    "quebrada",
    "huaico",
    "huayco",
    "tormenta",
    "caudal",
)


def _get_html(url: str, timeout: int = 15) -> str:
    response = requests.get(
        url,
        timeout=timeout,
        headers={"User-Agent": "ClimateAlertPlatform/1.0 (+academic-project)"},
    )
    response.raise_for_status()
    response.encoding = response.apparent_encoding or response.encoding
    return response.text


def _relevant(title: str) -> bool:
    text = title.lower()
    return any(term in text for term in RELEVANT_TERMS)


def _parse_national_table(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    results: list[dict] = []

    for table in soup.find_all("table"):
        rows: list[list[str]] = []
        for tr in table.find_all("tr"):
            cells = [cell.get_text(" ", strip=True) for cell in tr.find_all(["th", "td"])]
            if cells:
                rows.append(cells)

        if not rows:
            continue

        header = [x.lower() for x in rows[0]]
        if not ("aviso" in " ".join(header) and "nivel" in " ".join(header)):
            continue

        index = {name: i for i, name in enumerate(header)}
        for cells in rows[1:]:
            if len(cells) < 5:
                continue

            def get(name: str, default: str = "") -> str:
                i = index.get(name)
                return cells[i] if i is not None and i < len(cells) else default

            title = get("aviso")
            # El historial oficial debe conservar todos los tipos de aviso
            # (lluvia, viento, temperatura, nieve, etc.) para poder mostrar
            # también avisos pasados. El filtro temático se aplica en otras
            # secciones del dashboard.
            if not title or title.lower() == "aviso":
                continue

            number = get("nro.") or get("nro") or get("número")
            level = get("nivel").upper()
            results.append(
                {
                    "id": f"senamhi-{number or title[:40]}",
                    "source": "SENAMHI",
                    "official": True,
                    "type": "AVISO_METEOROLOGICO",
                    "title": title,
                    "number": number,
                    "issued_at": get("emisión"),
                    "start_at": get("inicio"),
                    "end_at": get("fin"),
                    "duration": get("duración"),
                    "level": level or "INFORMACION",
                    "url": SENAMHI_ALERTS_URL,
                }
            )

    return results


def _parse_short_term_rain(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True)

    match = re.search(
        r"N[°º]\s*(\d+)\s*-\s*(\d{4}).{0,500}?NIVEL\s+(AMARILLO|NARANJA|ROJO|VERDE)",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        return []

    number, year, level = match.groups()
    title_match = re.search(
        r"(AVISO DE CORTO PLAZO ANTE LLUVIAS INTENSAS)",
        text,
        flags=re.IGNORECASE,
    )
    title = title_match.group(1).upper() if title_match else "AVISO DE CORTO PLAZO ANTE LLUVIAS INTENSAS"

    start_match = re.search(r"Fecha de inicio:\s*([^·]+?)\s+Duración", text, flags=re.IGNORECASE)
    start_at = start_match.group(1).strip() if start_match else ""

    return [
        {
            "id": f"senamhi-rain-{year}-{number}",
            "source": "SENAMHI",
            "official": True,
            "type": "AVISO_CORTO_PLAZO_LLUVIA",
            "title": title,
            "number": number,
            "issued_at": "",
            "start_at": start_at,
            "end_at": "",
            "duration": "24 horas",
            "level": level.upper(),
            "url": SENAMHI_SHORT_TERM_RAIN_URL,
        }
    ]


def senamhi_alerts() -> dict:
    now = datetime.now(timezone.utc).isoformat()
    alerts: list[dict] = []
    errors: list[str] = []

    for label, url, parser in (
        ("national", SENAMHI_ALERTS_URL, _parse_national_table),
        ("short_term_rain", SENAMHI_SHORT_TERM_RAIN_URL, _parse_short_term_rain),
    ):
        try:
            alerts.extend(parser(_get_html(url)))
        except Exception as exc:
            errors.append(f"{label}: {exc}")

    dedup: dict[str, dict] = {}
    now_dt = datetime.now(timezone.utc)
    for alert in alerts:
        status = _alert_status(alert, now_dt)
        alert["status"] = status
        alert["is_current"] = status == "ACTUAL"
        dedup[alert["id"]] = alert

    result = {
        "source": "SENAMHI",
        "source_url": SENAMHI_ALERTS_URL,
        "fetched_at": now,
        "alerts": list(dedup.values())[:30],
    }
    if errors:
        result["warnings"] = errors
    return result
