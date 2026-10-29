"""Показ сравнительной аналитики: HTML с общим курсором (одна ось времени, все панели, числа часа под курсором),
картинка и подпись для Telegram. Данные и эпизоды — services/coinglass_web/compare.py.

    .venv/bin/python3 -m services.coinglass_web.compare_view [путь.html]
"""
from __future__ import annotations

import io
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from services.coinglass_web import compare, hypothesis, scenarios, tv_export

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "state" / "coinglass" / "compare"
CAPTION_LIMIT = 1024
PLOTLY = "https://cdn.jsdelivr.net/npm/plotly.js-dist-min@2.35.2/plotly.min.js"
# РЕЗУЛЬТАТЫ ПРОВЕРОК — показываются рядом с совокупностью, чтобы её не приняли за сигнал
COMPOSITE_NOTE = ("Проверка 01.05–27.10 (research/coinglass_compare/operator_lines.py; «3 из 4» = не меньше трёх "
                  "ненулевых наклонов, нулевых за 180 дней не было — operator_lines_recount.py): все 4 линии в одну "
                  "сторону за 72 ч — BTC 2 дня из 175, ETH 10 (4 попадания из 10); 3 из 4 → 3 суток: BTC 53%, ETH 48% — "
                  "монетка; 3 из 4 → сутки: BTC 60% [50–70] (n 91), ETH 61% [51–71] (n 96) — найдено после прогона, у "
                  "ETH это импульс цены, соседние окна 43–58%. Кандидат, не доказательство. Счёт вперёд — версия "
                  "comp-2 (с 29.10): решение в 06–08 UTC по данным на момент решения, вход — следующая минута Binance. "
                  "Даже 35 из 60 — это 58% с интервалом 46–70%: промежуточная точка, не допуск в торговлю.")


def export_status(sym: str, path: Path | None = None) -> dict | None:
    """Последний прогон выгрузки CoinGlass по символу: статус сверки, время, куда записано."""
    path = path or tv_export.RUNS
    if not path.exists():
        return None
    for line in reversed(compare._tail_lines(path, 600_000)):
        try:
            r = json.loads(line)
        except ValueError:
            continue
        s = (r.get("symbols") or {}).get(sym)
        if s:
            return {"run": r.get("run"), "status": s.get("status"), "why": s.get("why") or s.get("error"),
                    "obs": s.get("obs"), "log": s.get("log", "tv"),
                    "legend": [c.get("ok") for c in s.get("legend_checks", [])]}
    return None

# (ключ, подпись, панель, источник, единицы, охват/примечание)
SERIES = (
    ("px_close", "Цена (свечи)", "price", "Binance REST /fapi/v1/klines 1ч", "USDT", "незакрытый час помечен"),
    ("volume_usd", "Объём", "vol", "CoinGlass, Binance {sym}", "USD", ""),
    ("taker_delta", "Дельта тейкеров (кто бьёт по рынку)", "taker", "CoinGlass Aggregated Futures Taker Buy/Sell",
     "{coin}", "12 бирж по умолчанию CoinGlass (Binance, Bybit, OKX, Deribit, Hyperliquid…; без CME, Bitget, Gate, "
               "MEXC) — список в tv_runs inputs; + агрессивнее покупатели, − продавцы"),
    ("bn_taker_delta_usd", "Дельта тейкеров Binance", "taker", "Binance REST klines (taker buy)", "USD",
     "только Binance; скрыта, включается в легенде"),
    ("bid_ask_delta", "Стакан ±1%: заявки на покупку − на продажу", "book",
     "CoinGlass Aggregated Futures Bid & Ask Delta", "{coin}",
     "лимитные заявки ±1% (Depth 1), не сделки; те же 12 бирж, что у тейкеров"),
    ("fr_pct", "Фандинг Binance — текущая ставка", "fund", "CoinGlass «Ставка финансирования (Свечи)», закрытие часа",
     "% за {fi} ч", "меняющаяся ставка, не выплата"),
    ("fr_oiw_pct", "Фандинг, взвешенный по OI", "fund", "CoinGlass", "% за интервал", "все биржи; интервалы бирж разные"),
    ("fr_premium_pct", "premiumIndex (наш сбор)", "fund", "deriv_live, 5 мин → последнее в часе", "% за {fi} ч",
     "для сверки с CoinGlass; скрыт"),
    ("paid_pct", "Выплаты фандинга Binance", "fund", "Binance REST /fapi/v1/fundingRate", "% за {fi} ч",
     "раз в 8 ч — точки, не непрерывная история"),
    ("liq_all_long", "Ликвидации лонгов, все биржи", "liq", "CoinGlass «Совокупные ликвидации»", "USD",
     "«∅» CoinGlass = пусто, не ноль"),
    ("liq_all_short", "Ликвидации шортов, все биржи", "liq", "CoinGlass «Совокупные ликвидации»", "USD",
     "вниз от нуля, как у CoinGlass"),
    ("liq_coin_long", "Ликвидации лонгов Coin-залогом", "liq", "CoinGlass «Совокупные ликвидации (Coin-залогом)»",
     "USD", "инверсные контракты; часто «∅»"),
    ("liq_coin_short", "Ликвидации шортов Coin-залогом", "liq", "CoinGlass «Совокупные ликвидации (Coin-залогом)»",
     "USD", ""),
    ("our_liq_long", "Наши потоки: лонги", "liq", "liq_raw Binance+Bybit+OKX USDT-M, время биржи", "USD",
     "Binance шлёт не все события — охват неполный; скрыт"),
    ("our_liq_short", "Наши потоки: шорты", "liq", "liq_raw Binance+Bybit+OKX USDT-M, время биржи", "USD", "скрыт"),
    ("ls_acc", "L/S аккаунтов (толпа)", "ls", "CoinGlass = Binance globalLongShortAccountRatio", "отношение", ""),
    ("ls_top_pos", "L/S топов по позициям", "ls", "CoinGlass = Binance topLongShortPositionRatio", "отношение",
     "не Whale Index"),
    ("ls_global", "L/S аккаунтов (наш сбор)", "ls", "deriv_live", "отношение", "для сверки; скрыт"),
    ("wi2", "Whale Index 2", "wi2", "CoinGlass", "индекс", "формула CoinGlass не опубликована"),
    ("oi_coins", "OI Binance", "oi", "CoinGlass «Открытый интерес (Свечи)», закрытие", "{coin}", ""),
)
PANELS = (("price", "Цена", 0.2), ("vol", "Объём, USD", 0.06), ("taker", "Кто бьёт по рынку: дельта тейкеров", 0.09),
          ("book", "Стакан ±1%: покупка − продажа", 0.08), ("fund", "Фандинг, % за интервал ({fi} ч у Binance)", 0.1),
          ("liq", "Ликвидации, USD (лонги ↑, шорты ↓)", 0.12), ("ls", "Лонг/шорт", 0.1),
          ("wi2", "Whale Index 2", 0.08), ("oi", "OI Binance", 0.07))


