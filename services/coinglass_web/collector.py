"""Сбор цифр CoinGlass с публичной страницы «Уровни ликвидаций» (оператор 18.10: «наладить обработку данных с
коинглас»). API CoinGlass с тепловой картой — платный тариф; страница отдаёт цифры только после JavaScript, поэтому —
фоновый браузер (Playwright, headless Chromium), раз в час. Только чтение публичной страницы, без входа и ключей.

Из текста страницы (BTCUSDT Binance) берутся: последняя цена; магнитные зоны — топ-3 с каждой стороны (диапазон,
расстояние, сила, ширина); баланс ближнего поля ±3% (доли и сила лонгов/шортов, изменение доли шортов за 24 ч);
ключевые уровни ±2% (сторона, цена, расстояние, плечо, сила); последние развороты CLLD.

Пишет: state/coinglass/levels.jsonl (разобранное, добавление строк) и state/coinglass/raw_<YYYYMMDD>.txt (сырой текст —
для перепроверки разбора). Код выхода 0 — снимок записан, 1 — страница не загрузилась или не разобралась.

    .venv/bin/python3 -m services.coinglass_web.collector
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DIR = ROOT / "state" / "coinglass"
URL = "https://www.coinglass.com/ru/liquidation-levels"
NUM = r"[\d\s\u00a0\u202f]+(?:,\d+)?"


def num(s: str) -> float:
    return float(re.sub(r"[\s\u00a0\u202f]", "", s).replace(",", "."))


def _zones(block: str) -> list[dict]:
    out = []
    for m in re.finditer(rf"(\d)\n({NUM}) – ({NUM})\n([+-][\d.]+)%\n({NUM})\nширина ([\d.]+)%", block):
        out.append({"rank": int(m.group(1)), "lo": num(m.group(2)), "hi": num(m.group(3)),
                    "dist_pct": float(m.group(4)), "strength": num(m.group(5)), "width_pct": float(m.group(6))})
    return out


def parse_levels(text: str) -> dict:
    """Текст страницы → словарь. Нет цены или ни одной зоны/«нет значимых зон» с каждой стороны — ValueError."""
    m = re.search(rf"Последняя цена ({NUM})", text)
    if not m:
        raise ValueError("нет последней цены")
    out = {"price": num(m.group(1))}
    a, b = text.find("Шорты ликвидируются"), text.find("Лонги ликвидируются")
    c = text.find("Баланс ближнего поля", b)
    if min(a, b, c) < 0:
        raise ValueError("нет блока магнитных зон")
    out["zones_short"] = _zones(text[a:b])
    out["zones_long"] = _zones(text[b:c])
    for side, blk in (("short", text[a:b]), ("long", text[b:c])):
        if not out[f"zones_{side}"] and "нет значимых зон" not in blk:
            raise ValueError(f"зоны {side} не разобраны")
    m = re.search(rf"Лонги (\d+)% · ({NUM})\nШорт (\d+)% · ({NUM})", text[c:])
    if m:
        out["near"] = {"long_pct": int(m.group(1)), "long_strength": num(m.group(2)),
                       "short_pct": int(m.group(3)), "short_strength": num(m.group(4))}
        d = re.search(r"доля шортов ([+-]?\d+) п\.п\. vs 24 ч назад", text[c:])
        out["near"]["short_pp_24h"] = int(d.group(1)) if d else None
    out["key_levels"] = [{"side": "short" if g[0] == "Шорт" else "long", "price": num(g[1]), "dist_pct": float(g[2]),
                          "leverage": g[3].strip(), "strength": float(g[4])}
                         for g in re.findall(rf"(Шорт|Лонг)\t({NUM})\t([+-][\d.]+)%\t([^\t]+)\t([\d.]+)", text)]
    out["clld"] = re.findall(r"([▲▼]) (Бычий|Медвежий) разворот (\d\d-\d\d \d\d:\d\d)", text)[:4]
    return out


LIQ_URL = "https://www.coinglass.com/ru/liquidations/BTC"
# страницы, которые GPT собирал раз в сутки у себя (DAILY_COLLECTION_PROTOCOL) — на маке раз в час, снимком экрана:
# цифры там на холсте (canvas), текстом их нет
SHOTS = {"liq_heatmap": "https://www.coinglass.com/ru/pro/futures/LiquidationHeatMap?coin=BTC&type=pair",
         "depth_delta": "https://www.coinglass.com/ru/pro/depth-delta",
         "book_heatmap": "https://www.coinglass.com/ru/LiquidityHeatmap"}
_MULT = {"": 1, "K": 1e3, "M": 1e6, "B": 1e9}


def usd(v: str, suf: str = "") -> float:
    return float(v.replace(",", "")) * _MULT[suf]


def parse_liquidations(text: str) -> dict:
    """Страница ликвидаций BTC (все биржи CoinGlass) → итоги 24 ч, окна 1/4/12/24 ч, крупнейшая, к средней 7 дн., биржи."""
    m = re.search(r"Биткоин Ликвидации\n\$([\d,]+)\nЛонг : \$([\d,]+)\nШорт : \$([\d,]+)", text)
    if not m:
        raise ValueError("нет итога ликвидаций")
    out = {"total_24h": usd(m.group(1)), "long_24h": usd(m.group(2)), "short_24h": usd(m.group(3))}
    m = re.search(r"Крупнейшая одиночная ликвидация\n\$([\d,]+)", text)
    out["largest"] = usd(m.group(1)) if m else None
    m = re.search(r"Ликвидации vs ср\. 7 дн\.\n([\d.]+)x", text)
    out["vs_7d"] = float(m.group(1)) if m else None
    out["windows"] = {w: {"total": usd(a, sa), "long": usd(b, sb), "short": usd(c, sc)} for w, a, sa, b, sb, c, sc in
                      re.findall(r"(1h|4h|12h|24h) Rekt\n\$([\d.]+)([KMB]?)\nЛонг\n\$([\d.]+)([KMB]?)\nШорт\n"
                                 r"\$([\d.]+)([KMB]?)", text)}
    out["exchanges"] = {n.strip(): {"long": usd(a, sa), "short": usd(b, sb), "total": usd(c, sc), "share_pct": float(p)}
                        for n, a, sa, b, sb, c, sc, p in
                        re.findall(r"\n([A-Za-z][\w .]*)\n\t\n\$([\d.]+)([KMB]?)\n\t\n\$([\d.]+)([KMB]?)\n\t\n"
                                   r"\$([\d.]+)([KMB]?)\n\t([\d.]+)%", text)}
    return out


def _page(br, url: str):
    pg = br.new_page(locale="ru-RU", viewport={"width": 1400, "height": 2400},
                     user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                                "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
    pg.goto(url, wait_until="domcontentloaded", timeout=90_000)
    return pg


OBSERVE_JS = """() => {
  const vis = e => !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length);
  const ctrl = [...document.querySelectorAll('button, [role=combobox], [role=tab], .MuiSelect-select, select')]
    .filter(vis).map(e => ({t: (e.innerText || e.value || '').trim().slice(0, 60),
      cls: String(e.className || '').slice(0, 120), sel: e.getAttribute('aria-selected'),
      pressed: e.getAttribute('aria-pressed')})).filter(x => x.t).slice(0, 80);
  const cbs = [...document.querySelectorAll('input[type=checkbox]')].map(c => ({checked: c.checked,
      label: ((c.id && document.querySelector('label[for="' + c.id + '"]')) || c.closest('label') || {innerText: ''})
        .innerText.trim().slice(0, 60)}));
  const txt = document.body.innerText;
  const m = txt.match(/Порог ликвидности = ([\\d.]+)/);
  const h = [...document.querySelectorAll('h1, h2, h3')].map(e => e.innerText.trim()).filter(Boolean).slice(0, 8);
  return {controls: ctrl, checkboxes: cbs, threshold: m ? m[1] : null, headings: h, url: location.href};
}"""


def observe(pg) -> dict:
    """Настройки, реально видимые на загруженной странице (не константы кода): тексты кнопок/списков с классами и
    aria-состоянием, флажки, порог, заголовки. Разбор активной вкладки — по этим сырым данным."""
    try:
        return pg.evaluate(OBSERVE_JS)
    except Exception as exc:                                    # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"[:200]}


def collect_text() -> tuple[dict, dict, dict, dict]:
    """Этап 1: уровни и ликвидации — текстом. → (тексты, сбои, время получения, наблюдаемые настройки)."""
    from playwright.sync_api import sync_playwright
    texts, fails, caps, seen = {}, {}, {}, {}
    with sync_playwright() as p:
        br = p.chromium.launch(headless=True)
        try:
            for key, url, cond in (("levels", URL, "/Последняя цена \\d/.test(document.body.innerText) && "
                                                   "/\\d – \\d/.test(document.body.innerText)"),
                                   ("liquidations", LIQ_URL, "/Биткоин Ликвидации\\n\\$\\d/.test(document.body.innerText)")):
                for attempt in range(3 if key == "levels" else 1):   # уровни нужны C1 до 07:10 — 3 попытки
                    pg = None
                    try:
                        pg = _page(br, url)
                        pg.wait_for_function(f"() => {cond}", timeout=90_000)   # цифры подставляет JS
                        texts[key] = pg.evaluate("() => document.body.innerText")
                        caps[key] = datetime.now(timezone.utc).isoformat(timespec="milliseconds")   # время получения
                        seen[key] = observe(pg)
                        fails.pop(key, None)
                        break
                    except Exception as exc:                    # noqa: BLE001
                        fails[key] = f"попытка {attempt + 1}: {type(exc).__name__}: {exc}"[:200]
                        try:
                            texts[f"{key}_fail{attempt + 1}"] = pg.evaluate("() => document.body.innerText")[:4000]
                        except Exception:                       # noqa: BLE001
                            pass
                    finally:
                        if pg is not None:
                            pg.close()
        finally:
            br.close()
    return texts, fails, caps, seen


def collect_shots(shots_dir: Path, now: datetime) -> tuple[dict, dict, dict]:
    """Этап 2: снимки страниц с холстом. Тепловая карта — с включённой «Картой ликвидаций» (как у Windows-сбора GPT).
    → (файлы с SHA256, сбои, наблюдаемые настройки)."""
    import hashlib
    from playwright.sync_api import sync_playwright
    files, fails, seen = {}, {}, {}
    shots_dir.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        br = p.chromium.launch(headless=True)
        try:
            for key, url in SHOTS.items():
                try:
                    pg = _page(br, url)
                    pg.wait_for_timeout(12_000)                 # холст рисуется после загрузки данных
                    if key == "liq_heatmap":                    # подпись — отдельный <label for=…>
                        box = pg.get_by_label("Карта Ликвидаций")
                        if box.count() and not box.first.is_checked():
                            box.first.check()
                            pg.wait_for_timeout(4_000)
                    if key == "book_heatmap":                   # эталон GPT: интервал 15 мин (по умолчанию 5)
                        sel = pg.locator("button.MuiSelect-button", has_text="минута").first
                        if sel.count() and sel.inner_text().strip() != "15 минута":
                            sel.click()
                            pg.get_by_role("option", name="15 минута", exact=True).click()
                            pg.wait_for_timeout(6_000)
                    seen[key] = observe(pg)
                    clip = {"liq_heatmap": {"x": 290, "y": 360, "width": 1100, "height": 840},
                            "book_heatmap": {"x": 0, "y": 80, "width": 1400, "height": 1000}}.get(
                                key, {"x": 240, "y": 80, "width": 1160, "height": 1100})
                    path = shots_dir / f"{now:%H%M}_{key}.jpg"
                    pg.screenshot(path=str(path), type="jpeg", quality=70, clip=clip)
                    files[key] = {"file": f"{shots_dir.name}/{path.name}",
                                  "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                                  "captured": datetime.now(timezone.utc).isoformat(timespec="milliseconds")}
                    pg.close()
                except Exception as exc:                        # noqa: BLE001
                    fails[key] = f"{type(exc).__name__}: {exc}"[:200]
        finally:
            br.close()
    return files, fails, seen


def prune(now: datetime, shots_days: int = 14, raw_days: int = 30) -> None:
    """Снимки экрана старше 14 дней и сырой текст старше 30 дней — удалить (разобранные цифры остаются навсегда)."""
    import shutil
    for d in (DIR / "shots").glob("2*"):
        try:
            if (now - datetime.strptime(d.name, "%Y%m%d").replace(tzinfo=timezone.utc)).days > shots_days:
                shutil.rmtree(d)
        except ValueError:
            pass
    for f in DIR.glob("raw_2*.txt"):
        try:
            if (now - datetime.strptime(f.stem[4:], "%Y%m%d").replace(tzinfo=timezone.utc)).days > raw_days:
                f.unlink()
        except ValueError:
            pass


def main() -> int:
    import hashlib
    DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    prune(now)
    texts, fails, caps, seen = collect_text()
    rec = {"ts": now.isoformat(timespec="seconds"), "run_id": now.isoformat(timespec="seconds"), "symbol": "BTCUSDT",
           "started": now.isoformat(timespec="milliseconds"), **{f"{k}_captured": v for k, v in caps.items()}}
    for key, parser in (("levels", parse_levels), ("liquidations", parse_liquidations)):
        if key in texts:
            try:
                rec[key] = parser(texts[key])
            except ValueError as exc:
                fails[key] = f"разбор: {exc}"
    # C1: прогноз назначенного утра фиксируется сразу после уровней, до снимков (протокол: не позже 07:10)
    try:
        from services.coinglass_web import c1
        fc = c1.make_forecast(rec["run_id"], now, rec.get("levels"),
                              datetime.fromisoformat(caps["levels"]) if "levels" in caps else None, seen.get("levels"))
        if fc:
            rec["c1"] = {"forecast_id": fc["forecast_id"], "status": fc["status"], "record_sha256": fc["record_sha256"]}
    except Exception as exc:                                    # noqa: BLE001
        fails["c1"] = f"{type(exc).__name__}: {exc}"[:200]
    files, f2, seen2 = collect_shots(DIR / "shots" / f"{now:%Y%m%d}", now)
    fails.update(f2)
    seen.update(seen2)
    raw_path = DIR / f"raw_{now:%Y%m%d}.txt"
    with open(raw_path, "a", encoding="utf-8") as f:
        for key, t in texts.items():
            f.write(f"===== {rec['ts']} {key}\n{t}\n")
    rec["text_sha256"] = {k: hashlib.sha256(v.encode("utf-8")).hexdigest() for k, v in texts.items()}
    rec["files"] = files
    rec["settings_observed"] = seen
    rec["status"] = {k: ("ok" if k not in fails else "fail") for k in ("levels", "liquidations", *SHOTS)}
    if fails:
        rec["fails"] = fails
    rec["finished"] = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    with open(DIR / "snapshots.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    try:                                                        # исходы созревших прогнозов C1 и пропущенные слоты
        from services.coinglass_web import c1
        c1.evaluate()
    except Exception as exc:                                    # noqa: BLE001
        print(f"c1.evaluate: {type(exc).__name__}: {exc}"[:200])
    lv, lq = rec.get("levels") or {}, rec.get("liquidations") or {}
    print(f"{rec['ts']} цена {lv.get('price')}; зоны {len(lv.get('zones_short', []))}/{len(lv.get('zones_long', []))}; "
          f"ликвидации 24ч {lq.get('total_24h')}; c1 {rec.get('c1')}; сбои {fails or 'нет'}")
    return 0 if "levels" in rec else 1


if __name__ == "__main__":
    sys.exit(main())
