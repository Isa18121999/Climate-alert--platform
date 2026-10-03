import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from risk_engine import evaluate_risk


def test_low_risk():
    assert evaluate_risk(5, 1.5).level == "BAJO"


def test_medium_risk():
    assert evaluate_risk(24, 2.5).level == "MEDIO"


def test_high_risk():
    assert evaluate_risk(40, 4.1).level == "ALTO"


def test_critical_rain():
    assert evaluate_risk(55, 2.0).level == "CRITICO"
