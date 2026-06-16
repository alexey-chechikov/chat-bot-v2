"""Отправить оператору в TG карту плотности BTC + анонс команды /levels."""
import sys
from pathlib import Path
sys.path.insert(0, "/Users/alexeychechikov/code/bot7")
import config
import requests
from services.scalp_levels.levels import build_card

chat = str(config.CHAT_ID).split(",")[0].strip()
msg = ("✅ Скальп-карта плотности подключена. Команда /levels (или /levels SOL) — "
       "карта стенок для CScalp-экрана, в любой момент.\n\nВот сейчас по BTC:\n\n"
       + build_card("BTCUSDT"))
r = requests.post(f"https://api.telegram.org/bot{config.BOT_TOKEN}/sendMessage",
                  json={"chat_id": chat, "text": msg}, timeout=12)
print(r.status_code, r.text[:120])
