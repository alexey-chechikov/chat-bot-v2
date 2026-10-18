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


def collect(shots_dir: Path | None, now: datetime) -> tuple[dict, dict]:
    """Один браузер на запуск: уровни и ликвидации — текстом, остальное — снимками. → (сырые тексты, сбои)."""
    from playwright.sync_api import sync_playwright
    texts, fails, caps = {}, {}, {}
    with sync_playwright() as p:
        br = p.chromium.launch(headless=True)
        try:
            for key, url, cond in (("levels", URL, "/Последняя цена \\d/.test(document.body.innerText) && "
                                                   "/\\d – \\d/.test(document.body.innerText)"),
                                   ("liquidations", LIQ_URL, "/Биткоин Ликвидации\\n\\$\\d/.test(document.body.innerText)")):
                try:
                    pg = _page(br, url)
                    pg.wait_for_function(f"() => {cond}", timeout=90_000)   # цифры подставляет JS
                    texts[key] = pg.evaluate("() => document.body.innerText")
                    caps[key] = datetime.now(timezone.utc).isoformat(timespec="seconds")   # время получения (v1)
                    pg.close()
                except Exception as exc:                        # noqa: BLE001
                    fails[key] = f"{type(exc).__name__}: {exc}"[:200]
            if shots_dir is not None:
                shots_dir.mkdir(parents=True, exist_ok=True)
                for key, url in SHOTS.items():
                    try:
                        pg = _page(br, url)
                        pg.wait_for_timeout(12_000)             # холст рисуется после загрузки данных
                        clip = ({"x": 290, "y": 360, "width": 1100, "height": 840} if key == "liq_heatmap"
                                else {"x": 240, "y": 80, "width": 1160, "height": 1100})
                        pg.screenshot(path=str(shots_dir / f"{now:%H%M}_{key}.jpg"), type="jpeg", quality=70,
                                      clip=clip)
                        pg.close()
                    except Exception as exc:                    # noqa: BLE001
                        fails[key] = f"{type(exc).__name__}: {exc}"[:200]
        finally:
            br.close()
    return texts, fails, caps


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
    DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    prune(now)
    texts, fails, caps = collect(DIR / "shots" / f"{now:%Y%m%d}", now)
    rec = {"ts": now.isoformat(timespec="seconds"), "symbol": "BTCUSDT",
           **{f"{k}_captured": v for k, v in caps.items()}}
    for key, parser in (("levels", parse_levels), ("liquidations", parse_liquidations)):
        if key in texts:
            try:
                rec[key] = parser(texts[key])
            except ValueError as exc:
                fails[key] = f"разбор: {exc}"
    if fails:
        rec["fails"] = fails
    with open(DIR / f"raw_{now:%Y%m%d}.txt", "a", encoding="utf-8") as f:
        for key, t in texts.items():
            f.write(f"===== {rec['ts']} {key}\n{t}\n")
    with open(DIR / "snapshots.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    lv, lq = rec.get("levels") or {}, rec.get("liquidations") or {}
    print(f"{rec['ts']} цена {lv.get('price')}; зоны {len(lv.get('zones_short', []))}/{len(lv.get('zones_long', []))}; "
          f"ликвидации 24ч {lq.get('total_24h')}; сбои {fails or 'нет'}")
    return 0 if "levels" in rec else 1


if __name__ == "__main__":
    sys.exit(main())