def _clean(v):
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return v
    return None if math.isnan(f) or math.isinf(f) else round(f, 6)


def coverage(df: pd.DataFrame, paid: pd.DataFrame, sym: str, coin: str, now: datetime, fi: str = "?") -> list[dict]:
    """Охват каждого ряда в окне показа: первый/последний, пропуски среди закрытых часов, свежесть."""
    closed_end = pd.Timestamp(now).floor("1h")
    out = []
    for key, label, panel, src, units, note in SERIES:
        if key == "paid_pct":
            s = paid["paid_pct"] if not paid.empty else pd.Series(dtype=float)
            missing = None
        else:
            s = df[key] if key in df else pd.Series(dtype=float, index=df.index)
            closed = s[s.index < closed_end]
            missing = int(closed.isna().sum())
        s = s.dropna()
        last = s.index.max() if len(s) else None
        out.append({"key": key, "label": label, "source": src.format(sym=sym), "units": units.format(coin=coin, fi=fi),
                    "note": note, "first": s.index.min().strftime("%d.%m %H:%M") if len(s) else None,
                    "last": last.strftime("%d.%m %H:%M") if last is not None else None,
                    "missing": missing, "hours": int((df.index < closed_end).sum()) if key != "paid_pct" else None,
                    "fresh_min": int((pd.Timestamp(now) - last).total_seconds() / 60) - 60 if last is not None else None})
    return out


def payload(sym: str, now: datetime | None = None, *, data=None) -> dict:
    """Всё для показа одного символа: ряды за 14 суток, выплаты, эпизоды, охват, «что сейчас», совокупность."""
    now = now or datetime.now(timezone.utc)
    df, paid, meta = data if data is not None else compare.frame(sym, now)
    coin = sym.replace("USDT", "")
    z = compare.zscores(df)
    start = pd.Timestamp(now).floor("1h") - pd.Timedelta(days=compare.SHOW_DAYS)
    eps = compare.find_episodes(df, z, start, closed_before=pd.Timestamp(now).floor("1h"), top=6)
    episodes = []
    for i, ep in enumerate(eps, 1):
        d = compare.describe(df, ep, now)
        d["id"] = f"E{i}"
        episodes.append(d)
    view = df[df.index >= start]
    fi = (meta.get("funding_interval") or {}).get("hours")
    fi = str(fi) if fi else "?"
    comp = compare.composite(df, pd.Timestamp(now).floor("1h"))
    rec, src = scenarios.current(sym, df, now)
    sc = scenarios.card(rec, sym, now) if rec else None
    if sc:
        sc["source"] = src
    hy = hypothesis.build(rec, sym, df, now, hypothesis.last_shown(sym, before=now))
    p = {"sym": sym, "coin": coin, "built": now.isoformat(timespec="seconds"), "scenario": sc, "hypothesis": hy,
         "export": export_status(sym),
         "t": [t.strftime("%Y-%m-%d %H:%M") for t in view.index],
         "warsaw": [t.tz_convert(compare.WARSAW).strftime("%d.%m %H:%M") for t in view.index],
         "closed": [bool(t + pd.Timedelta(hours=1) <= pd.Timestamp(now)) for t in view.index],
         "ohlc": {k: [_clean(v) for v in view[f"px_{k}"]] for k in ("open", "high", "low", "close")},
         "s": {k: [_clean(v) for v in view[k]] if k in view else [] for k, *_ in SERIES if k != "paid_pct"},
         "paid": {"t": [t.strftime("%Y-%m-%d %H:%M") for t in paid.index[paid.index >= start]] if not paid.empty else [],
                  "v": [_clean(v) for v in paid["paid_pct"][paid.index >= start]] if not paid.empty else []},
         "episodes": episodes, "coverage": coverage(view, paid[paid.index >= start] if not paid.empty else paid, sym,
                                                    coin, now, fi),
         "now": compare.now_summary(df, now, coin), "checks": meta.get("checks"), "errors": meta.get("errors"),
         "composite": comp, "composite_live": compare.composite_stats(sym), "composite_note": COMPOSITE_NOTE,
         "tv_last_obs": meta.get("tv_last_obs"), "funding_interval": meta.get("funding_interval")}
    p["meta_series"] = [{"key": k, "label": lab, "panel": pan, "units": u.format(coin=coin, fi=fi),
                         "source": s_.format(sym=sym), "note": note} for k, lab, pan, s_, u, note in SERIES]
    p["panels"] = [{"id": a, "title": b.format(fi=fi), "h": c} for a, b, c in PANELS]
    return json.loads(json.dumps(p, ensure_ascii=False, default=_clean))


# ─────────────────────────────── HTML ───────────────────────────────

