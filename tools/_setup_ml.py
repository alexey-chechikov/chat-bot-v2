"""Setup ML on 3 bands + price + VOLUME only (operator's spec, 2026-06-07).
Features: where green(TEMA50)/yellow(TEMA100)/red(TEMA200) sit vs price, HOW the cross happened
(age, direction, speed of green×yellow), price behaviour (ROC, consecutive candles), and VOLUME
(spike z, trend). Gradient boosting finds the combinations. Strict time-split OOS (learn past,
test unseen future). Reports OOS AUC + accuracy vs baseline + which feature carries the signal."""
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "backtests" / "frozen" / "BTCUSDT_1h_2y.csv"
N_FWD = 18  # 3 days


def tema(s, n):
    e1 = s.ewm(span=n, adjust=False).mean(); e2 = e1.ewm(span=n, adjust=False).mean()
    e3 = e2.ewm(span=n, adjust=False).mean(); return 3 * e1 - 3 * e2 + e3


def main():
    df = pd.read_csv(SRC)
    df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    df = df.set_index("ts").resample("4h").agg({"close": "last", "volume": "sum"}).dropna()
    c, v = df["close"], df["volume"]
    t50, t100, t200 = tema(c, 50), tema(c, 100), tema(c, 200)

    fm = t50 - t100                                   # green vs yellow (the cross axis)
    cross_sign = np.sign(fm)
    cross_age = cross_sign.groupby((cross_sign != cross_sign.shift()).cumsum()).cumcount()
    consec = np.sign(c.diff())
    consec_run = consec.groupby((consec != consec.shift()).cumsum()).cumcount()

    F = pd.DataFrame({
        "d_green":  (c - t50) / c * 100,              # price vs green band
        "d_yellow": (c - t100) / c * 100,             # price vs yellow band
        "d_red":    (c - t200) / c * 100,             # price vs red band
        "cross_dir":   cross_sign,                    # green above/below yellow
        "cross_age":   cross_age,                     # bars since green×yellow crossed
        "cross_speed": (fm - fm.shift(6)) / c * 100,  # how fast the cross is widening
        "roc6":   (c / c.shift(6) - 1) * 100,         # price behaviour 1d
        "roc18":  (c / c.shift(18) - 1) * 100,        # price behaviour 3d
        "consec": consec * consec_run,                # signed run of same-dir candles
        "vol_z":  (v - v.rolling(60).mean()) / v.rolling(60).std(),   # volume spike
        "vol_trend": v / v.rolling(60).mean(),        # volume vs its average
    })
    fwd = (c.shift(-N_FWD) / c - 1) * 100
    y = (fwd > 0).astype(int)
    data = F.copy(); data["y"] = y; data = data.dropna()
    n = len(data); split = int(n * 0.70)
    Xtr, ytr = data.iloc[:split, :-1], data.iloc[:split, -1]
    Xte, yte = data.iloc[split:, :-1], data.iloc[split:, -1]
    print(f"bars {n}  learn {len(Xtr)} / test {len(Xte)} (unseen future)  horizon {N_FWD*4}h\n")

    try:
        from sklearn.ensemble import GradientBoostingClassifier
        from sklearn.metrics import roc_auc_score, accuracy_score
    except Exception as e:
        print("sklearn нет:", e); return
    m = GradientBoostingClassifier(n_estimators=150, max_depth=3, learning_rate=0.05,
                                   subsample=0.8, random_state=0)
    m.fit(Xtr, ytr)
    ptr = m.predict_proba(Xtr)[:, 1]; pte = m.predict_proba(Xte)[:, 1]
    print("=== РЕЗУЛЬТАТ (gradient boosting на 3 полосы + цена + объём) ===")
    print(f"  IN-SAMPLE AUC:  {roc_auc_score(ytr, ptr):.3f}   acc {accuracy_score(ytr, ptr>0.5):.2f}")
    print(f"  OOS AUC:        {roc_auc_score(yte, pte):.3f}   acc {accuracy_score(yte, pte>0.5):.2f}")
    print(f"  baseline (доля up в тесте): {yte.mean():.2f}  (0.50 AUC = монетка)")
    imp = pd.Series(m.feature_importances_, index=Xtr.columns).sort_values(ascending=False)
    print("\n  важность фич (что модель сочла главным):")
    for k, val in imp.items():
        print(f"    {k:12} {val:.3f}")


if __name__ == "__main__":
    main()
