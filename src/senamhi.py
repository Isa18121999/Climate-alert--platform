from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
from typing import Any

import requests
from bs4 import BeautifulSoup

# Avisos obtenidos exclusivamente desde páginas oficiales de SENAMHI.
SENAMHI_ALERTS_URL = "https://www.senamhi.gob.pe/?p=aviso-meteorologico"
SENAMHI_ALERTS_FALLBACK_URL = "https://www.senamhi.gob.pe/main.php?dp=lima&p=avisos-meteorologicos"
SENAMHI_ALERTS_FALLBACK_2_URL = "https://web2.senamhi.gob.pe/?p=avisos"
SENAMHI_SHORT_TERM_RAIN_URL = "https://www.senamhi.gob.pe/servicios/?p=aviso-24H"
SENAMHI_SHORT_TERM_RAIN_FALLBACK_URL = "https://www.senamhi.gob.pe/servicios/main.php?dp=lima&p=aviso-24H"
MONTHS_ES = {"ene":1,"enero":1,"feb":2,"febrero":2,"mar":3,"marzo":3,"abr":4,"abril":4,"may":5,"mayo":5,"jun":6,"junio":6,"jul":7,"julio":7,"ago":8,"agosto":8,"sep":9,"sept":9,"septiembre":9,"oct":10,"octubre":10,"nov":11,"noviembre":11,"dic":12,"diciembre":12}


