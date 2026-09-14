# Bot de Finanzas Personales (AWS Lambda + DynamoDB + Telegram)

Misma lógica de negocio que las versiones anteriores (Render/Telegram con
polling), pero con arquitectura **serverless**: en vez de un proceso corriendo
24/7 esperando mensajes, aquí el código **solo se ejecuta cuando hay algo que
hacer** (llega un mensaje, o toca un resumen programado). Esto encaja con
los niveles "Always Free" de AWS, que **no caducan**.

## Qué cambió respecto a la versión de Telegram con polling?

- `telegram_bot.py` (que hacía polling con `python-telegram-bot`) se
  reemplaza por `lambda_function.py`, mucho más simple: recibe un evento,
  responde, termina.
- `db.py` ahora usa **DynamoDB** (vía `boto3`) en vez de SQLite. Las
  funciones tienen **exactamente los mismos nombres y firmas** que antes,
  así que `core.py` y `goals.py` no cambiaron ni una línea.
- Ya no se necesita `python-telegram-bot`, `flask`, ni `apscheduler`. Las
  respuestas a Telegram se mandan con un cliente HTTP mínimo
  (`app/telegram_api.py`), usando solo la librería estándar de Python.
- Los resúmenes automáticos (semanal, alertas) ya no usan un scheduler
  interno: los dispara **EventBridge Scheduler** desde afuera, invocando la
  misma función Lambda con un payload distinto.

## 1. Crear la tabla de DynamoDB

Con la consola de AWS (DynamoDB → "Create table") o con la CLI:

```bash
aws dynamodb create-table \
  --table-name finanzas_bot \
  --attribute-definitions AttributeName=PK,AttributeType=S AttributeName=SK,AttributeType=S \
  --key-schema AttributeName=PK,KeyType=HASH AttributeName=SK,KeyType=RANGE \
  --billing-mode PAY_PER_REQUEST
```

`PAY_PER_REQUEST` (on-demand) es la opción más simple para empezar — para
el volumen de un bot personal, te vas a mantener muy por debajo del nivel
gratuito de todas formas.

## 2. Crear el rol de IAM para la función Lambda

Necesita permiso para escribir logs (básico de cualquier Lambda) y para
leer/escribir en la tabla de DynamoDB. Desde la consola de IAM, crea un rol
con las políticas administradas `AWSLambdaBasicExecutionRole` y agrega una
política inline con:

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem",
               "dynamodb:DeleteItem", "dynamodb:Query"],
    "Resource": "arn:aws:dynamodb:TU_REGION:TU_ACCOUNT_ID:table/finanzas_bot"
  }]
}
```

## 3. Empaquetar y crear la función Lambda

Solo `anthropic` y `httpx` necesitan empaquetarse — `boto3` ya viene
incluido en el runtime de Lambda, no lo agregues (aumentaría el tamaño del
paquete sin necesidad).

```bash
cd finanzas-bot-lambda
pip install -r requirements.txt -t package/
cp -r app package/
cp lambda_function.py package/
cd package && zip -r ../despliegue.zip . && cd ..
```

Sube `despliegue.zip` a una función Lambda nueva (consola o CLI):

```bash
aws lambda create-function \
  --function-name finanzas-bot \
  --runtime python3.12 \
  --handler lambda_function.handler \
  --role arn:aws:iam::TU_ACCOUNT_ID:role/TU_ROL \
  --zip-file fileb://despliegue.zip \
  --timeout 15 \
  --memory-size 128
```

Configura las variables de entorno (consola → tu función → Configuration →
Environment variables, o `aws lambda update-function-configuration`):

- `ANTHROPIC_API_KEY`
- `TELEGRAM_BOT_TOKEN`
- `MY_TELEGRAM_CHAT_ID` (puedes dejarlo vacío al principio, ver paso 5)
- `DYNAMODB_TABLE=finanzas_bot`

## 4. Crear el API Gateway (para que Telegram te pueda "tocar la puerta")

Crea una **HTTP API** (más simple y barata que una REST API clásica) con
una sola ruta:

```bash
aws apigatewayv2 create-api \
  --name finanzas-bot-api \
  --protocol-type HTTP \
  --target arn:aws:lambda:TU_REGION:TU_ACCOUNT_ID:function:finanzas-bot
```

Esto crea automáticamente una ruta `$default` que manda todo a tu Lambda.
El comando te devuelve un `ApiEndpoint` — esa es tu URL pública, algo como:

```
https://abc123xyz.execute-api.us-east-1.amazonaws.com
```

**Importante**: dale permiso a API Gateway para invocar tu Lambda:

```bash
aws lambda add-permission \
  --function-name finanzas-bot \
  --statement-id apigateway-access \
  --action lambda:InvokeFunction \
  --principal apigateway.amazonaws.com \
  --source-arn "arn:aws:execute-api:TU_REGION:TU_ACCOUNT_ID:*/*"
```

## 5. Configurar el webhook de Telegram (una sola vez)

```bash
export TELEGRAM_BOT_TOKEN=tu_token
python configurar_webhook.py https://abc123xyz.execute-api.us-east-1.amazonaws.com
```

Deberías ver `{'ok': True, 'result': True, 'description': 'Webhook was set'}`.

## 6. Obtener tu chat_id (igual que en la versión anterior)

Escríbele a tu bot en Telegram. Como `MY_TELEGRAM_CHAT_ID` todavía está
vacío, te va a responder con tu chat_id. Cópialo y actualiza la variable de
entorno en tu función Lambda (no hace falta re-subir el código, solo
actualizar la variable):

```bash
aws lambda update-function-configuration \
  --function-name finanzas-bot \
  --environment "Variables={ANTHROPIC_API_KEY=...,TELEGRAM_BOT_TOKEN=...,MY_TELEGRAM_CHAT_ID=TU_CHAT_ID,DYNAMODB_TABLE=finanzas_bot}"
