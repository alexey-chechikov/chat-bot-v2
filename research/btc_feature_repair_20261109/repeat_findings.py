"""Repeat the already specified quintile rules; no threshold/model search."""
from pathlib import Path
import json
import numpy as np
import pandas as pd

from replay_paths import LAB_ROOT, ORIGINAL_SOURCE, ensure_original_sources

ROOT = LAB_ROOT
OLD = ORIGINAL_SOURCE
FEATURES = ["базис 7д среднее, %", "базис фьючерс−спот, %", "фандинг 7д, %"]
MULT = np.array([.5, .75, 1., 1.25, 1.5])


def evaluate(train, test, feature, cash, clock, name):
    edges = np.quantile(train[feature], [.2, .4, .6, .8])
    q = np.searchsorted(edges, test[feature].to_numpy(float))
    m = MULT[q]
    y = test["итог, % базы"].to_numpy(float)
    rng = np.random.default_rng(91109)
    actual = float((y * m).sum())
    null = np.array([(y * rng.permutation(m)).sum() for _ in range(999)])
    ids = test["ряд"] + "|" + test["тип"] + "|" + test["вход UTC"]
    funded = cash.reindex(ids)[clock].to_numpy(float)
    strict = cash.reindex(ids).funding_complete.to_numpy(bool)
    funded_real = float((funded * m).sum())
    funded_null = np.array([(funded * rng.permutation(m)).sum() for _ in range(999)])
    return {"snapshot": name, "feature": feature, "n_train": len(train), "n_test": len(test),
            "test_start": test["вход UTC"].iloc[0], "no_funding_base": float(y.sum()),
            "no_funding_size": actual, "no_funding_delta": actual - float(y.sum()),
            "no_funding_perm_p": float((1 + (null >= actual).sum()) / 1000),
            "funding_clock": clock, "funded_observed_base": float(funded.sum()),
            "funded_observed_size": funded_real, "funded_observed_delta": funded_real - float(funded.sum()),
            "funded_observed_perm_p": float((1 + (funded_null >= funded_real).sum()) / 1000),
            "strict_funding_n_test": int(strict.sum()), "quintile_counts": np.bincount(q, minlength=5).tolist()}


def main():
    ensure_original_sources()
    cash = pd.read_csv(ROOT / "results/trade_repair_all.csv").set_index("trade_id")
    rows = []
    for name, path, clock in [
        ("original", OLD / "research/chart_walk_20261105/out/trade_table_btc.csv", "basis_bug_net_funding_proxy"),
        ("repaired", ROOT / "results/trade_table_btc_corrected.csv", "corrected_net_observed_funding_proxy"),
    ]:
        d = pd.read_csv(path, sep=";", decimal=",")
        for f in FEATURES:
            z = d[(d["ряд"] == "Binance") & (d["тип"] == "шорт под синей") & d[f].notna()].sort_values("вход UTC")
            n = len(z) // 2
            rows.append(evaluate(z.iloc[:n], z.iloc[n:], f, cash, clock, name))
        feature = "цена минус RSI в канале 30 свечей 4ч"
        train = d[(d["ряд"] == "Binance") & (d["тип"] == "шорт под жёлтой") & (d["вход UTC"] < "2023-01-01")]
        for venue in ("Binance", "Bitstamp"):
            z = d[(d["ряд"] == venue) & (d["тип"] == "шорт под жёлтой")]
            if venue == "Binance":
                z = z[z["вход UTC"] >= "2023-01-01"]
            r = evaluate(train, z, feature, cash, clock, name)
            r["test_venue"] = venue
            rows.append(r)
    (ROOT / "results/repeated_findings.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    pd.DataFrame(rows).to_csv(ROOT / "results/repeated_findings.csv", index=False)
    print(pd.DataFrame(rows).to_string(index=False))


if __name__ == "__main__":
    main()
