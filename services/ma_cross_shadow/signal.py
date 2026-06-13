"""Чистая логика MA-cross H5 — без IO, тестируемая.

EMA 14/77/200 по hl2=(H+L)/2. Сигнал = пересечение EMA14×EMA77 на ЗАКРЫТОМ баре.
Фильтры H5 (где НЕ входить, валидированы на 2 биржах):
  ① наклон EMA77 (5 баров) по направлению кросса;
  ② цена на стороне EMA200 (LONG → выше, SHORT → ниже);
  ③ прошлая нога > 4 баров (после whipsaw ≤4 — следующий сигнал ложный).
Сигнал «прошёл H5» = все три True. Иначе — пишем, но помечаем skip + причину.
"""
from __future__ import annotations

SLOPE_BARS = 5
WHIPSAW_BARS = 4


def _ema(xs: list[float], n: int) -> list[float]:
    a = 2.0 / (n + 1)
    e = xs[0]
    out = [e]
    for x in xs[1:]:
        e = x * a + e * (1 - a)
        out.append(e)
    return out


def compute(highs: list[float], lows: list[float], closes: list[float]) -> dict:
    """EMA-серии по hl2 + diff EMA14−EMA77. Списки хронологические (старое→новое)."""
    hl2 = [(h + l) / 2 for h, l in zip(highs, lows)]
    e14 = _ema(hl2, 14)
    e77 = _ema(hl2, 77)
    e200 = _ema(hl2, 200)
    diff = [a - b for a, b in zip(e14, e77)]
    return {"hl2": hl2, "e14": e14, "e77": e77, "e200": e200, "diff": diff}


def _zigzag(close: list[float], pct: float) -> list[tuple[int, float, str]]:
    """Пивоты ZigZag (idx, price, 'H'/'L'), разворот на pct% от экстремума."""
    piv: list[tuple[int, float, str]] = []
    hi_i = lo_i = 0
    hi = lo = close[0]
    trend = 0
    for i in range(1, len(close)):
        c = close[i]
        if c > hi:
            hi_i, hi = i, c
        if c < lo:
            lo_i, lo = i, c
        if trend >= 0 and c <= hi * (1 - pct / 100):
            piv.append((hi_i, hi, "H")); trend = -1; hi_i = lo_i = i; hi = lo = c
        elif trend <= 0 and c >= lo * (1 + pct / 100):
            piv.append((lo_i, lo, "L")); trend = 1; hi_i = lo_i = i; hi = lo = c
    return piv


def _is_impulse(close: list[float], zz_pct: float = 3.5) -> bool:
    """EW-структура: последние свинги монотонно трендят (HH+HL вверх / LH+LL вниз) =
    импульс (вход качественнее, валидировано на 4ч); перекрытие = коррекция."""
    piv = _zigzag(close, zz_pct)
    if len(piv) < 4:
        return False
    p4 = piv[-4:]
    hs = [p[1] for p in p4 if p[2] == "H"]
    ls = [p[1] for p in p4 if p[2] == "L"]
    if len(hs) >= 2 and len(ls) >= 2:
        return (hs[-1] > hs[-2] and ls[-1] > ls[-2]) or (hs[-1] < hs[-2] and ls[-1] < ls[-2])
    return False


def _last_cross_index(diff: list[float]) -> int | None:
    """Индекс последнего бара, где diff сменил знак (=кросс). None если нет."""
    for i in range(len(diff) - 1, 0, -1):
        if diff[i] == 0 or diff[i - 1] == 0:
            continue
        if (diff[i] > 0) != (diff[i - 1] > 0):
            return i
    return None


def assess_latest(highs: list[float], lows: list[float], closes: list[float]) -> dict | None:
    """Если ПОСЛЕДНИЙ закрытый бар — бар кросса, вернуть сигнал-dict, иначе None.

    dict: direction(1/-1), passed(bool), reasons(list причин skip), entry(close бара),
    ema14/ema77/ema200, slope77, prev_leg_bars, stretch_pct, bar_index.
    """
    n = len(closes)
    if n < 210:  # EMA200 не прогрелась
        return None
    ind = compute(highs, lows, closes)
    diff = ind["diff"]
    last = n - 1
    cx = _last_cross_index(diff)
    if cx != last:           # кросс должен быть именно на последнем закрытом баре
        return None

    d = 1 if diff[last] > 0 else -1
    e77 = ind["e77"]
    e200 = ind["e200"]
    slope77 = e77[last] - e77[last - SLOPE_BARS] if last >= SLOPE_BARS else 0.0
    # длина прошлой ноги: расстояние до предыдущего кросса
    prev_cx = _last_cross_index(diff[:last])
    prev_leg = (last - prev_cx) if prev_cx is not None else 99
    entry = closes[last]
    stretch = abs(entry - e77[last]) / entry * 100

    reasons = []
    slope_ok = (slope77 > 0) == (d == 1)
    if not slope_ok:
        reasons.append("наклон EMA77 против кросса")
    side_ok = (entry > e200[last]) == (d == 1)
    if not side_ok:
        reasons.append("цена не на стороне EMA200")
    leg_ok = prev_leg > WHIPSAW_BARS
    if not leg_ok:
        reasons.append(f"прошлая нога {prev_leg}≤{WHIPSAW_BARS} (whipsaw)")

    return {
        "direction": d,
        "passed": bool(slope_ok and side_ok and leg_ok),
        "reasons": reasons,
        "entry": round(entry, 4),
        "ema14": round(ind["e14"][last], 4),
        "ema77": round(e77[last], 4),
        "ema200": round(e200[last], 4),
        "slope77": round(slope77, 4),
        "prev_leg_bars": prev_leg,
        "stretch_pct": round(stretch, 3),
        "ew_impulse": _is_impulse(closes),   # EW: импульс = качественнее вход (4ч)
    }
