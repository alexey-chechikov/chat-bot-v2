"""Phase B/C dry-run — verify all 3 trained models (BTC/ETH/XRP) load via
resume_model and score real catalog events sensibly per symbol."""
import os
import sys

ROOT = "/Users/alexeychechikov/code/bot7"
os.chdir(ROOT)
sys.path.insert(0, ROOT)

import pandas as pd  # noqa: E402

from services.pump_freeze import resume_model  # noqa: E402

resume_model._reset_cache()
for sym in ("BTCUSDT", "ETHUSDT", "XRPUSDT"):
    print(f"\n=== {sym} ===")
    print(f"  model_available: {resume_model.model_available(sym)}")
    print(f"  horizon_min: {resume_model.horizon_min(sym)}")
    _, meta = resume_model._load(sym)
    feats = meta.get("feature_order", [])
    print(f"  feature_order ({len(feats)}): {feats}")
    print(f"  oot_auc: {meta.get('oot_auc')}  n_events: {meta.get('n_events')}")

    df = pd.read_csv(f"{ROOT}/state/{sym}_pump_event_catalog.csv")
    df = df[df["outcome"].isin(["trend", "whipsaw"])]
    print("  in-sample smoke (mean P(whipsaw) by actual outcome):")
    for oc in ("trend", "whipsaw"):
        sub = df[df["outcome"] == oc].dropna(subset=feats)
        scores = []
        for _, row in sub.iterrows():
            s = resume_model.score_event({k: row[k] for k in feats}, sym)
            if s is not None:
                scores.append(s)
        mean = sum(scores) / len(scores) if scores else float("nan")
        print(f"    {oc:8s} n={len(scores):4d}  mean P(whipsaw)={mean:.3f}")
