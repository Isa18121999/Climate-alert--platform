from __future__

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import requests
from flask import Blueprint, jsonify, request

from senamhi import senamhi_alerts

bp = Blueprint("dashboard_routes", __name__)

STATIONS = {
    "Lima": {"lat": -12.0464, "lon": -77.0428, "region": "Costa"},
    "Piura": {"lat": -5.1945, "lon": -80.6328, "region": "Costa"},
    "Tumbes": {"lat": -3.5708, "lon": -80.4590, "region": "Costa"},
    "Chiclayo": {"lat": -6.7714, "lon": -79.8409, "region": "Costa"},
    "Trujillo": {"lat": -8.1116, "lon": -79.0288, "region": "Costa"},
    "Ica": {"lat": -14.0678, "lon": -75.7286, "region": "Costa"},
    "Arequipa": {"lat": -16.4090, "lon": -71.5375, "region": "Sierra"},
    "Cusco": {"lat": -13.5319, "lon": -71.9675, "region": "Sierra"},
    "Huancayo": {"lat": -12.0651, "lon": -75.2049, "region": "Sierra"},
    "Iquitos": {"lat": -3.7437, "lon": -73.2516, "region": "Selva"},
    "Tarapoto": {"lat": -6.4850, "lon": -76.3600, "region": "Selva"},
    "Tacna": {"lat": -18.0066, "lon": -70.2463, "region": "Costa"},
}

DEPARTMENT_ALIASES = {
    "Lima": ("lima",), "Piura": ("piura",), "Tumbes": ("tumbes",),
    "Chiclayo": ("lambayeque", "chiclayo"), "Trujillo": ("la libertad", "trujillo"),
    "Ica": ("ica",), "Arequipa": ("arequipa",), "Cusco": ("cusco",),
    "Huancayo": ("junin", "junín", "huancayo"), "Iquitos": ("loreto", "iquitos"),
    "Tarapoto": ("san martin", "san martín", "tarapoto"), "Tacna": ("tacna",),
}
RISK_ORDER = {"VERDE": 1, "AMARILLO": 2, "NARANJA": 3, "ROJO": 4}


def _text(value) -> str:
    return str(value or "").lower().replace("á", "a").replace("é", "e").replace("í", "i").replace("ó", "o").replace("ú", "u").strip()


def _risk_from_level(level) -> str:
    value = _text(level)
    if any(x in value for x in ("4", "rojo", "critico", "critica", "critical")):
        return "ROJO"
    if any(x in value for x in ("3", "naranja", "alto", "high")):
        return "NARANJA"
    if any(x in value for x in ("2", "amarillo", "medio", "moderado", "medium")):
        return "AMARILLO"
    return "VERDE"


def _alert_matches(city: str, alert: dict) -> bool:
    haystack = " ".join([
        _text(alert.get("region")), _text(alert.get("regions")), _text(alert.get("department")),
        _text(alert.get("departments")), _text(alert.get("title")), _text(alert.get("name")),
        _text(alert.get("description")), _text(alert.get("message")),
    ])
    return any(alias in haystack for alias in DEPARTMENT_ALIASES.get(city, (city.lower(),)))


def _weather(city: str) -> dict:
    station = STATIONS[city]
    response = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": station["lat"], "longitude": station["lon"],
            "current": "temperature_2m,relative_humidity_2m,precipitation,rain,wind_speed_10m",
            "forecast_days": 1, "timezone": "America/Lima",
        }, timeout=8,
    )
    response.raise_for_status()
    return response.json().get("current", {})


def _build_zones() -> tuple[list[dict], list[dict]]:
    official = senamhi_alerts().get("alerts", [])
    current = [a for a in official if str(a.get("status", "")).upper() == "ACTUAL" or a.get("is_current") is True]
    zones = []
    with ThreadPoolExecutor(max_workers=len(STATIONS)) as executor:
        futures = {executor.submit(_weather, city): city for city in STATIONS}
        for future in as_completed(futures):
            city = futures[future]
            try:
                weather = future.result()
            except Exception as exc:
                print(f"DASHBOARD WEATHER {city}: {exc}")
                weather = {}
            matches = [a for a in current if _alert_matches(city, a)]
            alert_risk = max((_risk_from_level(a.get("level") or a.get("severity") or a.get("color")) for a in matches), key=lambda x: RISK_ORDER[x], default="VERDE")
            rain = float(weather.get("rain") or weather.get("precipitation") or 0)
            weather_risk = "ROJO" if rain >= 50 else "NARANJA" if rain >= 35 else "AMARILLO" if rain >= 20 else "VERDE"
            risk_level = max((alert_risk, weather_risk), key=lambda x: RISK_ORDER[x])
            reason = "Aviso oficial SENAMHI vigente" if matches else ("Precipitación elevada" if rain >= 20 else "Sin condición crítica detectada")
            zones.append({
                "city": city, "region": STATIONS[city]["region"],
                "temperature": weather.get("temperature_2m"), "rain_mm": rain,
                "humidity": weather.get("relative_humidity_2m"), "wind_kmh": weather.get("wind_speed_10m"),
                "risk": risk_level, "risk_label": risk_level,
                "risk_order": RISK_ORDER[risk_level], "reason": reason,
                "active_alerts": matches, "source": "SENAMHI + Open-Meteo",
            })
    zones.sort(key=lambda x: (-x["risk_order"], -float(x["rain_mm"] or 0), x["city"]))
    return zones, current


@bp.get("/dashboard/zones")
def dashboard_zones():
    region = _text(request.args.get("region", "todas"))
    risk = _text(request.args.get("risk", "todos")).upper()
    zones, current = _build_zones()
    filtered = zones
    if region in {"costa", "sierra", "selva"}:
        filtered = [z for z in filtered if _text(z["region"]) == region]
    if risk in RISK_ORDER:
        filtered = [z for z in filtered if z["risk"] == risk]
    return jsonify({
        "source": "Backend Climate Alert Platform", "fetched_at": datetime.now(timezone.utc).isoformat(),
        "filters": {"region": region, "risk": risk}, "total": len(filtered), "zones": filtered,
        "current_official_alerts": len(current),
    })


@bp.get("/dashboard/summary")
def dashboard_summary():
    zones, current = _build_zones()
    counts = {key: sum(1 for z in zones if z["risk"] == key) for key in RISK_ORDER}
    return jsonify({
        "source": "Backend Climate Alert Platform", "fetched_at": datetime.now(timezone.utc).isoformat(),
        "total_zones": len(zones), "risk_counts": counts, "current_official_alerts": len(current),
    })