HTML = r"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Сравнение метрик CoinGlass</title>
<meta name="claude:viewport-fit-sides" content="cover">
<script src="__PLOTLY__"></script>
<style>
/* одна ось времени, панели стопкой; справа (на телефоне — сверху) числа часа под курсором */
:root{--bg:#f5f6f4;--panel:#ffffff;--ink:#1c1e21;--muted:#646a70;--line:#dfe2df;--up:#13895c;--down:#c93c3c;
--accent:#2f62c9;--warn:#a86c12;--ep:rgba(47,98,201,.10);--grid:#eceeec;--c1:#2f62c9;--c2:#b07a12;--c3:#7c4fe0;--c4:#0d8a96}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#111316;--panel:#191b1f;--ink:#e6e8ea;
--muted:#979ca3;--line:#2a2d33;--up:#2fbf86;--down:#ef6262;--accent:#6d97ef;--warn:#e0a63a;--ep:rgba(109,151,239,.14);
--grid:#23262b;--c1:#6d97ef;--c2:#e0a63a;--c3:#a78bfa;--c4:#3cc4d2;color-scheme:dark}}
:root[data-theme="dark"]{--bg:#111316;--panel:#191b1f;--ink:#e6e8ea;--muted:#979ca3;--line:#2a2d33;--up:#2fbf86;
--down:#ef6262;--accent:#6d97ef;--warn:#e0a63a;--ep:rgba(109,151,239,.14);--grid:#23262b;--c1:#6d97ef;--c2:#e0a63a;
--c3:#a78bfa;--c4:#3cc4d2;color-scheme:dark}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 -apple-system,
BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;padding-left:max(16px,env(safe-area-inset-left,0px));
padding-right:max(16px,env(safe-area-inset-right,0px));padding-block:0 24px}
header{padding-block:14px 6px;display:flex;flex-wrap:wrap;gap:10px;align-items:baseline}
h1{font-size:18px;margin:0 8px 0 0;text-wrap:balance}.sub{color:var(--muted);font-size:12px}
.bar{display:flex;flex-wrap:wrap;gap:6px;padding-block:0 8px}
button:focus-visible{outline:2px solid var(--accent);outline-offset:1px}
button{background:var(--panel);color:var(--ink);border:1px solid var(--line);border-radius:6px;padding:5px 10px;
font:inherit;cursor:pointer}button.on{background:var(--accent);color:#fff;border-color:var(--accent)}
.wrap{display:grid;grid-template-columns:minmax(0,1fr) 330px;gap:12px}
#chart{background:var(--panel);border:1px solid var(--line);border-radius:8px;height:1500px;min-width:0}
#read{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:10px;font-size:12.5px;
position:sticky;top:8px;align-self:start;max-height:calc(100vh - 16px);overflow:auto}
#read table{width:100%;border-collapse:collapse;table-layout:fixed}#read td{padding:2px 4px;
border-bottom:1px solid var(--line);vertical-align:top;overflow-wrap:anywhere}#read td.v{text-align:right;width:40%;
font-variant-numeric:tabular-nums}
.gap{color:var(--warn)}.muted{color:var(--muted)}.pos{color:var(--up)}.neg{color:var(--down)}
section{padding-block:12px}h2{font-size:16px;margin:4px 0 8px}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:10px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:10px 12px}
.card h3{margin:0 0 6px;font-size:14px}.card ul{margin:4px 0;padding-left:18px}.card li{margin:2px 0}
.lbl{font-weight:600;font-size:12px;color:var(--muted);margin-top:6px;text-transform:uppercase;letter-spacing:.03em}
table.cov{width:100%;border-collapse:collapse;font-size:12.5px;background:var(--panel)}
table.cov td,table.cov th{border:1px solid var(--line);padding:4px 6px;text-align:left;vertical-align:top}
.nowbox{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:10px 12px}
.nowbox li{margin:2px 0}.scroll{overflow-x:auto}
.st{font-size:17px;font-weight:650;margin:0 0 4px}.cols{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));
gap:10px;margin-top:6px}.act{border:1px solid var(--line);border-radius:6px;padding:6px 8px}
table.ph{border-collapse:collapse;font-size:12px;margin:4px 0;width:100%}table.ph td,table.ph th{border-bottom:1px solid
var(--line);padding:2px 4px;text-align:right;font-variant-numeric:tabular-nums}table.ph td:first-child,table.ph th:first-child{text-align:left}
@media (max-width:900px){.wrap{grid-template-columns:1fr}#read{position:sticky;top:env(safe-area-inset-top,0px);
z-index:5;max-height:38vh;order:-1}#chart{height:1300px}.cards{grid-template-columns:1fr}}
</style></head><body>
<header><h1>Метрики вместе: цена, поток, стакан, фандинг, ликвидации, L/S, Whale Index 2, OI</h1>
<span class="sub" id="built"></span></header>
<div class="bar" id="syms"></div>
<div class="bar"><button data-r="24">24 ч</button><button data-r="168">7 дней</button><button data-r="0" class="on">
всё (14 дней)</button><span class="sub" style="align-self:center">ось — UTC; в подсказке и эпизодах — время Варшавы
(с 25.10 UTC+1, до того UTC+2)</span></div>
<div class="bar" id="epbtns"></div>
<div class="wrap"><div id="chart"></div><div id="read"><div class="muted">Наведите курсор (на телефоне — коснитесь)
на любую панель: здесь будут все числа этого часа.</div></div></div>
<section><h2>Состояние рынка и теневое действие сеток</h2><div class="nowbox" id="scn"></div></section>
<section><h2>Что сейчас</h2><div class="nowbox"><ul id="now"></ul><div id="comp" class="sub"></div></div></section>
<section><h2>Эпизоды: где метрики сошлись и где разошлись</h2><div class="sub" style="margin-bottom:8px">Эпизод —
часы, где необычны метрики минимум трёх разных семейств (цена/объём, поток, ликвидации, OI, фандинг, позиции):
для цены, потока, OI, фандинга и позиций — |z| ≥ 3 по медиане и MAD предыдущих 7 суток; для объёма и ликвидаций —
всплеск: не ниже 98-го процентиля недели и ≥ 3 её медиан (кратность медианы, это не z). Только прошлое. Совпадение —
описание, не прогноз. «После» в вывод не входит.</div><div class="cards" id="eps"></div></section>
<section><h2>Источники и охват</h2><div class="scroll"><table class="cov" id="cov"></table></div>
<div class="sub" id="checks" style="margin-top:6px"></div></section>
<script id="data" type="application/json">__DATA__</script>
<script>
const D = JSON.parse(document.getElementById('data').textContent);
const SYMS = Object.keys(D); let cur = SYMS[0]; let range = 0;
const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const fmt = (v, k) => { if (v === null || v === undefined) return '<span class="gap">пропуск</span>';
  const a = Math.abs(v);
  if (/^liq|^our_liq|volume|bn_taker/.test(k)) return (v < 0 ? '−' : '') + (a >= 1e6 ? '$' + (a / 1e6).toFixed(2) + 'M' : '$' + (a / 1e3).toFixed(1) + 'K');
  if (/pct/.test(k)) return v.toFixed(4) + '%';
  if (/ls_/.test(k)) return v.toFixed(3);
  if (k === 'wi2') return (v > 0 ? '+' : '') + v.toFixed(1);
  if (a >= 1000) return (v < 0 ? '−' : '') + Math.round(a).toLocaleString('ru-RU');
  return (v < 0 ? '−' : '') + a.toFixed(a >= 10 ? 1 : 2); };
