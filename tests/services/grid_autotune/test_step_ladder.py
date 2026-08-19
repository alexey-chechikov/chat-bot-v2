"""Лестница шага от набранной позиции.

Оператор 2026-08-19: «я бы в таком режиме и с таким общим ордером уже
почти 30к делал бы грид степ минимум 0.8» — про BTC SHORT при 31.8%
занятой ёмкости. И отдельно: «почему ты игнорируешь солану и её позицию
в 5к, грид степ у неё 0.2».

Триггер НЕ от движения рынка: оператор там же сказал, что ровный
монотонный рост без откатов он хочет пропускать. Только от занятости.
"""
from __future__ import annotations

import json

import pytest

from services.ginarea_api.models import DefaultGridParams
from services.grid_autotune import loop as gat
from tests.services.grid_autotune.test_grid_autotune import (  # noqa: F401
    _cfg, _isolate)

SHORT = "5189290547"
# ступени BTC SHORT: верхняя взята из слов оператора
LADDER = [[30, 0.80], [20, 0.40], [12, 0.20], [6, 0.12]]


@pytest.fixture(autouse=True)
def _isolate_ladder_memory(monkeypatch, tmp_path):
    """Память лестницы — тоже в tmp: тесты не должны писать в боевой файл."""
    monkeypatch.setattr(gat, "LADDER_MEMORY", tmp_path / "ladder_mem.json")


def _params(gs=0.06, tog=0.29, maxOp=300, maxQ=300, extra=None):
    d = {"gs": gs, "side": 2, "p": True, "obap": True, "maxOp": maxOp,
         "gap": {"tog": tog, "minS": 0.012, "maxS": 0.015, "isg": 0.018},
         "q": {"minQ": 100, "maxQ": maxQ, "qr": 1.4}, "tr": {"tr": 0}}
    d.update(extra or {})
    return DefaultGridParams.from_dict(d)


class FakeAPI:
    def __init__(self, params=None):
        self.params = params or _params()
        self.set_calls: list[tuple] = []

    def get_params(self, bot_id):
        return self.params

    def set_params(self, bot_id, params):
        self.set_calls.append((round(params.gs, 4), round(params.gap.tog, 4)))
        self.params = params

    def get_bot(self, bot_id):
        from types import SimpleNamespace
        return SimpleNamespace(status=2)


def _snap(pos_usd):
    """Инверсный бот: position уже в долларовых контрактах."""
    return {"position": -pos_usd, "avg_price": 64000.0, "bag": -500.0,
            "status": 2}


def _bcfg(**over):
    b = {"alias": "BTC-SHORT-INV", "inverse": True, "otc_expected": True,
         "base_gs": 0.06, "step_ladder": LADDER}
    b.update(over)
    return b


def _events():
    return [json.loads(l) for l in gat.JOURNAL_PATH.read_text().splitlines()]


# ─── чистая функция выбора ступени ───────────────────────────────────────
@pytest.mark.parametrize("occ,want", [
    (0.0, 0.06), (5.9, 0.06),
    (6.0, 0.12), (11.9, 0.12),
    (12.0, 0.20), (19.9, 0.20),
    (20.0, 0.40), (29.9, 0.40),
    (30.0, 0.80), (31.8, 0.80), (95.0, 0.80),
])
def test_ladder_step_picks_rung(occ, want):
    assert gat.ladder_step(LADDER, occ, 0.06) == want


def test_ladder_never_below_base():
    """База 0.5 выше всех ступеней — шаг не должен УМЕНЬШАТЬСЯ."""
    assert gat.ladder_step(LADDER, 0.0, 0.5) == 0.5
    assert gat.ladder_step(LADDER, 31.8, 0.5) == 0.8


def test_ladder_order_in_config_does_not_matter():
    shuffled = [[12, 0.20], [30, 0.80], [6, 0.12], [20, 0.40]]
    assert gat.ladder_step(shuffled, 31.8, 0.06) == 0.80
    assert gat.ladder_step(shuffled, 13.0, 0.06) == 0.20


# ─── боевой путь ─────────────────────────────────────────────────────────
def test_widens_at_operator_anchor():
    """31.8% ёмкости -> шаг 0.8, ровно как назвал оператор. Таргет цел."""
    _cfg(bots={SHORT: _bcfg()})
    api = FakeAPI(_params(gs=0.06, maxOp=300, maxQ=300))
    n = gat.tick(send_fn=[].append, api=api, drift={},
                 bags={SHORT: _snap(28_600)})   # 28600/90000 = 31.8%
    assert n == 1
    assert api.set_calls == [(0.8, 0.29)]
    ev = [e for e in _events() if e["event"] == "LADDER_APPLIED"][0]
    assert ev["gs_from"] == 0.06 and ev["gs_to"] == 0.8
    assert 31.0 < ev["occupancy_pct"] < 32.5


def test_returns_step_when_position_shrinks():
    """Ходит в обе стороны — отдельного отката не нужно.

    Снижает только СВОЁ значение, поэтому память заполнена.
    """
    gat.LADDER_MEMORY.write_text(json.dumps({SHORT: 0.8}), encoding="utf-8")
    _cfg(bots={SHORT: _bcfg()})
    api = FakeAPI(_params(gs=0.8, maxOp=300, maxQ=300))
    n = gat.tick(send_fn=[].append, api=api, drift={},
                 bags={SHORT: _snap(4_500)})    # 5% -> база
    assert n == 1
    assert api.set_calls == [(0.06, 0.29)]


