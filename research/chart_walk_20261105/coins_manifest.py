"""Манифест данных новых монет: строки, первый и последний бар, sha256. Сами данные не в git, fetch_coins.py и portrait_holdout2.py скачивают их заново с публичного API Binance."""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import fetch_coins as fc  # noqa: E402
import portrait_holdout2 as p2  # noqa: E402
import pos  # noqa: E402


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    rows = []
    for c in fc.COINS + p2.COINS2:
        b, f = fc.DIR / f"{c}USDT_1h.csv", fc.DIR / f"{c}USDT_funding.csv"
        d, r = pd.read_csv(b), pd.read_csv(f)
        rows.append({"монета": c, "партия": 1 if c in fc.COINS else 2, "баров": len(d), "первый": pd.Timestamp(d["ms"].iloc[0], unit="ms"), "последний": pd.Timestamp(d["ms"].iloc[-1], unit="ms"), "sha256_баров": sha(b), "выплат": len(r), "sha256_фандинга": sha(f)})
    t = pd.DataFrame(rows)
    t.to_csv(pos.OUT / "coins_manifest.csv", index=False)
    print(t.drop(columns=["sha256_баров", "sha256_фандинга"]).to_string(index=False))


if __name__ == "__main__":
    main()