const sg = (v, d, suf) => v === null || v === undefined ? '—' : (v > 0 ? '+' : v < 0 ? '−' : '') + Math.abs(v).toFixed(d) + (suf || '');
const px = v => v === null || v === undefined ? '—' : (v >= 1000 ? Math.round(v).toLocaleString('ru-RU') : v.toFixed(2));
const SHORT = {volume_usd: 'Объём', taker_delta: 'Тейкеры, все биржи', bn_taker_delta_usd: 'Тейкеры Binance',
  bid_ask_delta: 'Стакан ±1%', fr_pct: 'Ставка Binance', fr_oiw_pct: 'Ставка по OI', fr_premium_pct: 'premiumIndex (наш)',
  liq_all_long: 'Лонги, все биржи', liq_all_short: 'Шорты, все биржи', liq_coin_long: 'Лонги, Coin-залог',
  liq_coin_short: 'Шорты, Coin-залог', our_liq_long: 'Лонги, наши потоки', our_liq_short: 'Шорты, наши потоки',
  ls_acc: 'Толпа (аккаунты)', ls_top_pos: 'Топы (позиции)', ls_global: 'Толпа (наш сбор)', wi2: 'Whale Index 2',
  oi_coins: 'OI Binance'};
function domains(p) { const gap = 0.012, tot = p.panels.reduce((s, x) => s + x.h, 0), n = p.panels.length;
  const free = 1 - gap * (n - 1); let top = 1; const out = {};
  p.panels.forEach((x, i) => { const h = x.h / tot * free; out[x.id] = {d: [top - h, top], ax: i ? 'y' + (i + 1) : 'y',
    lay: i ? 'yaxis' + (i + 1) : 'yaxis', title: x.title}; top -= h + gap; }); return out; }
const HIDDEN = new Set(['bn_taker_delta_usd', 'fr_premium_pct', 'our_liq_long', 'our_liq_short', 'ls_global']);
function traces(p, dm) { const t = p.t, up = css('--up'), dn = css('--down'), tr = [];
  tr.push({type: 'candlestick', x: t, open: p.ohlc.open, high: p.ohlc.high, low: p.ohlc.low, close: p.ohlc.close,
    xaxis: 'x', yaxis: dm.price.ax, name: 'Цена', meta: 'full', hoverinfo: 'none', increasing: {line: {color: up}},
    decreasing: {line: {color: dn}}, showlegend: false});
  const col = {taker_delta: null, bid_ask_delta: null, fr_pct: css('--c1'), fr_oiw_pct: css('--c2'),
    fr_premium_pct: css('--c3'), ls_acc: css('--c1'), ls_top_pos: css('--c2'), ls_global: css('--c3'),
    wi2: css('--c3'), oi_coins: css('--c4'), volume_usd: css('--muted'), bn_taker_delta_usd: css('--c3')};
  for (const m of p.meta_series) { const k = m.key, y = p.s[k]; if (!y || !y.length) continue;
    const base = {x: t, y: y, xaxis: 'x', yaxis: dm[m.panel].ax, name: m.label, meta: 'full', hoverinfo: 'none',
      legendgroup: m.panel, visible: HIDDEN.has(k) ? 'legendonly' : true};
    if (k === 'px_close') continue;
    if (k === 'taker_delta' || k === 'bid_ask_delta') tr.push({...base, type: 'bar',
      marker: {color: y.map(v => v === null ? 'rgba(0,0,0,0)' : (v >= 0 ? up : dn))}});
    else if (k === 'volume_usd') tr.push({...base, type: 'bar', marker: {color: css('--muted')}, opacity: .55});
    else if (k === 'liq_all_long' || k === 'liq_all_short') tr.push({...base, type: 'bar',
      y: y.map(v => v === null ? null : (k === 'liq_all_long' ? Math.abs(v) : -Math.abs(v))),
      marker: {color: k === 'liq_all_long' ? up : dn}, opacity: .8});
    else if (k === 'liq_coin_long' || k === 'liq_coin_short') tr.push({...base, type: 'bar', width: 1.6e6,
      y: y.map(v => v === null ? null : (k === 'liq_coin_long' ? Math.abs(v) : -Math.abs(v))),
      marker: {color: css('--c2')}});
    else if (k === 'our_liq_long' || k === 'our_liq_short') tr.push({...base, type: 'scatter', mode: 'lines',
      y: y.map(v => v === null ? null : (k === 'our_liq_long' ? Math.abs(v) : -Math.abs(v))),
      line: {color: css('--c3'), width: 1}});
    else tr.push({...base, type: 'scatter', mode: 'lines', line: {color: col[k] || css('--ink'), width: 1.4},
      connectgaps: false}); }
  if (p.paid.t.length) tr.push({type: 'scatter', mode: 'markers', x: p.paid.t, y: p.paid.v, xaxis: 'x',
    yaxis: dm.fund.ax, name: 'Выплаты фандинга Binance', marker: {size: 6, color: css('--warn'), symbol: 'diamond'},
    hoverinfo: 'none', legendgroup: 'fund'});
  return tr; }
function layout(p, dm) { const ink = css('--ink'), grid = css('--grid'), L = {paper_bgcolor: css('--panel'),
  plot_bgcolor: css('--panel'), font: {color: ink, size: 11}, margin: {l: 52, r: 12, t: 8, b: 30}, barmode: 'overlay',
  bargap: 0, hovermode: 'x', hoversubplots: 'axis', dragmode: 'pan', showlegend: true,
  legend: {orientation: 'h', y: -0.025, font: {size: 10}},
  xaxis: {type: 'date', rangeslider: {visible: false}, gridcolor: grid, anchor: dm.oi.ax, showspikes: false},
  shapes: [], annotations: []};
  for (const id in dm) { L[dm[id].lay] = {domain: dm[id].d, gridcolor: grid, zerolinecolor: css('--line'),
    fixedrange: false, automargin: true};
    L.annotations.push({xref: 'paper', yref: 'paper', x: 0, y: dm[id].d[1], xanchor: 'left', yanchor: 'top',
      text: dm[id].title, showarrow: false, font: {size: 10.5, color: css('--muted')}, bgcolor: css('--panel'),
      borderpad: 2}); }
  p.episodes.forEach(e => { const x0 = e.start.slice(0, 16).replace('T', ' '), x1 = new Date(Date.parse(e.end) + 3600e3)
      .toISOString().slice(0, 16).replace('T', ' ');
    L.shapes.push({type: 'rect', xref: 'x', yref: 'paper', x0: x0, x1: x1, y0: 0, y1: 1, fillcolor: css('--ep'),
      line: {width: 0}, layer: 'below'});
    L.annotations.push({x: x0, y: 1, xref: 'x', yref: 'paper', text: e.id, showarrow: false, xanchor: 'left',
      yanchor: 'top', font: {size: 11, color: css('--accent')}}); });
  L.shapes.push({type: 'line', xref: 'x', yref: 'paper', x0: p.t[p.t.length - 1], x1: p.t[p.t.length - 1], y0: 0,
    y1: 1, line: {color: css('--accent'), width: 1, dash: 'dot'}, visible: false});
  if (range) { const end = Date.parse(p.t[p.t.length - 1].replace(' ', 'T') + 'Z');
    L.xaxis.range = [new Date(end - range * 3600e3).toISOString().slice(0, 16).replace('T', ' '),
      new Date(end + 3600e3).toISOString().slice(0, 16).replace('T', ' ')]; }
  return L; }
