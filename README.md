# Plataforma de Alerta Temprana para Lluvias Extremas e Inundaciones

MVP API-first serverless basado en AWS para consumir fuentes meteorológicas/hidrológicas, calcular riesgo, consultar noticias recientes y exponer alertas en tiempo casi real.

## Contexto

El proyecto sigue la Propuesta 1 del documento del Grupo 1: centralizar datos meteorológicos e hidrológicos, procesarlos en tiempo real, detectar riesgos y generar alertas automáticas con una arquitectura escalable en la nube.

## Arquitectura

```text
Open-Meteo Weather API ─┐
Open-Meteo Flood API ───┼─> API Gateway
GDELT News API ─────────┘
                         |
                         v
                     AWS Lambda
                       /     \
                      v       v
                 DynamoDB   Motor de riesgo
                      |       |
                      +-------+
                          |
                          v
                     Alertas SNS (opcional)
                          |
                          v
                   Dashboard web (S3/CloudFront)
```

### Servicios AWS

- **API Gateway**: endpoints HTTP.
- **AWS Lambda**: ingestión, consulta y evaluación de riesgo.
- **DynamoDB**: histórico de mediciones y alertas.
- **Amazon SNS**: notificaciones automáticas cuando el riesgo sea alto o crítico.
- **S3 + CloudFront**: alojamiento del dashboard estático.
- **CloudWatch**: logs y observabilidad.

## Endpoints

- `POST /measurements` recibe una medición.
- `GET /measurements?limit=20` consulta mediciones recientes.
- `GET /alerts?limit=20` consulta alertas recientes.
- `GET /weather?lat=&lon=` consulta condiciones meteorológicas desde Open-Meteo.
- `GET /flood?lat=&lon=` consulta caudal fluvial desde Open-Meteo Flood API / GloFAS.
- `GET /news?q=` consulta noticias recientes desde GDELT. Por defecto se usa GDELT; opcionalmente se puede establecer `NEWS_PROVIDER=newsapi` y `NEWS_API_KEY` para usar News API.

### Ejemplo de medición

```json
{
  "station_id": "EST-001",
  "timestamp": "2026-10-03T15:00:00Z",
  "rain_mm_h": 52.4,
  "river_level_m": 4.8,
  "location": {
    "lat": -12.0464,
    "lon": -77.0428
  }
}
```

## Integración API-first

El proyecto prioriza APIs externas como fuente de datos. El dashboard consulta las fuentes cada 60 segundos y muestra la hora de la última actualización. La frecuencia real de publicación depende de cada proveedor. La integración y las rutas están documentadas en `docs/API_INTEGRATION.md`.

## Regla de riesgo del MVP

La función combina lluvia por hora y nivel de río. Los umbrales son configurables y sirven como demostración técnica, no como sistema operativo de alerta oficial.

- **BAJO**: valores por debajo de atención.
- **MEDIO**: lluvia >= 20 mm/h o río >= 3.0 m.
- **ALTO**: lluvia >= 35 mm/h o río >= 4.0 m.
- **CRÍTICO**: lluvia >= 50 mm/h o río >= 5.0 m.

## Despliegue con AWS SAM

Requisitos:

- AWS CLI configurado.
- AWS SAM CLI.
- Python 3.12.

```bash
sam build
sam deploy --guided
```

Durante el despliegue se crearán las tablas DynamoDB, la API HTTP y el tópico SNS.

## Ejecución local

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r src/requirements.txt
pytest -q
```

## Simulación rápida

```bash
python src/risk_engine.py
```

## Estructura

```text
.
├── dashboard/index.html
├── events/sample_measurement.json
├── src/
│   ├── handler.py
│   ├── requirements.txt
│   └── risk_engine.py
├── tests/test_risk_engine.py
├── template.yaml
└── README.md
```

## Alcance académico

Este repositorio implementa un **MVP demostrable** de la propuesta: ingestión, procesamiento, persistencia, evaluación y visualización. Para una solución operativa se requerirían validación hidrológica, calibración por cuenca, integración con fuentes oficiales y un protocolo institucional de emisión de alertas.

## Demostración web publicada

- Frontend: https://climate-alert-platform.onrender.com
- Backend API: https://climate-alert-platform-api.onrender.com
- Health check: https://climate-alert-platform-api.onrender.com/health

El frontend consume el backend cloud para las rutas de clima, caudal y noticias. También se mantienen las integraciones directas documentadas como respaldo técnico.

> Nota: esta versión usa Render para demostrar el despliegue web/API. La plantilla AWS SAM permanece en `template.yaml` para el despliegue equivalente sobre AWS cuando se disponga de credenciales/permisos AWS.
