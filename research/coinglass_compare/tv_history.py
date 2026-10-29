"""Вся доступная часовая история индикаторов CoinGlass (бесплатно — 180 дней, с 01.05.2026) для проверки чтения
оператора 28.10 (линии тренда по Bid&Ask Delta, фандингу, L/S аккаунтов, Whale Index 2) и атласа индикаторов
(research/indicator_atlas). Тот же штатный exportData, что у services/coinglass_web/tv_export.py, со сверкой по
легенде. Пишет research/coinglass_compare/data/<SYM>_1h.csv (только закрытые к моменту выгрузки бары) и
<SYM>_1h.manifest.json (время выгрузки, статус сверки, охват, sha256).

    .venv/bin/python3 research/coinglass_compare/tv_history.py [SYM ...]    # по умолчанию BTCUSDT ETHUSDT
"""
from __future__ import annotations

import csv
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from services.coinglass_web import tv_export  # noqa: E402

OUT = Path(__file__).resolve().parent / "data"


def main() -> None:
    from playwright.sync_api import sync_playwright
    syms = tuple(a.upper() for a in sys.argv[1:]) or ("BTCUSDT", "ETHUSDT")
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        br = p.chromium.launch(headless=True)
        try:
            for sym in syms:
                try:
                    r = tv_export.export_symbol(br, sym, days=182)
                except Exception as exc:                        # noqa: BLE001
                    print(sym, "сбой", f"{type(exc).__name__}: {exc}"[:200])
                    continue
                status, why = tv_export.verdict(r["stable"], r["checks"], r.get("missing"))
                obs = r["obs"].timestamp()
                rows = {t: v for t, v in r["rows"].items() if t + 3600 <= obs}     # незакрытый бар не пишем
                path = OUT / f"{sym}_1h.csv"
                with open(path, "w", newline="", encoding="utf-8") as f:
                    w = csv.writer(f)
                    w.writerow(["bar_utc", *tv_export.COLUMNS])
                    for t in sorted(rows):
                        w.writerow([datetime.fromtimestamp(t, timezone.utc).isoformat(),
                                    *(rows[t].get(c) for c in tv_export.COLUMNS)])
                cov = tv_export.coverage(rows)
                man = {"sym": sym, "obs": r["obs"].isoformat(timespec="seconds"), "status": status, "why": why,
                       "chart": {"symbol": r["export_symbol"], "resolution": r["export_resolution"]},
                       "studies": r["setup"]["names"], "legend_checks": r["checks"], "rows": len(rows),
                       "coverage": cov, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                (OUT / f"{sym}_1h.manifest.json").write_text(json.dumps(man, ensure_ascii=False, indent=1),
                                                            encoding="utf-8")
                print(sym, status, why or "", len(rows), "сверка", [c.get("ok") for c in r["checks"]],
                      {c: (v["filled"], (v["first"] or "")[:10]) for c, v in cov.items()})
        finally:
            br.close()


if __name__ == "__main__":
    main()
