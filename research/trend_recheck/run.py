"""Прогон протокола docs/TREND_4H_RECHECK_PROTOCOL_2026-10-15.md (commit b048207; дополнение §7а — 6ed43ad) целиком.

  .venv/bin/python3 research/trend_recheck/run.py [--scratch DIR]

1) sha256 входов сверяются с out/data_manifest.json (и сам manifest — с закреплённым sha256) — до использования;
   протокол: версия b048207 — та, по которой готовились данные, рабочий файл = 6ed43ad, разница — только вставка §7а.
2) analyze() — весь конвейер на одном наборе минут: базовая ячейка ETH, XRP, портфель ETH+XRP, BTC (вне решения) на
   P1 / P2 / всём ряду; ×2 проскальзывание, C2 без ADX, 16 ячеек LB×K, смещения якоря 01/02/03, задержка +5 мин, без
   аварийного стопа — полные повторные прогоны тем же циклом replay.run(); C1 999 повторов (seed 20261015), трети P1,
   бутстрап по ISO-неделям, разбивка выходов, воронка, совместная кривая и просадка, ворота и статус.
3) Основной расчёт — минуты как есть (дыры XRP остаются). Чувствительность §7а — тот же analyze() на ряду, где у XRP
   5 дней дыр взяты из дневных архивов (xrp_fill.py, только в памяти). Ворота и статус — по основному расчёту.
4) Живое против бэктеста (live_check.py) — по основному расчёту.
5) out/: ledger, события, c1_reps, summary.json, results_manifest.json; затем report.py → docs/…RESULTS….md.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
import time
from dataclasses import asdict, replace
from pathlib import Path

import numpy as np

import live_check
import replay as rp
import stats as st
import xrp_fill

DATA_MANIFEST = rp.OUT / "data_manifest.json"
DATA_MANIFEST_SHA = "8a2464cccd1a8dc0308078137498d195f8c2e0172b14ff2b3d9de4d288eca66a"
PROTOCOL_SHA_7A = "35f2bd42905f66129587863966ea2c710900e3f0b9610aa470b4e7ef88ccad97"   # файл после 6ed43ad
SCRATCH = Path("/private/tmp/claude-501/-Users-alexeychechikov/2d0b9f1e-cee7-410e-8e42-97e17a0b8d1a/scratchpad")
REPS = 999
PERIODS = ("P1", "P2", "full")
SCOPES = {"ETHUSDT": ("ETHUSDT",), "XRPUSDT": ("XRPUSDT",), "PORT": rp.DECISION, "BTCUSDT": ("BTCUSDT",)}
SCRIPTS = ["research/trend_recheck/replay.py", "research/trend_recheck/stats.py", "research/trend_recheck/run.py",
           "research/trend_recheck/live_check.py", "research/trend_recheck/report.py",
           "research/trend_recheck/selfcheck.py", "research/trend_recheck/xrp_fill.py",
           "research/trend_recheck/fetch_um_daily.py", "research/trend_recheck/build_early.py", "tools/trend_state.py",
           "scripts/ohlc_grid.py", "tests/research_trend/tr_fx.py", "tests/research_trend/test_tr_execution.py",
           "tests/research_trend/test_tr_stats_data.py", "tests/research_trend/test_tr_fill.py"]


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def _git_show(commit: str, rel: str) -> bytes:
    return subprocess.run(["git", "-C", str(rp.ROOT), "show", f"{commit}:{rel}"], check=True,
                          capture_output=True).stdout


def verify_protocol(dm: dict) -> dict:
    """b048207 — версия, по которой готовились данные (sha в data_manifest); рабочий файл — ровно 6ed43ad; между ними —
    только вставка раздела §7а (правила и параметры §1–§7 не тронуты)."""
    import hashlib
    rel = str(rp.PROTOCOL.relative_to(rp.ROOT))
    cur = rp.PROTOCOL.read_bytes()
    old = _git_show(rp.PROTOCOL_COMMIT, rel)
    new = _git_show(rp.ADDENDUM_COMMIT, rel)
    h_old, h_cur = hashlib.sha256(old).hexdigest(), hashlib.sha256(cur).hexdigest()
    if h_old != dm["protocol_sha256"]:
        raise SystemExit(f"протокол {rp.PROTOCOL_COMMIT}: sha256 {h_old} ≠ data_manifest {dm['protocol_sha256']}")
    if cur != new or h_cur != PROTOCOL_SHA_7A:
        raise SystemExit(f"рабочий файл протокола ≠ {rp.ADDENDUM_COMMIT} (sha256 {h_cur})")
    text = cur.decode("utf-8")
    a = re.search(r"^## 7\S\. Дополнение", text, re.M)
    b = re.search(r"^## 8\. ", text, re.M)
    if not a or not b or (text[:a.start()] + text[b.start():]).encode("utf-8") != old:
        raise SystemExit("дополнение протокола — не только вставка раздела §7а")
    return {"b048207": h_old, "6ed43ad_working_file": h_cur, "diff": "только вставка §7а"}


def verify_inputs() -> tuple[dict, dict]:
    got = rp.sha256(DATA_MANIFEST)
    if got != DATA_MANIFEST_SHA:
        raise SystemExit(f"data_manifest.json sha256 {got} ≠ закреплённого {DATA_MANIFEST_SHA}")
    dm = json.loads(DATA_MANIFEST.read_text(encoding="utf-8"))
    if dm.get("protocol_commit") != rp.PROTOCOL_COMMIT:
        raise SystemExit("manifest не от протокола b048207")
    proto = verify_protocol(dm)
    checked = {}
    for sym in rp.SYMBOLS:
        mm = dm["minutes"][sym]
        for part in ("P1_early", "P2_existing"):
            f, want = mm[part]["file"], mm[part]["sha256"]
            h = rp.sha256(rp.ROOT / f)
            if h != want:
                raise SystemExit(f"{f}: sha256 {h} ≠ manifest {want}")
            checked[f] = h
        if not mm["seam_2024_05_15_31"]["ok"] or not mm["join"]["continuous_no_gap_no_overlap"]:
            raise SystemExit(f"{sym}: шов P1/P2 в manifest не ок")
        f, want = dm["funding"][sym]["file"], dm["funding"][sym]["sha256"]
        h = rp.sha256(rp.ROOT / f)
        if h != want:
            raise SystemExit(f"{f}: sha256 {h} ≠ manifest {want}")
        checked[f] = h
    checked["research/trend_recheck/out/data_manifest.json"] = got
    checked[str(rp.PROTOCOL.relative_to(rp.ROOT))] = proto["6ed43ad_working_file"]
    return checked, proto


def summarize(trades_by_sym: dict[str, list[dict]]) -> dict:
    out = {}
    for scope, syms in SCOPES.items():
        tr = [t for s in syms for t in trades_by_sym.get(s, [])]
        out[scope] = {p: st.block(st.in_period(tr, p)) for p in PERIODS}
    return out


def ledger_rows(trades: list[dict]) -> list[dict]:
    rows = []
    for t in sorted(trades, key=lambda z: (z["sym"], z["entry_ts"])):
        rows.append({"sym": t["sym"], "period": t["period"], "side": t["side"],
                     "signal_bar_utc": rp.iso(t["signal_bar"]), "entry_utc": rp.iso(t["entry_ts"]),
                     "exit_utc": rp.iso(t["exit_ts"]), "E": t["E"], "entry_fill": t["entry_fill"],
                     "chandelier0": t["ch0"], "trigger0": t["trig0"], "qty": t["qty"], "exit_price_raw": t["exit_raw"],
                     "exit_fill": t["exit_fill"], "exit_kind": t["kind"], "R": t["R"], "R_gross": t["R_gross"],
                     "pnl_net": t["net"], "gross": t["gross"], "fee_in": t["fee_in"], "fee_out": t["fee_out"],
                     "funding": t["funding"], "funding_n": t["funding_n"], "risk_usd": t["risk"],
                     "n_ratchet": t["n_ratchet"], "last_trigger": t["last_trig"], "deferred_exits": t["deferred_exits"],
                     "incomplete_bars_in_trade": t["incomplete_bars_in_trade"], "censored": t["censored"],
                     "entry_ts": t["entry_ts"], "exit_ts": t["exit_ts"]})
    return rows


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields = list(dict.fromkeys(k for r in rows for k in r))
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def c1_run(series: dict, trades: dict, cands: dict, literal: bool, independent: bool = False) -> dict:
    """999 повторов, один генератор seed 20261015; порядок символов в повторе ETH, XRP, BTC."""
    strata = {s: rp.c1_strata(cands[s]) for s in rp.SYMBOLS}
    keys = {s: rp.template_keys(series[s], trades[s], cands[s]) for s in rp.SYMBOLS}
    rng = np.random.default_rng(st.SEED)
    sums = {(s, p): np.zeros(REPS) for s in rp.SYMBOLS for p in (0, 1)}
    cnts = {(s, p): np.zeros(REPS) for s in rp.SYMBOLS for p in (0, 1)}
    durs = {(s, p): np.zeros(REPS) for s in rp.SYMBOLS for p in (0, 1)}
    dropped = {s: np.zeros(REPS) for s in rp.SYMBOLS}
    cens = {s: np.zeros(REPS) for s in rp.SYMBOLS}
    for r in range(REPS):
        for s in rp.SYMBOLS:
            got, dr = rp.c1_replicate(strata[s], keys[s], rng, literal=literal, independent=independent)
            dropped[s][r] = dr
            for R, _net, c, per, dur in got:
                if c:
                    cens[s][r] += 1
                    continue
                sums[(s, per)][r] += R
                cnts[(s, per)][r] += 1
                durs[(s, per)][r] += dur
    res = {"templates": {s: len(keys[s]) for s in rp.SYMBOLS},
           "candidates": {s: int(len(cands[s]["rows"])) for s in rp.SYMBOLS},
           "atr_terciles": {s: cands[s]["terciles"] for s in rp.SYMBOLS},
           "dropped_mean": {s: float(dropped[s].mean()) for s in rp.SYMBOLS},
           "dropped_max": {s: int(dropped[s].max()) for s in rp.SYMBOLS},
           "censored_mean": {s: float(cens[s].mean()) for s in rp.SYMBOLS}, "means": {}, "trades_mean": {},
           "duration_bars_mean": {}}
    for scope, syms in SCOPES.items():
        for pi, pname in ((0, "P1"), (1, "P2")):
            sm = sum(sums[(s, pi)] for s in syms)
            cn = sum(cnts[(s, pi)] for s in syms)
            du = sum(durs[(s, pi)] for s in syms)
            with np.errstate(invalid="ignore", divide="ignore"):
                mean = np.where(cn > 0, sm / np.maximum(cn, 1), np.nan)
            res["means"][f"{scope}_{pname}"] = mean
            res["trades_mean"][f"{scope}_{pname}"] = float(cn.mean())
            res["duration_bars_mean"][f"{scope}_{pname}"] = float(du.sum() / cn.sum()) if cn.sum() else None
    return res


def c1_rank(means: np.ndarray, strat_mean: float | None) -> dict:
    if strat_mean is None:
        return {"rank": None}
    ok = np.isfinite(means)
    k = int(np.sum(means[ok] >= strat_mean)) + int(np.sum(~ok))     # повтор без сделок — не в пользу стратегии
    return {"rank": (k + 1) / (REPS + 1), "k": k, "reps": REPS, "reps_without_trades": int(np.sum(~ok)),
            "control_mean_of_means": float(np.nanmean(means)) if ok.any() else None,
            "control_p95": float(np.nanquantile(means, 0.95)) if ok.any() else None, "strategy_mean": strat_mean}


def c1_pool(cands: dict) -> dict:
    """Диагностика: все кандидаты C1 (каждая полная свеча после прогрева × обе стороны, сделка тем же циклом) —
    среднее R и R до расходов и фандинга, по символу, периоду и стороне. Объясняет знак среднего контроля."""
    out = {}
    for scope, syms in SCOPES.items():
        a = np.concatenate([cands[s]["rows"] for s in syms])
        a = a[a[:, 5] == 0]
        for pi, pname in ((0, "P1"), (1, "P2")):
            for d, dn in ((0, "both"), (1, "LONG"), (-1, "SHORT")):
                sel = (a[:, 7] == pi) & ((a[:, 1] == d) if d else True)
                b = a[sel]
                out[f"{scope}_{pname}_{dn}"] = {"n": int(len(b)), "mean_R": float(b[:, 3].mean()) if len(b) else None,
                                                "mean_R_gross": float(b[:, 10].mean()) if len(b) else None}
    return out


def xrp_trade_diff(a: list[dict], b: list[dict]) -> dict:
    """Сделки базы XRP: основной ряд против ряда §7а — по (вход, сторона)."""
    ka = {(t["entry_ts"], t["d"]): t for t in a}
    kb = {(t["entry_ts"], t["d"]): t for t in b}

    def row(t):
        return {"side": t["side"], "entry_utc": rp.iso(t["entry_ts"]), "exit_utc": rp.iso(t["exit_ts"]),
                "kind": t["kind"], "R": t["R"], "net": t["net"], "period": t["period"]}

    changed = []
    for k in sorted(set(ka) & set(kb)):
        x, y = ka[k], kb[k]
        if (x["exit_ts"], x["kind"], x["exit_raw"], x["qty"]) != (y["exit_ts"], y["kind"], y["exit_raw"], y["qty"]) \
                or abs(x["net"] - y["net"]) > 1e-9:
            changed.append({"primary": row(x), "filled": row(y)})
    return {"only_primary": [row(ka[k]) for k in sorted(set(ka) - set(kb))],
            "only_filled": [row(kb[k]) for k in sorted(set(kb) - set(ka))], "changed": changed,
            "same": len(set(ka) & set(kb)) - len(changed)}


def build_variants() -> dict:
    variants = {"base": rp.BASE, "slip2": replace(rp.BASE, slip=0.0004), "c2_no_adx": replace(rp.BASE, adx_min=None),
                "delay5": replace(rp.BASE, delay_min=5), "no_emergency": replace(rp.BASE, emergency=False)}
    for lb in (20, 30, 45, 60):
        for k in (2.0, 2.5, 3.0, 4.0):
            variants[f"cell_lb{lb}_k{k:g}"] = replace(rp.BASE, lb=lb, k=k)
    for h in (1, 2, 3):
        variants[f"offset_{h:02d}"] = replace(rp.BASE, offset_h=h)
    return variants


def analyze(minutes: dict, funding: dict, label: str, want_events: bool) -> dict:
    """Весь конвейер протокола §2–§6 на одном наборе минут."""
    base_series, data_end = {}, {}
    for s in rp.SYMBOLS:
        m = minutes[s]
        valid = rp.valid_mask(m["o"], m["h"], m["l"], m["c"], m["v"])
        data_end[s] = rp.data_end_ms(m["ts"], m["o"], m["h"], m["l"], m["c"], valid)
        base_series[s] = rp.Series(s, m["ts"], m["o"], m["h"], m["l"], m["c"], m["v"], offset_h=0,
                                   funding=funding[s], end_ms=data_end[s])
    cache = {(s, 0): base_series[s] for s in rp.SYMBOLS}

    def series_for(sym: str, off: int) -> rp.Series:
        if (sym, off) not in cache:
            m = minutes[sym]
            cache[(sym, off)] = rp.Series(sym, m["ts"], m["o"], m["h"], m["l"], m["c"], m["v"], offset_h=off,
                                          funding=funding[sym], end_ms=data_end[sym])
        return cache[(sym, off)]

    variants = build_variants()
    runs, funnels, events = {}, {}, {s: [] for s in rp.SYMBOLS}
    for name, cfg in variants.items():
        runs[name], funnels[name] = {}, {}
        for s in rp.SYMBOLS:
            out = rp.run(series_for(s, cfg.offset_h), cfg, events[s] if (name == "base" and want_events) else None)
            runs[name][s] = out["trades"]
            funnels[name][s] = out["funnel"]
        log(f"[{label}] прогон {name}: " + ", ".join(f"{s[:3]} {len(runs[name][s])}" for s in rp.SYMBOLS))
    base = runs["base"]
    summ = {name: summarize(runs[name]) for name in runs}
    if summ["cell_lb30_k3"] != summ["base"]:
        raise SystemExit("ячейка (30, 3) не совпала с базой — цикл не детерминирован")

    log(f"[{label}] C1: кандидаты и 999 повторов")
    cands = {s: rp.c1_candidates(base_series[s]) for s in rp.SYMBOLS}
    c1 = c1_run(base_series, base, cands, literal=False)
    c1_lit = c1_run(base_series, base, cands, literal=True)
    c1_ind = c1_run(base_series, base, cands, literal=False, independent=True)
    c1_ranks, c1_lit_ranks, c1_ind_ranks = {}, {}, {}
    for key in c1["means"]:
        scope, per = key.rsplit("_", 1)
        c1_ranks[key] = c1_rank(c1["means"][key], summ["base"][scope][per]["mean_R"])
        c1_lit_ranks[key] = c1_rank(c1_lit["means"][key], summ["base"][scope][per]["mean_R"])
        c1_ind_ranks[key] = c1_rank(c1_ind["means"][key], summ["base"][scope][per]["mean_R"])
    strat_dur = {}
    for scope, syms in SCOPES.items():
        for pname in ("P1", "P2"):
            tr = st.done([t for s in syms for t in st.in_period(base[s], pname)])
            strat_dur[f"{scope}_{pname}"] = (float(np.mean([t["exit_bar"] - t["signal_bar_idx"] for t in tr]))
                                             if tr else None)
    reps_rows = [{"rep": r, **{k: (float(v[r]) if np.isfinite(v[r]) else None) for k, v in c1["means"].items()}}
                 for r in range(REPS)]

    log(f"[{label}] бутстрап, трети, кривая капитала")
    end_all = max(data_end.values())
    ci = {}
    for scope, syms in SCOPES.items():
        for p, (a, b) in (("P1", (st.P1_START, st.P1_END)), ("P2", (st.P1_END, end_all)),
                          ("full", (st.P1_START, end_all))):
            tr = st.done([t for s in syms for t in st.in_period(base[s], p)])
            ci[f"{scope}_{p}"] = st.weekly_ci([t["entry_ts"] for t in tr], [t["R"] for t in tr], a, b)
    tr = st.done([t for s in rp.DECISION for t in st.in_period(runs["slip2"][s], "P1")])
    ci["slip2_PORT_P1"] = st.weekly_ci([t["entry_ts"] for t in tr], [t["R"] for t in tr], st.P1_START, st.P1_END)
    thirds = {scope: st.thirds([t for s in syms for t in st.in_period(base[s], "P1")]) for scope, syms in SCOPES.items()}
    thirds_slip2 = st.thirds([t for s in rp.DECISION for t in st.in_period(runs["slip2"][s], "P1")])
    mk = {}
    for s in rp.SYMBOLS:
        S = base_series[s]
        mk[s] = {"bend": S.bend, "bc": S.bc, "f_t": S.f_t, "f_cum": np.concatenate([[0.0], np.cumsum(S.f_mark * S.f_rate)])}
    equity = {}
    for vname in ("base", "no_emergency", "slip2"):
        for scope, syms in SCOPES.items():
            for p in PERIODS:
                tr = [t for s in syms for t in st.in_period(runs[vname][s], p)]
                grid, eq = st.equity_curve(tr, {s: mk[s] for s in syms})
                equity[f"{vname}_{scope}_{p}"] = st.max_dd(grid, eq)
    last365 = {}
    for vname in ("base", "no_emergency"):
        cut = end_all - 365 * rp.DAY
        tr = [t for s in rp.DECISION for t in runs[vname][s] if t["entry_ts"] >= cut]
        last365[vname] = {**st.block(tr), "from_utc": rp.iso(cut)}

    exits = {scope: {p: st.exits([t for s in syms for t in st.in_period(base[s], p)]) for p in PERIODS}
             for scope, syms in SCOPES.items()}
    reentry, keep_live = {}, {}
    for s in rp.SYMBOLS:
        starts = {i for i, _, _ in rp.live_episodes(base_series[s], rp.BASE)}
        r_in = [t for t in base[s] if t["signal_bar_idx"] not in starts]
        keep_live[s] = [t for t in base[s] if t["signal_bar_idx"] in starts]
        reentry[s] = {p: sum(1 for t in r_in if p == "full" or t["period"] == p) for p in PERIODS}
        reentry[s]["mean_R_P1"] = (float(np.mean([t["R"] for t in r_in if t["period"] == "P1" and not t["censored"]]))
                                   if any(t["period"] == "P1" and not t["censored"] for t in r_in) else None)
    without_reentry = summarize(keep_live)
    funnel_period = {}
    for s in rp.SYMBOLS:
        ev = events[s]
        funnel_period[s] = {}
        for p in ("P1", "P2"):
            sel = [e for e in ev if (e["ts"] < rp.P1_END) == (p == "P1")]
            funnel_period[s][p] = {k: sum(1 for e in sel if e["event"] == k) for k in
                                   ("entry", "skip_beyond_chandelier", "skip_qty0", "skip_data_end",
                                    "signal_on_incomplete_bar")}

    P = summ["base"]["PORT"]
    g = {"mean_R": P["P1"]["mean_R"], "mean_R_slip2": summ["slip2"]["PORT"]["P1"]["mean_R"], "n": P["P1"]["n"],
         "weeks_nonempty": ci["PORT_P1"]["weeks_nonempty"], "ci_all": ci["PORT_P1"]["all"],
         "third3_mean_R": thirds["PORT"][2]["mean_R"], "third3_n": thirds["PORT"][2]["n"],
         "p2_mean_R": P["P2"]["mean_R"], "p2_n": P["P2"]["n"],
         "neighbors": {"(20,3)": summ["cell_lb20_k3"]["PORT"]["P1"]["mean_R"],
                       "(45,3)": summ["cell_lb45_k3"]["PORT"]["P1"]["mean_R"],
                       "(30,2.5)": summ["cell_lb30_k2.5"]["PORT"]["P1"]["mean_R"],
                       "(30,4)": summ["cell_lb30_k4"]["PORT"]["P1"]["mean_R"]},
         "offsets": {"00": P["P1"]["mean_R"], **{f"{h:02d}": summ[f"offset_{h:02d}"]["PORT"]["P1"]["mean_R"]
                                                   for h in (1, 2, 3)}},
         "c1_rank": c1_ranks["PORT_P1"]["rank"]}
    gate_rows = st.gates(g)
    status = st.status(g["mean_R"], g["n"], gate_rows)
    log(f"[{label}] статус по воротам: {status}")
    c1_out = {k: v for k, v in c1.items() if k != "means"}
    c1_lit_out = {k: v for k, v in c1_lit.items() if k != "means"}
    c1_ind_out = {k: v for k, v in c1_ind.items() if k != "means"}
    packed = {
        "status": status, "gates": gate_rows, "gate_values": g,
        "data": {s: {"first_minute_utc": rp.iso(int(minutes[s]["ts"][0])), "data_end_utc": rp.iso(data_end[s]),
                     "bars": int(base_series[s].nb), "incomplete_bars": int((~base_series[s].complete).sum()),
                     "p1_rows": int(minutes[s]["p1_rows"]), "p2_rows": int(minutes[s]["p2_rows"]),
                     "funding_settlements_used": int(len(base_series[s].f_t)),
                     "funding_mark_from_close": int(base_series[s].f_mark_from_close)} for s in rp.SYMBOLS},
        "summary": summ, "ci": ci, "thirds": thirds, "thirds_slip2_PORT": thirds_slip2,
        "thirds_bounds_utc": [[rp.iso(a), rp.iso(b)] for a, b in st.THIRDS],
        "equity_dd": equity, "last365": last365, "exits": exits, "funnel": funnels["base"],
        "funnel_by_period": funnel_period, "funnel_variants": funnels,
        "reentry_inside_live_episode": reentry, "without_reentry_diag": without_reentry,
        "c1": {**c1_out, "ranks": c1_ranks}, "c1_literal_diag": {**c1_lit_out, "ranks": c1_lit_ranks},
        "c1_independent_diag": {**c1_ind_out, "ranks": c1_ind_ranks}, "strategy_duration_bars_mean": strat_dur,
        "c1_pool_diag": c1_pool(cands),
    }
    return {"packed": packed, "runs": runs, "events": events, "series": base_series, "reps_rows": reps_rows,
            "data_end": data_end}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scratch", default=str(SCRATCH))
    args = ap.parse_args()
    t0 = time.time()
    rp.OUT.mkdir(exist_ok=True)
    log("сверка sha256 входов с data_manifest.json и протокола")
    inputs, proto = verify_inputs()
    log("загрузка минут P1+P2")
    minutes = {s: rp.read_minutes(s) for s in rp.SYMBOLS}
    funding = {s: rp.read_funding(s) for s in rp.SYMBOLS}
    A = analyze(minutes, funding, "основной", want_events=True)

    log("живое против бэктеста")
    base = A["runs"]["base"]
    live = live_check.run({s: A["series"][s] for s in rp.DECISION}, {s: base[s] for s in rp.DECISION},
                          Path(args.scratch) / "spot_snapshot")

    log("§7а: XRP с 5 днями из дневных архивов (в памяти)")
    mf = dict(minutes)
    mf["XRPUSDT"], fill_rep = xrp_fill.fill(minutes["XRPUSDT"])
    B = analyze(mf, funding, "XRP §7а", want_events=False)
    for s in ("ETHUSDT", "BTCUSDT"):
        if B["packed"]["summary"]["base"][s] != A["packed"]["summary"]["base"][s]:
            raise SystemExit(f"§7а: {s} изменился, хотя его минуты те же")
    del mf
    fill_diff = xrp_trade_diff(A["runs"]["base"]["XRPUSDT"], B["runs"]["base"]["XRPUSDT"])
    for X in (A, B):                       # диагностика: статус, если бы ворота 7 считались по другому варианту C1
        pk = X["packed"]
        for tag in ("literal", "independent"):
            g_alt = {**pk["gate_values"], "c1_rank": pk[f"c1_{tag}_diag"]["ranks"]["PORT_P1"]["rank"]}
            pk[f"status_if_c1_{tag}_diag"] = st.status(g_alt["mean_R"], g_alt["n"], st.gates(g_alt))

    # ---------------- запись
    out_files = {}
    for s in rp.SYMBOLS:
        p = rp.OUT / f"ledger_base_{s}.csv"
        write_csv(p, ledger_rows(base[s]))
        out_files[p] = None
        p = rp.OUT / f"events_base_{s}.csv"
        ev = [{"utc": rp.iso(e["ts"]), **e} for e in sorted(A["events"][s], key=lambda z: z["ts"])]
        keys = sorted({k for e in ev for k in e}, key=lambda k: (k not in ("utc", "ts", "event", "side"), k))
        ev = [{k: e.get(k) for k in keys} for e in ev]
        write_csv(p, ev)
        out_files[p] = None
    rows = []
    for name in A["runs"]:
        if name == "base":
            continue
        for r in ledger_rows([t for s in rp.SYMBOLS for t in A["runs"][name][s]]):
            rows.append({"variant": name, **r})
    p = rp.OUT / "ledger_variants.csv"
    write_csv(p, rows)
    out_files[p] = None
    p = rp.OUT / "ledger_base_XRPUSDT_filled7a.csv"
    write_csv(p, ledger_rows(B["runs"]["base"]["XRPUSDT"]))
    out_files[p] = None
    rows = []
    for name in B["runs"]:
        if name == "base":
            continue
        for r in ledger_rows(B["runs"][name]["XRPUSDT"]):
            rows.append({"variant": name, **r})
    p = rp.OUT / "ledger_variants_XRPUSDT_filled7a.csv"
    write_csv(p, rows)
    out_files[p] = None
    for tag, X in (("", A), ("_filled7a", B)):
        p = rp.OUT / f"c1_reps{tag}.csv"
        write_csv(p, X["reps_rows"])
        out_files[p] = None
    p = rp.OUT / "live_vs_backtest.csv"
    write_csv(p, live["live"])
    out_files[p] = None
    p = rp.OUT / "backtest_unmatched_live_window.csv"
    write_csv(p, live["bt_unmatched"])
    out_files[p] = None
    for extra in ("um_daily_fetch.json",):
        out_files[rp.OUT / extra] = None

    variants = build_variants()
    summary = {
        "protocol": str(rp.PROTOCOL.relative_to(rp.ROOT)), "protocol_commit": rp.PROTOCOL_COMMIT,
        "addendum_commit": rp.ADDENDUM_COMMIT, "protocol_check": proto,
        "generated_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
        **A["packed"],
        "cfg_base": asdict(rp.BASE), "variants": {k: asdict(v) for k, v in variants.items()},
        "live": live, "formalizations": rp.FORMALIZATIONS,
        "xrp_filled_7a": {**B["packed"], "fill_report": fill_rep, "xrp_trade_diff": fill_diff},
        "selfcheck": (json.loads((rp.OUT / "selfcheck.json").read_text(encoding="utf-8"))
                      if (rp.OUT / "selfcheck.json").exists() else None),
        "runtime_sec": round(time.time() - t0, 1),
    }
    if summary["selfcheck"] is not None:
        out_files[rp.OUT / "selfcheck.json"] = None
    p = rp.OUT / "summary.json"
    p.write_text(json.dumps(st.jsonable(summary), ensure_ascii=False, indent=1), encoding="utf-8")
    out_files[p] = None

    import report
    doc = report.write(json.loads(p.read_text(encoding="utf-8")))
    out_files[doc] = None
    man = {"protocol": str(rp.PROTOCOL.relative_to(rp.ROOT)), "protocol_commit": rp.PROTOCOL_COMMIT,
           "addendum_commit": rp.ADDENDUM_COMMIT, "protocol_check": proto,
           "generated_utc": summary["generated_utc"], "inputs_sha256": inputs,
           "inputs_7a_daily_archives_sha256": fill_rep["archives_sha256"],
           "live_inputs": {"state/trend_signals.jsonl": rp.sha256(live_check.JOURNAL),
                           **{v["file"]: {"snapshot_sha256": v["sha256"], "rows_used": v["rows_used"]}
                              for v in live["spot_snapshot"].values()}},
           "scripts_sha256": {f: rp.sha256(rp.ROOT / f) for f in SCRIPTS},
           "outputs_sha256": {str(k.relative_to(rp.ROOT)): rp.sha256(k) for k in out_files},
           "status": summary["status"]}
    (rp.OUT / "results_manifest.json").write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"готово за {time.time() - t0:.0f} с")


if __name__ == "__main__":
    sys.exit(main())