```

## 7. Programar los resúmenes automáticos con EventBridge Scheduler

A diferencia de los cron jobs que vivían dentro del proceso (como en la
versión con polling), aquí un servicio externo de AWS "despierta" tu
función Lambda en el horario que definas — la función ni siquiera está
corriendo mientras tanto, por eso es gratis de verdad.

```bash
# Resumen semanal: domingos 8:00 PM hora Bogota
aws scheduler create-schedule \
  --name finanzas-resumen-semanal \
  --schedule-expression "cron(0 20 ? * SUN *)" \
  --schedule-expression-timezone "America/Bogota" \
  --target "Arn=arn:aws:lambda:TU_REGION:TU_ACCOUNT_ID:function:finanzas-bot,RoleArn=arn:aws:iam::TU_ACCOUNT_ID:role/TU_ROL_DE_SCHEDULER,Input='{\"accion\":\"resumen_semanal\"}'" \
  --flexible-time-window "Mode=OFF"

# Alerta de presupuesto: todos los dias 9:00 AM hora Bogota
aws scheduler create-schedule \
  --name finanzas-alerta-presupuesto \
  --schedule-expression "cron(0 9 * * ? *)" \
  --schedule-expression-timezone "America/Bogota" \
  --target "Arn=arn:aws:lambda:TU_REGION:TU_ACCOUNT_ID:function:finanzas-bot,RoleArn=arn:aws:iam::TU_ACCOUNT_ID:role/TU_ROL_DE_SCHEDULER,Input='{\"accion\":\"alerta_presupuesto\"}'" \
  --flexible-time-window "Mode=OFF"
```

`EventBridge Scheduler` (a diferencia de las reglas clásicas de CloudWatch
Events) soporta zonas horarias directamente con
`--schedule-expression-timezone`, así que no hay que convertir manualmente a
UTC. El `RoleArn` del scheduler necesita permiso `lambda:InvokeFunction`
sobre tu función — es un rol de IAM aparte, con esa única política.

## 8. Comandos que entiende el bot

Son exactamente los mismos que en las versiones anteriores — nada cambió a
nivel de lo que le puedes escribir:

| Escribes | Qué hace |
|---|---|
| `gaste 25000 en almuerzo` | Registra un gasto |
| `compre 50000 en almuerzo con tarjeta de credito` | Registra el gasto y el medio de pago |
| `me pagaron 2 millones de sueldo` | Registra un ingreso |
| `ahorre 100 mil para el carro` | Ahorra hacia un fondo |
| `retirar 200000 del carro` | Retira de un fondo |
| `resumen semanal` / `como voy` | Balance de los últimos 7 días |
| `resumen mensual` / `proyeccion` | Proyección de cierre de mes |
| `definir presupuesto comida 600000` | Presupuesto por categoría |
| `definir presupuesto general 3000000` | Presupuesto total del mes |
| `definir fondo carro 5000000` | Crear fondo de ahorro |
| `fondos` / `fondo carro` | Ver progreso de fondos |
| `definir gasto fijo arriendo 800000` | Definir gasto fijo (no se registra solo) |
| `registrar gastos fijos` | Registrar los gastos fijos pendientes del mes |
| `balance por medio de pago` | Ver gastos agrupados por efectivo/tarjeta/etc |
| `listar` / `borrar 5` / `editar 5 monto 30000` | Ver, borrar o editar transacciones |

## 9. Costo esperado

- **Lambda**: para un uso personal (unas cuantas invocaciones al día más los
  2 jobs programados), estás muy por debajo del millón de invocaciones
  gratis al mes. **$0**.
- **DynamoDB**: con el volumen de datos de un bot personal (unos cuantos
  KB), nunca te acercas a los 25 GB gratis. **$0**.
- **API Gateway**: las HTTP API tienen 1 millón de llamadas gratis al mes
  *solo durante los primeros 12 meses* de la cuenta; después cuesta
  aproximadamente $1 USD por millón de llamadas — para tu volumen personal,
  estamos hablando de fracciones de centavo, incluso pasado el año.
- **Anthropic API**: el mismo estimado de siempre, menos de $1 USD/mes.

## 10. Limitaciones de este diseño (para que las conozcas)

- **Sin indices secundarios**: todas las consultas (transacciones del mes,
  de la semana, etc.) traen TODOS los registros de ese tipo y filtran en
  Python. Para el volumen de un bot personal (cientos o pocos miles de
  transacciones a lo largo de años) esto es perfectamente eficiente y
  barato; si algún día esto creciera muchísimo (miles de transacciones por
  día), convendría rediseñar con índices secundarios globales (GSI).
- **Cold starts**: la primera invocación después de un rato sin uso tarda
  un poco más (1-2 segundos) mientras Lambda "despierta" el contenedor. Para
  un bot personal esto es imperceptible en la práctica.

## Estructura del bot en AWS
```
Webhook → es el mecanismo/dirección mediante el cual Telegram envía los eventos.
API Gateway → es la puerta de entrada HTTP que recibe esos eventos.
Lambda → es quien procesa el evento.
DynamoDB → donde guardas la información.
```

O como una analogía

```
Telegram → persona que envía una carta
Webhook → dirección de envío
API Gateway → recepción del edificio
Lambda → empleado que procesa la carta
DynamoDB → archivador donde guarda la información
```
