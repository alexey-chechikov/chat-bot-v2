"""Train the pump_freeze resume-gate GBM — the Phase-4 model artifact.

Loads the Phase-1 event catalog, trains a depth-3 GradientBoostingClassifier
on the 9 train_final features to predict whipsaw (class 1) vs trend (class 0),
reports out-of-time AUC (must reproduce Win's ~0.91), and freezes:
  models/pump_resume_gbm.joblib
  models/pump_resume_gbm.meta.json

The production model is trained on ALL trend/whipsaw events; the OOT splits
are only a generalisation check (train older slice, test newer slice).
"""
from __future__ import annotations

import json
from pathlib import Path

import joblib
import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.metrics import roc_auc_score

ROOT = Path("/Users/alexeychechikov/code/bot7")
CATALOG = ROOT / "state" / "BTCUSDT_pump_event_catalog.csv"
MODEL_OUT = ROOT / "models" / "pump_resume_gbm.joblib"
META_OUT = ROOT / "models" / "pump_resume_gbm.meta.json"

# FINAL 9-feature contract (train_final, 9b7577d) — order is the model's
# feature_order; build_live_features() emits exactly this set.
FEATURES = ["accel", "funding_at_anchor", "move_pct", "move_t5", "move_t15",
            "move_t30", "move_t60", "vol_spike", "wick_ratio"]

GBM_PARAMS = dict(max_depth=3, n_estimators=150, learning_rate=0.05,
                  subsample=0.9, min_samples_leaf=10, random_state=42)

WHIPSAW_THR = 0.65
TREND_THR = 0.35
HORIZON_MIN = 60


def _oot_auc(df: pd.DataFrame, frac_train: float) -> tuple[float, int, int]:
    cut = int(len(df) * frac_train)
    tr, te = df.iloc[:cut], df.iloc[cut:]
    m = GradientBoostingClassifier(**GBM_PARAMS)
    # fit on .values (numpy) — model stores no feature names, so predicting
    # with a plain list (resume_model.score_event) raises no sklearn warning.
    m.fit(tr[FEATURES].values, tr["y"].values)
    auc = roc_auc_score(te["y"], m.predict_proba(te[FEATURES].values)[:, 1])
    return auc, len(tr), len(te)


def main() -> int:
    df = pd.read_csv(CATALOG)
    df = df[df["outcome"].isin(["trend", "whipsaw"])].copy()
    df = df.sort_values("anchor_ts").reset_index(drop=True)
    df["y"] = (df["outcome"] == "whipsaw").astype(int)  # class 1 = whipsaw
    before = len(df)
    df = df.dropna(subset=FEATURES + ["y"]).reset_index(drop=True)
    print(f"catalog: {before} trend/whipsaw events, {len(df)} after dropna")
    print(f"  class balance: whipsaw={int(df['y'].sum())} trend={int((1-df['y']).sum())}")

    # out-of-time generalisation check (train older, test newer)
    auc60, ntr60, nte60 = _oot_auc(df, 0.60)
    auc50, ntr50, nte50 = _oot_auc(df, 0.50)
    print(f"OOT AUC 60/40: {auc60:.4f}  (train {ntr60}, test {nte60})")
    print(f"OOT AUC 50/50: {auc50:.4f}  (train {ntr50}, test {nte50})")

    # production model — trained on ALL events
    final = GradientBoostingClassifier(**GBM_PARAMS)
    final.fit(df[FEATURES].values, df["y"].values)
    imp = sorted(zip(FEATURES, final.feature_importances_),
                 key=lambda x: -x[1])
    print("feature importances:")
    for name, v in imp:
        print(f"  {name:20s} {v:.3f}")

    MODEL_OUT.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(final, MODEL_OUT)
    meta = {
        "feature_order": FEATURES,
        "live_grade_used": "reliable",
        "horizon_min": HORIZON_MIN,
        "whipsaw_threshold": WHIPSAW_THR,
        "trend_threshold": TREND_THR,
        "oot_auc": round(float(auc60), 4),
        "oot_auc_50_50": round(float(auc50), 4),
        "n_events": int(len(df)),
        "model": "GradientBoostingClassifier " + json.dumps(GBM_PARAMS),
        "trained_on": "state/pump_event_catalog.csv (Phase 1, 542 events @ 8b51acd)",
        "trained_by": "Mac-Claude — broke the artifact-ownership deadlock 2026-05-22",
    }
    META_OUT.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"\nsaved: {MODEL_OUT.name} ({MODEL_OUT.stat().st_size} bytes) + meta.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
