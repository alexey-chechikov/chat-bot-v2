"""ТРЕНД по каждому активу: старт, сопровождение, ИСТОЩЕНИЕ, конец.

Профили активов калибруются отдельно (tools/calibrate_assets.py →
state/asset_profiles.json): у каждого свои пороги истощения и свой вердикт,
годится ли он для трендового бота.

Что показывает:
  • в тренде или нет; уровни входа (пробой 5д при ADX≥20)
  • Chandelier-стоп ATR×3 = уровень закрытия/разворота
  • ЧЕК-ЛИСТ ИСТОЩЕНИЯ по порогам ДАННОГО актива + вероятность конца

Чек-лист откалиброван на 11 522 наблюдениях (2 года, BTC+ETH+XRP),
база «нога кончится за 2 суток» = 35.7%:
  отрыв от EMA20 ≥ 8%        → 89%  (лифт 2.50x)  ← сильнейший
  отрыв ≥5% И объём ≥2×      → 73%  (2.06x)
  ход ≥15% И RSI≥70 И отрыв≥5→ 70%  (1.97x)
  отрыв ≥5%                  → 67%  (1.87x)
  RSI ≥ 75                   → 56%  (1.58x)
НЕ работают (проверено): хвост-отвержение 1.04x, дивергенция RSI 1.16x,
иссякание объёма 0.93x, длительность ≥7д 0.82x (долгий тренд СКОРЕЕ
продолжится). В чек-лист не включены сознательно.

Запуск: .venv/bin/python3 tools/trend_state.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PROFILES = ROOT / "state" / "asset_profiles.json"
ENTRY_LB = 30          # баров 4h = 5 дней
ATR_MULT = 3.0
ADX_MIN = 20.0
BASE_REVERSAL_PCT = 35.7   # база: нога кончится в ближайшие 2 суток


def _atr(df, n=14):
    tr = pd.concat([df["high"] - df["low"],
                    (df["high"] - df["close"].shift()).abs(),
                    (df["low"] - df["close"].shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()


def _adx(df, n=14):
    up, dn = df["high"].diff(), -df["low"].diff()
    plus = np.where((up > dn) & (up > 0), up, 0.0)
    minus = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = pd.concat([df["high"] - df["low"],
                    (df["high"] - df["close"].shift()).abs(),
                    (df["low"] - df["close"].shift()).abs()], axis=1).max(axis=1)
    a = tr.ewm(alpha=1/n, adjust=False).mean()
    pdi = 100 * pd.Series(plus, index=df.index).ewm(alpha=1/n, adjust=False).mean() / a
    mdi = 100 * pd.Series(minus, index=df.index).ewm(alpha=1/n, adjust=False).mean() / a
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    return dx.ewm(alpha=1/n, adjust=False).mean(), pdi, mdi


def _rsi(c, n=14):
    d = np.diff(c, prepend=c[0])
    up = pd.Series(np.where(d > 0, d, 0)).ewm(alpha=1/n, adjust=False).mean()
    dn = pd.Series(np.where(d < 0, -d, 0)).ewm(alpha=1/n, adjust=False).mean()
    return (100 - 100 / (1 + up / dn.replace(0, np.nan))).to_numpy()


def load_4h(symbol: str, bars: int = 700) -> pd.DataFrame | None:
    p = ROOT / "backtests" / "frozen" / f"{symbol}_1m_2y.csv"
    if p.exists():
        d = pd.read_csv(p)
        unit = "ms" if d["ts"].iloc[-1] > 1e12 else "s"
        d["dt"] = pd.to_datetime(d["ts"], unit=unit, utc=True)
        d = d.set_index("dt").sort_index()
        d = d.resample("4h").agg({"open": "first", "high": "max", "low": "min",
                                  "close": "last", "volume": "sum"}).dropna()
    else:
        from core.data_loader import load_klines
        raw = load_klines(symbol, "4h", 1000)
        d = raw.rename(columns={"open_time": "dt"}).set_index("dt")
        d = d[["open", "high", "low", "close", "volume"]]
    return d.tail(bars)


def analyze(symbol: str, prof: dict) -> dict | None:
    df = load_4h(symbol)
    if df is None or len(df) < 80:
        return None
    df = df.copy()
    df["atr"] = _atr(df)
    df["ema20"] = df["close"].ewm(span=20).mean()
    df["adx"], df["pdi"], df["mdi"] = _adx(df)
    df["vma"] = df["volume"].rolling(30).mean()
    df["hh"] = df["high"].rolling(ENTRY_LB).max().shift(1)
    df["ll"] = df["low"].rolling(ENTRY_LB).min().shift(1)
    df = df.dropna()
    rsi_arr = _rsi(df["close"].to_numpy())

    pos, entry, peak, since, leg_start_px = None, 0.0, 0.0, None, None
    for i, (ts, r) in enumerate(df.iterrows()):
        if pos is None:
            if r["close"] > r["hh"] and r["adx"] >= ADX_MIN:
                pos, entry, peak, since, leg_start_px = "LONG", r["close"], r["high"], ts, r["close"]
            elif r["close"] < r["ll"] and r["adx"] >= ADX_MIN:
                pos, entry, peak, since, leg_start_px = "SHORT", r["close"], r["low"], ts, r["close"]
            continue
        peak = max(peak, r["high"]) if pos == "LONG" else min(peak, r["low"])
        stop = (peak - ATR_MULT * r["atr"] if pos == "LONG"
                else peak + ATR_MULT * r["atr"])
        if (r["close"] < stop) if pos == "LONG" else (r["close"] > stop):
            pos, since, leg_start_px = None, None, None

    last = df.iloc[-1]
    up_bias = last["pdi"] >= last["mdi"]
    rsi_dir = rsi_arr[-1] if up_bias else 100 - rsi_arr[-1]
    stretch_pct = abs(last["close"] - last["ema20"]) / last["ema20"] * 100
    stretch_atr = abs(last["close"] - last["ema20"]) / last["atr"] if last["atr"] else 0
    vol_ratio = last["volume"] / last["vma"] if last["vma"] else 1.0
    # ход текущей ноги: от экстремума за окно входа
    ref = df["low"].tail(ENTRY_LB).min() if up_bias else df["high"].tail(ENTRY_LB).max()
    move_pct = abs(last["close"] / ref - 1) * 100

    res = {"px": last["close"], "adx": last["adx"], "atr": last["atr"],
           "pdi": last["pdi"], "mdi": last["mdi"], "hh": last["hh"],
           "ll": last["ll"], "pos": pos, "rsi": rsi_dir,
           "stretch_pct": stretch_pct, "stretch_atr": stretch_atr,
           "vol_ratio": vol_ratio, "move_pct": move_pct, "dir": "вверх" if up_bias else "вниз"}
    if pos:
        res.update({"entry": entry, "since": since, "peak": peak,
                    "stop": (peak - ATR_MULT * last["atr"] if pos == "LONG"
                             else peak + ATR_MULT * last["atr"])})
        res["open_pnl"] = ((last["close"] / entry - 1) if pos == "LONG"
                           else (1 - last["close"] / entry)) * 100
        res["dist_stop"] = abs(last["close"] - res["stop"]) / last["close"] * 100
    return res


def exhaustion(s: dict, prof: dict) -> tuple[int, list[str], float]:
    """Чек-лист истощения по порогам ДАННОГО актива. → (сколько, детали, P%)."""
    st_med = prof.get("stretch_atr_med", 2.0)
    st_p75 = prof.get("stretch_atr_p75", 2.6)
    rsi_med = prof.get("rsi_med", 68)
    vol_p75 = prof.get("vol_p75", 2.0)
    leg_med = prof.get("leg_move_pct_med", 10.0)

    checks = []
    hit = 0
    # 1) растяжение — сильнейший фактор
    if s["stretch_atr"] >= st_p75:
        hit += 1
        checks.append(f"✔ отрыв от EMA20 {s['stretch_atr']:.1f} ATR ≥ {st_p75} "
                      f"(75-й перц. разворотов) — ГЛАВНЫЙ признак")
    elif s["stretch_atr"] >= st_med:
        hit += 1
        checks.append(f"✔ отрыв {s['stretch_atr']:.1f} ATR ≥ медианы разворотов {st_med}")
    else:
        checks.append(f"✘ отрыв {s['stretch_atr']:.1f} ATR < медианы {st_med} — "
                      f"цена не растянута")
    # 2) размер хода
    if s["move_pct"] >= leg_med:
        hit += 1
        checks.append(f"✔ ход {s['move_pct']:.1f}% ≥ типичной ноги {leg_med}%")
    else:
        checks.append(f"✘ ход {s['move_pct']:.1f}% < типичной ноги {leg_med}% — "
                      f"движение молодое")
    # 3) RSI
    if s["rsi"] >= rsi_med:
        hit += 1
        checks.append(f"✔ RSI по ходу {s['rsi']:.0f} ≥ {rsi_med} (медиана разворотов)")
    else:
        checks.append(f"✘ RSI {s['rsi']:.0f} < {rsi_med}")
    # 4) климакс объёма
    if s["vol_ratio"] >= vol_p75:
        hit += 1
        checks.append(f"✔ объём {s['vol_ratio']:.1f}× ≥ {vol_p75}× — климакс")
    else:
        checks.append(f"✘ объём {s['vol_ratio']:.1f}× — климакса нет")

    # вероятность по замеренным лифтам (база 35.7%)
    p = BASE_REVERSAL_PCT
    if s["stretch_atr"] >= st_p75 and s["vol_ratio"] >= vol_p75:
        p = 73.0
    elif s["stretch_atr"] >= st_p75 and s["move_pct"] >= leg_med and s["rsi"] >= 70:
        p = 70.0
    elif s["stretch_atr"] >= st_p75:
        p = 67.0
    elif s["stretch_atr"] >= st_med and s["rsi"] >= 70:
        p = 53.0
    elif s["rsi"] >= 75:
        p = 56.0
    elif s["stretch_atr"] >= st_med:
        p = 45.0
    return hit, checks, p


def main() -> int:
    try:
        data = json.loads(PROFILES.read_text(encoding="utf-8"))
    except Exception:
        print("нет state/asset_profiles.json — запусти tools/calibrate_assets.py")
        return 1
    print(f"ТРЕНД + ИСТОЩЕНИЕ по активам   (профили от "
          f"{data.get('calibrated_at', '?')[:10]})")
    print(f"база «нога кончится за 2 суток» = {BASE_REVERSAL_PCT}%\n")

    for sym, prof in data.get("assets", {}).items():
        s = analyze(sym, prof)
        if not s:
            print(f"{sym}: нет данных\n")
            continue
        edge = prof.get("trend_edge", {})
        role = ("ТРЕНДОВЫЙ БОТ ОК" if prof.get("trend_bot_ok")
                else "трендового эджа нет → только грид")
        print(f"═══ {sym}  ${s['px']:,.4f} ═══  [{role}: 2г {edge.get('total_pct')}%, "
              f"PF {edge.get('pf')}, WR {edge.get('wr_pct')}%]")
        print(f"  ADX {s['adx']:.0f} · {s['dir']} · ATR {s['atr']:,.4f} · "
              f"типичная нога {prof.get('leg_move_pct_med')}% / "
              f"{prof.get('leg_days_med')}д")

        if s["pos"]:
            print(f"  🔥 В ТРЕНДЕ {s['pos']} с {s['since']:%d.%m %H:%M} от "
                  f"{s['entry']:,.4f} · открытый PnL {s['open_pnl']:+.1f}%")
            print(f"  🛑 ВЫХОД/РАЗВОРОТ: закрытие 4h "
                  f"{'ниже' if s['pos'] == 'LONG' else 'выше'} "
                  f"{s['stop']:,.4f} (до него {s['dist_stop']:.1f}%)")
        else:
            print(f"  тренда нет · вход LONG выше {s['hh']:,.4f} / "
                  f"SHORT ниже {s['ll']:,.4f} (при ADX≥{ADX_MIN:.0f})")

        hit, checks, p = exhaustion(s, prof)
        print(f"  ── ИСТОЩЕНИЕ: {hit}/4 факторов → P(конец движения) ≈ {p:.0f}% "
              f"(база {BASE_REVERSAL_PCT}%)")
        for ch in checks:
            print(f"     {ch}")
        if hit >= 3:
            aft = (f"дальше: полный разворот {prof.get('after_full_reversal_pct')}%, "
                   f"глубокая коррекция {prof.get('after_deep_pct')}%, "
                   f"мелкая {prof.get('after_small_pct')}%")
            print(f"  ⚠️ СОШЛОСЬ {hit}/4 — фиксировать/разворачивать. {aft}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
