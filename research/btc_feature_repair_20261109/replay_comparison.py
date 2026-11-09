"""Old versus repaired results on the same 973 reconciled closed trades."""
from __future__ import annotations

from collections import Counter
import importlib.util
import json
import pickle

import numpy as np
import pandas as pd

from replay_inputs import ROOT, OLD
from replay_paths import bootstrap_project, ensure_original_sources

bootstrap_project()
from services.btc_signals import features as fx
from replay_cashflows import event_net, prepare_funding

FUND_FEATURES = ["фандинг 24ч, %", "фандинг 7д, %", "фандинг 30д, %"]
PATH_COMPARE = ["MFE, ATR", "MAE, ATR", "отдача, ATR", "сначала +1 ATR или −1 ATR", "часов в сделке",
                "ход через 24ч, %", "ход через 72ч, %", "ход через 7д, %"]


def changed(x, y, atol=0.000051):
    if pd.isna(x) and pd.isna(y):
        return False
    if pd.isna(x) or pd.isna(y):
        return True
    return abs(float(x) - float(y)) > atol


def main():
    ensure_original_sources()
    with (ROOT / "replay_cache.pkl").open("rb") as f:
        cache = pickle.load(f)
    d = pd.read_csv(OLD / "research/chart_walk_20261105/out/trade_table_btc.csv", sep=";", decimal=",")
    spec = importlib.util.spec_from_file_location("original_features", OLD / "services/btc_signals/features.py")
    old_fx = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(old_fx)
    minute = pd.read_csv(ROOT / "target_exit_minutes.csv")
    minute["hour"] = minute["open_ms"].to_numpy(np.int64) // 3600000 * 3600
    tapes = {}
    for hour, g in minute.groupby("hour"):
        tapes[int(hour + 3600)] = {"t": g["open_ms"].to_numpy(np.int64) // 1000,
                                  **{k: g[col].to_numpy(float) for k, col in zip("ohlc", ["open", "high", "low", "close"])}}
    out = ROOT / "results"
    out.mkdir(exist_ok=True)
    rows, cash_detail, totals, corrected = [], [], [], d.copy()
    for venue, data in cache.items():
        a, old_a, lay, h4f = data["a"], data["old_a"], data["lay"], data["h4f"]
        a["venue"] = venue
        old_p = old_fx.prepare(old_a, lay, h4f if venue == "Binance" else None)
        new_p = fx.prepare(a, lay, h4f if venue == "Binance" else None)
        data["fund"].attrs["venue"] = venue
        prepared_fund = prepare_funding(data["fund"])
        for ix, original in d[d["ряд"] == venue].iterrows():
            t0 = int(pd.Timestamp(original["вход UTC"], tz="UTC").timestamp())
            tag, side = original["тип"].split(" ", 1)[1], int(original["сторона"])
            old = data["old_trades"][(t0, tag, side)]
            e = data["trades"][(t0, tag, side)]
            p, i0, i1 = e["pos"], e["pos"]["entry_i"], e["i"]
            mode = "target" if e["why"].startswith("цель") else "close"
            path = fx.path(a, i0, i1, side, p["entry"], e["px"], exit_mode=mode,
                           execution=tapes.get(e["t"]) if venue == "Binance" and mode == "target" else None)
            cash_new = event_net(e, a, prepared_fund, "corrected")
            cash_old = event_net(old, a, prepared_fund, "old_event_clock")
            cash_bug = event_net(old, a, prepared_fund, "basis_bug")
            # Apply correct cash conventions to the original order state too;
            # this separates add chronology effects from accounting changes.
            cash_old_correct = event_net(old, a, prepared_fund, "corrected")
            trade_id = f"{venue}|{original['тип']}|{original['вход UTC']}"
            r = {"trade_id": trade_id, "venue": venue, "type": original["тип"],
                 "entry_utc": original["вход UTC"], "exit_utc": original["выход UTC"],
                 "old_published_net_no_funding": original["итог, % базы"],
                 "old_replayed_net_no_funding": old["res"], "corrected_net_no_funding": e["res"],
                 "delta_net_no_funding": e["res"] - old["res"],
                 "old_add": bool(old["pos"]["add_done"]), "corrected_add": bool(p["add_done"]),
                 "add_utc": None if p.get("add_t") is None else pd.Timestamp(p["add_t"], unit="s").strftime("%Y-%m-%d %H:%M"),
                 "old_recorded_clock_net_funding_proxy": cash_old["net_with_observed_funding"],
                 "corrected_net_observed_funding_proxy": cash_new["net_with_observed_funding"],
                 "delta_funding_clock_proxy": cash_new["net_with_observed_funding"] - cash_old["net_with_observed_funding"],
                 "basis_bug_net_funding_proxy": cash_bug["net_with_observed_funding"],
                 "basis_bug_correction_proxy": cash_old_correct["net_with_observed_funding"] - cash_bug["net_with_observed_funding"],
                 "funding_complete": cash_new["funding_complete"], "funding_status": cash_new["status"],
                 "corrected_net_funding_strict": cash_new["net_with_funding_strict"],
                 "exit_mode": mode, "path_quality": path["качество пути"], "exit_resolution": path["разрешение выхода"],
                 "path_reason": path["причина качества пути"],
                 "old_MFE_ATR": original["MFE, ATR"], "corrected_MFE_ATR": path["MFE, ATR"],
                 "old_MAE_ATR": original["MAE, ATR"], "corrected_MAE_ATR": path["MAE, ATR"],
                 "corrected_MAE_lower_ATR": path["MAE lower, ATR"], "corrected_MAE_upper_ATR": path["MAE upper, ATR"],
                 "old_giveback_ATR": original["отдача, ATR"], "corrected_giveback_ATR": path["отдача, ATR"],
                 "old_first_threshold": original["сначала +1 ATR или −1 ATR"],
                 "corrected_first_threshold": path["сначала +1 ATR или −1 ATR"]}
            reasons = []
            if abs(e["res"] - old["res"]) > 1e-10:
                reasons.append("add_chronology_net")
            if abs(r["delta_funding_clock_proxy"]) > 1e-10:
                reasons.append("funding_event_clock")
            if abs(r["basis_bug_correction_proxy"]) > 1e-10:
                reasons.append("basis_add_funding_start")
            for col in FUND_FEATURES:
                oldv, newv = old_p[col][i0], new_p[col][i0]
                r["old_" + col], r["corrected_" + col] = oldv, newv
                # Reconciliation against the published feature rounding too.
                assert not changed(original[col], oldv), (trade_id, col, original[col], oldv)
                corrected.loc[ix, col] = newv
                if changed(oldv, newv, 1e-10):
                    reasons.append("availability:" + col)
            for col in PATH_COMPARE:
                if changed(original[col], path[col]):
                    reasons.append("path:" + col)
            r["affected"] = bool(reasons)
            r["affected_actual_data_or_clock"] = any(x != "basis_add_funding_start" for x in reasons)
            r["basis_bug_in_original_checker_scope"] = venue == "Binance" and original["тип"] == "шорт под синей"
            r["basis_bug_counterfactual_changed"] = "basis_add_funding_start" in reasons
            r["change_reasons"] = " | ".join(reasons)
            rows.append(r)
            for clock, obj in [("old_event_clock", cash_old), ("corrected", cash_new), ("basis_bug", cash_bug)]:
                cash_detail.append({"trade_id": trade_id, "clock": clock, **obj})
            for col, value in path.items():
                corrected.loc[ix, col] = value
            corrected.loc[ix, "итог, % базы"] = e["res"]
            corrected.loc[ix, "добор"] = int(bool(p["add_done"]))
            corrected.loc[ix, "цена добора"] = p.get("add_px")
            corrected.loc[ix, "добор UTC"] = r["add_utc"]
            corrected.loc[ix, "_add_t"] = p.get("add_t")
            corrected.loc[ix, "_add_i"] = np.searchsorted(a["t"], p["add_t"]) if p.get("add_t") is not None else np.nan
            corrected.loc[ix, "_add_before_close"] = bool(p["add_done"]) and tag in {"над синей", "под синей"}
            for name, val in {"_t0": t0, "_t1": e["t"], "_i0": i0, "_i1": i1}.items():
                corrected.loc[ix, name] = val
    result = pd.DataFrame(rows)
    assert len(result) == 973 and result.trade_id.nunique() == 973
    result.to_csv(out / "trade_repair_all.csv", index=False, encoding="utf-8-sig", float_format="%.10g")
    result[result.affected].to_csv(out / "trade_repair_affected.csv", index=False, encoding="utf-8-sig", float_format="%.10g")
    result[result.affected_actual_data_or_clock].to_csv(out / "trade_repair_actual_affected.csv", index=False, encoding="utf-8-sig", float_format="%.10g")
    corrected.to_csv(out / "trade_table_btc_corrected.csv", sep=";", decimal=",", index=False, encoding="utf-8-sig", float_format="%.8g")
    corrected.to_pickle(out / "trade_table_btc_corrected.pkl")
    (out / "trade_repair_cashflows.json").write_text(json.dumps(cash_detail, ensure_ascii=False, indent=2), encoding="utf-8")
    for (venue, typ), g in result.groupby(["venue", "type"]):
        totals.append({"venue": venue, "type": typ, "n": len(g), "affected": int(g.affected.sum()),
                       **{c: float(g[c].sum()) for c in ["old_replayed_net_no_funding", "corrected_net_no_funding",
                                                       "old_recorded_clock_net_funding_proxy", "corrected_net_observed_funding_proxy",
                                                       "delta_funding_clock_proxy", "basis_bug_correction_proxy"]},
                       "strict_funding_n": int(g.funding_complete.sum())})
    counts = Counter(r for rs in result.change_reasons for r in rs.split(" | ") if r)
    summary = {"matched_trades": len(result), "affected_trades": int(result.affected.sum()),
               "actual_data_or_clock_affected": int(result.affected_actual_data_or_clock.sum()),
               "basis_counterfactual_only": int((result.affected & ~result.affected_actual_data_or_clock).sum()),
               "reasons": dict(counts), "totals": totals,
               "target_exit_quality": result[result.exit_mode == "target"].groupby(["venue", "exit_resolution", "path_quality"]).size().reset_index(name="n").to_dict("records"),
               "source_precision": "published CSV rounded4; source old/new replay compared before rounding",
               "funding_scope": "observed source rates and same-clock spot price proxy, not actual futures marks; strict unsupported prehistory is NaN"}
    (out / "trade_repair_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
