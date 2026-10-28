"""Часовые ряды индикаторов CoinGlass со страницы суперчарта (оператор 27.10: «сравнение метрик — где сходятся
ликвидации, лонги-шорты, фандинг»; задание GPT f2559762 — Whale Index 2 и «Совокупные ликвидации (Coin-залогом)»).

Страница https://www.coinglass.com/tv/ru/Binance_<SYM> — TradingView с индикаторами CoinGlass. Ключ API не нужен:
индикаторы добавляются штатным `createStudy`, значения берутся штатным `exportData` (то же, что «Экспорт данных
графика» TradingView) — ровно то, что нарисовано, с тем же временем бара. Ответы сайта зашифрованы — их не трогаем.
Каждый прогон сверяет выгрузку с легендой графика: курсор на 3 бара, числа легенды против строк выгрузки.

Пишет (только добавление):
- state/coinglass/tv/<SYM>_1h.jsonl — новые или изменившиеся бары: {"bar": начало бара UTC, "obs": время выгрузки,
  "closed": бар закрыт к obs, значения}; «как было известно в момент T» = последняя запись бара с obs ≤ T;
- state/coinglass/tv_runs.jsonl — прогон: настройки графика, найденные индикаторы, охват столбцов, сверка, сбои.
Пустое значение CoinGlass (на графике «∅») хранится как null, нулём не становится.

    .venv/bin/python3 -m services.coinglass_web.tv_export [BTCUSDT ETHUSDT]
"""
from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DIR = ROOT / "state" / "coinglass" / "tv"
RUNS = ROOT / "state" / "coinglass" / "tv_runs.jsonl"
URL = "https://www.coinglass.com/tv/ru/Binance_{sym}"
DAYS = 21
SYMBOLS = ("BTCUSDT", "ETHUSDT")
# (ключ, имя индикатора в списке CoinGlass — регулярное выражение, {подпись линии в выгрузке: столбец}).
# В именах CoinGlass местами латинские «A»/«O» вместо кириллицы — оба варианта.
STUDIES = (
    ("wi2", r"^<CoinGlass> Whale Index 2$", {"value": "wi2"}),
    ("liq_coin", r"^<CoinGlass> Совокупные ликвидации \(Coin-залогом\)$",
     {"Long": "liq_coin_long", "Short": "liq_coin_short"}),
    ("liq_all", r"^<CoinGlass> Совокупные ликвидации$", {"Long": "liq_all_long", "Short": "liq_all_short"}),
    ("ls_acc", r"^<CoinGlass> Лонг/Шорт коэффициент \([AА]ккаунтов\)$", {"value": "ls_acc"}),
    ("ls_top_pos", r"^<CoinGlass> Коэффициент лонг/шорт позиций топ трейдеров$", {"value": "ls_top_pos"}),
    ("fr", r"^<CoinGlass> Ставка финансирования \(Свечи\)$", {"Candles (Цена закр.)": "fr_pct"}),
    ("fr_oiw", r"^<CoinGlass> ставка по финансированию \(взвешенная по открытому интересу\)$", {"Styles": "fr_oiw_pct"}),
    ("oi", r"^<CoinGlass> [OО]ткрытый интерес \(Свечи\)$", {"Candles (Цена закр.)": "oi_coins"}),
    ("vol", r"^Volume$", {"Volume": "volume_usd"}),
    # «кто покупает»: заявки стакана ±1% (лимитные) и агрессор по рынку (тейкер), все биржи CoinGlass, в монетах
    ("ba", r"^<CoinGlass> Aggregated Futures Bid & Ask Delta$", {"Delta": "bid_ask_delta"}),
    ("taker", r"^<CoinGlass> Aggregated Futures Taker Buy/Sell Volume$",
     {"Long": "taker_buy", "Short": "taker_sell", "Delta": "taker_delta"}),
)
SERIES = {"open": "open", "high": "high", "low": "low", "close": "close"}
COLUMNS = ("open", "high", "low", "close", *(c for _, _, m in STUDIES for c in m.values()))

