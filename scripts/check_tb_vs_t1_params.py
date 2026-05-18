"""Сравнение latest GinArea params TB vs T1. Если различаются — A/B нечестный."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PARAMS_CSV = ROOT / "ginarea_live" / "params.csv"

# bot_id mapping (state/short_bots_managed.json)
T1_ID = "4729923198"
TB_ID = "4525648417"

KEY_FIELDS = ["grid_step", "max_opened_orders", "border_top", "border_bottom",
              "target", "leverage", "side"]
JSON_KEYS = ["q.minQ", "q.maxQ", "q.qr", "slp.tp", "gap.minS", "gap.maxS",
             "gap.tog", "in.otc", "tr.tr", "ttp", "ttpinc"]


def _get_nested(d: dict, dotted: str):
    cur = d
    for part in dotted.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def main():
    print(f"Loading {PARAMS_CSV.name}...")
    df = pd.read_csv(PARAMS_CSV)
    df["ts"] = pd.to_datetime(df["ts_utc"], format="ISO8601", errors="coerce", utc=True)
    df = df.dropna(subset=["ts"])

    t1_rows = df[df.bot_id.astype(str).str.split(".").str[0] == T1_ID]
    tb_rows = df[df.bot_id.astype(str).str.split(".").str[0] == TB_ID]
    if t1_rows.empty:
        print(f"FAIL: no T1 params (bot_id {T1_ID})")
        return
    if tb_rows.empty:
        print(f"FAIL: no TB params (bot_id {TB_ID})")
        return
    t1 = t1_rows.sort_values("ts").iloc[-1]
    tb = tb_rows.sort_values("ts").iloc[-1]

    print(f"\nT1 latest snapshot: {t1.ts}  alias={t1.bot_name.strip()}")
    print(f"TB latest snapshot: {tb.ts}  alias={tb.bot_name.strip()}")

    print(f"\n{'─'*70}")
    print(f"  Field-by-field comparison")
    print(f"{'─'*70}")
    print(f"{'field':25} {'T1':>20} {'TB':>20}  match?")

    mismatches = []
    for fld in KEY_FIELDS:
        v1 = t1.get(fld)
        v2 = tb.get(fld)
        match = (str(v1) == str(v2))
        mark = "✓" if match else "✗"
        print(f"{fld:25} {str(v1):>20} {str(v2):>20}  {mark}")
        if not match:
            mismatches.append((fld, v1, v2))

    # JSON params (deeper structure)
    try:
        t1_json = json.loads(t1.raw_params_json)
        tb_json = json.loads(tb.raw_params_json)
    except (json.JSONDecodeError, KeyError):
        print("\nWARNING: raw_params_json parse failed for one of bots")
        return

    print(f"\n{'─'*70}")
    print(f"  Deep JSON fields (raw_params_json)")
    print(f"{'─'*70}")
    print(f"{'field':25} {'T1':>20} {'TB':>20}  match?")
    for key in JSON_KEYS:
        v1 = _get_nested(t1_json, key)
        v2 = _get_nested(tb_json, key)
        match = (v1 == v2)
        mark = "✓" if match else "✗"
        print(f"{key:25} {str(v1):>20} {str(v2):>20}  {mark}")
        if not match:
            mismatches.append((key, v1, v2))

    # in.start.cnds (trigger condition)
    t1_cnds = _get_nested(t1_json, "in.start.cnds")
    tb_cnds = _get_nested(tb_json, "in.start.cnds")
    cnds_match = (t1_cnds == tb_cnds)
    print(f"\nin.start.cnds trigger:")
    print(f"  T1: {json.dumps(t1_cnds, ensure_ascii=False)}")
    print(f"  TB: {json.dumps(tb_cnds, ensure_ascii=False)}")
    print(f"  match: {'✓' if cnds_match else '✗'}")
    if not cnds_match:
        mismatches.append(("in.start.cnds", t1_cnds, tb_cnds))

    print(f"\n{'='*70}")
    if not mismatches:
        print(f"  ✓ TB ↔ T1 параметры ИДЕНТИЧНЫ — A/B fair")
    else:
        print(f"  ✗ Различий: {len(mismatches)}")
        print(f"  A/B comparison будет НЕ честный пока параметры не совпадут.")
        print(f"\n  Действие: в GinArea UI открой бот TB ({tb.bot_name.strip()}) и подкрути:")
        for fld, v1, v2 in mismatches:
            print(f"    {fld}: текущий={v2}  →  должно быть как у T1={v1}")


if __name__ == "__main__":
    main()
