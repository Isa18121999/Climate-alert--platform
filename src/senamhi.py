from __future__ import annotations

import re
from datetime import datetime, timezone, timedelta
from typing import Any

import requests
from bs4 import BeautifulSoup

SENAMHI_ALERTS_URL = "https://web2.senamhi.gob.pe/?p=avisos"
SENAMHI_SHORT_TERM_RAIN_URL = "https://www.senamhi.gob.pe/servicios/main.php?dp=lima&p=aviso-24H"
MONTHS_ES = {"ene":1,"enero":1,"feb":2,"febrero":2,"mar":3,"marzo":3,"abr":4,"abril":4,"may":5,"mayo":5,"jun":6,"junio":6,"jul":7,"julio":7,"ago":8,"agosto":8,"sep":9,"sept":9,"septiembre":9,"oct":10,"octubre":10,"nov":11,"noviembre":11,"dic":12,"diciembre":12}

# Respaldo histórico oficial: se mezcla con los datos obtenidos de SENAMHI
# para que el dashboard siempre pueda mostrar avisos pasados.
HISTORICAL_OFFICIAL = [
    ("269", "INCREMENTO DE VIENTO EN LA SIERRA NORTE", "2026-07-07", "2026-07-09", "NARANJA"),
    ("268", "INCREMENTO DE TEMPERATURA DIURNA EN LA COSTA Y SIERRA (EXTENSIÓN DEL AVISO 266)", "2026-07-07", "2026-07-09", "NARANJA"),
    ("267", "NEVADA EN LA SIERRA CENTRO Y SUR (EXTENSIÓN DEL AVISO 261)", "2026-07-04", "2026-07-04", "AMARILLO"),
    ("266", "INCREMENTO DE TEMPERATURA DIURNA EN LA COSTA Y SIERRA", "2026-07-04", "2026-07-06", "NARANJA"),
    ("265", "INCREMENTO DE VIENTO EN LA COSTA CENTRO Y SUR", "2026-07-05", "2026-07-06", "NARANJA"),
    ("264", "DESCENSO DE TEMPERATURA DIURNA EN LA SELVA - QUINTO FRIAJE", "2026-07-03", "2026-07-04", "NARANJA"),
    ("263", "INCREMENTO DE VIENTO EN LA COSTA CENTRO Y SUR", "2026-07-03", "2026-07-04", "NARANJA"),
    ("262", "LLUVIA EN LA SELVA - QUINTO FRIAJE", "2026-07-02", "2026-07-03", "AMARILLO"),
    ("261", "NEVADA EN LA SIERRA CENTRO Y SUR", "2026-07-02", "2026-07-03", "NARANJA"),
    ("260", "INCREMENTO DE VIENTO EN LA SIERRA", "2026-07-01", "2026-07-03", "AMARILLO"),
]


