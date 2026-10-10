"""Трендовая система ETH (правила tools/trend_state: пробой 30 баров 4ч при ADX≥20, выход — закрытие за
Chandelier ATR×3) на 2 годах по СТОРОНАМ и по режиму SMA100 (дневное закрытие вчера выше/ниже SMA100).
Вопрос оператора 10.10: «гейт шортовый, лонги не запускаем — правильно?». Комиссия 0.1% за круг.
Плюс разрез по времени: первый год / второй год."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.trend_state import ADX_MIN, ATR_MULT, ENTRY_LB, _adx, _atr, load_4h  # noqa: E402

SYM = sys.argv[1] if len(sys.argv) > 1 else "ETHUSDT"
df = load_4h(SYM, bars=100_000).copy()
df["atr"] = _atr(df)
df["adx"], _, _ = _adx(df)
df["hh"] = df["high"].rolling(ENTRY_LB).max().shift(1)
df["ll"] = df["low"].rolling(ENTRY_LB).min().shift(1)
df = df.dropna()
daily = pd.read_csv(ROOT / "data" / "historical" / f"daily_{SYM}.csv")
daily["dt"] = pd.to_datetime(daily["ts_ms"], unit="ms", utc=True)
daily = daily.set_index("dt")["close"].astype(float)
above = (daily > daily.rolling(100).mean()).shift(1)          # режим дня D — по закрытию D−1

trades = []
pos = None
for ts, r in df.iterrows():
    if pos is None:
        if r["close"] > r["hh"] and r["adx"] >= ADX_MIN:
            pos = {"side": "LONG", "entry": r["close"], "peak": r["high"], "ts": ts}
        elif r["close"] < r["ll"] and r["adx"] >= ADX_MIN:
            pos = {"side": "SHORT", "entry": r["close"], "peak": r["low"], "ts": ts}
        continue
    if pos["side"] == "LONG":
        pos["peak"] = max(pos["peak"], r["high"])
        stop = pos["peak"] - ATR_MULT * r["atr"]
        out = r["close"] < stop
    else:
        pos["peak"] = min(pos["peak"], r["low"])
        stop = pos["peak"] + ATR_MULT * r["atr"]
        out = r["close"] > stop
    if out:
        d = 1 if pos["side"] == "LONG" else -1
        pnl = d * (r["close"] / pos["entry"] - 1) * 100 - 0.1
        day = pos["ts"].normalize()
        reg = above.asof(day) if day >= above.index[0] else np.nan
        trades.append({"side": pos["side"], "pnl": pnl, "ts": pos["ts"], "above": reg})
        pos = None

t = pd.DataFrame(trades)
t0, t1 = t["ts"].min(), t["ts"].max()
mid = t0 + (t1 - t0) / 2
print(f"{SYM}: {len(t)} сделок {t0:%Y-%m-%d} … {t1:%Y-%m-%d} (середина {mid:%Y-%m-%d}), комиссия 0.1%/круг")


def line(name, s):
    if s.empty:
        return f"{name:<38} нет сделок"
    w, l_ = s[s > 0], s[s <= 0]
    pf = w.sum() / -l_.sum() if l_.sum() else float("inf")
    return f"{name:<38} сделок {len(s):>3}, сумма {s.sum():+7.1f}%, PF {pf:4.2f}, в плюсе {len(w) / len(s):.0%}"


print(line("ВСЕ", t["pnl"]))
for side in ("LONG", "SHORT"):
    s = t[t["side"] == side]
    print(line(side, s["pnl"]))
    print("   " + line(f"{side}, 1-й год", s[s["ts"] < mid]["pnl"]))
    print("   " + line(f"{side}, 2-й год", s[s["ts"] >= mid]["pnl"]))
    print("   " + line(f"{side}, цена ВЫШЕ SMA100", s[s["above"] == True]["pnl"]))   # noqa: E712
    print("   " + line(f"{side}, цена НИЖЕ SMA100", s[s["above"] == False]["pnl"]))  # noqa: E712
g = t[((t["side"] == "LONG") & (t["above"] == True)) | ((t["side"] == "SHORT") & (t["above"] == False))]  # noqa: E712
print(line("ПО ГЕЙТУ (лонг выше, шорт ниже SMA100)", g["pnl"]))
print("   " + line("гейт, 1-й год", g[g["ts"] < mid]["pnl"]))
print("   " + line("гейт, 2-й год", g[g["ts"] >= mid]["pnl"]))
print("   " + line("всё без гейта, 1-й год", t[t["ts"] < mid]["pnl"]))
print("   " + line("всё без гейта, 2-й год", t[t["ts"] >= mid]["pnl"]))
print(line("ТОЛЬКО ШОРТЫ", t[t["side"] == "SHORT"]["pnl"]))

# контроль: тот же гейт, но режим сдвинут по кругу на случайное число дней (то же время «выше/ниже», те же
# переключения, но не привязан к цене) — настоящий гейт должен быть лучше почти всех сдвигов по PF
reg = above.dropna()
rng = np.random.default_rng(11)
pfs = []
for k in rng.integers(60, len(reg) - 60, 30):
    shifted = pd.Series(np.roll(reg.to_numpy(), int(k)), index=reg.index)
    ab = t["ts"].dt.normalize().map(lambda d: shifted.asof(d))
    gg = t[((t["side"] == "LONG") & (ab == True)) | ((t["side"] == "SHORT") & (ab == False))]  # noqa: E712
    w, l_ = gg["pnl"][gg["pnl"] > 0], gg["pnl"][gg["pnl"] <= 0]
    pfs.append((w.sum() / -l_.sum() if l_.sum() else 9.9, gg["pnl"].sum(), len(gg)))
pf_real = g["pnl"][g["pnl"] > 0].sum() / -g["pnl"][g["pnl"] <= 0].sum()
arr = np.array(pfs)
print(f"контроль 30 сдвигов режима: PF {arr[:, 0].min():.2f}…{arr[:, 0].max():.2f} (медиана {np.median(arr[:, 0]):.2f}), "
      f"сумма {arr[:, 1].min():+.0f}…{arr[:, 1].max():+.0f}%; PF не хуже настоящего гейта ({pf_real:.2f}): "
      f"{int((arr[:, 0] >= pf_real).sum())} из 30")
now_close = daily.iloc[-1]
sma_now = daily.rolling(100).mean().iloc[-1]
print(f"сейчас: {SYM} {now_close:,.2f}, SMA100 {sma_now:,.2f} → цена {'ВЫШЕ' if now_close > sma_now else 'НИЖЕ'} SMA100 "
      f"({(now_close / sma_now - 1) * 100:+.1f}%) — по гейту разрешены {'ЛОНГИ' if now_close > sma_now else 'ШОРТЫ'}")
