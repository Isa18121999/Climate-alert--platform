from __future__ import annotations

from dataclasses import dataclass


# ============================================================
# RESULTADO DEL MOTOR DE RIESGO
# ============================================================
# Esta estructura agrupa el nivel calculado, el puntaje y las razones
# que explican por qué una medición obtuvo ese nivel.
@dataclass(frozen=True)
class RiskResult:
    level: str
    score: int
    reasons: list[str]


def evaluate_risk(rain_mm_h: float, river_level_m: float) -> RiskResult:
    """Deterministic MVP rule engine.

    The thresholds are configurable demonstration values and are not an official
    hydrological warning model.
    """
    score = 0
    reasons: list[str] = []

    # ========================================================
    # EVALUACIÓN DE LLUVIA
    # ========================================================
    # Cada rango añade puntos y registra la condición que provocó
    # el incremento del riesgo.
    if rain_mm_h >= 50:
        score += 2
        reasons.append("lluvia >= 50 mm/h")
    elif rain_mm_h >= 35:
        score += 1
        reasons.append("lluvia >= 35 mm/h")
    elif rain_mm_h >= 20:
        score += 1
        reasons.append("lluvia >= 20 mm/h")

    # ========================================================
    # EVALUACIÓN DEL NIVEL DEL RÍO
    # ========================================================
    if river_level_m >= 5:
        score += 2
        reasons.append("nivel de río >= 5 m")
    elif river_level_m >= 4:
        score += 1
        reasons.append("nivel de río >= 4 m")
    elif river_level_m >= 3:
        score += 1
        reasons.append("nivel de río >= 3 m")

    # ========================================================
    # CLASIFICACIÓN FINAL
    # ========================================================
    # Los valores de 50 mm/h de lluvia o 5 m de río fuerzan el nivel
    # crítico. En los demás casos se utiliza el puntaje acumulado.
    if rain_mm_h >= 50 or river_level_m >= 5:
        level = "CRITICO"
    elif score >= 2:
        level = "ALTO"
    elif score == 1:
        level = "MEDIO"
    else:
        level = "BAJO"

    return RiskResult(level=level, score=score, reasons=reasons)


# ============================================================
# PRUEBAS RÁPIDAS DEL MOTOR
# ============================================================
# Permite ejecutar el archivo directamente para comprobar algunos
# escenarios de ejemplo sin iniciar toda la aplicación.
if __name__ == "__main__":
    for rain, river in [(8, 1.8), (24, 2.8), (40, 4.1), (60, 5.2)]:
        print(rain, river, evaluate_risk(rain, river))