def _parse_datetime(value: str) -> datetime | None:
    if not value:
        return None
    text = re.sub(r"[–—]", "-", value.strip().lower())
    text = re.sub(r"\bhoras?\b", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    for fmt in ("%d/%m/%Y %H:%M:%S","%d/%m/%Y %H:%M","%d-%m-%Y %H:%M:%S","%d-%m-%Y %H:%M","%d/%m/%Y","%d-%m-%Y","%Y-%m-%d %H:%M:%S","%Y-%m-%d %H:%M","%Y-%m-%dT%H:%M:%S","%Y-%m-%dT%H:%M","%Y-%m-%d"):
        try:
            return datetime.strptime(text[:19], fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    match = re.search(r"(?:lunes|martes|miércoles|miercoles|jueves|viernes|sábado|sabado|domingo)?\s*(\d{1,2})\s+(?:de\s+)?([a-záéíóú]+)\s+(?:de\s+)?(\d{4})(?:\s*[-,]\s*(\d{1,2}):(\d{2}))?", text)
    if match:
        day, month_name, year, hour, minute = match.groups()
        month = MONTHS_ES.get(month_name)
        if month:
            return datetime(int(year), month, int(day), int(hour or 0), int(minute or 0), tzinfo=timezone.utc)
    return None


def _status(alert: dict[str, Any], now: datetime) -> str:
    start, end = _parse_datetime(str(alert.get("start_at", ""))), _parse_datetime(str(alert.get("end_at", "")))
    if start and end:
        if start <= now <= end: return "ACTUAL"
        return "PROXIMO" if now < start else "PASADO"
    if start:
        duration = str(alert.get("duration", "")).lower()
        inferred_end = start + timedelta(hours=24) if "24" in duration else None
        if inferred_end:
            if start <= now <= inferred_end: return "ACTUAL"
            return "PROXIMO" if now < start else "PASADO"
        return "ACTUAL" if start <= now else "PROXIMO"
    if end: return "PASADO" if end < now else "ACTUAL"
    return "SIN_FECHA"


def _get_html(url: str) -> str:
    response = requests.get(url, timeout=20, headers={"User-Agent": "ClimateAlertPlatform/1.0 (+academic-project)"})
    response.raise_for_status()
    response.encoding = response.apparent_encoding or response.encoding
    return response.text


def _norm(value: str) -> str:
    value = value.lower().strip().replace("º", "o").replace("°", "o")
    value = re.sub(r"[^a-záéíóúñ0-9]+", " ", value)
    return value.strip()


def _column(header: list[str], *names: str) -> int | None:
    for i, cell in enumerate(header):
        n = _norm(cell)
        if any(name in n for name in names): return i
    return None


def _parse_national_tables(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    results = []
    for table in soup.find_all("table"):
        rows = []
        for tr in table.find_all("tr"):
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
            if cells: rows.append(cells)
        if len(rows) < 2: continue
        header = rows[0]
        joined = " ".join(_norm(x) for x in header)
        if "aviso" not in joined or "nivel" not in joined: continue
        ia = _column(header, "aviso")
        inn = _column(header, "nro", "numero", "número")
        il = _column(header, "nivel")
        ie = _column(header, "emision", "emisión")
        ii = _column(header, "inicio")
        ifn = _column(header, "fin", "termino", "término")
        idu = _column(header, "duracion", "duración")
        if ia is None or il is None: continue
        for cells in rows[1:]:
            def get(idx): return cells[idx].strip() if idx is not None and idx < len(cells) else ""
            title = get(ia)
            if not title or _norm(title) in ("aviso", "avisos"): continue
            number, level = get(inn), get(il).upper()
            results.append({
                "id": f"senamhi-{number or re.sub(r'[^a-z0-9]+','-',title.lower())[:50]}",
                "source": "SENAMHI", "official": True, "type": "AVISO_METEOROLOGICO",
                "title": title, "number": number, "issued_at": get(ie), "start_at": get(ii),
                "end_at": get(ifn), "duration": get(idu), "level": level or "INFORMACION",
                "url": SENAMHI_ALERTS_URL,
            })
    return results


def _historical_fallback() -> list[dict]:
    return [{
        "id": f"senamhi-{number}", "source": "SENAMHI", "official": True,
        "type": "AVISO_METEOROLOGICO", "title": title, "number": number,
        "issued_at": start, "start_at": start, "end_at": end,
        "duration": "", "level": level, "url": SENAMHI_ALERTS_URL,
    } for number, title, start, end, level in HISTORICAL_OFFICIAL]


def _parse_short_term_rain(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True)
    match = re.search(r"N[°º]\s*(\d+)\s*-\s*(\d{4}).{0,800}?NIVEL\s+(AMARILLO|NARANJA|ROJO|VERDE)", text, re.I)
    if not match: return []
    number, year, level = match.groups()
    title = "AVISO DE CORTO PLAZO ANTE LLUVIAS INTENSAS"
    start_match = re.search(r"Fecha de inicio:\s*([^·]+?)(?:Duración|Fin|$)", text, re.I)
    start_at = start_match.group(1).strip() if start_match else ""
    return [{"id":f"senamhi-rain-{year}-{number}","source":"SENAMHI","official":True,"type":"AVISO_CORTO_PLAZO_LLUVIA","title":title,"number":number,"issued_at":"","start_at":start_at,"end_at":"","duration":"24 horas","level":level.upper(),"url":SENAMHI_SHORT_TERM_RAIN_URL}]


def senamhi_alerts() -> dict:
    alerts, errors = [], []
    for label, url, parser in (("national", SENAMHI_ALERTS_URL, _parse_national_tables), ("short_term_rain", SENAMHI_SHORT_TERM_RAIN_URL, _parse_short_term_rain)):
        try: alerts.extend(parser(_get_html(url)))
        except Exception as exc: errors.append(f"{label}: {exc}")

    now_dt = datetime.now(timezone.utc)
    # El portal puede entregar la tabla histórica mediante JS. Mezclamos
    # siempre los avisos históricos oficiales conocidos para que la sección
    # "Avisos pasados" nunca quede vacía por una respuesta HTML incompleta.
    historical = _historical_fallback()
    known_ids = {a.get("id") for a in alerts}
    alerts.extend(a for a in historical if a.get("id") not in known_ids)

    dedup = {}
    for alert in alerts:
        status = _status(alert, now_dt)
        alert["status"], alert["is_current"] = status, status == "ACTUAL"
        dedup[alert["id"]] = alert

    ordered = sorted(dedup.values(), key=lambda x: _parse_datetime(str(x.get("end_at", ""))) or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    past = [a for a in ordered if a.get("status") == "PASADO"]
    current = [a for a in ordered if a.get("status") == "ACTUAL"]
    return {
        "source":"SENAMHI",
        "source_url":SENAMHI_ALERTS_URL,
        "fetched_at":now_dt.isoformat(),
        "alerts":ordered[:50],
        "past_alerts":past[:50],
        "current_alerts":current[:50],
        "warnings":errors,
    }
