"""Протокол §Сигнал п.1: ADX14 Уайлдера (seed = среднее первых 14 TR/DM, ADX seed = среднее первых 14 DX, далее
RMA 1/14), окно 30 завершённых 4h без текущей, правило «впервые выше», SHORT зеркально; EMA20 с seed SMA20."""
import math

import numpy as np

from tests.research_manual.mp_fx import rp, sym4


def _ref_adx(h, l, c, n=14):
    """Независимая построчная реализация по тексту протокола."""
    m = len(h)
    tr, pdm, mdm = [None] * m, [None] * m, [None] * m
    for i in range(1, m):
        tr[i] = max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
        up, dn = h[i] - h[i - 1], l[i - 1] - l[i]
        pdm[i] = up if (up > dn and up > 0) else 0.0
        mdm[i] = dn if (dn > up and dn > 0) else 0.0
    atr, sp, sm, dx, adx = ([math.nan] * m for _ in range(5))
    atr[n] = sum(tr[1:n + 1]) / n
    sp[n] = sum(pdm[1:n + 1]) / n
    sm[n] = sum(mdm[1:n + 1]) / n
    for i in range(n + 1, m):
        atr[i] = (atr[i - 1] * (n - 1) + tr[i]) / n
        sp[i] = (sp[i - 1] * (n - 1) + pdm[i]) / n
        sm[i] = (sm[i - 1] * (n - 1) + mdm[i]) / n
    for i in range(n, m):
        pdi, mdi = 100 * sp[i] / atr[i], 100 * sm[i] / atr[i]
        dx[i] = 100 * abs(pdi - mdi) / (pdi + mdi)
    adx[2 * n - 1] = sum(dx[n:2 * n]) / n
    for i in range(2 * n, m):
        adx[i] = (adx[i - 1] * (n - 1) + dx[i]) / n
    return np.array(adx), np.array(atr)


def _series(m=80, seed=7):
    rng = np.random.default_rng(seed)
    c = 100 + np.cumsum(rng.normal(0, 1, m))
    h = c + rng.uniform(0.1, 1.5, m)
    l = c - rng.uniform(0.1, 1.5, m)
    return h, l, c


def test_adx_wilder_seeding_matches_reference():
    h, l, c = _series()
    got = rp.adx_wilder(h, l, c, 14)
    ref, _ = _ref_adx(h, l, c, 14)
    assert np.all(np.isnan(got[:27])) and np.isfinite(got[27])        # первое значение — бар 2n−1 = 27
    assert np.allclose(got[27:], ref[27:], rtol=0, atol=1e-10)


def test_atr_wilder_seed_is_mean_of_first_14_tr():
    h, l, c = _series()
    got = rp.atr_wilder(h, l, c, 14)
    _, ref = _ref_adx(h, l, c, 14)
    assert np.all(np.isnan(got[:14]))
    assert np.allclose(got[14:], ref[14:], rtol=0, atol=1e-10)


def test_ema_seed_sma20_then_alpha():
    c = np.arange(1, 41, dtype=float)
    e = rp.ema_sma_seed(c, 20)
    assert np.all(np.isnan(e[:19])) and e[19] == np.mean(c[:20])
    assert math.isclose(e[20], e[19] + 2 / 21 * (c[20] - e[19]), abs_tol=1e-12)


def test_indicators_reseed_after_hole():
    h, l, c = _series(70)
    ok = np.ones(70, bool)
    ok[30] = False
    out = rp.by_segments(ok, rp.atr_wilder, h, l, c, n=14)
    assert np.isnan(out[30]) and np.all(np.isnan(out[31:45])) and np.isfinite(out[45])
    assert math.isclose(out[45], np.mean(rp.true_range(h[31:46], l[31:46], c[31:46])), abs_tol=1e-12)


def _base(n=40):
    return [101.0] * n, [99.0] * n, [100.0] * n


def test_window_30_excludes_current_bar():
    H, L, C = _base()
    H[35], L[35], C[35] = 102.0, 100.0, 101.5          # свой high выше close — окно его не включает
    ev = rp.detect_events(sym4(H, L, C), need_adx=True)
    assert [(e[1], e[2]) for e in ev] == [(1, 35)]
    assert ev[0][0] == rp.START + 36 * rp.H4            # время события — закрытие 4h-свечи


def test_window_is_exactly_30_previous_bars():
    H, L, C = _base()
    H[35], L[35], C[35] = 102.0, 100.0, 101.5
    H[5] = 101.6                                        # i−30 — внутри окна → пробоя нет
    assert rp.detect_events(sym4(H, L, C), need_adx=True) == []
    H[5], H[4] = 101.0, 101.6                           # i−31 — вне окна → пробой есть
    assert [e[2] for e in rp.detect_events(sym4(H, L, C), need_adx=True)] == [35]


def test_first_time_above_rule_and_adx_independent():
    H, L, C = _base()
    H[35], L[35], C[35] = 102.0, 100.0, 101.5
    H[36], L[36], C[36] = 103.0, 101.0, 102.5          # снова выше 30-high, но предыдущий close уже был выше
    assert [e[2] for e in rp.detect_events(sym4(H, L, C), need_adx=True)] == [35]
    adx = np.full(40, 25.0)
    adx[35] = 15.0                                      # первый пробой без ADX — второй не становится «первым»
    assert rp.detect_events(sym4(H, L, C, adx=adx), need_adx=True) == []
    assert [e[2] for e in rp.detect_events(sym4(H, L, C, adx=adx), need_adx=False)] == [35]   # C2 — без ADX


def test_short_mirror_and_adx_threshold_inclusive():
    H, L, C = _base()
    H[35], L[35], C[35] = 100.0, 98.0, 98.5
    adx = np.full(40, 20.0)                             # ADX ≥ 20 — включительно
    ev = rp.detect_events(sym4(H, L, C, adx=adx), need_adx=True)
    assert [(e[1], e[2]) for e in ev] == [(-1, 35)]
    adx[35] = 19.999
    assert rp.detect_events(sym4(H, L, C, adx=adx), need_adx=True) == []


def test_hole_in_window_blocks_event():
    H, L, C = _base()
    H[35], L[35], C[35] = 102.0, 100.0, 101.5
    s = sym4(H, L, C)
    s.b4["ok"][10] = False
    assert rp.detect_events(s, need_adx=True) == []
