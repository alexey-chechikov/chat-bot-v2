"""Alt grid scanner + MegaHard preset adapter (BitMEX). Operator's daily table 2-3x/day.
Scans BitMEX USDT perps, ranks by intraday range x liquidity x chop (low ER), flags danger
(pump/trend), and outputs ready Dynamic-Auto MegaHard settings per candidate (size by notional,
step by vol, mult<=1.4, target>step, + mandatory SL the preset lacks). Data = BitMEX itself.

scan() returns structured rows (used by services/morning_brief); main() prints the table.
2026-06-11 (Win, разбор WLD): памп-отсев, ранжирование к ПИЛЕ (пик ~4% + низкий ER),
охват от волатильности символа (span = clamp(12×√vr, 8, 24)%)."""
import urllib.request, json, numpy as np, pandas as pd, time, datetime
# время-наклон (из анализа BitMEX ~30д): US-день = чоп+амплитуда (хорошо гриду), утро-UTC = тренд
GOOD_HRS = {0, 9, 13, 14, 15, 16, 17}   # UTC, grid-индекс ~2.0-2.1
BAD_HRS  = {1, 5, 6, 11}                 # UTC, grid-индекс ~1.5-1.6 (направленно)

UA = {"User-Agent": "Mozilla/5.0"}
def get(url):
    return json.load(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20))

def klines(sym, n4h=60):
    n1h = n4h * 4 + 8   # BitMEX binSize=4h не поддерживается → тянем 1h, ресемплим
    u = f"https://www.bitmex.com/api/v1/trade/bucketed?binSize=1h&partial=false&symbol={sym}&count={n1h}&reverse=true"
    k = get(u)[::-1]
    df = pd.DataFrame(k)
    df["ts"] = pd.to_datetime(df["timestamp"])
    df = df.set_index("ts")[["open","high","low","close"]].resample("4h").agg(
        {"open":"first","high":"max","low":"min","close":"last"}).dropna()
    return df["high"].to_numpy(float), df["low"].to_numpy(float), df["close"].to_numpy(float)

def metrics(h, l, c):
    tr = np.maximum(h[1:]-l[1:], np.maximum(abs(h[1:]-c[:-1]), abs(l[1:]-c[:-1])))
    atrp = float(pd.Series(tr).ewm(alpha=1/14, adjust=False).mean().iloc[-1]/c[-1]*100)
    rng24 = float((h[-6:].max()-l[-6:].min())/c[-1]*100)
    t7 = float(c[-1]/c[-42]-1)*100 if len(c) >= 42 else 0.0
    t1 = float(c[-1]/c[-6]-1)*100
    diff = np.abs(np.diff(c[-12:])); er = float(abs(c[-1]-c[-12])/diff.sum()) if diff.sum() > 0 else 0.0
    return dict(price=c[-1], atrp=atrp, rng24=rng24, t7=t7, t1=t1, er=er)

SPAN0 = 12.0  # базовый охват для символа с волатильностью = BTC; масштабируем под ATR символа
RISK = 175    # $ риск/бот = жёсткий SL-бэкстоп; ранний выход делает _grid_drift_monitor.py
def adapt(price, atrp, btc_atrp, btc_notional):
    vr = atrp/btc_atrp if btc_atrp else 1.0
    # ОХВАТ от волатильности: волатильнее символ -> шире коридор, чтобы нормальный ход остался ВНУТРИ.
    # Урок WLD 2026-06-10: флэт-12% на 10%-мувере -> мешок пробил SL. span ∈ [8,24]%.
    span = round(min(max(SPAN0*max(vr, 1.0)**0.5, 8.0), 24.0), 1)
    step = round(min(max(0.5*vr, 0.4), 1.5), 2)
    target = round(max(step+0.1, 0.55), 2)
    mult = 1.4 if vr < 2 else 1.3
    ordcnt = int(round(span/step))                  # ордеров под РЕАЛЬНЫЙ охват (не флэт 12)
    # size из РИСКА: полная поза теряет ~RISK при ~span/2 против -> волатильнее = ШИРЕ стоп% = МЕНЬШЕ поза
    maxnotional = RISK/(span/2/100)                 # $-экспозиция полной позы
    sizenotional = maxnotional/5                     # size:max = 1:5 как в пресете
    size = sizenotional/price
    maxsz = maxnotional/price
    baseoff = round(min(1.5*vr, 5.0), 1)
    return dict(vr=vr, step=step, target=target, mult=mult, ordcnt=ordcnt, span=span,
                size=size, maxsz=maxsz, baseoff=baseoff, sl=-RISK, tp=RISK)

def hour_tilt(uh):
    if uh in GOOD_HRS:
        return "🟢 ХОРОШИЙ час (US-день, чоп+амплитуда)"
    if uh in BAD_HRS:
        return "🔴 ПЛОХОЙ час (утро-UTC, направленно — осторожно с новыми)"
    return "🟡 нейтральный час"

