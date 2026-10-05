# Alertas automáticas con AWS SNS

Esta carpeta implementa el envío de alertas por correo para **Climate Alert Platform**.

## Flujo

```text
SENAMHI + Open-Meteo / GloFAS
          |
          v
Backend Climate Alert Platform
          |
          v
AWS Lambda (cada 5 minutos)
          |
          +--> DynamoDB: evita duplicados
          |
          v
Amazon SNS
          |
          v
Correo electrónico del usuario
```

### Reglas de envío

- Aviso oficial SENAMHI con estado `ACTUAL` o `is_current=true` -> **se envía**.
- Aviso oficial SENAMHI con estado `PASADO` -> **no se envía**.
- Riesgo calculado `ALTO` -> se notifica como **FUERTE**.
- Riesgo calculado `CRITICO` -> se notifica como **EXTREMA**.
- Riesgo `MEDIO`/`BAJO` -> permanece en el dashboard y **no envía correo**.
- La tabla DynamoDB registra cada alerta enviada para evitar correos repetidos.

> El monitoreo está programado cada 5 minutos. Por rigor académico, se debe describir como **monitoreo periódico de 5 minutos**, no como tiempo real instantáneo.

## Despliegue con AWS SAM

### 1. Instalar AWS CLI y AWS SAM CLI

Configura primero tus credenciales de AWS con:

```bash
aws configure
```

La región usada por el proyecto es `us-east-1`.

### 2. Construir

Desde la raíz del repositorio:

```bash
sam build --template-file aws/template.yaml
```

### 3. Desplegar

```bash
sam deploy --guided --template-file .aws-sam/build/template.yaml
```

Durante el asistente:

- **Stack Name:** `climate-alert-platform`
- **AWS Region:** `us-east-1`
- **AlertEmail:** el correo que recibirá las alertas.
- **ApiBaseUrl:** `https://climate-alert-platform-api.onrender.com`
- Acepta la creación de los recursos IAM solicitados.
- Guarda la configuración cuando SAM lo pregunte.

### 4. Confirmar el correo

AWS SNS enviará un correo de confirmación a `AlertEmail`.

Debes abrirlo y seleccionar **Confirm subscription**. Hasta confirmar la suscripción, SNS no entregará los correos.

### 5. Probar la Lambda

Después del despliegue, en AWS Lambda abre `climate-alert-monitor` y ejecuta una prueba con un evento JSON vacío:

```json
{}
```

La respuesta esperada tiene esta estructura:

```json
{
  "status": "ok",
  "checked_at": "...",
  "notifications": []
}
```

Si existe una alerta activa, aparecerá una notificación con `status: "sent"`. Si ya fue enviada anteriormente, aparecerá `status: "duplicate"`.

## Recursos creados

- Amazon SNS Topic: `climate-alerts-peru`
- Suscripción SNS por correo
- AWS Lambda: `climate-alert-monitor`
- Amazon DynamoDB: `climate-alert-sent`
- Amazon EventBridge Schedule: cada 5 minutos

No se modifican el diseño ni las secciones del dashboard. El dashboard continúa funcionando con el backend existente.
