"""Train the pump_freeze resume-gate GBM — Phase 4 model artifact, per-symbol.

Loads the per-symbol Phase-1 event catalog, trains a depth-3 GBM on the 9
train_final features to predict whipsaw (class 1) vs trend (class 0), reports
out-of-time AUC, and freezes:
  models/{SYMBOL}_pump_resume_gbm.joblib
  models/{SYMBOL}_pump_resume_gbm.meta.json

The production model is trained on ALL trend/whipsaw events; OOT splits are
generalisation checks (train older slice, test newer slice).

Usage:
    .venv/bin/python3 scripts/pump_research/train_resume_model.py
    .venv/bin/python3 scripts/pump_research/train_resume_model.py --symbol ETHUSDT
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import joblib
import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.metrics import roc_auc_score

ROOT = Path("/Users/alexeychechikov/code/bot7")

# FINAL 9-feature contract (train_final, 9b7577d) — order is the model's
# feature_order; build_live_features() emits exactly this set.
FEATURES = ["accel", "funding_at_anchor", "move_pct", "move_t5", "move_t15",
            "move_t30", "move_t60", "vol_spike", "wick_ratio"]

GBM_PARAMS = dict(max_depth=3, n_estimators=150, learning_rate=0.05,
                  subsample=0.9, min_samples_leaf=10, random_state=42)

WHIPSAW_THR = 0.65
TREND_THR = 0.35
HORIZON_MIN = 60


def _paths(symbol: str) -> tuple[Path, Path, Path]:
    return (
        ROOT / "state" / f"{symbol}_pump_event_catalog.csv",
        ROOT / "models" / f"{symbol}_pump_resume_gbm.joblib",
        ROOT / "models" / f"{symbol}_pump_resume_gbm.meta.json",
    )


def _oot_auc(df: pd.DataFrame, frac_train: float) -> tuple[float, int, int]:
    cut = int(len(df) * frac_train)
    tr, te = df.iloc[:cut], df.iloc[cut:]
    m = GradientBoostingClassifier(**GBM_PARAMS)
    # fit on .values — model stores no feature names, so predicting with a
    # plain list (resume_model.score_event) raises no sklearn warning.
    m.fit(tr[FEATURES].values, tr["y"].values)
    auc = roc_auc_score(te["y"], m.predict_proba(te[FEATURES].values)[:, 1])
    return auc, len(tr), len(te)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="BTCUSDT")
    args = ap.parse_args()
    sym = args.symbol
    catalog, model_out, meta_out = _paths(sym)

    df = pd.read_csv(catalog)
    df = df[df["outcome"].isin(["trend", "whipsaw"])].copy()
    df = df.sort_values("anchor_ts").reset_index(drop=True)
    df["y"] = (df["outcome"] == "whipsaw").astype(int)  # class 1 = whipsaw
    before = len(df)
    df = df.dropna(subset=FEATURES + ["y"]).reset_index(drop=True)
    print(f"{sym} catalog: {before} trend/whipsaw events, {len(df)} after dropna")
    print(f"  class balance: whipsaw={int(df['y'].sum())} trend={int((1-df['y']).sum())}")

    auc60, ntr60, nte60 = _oot_auc(df, 0.60)
    auc50, ntr50, nte50 = _oot_auc(df, 0.50)
    print(f"OOT AUC 60/40: {auc60:.4f}  (train {ntr60}, test {nte60})")
    print(f"OOT AUC 50/50: {auc50:.4f}  (train {ntr50}, test {nte50})")

    # production model — trained on ALL events for this symbol
    final = GradientBoostingClassifier(**GBM_PARAMS)
    final.fit(df[FEATURES].values, df["y"].values)
    imp = sorted(zip(FEATURES, final.feature_importances_),
                 key=lambda x: -x[1])
    print("feature importances:")
    for name, v in imp:
        print(f"  {name:20s} {v:.3f}")

    # also a per-direction OOT split, since LONG bots run on the down side
    for d in ("up", "down"):
        sub = df[df["direction"] == d]
        if len(sub) < 20:
            continue
        cut = int(len(sub) * 0.60)
        m = GradientBoostingClassifier(**GBM_PARAMS)
        m.fit(sub.iloc[:cut][FEATURES].values, sub.iloc[:cut]["y"].values)
        te = sub.iloc[cut:]
        auc_d = roc_auc_score(te["y"], m.predict_proba(te[FEATURES].values)[:, 1])
        print(f"  per-direction OOT 60/40 {d:4}: n={len(sub)} AUC={auc_d:.4f}")

    model_out.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(final, model_out)
    meta = {
        "symbol": sym,
        "feature_order": FEATURES,
        "live_grade_used": "reliable",
        "horizon_min": HORIZON_MIN,
        "whipsaw_threshold": WHIPSAW_THR,
        "trend_threshold": TREND_THR,
        "oot_auc": round(float(auc60), 4),
        "oot_auc_50_50": round(float(auc50), 4),
        "n_events": int(len(df)),
        "model": "GradientBoostingClassifier " + json.dumps(GBM_PARAMS),
        "trained_on": f"state/{sym}_pump_event_catalog.csv",
        "trained_by": "Mac-Claude — Phase B/C per-symbol model",
    }
    meta_out.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"\nsaved: {model_out.name} ({model_out.stat().st_size} bytes) + meta.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
