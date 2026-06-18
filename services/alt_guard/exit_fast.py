"""EXIT-FAST: подтверждённый взрывной ход (Win, форензика 0 ложных в ренже).
Donchian-пробой + ATR-расширение ×1.4 + объём-спайк ×2.4. Все три → fired, направление.
Спека из REPLY_MAC_SOL_RESUME_WIN_2026-06-17 (SOL 15.06 00:00 @71.18, ралли →75.45)."""
from __future__ import annotations

DONCHIAN_N = 20      # окно пробоя (баров)
ATR_MULT = 1.4       # ход бара ≥ ATR×1.4
VOL_MULT = 2.4       # объём бара ≥ среднего ×2.4


def _atr(highs, lows, closes, n):
    trs = []
    for i in range(1, len(closes)):
        trs.append(max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]),
                       abs(lows[i] - closes[i - 1])))
    if len(trs) < n:
        return None
    return sum(trs[-n:]) / n


def exit_fast(highs: list[float], lows: list[float], closes: list[float],
              vols: list[float], n: int = DONCHIAN_N) -> tuple[bool, int]:
    """→ (fired, direction +1 вверх / −1 вниз). Все три условия на ПОСЛЕДНЕМ баре."""
    if len(closes) < n + 2:
        return False, 0
    atr = _atr(highs, lows, closes, n)
    if not atr or atr <= 0:
        return False, 0
    c = closes[-1]
    bar_move = abs(closes[-1] - closes[-2])
    vol_avg = sum(vols[-n:]) / n if any(vols[-n:]) else 0.0
    vol_ok = vol_avg > 0 and vols[-1] >= vol_avg * VOL_MULT
    atr_ok = bar_move >= atr * ATR_MULT
    # Donchian: пробой максимума/минимума предыдущих n баров (без текущего)
    prior_hi = max(highs[-n - 1:-1])
    prior_lo = min(lows[-n - 1:-1])
    up_break = c > prior_hi
    dn_break = c < prior_lo
    if atr_ok and vol_ok and up_break:
        return True, 1
    if atr_ok and vol_ok and dn_break:
        return True, -1
    return False, 0
