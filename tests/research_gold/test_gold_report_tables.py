"""П.7 (отчётная часть): таблица версий берёт «до расходов» из того же ledger, что и «после» (тот же qty, без отдельной
симуляции с урезанием номинала), и печатает обе нормировки R, B−A с ДИ и счётчики чувствительностей.
Сопровождающий тест к test_gold_r_units.py: прежний sweep_report_tables.py читал отдельный прогон «3000_gross»."""
import contextlib
import io
import json
import re
import sys

from tests.research_gold.test_gold_main_report import _run_main

import sweep_report_tables as rt  # noqa: E402  (путь research/gold добавлен в gold_fx)


def _report(path, monkeypatch) -> str:
    monkeypatch.setattr(sys, "argv", ["sweep_report_tables.py", str(path)])
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rt.main()
    return buf.getvalue()


def test_version_table_gross_column_is_the_net_ledger_without_costs(tmp_path, monkeypatch):
    res = _run_main(tmp_path, monkeypatch)
    out = _report(tmp_path / "o.json", monkeypatch)
    st = res["versions"]["A"]["3000_net"]["stats"]
    row = next(ln for ln in out.splitlines() if ln.startswith("| A | "))
    cells = [c.strip() for c in row.strip("|").split("|")]
    assert cells[3] == f"{st['exp_R']:+.3f}" and cells[4] == f"{st['exp_R_gross']:+.3f}", row
    assert cells[7] == f"{st['exp_pR_gross']:+.3f}" and cells[9] == f"{st['exp_pR']:+.3f}", row
    assert re.search(r"B−A \(парный бутстрап по общим ISO-неделям, недель \d+\)", out), out
    assert "отмена по ТЗ «до входа»" in out and "сигналов обрезано концом данных" in out
    assert json.loads((tmp_path / "o.json").read_text(encoding="utf-8"))["versions"]["A"].get("3000_gross") is None
