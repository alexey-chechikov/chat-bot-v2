"""Does the resume-gate model work for LONG bots (down-dumps), not just
SHORT (up-pumps)? Splits the out-of-time test AUC by event direction."""
import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.metrics import roc_auc_score

CAT = "/Users/alexeychechikov/code/bot7/state/pump_event_catalog.csv"
FEATURES = ["accel", "funding_at_anchor", "move_pct", "move_t5", "move_t15",
            "move_t30", "move_t60", "vol_spike", "wick_ratio"]
PARAMS = dict(max_depth=3, n_estimators=150, learning_rate=0.05,
              subsample=0.9, min_samples_leaf=10, random_state=42)

df = pd.read_csv(CAT)
df = df[df["outcome"].isin(["trend", "whipsaw"])].sort_values("anchor_ts")
df = df.reset_index(drop=True)
df["y"] = (df["outcome"] == "whipsaw").astype(int)
df = df.dropna(subset=FEATURES + ["y"]).reset_index(drop=True)

cut = int(len(df) * 0.6)
tr, te = df.iloc[:cut], df.iloc[cut:].copy()
m = GradientBoostingClassifier(**PARAMS)
m.fit(tr[FEATURES].values, tr["y"].values)
te["p"] = m.predict_proba(te[FEATURES].values)[:, 1]

print(f"train: {len(tr)}  test: {len(te)}")
print(f"overall OOT AUC: {roc_auc_score(te['y'], te['p']):.4f}")
for d in ("up", "down"):
    s = te[te["direction"] == d]
    pos = int(s["y"].sum())
    print(f"  {d:4} (SHORT-side / LONG-side): n={len(s)}  "
          f"whipsaw={pos} trend={len(s)-pos}  "
          f"AUC={roc_auc_score(s['y'], s['p']):.4f}")
# train-set direction balance
for d in ("up", "down"):
    print(f"  train {d}: {int((tr['direction'] == d).sum())} events")
