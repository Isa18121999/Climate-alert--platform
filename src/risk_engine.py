from __future__ import annotations

from dataclasses import dataclass


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

    if rain_mm_h >= 50:
        score += 2
        reasons.append("lluvia >= 50 mm/h")
    elif rain_mm_h >= 35:
        score += 1
        reasons.append("lluvia >= 35 mm/h")
    elif rain_mm_h >= 20:
        score += 1
        reasons.append("lluvia >= 20 mm/h")

    if river_level_m >= 5:
        score += 2
        reasons.append("nivel de río >= 5 m")
    elif river_level_m >= 4:
        score += 1
        reasons.append("nivel de río >= 4 m")
    elif river_level_m >= 3:
        score += 1
        reasons.append("nivel de río >= 3 m")

    if rain_mm_h >= 50 or river_level_m >= 5:
        level = "CRITICO"
    elif score >= 2:
        level = "ALTO"
    elif score == 1:
        level = "MEDIO"
    else:
        level = "BAJO"

    return RiskResult(level=level, score=score, reasons=reasons)


if __name__ == "__main__":
    for rain, river in [(8, 1.8), (24, 2.8), (40, 4.1), (60, 5.2)]:
        print(rain, river, evaluate_risk(rain, river))
