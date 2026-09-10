# Bot de Finanzas Personales (Python + Telegram + Claude)

Misma lógica que las versiones anteriores, pero conectada por Telegram en vez
de SMS/Twilio: gratis, sin verificación de negocio, y sin necesidad de ngrok
para probarlo (usa "polling" en vez de webhook).

## 1. Crear el bot en Telegram (2 minutos)

1. Abre Telegram y busca **@BotFather** (el bot oficial para crear bots).
2. Escríbele `/newbot`.
3. Te va a pedir un nombre para mostrar (ej. "Mis Finanzas") y un username
   único que debe terminar en `bot` (ej. `misfinanzas_sofia_bot`).
4. BotFather te va a dar un **token** parecido a
   `123456789:AAxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx`. Ese es tu `TELEGRAM_BOT_TOKEN`.

## 2. Instalar dependencias

```bash
cd finanzas-bot-telegram
python3 -m venv venv
source venv/bin/activate      # en Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## 3. Configurar variables de entorno

```bash
cp .env.example .env
```

Edita `.env` y llena:
- `ANTHROPIC_API_KEY`: tu API key de Anthropic.
- `TELEGRAM_BOT_TOKEN`: el que te dio BotFather.
- `MY_TELEGRAM_CHAT_ID`: **déjalo vacío por ahora**, lo llenamos en el siguiente paso.

## 4. Primera corrida: obtener tu chat_id

```bash
python -m app.telegram_bot
```

Abre Telegram, busca tu bot por el username que le pusiste, y mándale
cualquier mensaje (ej. "hola"). El bot te va a responder con algo como:

```
Tu chat_id es: 987654321