def test_manual_raise_is_not_pulled_back_down(tmp_path, monkeypatch):
    """Оператор 19.08: «не уменьшал если я увеличил не дождавшись».

    Он поставил 1.5 руками при занятости 5% (ступень = база 0.06).
    Лестница обязана оставить его в покое.
    """
    monkeypatch.setattr(gat, "LADDER_MEMORY", tmp_path / "ladder.json")
    _cfg(bots={SHORT: _bcfg()})
    api = FakeAPI(_params(gs=1.5, maxOp=300, maxQ=300))
    n = gat.tick(send_fn=[].append, api=api, drift={},
                 bags={SHORT: _snap(4_500)})
    assert n == 0
    assert not api.set_calls
    ev = [e for e in _events() if e["event"] == "LADDER_MANUAL_HELD"][0]
    assert ev["gs_now"] == 1.5 and ev["ladder_wants"] == 0.06


def test_manual_raise_still_gets_raised_further(tmp_path, monkeypatch):
    """Ручное значение не блокирует РОСТ: ступень выше — расширяем."""
    monkeypatch.setattr(gat, "LADDER_MEMORY", tmp_path / "ladder.json")
    _cfg(bots={SHORT: _bcfg(step_ladder=[[30, 2.0]] + LADDER[1:])})
    api = FakeAPI(_params(gs=1.5, maxOp=300, maxQ=300))
    n = gat.tick(send_fn=[].append, api=api, drift={},
                 bags={SHORT: _snap(28_600)})
    assert n == 1
    assert api.set_calls == [(2.0, 0.29)]


def test_ladder_lowers_only_its_own_value(tmp_path, monkeypatch):
    """Своё значение лестница снижать вправе — иначе шаг залипнет наверху."""
    mem = tmp_path / "ladder.json"
    monkeypatch.setattr(gat, "LADDER_MEMORY", mem)
    mem.write_text(json.dumps({SHORT: 0.8}), encoding="utf-8")
    _cfg(bots={SHORT: _bcfg()})
    api = FakeAPI(_params(gs=0.8, maxOp=300, maxQ=300))
    n = gat.tick(send_fn=[].append, api=api, drift={},
                 bags={SHORT: _snap(4_500)})
    assert n == 1
    assert api.set_calls == [(0.06, 0.29)]


def test_no_op_when_already_on_rung():
    _cfg(bots={SHORT: _bcfg()})
    api = FakeAPI(_params(gs=0.8, maxOp=300, maxQ=300))
    n = gat.tick(send_fn=[].append, api=api, drift={},
                 bags={SHORT: _snap(28_600)})
    assert n == 0
    assert not api.set_calls


def test_target_is_never_touched():
    _cfg(bots={SHORT: _bcfg()})
    api = FakeAPI(_params(gs=0.06, tog=0.29, maxOp=300, maxQ=300))
    gat.tick(send_fn=[].append, api=api, drift={},
             bags={SHORT: _snap(28_600)})
    assert api.params.gap.tog == 0.29


def test_linear_bot_position_converted_by_price():
    """У линейного позиция в МОНЕТАХ — без умножения на цену занятость
    вышла бы в тысячи раз меньше и ступень бы не сработала."""
    sol = "5253063096"
    _cfg(bots={sol: {"alias": "SOL", "base_gs": 0.2,
                     "step_ladder": [[12, 0.6], [6, 0.4]]}})
    api = FakeAPI(_params(gs=0.2, tog=0.64, maxOp=100, maxQ=5))
    # 66.6 монет × $77 = $5 128 из ёмкости 100×5×77 = $38 500 -> 13.3%
    snap = {"position": 66.6, "avg_price": 77.0, "bag": -87.0, "status": 2}
    n = gat.tick(send_fn=[].append, api=api, drift={}, bags={sol: snap})
    assert n == 1
    assert api.set_calls == [(0.6, 0.64)]


def test_otc_reset_on_write_is_caught():
    """set_params может сбросить otcPassed (инцидент 17.05)."""
    _cfg(bots={SHORT: _bcfg()})
    api = FakeAPI(_params(gs=0.06, maxOp=300, maxQ=300,
                          extra={"in": {"otc": True, "otcPassed": True}}))

    def bad_set(bot_id, params):
        api.set_calls.append((round(params.gs, 4), round(params.gap.tog, 4)))
        params.extra_raw["in"] = dict(params.extra_raw["in"], otcPassed=False)
        api.params = params

    api.set_params = bad_set
    n = gat.tick(send_fn=[].append, api=api, drift={},
                 bags={SHORT: _snap(28_600)})
    assert n == 0
    assert any(e["event"] == "LADDER_FAILED" for e in _events())


def test_missing_capacity_is_skipped_not_guessed():
    _cfg(bots={SHORT: _bcfg()})
    api = FakeAPI(_params(gs=0.06, maxOp=300, maxQ=300))
    n = gat.tick(send_fn=[].append, api=api, drift={},
                 bags={SHORT: {"position": -28600, "avg_price": 0.0,
                               "bag": -1.0, "status": 2}})
    assert n == 0
    assert any(e["event"] == "LADDER_SKIP_NO_CAPACITY" for e in _events())
