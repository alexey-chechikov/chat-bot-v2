"""Дневные архивы aggTrades Binance USDⓈ-M (data.binance.vision) — сделки с флагом агрессора для footprint.

Каждый день — свой zip + файл .CHECKSUM биржи (sha256 сверяется). Архивы — внешние недоверенные данные: лежат в
backtests/aggtrades/<SYM>/ (в .gitignore), читаются только как CSV. Слово оператора 14.10: «не целый архив, недели».

    .venv/bin/python3 research/atlas_data/fetch_aggtrades_daily.py BTCUSDT 2026-08-19 2026-10-13
"""
import hashlib
import sys
import time
import urllib.request
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE = "https://data.binance.vision/data/futures/um/daily/aggTrades"


def get(url: str) -> bytes:
    for k in range(5):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "bot7"}), timeout=120).read()
        except Exception:                                   # noqa: BLE001
            if k == 4:
                raise
            time.sleep(2 ** k)


def main() -> None:
    sym, a, b = sys.argv[1], date.fromisoformat(sys.argv[2]), date.fromisoformat(sys.argv[3])
    out = ROOT / "backtests" / "aggtrades" / sym
    out.mkdir(parents=True, exist_ok=True)
    d, total, bad = a, 0, []
    while d <= b:
        name = f"{sym}-aggTrades-{d.isoformat()}.zip"
        dst = out / name
        if not dst.exists():
            blob = get(f"{BASE}/{sym}/{name}")
            want = get(f"{BASE}/{sym}/{name}.CHECKSUM").decode().split()[0]
            if hashlib.sha256(blob).hexdigest() != want:
                bad.append(name)
            else:
                dst.write_bytes(blob)
        total += dst.stat().st_size if dst.exists() else 0
        d += timedelta(days=1)
    print(f"{sym}: {(b - a).days + 1} дней, {total / 1e6:,.0f} МБ, контрольная сумма не сошлась: {bad or 'нет'}")


if __name__ == "__main__":
    main()
