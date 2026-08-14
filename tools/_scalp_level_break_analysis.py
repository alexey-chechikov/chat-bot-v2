"""LEVEL_BREAK: 15 103 сигнала = 84% всей ТГ-выдачи. Есть ли эдж.
Проверка: после пробоя ВНИЗ цена должна идти ВНИЗ чаще, чем обычно.
Плюс — сколько из них дубли."""
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path("/Users/alexeychechikov/code/bot7")
s = pd.read_csv(ROOT / "market_live" / "signals.csv", on_bad_lines="skip")
s["ts"] = pd.to_datetime(s["ts_utc"], utc=True, errors="coerce")
s = s.dropna(subset=["ts"])
lb = s[s["signal_type"] == "LEVEL_BREAK"].copy()
print(f"LEVEL_BREAK: {len(lb):,}   период {lb['ts'].min():%d.%m} → "
      f"{lb['ts'].max():%d.%m}")
days = (lb["ts"].max() - lb["ts"].min()).total_seconds() / 86400
print(f"частота: {len(lb)/days:.0f} штук в сутки, "
      f"{len(lb)/days/24:.1f} в час")


def field(js, key):
    try:
        d = json.loads(js)
    except (ValueError, TypeError):
        return None
    return d.get(key)


lb["dir"] = lb["details_json"].apply(lambda x: field(x, "direction"))
lb["price"] = pd.to_numeric(lb["details_json"].apply(
    lambda x: field(x, "price")), errors="coerce")
lb["source"] = lb["details_json"].apply(lambda x: field(x, "source"))
print(f"\nпо направлению: {lb['dir'].value_counts().to_dict()}")
print(f"по источнику:   {lb['source'].value_counts().head(6).to_dict()}")

# --- дубли: одинаковое направление в пределах 10 минут ---
lb = lb.sort_values("ts")
gap = lb["ts"].diff().dt.total_seconds()
same = lb["dir"] == lb["dir"].shift()
dup10 = ((gap < 600) & same).sum()
dup60 = ((gap < 3600) & same).sum()
print(f"\nповторы того же направления в пределах 10 мин: {dup10:,} "
      f"({dup10/len(lb)*100:.0f}%)")
print(f"                                 в пределах часа: {dup60:,} "
      f"({dup60/len(lb)*100:.0f}%)")
print(f"медианный интервал между сигналами: {gap.median():.0f} сек")

# --- эдж ---
px = pd.read_csv(ROOT / "market_live" / "market_1m.csv", on_bad_lines="skip")
px["ts"] = pd.to_datetime(px["ts_utc"], utc=True, errors="coerce")
px = px.dropna(subset=["ts"]).set_index("ts")["close"].sort_index()
px = px[~px.index.duplicated()]
grid = px.resample("1min").last().ffill()

lb["bin"] = lb["ts"].dt.floor("1min")
lb["p0"] = lb["bin"].map(grid)
lb = lb.dropna(subset=["p0", "dir"])
print(f"\nсигналов с ценой: {len(lb):,}")

print("\n" + "=" * 92)
print("ЭДЖ: идёт ли цена в сторону пробоя")
print("=" * 92)
print(f"{'горизонт':>10s} {'после ВНИЗ':>26s} {'после ВВЕРХ':>26s} {'база':>12s}")
gv = grid.to_numpy()
gi = {t: i for i, t in enumerate(grid.index)}
base_all = np.diff(np.log(gv))
for mins in (15, 60, 240, 1440):
    res = {}
    for dr in ("down", "up"):
        sub = lb[lb["dir"] == dr]
        fwd = []
        for t, p0 in zip(sub["bin"], sub["p0"]):
            i = gi.get(t)
            if i is None or i + mins >= len(gv):
                continue
            fwd.append((gv[i + mins] / p0 - 1) * 100)
        fwd = np.array(fwd)
        if len(fwd) < 30:
            continue
        # доля движений в «правильную» сторону
        right = (fwd < 0).mean() if dr == "down" else (fwd > 0).mean()
        res[dr] = (np.median(fwd), right * 100, len(fwd))
    # база: случайные моменты
    rng = np.random.default_rng(1)
    idx = rng.integers(0, len(gv) - mins - 1, 4000)
    bf = (gv[idx + mins] / gv[idx] - 1) * 100
    line = f"{mins:8d}м "
    for dr in ("down", "up"):
        if dr in res:
            m, r, n = res[dr]
            line += f"{m:+7.3f}% верно {r:4.1f}% (n={n:5d}) "
        else:
            line += " " * 26
    line += f"{np.median(bf):+7.3f}%"
    print(line)

print("\nбаза «доля падений» на случайных моментах: "
      f"{(bf < 0).mean()*100:.1f}%")

print("\n" + "=" * 92)
print("СКОЛЬКО ЭТО СТОИТ ВНИМАНИЯ")
print("=" * 92)
print(f"  LEVEL_BREAK составляют {len(s[s['signal_type']=='LEVEL_BREAK'])/len(s)*100:.0f}% "
      f"всей выдачи сигналов")
print(f"  при {len(lb)/days:.0f} шт/сутки это {len(lb)/days*30:.0f} сообщений в месяц")
lv = json.loads((ROOT / "state" / "manual_levels.json").read_text())
b = lv.get("BTCUSD", {})
hv = b.get("hvn", [])
if len(hv) > 1:
    d2 = np.diff(sorted(hv))
    print(f"\n  уровни HVN на BTC: {sorted(hv)}")
    print(f"  расстояние между соседними: {d2.round(1).tolist()} долларов")
    print(f"  это {(d2/np.mean(hv)*100).round(3).tolist()}% цены")
