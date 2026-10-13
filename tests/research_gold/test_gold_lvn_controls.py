"""П.8 разбора GPT 13.10 (§6 «Контроль LVN»). Заранее заданная нулевая гипотеза:
- на каждый день (и окно) ОДНО случайное размещение зон, общее для всех сигналов дня;
- то же число зон и те же ширины, только в корзинах зоны стоимости вне LVN, без пересечений и слияний;
- невозможное размещение считается невалидным; при нуле валидных контролей ранг — NA (никогда не 1.000);
- контроль сравнивается с E, прогоняя каждый контроль через ту же событийную петлю E, а не фильтруя готовый ledger B.
Проверяется настоящий main() скрипта контролей на заглушках рынка/симуляции (как в пробе GPT gold_stats_probe.py)."""
import contextlib
import io
import re
import sys

import numpy as np

from tests.research_gold.gold_fx import sb

import sweep_lvn_controls as ctl  # noqa: E402  (путь research/gold добавлен в gold_fx)


def _run_main(monkeypatch, mask, signals, e_only=(), n=200):
    real_mask = np.asarray(mask, dtype=bool)
    edges = 1000.0 + 0.5 * np.arange(len(real_mask) + 1)
    calls = []
    real_near = sb.Market.near_zone

    class StubMarket:
        def __init__(self, *args, **kwargs):
            pass

        def lvn(self, day, window=2):
            return edges, real_mask.copy(), np.ones(len(real_mask), dtype=bool)

        @staticmethod
        def near_zone(level, e, m):
            calls.append(np.array(m, copy=True))
            return real_near(level, e, m)

    def fake_simulate(m, version, capital, costs, lvn_window=2, **kwargs):
        out = []
        for s in list(signals) + (list(e_only) if version == "E" else []):
            if version == "E":
                z = m.lvn(s["day"], lvn_window)
                if z is None or not sb.Market.near_zone(s["level"], z[0], z[1]):
                    continue
            ts = s["day"] * sb.DAY + s.get("h", 0) * 3_600_000
            out.append(dict(R=s["R"], pnl=s["R"], sig_ts=ts, entry_ts=ts, level=s["level"], entry=1001.0,
                            stop=1000.0))
        return {"trades": out, "skipped_min": 0, "capped": 0}

    monkeypatch.setattr(sb, "Market", StubMarket)
    monkeypatch.setattr(sb, "load", lambda *a, **k: ({}, {}))
    monkeypatch.setattr(sb, "simulate", fake_simulate)
    monkeypatch.setattr(ctl, "N_CTL", n)
    monkeypatch.setattr(sys, "argv", ["sweep_lvn_controls.py", "PAXG"])
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        ctl.main()
    return buf.getvalue(), calls, real_mask


def test_zero_valid_controls_give_rank_na_not_one(monkeypatch):
    # две LVN-зоны шириной 2, свободны только одиночные корзины → размещение невозможно
    out, _, _ = _run_main(monkeypatch, [0, 1, 1, 0, 1, 1, 0],
                          [dict(day=0, level=1001.0, R=-0.5), dict(day=0, h=2, level=1001.0, R=0.5)])
    assert "ранг 1.000" not in out, out
    assert re.search(r"ранг NA", out), out


def test_control_zones_keep_number_and_widths_without_overlap_or_merge(monkeypatch):
    original = [0, 0, 1, 0, 0, 1, 0, 0]
    _, calls, real = _run_main(monkeypatch, original, [dict(day=0, level=1001.25, R=-0.5)])
    controls = [c for c in calls if not np.array_equal(c, real)]
    assert controls, "контрольные зоны не проверялись"
    bad = [c.astype(int).tolist() for c in controls if c.sum() != 2 or len(ctl.runs(c)) != 2 or (c & real).any()]
    assert not bad, f"{len(bad)}/{len(controls)} размещений потеряли/слили зону, напр. {bad[0]}"


def test_same_day_signals_share_one_random_profile(monkeypatch):
    # два одинаковых сигнала одного дня: R +1 и −1; настоящий профиль задевает оба (среднее 0)
    mask = [0] * 10 + [1] + [0] * 9
    out, _, _ = _run_main(monkeypatch, mask, [dict(day=0, level=1005.25, R=1.0), dict(day=0, h=2, level=1005.25, R=-1.0)])
    mt = re.search(r"не хуже настоящего (\d+)/(\d+)", out)
    assert mt, out
    k, n = int(mt.group(1)), int(mt.group(2))
    assert n > 0 and k == n, f"решения по сигналам одного дня разошлись: {k}/{n}"


def test_real_statistic_is_the_resimulated_e_ledger_not_a_filter_of_b(monkeypatch):
    mask = [0] * 10 + [1] + [0] * 9
    b_sig = [dict(day=0, level=1005.25, R=-1.0), dict(day=0, h=2, level=1005.25, R=-1.0)]
    e_only = [dict(day=1, level=1005.25, R=2.0)]                # сигнал, который E берёт, пока B занят позицией
    out, _, _ = _run_main(monkeypatch, mask, b_sig, e_only=e_only)
    mt = re.search(r"ожидание ([+-]?\d+\.\d+)R", out)
    assert mt, out
    assert float(mt.group(1)) == 0.0, f"настоящее значение взято из фильтра ledger B: {mt.group(0)}"
