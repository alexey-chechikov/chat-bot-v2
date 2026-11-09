from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import pickle

import numpy as np
import pandas as pd

from replay_inputs import ROOT, OLD, build
from replay_paths import PROJECT_ROOT, bootstrap_project, ensure_original_sources

bootstrap_project()
from services.btc_signals import engine as new_engine


def old_module(name, rel):
    spec = importlib.util.spec_from_file_location(name, OLD / rel)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def key(e):
    return (int(e["pos"]["entry_t"]), e["tag"], e["side"])


def main():
    ensure_original_sources()
    old_engine = old_module("original_engine", "services/btc_signals/engine.py")
    ref = pd.read_csv(OLD / "research/chart_walk_20261105/out/trade_table_btc.csv", sep=";", decimal=",")
    cache, checks = {}, []
    for venue in ("Binance", "Bitstamp"):
        a, lay, h4f, fund = build(venue, source_root=OLD)
        b, new_lay, _, _ = build(venue, source_root=PROJECT_ROOT)
        assert np.array_equal(a["t"], b["t"])
        assert all(np.allclose(a[name], b[name], equal_nan=True) for name in ["c", "h", "l", "f_G", "f_Y", "f_R", "f_B", "atr4"])
        assert all(np.allclose(x, y, equal_nan=True) for x, y in zip(lay, new_lay))
        old_ev, old_pos = old_engine.simulate(a, lay)
        new_ev, new_pos = new_engine.simulate(b, new_lay)
        old432, old_p432, _ = old_engine.simulate432(a)
        new432, new_p432, _ = new_engine.simulate432(b)
        old_tr = {key(e): e for e in old_ev + old432 if e["kind"] == "выход"}
        new_tr = {key(e): e for e in new_ev + new432 if e["kind"] == "выход"}
        assert old_tr.keys() == new_tr.keys()
        selected = ref[ref["ряд"] == venue]
        assert len(old_tr) == len(selected), (venue, len(old_tr), len(selected))
        diffs = []
        for _, row in selected.iterrows():
            t0 = int(pd.Timestamp(row["вход UTC"], tz="UTC").timestamp())
            tag = row["тип"].split(" ", 1)[1]
            e = old_tr[(t0, tag, int(row["сторона"]))]
            assert e["t"] == int(pd.Timestamp(row["выход UTC"], tz="UTC").timestamp())
            diffs.append(abs(e["res"] - row["итог, % базы"]))
        assert max(diffs) < .000051
        checks.append({"venue": venue, "matched_trades": len(old_tr), "max_published_rounding_error": max(diffs),
                       "old_no_funding": sum(e["res"] for e in old_tr.values()),
                       "new_no_funding": sum(e["res"] for e in new_tr.values()),
                       "add_state_changed": sum(old_tr[k]["pos"]["add_done"] != new_tr[k]["pos"]["add_done"] for k in old_tr)})
        cache[venue] = {"old_a": a, "a": b, "lay": lay, "h4f": h4f, "fund": fund,
                        "old_trades": old_tr, "trades": new_tr,
                        "old_events": old_ev + old432, "events": new_ev + new432,
                        "open_positions": [new_pos, new_p432]}
        print(checks[-1], flush=True)
    with (ROOT / "replay_cache.pkl").open("wb") as handle:
        pickle.dump(cache, handle, protocol=pickle.HIGHEST_PROTOCOL)
    (ROOT / "replay_reconciliation.json").write_text(json.dumps(checks, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
