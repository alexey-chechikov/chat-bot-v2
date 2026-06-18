"""Есть ли эдж в расхождении BTC↔альты по ТОП-20 (вопрос оператора 2026-06-17).

Гипотеза: альт ушёл от BTC (excess-ход) → возвращается (mean-reversion = fade-эдж)
или продолжает (momentum)? Кросс-секция топ-20 USDT-перпов Bybit, 4ч.
excess_back = ret_alt(L) − ret_btc(L); excess_fwd = ret_alt(F) − ret_btc(F).
Эдж = верхний дециль diverger → отрицательный forward (вернулся) и наоборот.
Оговорка: live-фетч ~720 баров 4ч ≈ 120 дней = один режим, тонко.
"""
import json
import time
import urllib.request
import numpy as np

UA = {"User-Agent": "Mozilla/5.0"}
FEE = 0.15  # %/RT taker
STABLE = {"USDC", "USDE", "DAI", "TUSD", "FDUSD", "USDT"}


def get(url):
    return json.load(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20))


def top_alts(n=20):
    d = get("https://api.bybit.com/v5/market/tickers?category=linear")
    rows = d.get("result", {}).get("list", [])
    perps = []
    for r in rows:
        s = r.get("symbol", "")
        if not s.endswith("USDT"):
            continue
        base = s[:-4]
        if base in ("BTC",) or base in STABLE:
            continue
        try:
            to = float(r.get("turnover24h") or 0)
        except ValueError:
            to = 0
        perps.append((s, to))
    perps.sort(key=lambda x: -x[1])
    return [s for s, _ in perps[:n]]


def klines(sym, n=720):
    d = get(f"https://api.bybit.com/v5/market/kline?category=linear&symbol={sym}&interval=240&limit={n}")
    lst = d.get("result", {}).get("list", [])
    rows = sorted(([int(x[0]), float(x[4])] for x in lst), key=lambda r: r[0])
    return {ts: c for ts, c in rows}


def main():
    L, F = 6, 6  # 1 день назад / 1 день вперёд (4ч-бары)
    print("Тяну BTC + топ-20 альтов (Bybit 4ч)…")
    btc = klines("XBTUSDT") if False else klines("BTCUSDT")
    alts = top_alts(20)
    print(f"альты: {', '.join(a[:-4] for a in alts)}\n")
    series = {}
    for s in alts:
        try:
            series[s] = klines(s)
            time.sleep(0.1)
        except Exception:
            pass

    # попарное выравнивание каждого альта с BTC (не требуем общих у всех — токены разного возраста)
    def pairs_for(alt_series, L, F):
        common = sorted(set(btc) & set(alt_series))
        if len(common) < L + F + 30:
            return None
        bc = np.array([btc[t] for t in common]); a = np.array([alt_series[t] for t in common])
        out = []
        for i in range(L, len(common) - F):
            eb = 100 * ((a[i]/a[i-L]-1) - (bc[i]/bc[i-L]-1))
            ef = 100 * ((a[i+F]/a[i]-1) - (bc[i+F]/bc[i]-1))
            out.append((eb, ef))
        return out, len(common)

    pairs = []
    used = []
    for s, sc in series.items():
        r = pairs_for(sc, L, F)
        if r:
            pairs += r[0]; used.append((s[:-4], r[1]))
    if len(pairs) < 200:
        print("мало наблюдений"); return
    pa = np.array(pairs)
    eb, ef = pa[:, 0], pa[:, 1]
    print(f"альтов с историей: {len(used)} ({', '.join(f'{n}({b//6}д)' for n,b in used[:12])}…)")
    print(f"наблюдений (альт×бар): {len(pa)}\n")

    corr = np.corrcoef(eb, ef)[0, 1]
    print(f"corr(excess_back, excess_fwd) = {corr:+.3f}  "
          f"({'mean-reversion (fade-эдж)' if corr < -0.05 else 'momentum' if corr > 0.05 else '≈ноль'})")

    # дециль: верхний 10% diverger (обогнал BTC) → forward; нижний 10% (отстал) → forward
    hi = np.percentile(eb, 90); lo = np.percentile(eb, 10)
    top = ef[eb >= hi]; bot = ef[eb <= lo]
    print(f"\nверхний дециль (обогнал BTC на ≥{hi:.1f}%): forward excess {top.mean():+.2f}% (n{len(top)})")
    print(f"нижний дециль (отстал на ≤{lo:.1f}%):  forward excess {bot.mean():+.2f}% (n{len(bot)})")
    spread = bot.mean() - top.mean()   # long отставших − short обогнавших (если mean-revert > 0)
    print(f"long-short спред (отставшие − обогнавшие): {spread:+.2f}% / {F*4}ч  ·  "
          f"после fee×2 {spread - 2*FEE:+.2f}%")

    # по горизонтам
    print("\nГоризонты (forward excess спред отставшие−обогнавшие):")
    for f2 in (1, 3, 6, 12):
        pp = []
        for s, sc in series.items():
            r = pairs_for(sc, L, f2)
            if r:
                pp += r[0]
        pp = np.array(pp)
        h2 = np.percentile(pp[:, 0], 90); l2 = np.percentile(pp[:, 0], 10)
        sp = pp[pp[:, 0] <= l2][:, 1].mean() - pp[pp[:, 0] >= h2][:, 1].mean()
        print(f"  {f2*4:>2}ч: спред {sp:+.2f}%  после fee {sp-2*FEE:+.2f}%")


if __name__ == "__main__":
    main()
