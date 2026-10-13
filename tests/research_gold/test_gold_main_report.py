"""П.9 и отчётная часть п.6 разбора GPT 13.10, на настоящем main() по синтетическому CSV:
- B−A: разница ожиданий B и A с 95% ДИ по ОБЩИМ ISO-неделям (парный блочный бутстрап), а не два отдельных минуса;
- чувствительность отмены по ТЗ (до входа) рядом с основным прогоном по протоколу, с числом отменённых."""
import json
import sys

import numpy as np
import pandas as pd

from tests.research_gold.gold_fx import POST_CUT_DAY, block, combine, sb, set_bar, set_minute


def _fixture() -> dict:
    parts, edits = [], []
    day = POST_CUT_DAY
    for k in range(12):
        parts += [block(day, 0, 60, 100.0), block(day + 1, 0, 360, 104.0)]
        edits.append((k % 3, day + 1))
        day += 2
    a = combine(*parts)
    for kind, d in edits:
        if kind in (0, 1):                                      # B проходит: VWAP дня ниже close подтверждения
            set_bar(a, d, 0, o=100.5, h=101, l=99, c=100.5)
            set_bar(a, d, 15, o=100.5, h=102, l=99.5, c=101.5)
            if kind == 1:
                set_minute(a, d, 120, high=120.0)               # цель
        else:                                                   # B отсеян: дорогой объём в начале дня
            set_bar(a, d, 0, o=110, h=110, l=110, c=110, volume=50.0)
            set_bar(a, d, 15, o=100.5, h=101, l=99, c=100.5)
            set_bar(a, d, 30, o=100.5, h=102, l=99.5, c=101.5)
            set_minute(a, d, 150, open=98.0, low=95.0)          # стоп с гэпом
    return a


def _run_main(tmp_path, monkeypatch) -> dict:
    a = _fixture()
    p = tmp_path / sb.INST["PAXG"]["file"]
    p.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({k: a[k] for k in ("ts", "open", "high", "low", "close", "volume")}).to_csv(p, index=False)
    out = tmp_path / "o.json"
    monkeypatch.setattr(sb, "ROOT", tmp_path)
    monkeypatch.setattr(sys, "argv", ["sweep_backtest.py", "PAXG", f"--out={out}", f"--data-root={tmp_path}"])
    sb.main()
    return json.loads(out.read_text(encoding="utf-8"))


def _weeks(tr):
    return {tuple(pd.Timestamp(t["entry_ts"], unit="ms").isocalendar()[:2]) for t in tr}


def test_main_reports_paired_b_minus_a_ci_over_common_iso_weeks(tmp_path, monkeypatch):
    res = _run_main(tmp_path, monkeypatch)
    ta = res["versions"]["A"]["3000_net"]["trades"]
    tb = res["versions"]["B"]["3000_net"]["trades"]
    assert len(ta) > len(tb) > 0
    d = res.get("b_minus_a", {}).get("net_R")
    assert d, "разница B−A и её ДИ не посчитаны"
    assert np.isclose(d["diff"], np.mean([t["R"] for t in tb]) - np.mean([t["R"] for t in ta]))
    assert d["weeks"] == len(_weeks(ta) | _weeks(tb))
    lo, hi = d["ci"]
    assert lo <= d["diff"] <= hi


def test_main_reports_spec_cancel_sensitivity_next_to_protocol_run(tmp_path, monkeypatch):
    res = _run_main(tmp_path, monkeypatch)
    sens = res["versions"]["A"].get("sens", {}).get("spec_cancel")
    assert sens is not None, "чувствительность отмены по ТЗ не посчитана"
    assert sens["cancelled"] == 0 and sens["n"] == res["versions"]["A"]["3000_net"]["stats"]["n"]
