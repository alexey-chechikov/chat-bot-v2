"""cScalp 5м: бэктест ПРОБОЙ vs ОТБОЙ от плотности + fee-математика безубытка.
Плотность аппроксимируем (у меня нет истории стакана): уровни = Donchian hi/lo (кластеры стопов/
очевидные S/R, что скальперы и торгуют) + дневной POC (узел объёма). Это ПРОКСИ реальной плотности
в DOM — калибровка ожиданий, не финальное слово (живую абсорбцию ты читаешь в cScalp сам).
Тест строго каузален: уровни из ПРОШЛОГО, вход на касании, выход вперёд по TP/SL/таймауту.
Считаем gross и NET-of-fee (тейкер vs мейкер) — на 5м комиссия решает. Данные: BitMEX 5м (кэш data/cscalp)."""
import urllib.request, json, time, os, sys
import numpy as np, pandas as pd

UA = {"User-Agent": "Mozilla/5.0"}
CACHE = "data/cscalp"
def get(u): return json.load(urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=30))

def fetch_5m(sym, days=30):
    os.makedirs(CACHE, exist_ok=True)
    path = f"{CACHE}/{sym}_5m.csv"
    if os.path.exists(path):
        return pd.read_csv(path, index_col=0, parse_dates=True)
    start = (pd.Timestamp.utcnow() - pd.Timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    rows, st = [], start
    while True:
        u = (f"https://www.bitmex.com/api/v1/trade/bucketed?binSize=5m&partial=false&symbol={sym}"
             f"&count=1000&reverse=false&startTime={st}")
        k = get(u)
        if not k: break
        rows += k
        if len(k) < 1000: break
        st = k[-1]["timestamp"]; time.sleep(1.1)
    df = pd.DataFrame(rows); df["ts"] = pd.to_datetime(df["timestamp"])
    df = df.drop_duplicates("ts").set_index("ts").sort_index()[["open", "high", "low", "close", "volume"]]
    df.to_csv(path); return df

def daily_poc(df, win=288, bins=80):
    """POC trailing win баров (каузально): цена-бин с макс объёмом. Возвращает Series POC на каждом баре."""
    c = df["close"].to_numpy(); v = df["volume"].to_numpy(); n = len(c); poc = np.full(n, np.nan)
    for i in range(win, n):
        lo, hi = c[i - win:i].min(), c[i - win:i].max()
        if hi <= lo: continue
        edges = np.linspace(lo, hi, bins + 1)
        idx = np.clip(np.digitize(c[i - win:i], edges) - 1, 0, bins - 1)
        vol = np.bincount(idx, weights=v[i - win:i], minlength=bins)
        poc[i] = (edges[vol.argmax()] + edges[vol.argmax() + 1]) / 2
    return poc

def er(close, n=24):
    return (np.abs(close - np.roll(close, n)) /
            pd.Series(np.abs(np.diff(close, prepend=close[0]))).rolling(n).sum().to_numpy())

def backtest(df, L=48, tol=0.0008, brk=0.0006, tp=0.0025, sl=0.0020, K=12, fee_rt=0.0010):
    """L=Donchian lookback (4ч). tol=зона касания. brk=подтв.пробоя. tp/sl/K=выход. fee_rt=round-turn."""
    h, l, c = df["high"].to_numpy(), df["low"].to_numpy(), df["close"].to_numpy()
    n = len(c)
    don_hi = pd.Series(h).rolling(L).max().shift(1).to_numpy()
    don_lo = pd.Series(l).rolling(L).min().shift(1).to_numpy()
    poc = daily_poc(df)
    erv = er(c)
    res = {k: {"brk": [], "bnc": []} for k in ("all", "trend", "range")}

    def exit_ret(i, side):
        for j in range(i + 1, min(i + 1 + K, n)):
            mv = side * (c[j] / c[i] - 1)
            if mv >= tp: return tp
            if mv <= -sl: return -sl
        return side * (c[min(i + K, n - 1)] / c[i] - 1)

    for i in range(L + 1, n - K):
        reg = "trend" if (not np.isnan(erv[i]) and erv[i] > 0.5) else "range"
        levels_up = [x for x in (don_hi[i], poc[i]) if not np.isnan(x)]   # сопротивления сверху
        levels_dn = [x for x in (don_lo[i], poc[i]) if not np.isnan(x)]
        # ПРОБОЙ вверх сопротивления
        for lv in levels_up:
            if h[i] >= lv * (1 - tol) and c[i] > lv * (1 + brk) and c[i - 1] <= lv:
                r = exit_ret(i, +1); res["all"]["brk"].append(r); res[reg]["brk"].append(r); break
        # ОТБОЙ вниз от сопротивления (тык вверх, закрытие ниже уровня)
        for lv in levels_up:
            if h[i] >= lv * (1 - tol) and c[i] < lv and (h[i] - c[i]) / c[i] > brk:
                r = exit_ret(i, -1); res["all"]["bnc"].append(r); res[reg]["bnc"].append(r); break
        # ПРОБОЙ вниз поддержки
        for lv in levels_dn:
            if l[i] <= lv * (1 + tol) and c[i] < lv * (1 - brk) and c[i - 1] >= lv:
                r = exit_ret(i, -1); res["all"]["brk"].append(r); res[reg]["brk"].append(r); break
        # ОТБОЙ вверх от поддержки
        for lv in levels_dn:
            if l[i] <= lv * (1 + tol) and c[i] > lv and (c[i] - l[i]) / c[i] > brk:
                r = exit_ret(i, +1); res["all"]["bnc"].append(r); res[reg]["bnc"].append(r); break
    return res, fee_rt

def stat(arr, fee_rt):
    if len(arr) < 10: return f"n={len(arr):>4}  — мало"
    a = np.array(arr); net = a - fee_rt
    return (f"n={len(arr):>4}  WR{(a>0).mean()*100:>4.0f}%  gross{a.mean()*1e4:>+6.1f}bp  "
            f"NET(тейк){net.mean()*1e4:>+6.1f}bp  NET(мейк){a.mean()*1e4:>+6.1f}bp  "
            f"итог${net.sum()*10000:>+7.0f}/10k-нот")

def main():
    syms = sys.argv[1].split(",") if len(sys.argv) > 1 else ["XBTUSDT", "ETHUSDT"]
    for sym in syms:
        df = fetch_5m(sym)
        res, fee = backtest(df)
        print(f"\n==== {sym} 5м ({len(df)} баров ≈ {len(df)/288:.0f}д) · TP+25bp/SL-20bp/12бар · fee тейкер 10bp round ====")
        for reg in ("all", "trend", "range"):
            tag = {"all": "ВСЕ", "trend": "ТРЕНД(ER>0.5)", "range": "ФЛЭТ(ER<0.5)"}[reg]
            print(f"  [{tag}]")
            print(f"    ПРОБОЙ : {stat(res[reg]['brk'], fee)}")
            print(f"    ОТБОЙ  : {stat(res[reg]['bnc'], fee)}")
    # fee-математика безубытка
    print("\n==== FEE-МАТЕМАТИКА безубытка (R:R и комиссия) ====")
    print("нужен WR, чтобы выйти в 0 при разной цели и комиссии (round-turn):")
    print(f"{'цель/стоп':>12}{'fee 0bp(мейк)':>15}{'fee 5bp':>10}{'fee 10bp(тейк)':>16}{'fee 15bp':>10}")
    for tp, sl in [(25, 20), (20, 20), (30, 15), (15, 15)]:
        row = f"  +{tp}/-{sl}bp ".ljust(12)
        for f in (0, 5, 10, 15):
            be = (sl + f) / (tp + sl) * 100   # WR безубытка = (SL+fee)/(TP+SL)
            row += f"{be:>13.0f}%"
        print(row)
    print("Читать: на 5м цель ~25bp при тейкере 10bp нужен WR ~58-67% — высокая планка.")
    print("Мейкер-вход (встать В плотность лимиткой) опускает планку до ~44-50%. Тейкер-пробой жрёт край.")

if __name__ == "__main__":
    main()
