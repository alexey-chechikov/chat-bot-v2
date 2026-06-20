"""Публичные ID BitMEX-ключей, которые использует bot7 локально (секреты НЕ печатаем).
Для сверки со списком ключей на бирже."""
from pathlib import Path

ROOT = Path("/Users/alexeychechikov/code/bot7")
CANDIDATES = [
    ROOT / ".env.local",
    ROOT / ".env",
    ROOT / "ginarea_tracker" / ".env",
]
KEY_NAMES = {"BITMEX_API_KEY", "BITMEX_AUTOTRADER_API_KEY", "BITMEX_KEY"}

for p in CANDIDATES:
    if not p.exists():
        continue
    print(f"── {p.relative_to(ROOT)}:")
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if "=" not in line or line.startswith("#"):
            continue
        k, _, v = line.partition("=")
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if "SECRET" in k or "PASSWORD" in k or "TOTP" in k:
            print(f"   {k} = ***скрыт***")
        elif k in KEY_NAMES or "BITMEX" in k:
            print(f"   {k} = {v}")
