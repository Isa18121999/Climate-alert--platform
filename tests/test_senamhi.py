from src.senamhi import _parse_national_table, _parse_short_term_rain


def test_parse_national_table():
    html = """
    <table>
      <tr><th>Aviso</th><th>Nro.</th><th>Emisión</th><th>Inicio</th><th>Fin</th><th>Duración</th><th>Nivel</th></tr>
      <tr><td>LLUVIAS INTENSAS EN LA SIERRA</td><td>123 (vigente)</td><td>2026-10-03</td><td>2026-10-04</td><td>2026-10-05</td><td>47 Hrs.</td><td>NARANJA</td></tr>
      <tr><td>INCREMENTO DE TEMPERATURA</td><td>122</td><td>2026-10-03</td><td>2026-10-04</td><td>2026-10-05</td><td>47 Hrs.</td><td>NARANJA</td></tr>
    </table>
    """
    alerts = _parse_national_table(html)
    assert len(alerts) == 1
    assert alerts[0]["source"] == "SENAMHI"
    assert alerts[0]["official"] is True
    assert alerts[0]["level"] == "NARANJA"


def test_parse_short_term_rain():
    html = """
    <html><body>
      N°187 - 2026 NIVEL AMARILLO
      AVISO DE CORTO PLAZO ANTE LLUVIAS INTENSAS
      Fecha de inicio: Lunes 6 julio 2026 - 13:00 horas Duración: 24 hrs
    </body></html>
    """
    alerts = _parse_short_term_rain(html)
    assert len(alerts) == 1
    assert alerts[0]["number"] == "187"
    assert alerts[0]["level"] == "AMARILLO"