let pending = null;
function readout(p, i) { const rows = [`<tr><td colspan="2"><b>${p.warsaw[i]} Варшава</b> · ${p.t[i].slice(5)} UTC
  ${p.closed[i] ? '' : ' · <span class="gap">час не закрыт</span>'}</td></tr>`];
  const o = p.ohlc; rows.push(`<tr><td>Цена, закрытие</td><td class="v">${px(o.close[i])}</td></tr>
    <tr><td class="muted">макс / мин часа</td><td class="v muted">${px(o.high[i])} / ${px(o.low[i])}</td></tr>`);
  let last = '';
  for (const m of p.meta_series) { if (m.key === 'px_close' || m.key === 'paid_pct') continue;
    const y = p.s[m.key]; if (!y || !y.length) continue; const panel = p.panels.find(x => x.id === m.panel).title;
    if (panel !== last) { rows.push(`<tr><td colspan="2" class="muted" style="padding-top:6px">${panel}</td></tr>`); last = panel; }
    const v = y[i], cls = v === null ? '' : (/delta|liq_all_long|liq_coin_long|our_liq_long/.test(m.key) ? (v >= 0 ? 'pos' : 'neg') : '');
    rows.push(`<tr title="${m.label}: ${m.source}${m.note ? ' — ' + m.note : ''}"><td>${SHORT[m.key] || m.label}
      <span class="muted">${m.units}</span></td><td class="v ${cls}">${fmt(v, m.key)}</td></tr>`); }
  const e = p.episodes.find(e => p.t[i] >= e.start.slice(0, 16).replace('T', ' ') && p.t[i] <= e.end.slice(0, 16).replace('T', ' '));
  if (e) rows.push(`<tr><td colspan="2" style="padding-top:6px"><b>${e.id}</b>: ${e.main}</td></tr>`);
  document.getElementById('read').innerHTML = '<table>' + rows.join('') + '</table>'; }
function hook(p) { const el = document.getElementById('chart');
  el.on('plotly_hover', ev => { const pt = ev.points.find(q => q.data.meta === 'full'); if (!pt) return;
    const i = pt.pointIndex; readout(p, i); if (pending) return;
    pending = requestAnimationFrame(() => { pending = null; const k = el.layout.shapes.length - 1;
      Plotly.relayout(el, {[`shapes[${k}].x0`]: p.t[i], [`shapes[${k}].x1`]: p.t[i], [`shapes[${k}].visible`]: true}); }); }); }
function epCards(p) { const box = document.getElementById('eps'), btns = document.getElementById('epbtns');
  btns.innerHTML = p.episodes.map(e => `<button data-e="${e.id}">${e.id} ${e.when.split(' Варшава')[0]}</button>`).join('');
  const num = x => x === null || x === undefined ? 'нет данных' : x;
  const utc = s => s ? s.slice(5, 16).replace('T', ' ') + ' UTC' : '';
  const phTab = e => { const ph = e.phases; if (!ph || !ph.phases.length) return '';
    return `<div class="lbl">Фазы по часам</div><table class="ph"><tr><th>часы (UTC)</th><th>что было</th><th>тейкеры</th><th>OI Binance</th><th>ликв. лонгов / шортов</th></tr>` +
      ph.phases.map(f => `<tr><td>${f.from.slice(11, 16)}–${f.to.slice(11, 16)}</td><td>${f.label}</td><td>${fmt(f.taker, 'taker')}</td><td>${sg(f.oi_pct, 2, '%')}</td><td>${fmt(f.liq_long, 'liq')} / ${fmt(f.liq_short, 'liq')}</td></tr>`).join('') +
      `</table><div class="sub">${ph.note}</div>`; };
  box.innerHTML = p.episodes.length ? p.episodes.map(e => { const n = e.numbers, pr = n.price,
    a6 = e.after['6h'], a24 = e.after['24h'], cv = n.coverage || {},
    part = Object.entries(cv).filter(([k, v]) => v[0] < v[1] && !/ours/.test(k)).map(([k, v]) => `${k} ${v[0]} из ${v[1]} ч`),
    aft = h => h ? `цена ${sg(h.price_pct, 2, '%')}, OI ${sg(h.oi_pct, 2, '%')}; ${h.first_close_beyond ? 'гипотеза не выдержала: закрытие за уровнем ' + utc(h.first_close_beyond) : 'закрытий за уровнем гипотезы не было'}` : 'ещё не наступило';
    return `<div class="card" id="card-${e.id}"><h3>${e.id} · ${e.when} · ${e.hours} ч · ${e.direction}</h3>
    <div class="sub">необычны: ${e.metrics.join(', ')}</div>
    <div class="lbl">Числа</div><ul>
    <li>цена ${px(pr.before)} → ${px(pr.end)} (${sg(pr.pct, 2, '%')}), диапазон ${px(pr.low)}–${px(pr.high)}</li>
    <li>объём ×${n.volume_x_median === null ? '—' : n.volume_x_median.toFixed(1)} к медиане часа; тейкеры ${fmt(n.taker_delta_coins, 'taker')} ${p.coin} (6 ч до: ${fmt(n.taker_delta_6h_before, 'taker')})</li>
    <li>OI ${sg(n.oi_pct, 2, '%')}; фандинг ${n.funding_pct.map(v => sg(v, 4, '%')).join(' → ')}</li>
    <li>толпа L/S ${n.ls_acc.map(v => v === null ? '—' : v.toFixed(2)).join(' → ')}; топы ${n.ls_top.map(v => v === null ? '—' : v.toFixed(2)).join(' → ')}; Whale Index 2 ${n.wi2.map(v => sg(v, 1)).join(' → ')}</li>
    <li>ликвидации все биржи: лонги ${fmt(n.liq_all_usd[0], 'liq')}, шорты ${fmt(n.liq_all_usd[1], 'liq')}; Coin-залогом ${fmt(n.liq_coin_usd[0], 'liq')} / ${fmt(n.liq_coin_usd[1], 'liq')}; наши потоки ${fmt(n.liq_ours_usd[0], 'liq')} / ${fmt(n.liq_ours_usd[1], 'liq')}</li></ul>
    ${part.length ? `<div class="sub gap">окна неполные: ${part.join(', ')} — суммы по полученным часам, в выводы не идут</div>` : ''}
    ${phTab(e)}
    <div class="lbl">Совпало</div><ul>${e.agree.length ? e.agree.map(x => `<li>${x}</li>`).join('') : '<li class="muted">—</li>'}</ul>
    <div class="lbl">Разошлось</div><ul>${e.differ.length ? e.differ.map(x => `<li>${x}</li>`).join('') : '<li class="muted">—</li>'}</ul>
    <div class="lbl">Наблюдение и с чем совместимо</div><div>${e.main}</div>
    <div class="lbl">Альтернатива</div><div>${e.alt}</div>
    <div class="lbl">Гипотеза на 24 ч (записана сразу)</div><div>${e.watch}</div>
    <div class="lbl">Условие смены сценария</div><div>${e.cancel}</div>
    <div class="lbl">Что было после (в вывод не входит)</div><div class="sub">через 6 ч: ${aft(a6)}<br>через 24 ч: ${aft(a24)}</div>
    </div>`; }).join('') : '<div class="muted">За 14 дней эпизодов по правилу нет.</div>';
  btns.querySelectorAll('button').forEach(b => b.onclick = () => { const e = p.episodes.find(x => x.id === b.dataset.e);
    const s = Date.parse(e.start), f = Date.parse(e.end);
    Plotly.relayout('chart', {'xaxis.range': [new Date(s - 18 * 3600e3).toISOString().slice(0, 16).replace('T', ' '),
      new Date(f + 30 * 3600e3).toISOString().slice(0, 16).replace('T', ' ')]});
    document.getElementById('card-' + e.id).scrollIntoView({behavior: 'smooth', block: 'nearest'}); }); }
