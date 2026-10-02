"""Тесты границы набора. Логика вся в decide() — её и проверяем."""
from __future__ import annotations

import pytest

from services.grid_border.loop import border_of, decide, is_breached

ATR = 2000.0
K = 0.75
D = K * ATR          # 1500


def base(**kw):
    d = {"price": 78000.0, "position_usd": -1800.0, "anchor": 78000.0,
         "atr_value": ATR, "k": K, "open_orders": 12, "max_op": 50,
         "frozen_at": None}
    d.update(kw)
    return decide(**d)


def test_border_side_depends_on_direction():
    # лонг теряет вниз, шорт вверх — граница ставится там, где хуже
    assert border_of(78000.0, True, ATR, K) == pytest.approx(78000 - D)
    assert border_of(78000.0, False, ATR, K) == pytest.approx(78000 + D)


def test_is_breached():
    assert is_breached(76000.0, 76500.0, True)
    assert not is_breached(77000.0, 76500.0, True)
    assert is_breached(80000.0, 79500.0, False)
    assert not is_breached(79000.0, 79500.0, False)


def test_anchor_set_on_first_position():
    r = base(anchor=None)
    assert r["action"] == "SET_ANCHOR"
    assert r["anchor"] == 78000.0


def test_no_action_inside_border():
    assert base(price=78500.0)["action"] == "NONE"


def test_freeze_when_short_and_price_above_border():
    r = base(price=79600.0)          # граница шорта 79 500
    assert r["action"] == "FREEZE"
    assert r["new_max_op"] == 12
    assert r["prev_max_op"] == 50


def test_freeze_when_long_and_price_below_border():
    r = base(position_usd=1700.0, price=76400.0)   # граница лонга 76 500
    assert r["action"] == "FREEZE"
    assert r["new_max_op"] == 12


def test_no_double_freeze():
    assert base(price=79600.0, frozen_at=50)["action"] == "NONE"


def test_release_when_price_returns():
    r = base(price=78500.0, frozen_at=50)
    assert r["action"] == "RELEASE"


def test_clear_when_position_gone():
    assert base(position_usd=0.0, frozen_at=50)["action"] == "CLEAR"
    assert base(position_usd=0.0, anchor=None, frozen_at=None
                )["action"] == "NONE"


def test_no_freeze_without_open_orders():
    """maxOp=0 остановил бы сетку целиком — это пауза, а не заморозка."""
    r = base(price=79600.0, open_orders=0)
    assert r["action"] == "NONE"
    assert "нет открытых ордеров" in r["reason"]


def test_no_atr_no_action():
    assert base(price=79600.0, atr_value=0.0)["action"] == "NONE"


def test_seed_anchor_from_history(tmp_path):
    """Якорь для уже открытой позиции берётся из истории, а не «отсюда».

    10.09 служба на первом тике поставила якорь LONG COIN на текущую цену
    $78 128, хотя набор шёл от $80 468 — граница уехала туда, где позиции
    ничего не грозит, и пробой был бы пропущен.
    """
    from services.grid_border.loop import seed_anchor

    p = tmp_path / "snapshots.csv"
    lines = ["ts_utc,bot_id,position,average_price"]
    # позиция пуста, потом набор от 80 468 с усреднением вниз
    for k in range(4):
        lines.append(f"2026-09-01T0{k}:00,111,0.0,0.0")
    for k, (pos, avg) in enumerate(
            [(100, 80468.0), (300, 80100.0), (900, 80495.0), (1700, 80495.0)]):
        lines.append(f"2026-09-03T1{k}:00,111,{pos},{avg}")
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert seed_anchor("111", snapshots=p) == pytest.approx(80468.0)


def test_seed_anchor_missing_file_is_none(tmp_path):
    from services.grid_border.loop import seed_anchor

    assert seed_anchor("111", snapshots=tmp_path / "нет.csv") is None


def test_short_border_is_above_and_long_below():
    """Проверка, что стороны не перепутаны: это главная ошибка в такой
    логике, и она молча ломает всё."""
    short = base(price=76000.0)      # шорт, цена УПАЛА — ему хорошо
    assert short["action"] == "NONE"
    long_ok = base(position_usd=1700.0, price=80000.0)   # лонгу хорошо
    assert long_ok["action"] == "NONE"
