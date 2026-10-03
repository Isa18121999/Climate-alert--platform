# Despliegue

## 1. Crear infraestructura

```bash
sam build
sam deploy --guided
```

## 2. Probar la API

Reemplaza `API_URL` por el valor de la salida `ApiUrl`.

```bash
curl -X POST "$API_URL/measurements" \
  -H 'content-type: application/json' \
  -d @events/sample_measurement.json

curl "$API_URL/measurements"
curl "$API_URL/alerts"
```

## 3. SNS

La infraestructura crea el tópico SNS. Para recibir correo, confirma una suscripción al tópico en la consola de AWS.