SETUP_JS = """async ({studies, days}) => {
  const f = document.querySelector('iframe');
  const w = f && f.contentWindow;
  if (!w || !w.tradingViewApi) return {ready: false};
  const api = w.tradingViewApi, c = api.activeChart();
  if (c.resolution() !== '60') { await c.setResolution('60'); }
  const all = api.getStudiesList();
  const ids = {}, names = {};
  for (const [key, re] of studies) {
    const rx = new RegExp(re);
    const have = c.getAllStudies().find(s => rx.test(s.name));
    const name = have ? have.name : all.find(n => rx.test(n));
    names[key] = name || null;
    ids[key] = have ? have.id : (name ? await c.createStudy(name, false, false) : null);
  }
  const now = Math.floor(Date.now() / 1000);
  await c.setVisibleRange({from: now - days * 86400, to: now});
  return {ready: true, ids, names, resolution: c.resolution(), symbol: c.symbol()};
}"""

EXPORT_JS = """async (ids) => {
  const w = document.querySelector('iframe').contentWindow, c = w.tradingViewApi.activeChart();
  const ex = await c.exportData({includeTime: true, includeSeries: true, includedStudies: ids});
  return {schema: ex.schema, data: ex.data.map(r => Array.from(r, v => (v === null || Number.isNaN(v)) ? null : v)),
          resolution: c.resolution(), symbol: c.symbol()};
}"""

LEGEND_JS = """() => {
  const d = document.querySelector('iframe').contentDocument;
  const txt = sel => [...d.querySelectorAll(sel)].map(e => e.innerText.replace(/\\s+/g, ' ').trim());
  return {series: txt('[data-name="legend-series-item"]'), studies: txt('[data-name="legend-source-item"]')};
}"""


def columns_of(schema: list[dict], ids: dict) -> list[str | None]:
    """Схема выгрузки → имя нашего столбца для каждой позиции (None — не наш). Позиция 0 — время."""
    by_id = {v: k for k, v in ids.items() if v}
    maps = {k: m for k, _, m in STUDIES}
    out: list[str | None] = []
    for s in schema:
        if s.get("type") == "time":
            out.append("time")
        elif s.get("sourceType") == "series":
            out.append(SERIES.get(s.get("plotTitle")))
        else:
            key = by_id.get(s.get("sourceId"))
            out.append(maps.get(key, {}).get(s.get("plotTitle")) if key else None)
    return out


def rows_of(export: dict, ids: dict) -> dict[int, dict]:
    """Выгрузка → {начало бара, с: {столбец: значение}}; null остаётся null."""
    cols = columns_of(export["schema"], ids)
    out: dict[int, dict] = {}
    for r in export["data"]:
        if r[0] is None:
            continue
        out[int(r[0])] = {c: r[j] for j, c in enumerate(cols) if c and c != "time"}
    return out


_SUF = {"": 1.0, "K": 1e3, "M": 1e6, "B": 1e9}


def parse_shown(tok: str) -> tuple[float | None, float]:
    """Число легенды → (значение, допуск по показанной точности). «∅» → (None, 0)."""
    tok = tok.replace("−", "-").replace(",", "")
    if tok == "∅":
        return None, 0.0
    m = re.fullmatch(r"(-?\d+(?:\.(\d+))?)([KMB]?)", tok)
    if not m:
        raise ValueError(tok)
    dec = len(m.group(2) or "")
    mult = _SUF[m.group(3)]
    return float(m.group(1)) * mult, 0.5 * 10 ** -dec * mult + 1e-12


def legend_values(item: str, name: str) -> list[str]:
    """Текст пункта легенды «<имя> <параметры> No Filter v1 v2» → ["v1", "v2"]."""
    tail = item[len(name):]
    return tail.split("No Filter", 1)[1].split() if "No Filter" in tail else tail.split()[-2:]