function hyp(p) { const h = p.hypothesis; if (!h) return '';
  const li = a => a && a.length ? a.map(x => `<li>${x}</li>`).join('') : '<li class="muted">—</li>';
  return `<div class="st">${h.header}</div><div style="margin:6px 0 8px"><b>${h.conclusion}</b></div>
    <div class="cols"><div><div class="lbl">Почему</div><ul>${li(h.why)}</ul></div>
    <div><div class="lbl">Что против</div><ul>${li(h.against)}</ul></div></div>
    <div class="lbl">Подтвердит</div><div>${h.confirm || '—'}</div><div class="lbl">Отменит</div><div>${h.cancel || '—'}</div>
    ${h.change ? `<div class="lbl">С прошлого показа</div><div>${h.change}</div>` : ''}
    <div class="sub">Гипотеза ${h.v} не откалибрована — вероятность не пишу. Подробности состояния ниже.</div><hr>`; }
function scn(p) { const el = document.getElementById('scn'), c = p.scenario;
  if (!c) { el.innerHTML = hyp(p) + '<div class="muted">Состояние не определено: данных не хватает.</div>'; return; }
  const li = a => a.length ? a.map(x => `<li>${x}</li>`).join('') : '<li class="muted">—</li>';
  const act = (name, a) => `<div class="act"><b>${name}</b>: новые входы — ${a.entries}; продолжать — ${a.continue}; остаток — ${a.residual}; запуск — ${a.start}<div class="sub">${a.why}</div></div>`;
  const b = c.box ? `${c.box.kind === 'flat' ? 'флет' : 'опорная коробка'} ${px(c.box.L)}–${px(c.box.H)} (${(c.box.width_pct ?? 0).toFixed(2)}%, с ${c.box.set_bar.slice(5, 16).replace('T', ' ')} UTC)` : (c.move ? `движение ${c.move.dir > 0 ? 'вверх' : 'вниз'}: экстремум ${px(c.move.extreme)}, опора ${px(c.move.support)}` : '—');
  el.innerHTML = hyp(p) + `<div class="st">${p.sym}: ${c.state_ru} <span class="sub">(${c.state}, вариант ${c.variant === 'flow' ? 'цена + поток' : 'только цена'})</span></div>
    <div class="sub">по часам до ${c.observed_warsaw} Варшава · давность ${c.age_min} мин · источник: ${c.source}</div>
    <div class="cols"><div><div class="lbl">Поддерживает</div><ul>${li(c.support)}</ul></div>
    <div><div class="lbl">Противоречит</div><ul>${li(c.contra)}</ul></div></div>
    <div class="lbl">Границы</div><div>${b}</div>
    ${c.tags.length ? `<div class="sub">метки: ${c.tags.join('; ')}</div>` : ''}
    <div class="lbl">Следующий переход</div><div>${c.next}</div>
    <div class="lbl">Теневое действие (только журнал)</div><div class="cols">${act('Лонг-сетки', c.actions.long)}${act('Шорт-сетки', c.actions.short)}</div>
    <div class="lbl">Все наблюдения часа</div><ul>${c.facts.map(f => `<li><span class="muted">${f.block}:</span> ${f.text}</li>`).join('')}</ul>
    <div class="sub">${c.note}</div>`; }