def _parse_datetime(value: str) -> datetime | None:
    if not value: return None
    text = re.sub(r"[–—]", "-", value.strip().lower())
    text = re.sub(r"\bhoras?\b", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S","%Y-%m-%d %H:%M","%Y-%m-%d","%d/%m/%Y %H:%M:%S","%d/%m/%Y %H:%M","%d/%m/%Y","%d-%m-%Y %H:%M:%S","%d-%m-%Y %H:%M","%d-%m-%Y"):
        try: return datetime.strptime(text[:19], fmt).replace(tzinfo=timezone.utc)
        except ValueError: pass
    match = re.search(r"(?:lunes|martes|miércoles|miercoles|jueves|viernes|sábado|sabado|domingo)?\s*(\d{1,2})\s+(?:de\s+)?([a-záéíóú]+)\s+(?:de\s+)?(\d{4})(?:\s*[-,]\s*(\d{1,2}):(\d{2}))?", text)
    if match:
        day, month_name, year, hour, minute = match.groups()
        month = MONTHS_ES.get(month_name)
        if month: return datetime(int(year), month, int(day), int(hour or 0), int(minute or 0), tzinfo=timezone.utc)
    return None


def _status(alert: dict[str, Any], now: datetime) -> str:
    start = _parse_datetime(str(alert.get("start_at", "")))
    end = _parse_datetime(str(alert.get("end_at", "")))
    if start and end:
        if start <= now <= end: return "ACTUAL"
        return "PROXIMO" if now < start else "PASADO"
    if start:
        duration = str(alert.get("duration", "")).lower()
        if "24" in duration:
            end = start + timedelta(hours=24)
            if start <= now <= end: return "ACTUAL"
            return "PROXIMO" if now < start else "PASADO"
        return "ACTUAL" if start <= now else "PROXIMO"
    if end: return "PASADO" if end < now else "ACTUAL"
    return "SIN_FECHA"


def _get_html(url: str) -> str:
    response = requests.get(url, timeout=10, headers={"User-Agent":"ClimateAlertPlatform/1.0 (+academic-project)","Accept-Language":"es-PE,es;q=0.9"})
    response.raise_for_status()
    response.encoding = response.apparent_encoding or response.encoding
    return response.text


def _norm(value: str) -> str:
    value = value.lower().strip().replace("º", "o").replace("°", "o")
    return re.sub(r"[^a-záéíóúñ0-9]+", " ", value).strip()


def _column(header: list[str], *names: str) -> int | None:
    for i, cell in enumerate(header):
        if any(name in _norm(cell) for name in names): return i
    return None


def _parse_national_tables(html: str, source_url: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    results = []
    for table in soup.find_all("table"):
        rows = []
        for tr in table.find_all("tr"):
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th","td"])]
            if cells: rows.append(cells)
        if len(rows) < 2: continue
        header = rows[0]
        joined = " ".join(_norm(x) for x in header)
        if "aviso" not in joined or "nivel" not in joined: continue
        ia, inn, il = _column(header,"aviso"), _column(header,"nro","numero","número"), _column(header,"nivel")
        ie, ii = _column(header,"emision","emisión"), _column(header,"inicio")
        ifn, idu = _column(header,"fin","termino","término"), _column(header,"duracion","duración")
        ir = _column(header,"departamento","departamentos","region","región","regiones","zona","zonas")
        if ia is None or il is None: continue
        for cells in rows[1:]:
            def get(idx): return cells[idx].strip() if idx is not None and idx < len(cells) else ""
            title = get(ia)
            if not title or _norm(title) in ("aviso","avisos"): continue
            number, level = get(inn), get(il).upper()
            clean_number = re.sub(r"\s*\(.*?\)", "", number).strip()
            region = get(ir)
            results.append({"id":f"senamhi-{clean_number or re.sub(r'[^a-z0-9]+','-',title.lower())[:50]}","source":"SENAMHI","official":True,"type":"AVISO_METEOROLOGICO","title":title,"number":clean_number or number,"issued_at":get(ie),"start_at":get(ii),"end_at":get(ifn),"duration":get(idu),"level":level or "INFORMACION","region":region or "Perú","url":source_url})
    return results


def _parse_short_term_rain(html: str, source_url: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True)
    match = re.search(r"N[°º]\s*(\d+)\s*-\s*(\d{4}).{0,1600}?NIVEL\s+(AMARILLO|NARANJA|ROJO|VERDE)", text, re.I)
    if not match: return []
    number, year, level = match.groups()
    start_match = re.search(r"Fecha de inicio:\s*(.*?)(?:\s+Duración:|\s+Plazo:|$)", text, re.I)
    start_value = start_match.group(1).strip() if start_match else ""
    return [{"id":f"senamhi-rain-{year}-{number}","source":"SENAMHI","official":True,"type":"AVISO_CORTO_PLAZO_LLUVIA","title":"AVISO DE CORTO PLAZO ANTE LLUVIAS INTENSAS","number":number,"issued_at":"","start_at":start_value,"end_at":"","duration":"24 horas","level":level.upper(),"region":"Perú","url":source_url}]


def senamhi_alerts() -> dict:
    alerts, errors = [], []
    sources = [
        ("national", SENAMHI_ALERTS_URL),
        ("national_fallback", SENAMHI_ALERTS_FALLBACK_URL),
        ("national_fallback_2", SENAMHI_ALERTS_FALLBACK_2_URL),
        ("short_term_rain", SENAMHI_SHORT_TERM_RAIN_URL),
        ("short_term_rain_fallback", SENAMHI_SHORT_TERM_RAIN_FALLBACK_URL),
    ]
    with ThreadPoolExecutor(max_workers=len(sources)) as executor:
        futures = {executor.submit(_get_html, url):(label,url) for label,url in sources}
        for future in as_completed(futures):
            label, url = futures[future]
            try:
                html = future.result()
                if label.startswith("short_term_rain"):
                    alerts.extend(_parse_short_term_rain(html, url))
                else:
                    alerts.extend(_parse_national_tables(html, url))
            except Exception as exc:
                errors.append(f"{label}: {exc}")

    now_dt = datetime.now(timezone.utc)
    dedup = {}
    for alert in alerts:
        status = _status(alert, now_dt)
        alert["status"], alert["is_current"] = status, status == "ACTUAL"
        dedup[alert["id"]] = alert

    ordered = sorted(dedup.values(), key=lambda x:_parse_datetime(str(x.get("end_at",""))) or _parse_datetime(str(x.get("start_at",""))) or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    current = [a for a in ordered if a["status"] == "ACTUAL"]
    past = [a for a in ordered if a["status"] == "PASADO"]
    upcoming = [a for a in ordered if a["status"] == "PROXIMO"]
    return {"source":"SENAMHI","source_url":SENAMHI_ALERTS_URL,"fetched_at":now_dt.isoformat(),"alerts":(current[:40]+upcoming[:10]+past[:50])[:100],"current_alerts":current[:50],"past_alerts":past[:50],"upcoming_alerts":upcoming[:20],"current_count":len(current),"past_count":len(past),"upcoming_count":len(upcoming),"total_count":len(ordered),"warnings":errors,"note":"Los avisos se obtienen exclusivamente de fuentes oficiales de SENAMHI; no se utilizan avisos históricos escritos manualmente."}
