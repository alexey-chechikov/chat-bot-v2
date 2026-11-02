"""research/indicator_atlas — остаток разбора GPT 29.10 (docs/WEEX_GPT_CRITICAL_REPLY_RECHECK_2026-10-29.md §2, P1):
неизвестная метка (нет признака) превращалась в False и попадала в группу «без метки» — в фактическом Δ и в плацебо.
Ветки «до 02.11» в тестах повторяют старый расчёт (знаменатель по всем часам состояния), чтобы на старом коммите тест
падал на значении Δ, а не на отсутствии новой функции."""
import inspect

import numpy as np
import pandas as pd

from research.indicator_atlas import atlas, scan2

LIQ = "всплеск ликвидаций лонгов 6ч"


def _features():
    """Три часа, все признаки известны, кроме ликвидаций лонгов во втором часе."""
    idx = pd.date_range("2026-10-01", periods=3, freq="1h", tz="UTC")
    f = pd.DataFrame(index=idx)
    for key in atlas.LEVELS:
        f[f"{key}_p"] = 0.5
        for h in (6, 24):
            f[f"{key}_z{h}"] = 0.0
    for c in ("r24", "tak6", "tak24", "red6", "green6", "book6"):
        f[c] = 0.0
    for c in ("tak6p", "tak24p", "bookp6", "vol6p", "w24p"):
        f[c] = 0.5
    f["liqL6p"] = [0.99, np.nan, 0.2]
    f["liqS6p"] = 0.2
    f["liqL_spike"] = f["liqL6p"] >= 0.95
    f["liqS_spike"] = False
    return f


def _frame(f):
    parts = [f, atlas.tokens(f)]
    if hasattr(atlas, "token_known"):
        parts.append(atlas.token_known(f).add_prefix(atlas.KNOWN))
    return pd.concat(parts, axis=1)


def _mats(d, label):
    if hasattr(scan2, "token_mats"):
        return scan2.token_mats(d, [label])
    t = d[[label]].to_numpy(float)                      # до 02.11: наблюдаемость не различалась
    return t, np.ones_like(t)


def test_unknown_liquidation_is_not_in_negative_label_comparison():
    """Контрпример GPT: два известных часа — продолжение вверх, неизвестный час — вниз. Δ = 0, а не +0.5."""
    d = _frame(_features())
    d["context"] = "UP"
    d["first"] = ["up", "down", "up"]
    vy, v = scan2.outcome_mats(d, [("UP", "cont", "first", "up")])
    m = np.hstack([vy, v])
    T, O = _mats(d, LIQ)
    tot = O.T @ m if hasattr(scan2, "token_mats") else m.sum(axis=0)
    delta, with_label, without_label, _ = scan2.delta_from(T.T @ m, tot, 1)
    assert delta[0, 0] == 0.0, {"delta": delta.tolist(), "with": with_label.tolist(),
                                "without": without_label.tolist()}


def test_placebo_shifts_observability_together_with_the_label(monkeypatch):
    """В перестановке маска наблюдаемости едет вместе с меткой: при сдвиге на 1 неизвестный час метки ложится на
    исход 0 и не должен попасть в «без метки» (там все исходы 1)."""
    monkeypatch.setattr(scan2, "SHIFT_MIN", 1)
    T = np.array([[1], [0], [0], [0], [0], [0]], dtype=float)
    O = np.array([[1], [0], [1], [1], [1], [1]], dtype=float)
    y = np.array([1, 1, 0, 1, 1, 1], dtype=float)
    M = np.column_stack([y, np.ones(6)])
    if "Os" in inspect.signature(scan2.placebo_all_common).parameters:
        out = scan2.placebo_all_common([T], [O], [M], 1)
    else:
        out = scan2.placebo_all_common([T], [M], M.sum(axis=0), 1)
    assert out[0, 0, 0] == 0.0, out[:, 0, 0].tolist()  # s=1: с меткой 1/1, без метки 4/4 (старый расчёт 4/5)


def test_token_known_requires_every_feature_of_the_label():
    f = _features()
    f.loc[f.index[0], "oi_z24"] = np.nan
    k = atlas.token_known(f)
    assert k[LIQ].tolist() == [True, False, True]
    assert k["всплеск ликвидаций шортов 6ч"].all()
    assert k["цена ↑, OI ↓ (дивергенция 24ч)"].tolist() == [False, True, True]   # нужен и r24, и z24
    assert k["OI высоко"].all()
    t = atlas.tokens(f)
    assert not (t & ~k).to_numpy().any()                # метка не стоит там, где она не наблюдаема


def test_token_columns_exclude_observability_masks():
    d = _frame(_features())
    toks = atlas.token_columns(d)
    assert toks == list(atlas.tokens(_features()).columns)
    assert not any(c.startswith(atlas.KNOWN) for c in toks)
    T, O = scan2.token_mats(d, toks)
    assert T.shape == O.shape and (T <= O).all()