function side(p) { document.getElementById('now').innerHTML = p.now.map(x => `<li>${x}</li>`).join('');
  const c = p.composite, nm = {bid_ask_delta: 'стакан', fr_pct: 'фандинг', ls_acc: 'толпа L/S', wi2: 'Whale Index 2'},
    ar = s => s > 0 ? '↑' : (s < 0 ? '↓' : '→');
  const L = p.composite_live || {}, live = L.n ? ` Счёт вперёд (${L.version}): попаданий ${(L.hit * 100).toFixed(0)}% из ${L.n}, интервал ${(L.ci95[0] * 100).toFixed(0)}–${(L.ci95[1] * 100).toFixed(0)}%.` : ` Счёт вперёд (${L.version || 'comp-2'}): исходов пока нет.`;
  document.getElementById('comp').innerHTML = (c ? `<b>Линии 72 ч</b> (как на скрине оператора): ` + Object.entries(c.signs)
    .map(([k, s]) => `${nm[k]} ${ar(s)}`).join(', ') + ` → вверх ${c.pos}, вниз ${c.neg}, без наклона ${c.zero}; ` +
    (c.call ? `согласны 3+ линии ${c.call > 0 ? 'вверх' : 'вниз'}. ` : 'трёх согласных нет. ') : 'Линии 72 ч: в окне есть пропуски. ')
    + p.composite_note + live;
  const cov = p.coverage; document.getElementById('cov').innerHTML = '<tr><th>ряд</th><th>источник</th><th>единицы</th>' +
    '<th>с</th><th>по</th><th>пропуски (закрытые часы)</th><th>свежесть</th><th>примечание</th></tr>' + cov.map(r =>
    `<tr><td>${r.label}</td><td>${r.source}</td><td>${r.units}</td><td>${r.first || '—'}</td><td>${r.last || '—'}</td>
    <td>${r.missing === null ? '—' : r.missing + ' из ' + r.hours}</td><td>${r.fresh_min === null ? 'нет данных' : (r.fresh_min <= 60 ? 'свежий' : 'отстаёт на ' + Math.round(r.fresh_min / 60) + ' ч')}</td>
    <td>${r.note || ''}</td></tr>`).join('');
  const ck = p.checks || {}, cc = ck.close_cg_vs_binance, fr = ck.funding_cg_vs_premiumIndex_pct, ls = ck.ls_acc_cg_vs_binance;
  document.getElementById('checks').innerHTML = 'Проверки: ' + [cc ? `закрытие часа CoinGlass = Binance в ${(cc.share_exact * 100).toFixed(1)}% из ${cc.bars} (со сдвигом на час медиана расхождения ${(ck.close_shifted_1h_max_rel_diff * 100).toFixed(2)}% — время выровнено)` : 'цена CoinGlass/Binance не сверена',
    fr ? `ставка CoinGlass против нашего premiumIndex: медиана расхождения ${fr.median_abs_diff_pp.toFixed(5)} п.п.` : '',
    ls ? `L/S аккаунтов CoinGlass против нашего: медиана ${ls.median_abs_diff.toFixed(3)}` : '',
    `дублей часов ${ck.duplicate_bars ?? '—'}`, Object.keys(p.errors || {}).length ? 'сбои: ' + JSON.stringify(p.errors) : '',
    p.export ? `последняя выгрузка CoinGlass ${(p.export.obs || p.export.run || '').slice(5, 16).replace('T', ' ')} UTC: ${p.export.status === 'ok' ? 'сверена с легендой (' + p.export.legend.filter(Boolean).length + ' из ' + p.export.legend.length + ' баров)' : '<span class="gap">НЕ сверена — в карантине, в графике и сигналах не участвует: ' + (p.export.why || '') + '</span>'}` : ''].filter(Boolean).join('; ') + '.';
  document.getElementById('built').textContent = `собрано ${p.built.replace('T', ' ').slice(0, 16)} UTC · CoinGlass выгружен ${(p.tv_last_obs || '—').replace('T', ' ').slice(0, 16)} UTC`; }
function draw() { const p = D[cur], dm = domains(p);
  Plotly.react('chart', traces(p, dm), layout(p, dm), {responsive: true, displaylogo: false, scrollZoom: true,
    modeBarButtonsToRemove: ['select2d', 'lasso2d', 'autoScale2d']}).then(() => hook(p));
  scn(p); epCards(p); side(p); readout(p, p.t.length - 1); }
document.getElementById('syms').innerHTML = SYMS.map(s => `<button data-s="${s}" class="${s === cur ? 'on' : ''}">${s}</button>`).join('');
document.querySelectorAll('[data-s]').forEach(b => b.onclick = () => { cur = b.dataset.s;
  document.querySelectorAll('[data-s]').forEach(x => x.classList.toggle('on', x === b)); draw(); });
document.querySelectorAll('[data-r]').forEach(b => b.onclick = () => { range = +b.dataset.r;
  document.querySelectorAll('[data-r]').forEach(x => x.classList.toggle('on', x === b)); draw(); });
draw();
</script></body></html>"""


def render_html(payloads: dict[str, dict], standalone: bool = True) -> str:
    """standalone — полный документ (файл в Telegram); иначе — содержимое для страницы claude.ai (обёртку
    doctype/html/head/body добавляет публикация)."""
    data = json.dumps(payloads, ensure_ascii=False).replace("</", "<\\/")
    html = HTML.replace("__PLOTLY__", PLOTLY).replace("__DATA__", data)
    if not standalone:
        for tag in ('<!doctype html>\n<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" '
                    'content="width=device-width, initial-scale=1">\n', "</style></head><body>", "</body></html>"):
            html = html.replace(tag, "</style>" if tag.startswith("</style>") else "")
    return html


# ─────────────────────────────── картинка и подпись ───────────────────────────────

def render_png(p: dict) -> bytes:
    """9 панелей как в HTML, эпизоды затенены и подписаны E1…; для Telegram."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    t = pd.to_datetime(p["t"])
    s = {k: np.array([np.nan if v is None else v for v in vals], dtype=float) for k, vals in p["s"].items() if vals}
    o = {k: np.array([np.nan if v is None else v for v in vals], dtype=float) for k, vals in p["ohlc"].items()}
    bg, ink, mut, up, dn = "#121316", "#e8e8ea", "#9a9aa2", "#2fbf86", "#ef6262"
    hs = [x["h"] for x in p["panels"]]
    with plt.rc_context({"text.parse_math": False, "font.size": 8}):
        fig, axs = plt.subplots(len(hs), 1, figsize=(11, 15), sharex=True, gridspec_kw={"height_ratios": hs},
                                facecolor=bg)
        try:
            from matplotlib.ticker import FuncFormatter

            def human(v, _pos=None):
                a_ = abs(v)
                return (f"{v / 1e9:.1f}B" if a_ >= 1e9 else f"{v / 1e6:.0f}M" if a_ >= 1e6 else
                        f"{v / 1e3:.0f}K" if a_ >= 1e4 else f"{v:g}")
            ax = {x["id"]: a for x, a in zip(p["panels"], axs)}
            w = 0.03
            for a, (x, title) in zip(axs, [(x["id"], x["title"]) for x in p["panels"]]):
                a.set_facecolor(bg)
                a.tick_params(colors=mut, labelsize=7)
                for sp in a.spines.values():
                    sp.set_color("#2c2d33")
                a.grid(color="#24252b", lw=0.5)
                a.yaxis.set_major_formatter(FuncFormatter(human))
                a.text(0.003, 0.97, title, transform=a.transAxes, va="top", ha="left", color=ink, fontsize=7.5,
                       zorder=5, bbox={"facecolor": bg, "edgecolor": "none", "alpha": 0.75, "pad": 1})
            a = ax["price"]
            colors = np.where(o["close"] >= o["open"], up, dn)
            a.vlines(t, o["low"], o["high"], color=colors, lw=0.6)
            a.bar(t, o["close"] - o["open"], bottom=o["open"], width=w, color=colors)
            ax["vol"].bar(t, s.get("volume_usd", np.zeros(len(t))), width=w, color=mut, alpha=0.6)
            for k, pan in (("taker_delta", "taker"), ("bid_ask_delta", "book")):
                if k in s:
                    ax[pan].bar(t, s[k], width=w, color=np.where(s[k] >= 0, up, dn))
            for k, c in (("fr_pct", "#6d97ef"), ("fr_oiw_pct", "#e0a63a")):
                if k in s:
                    ax["fund"].plot(t, s[k], color=c, lw=1, label=k)
            if p["paid"]["t"]:
                ax["fund"].scatter(pd.to_datetime(p["paid"]["t"]), p["paid"]["v"], s=10, color="#e0a63a", marker="D",
                                   zorder=3)
            if "liq_all_long" in s:
                ax["liq"].bar(t, np.abs(s["liq_all_long"]), width=w, color=up)
                ax["liq"].bar(t, -np.abs(s["liq_all_short"]), width=w, color=dn)
            for k, c in (("ls_acc", "#6d97ef"), ("ls_top_pos", "#e0a63a")):
                if k in s:
                    ax["ls"].plot(t, s[k], color=c, lw=1.1)
            if "wi2" in s:
                ax["wi2"].plot(t, s["wi2"], color="#a78bfa", lw=1.1)
                ax["wi2"].axhline(0, color=mut, lw=0.5)
            if "oi_coins" in s:
                ax["oi"].plot(t, s["oi_coins"], color="#3cc4d2", lw=1.1)
            for e in p["episodes"]:
                x0 = pd.Timestamp(e["start"]).tz_localize(None)
                x1 = pd.Timestamp(e["end"]).tz_localize(None) + pd.Timedelta(hours=1)
                for a in axs:
                    a.axvspan(x0, x1, color="#6d97ef", alpha=0.13, lw=0)
                axs[0].text(x0, 1.0, e["id"], transform=axs[0].get_xaxis_transform(), color="#6d97ef", fontsize=8,
                            va="top", ha="left", fontweight="bold")
            ax["fund"].text(0.995, 0.97, "синяя — ставка Binance, жёлтая — по OI, ромбы — выплаты", color=mut,
                            fontsize=6.5, transform=ax["fund"].transAxes, va="top", ha="right")
            ax["ls"].text(0.995, 0.97, "синяя — толпа (аккаунты), жёлтая — топы по позициям", color=mut,
                          fontsize=6.5, transform=ax["ls"].transAxes, va="top", ha="right")
            axs[-1].xaxis.set_major_formatter(mdates.DateFormatter("%d.%m"))
            axs[0].set_title(f"{p['sym']} 1ч · CoinGlass + Binance · ось UTC · {p['built'][:16].replace('T', ' ')} UTC",
                             color=ink, fontsize=10, loc="left")
            fig.subplots_adjust(left=0.06, right=0.99, top=0.975, bottom=0.03, hspace=0.12)
            buf = io.BytesIO()
            fig.savefig(buf, format="png", dpi=110, facecolor=bg)
            return buf.getvalue()
        finally:
            plt.close(fig)


