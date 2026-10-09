"""Сводка сетки на объём: лонг+шорт книга вместе, по окнам, комиссиям и политике."""
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
pd.set_option("display.width", 250)
d = pd.read_json(HERE / "volume_grid_runs.jsonl", lines=True)
g = d.groupby(["sym", "step", "target", "window", "fee", "policy"]).agg(
    net=("net", "sum"), dd=("max_dd", "max"), bust=("bust", "sum"), turnover=("turnover", "sum"),
    fees=("fees", "sum"), funding=("funding", "sum"), days=("days", "first")).reset_index()
g["в месяц $"] = g.net / g.days * 30
g["оборот/мес $млн"] = g.turnover / g.days * 30 / 1e6
for fee in ("лимит+кэшбэк", "маркет+кэшбэк", "лимит без кэшбэка"):
    for pol in ("P0", "P2"):
        x = g[(g.fee == fee) & (g.policy == pol)]
        t = x.pivot_table(index=["sym", "step", "target"], columns="window", values="в месяц $").round(0)
        b = x.pivot_table(index=["sym", "step", "target"], columns="window", values="bust").astype(int)
        t["ликв (tr/val/test)"] = b["train"].astype(str) + "/" + b["validation"].astype(str) + "/" + b["test"].astype(str)
        t["оборот/мес млн (test)"] = x[x.window == "test"].set_index(["sym", "step", "target"])["оборот/мес $млн"].round(2)
        print(f"\n=== {fee}, {'без ограничения' if pol == 'P0' else 'стресс-бюджет'} — $ в месяц (лонг+шорт), депозит $3 300 ===")
        print(t[["train", "validation", "test", "full", "ликв (tr/val/test)", "оборот/мес млн (test)"]].to_string())
