#!/usr/bin/env python3
"""Helper: fetches your Telegram chat ID after you send a message to your bot."""
import sys
import requests
from dotenv import load_dotenv
import os

load_dotenv()
token = os.getenv("TELEGRAM_BOT_TOKEN", "")

if not token or token == "your_telegram_bot_token_here":
    print("ERROR: Primero pon tu TELEGRAM_BOT_TOKEN en el archivo .env")
    sys.exit(1)

print(f"Buscando mensajes del bot...")
print(f"(Asegurate de haber enviado algun mensaje a tu bot en Telegram)\n")

url = f"https://api.telegram.org/bot{token}/getUpdates"
try:
    resp = requests.get(url, timeout=10)
    data = resp.json()
except Exception as e:
    print(f"Error conectando con Telegram: {e}")
    sys.exit(1)

if not data.get("ok"):
    print(f"Telegram devolvio error: {data}")
    sys.exit(1)

results = data.get("result", [])
if not results:
    print("No hay mensajes. Envia un mensaje a tu bot en Telegram y ejecuta esto otra vez.")
    sys.exit(1)

chat_id = results[0]["message"]["chat"]["id"]
chat_name = results[0]["message"]["chat"].get("first_name", "")
print(f"Tu TELEGRAM_CHAT_ID es: {chat_id}")
print(f"Chat de: {chat_name}")
print(f"\nAhora pon este valor en tu archivo .env en la linea TELEGRAM_CHAT_ID={chat_id}")
