"""Есть ли эдж в РАСХОЖДЕНИИ BTC vs альты на топ-20? Две гипотезы, честно, net-of-fee.
Дельта = excess-доход альта над BTC за lookback L. Тест:
  (A) КРОСС-СЕКЦИЯ: ранжируем 20 альтов по excess, лонг топ-квинтиль / шорт нижний, держим H. Моментум?
  (B) ПУЛ time-series: при большом |excess| — продолжается (моментум) или разворачивается (реверсия)?
Альты HIGH-corr с BTC (0.9+), так что long-short ~снимает BTC-бету → меряем чистый спред.
Анти-оверфит: половины h1/h2, по горизонтам, с комиссией. Данные BitMEX 4ч (топ-20 по обороту = прокси cap)."""
import urllib.request, json, time, sys
import numpy as np, pandas as pd

UA = {"User-Agent": "Mozilla/5.0"}
def get(u): return json.load(urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=30))

def top_alts(n=20):
    ins = get("https://www.bitmex.com/api/v1/instrument/active")
    perps = [i for i in ins if i.get("state") == "Open" and i.get("typ") == "FFWCSX"
             and str(i.get("symbol", "")).endswith("USDT")]
    perps.sort(key=lambda i: -(i.get("turnover24h") or 0))
    perps = [i["symbol"] for i in perps if i["symbol"] not in ("XBTUSDT",)]
    return perps[:n]

