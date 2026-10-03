# Integración API-first

La propuesta usa APIs como fuente principal de datos, en lugar de depender de valores simulados en la interfaz.

## API externas

### 1. Open-Meteo Weather API

 Endpoint utilizado por Lambda:

`https://api.open-meteo.com/v1/forecast`

Entrega condiciones meteorológicas actuales y series horarias por latitud/longitud.

### 2. Open-Meteo Flood API / GloFAS

Endpoint:

`https://flood-api.open-meteo.com/v1/flood`

Entrega pronóstico de caudal fluvial diario (`river_discharge`) para la zona solicitada.

### 3. GDELT DOC 2.0

Endpoint:

`https://api.gdeltproject.org/api/v2/doc/doc`

La aplicación consulta noticias relacionadas con "Peru inundación lluvias El Niño" en una ventana reciente. El dashboard vuelve a consultar cada 60 segundos.

## Endpoints propios

- `GET /weather?lat=-5.1945&lon=-80.6328`
- `GET /flood?lat=-5.1945&lon=-80.6328`
- `GET /news?q=Peru%20inundacion%20lluvias%20El%20Nino`
- `POST /measurements`
- `GET /measurements`
- `GET /alerts`

## Actualización en tiempo real

El frontend realiza polling cada minuto. Esto significa que la pantalla se actualiza como máximo cada 60 segundos, pero la frescura final depende del proveedor de cada API. GDELT 2.0 opera con un ciclo de actualización de aproximadamente 15 minutos, por lo que no se debe presentar como garantía de una noticia nueva exactamente cada minuto.

Para una versión de producción se puede añadir WebSocket/SSE para enviar eventos desde API Gateway/Lambda al navegador sin polling.

## API de noticias alternativa

Se puede cambiar el proveedor por News API sin modificar el frontend. News API ofrece `top-headlines` y `everything` y requiere una API key. La clave debe mantenerse en Secrets Manager o Parameter Store y nunca en el repositorio.