def score_row(m, turnover24h, *, pump, danger, thin):
    """Ранжируем к ПИЛЕ (Win 2026-06-11): пик размаха ~4% (хватает доить, не уезжает),
    штраф за >4% и за высокий ER (тренд). Памп = score 0."""
    range_fit = m["rng24"] if m["rng24"] <= 4 else 4*(4.0/m["rng24"])**1.5
    chop = 1 - min(m["er"], 0.9)
    return (range_fit*np.log10(max(turnover24h or 1, 10))*chop
            * (0 if pump else 1) * (0.3 if danger else 1) * (0.4 if thin else 1))

def scan():
    """→ dict(hour_utc, tilt, btc=dict(price, atrp, notional), rows=[...]) — rows
    отсортированы по score, каждая: sym, m (metrics), a (adapt-настройки), liqrel,
    pump, danger, thin, score."""
    ins = get("https://www.bitmex.com/api/v1/instrument/active")
    perps = [i for i in ins if i.get("state") == "Open" and i.get("typ") == "FFWCSX"
             and (i.get("quoteCurrency") == "USDT" or str(i.get("symbol","")).endswith("USDT"))]
    perps.sort(key=lambda i: -(i.get("turnover24h") or 0))
    perps = [i for i in perps if i.get("symbol") not in ("XBTUSDT", "ETHUSDT")][:14]  # альты, топ ликвидные
    # BTC reference
    bh, bl, bc = klines("XBTUSDT"); btc_atrp = metrics(bh, bl, bc)["atrp"]; btc_notional = bc[-1]*0.005
    uh = datetime.datetime.utcnow().hour
    rows = []
    turnovers = [i.get("turnover24h") or 0 for i in perps]
    tmax = max(turnovers) if turnovers else 1
    for i in perps:
        sym = i["symbol"]
        try:
            h, l, c = klines(sym); m = metrics(h, l, c); a = adapt(m["price"], m["atrp"], btc_atrp, btc_notional)
            liqrel = (i.get("turnover24h") or 0)/tmax
            # ПАМП/ОБВАЛ = откат впереди = дрейф = враг грида (урок WLD: уехал -8.4% за день). ЖЁСТКИЙ отсев.
            pump = abs(m["t1"]) > 12 or abs(m["t7"]) > 35
            danger = abs(m["t7"]) > 50 or abs(m["t1"]) > 20 or m["er"] > 0.55
            thin = liqrel < 0.05
            score = score_row(m, i.get("turnover24h"), pump=pump, danger=danger, thin=thin)
            rows.append(dict(sym=sym, m=m, a=a, liqrel=liqrel, pump=pump,
                             danger=danger, thin=thin, score=score))
            time.sleep(0.12)
        except Exception:
            pass
    rows.sort(key=lambda r: -r["score"])
    return dict(hour_utc=uh, tilt=hour_tilt(uh),
                btc=dict(price=float(bc[-1]), atrp=btc_atrp, notional=btc_notional), rows=rows)

def main():
    s = scan()
    uh = s["hour_utc"]
    print(f"⏰ Сейчас {uh:02d}:00 UTC ({(uh+3)%24:02d}:00 мск) — {s['tilt']}")
    print(f"BTC репер: {s['btc']['price']:,.0f}  ATR%4ч {s['btc']['atrp']:.2f}  notional/IN ${s['btc']['notional']:.0f}\n")
    print(f"{'альт':9}{'цена':>10}{'rng24':>6}{'ER':>5}{'ликв':>5} | "
          f"{'step':>5}{'орд':>4}{'охв%':>6}{'target':>7}{'mult':>5}{'size':>10}{'max':>11}{'off':>5}{'TP/SL$':>8}  ст")
    for r in s["rows"]:
        m, a = r["m"], r["a"]
        st = "🚫памп" if r["pump"] else ("🚫" if r["danger"] else ("⚠" if r["thin"] else "✅"))
        tpsl = f"+{a['tp']:.0f}/{a['sl']:.0f}"
        print(f"{r['sym']:9}{m['price']:>10.4f}{m['rng24']:>6.1f}{m['er']:>5.2f}{r['liqrel']:>5.2f} | "
              f"{a['step']:>5}{a['ordcnt']:>4}{a['span']:>6}{a['target']:>7}{a['mult']:>5}"
              f"{a['size']:>10.2f}{a['maxsz']:>11.2f}{-a['baseoff']:>5.1f}{tpsl:>8}  {st}")
    print("\nНастройки Dynamic-Auto MegaHard под альт: охват от ВОЛАТИЛЬНОСТИ символа (волатильнее = шире коридор,")
    print("чтобы нормальный ход остался внутри), order_count=охват/step, size из риска (волатильнее = меньше поза),")
    print("step=0.5×воля, target>step, mult≤1.4, SL=−$175 жёсткий бэкстоп. РАННИЙ выход = drift-монитор по мешку.")
    print("🚫памп=уехал >12%/1д или >35%/7д (откат впереди — НЕ брать) · 🚫тренд/ER · ⚠тонкий · ✅пила. Бери ✅ верх.")
    print("После запуска КАЖДЫЙ бот ведём _grid_drift_monitor.py: дрейф → расширить step/target ×2 → если упорно → закрыть.")

if __name__ == "__main__":
    main()