def klines(sym, binSize="1h", resample="4h", days=120):
    start = (pd.Timestamp.utcnow() - pd.Timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    rows, st = [], start
    while True:
        u = (f"https://www.bitmex.com/api/v1/trade/bucketed?binSize={binSize}&partial=false&symbol={sym}"
             f"&count=1000&reverse=false&startTime={st}")
        k = get(u)
        if not k: break
        rows += k
        if len(k) < 1000: break
        st = k[-1]["timestamp"]; time.sleep(0.6)
    if not rows: return None
    df = pd.DataFrame(rows); df["ts"] = pd.to_datetime(df["timestamp"])
    return df.drop_duplicates("ts").set_index("ts")["close"].resample(resample).last()

def klines_4h(sym, days=120):
    return klines(sym, "1h", "4h", days)

def main():
    L = int(sys.argv[1]) if len(sys.argv) > 1 else 6      # lookback баров (1д)
    FEE = 0.0010                                          # round-turn на ногу
    syms = top_alts(20)
    print(f"Топ-20 альтов BitMEX (по обороту): {', '.join(s.replace('USDT','') for s in syms)}")
    btc = klines_4h("XBTUSDT")
    closes = {"BTC": btc}
    for s in syms:
        try:
            k = klines_4h(s)
            if k is not None and k.notna().sum() > 300:
                closes[s] = k
        except Exception:
            pass
        time.sleep(0.2)
    px = pd.DataFrame(closes).dropna()
    alts = [c for c in px.columns if c != "BTC"]
    print(f"С историей: {len(alts)} альтов, {len(px)} баров 4ч ({len(px)/6:.0f}д)\n")
    lr = np.log(px).diff()
    btc_ret = lr["BTC"]
    excess = lr[alts].subtract(btc_ret, axis=0)            # мгновенный excess над BTC
    exc_L = excess.rolling(L).sum()                        # excess за lookback (сигнал-дельта)

    # ---- (A) КРОСС-СЕКЦИЯ: лонг топ / шорт низ по exc_L, форвард-спред ----
    print("==== (A) КРОСС-СЕКЦИЯ long top / short bottom квинтиль по excess ====")
    print(f"{'гор-т':>6}{'момент net%':>13}{'h1':>7}{'h2':>7}{'реверс net%':>13}{'Sharpe-мом':>11}")
    half = len(px) // 2
    for H in [1, 3, 6, 12]:
        fwd = excess.shift(-H).rolling(H).sum() if False else excess[::-1].rolling(H).sum()[::-1].shift(-1)
        fwd = excess.rolling(H).sum().shift(-H)            # excess вперёд на H
        q = exc_L.rank(axis=1, pct=True)
        longm = (q >= 0.8); shortm = (q <= 0.2)
        ls = (fwd[longm].mean(axis=1) - fwd[shortm].mean(axis=1))   # моментум-спред на бар-решение
        ls = ls.dropna()
        # берём непересекающиеся решения каждые H баров
        idx = ls.index[::H]
        mom = ls.loc[idx] - 2 * FEE                        # 2 ноги fee
        rev = -ls.loc[idx] - 2 * FEE
        sh = mom.mean() / mom.std() * np.sqrt(len(mom)) if mom.std() > 0 else 0
        h1 = mom.loc[mom.index < px.index[half]].sum() * 100
        h2 = mom.loc[mom.index >= px.index[half]].sum() * 100
        print(f"{H*4:>5}ч{mom.sum()*100:>13.1f}{h1:>7.1f}{h2:>7.1f}{rev.sum()*100:>13.1f}{sh:>11.2f}")

    # ---- (B) ПУЛ time-series: большой |excess| → продолжение или разворот ----
    print("\n==== (B) ПУЛ: excess за L → forward excess (H=L), по бакетам силы расхождения ====")
    H = L
    fwd = excess.rolling(H).sum().shift(-H)
    sig = exc_L.shift(0)
    pairs = pd.DataFrame({"sig": sig.values.ravel(), "fwd": fwd.values.ravel()}).dropna()
    pairs = pairs[np.abs(pairs["sig"]) > 0.005]            # отсечь шум <0.5%
    pairs["bucket"] = pd.qcut(pairs["sig"], 5, labels=["сильн↓", "↓", "0", "↑", "сильн↑"])
    print(f"  корреляция sig↔fwd: {pairs['sig'].corr(pairs['fwd']):+.3f}  (+ = моментум, − = реверсия)")
    print(f"  {'бакет excess':>14}{'n':>7}{'ср.fwd excess%':>16}")
    for b, g in pairs.groupby("bucket", observed=True):
        print(f"  {str(b):>14}{len(g):>7}{g['fwd'].mean()*100:>15.2f}%")
    # «торгуемый» край: лонг сильн↑ / шорт сильн↓ (моментум) vs наоборот
    top = pairs[pairs.bucket == "сильн↑"]["fwd"].mean()
    bot = pairs[pairs.bucket == "сильн↓"]["fwd"].mean()
    print(f"\n  моментум-край (лонг сильн↑ − шорт сильн↓): {(top-bot)*100:+.2f}%/сделку gross; "
          f"после fee 20bp: {((top-bot)-0.002)*100:+.2f}%")

def daily_test():
    """ДНЕВКИ ~700д: недельный кросс-секционный моментум (где эдж в крипте обычно и живёт)."""
    FEE = 0.0010
    syms = top_alts(20); btc = klines("XBTUSDT", "1d", "1D", 700)
    closes = {"BTC": btc}
    for s in syms:
        try:
            k = klines(s, "1d", "1D", 700)
            if k is not None and k.notna().sum() > 120: closes[s] = k
        except Exception: pass
        time.sleep(0.2)
    px = pd.DataFrame(closes); px = px[px["BTC"].notna()]   # НЕ dropna по всем (новые токены схлопывали историю);
    alts = [c for c in px.columns if c != "BTC"]             # ранжируем каждый день среди ДОСТУПНЫХ альтов
    print(f"\n==== ДНЕВКИ: {len(alts)} альтов, {len(px)} дней — кросс-секц. моментум excess над BTC ====")
    lr = np.log(px).diff(); excess = lr[alts].subtract(lr["BTC"], axis=0)
    print(f"{'L→H дней':>10}{'момент net%':>13}{'h1':>7}{'h2':>7}{'Sharpe':>8}{'реверс net%':>13}")
    for L, H in [(7, 7), (14, 7), (14, 14), (30, 14), (30, 30)]:
        exc_L = excess.rolling(L).sum(); fwd = excess.rolling(H).sum().shift(-H)
        q = exc_L.rank(axis=1, pct=True)
        ls = (fwd[q >= 0.8].mean(axis=1) - fwd[q <= 0.2].mean(axis=1)).dropna()
        idx = ls.index[::H]; mom = ls.loc[idx] - 2 * FEE
        half = px.index[len(px) // 2]
        sh = mom.mean() / mom.std() * np.sqrt(len(mom)) if mom.std() > 0 else 0
        print(f"{L:>5}→{H:<4}{mom.sum()*100:>13.1f}{mom[mom.index<half].sum()*100:>7.1f}"
              f"{mom[mom.index>=half].sum()*100:>7.1f}{sh:>8.2f}{(-mom-0*FEE).sum()*100:>13.1f}")

def regime_split():
    """OOS для Мака: моментум расхождения по РЕЖИМАМ (альт-сезон vs BTC-доминанс; BTC-вверх vs вниз).
    Мак нашёл +3.1%/24ч на 120д (=альт-сезон). Вопрос: переживёт ли вне альт-сезона / в краху?"""
    FEE = 0.0010
    syms = top_alts(20); btc = klines("XBTUSDT", "1d", "1D", 700)
    closes = {"BTC": btc}
    for s in syms:
        try:
            k = klines(s, "1d", "1D", 700)
            if k is not None and k.notna().sum() > 120: closes[s] = k
        except Exception: pass
        time.sleep(0.2)
    px = pd.DataFrame(closes); px = px[px["BTC"].notna()]
    alts = [c for c in px.columns if c != "BTC"]
    lr = np.log(px).diff(); excess = lr[alts].subtract(lr["BTC"], axis=0)
    btc_sma = px["BTC"].rolling(50).mean()
    btc_up = px["BTC"] > btc_sma                                   # BTC-тренд вверх/вниз
    altseason = excess.mean(axis=1).rolling(30).sum() > 0          # альты в среднем бьют BTC = альт-сезон
    print(f"\n==== OOS по РЕЖИМАМ (дневки {len(px)}д, {len(alts)} альтов) ====")
    print(f"альт-сезон дней: {int(altseason.sum())}/{len(px)} · BTC-вверх: {int(btc_up.sum())}/{len(px)}")
    for L, H in [(2, 2), (3, 3)]:
        exc_L = excess.rolling(L).sum(); fwd = excess.rolling(H).sum().shift(-H)
        q = exc_L.rank(axis=1, pct=True)
        ls = (fwd[q >= 0.8].mean(axis=1) - fwd[q <= 0.2].mean(axis=1))   # моментум-спред (лонг-лидер/шорт-аутсайдер)
        ls = (ls - 2 * FEE).reindex(px.index)
        idx = px.index[::H]
        print(f"\n  L→H={L}→{H}д (моментум-спред, net fee, per-режим среднее за ребаланс):")
        for label, mask in [("альт-сезон", altseason), ("BTC-доминанс", ~altseason),
                            ("BTC↑", btc_up), ("BTC↓", ~btc_up)]:
            sub = ls.loc[idx][mask.reindex(idx).fillna(False)].dropna()
            if len(sub) >= 4:
                wr = (sub > 0).mean() * 100
                print(f"    {label:14} n={len(sub):>3}  ср/ребал {sub.mean()*100:>+5.2f}%  "
                      f"сумма {sub.sum()*100:>+6.1f}%  win {wr:>3.0f}%")

def regime_switch():
    """ЭДЖ-ХАНТ: режим медленный (недели) → опознаём каузально и ПЕРЕКЛЮЧАЕМ сигнал.
    Альт-сезон → моментум (диверг продолжается); BTC-доминанс → РЕВЕРСИЯ (диверг возвращается).
    Сравниваем: всегда-момент / всегда-реверс / ПЕРЕКЛЮЧ / момент+флэт-в-доминансе. Каузально, half-split."""
    FEE = 0.0010
    syms = top_alts(20); btc = klines("XBTUSDT", "1d", "1D", 700)
    closes = {"BTC": btc}
    for s in syms:
        try:
            k = klines(s, "1d", "1D", 700)
            if k is not None and k.notna().sum() > 120: closes[s] = k
        except Exception: pass
        time.sleep(0.2)
    px = pd.DataFrame(closes); px = px[px["BTC"].notna()]
    alts = [c for c in px.columns if c != "BTC"]
    lr = np.log(px).diff(); excess = lr[alts].subtract(lr["BTC"], axis=0)
    # КАУЗАЛЬНЫЙ ярлык режима: трейлинг-30д средний excess альтов (>0 = альт-сезон), сдвиг на 1 (только прошлое)
    altseason = (excess.mean(axis=1).rolling(30).sum().shift(1) > 0)
    half = px.index[len(px) // 2]
    def rep(name, s):
        s = s.dropna()
        sh = s.mean() / s.std() * np.sqrt(len(s)) if s.std() > 0 else 0
        print(f"    {name:24} сум {s.sum()*100:>+7.1f}%  h1 {s[s.index<half].sum()*100:>+6.1f}  "
              f"h2 {s[s.index>=half].sum()*100:>+6.1f}  win {(s>0).mean()*100:>3.0f}%  Sharpe {sh:>5.2f}")
    print(f"\n==== ЭДЖ-ХАНТ: режим-переключатель (дневки {len(px)}д, {len(alts)} альтов) ====")
    for L, H in [(1, 1), (2, 2), (3, 3)]:
        exc_L = excess.rolling(L).sum(); fwd = excess.rolling(H).sum().shift(-H)
        q = exc_L.rank(axis=1, pct=True)
        mom = (fwd[q >= 0.8].mean(axis=1) - fwd[q <= 0.2].mean(axis=1)) - 2 * FEE   # моментум-спред
        idx = px.index[::H]; m = mom.reindex(idx); reg = altseason.reindex(idx).fillna(True)
        print(f"\n  L→H={L}→{H}д:")
        rep("всегда МОМЕНТУМ", m)
        rep("всегда РЕВЕРСИЯ", -m)
        rep("ПЕРЕКЛЮЧ (мом↔рев)", m.where(reg, -m))
        rep("мом + флэт в доминансе", m.where(reg, 0.0))

def reversion_test():
    """Жёсткая проверка short-term reversal: исполнение со СДВИГОМ на бар (убрать close-to-close подгон)
    + СВИП реалистичной комиссии. Если выживает с задержкой и при тейкер-косте — эдж; если умирает — артефакт."""
    syms = top_alts(20); btc = klines("XBTUSDT", "1d", "1D", 700)
    closes = {"BTC": btc}
    for s in syms:
        try:
            k = klines(s, "1d", "1D", 700)
            if k is not None and k.notna().sum() > 120: closes[s] = k
        except Exception: pass
        time.sleep(0.2)
    px = pd.DataFrame(closes); px = px[px["BTC"].notna()]
    alts = [c for c in px.columns if c != "BTC"]
    lr = np.log(px).diff(); excess = lr[alts].subtract(lr["BTC"], axis=0)
    half = px.index[len(px) // 2]
    exc_L = excess                                       # L=1д сигнал (excess за день)
    q = exc_L.rank(axis=1, pct=True)
    # РЕВЕРСИЯ: лонг нижний дециль (отставшие) / шорт верхний (обогнавшие)
    immediate = (excess.shift(-1)[q <= 0.2].mean(axis=1) - excess.shift(-1)[q >= 0.8].mean(axis=1))  # вход close_t
    delayed = (excess.shift(-2)[q <= 0.2].mean(axis=1) - excess.shift(-2)[q >= 0.8].mean(axis=1))     # вход close_{t+1}
    print(f"\n==== SHORT-TERM REVERSAL: исполнение + комиссия-свип (дневки {len(px)}д, {len(alts)} альтов) ====")
    print("РЕВЕРСИЯ 1д: лонг отставших / шорт обогнавших BTC, ребаланс ежедневно\n")
    for nm, s in [("НЕМЕДЛЕННО (вход close_t — подгон)", immediate),
                  ("СО СДВИГОМ на бар (вход close_t+1 — реально)", delayed)]:
        s = s.dropna()
        print(f"  {nm}:")
        print(f"    {'комиссия/ребаланс':>22}{'сум net%':>10}{'h1':>8}{'h2':>8}{'Sharpe':>8}")
        for c in (0.0, 0.0005, 0.0010, 0.0020, 0.0040):
            net = s - 2 * c                              # 2 ноги
            sh = net.mean() / net.std() * np.sqrt(len(net)) if net.std() > 0 else 0
            tag = {0.0: "0 (gross)", 0.0005: "5bp/ногу(мейк)", 0.0010: "10bp", 0.0020: "20bp(тейк)", 0.0040: "40bp(альт-слип)"}[c]
            print(f"    {tag:>22}{net.sum()*100:>9.0f}%{net[net.index<half].sum()*100:>8.0f}"
                  f"{net[net.index>=half].sum()*100:>8.0f}{sh:>8.2f}")
    print("\n  Ключ: если СО СДВИГОМ при 20-40bp выживает в ОБЕИХ половинах — эдж реален; если рушится — микроструктура.")

def tf4h_test():
    """Стресс находки Мака на ЕГО таймфрейме: 4ч моментум 24/48ч, реальное исполнение (сдвиг бар) + fee-свип."""
    syms = top_alts(20); btc = klines("XBTUSDT", "1h", "4h", 300)
    closes = {"BTC": btc}
    for s in syms:
        try:
            k = klines(s, "1h", "4h", 300)
            if k is not None and k.notna().sum() > 600: closes[s] = k
        except Exception: pass
        time.sleep(0.3)
    px = pd.DataFrame(closes); px = px[px["BTC"].notna()]
    alts = [c for c in px.columns if c != "BTC"]
    lr = np.log(px).diff(); excess = lr[alts].subtract(lr["BTC"], axis=0)
    half = px.index[len(px) // 2]
    L = 6                                                # 1д lookback (как Мак)
    exc_L = excess.rolling(L).sum(); q = exc_L.rank(axis=1, pct=True)
    print(f"\n==== 4ч МОМЕНТУМ (находка Мака) — реальное исполнение + fee-свип ({len(px)} баров 4ч, {len(alts)} альтов) ====")
    print("МОМЕНТУМ: лонг обогнавших BTC / шорт отставших, лукбэк 1д\n")
    for H, hh in [(6, "24ч"), (12, "48ч")]:
        fwd_imm = excess.rolling(H).sum().shift(-H)      # вход close_t (подгон)
        fwd_del = excess.rolling(H).sum().shift(-H - 1)  # вход close_{t+1} (реально)
        idx = px.index[::H]
        for nm, fwd in [("немедленно (подгон)", fwd_imm), ("СО СДВИГОМ (реально)", fwd_del)]:
            sp = (fwd[q >= 0.8].mean(axis=1) - fwd[q <= 0.2].mean(axis=1)).reindex(idx).dropna()
            line = f"  H={hh:>3} {nm:22}"
            for c in (0.0, 0.0010, 0.0020):
                net = sp - 2 * c
                tag = {0.0: "gross", 0.0010: "10bp", 0.0020: "20bp"}[c]
                h1 = net[net.index < half].sum() * 100; h2 = net[net.index >= half].sum() * 100
                line += f"  {tag}:{net.sum()*100:>+5.0f}%(h1{h1:>+4.0f}/h2{h2:>+4.0f})"
            print(line)
    print("\n  Если СО СДВИГОМ обе половины + при 10-20bp — эдж; если рушится с задержкой — как дневка, артефакт.")

if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    if arg == "daily": daily_test()
    elif arg == "regime": regime_split()
    elif arg == "switch": regime_switch()
    elif arg == "reversion": reversion_test()
    elif arg == "tf4h": tf4h_test()
    else: main()
