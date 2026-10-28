"""Вся доступная часовая история индикаторов CoinGlass (бесплатно — 180 дней, с 01.05.2026) для проверки чтения
оператора 28.10 (линии тренда по Bid&Ask Delta, фандингу, L/S аккаунтов, Whale Index 2). Тот же штатный exportData,
что у services/coinglass_web/tv_export.py, со сверкой по легенде. Пишет research/coinglass_compare/data/<SYM>_1h.csv.

    .venv/bin/python3 research/coinglass_compare/tv_history.py
"""
from __future__ import annotations

import csv
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from services.coinglass_web import tv_export  # noqa: E402

OUT = Path(__file__).resolve().parent / "data"


def main() -> None:
    from playwright.sync_api import sync_playwright
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        br = p.chromium.launch(headless=True)
        try:
            for sym in ("BTCUSDT", "ETHUSDT"):
                r = tv_export.export_symbol(br, sym, days=182)
                rows = r["rows"]
                path = OUT / f"{sym}_1h.csv"
                with open(path, "w", newline="", encoding="utf-8") as f:
                    w = csv.writer(f)
                    w.writerow(["bar_utc", *tv_export.COLUMNS])
                    for t in sorted(rows):
                        w.writerow([datetime.fromtimestamp(t, timezone.utc).isoformat(),
                                    *(rows[t].get(c) for c in tv_export.COLUMNS)])
                cov = tv_export.coverage(rows)
                print(sym, len(rows), "сверка", [c.get("ok") for c in r["checks"]], "стабильно", r["stable"],
                      {c: (v["filled"], (v["first"] or "")[:10]) for c, v in cov.items()})
        finally:
            br.close()


if __name__ == "__main__":
    main()