Copialo en tu archivo .env como MY_TELEGRAM_CHAT_ID y reinicia el bot
para que solo tu puedas usarlo.
```

Copia ese número en tu `.env`:
```
MY_TELEGRAM_CHAT_ID=987654321
```

Este paso es importante por seguridad: sin esto, el bot le respondería a
**cualquier persona** que lo encuentre en Telegram y le escriba. Con el
chat_id configurado, solo tú puedes usarlo.

## 5. Reiniciar y usar de verdad

Detén el bot (`Ctrl+C`) y vuelve a correrlo:

```bash
python -m app.telegram_bot
```

Ahora ya puedes escribirle normalmente:

```
gaste 25000 en almuerzo
```
```
resumen semanal
```
```
definir presupuesto comida 600000
```

## 6. Comandos que entiende el bot

| Escribes | Qué hace |
|---|---|
| `gaste 25000 en almuerzo` | Registra un gasto (el LLM interpreta monto y categoría) |
| `me pagaron 2 millones de sueldo` | Registra un ingreso |
| `ahorre 100 mil para el carro` | Registra un ahorro hacia el fondo "carro" (si no dices un fondo, usa "general") |
| `resumen semanal` o `como voy` | Balance de los últimos 7 días |
| `resumen mensual` o `proyeccion` | Proyección de cierre de mes por categoría |
| `definir presupuesto comida 600000` | Define/actualiza el límite mensual de una categoría |
| `definir presupuesto general 3000000` | Define un tope total de gasto mensual (todas las categorías) |
| `definir fondo carro 5000000 2027-06-01` | Crea un fondo de ahorro con nombre, meta y fecha (ambas opcionales) |
| `fondos` o `mis fondos` | Lista todos tus fondos con su progreso |
| `fondo carro` | Progreso de un fondo específico |
| `borrar fondo carro` | Elimina la definición de un fondo (el historial ahorrado se conserva) |
| `definir gasto fijo arriendo 800000 vivienda` | Registra un gasto fijo recurrente (categoría opcional) |
| `registrar gastos fijos` | Registra ya mismo los gastos fijos pendientes de este mes como transacciones reales |
| `borrar gasto fijo arriendo` | Elimina un gasto fijo definido (deja de registrarse a futuro) |
| `gastos fijos` | Lista tus gastos fijos definidos y qué % de tus ingresos representan |
| `listar` o `listar 20` | Muestra tus últimas transacciones con su id (por defecto 10) |
| `borrar 5` | Borra la transacción con id 5 |
| `borrar ultimo` | Borra la transacción más reciente |
| `editar 5 monto 30000` | Corrige el monto de la transacción con id 5 |
| `editar 5 categoria transporte` | Corrige la categoría de la transacción con id 5 |

## 7. Cómo funcionan los fondos de ahorro

En vez de una sola meta de ahorro genérica, puedes tener varios fondos con nombre propio (carro, estudio, fondo de emergencia, etc.):

1. Los defines con `definir fondo <nombre> <meta opcional> <fecha opcional>`.
2. Cuando registras un ahorro (`ahorre 100 mil para el carro`), el LLM detecta el fondo destino a partir de lo que escribiste. Si no mencionas ninguno, se guarda bajo el fondo `"general"`.
3. `fondos` te muestra el progreso de todos; `fondo carro` te muestra solo uno.
4. El dinero se va acumulando indefinidamente (no se reinicia cada mes, a diferencia de los presupuestos) — tiene sentido porque una meta de ahorro es algo que construyes a lo largo de varios meses.

## 8. Cómo funcionan los gastos fijos automáticos

1. Los defines una sola vez con `definir gasto fijo <nombre> <monto> <categoria opcional>`.
2. **El primer día de cada mes a las 8:00 AM**, el bot revisa todos tus gastos fijos y crea automáticamente la transacción de ese mes por cada uno — así sí cuentan dentro de tus presupuestos, proyecciones y resúmenes, como cualquier otro gasto.
3. Si quieres que se registren antes de esa fecha (por ejemplo, para probar ahora mismo), escribe `registrar gastos fijos` — es seguro escribirlo varias veces, nunca duplica lo que ya se registró ese mes.
4. `gastos fijos` (sin la palabra "registrar") sigue mostrando el listado de definiciones y qué porcentaje de tus ingresos representan, independientemente de si ya se registraron como transacción este mes.

## 9. Resúmenes y alertas automáticas

`app/telegram_bot.py` deja configurados tres jobs con el `JobQueue` propio de la librería (usa APScheduler por debajo, pero ya integrado):
- **Resumen semanal**: domingos a las 8:00 PM (hora de Bogotá).
- **Alerta de presupuesto**: todos los días a las 9:00 AM, solo si hay riesgo de superar algún presupuesto.
- **Registro de gastos fijos**: el día 1 de cada mes a las 8:00 AM.

Estos jobs solo se activan si `MY_TELEGRAM_CHAT_ID` ya está configurado.

## Diferencias clave frente a la versión con Twilio/SMS

- **Sin costo por mensaje**: la API de bots de Telegram es 100% gratuita.
- **Sin ngrok para desarrollo**: usamos "polling" (`app.run_polling()`), el
  bot pregunta activamente a Telegram por mensajes nuevos, no necesita una
  URL pública. Para producción también puedes cambiar a webhook si quieres,
  pero polling funciona bien incluso desplegado.
- **Autenticación por chat_id** en vez de número de teléfono — mismo
  concepto de seguridad (solo tú puedes usar el bot), solo cambia el dato
  que se compara.
- Ya no se usa Flask ni Gunicorn: `app/telegram_bot.py` es un script que
  corre directamente con `python -m app.telegram_bot` (para producción,
  igual conviene correrlo con un supervisor de procesos, ver abajo).

## 10. Desplegarlo para que corra 24/7

Como no depende de un webhook HTTP expuesto, desplegarlo es aún más simple:
en Render/Railway, en vez de un "Web Service" usas un **"Background Worker"**
(o su equivalente) que simplemente corre `python -m app.telegram_bot` de
forma continua. No necesitas configurar ninguna URL pública ni dominio.

## Próximos pasos sugeridos (no incluidos en este prototipo)

- Fecha de inicio real para la meta de ahorro (para calcular si vas
  "adelantado o atrasado" con precisión).
- Editar/borrar un registro por error (ej. "borra el ultimo gasto").
- Comandos nativos de Telegram con botones (`/start`, `/ayuda`) en vez de
  solo texto libre, usando `CommandHandler` de la misma librería.
