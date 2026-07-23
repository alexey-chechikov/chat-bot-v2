"""Замер РЕАЛЬНОЙ комиссии по закрытым ордерам GinArea.

Урок 2026-07-23: справочные ставки бирж врали. Оператор: «я всегда работал
рыночными ордерами и всегда платил 0.035%». Проверка по полю fee закрытых
ордеров подтвердила его, а не прайс (846 ордеров, разброс нулевой).
Правило: комиссию БРАТЬ ИЗ ОРДЕРОВ, а не из документации биржи.

Запуск: .venv/bin/python3 tools/measure_fees.py [--bot ID ...]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DEFAULT_BOTS = {
    "5330789037": "BTC-OKX",
    "4812772488": "ETH-OKX",
    "4499423673": "BTC-DYN (BitMEX, архив)",
    "6233908669": "ETH-DYN (BitMEX, архив)",
}
MAX_PAGES = 6


def measure(api, bot_id: str) -> dict | None:
    fees = notional_one = notional_both = 0.0
    n = 0
    for page in range(MAX_PAGES):
        try:
            d = api.get_orders(int(bot_id), only_opened=False,
                               page_number=page, page_size=100)
        except Exception as e:
            print(f"    ошибка запроса: {e}")
            break
        rows = d.get("orders") or []
        if not rows:
            break
        for o in rows:
            if o.get("isOpen"):
                continue
            try:
                q = float(o["quantity"])
                p = float(o["price"])
                cp = float(o.get("closedPrice") or p)
                f = float(o.get("fee") or 0)
            except (TypeError, ValueError, KeyError):
                continue
            if not f or not q or not p:
                continue
            fees += f
            notional_one += q * p
            notional_both += q * p + q * cp
            n += 1
    if not n or notional_one <= 0:
        return None
    # поле fee = комиссия ОДНОЙ стороны (у открытого ордера, где исполнен
    # только вход, fee уже равна 0.035% нотионала — значит выход тарифицируется
    # отдельно). Полный цикл грида = вдвое.
    side_pct = fees / notional_one * 100
    return {
        "orders": n,
        "fees": fees,
        "side_pct": side_pct,
        "cycle_pct": side_pct * 2,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bot", action="append", default=None,
                    help="bot_id (можно несколько)")
    args = ap.parse_args()
    bots = ({b: b for b in args.bot} if args.bot else DEFAULT_BOTS)

    from services.short_bots_guard.control import _build_api
    api, err = _build_api()
    if api is None:
        print("API недоступен:", err)
        return 1

    print("ФАКТИЧЕСКАЯ КОМИССИЯ (из поля fee закрытых ордеров)\n")
    for bid, alias in bots.items():
        r = measure(api, bid)
        if r is None:
            print(f"{alias:26s} закрытых ордеров с комиссией нет — "
                  f"замерить позже")
            continue
        print(f"{alias:26s} n={r['orders']:4d}  "
              f"за сторону {r['side_pct']:.4f}%  "
              f"за цикл {r['cycle_pct']:.4f}%  "
              f"(всего {r['fees']:.2f})")
    print("\nЗа сторону = поле fee / нотионал. Цикл (вход+выход) = вдвое.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
