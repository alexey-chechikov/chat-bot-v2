#!/usr/bin/env python3
"""Утренняя TG-карточка: BTC-режим + core-боты + альт-кандидаты + риск (одной карточкой).

Запуск:
  /Users/alexeychechikov/code/bot7/.venv/bin/python3 scripts/morning_card.py            # stdout
  /Users/alexeychechikov/code/bot7/.venv/bin/python3 scripts/morning_card.py --send     # + push в TG
  --no-scan — пропустить альт-сканер (быстро, без секции кандидатов)

Расписание: LaunchAgent com.bot7.morning-brief — каждые 4ч по Варшаве:
03/07/11/15/19/23 (= 04/08/12/16/20/00 мск).
Состояние ботов читается из выгрузки ginarea-tracker (НЕ GinArea API — сессию держит трекер).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--send", action="store_true", help="отправить карточку в TG (канал tv_webhook)")
    ap.add_argument("--no-scan", action="store_true", help="без альт-сканера")
    args = ap.parse_args()

    from services.morning_brief.card import build_morning_card
    card = build_morning_card(include_scan=not args.no_scan)
    print(card)

    if args.send:
        from services.tv_webhook.tg_notify import send_tv_signal
        ok = send_tv_signal(card)
        print(f"TG send: {'ok' if ok else 'FAILED'}", file=sys.stderr)
        return 0 if ok else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
