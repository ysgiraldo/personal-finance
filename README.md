# Bot de Finanzas Personales (Python + Flask + Twilio + Claude)

Misma idea que la versión en Node.js: recibes SMS con tus movimientos en
lenguaje natural ("gaste 25000 en almuerzo"), Claude los interpreta, se
guardan en SQLite, y el bot te dice cómo vas frente a tus presupuestos y
metas.

## 1. Crear entorno virtual e instalar dependencias

```bash
cd finanzas-bot-py
python3 -m venv venv
source venv/bin/activate      # en Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## 2. Configurar variables de entorno

```bash
cp .env.example .env
```

Edita `.env` y llena:
- `ANTHROPIC_API_KEY`: tu API key de Anthropic (console.anthropic.com).
- `TWILIO_ACCOUNT_SID` y `TWILIO_AUTH_TOKEN`: desde el dashboard de Twilio.
- `TWILIO_PHONE_NUMBER`: el número que compraste en Twilio.
- `MY_PHONE_NUMBER`: tu número personal, con código de país (ej. `+57...`).

## 3. Probar la lógica SIN necesidad de Twilio (recomendado primero)

```bash
python -m app.server
```

En otra terminal:

```bash
curl -X POST http://localhost:3000/test \
  -H "Content-Type: application/json" \
  -d '{"texto": "gaste 25000 en almuerzo"}'
```

Deberías ver algo como:
```json
{ "respuesta": "Registrado: $25.000 (gasto) en comida.\nLlevas $25.000 de $600.000 en comida este mes (4%)." }
```

Prueba también los comandos especiales:
```bash
curl -X POST http://localhost:3000/test -H "Content-Type: application/json" \
  -d '{"texto": "definir presupuesto comida 600000"}'

curl -X POST http://localhost:3000/test -H "Content-Type: application/json" \
  -d '{"texto": "resumen semanal"}'

curl -X POST http://localhost:3000/test -H "Content-Type: application/json" \
  -d '{"texto": "resumen mensual"}'
```

## 4. Conectar con Twilio de verdad (SMS reales)

1. Compra un número con SMS en la consola de Twilio.
2. Para probar en local, instala [ngrok](https://ngrok.com/) y corre:
   ```bash
   ngrok http 3000
   ```
   Esto te da una URL pública tipo `https://xxxx.ngrok-free.app`.
3. En la consola de Twilio, en la configuración del número, en el campo
   **"A message comes in"**, pon: `https://xxxx.ngrok-free.app/sms` (método POST).
4. Guarda, y ya puedes mandarle un SMS real a tu número de Twilio desde tu celular.

> Nota: ngrok es solo para desarrollo local. Para producción, despliega en
> Render, Railway o un VPS, y usa esa URL fija en la configuración de Twilio.

## 5. Corriendo en producción (Gunicorn en vez del servidor de desarrollo)

El servidor de desarrollo de Flask (`app.run(...)`) no está pensado para
producción. Para desplegar, usa Gunicorn:

```bash
pip install gunicorn
gunicorn -w 1 -b 0.0.0.0:3000 "app.server:app"
```

Importante: usa **`-w 1`** (un solo worker). Si usas más de un worker, cada
uno arrancaría su propio scheduler y los cron jobs (resumen semanal, alertas)
se duplicarían.

## 6. Comandos que entiende el bot

| Escribes | Qué hace |
|---|---|
| `gaste 25000 en almuerzo` | Registra un gasto (el LLM interpreta monto y categoría) |
| `me pagaron 2 millones de sueldo` | Registra un ingreso |
| `ahorre 100 mil` | Registra un ahorro |
| `resumen semanal` o `como voy` | Balance de los últimos 7 días |
| `resumen mensual` o `proyeccion` | Proyección de cierre de mes por categoría |
| `definir presupuesto comida 600000` | Define/actualiza el límite mensual de una categoría |
| `definir ahorro 2000000 2027-03-01` | Define una meta de ahorro con fecha objetivo |

## 7. Resúmenes y alertas automáticas

`app/scheduler.py` deja configurados dos jobs con APScheduler (el equivalente
en Python a `node-cron`):
- **Resumen semanal**: domingos a las 8:00 PM (hora de Bogotá).
- **Alerta de presupuesto**: todos los días a las 9:00 AM, pero solo te
  escribe si alguna categoría va camino a superarse.

## Diferencias clave frente a la versión en Node.js

- SQLite viene incluido en Python (`sqlite3`), no se necesita ninguna
  librería externa como `better-sqlite3`.
- Los cron jobs usan **APScheduler** en vez de `node-cron`.
- El modelo configurado por defecto es **Haiku** (más barato), en vez de
  Sonnet, porque la tarea de clasificar monto/categoría no necesita el
  modelo más potente.

## Próximos pasos sugeridos (no incluidos en este prototipo)

- Fecha de inicio real para la meta de ahorro (para calcular si vas
  "adelantado o atrasado" con precisión, no solo el mes actual).
- Editar/borrar un registro por error (ej. "borra el ultimo gasto").
- Desplegar en un servicio gratuito (Render/Railway) con un ping periódico
  (UptimeRobot/cron-job.org) para que el cron semanal no se pierda si el
  servicio está dormido.