def check_legend(legend: dict, rows: dict[int, dict], names: dict) -> dict:
    """Легенда под курсором против выгрузки: бар — по OHLC легенды, линии — по имени индикатора."""
    m = re.search(r"ОТКР\s*([\d.]+)\s*МАКС\s*([\d.]+)\s*МИН\s*([\d.]+)\s*ЗАКР\s*([\d.]+)", " ".join(legend["series"]))
    if not m:
        return {"ok": False, "why": "нет OHLC в легенде"}
    o, h, lo, c = (float(x) for x in m.groups())
    bars = [t for t, r in rows.items() if r.get("open") == o and r.get("close") == c and r.get("high") == h]
    if len(bars) != 1:
        return {"ok": False, "why": f"бар по OHLC не однозначен ({len(bars)})"}
    bar, row = bars[0], rows[bars[0]]
    maps = {k: list(mp.values()) for k, _, mp in STUDIES}
    order = sorted(((n, k) for k, n in names.items() if n), key=lambda x: -len(x[0]))
    checks = []
    for item in legend["studies"]:
        hit = next(((n, k) for n, k in order if item.startswith(n + " ")), None)
        if not hit or hit[1] in ("vol", "fr", "oi"):            # у свечных индикаторов в легенде 4 числа — не сверяем
            continue
        n, key = hit
        shown = legend_values(item, n)
        for col, tok in zip(maps[key], shown):
            try:
                val, tol = parse_shown(tok)
            except ValueError:
                checks.append({"col": col, "shown": tok, "ok": False})
                continue
            got = row.get(col)
            ok = (got is None) if val is None else (got is not None and abs(got - val) <= tol)
            checks.append({"col": col, "shown": tok, "exported": got, "ok": ok})
    return {"bar": datetime.fromtimestamp(bar, timezone.utc).isoformat(), "checks": checks,
            "ok": bool(checks) and all(x["ok"] for x in checks)}


def _last_logged(path: Path) -> dict[int, dict]:
    """Последнее записанное значение каждого бара (для записи только изменений)."""
    out: dict[int, dict] = {}
    if path.exists():
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                    out[int(datetime.fromisoformat(r["bar"]).timestamp())] = r
                except (ValueError, KeyError):
                    continue
    return out


def append_changes(sym: str, rows: dict[int, dict], obs: datetime, *, base: Path = DIR) -> int:
    """Дописать новые и изменившиеся бары; бар закрыт, если его конец ≤ времени выгрузки. → число записей."""
    base.mkdir(parents=True, exist_ok=True)
    path = base / f"{sym}_1h.jsonl"
    prev = _last_logged(path)
    n = 0
    with open(path, "a", encoding="utf-8") as f:
        for t in sorted(rows):
            vals = {c: rows[t].get(c) for c in COLUMNS}
            closed = t + 3600 <= obs.timestamp()
            old = prev.get(t)
            if old and old.get("closed") == closed and all(old.get(c) == vals[c] for c in COLUMNS):
                continue
            f.write(json.dumps({"bar": datetime.fromtimestamp(t, timezone.utc).isoformat(),
                                "obs": obs.isoformat(timespec="seconds"), "closed": closed, **vals}) + "\n")
            n += 1
    return n


def coverage(rows: dict[int, dict]) -> dict:
    """Охват каждого столбца: заполнено/всего, первый и последний заполненный бар."""
    ts = sorted(rows)
    out = {}
    for c in COLUMNS:
        filled = [t for t in ts if rows[t].get(c) is not None]
        out[c] = {"filled": len(filled), "bars": len(ts),
                  "first": datetime.fromtimestamp(filled[0], timezone.utc).isoformat() if filled else None,
                  "last": datetime.fromtimestamp(filled[-1], timezone.utc).isoformat() if filled else None}
    return out


