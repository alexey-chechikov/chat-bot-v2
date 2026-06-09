"""Одноразово отправить оператору свежую главную клавиатуру (reply keyboard
обновляется на телефоне только сообщением с reply_markup)."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import config
import requests
from telegram_ui.keyboards import build_main_keyboard

chat = str(config.CHAT_ID).split(",")[0].strip()
kb = json.loads(build_main_keyboard().to_json())
r = requests.post(
    f"https://api.telegram.org/bot{config.BOT_TOKEN}/sendMessage",
    json={
        "chat_id": chat,
        "text": ("🔄 Клавиатура обновлена: кнопка /card — карточка-брифинг "
                 "(BTC-режим + боты + АЛЬТЫ + анализ) в любой момент.\n"
                 "/card fast — за ~2с без альт-сканера."),
        "reply_markup": kb,
    },
    timeout=10,
)
print(r.status_code, r.text[:200])
