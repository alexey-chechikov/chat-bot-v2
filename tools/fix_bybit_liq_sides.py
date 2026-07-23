"""Разовая нормализация: переворот bybit-меток в исторических ликвидациях.

Баг (найден 2026-07-23): топик bybit allLiquidation отдаёт в поле S сторону
ПОЗИЦИИ, а коллектор трактовал её как сторону ордера (sell→long, правило
старого топика liquidation). Метки bybit перевёрнуты за всю историю
(май/июнь/июль — проверено на часовых ходах цены: метка «long»
доминировала на РОСТЕ, хотя лонги выносит на падении; okx всё время
корректен). bybit даёт ~2/3 объёма, поэтому портил агрегат.

Скрипт: bybit-строки long<->short, okx/binance не трогает, бэкап рядом.
Запуск: .venv/bin/python3 tools/fix_bybit_liq_sides.py [--apply]
"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
FILES = [ROOT / "market_live" / "liquidations.csv",
         ROOT / "market_live" / "liquidations_ETHUSDT.csv",
         ROOT / "market_live" / "liquidations_XRPUSDT.csv"]
SUFFIX = ".pre-bybit-side-fix.bak"
FLIP = {"long": "short", "short": "long"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="без флага — только показать, что изменится")
    args = ap.parse_args()

    for path in FILES:
        if not path.exists():
            print(f"{path.name}: нет файла — пропуск")
            continue
        df = pd.read_csv(path)
        if "exchange" not in df or "side" not in df:
            print(f"{path.name}: нет колонок exchange/side — пропуск")
            continue
        mask = (df["exchange"] == "bybit") & df["side"].isin(FLIP)
        n = int(mask.sum())
        before = df.loc[mask, "side"].value_counts().to_dict()
        print(f"{path.name}: строк всего {len(df)}, bybit к перевороту {n} "
              f"{before}")
        if not args.apply or not n:
            continue
        backup = path.with_suffix(path.suffix + SUFFIX)
        if not backup.exists():
            shutil.copy2(path, backup)
            print(f"  бэкап → {backup.name}")
        df.loc[mask, "side"] = df.loc[mask, "side"].map(FLIP)
        df.to_csv(path, index=False)
        after = df.loc[mask, "side"].value_counts().to_dict()
        print(f"  готово: {after}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
