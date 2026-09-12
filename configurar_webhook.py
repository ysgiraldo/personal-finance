"""
Uso (una sola vez, despues de crear tu API Gateway):

    python configurar_webhook.py https://tu-api-id.execute-api.us-east-1.amazonaws.com/webhook

Requiere la variable de entorno TELEGRAM_BOT_TOKEN (puedes exportarla antes,
o cargarla desde un .env local con python-dotenv si prefieres).
"""
import sys
from app import telegram_api

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Uso: python configurar_webhook.py <url_de_tu_api_gateway>")
        sys.exit(1)

    url = sys.argv[1]
    resultado = telegram_api.configurar_webhook(url)
    print(resultado)
