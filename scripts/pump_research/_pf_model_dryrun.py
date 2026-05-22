"""Phase 4 dry-run — verify the trained resume-gate artifact loads through
resume_model and scores real catalog events sensibly (whipsaw should score
higher P(whipsaw) than trend). No live bot touched."""
import os
import sys

ROOT = "/Users/alexeychechikov/code/bot7"
os.chdir(ROOT)
sys.path.insert(0, ROOT)

import pandas as pd  # noqa: E402

from services.pump_freeze import resume_model  # noqa: E402

resume_model._reset_cache()
print(f"model_available: {resume_model.model_available()}")
print(f"horizon_min: {resume_model.horizon_min()}")
_, meta = resume_model._load()
feats = meta.get("feature_order", [])
print(f"feature_order ({len(feats)}): {feats}")
print(f"oot_auc: {meta.get('oot_auc')}")

df = pd.read_csv(ROOT + "/state/pump_event_catalog.csv")
df = df[df["outcome"].isin(["trend", "whipsaw"])]
print("in-sample smoke (mean P(whipsaw) by actual outcome):")
for oc in ("trend", "whipsaw"):
    sub = df[df["outcome"] == oc].dropna(subset=feats)
    scores = [resume_model.score_event({k: row[k] for k in feats})
              for _, row in sub.iterrows()]
    scores = [s for s in scores if s is not None]
    mean = sum(scores) / len(scores) if scores else float("nan")
    print(f"  {oc:8s} n={len(scores):3d}  mean P(whipsaw)={mean:.3f}")

# one concrete score path
sample = df.dropna(subset=feats).iloc[0]
s = resume_model.score_event({k: sample[k] for k in feats})
print(f"sample score_event -> {s:.3f}  gate={resume_model.gate_decision(s)}")
