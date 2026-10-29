"""Замечания GPT a7d799b §6.1 к book_on_rise: (1) «зелёный = не красный» — сколько часов стакан ровно 0; (2) правда ли у
альтов стакан «почти всегда зелёный» — доля наблюдаемых часов с bid_ask_delta > 0 / < 0 / = 0 и доля 6-часовых окон
«≥5 из 6 > 0» и «≥5 из 6 < 0», по монетам. Только описание, без отбора.

    .venv/bin/python3 research/indicator_atlas/book_sign_share.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from research.indicator_atlas import atlas  # noqa: E402

out = {}
for sym in atlas.available():
    b = atlas.load(sym)["bid_ask_delta"].astype(float)
    obs = b.notna()
    pos, neg, zero = (b > 0).sum(), (b < 0).sum(), (b == 0).sum()
    green6 = (b > 0).astype(float).where(obs).rolling(6, min_periods=6).sum()
    red6 = (b < 0).astype(float).where(obs).rolling(6, min_periods=6).sum()
    n6 = int(green6.notna().sum())
    out[sym] = {"hours": int(obs.sum()), "pos": float(pos / obs.sum()), "neg": float(neg / obs.sum()), "zero": int(zero),
                "green5of6": float((green6 >= 5).sum() / n6), "red5of6": float((red6 >= 5).sum() / n6),
                "notred_le1": float((red6 <= 1).sum() / n6)}
    r = out[sym]
    print(f"{sym:9s} часов {r['hours']}: >0 {r['pos']:.0%}, <0 {r['neg']:.0%}, ровно 0 — {r['zero']}; окна 6 ч: "
          f"зелёных ≥5/6 {r['green5of6']:.0%}, красных ≥5/6 {r['red5of6']:.0%}, «красных ≤1» {r['notred_le1']:.0%}")
(Path(__file__).resolve().parent / "book_sign_share_result.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