def caption(p: dict) -> str:
    """Подпись к картинке: «что сейчас» и эпизоды одной строкой каждый; режется по 1024."""
    lines = [f"🔭 {p['sym']}: метрики вместе за 14 дней (полный разбор с курсором — файл HTML)"]
    sc, hy = p.get("scenario"), p.get("hypothesis")
    if hy:
        lines += hypothesis.lines(hy)
    if sc:
        a = sc["actions"]
        lines.append(f"Теневое (только журнал, не торговый сигнал): лонг-сетки — {a['long']['entries']}"
                     + (f", {a['long']['residual']}" if a["long"]["residual"] != "держать" else "")
                     + f"; шорт-сетки — {a['short']['entries']}"
                     + (f", {a['short']['residual']}" if a["short"]["residual"] != "держать" else ""))
    lines += [f"• {x}" for x in p["now"]]
    for e in reversed(p["episodes"]):
        d = e["differ"][0] if e["differ"] else "без расхождений"
        lines.append(f"{e['id']} {e['when'].split(' Варшава')[0]} {e['direction']}: {e['main']} Разошлось: {d}")
    lines.append("Совпадение метрик — описание, не прогноз (проверено на 180 днях, см. HTML).")
    while len("\n".join(lines)) > CAPTION_LIMIT and len(lines) > 3:
        lines.pop(-2)
    return "\n".join(lines)[:CAPTION_LIMIT]


DOC_CAPTION = ("Метрики вместе — открыть файл в браузере: общий курсор с числами часа, эпизоды «совпало/разошлось», "
               "источники и охват")


def build_all(now: datetime | None = None, symbols=compare.SYMBOLS) -> dict:
    """→ {"photos": [(png, caption)…], "html": bytes, "filename": str}; сбой символа — без него, всех — ошибка."""
    import logging
    now = now or datetime.now(timezone.utc)
    pays, photos = {}, []
    for sym in symbols:
        try:
            p = payload(sym, now)
            photos.append((render_png(p), caption(p)))
            pays[sym] = p
        except Exception:                                       # noqa: BLE001
            logging.getLogger(__name__).exception("compare_view.symbol_failed %s", sym)
    if not pays:
        raise RuntimeError("сравнительная аналитика не собралась ни по одному символу")
    html = render_html(pays).encode("utf-8")
    return {"photos": photos, "html": html, "filename": f"metrics_{now.astimezone(compare.WARSAW):%Y%m%d_%H%M}.html",
            "hypotheses": [p["hypothesis"] for p in pays.values() if p.get("hypothesis")], "built": now}


def deliver(photo_fn, doc_fn=None, now: datetime | None = None, symbols=compare.SYMBOLS) -> dict:
    """Картинки (photo_fn(png, caption)) и один HTML на все символы (doc_fn(data, filename, caption)); показанные
    гипотезы — в журнал (для «что изменилось с прошлого показа» и будущей сверки условий)."""
    import logging
    res = build_all(now, symbols)
    for png, cap in res["photos"]:
        photo_fn(png, cap)
    if doc_fn is not None:
        doc_fn(res["html"], res["filename"], DOC_CAPTION)
    for h in res.get("hypotheses") or []:
        try:
            hypothesis.log_shown(h, res.get("built") or now or datetime.now(timezone.utc))
        except Exception:                                       # noqa: BLE001 — журнал не мешает доставке
            logging.getLogger(__name__).exception("compare_view.hypothesis_log_failed %s", h.get("sym"))
    return res


def main() -> int:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else OUT_DIR / "latest.html"
    res = build_all()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(res["html"])
    for i, (png, cap) in enumerate(res["photos"]):
        (out.parent / f"{out.stem}_{i}.png").write_bytes(png)
        print(cap, "\n", len(cap))
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
