"""Участки оператора май–октябрь 2026: его чтение против данных + сверка ключевых чисел GPT.

Цена — Binance spot BTCUSDT (минутки, mr_data); средние — как в его индикаторах (TEMA50/100/200, EMA200, зона v11);
CoinGlass — экспорт research/coinglass_compare/data/BTCUSDT_1h.csv (агрегат по биржам; GPT этой истории не имел:
«WI2, ликвидаций, OI после 11 мая нет» — у нас есть с 01.05 по 28.10). Фандинг — фактические выплаты Binance.
Описание, не бэктест: проценты — изменение цены open→close, не PnL."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import gridk  # noqa: E402
import mr_data as md  # noqa: E402

T = lambda s: int(pd.Timestamp(s, tz="UTC").timestamp())  # noqa: E731
SEG = [("6–9 мая", "2026-05-06", "2026-05-10"), ("10–13 мая", "2026-05-10", "2026-05-14"),
       ("12–22 мая", "2026-05-12", "2026-05-23"), ("31 мая–6 июня", "2026-05-31", "2026-06-07"),
       ("7–15 июня", "2026-06-07", "2026-06-16"), ("16 июня–1 июля", "2026-06-16", "2026-07-02"),
       ("2 июля–15 авг", "2026-07-02", "2026-08-16"), ("19–25 авг", "2026-08-19", "2026-08-26"),
       ("26 авг–14 сен", "2026-08-26", "2026-09-15"), ("15–21 сен (отскок от 75k)", "2026-09-15", "2026-09-22"),
       ("22 сен–7 окт (84–87k)", "2026-09-22", "2026-10-08"), ("8–28 окт (у синей ~82k)", "2026-10-08", "2026-10-29"),
       ("29 окт–2 ноя", "2026-10-29", "2026-11-03")]


def main():
    m, h1, h4, d1, fund = md.build()
    cg = pd.read_csv(md.ROOT / "research/coinglass_compare/data/BTCUSDT_1h.csv")
    cg["t"] = pd.to_datetime(cg["bar_utc"]).astype("int64") // 10 ** 9
    cg = cg.set_index("t")
    rows = []
    for nm, a, b in SEG:
        ta, tb = T(a), T(b)
        mm = m[(m["ts"] >= ta) & (m["ts"] < tb)]
        q1 = h1[(h1.index >= ta) & (h1.index < tb)]
        q4 = h4[(h4.index >= ta) & (h4.index < tb)]
        c = cg[(cg.index >= ta) & (cg.index < tb)]
        r = {"участок": nm, "цена_%": round((mm["close"].iloc[-1] / mm["open"].iloc[0] - 1) * 100, 2),
             "high": round(mm["high"].max()), "low": round(mm["low"].min()),
             "4H_ниже_красной_%": round((q4["close"] < q4["R"]).mean() * 100),
             "4H_ниже_жёлтой_%": round((q4["close"] < q4["Y"]).mean() * 100),
             "4H_ниже_EMA200_%": round((q4["close"] < q4["B"]).mean() * 100),
             "1H_ниже_EMA200_%": round((q1["close"] < q1["B"]).mean() * 100),
             "4H_зона_−1/0/+1_%": [round((q4["zone"] == z).mean() * 100) for z in (-1, 0, 1)],
             "4H_spread<0.6_%": round((q4["spread"] < 0.6).mean() * 100)}
        if len(c) and c["taker_buy"].notna().any():
            tb_, ts_ = c["taker_buy"].sum(), c["taker_sell"].abs().sum()
            r["CG_тейкер_покупки_%"] = round(tb_ / (tb_ + ts_) * 100, 2)
            r["CG_часов_с_плюс_дельтой_%"] = round((c["taker_delta"] > 0).mean() * 100)
            r["CG_ликв_лонгов_$M"] = round(c["liq_all_long"].fillna(0).sum() / 1e6, 1)
            r["CG_ликв_шортов_$M"] = round(c["liq_all_short"].abs().fillna(0).sum() / 1e6, 1)
            r["CG_фандинг_ср_%"] = round(c["fr_oiw_pct"].mean(), 4)
            r["CG_фандинг_<0_часов_%"] = round((c["fr_oiw_pct"] < 0).mean() * 100)
            oi = c["oi_coins"].dropna()
            r["CG_OI_%"] = round((oi.iloc[-1] / oi.iloc[0] - 1) * 100, 2) if len(oi) else None
            for k in ("wi2", "ls_acc", "ls_top_pos"):
                s = c[k].dropna()
                r[f"CG_{k}_нач→кон"] = [round(s.iloc[0], 2), round(s.iloc[-1], 2)] if len(s) else None
            r["CG_стакан_bid−ask_ср"] = round(c["bid_ask_delta"].mean(), 1)
            r["CG_стакан_часов_bid>ask_%"] = round((c["bid_ask_delta"] > 0).mean() * 100)
        rows.append(r)
        print(json.dumps(r, ensure_ascii=False), flush=True)
    chk = gpt_checks(m, h1, h4, d1, fund, cg)
    oct_ = oct_82k(m, h4, fund)
    out = HERE / "out"
    out.mkdir(exist_ok=True)
    (out / "segments_result.json").write_text(json.dumps({"segments": rows, "gpt_checks": chk, "oct_82k": oct_},
                                                          ensure_ascii=False, indent=1, default=str))


def gpt_checks(m, h1, h4, d1, fund, cg):
    """Числа GPT, которые можно проверить нашими данными."""
    out = {}
    f = fund[(fund.index >= T("2026-06-03")) & (fund.index < T("2026-06-06"))]
    out["фандинг_3–5_июня"] = {str(pd.to_datetime(t, unit="s")): round(v * 100, 6) for t, v in f.items()}
    neg = f[f < 0]
    if len(neg):
        t0 = int(neg.index[0]) // 3600 * 3600 + 3600
        a = m[m["ts"] == t0]["open"].iloc[0]
        b = m[m["ts"] == t0 + 86400]["open"].iloc[0]
        out["первая_отриц_выплата_и_24ч_после_%"] = [str(pd.to_datetime(neg.index[0], unit="s")), round((b / a - 1) * 100, 2)]
    d = d1[(d1.index >= T("2026-08-17")) & (d1.index < T("2026-08-22"))]
    out["SMA100_19–21_авг"] = {str(pd.to_datetime(t, unit="s").date()): [round(r["close"], 2), round(r["sma100"], 2),
                                                                       r["reg0"], r["reg2"]] for t, r in d.iterrows()}
    q = h4[(h4.index >= T("2026-06-16")) & (h4.index < T("2026-07-02"))]
    out["16июн–1июл_4H_выше_красной_%"] = round((q["close"] > q["R"]).mean() * 100, 2)
    out["16июн–1июл_4H_зона−1_%"] = round((q["zone"] == -1).mean() * 100, 2)
    for nm, tf in (("H1", h1), ("H4", h4)):
        z = tf[(tf.index >= T("2026-05-06")) & (tf.index < T("2026-08-22"))]["zone"]
        ch = z[z != z.shift(1)].iloc[1:]
        out[f"смены_зоны_{nm}_06.05–21.08"] = [f"{pd.to_datetime(tf.loc[t, 'known'], unit='s'):%d.%m %H:%M}→{v:+d}"
                                              for t, v in ch.items()][:40]
    c = cg[(cg.index >= T("2026-05-06")) & (cg.index < T("2026-05-10"))]
    oi = c["oi_coins"].dropna()
    out["CG_OI_6→9_мая_%"] = round((oi.iloc[-1] / oi.iloc[0] - 1) * 100, 2)
    out["CG_ls_acc_6→9_мая"] = [c["ls_acc"].dropna().iloc[0], c["ls_acc"].dropna().iloc[-1]]
    out["CG_ls_top_pos_6→9_мая"] = [c["ls_top_pos"].dropna().iloc[0], c["ls_top_pos"].dropna().iloc[-1]]
    mx = m[(m["ts"] >= T("2026-08-15")) & (m["ts"] < T("2026-11-03"))]
    i = mx["high"].idxmax()
    out["максимум_авг–ноя"] = [str(pd.to_datetime(mx.loc[i, "ts"], unit="s")), mx.loc[i, "high"]]
    return out


def oct_82k(m, h4, fund):
    """Спор «82k»: первое касание EMA200 4H сверху 08.10 при SMA100 вверх. Что дали бы: (а) держать лонг-сетку
    0.6/1.4 до выключения 30.10 (живое правило тогда — до порога SMA100 ~76k), (б) закрыть её на касании,
    (в) шорт-сетка 0.6/1.4 с касания до сегодня и по правилу T1 (до перехода Z4 в +1 или 14 суток).
    Ордер $100, потолок $6 000, издержки живые. Сетки стартуют на касании пустыми — это не живой учёт."""
    k4, L4, C4, B4 = (h4[c].to_numpy() for c in ("known", "low", "close", "B"))
    j = next(j for j in range(1, len(k4)) if k4[j] >= T("2026-10-01") and L4[j] <= B4[j] and C4[j - 1] > B4[j - 1])
    t_touch = int(k4[j])
    mk = gridk.Market(m["ts"].to_numpy(), m["open"].to_numpy(), m["high"].to_numpy(), m["low"].to_numpy(),
                      m["close"].to_numpy(), fund)
    t_now = int(m["ts"].iloc[-1]) + 60
    px = lambda t: float(m[m["ts"] >= t]["open"].iloc[0])  # noqa: E731
    res = {"касание": [str(pd.to_datetime(t_touch, unit="s")), round(B4[j]), round(px(t_touch))],
           "цена_сейчас": float(m["close"].iloc[-1])}
    for nm, a, b, s in (("лонг-сетка с касания до 30.10 00:00", t_touch, T("2026-10-30"), 1),
                        ("шорт-сетка с касания до сейчас", t_touch, t_now, -1),
                        ("шорт-сетка T1 (14 сут)", t_touch, t_touch + 14 * 86400, -1),
                        ("лонг-сетка 22.09→касание (что было до)", T("2026-09-22"), t_touch, 1)):
        r = mk.run(mk.idx([a]), mk.idx([b]), s, cap=6000.0)[0]
        res[nm] = {c: round(float(v), 1) for c, v in zip(gridk.COLS, r)}
    return res


if __name__ == "__main__":
    main()
