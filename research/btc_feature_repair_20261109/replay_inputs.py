"""Portable, read-only reconstruction of the original bar/indicator pipeline.

Exact pure functions are loaded from the selected source snapshot by AST, avoiding
private scratchpad imports. Hourly OHLCV sources are local public-data caches;
this is independently reconciled with the published trade list before use.
"""
from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

from replay_paths import LAB_ROOT, PROJECT_ROOT, ORIGINAL_SOURCE, DATA_DIR, bootstrap_project, ensure_original_sources

bootstrap_project()
ROOT = LAB_ROOT
OLD = ORIGINAL_SOURCE
DATA = DATA_DIR


def functions(source, names, env):
    tree = ast.parse(Path(source).read_text(encoding="utf-8"))
    selected = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    assert len(selected) == len(names), (source, names)
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(source), "exec"), env)
    return SimpleNamespace(**{name: env[name] for name in names})


def funding():
    d = pd.read_csv(DATA / "um_BTCUSDT_funding.csv")
    tail = ROOT / "funding_tail.csv"
    if tail.exists():
        x = pd.read_csv(tail)
        d = pd.concat([d, pd.DataFrame({"ms": x["fundingTime"], "rate": x["fundingRate"]})], ignore_index=True)
    t = (d["ms"].to_numpy(np.int64) // 60000) * 60
    assert (np.diff(t) > 0).all()
    return pd.Series(d["rate"].to_numpy(float), index=t)


def load_hourly(venue):
    if venue == "Binance":
        d = pd.read_csv(DATA / "spot_BTCUSDT_1h.csv")
        tail = ROOT / "spot_hour_tail.csv"
        if tail.exists():
            x = pd.read_csv(tail).rename(columns={"open_ms": "ms"})
            d = pd.concat([d, x], ignore_index=True)
        d["ts"] = d["ms"].to_numpy(np.int64) // 1000
    else:
        d = pd.read_csv(DATA / "bitstamp_btcusd_1h.csv")
        d["ts"] = d["timestamp"].to_numpy(np.int64)
        d = d[d["close"] > 0].copy()
    assert d["ts"].is_monotonic_increasing and not d["ts"].duplicated().any()
    return d


def build(venue="Binance", source_root=OLD, state=True):
    src = Path(source_root)
    if src.resolve() == OLD:
        ensure_original_sources()
    cwdir = src / "research/chart_walk_20261105"
    mdpath = PROJECT_ROOT / "research/market_regimes_20261102/mr_data.py"
    env = {"np": np, "pd": pd}
    md = functions(mdpath, ["bars", "ema", "tema", "rma", "zone_v11", "add_ind"], dict(env))
    cwenv = dict(env, LINES=("G", "Y", "R", "B"))
    cw = functions(cwdir / "cw_data.py", ["run_len", "asof", "roll_rank", "features", "T"], cwenv)
    d = load_hourly(venue)
    h1, h4 = md.add_ind(md.bars(d, 3600)), md.add_ind(md.bars(d, 14400))
    day = md.bars(d, 86400)
    h1f, h4f = cw.features(h1, h4, 1), cw.features(h4, h1, 4)
    rates = funding() if venue == "Binance" else pd.Series([0.0], index=[1356998400])
    jr = functions(cwdir / "journal.py", ["wilder", "add_extra"], dict(env))
    ru = functions(cwdir / "rules.py", ["prepare"], dict(env))
    er = functions(cwdir / "entry_rules.py", ["prep"], dict(env, jr=jr, rules=ru, cw=cw))
    a, h4f = er.prep(h1f, h4f, day, rates)
    a["i0"] = int(np.searchsorted(a["t"], cw.T("2018-01-01" if venue == "Binance" else "2014-01-01")))
    wd = functions(cwdir / "words.py", ["add_runs"], dict(env, cw=cw))
    wd.add_runs(a)
    if state:
        ec = functions(cwdir / "entry_common.py", ["extras"], dict(env, DAY=24))
        sm = functions(cwdir / "state_map.py", ["since", "add_state"], dict(env, ec=ec, H5D=120, FLAT_B4=.5))
        sm.add_state(a)
    pl = functions(cwdir / "plus.py", ["layer"], dict(env, H4=14400, YEAR=2190))
    return a, pl.layer(a), h4f, rates


if __name__ == "__main__":
    import importlib.util
    ensure_original_sources()
    spec = importlib.util.spec_from_file_location("old_engine", OLD / "services/btc_signals/engine.py")
    old = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(old)
    ref = pd.read_csv(OLD / "research/chart_walk_20261105/out/trade_table_btc.csv", sep=";", decimal=",")
    for venue in ("Binance", "Bitstamp"):
        a, lay, _, _ = build(venue)
        ev, _ = old.simulate(a, lay)
        e432, _, _ = old.simulate432(a)
        rows = []
        for e in ev + e432:
            if e["kind"] == "выход":
                rows.append({"вход UTC": pd.Timestamp(e["pos"]["entry_t"], unit="s").strftime("%Y-%m-%d %H:%M"),
                             "тип": ("лонг " if e["side"] == 1 else "шорт ") + e["tag"],
                             "calc": e["res"], "exit": e["t"]})
        out = pd.DataFrame(rows)
        merged = ref[ref["ряд"] == venue].merge(out, on=["вход UTC", "тип"], how="outer", indicator=True)
        both = merged[merged["_merge"] == "both"]
        print(venue, "ref", len(ref[ref["ряд"] == venue]), "replay", len(out), "matched", len(both),
              "max PnL difference", (both["calc"] - both["итог, % базы"]).abs().max(),
              "sum reference/replay", both["итог, % базы"].sum(), both["calc"].sum(), flush=True)
        merged.to_csv(ROOT / ("replay_reconciliation_" + venue + ".csv"), index=False)
