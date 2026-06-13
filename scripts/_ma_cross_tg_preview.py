"""Отправить оператору в TG: текущий статус /ma_cross + образец карточки сигнала."""
import sys
from pathlib import Path

ROOT = Path("/Users/alexeychechikov/code/bot7")
sys.path.insert(0, str(ROOT))

import config
import requests
from services.ma_cross_shadow.report import build_status_text
from services.ma_cross_shadow.tracker import _format_card

chat = str(config.CHAT_ID).split(",")[0].strip()
sample = _format_card(dict(
    symbol="BTCUSDT", dir="LONG", passed_h5=True, skip_reasons=[],
    entry=63200.0, ema14=63100.0, ema77=62000.0, ema200=61000.0,
    stretch_pct=1.9, ew_impulse=True, ma100_lean="LONG"))

msg = ("✅ MA-CROSS H5 подключён в Telegram. Теперь по каждому кроссу EMA14×77 (4ч) по "
       "BTC/SOL/XRP сюда придёт карточка. Вот как она выглядит (образец):\n\n"
       + sample +
       "\n\n— — — — —\nТекущий статус (/ma_cross):\n\n" + build_status_text() +
       "\n\nИндикатор для графика: ma_cross_h5_v2.pine (вставь в TradingView, ставь 4ч).")

r = requests.post(f"https://api.telegram.org/bot{config.BOT_TOKEN}/sendMessage",
                  json={"chat_id": chat, "text": msg}, timeout=10)
print(r.status_code, r.text[:150])
