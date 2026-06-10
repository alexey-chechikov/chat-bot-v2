"""Диагностика Bot API: getMe + getWebhookInfo (read-only, апдейты не потребляет)."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import config
import requests

base = f"https://api.telegram.org/bot{config.BOT_TOKEN}"
for method in ("getMe", "getWebhookInfo"):
    r = requests.get(f"{base}/{method}", timeout=10)
    print(method, "→", json.dumps(r.json(), ensure_ascii=False, indent=1)[:600], "\n")