def export_symbol(br, sym: str, days: int = DAYS) -> dict:
    """Один символ: страница → индикаторы → выгрузка, пока не перестанет меняться → сверка с легендой."""
    pg = br.new_page(locale="ru-RU", viewport={"width": 1400, "height": 1600},
                     user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                                "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
    t0 = time.time()
    try:
        pg.goto(URL.format(sym=sym), wait_until="domcontentloaded", timeout=90_000)
        pg.wait_for_function("() => { const f = document.querySelector('iframe'); "
                             "return !!(f && f.contentWindow && f.contentWindow.tradingViewApi); }", timeout=90_000)
        pg.wait_for_timeout(5_000)
        setup = pg.evaluate(SETUP_JS, {"studies": [[k, r] for k, r, _ in STUDIES], "days": days})
        if not setup.get("ready"):
            raise RuntimeError("график не готов")
        ids = setup["ids"]
        want = [v for v in ids.values() if v]
        prev_sig, export, stable = None, None, 0
        for _ in range(30):                                     # до ~90 с: данные индикаторов догружаются
            pg.wait_for_timeout(3_000)
            export = pg.evaluate(EXPORT_JS, want)
            rows = rows_of(export, ids)
            sig = (len(rows), tuple(sum(r.get(c) is not None for r in rows.values()) for c in COLUMNS))
            enough = len(rows) >= days * 24 * 0.9 and all(sig[1][COLUMNS.index(c)] > 0 for k, _r, m in STUDIES
                                                          if ids.get(k) for c in m.values() if not c.startswith("liq"))
            stable = stable + 1 if sig == prev_sig and enough else 0
            prev_sig = sig
            if stable >= 2:
                break
        obs = datetime.now(timezone.utc)
        rows = rows_of(export, ids)
        checks = []
        box = pg.locator("iframe").first.bounding_box()
        for frac in (0.3, 0.55, 0.8):                           # курсор на 3 бара главной панели
            pg.mouse.move(box["x"] + box["width"] * frac * 0.85, box["y"] + box["height"] * 0.12)
            pg.wait_for_timeout(600)
            checks.append(check_legend(pg.evaluate(LEGEND_JS), rows, setup["names"]))
        pg.mouse.move(box["x"] + box["width"] * 0.98, box["y"] + 5)
        return {"sym": sym, "obs": obs, "rows": rows, "setup": setup, "checks": checks, "stable": stable >= 2,
                "seconds": round(time.time() - t0, 1),
                "export_resolution": export.get("resolution"), "export_symbol": export.get("symbol")}
    finally:
        pg.close()


def collect(symbols=SYMBOLS, days: int = DAYS) -> dict:
    """Все символы одним браузером; сбой символа не мешает остальным. → сводка прогона (и в tv_runs.jsonl)."""
    from playwright.sync_api import sync_playwright
    started = datetime.now(timezone.utc)
    summary = {"run": started.isoformat(timespec="seconds"), "days": days, "symbols": {}}
    with sync_playwright() as p:
        br = p.chromium.launch(headless=True)
        try:
            for sym in symbols:
                try:
                    r = export_symbol(br, sym, days)
                    written = append_changes(sym, r["rows"], r["obs"])
                    ts = sorted(r["rows"])
                    summary["symbols"][sym] = {
                        "status": "ok" if r["stable"] and all(c.get("ok") for c in r["checks"]) else "check",
                        "obs": r["obs"].isoformat(timespec="seconds"), "bars": len(ts), "written": written,
                        "first_bar": datetime.fromtimestamp(ts[0], timezone.utc).isoformat() if ts else None,
                        "last_bar": datetime.fromtimestamp(ts[-1], timezone.utc).isoformat() if ts else None,
                        "chart": {"symbol": r["export_symbol"], "resolution": r["export_resolution"]},
                        "studies": r["setup"]["names"], "stable": r["stable"], "legend_checks": r["checks"],
                        "coverage": coverage(r["rows"]), "seconds": r["seconds"]}
                except Exception as exc:                        # noqa: BLE001
                    summary["symbols"][sym] = {"status": "fail", "error": f"{type(exc).__name__}: {exc}"[:300]}
        finally:
            br.close()
    summary["finished"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    RUNS.parent.mkdir(parents=True, exist_ok=True)
    with open(RUNS, "a", encoding="utf-8") as f:
        f.write(json.dumps(summary, ensure_ascii=False) + "\n")
    return summary


def main() -> int:
    syms = tuple(a.upper() for a in sys.argv[1:]) or SYMBOLS
    s = collect(syms)
    for sym, r in s["symbols"].items():
        cov = r.get("coverage") or {}
        print(sym, r["status"], r.get("bars"), r.get("first_bar"), r.get("last_bar"), "записано", r.get("written"),
              "сверка", [c.get("ok") for c in r.get("legend_checks", [])], r.get("error", ""),
              {c: v["filled"] for c, v in cov.items()})
    return 0 if all(r["status"] != "fail" for r in s["symbols"].values()) else 1


if __name__ == "__main__":
    sys.exit(main())
