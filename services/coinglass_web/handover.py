"""Экспорт для сверки настроек у GPT (docs/COINGLASS_V1_GPT_REPLY_2026-10-18.md, «Просьба к разработчику Mac»).

Только производные метаданные одного прогона сборщика: run_id и времена, статус источников, ожидаемые настройки
(эталон Windows) отдельно от реально прочитанных со страницы (settings_observed → поля), SHA локальных файлов,
признаки загрузки графика/чисел, готовность C1, доказательство доставки утренней сводки. Без сырого DOM/JPEG, цен,
рыночных рядов, Telegram-идентификаторов, ключей и сведений счёта.

    .venv/bin/python3 -m services.coinglass_web.handover [--run-id ISO]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from services.coinglass_web import c1
from services.coinglass_web.collector import DIR, ROOT, image_check

OUT = ROOT / "docs" / "COINGLASS_MAC_HANDOVER_METADATA_2026-10-18.json"
REF = ROOT / "research" / "coinglass_v1_reply_review_20261018" / "WINDOWS_SETTINGS_REFERENCE.json"
SOURCE_IDS = {"liq_heatmap": "coinglass_liquidation_model1_btc", "liquidations": "coinglass_btc_actual_liquidations",
              "book_heatmap": "coinglass_orderbook_heatmap_btc", "depth_delta": "coinglass_spot_book_delta_btc",
              "levels": "coinglass_liquidation_levels"}
NO_CMP = {"captured_at_ms", "read_started_at_ms", "read_finished_at_ms", "displayed_timezone"}
SKIP = {"Preferences", "Decline", "Accept", "Русский", "Войти"}             # баннер cookies, язык, вход


def _clean(t: str) -> str:
    """Свидетельство без рыночных чисел (цена в кнопке символа и т.п.)."""
    return re.sub(r"\d{1,3}(?:[\s  ]\d{3})+(?:[.,]\d+)?|\d{4,}(?:[.,]\d+)?", "<num>",
                  t.replace("\n", " ")).strip()


def _ctl(seen: dict) -> list[dict]:
    return [c for c in seen.get("controls", []) if c.get("t") not in SKIP]


def _sel(c: dict) -> bool:
    return c.get("sel") == "true" or c.get("pressed") == "true"


def _instrument(text: str) -> tuple[str | None, str | None]:
    m = re.match(r"(\w+)\s+(BTC)/?(USDT)\s+Бессрочный", text)
    return (m.group(1), f"{m.group(2)}{m.group(3)}_perpetual") if m else (None, None)


def derive(key: str, seen: dict, rec: dict) -> tuple[dict, list[str]]:
    """Поля настроек из реально прочитанного состояния страницы + строки-свидетельства."""
    ctl, out, ev = _ctl(seen), {}, []
    if key == "liq_heatmap":
        for c in ctl:
            if re.fullmatch(r"Модель (\d)", c["t"]) and _sel(c):
                out["model"] = int(c["t"][-1])
                ev.append(f"вкладка «{c['t']}» aria-selected=true")
            if c["t"] in ("Пара", "Символ") and _sel(c):
                out["mode"] = {"Пара": "pair", "Символ": "symbol"}[c["t"]]
                ev.append(f"вкладка «{c['t']}» aria-selected=true")
            if "Бессрочный" in c["t"]:
                out["exchange"], out["symbol"] = _instrument(c["t"])
                ev.append(f"поле инструмента «{c['t']}»")
            if re.fullmatch(r"\d+ час", c["t"]):
                out["window"] = c["t"].split()[0] + "h"
                ev.append(f"список окна «{c['t']}»")
        if seen.get("threshold") is not None:
            out["threshold"] = float(seen["threshold"])
            ev.append(f"текст «Порог ликвидности = {seen['threshold']}»")
        for cb in seen.get("checkboxes", []):
            if cb.get("label") == "Карта Ликвидаций":
                out["liquidation_map"] = bool(cb["checked"])
                ev.append(f"флажок «Карта Ликвидаций» checked={cb['checked']}")
    elif key == "liquidations":
        if seen.get("url", "").rstrip("/").endswith("/liquidations/BTC"):
            out["symbol"] = "BTC"
            ev.append("URL /liquidations/BTC, заголовок «" + (seen.get("headings") or [""])[0] + "»")
        ex = [c for c in ctl if c["t"] == "Биржи"]
        lq = rec.get("liquidations") or {}
        if ex:
            out["exchanges"] = "all_covered_by_provider"
            ev.append(f"фильтр «Биржи» без выбора; в таблице бирж {len(lq.get('exchanges') or {})} строк")
        if lq.get("windows"):
            out["windows_hours"] = sorted(int(k.rstrip("h")) for k in lq["windows"])
            ev.append("окна из разобранного текста страницы: " + ", ".join(sorted(lq["windows"], key=lambda k: int(k[:-1]))))
    elif key == "book_heatmap":
        for c in ctl:
            if "Бессрочный" in c["t"]:
                m = re.match(r"(\w+)\s+(BTCUSDT)\s+Бессрочный", c["t"])
                if m:
                    out["exchange"], out["symbol"] = m.group(1), "BTCUSDT_perpetual"
                ev.append(f"поле инструмента «{c['t']}»")
            if re.fullmatch(r"\d+ минута|\d+ час", c["t"]):
                n, u = c["t"].split()
                out["bar_interval"] = n + ("m" if u == "минута" else "h")
                ev.append(f"список интервала «{c['t']}»")
            m = re.fullmatch(r"Уровень слияния : (\d+)", c["t"])
            if m:
                out["merge"] = int(m.group(1))
                ev.append(f"список «{c['t']}»")
    elif key == "depth_delta":
        grp = []                                                    # первая панель: «агрегированная дельта»
        for c in ctl:
            if grp and c["t"] == "5":
                break
            grp.append(c["t"])
        grp = [t for t in grp if t != "5"]
        mp = {"Доллары": ("currency", "USD"), "Spot": ("market", "Spot"), "BTC": ("symbol", "BTC"),
              "Дельта": ("mode", "Delta")}
        for t in grp:
            if t in mp:
                out[mp[t][0]] = mp[t][1]
            elif re.fullmatch(r"\d+ минута", t):
                out["bar_interval"] = t.split()[0] + "m"
            elif re.fullmatch(r"\d+%", t):
                out["range_percent"] = int(t[:-1])
        ev.append("первая панель «" + (seen.get("headings") or [""])[0] + "»: " + " | ".join(grp))
    elif key == "levels":
        h = [x for x in seen.get("headings", []) if "Binance" in x]
        if h:
            m = re.search(r"(\w+) (BTCUSDT)", h[0])
            out["exchange"], out["symbol"] = (m.group(1), m.group(2)) if m else (None, None)
            ev.append(f"заголовок «{h[0]}»")
        pressed = [c["t"] for c in ctl if c.get("pressed") == "true"]
        out["controls_pressed"] = pressed
        ev.append("нажатые переключатели: " + " | ".join(pressed))
    return out, [_clean(e) for e in ev]


def compare(expected: dict, observed: dict) -> dict:
    res = {}
    for k, v in expected.items():
        if k in NO_CMP:
            continue
        if k not in observed or observed[k] is None:
            res[k] = "unknown"
        else:
            res[k] = "match" if observed[k] == v else "mismatch"
    return res


def _sha_file(p: Path) -> str | None:
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None


def _delivery_evidence(d: dict) -> dict:
    """Связь доставки с пакетом и основание успеха: SHA записи снимка, строка лога «regime_card.sent», число ошибок
    отправки за день. Ошибки отправки логируются всегда (regime_watch.send_failed); до 19.10 ~11:40 они не прерывали
    отправку, поэтому для ранних записей успех = нет ни одной такой строки за день."""
    out = {"expected_local": f"{d['date']}T08:00 Europe/Warsaw",
           "delay_reason": "карточка опрашивается раз в 15 мин (app_runner, окно 08:00–11:00) и собирается ~1–2 мин"}
    run = d.get("snapshot_run_id")
    for line in (DIR / "snapshots.jsonl").read_text(encoding="utf-8").splitlines():
        if run and f'"run_id": "{run}"' in line:
            out["snapshot_record_sha256"] = hashlib.sha256(line.encode("utf-8")).hexdigest()
            r = json.loads(line)
            out["snapshot_files_sha256"] = {k: v["sha256"] for k, v in (r.get("files") or {}).items()}
            out["snapshot_text_sha256"] = r.get("text_sha256")
            break
    sent_line, failed = None, 0
    for lp in sorted((ROOT / "logs").glob("app.log*")):
        for line in lp.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.startswith(d["date"]):
                continue
            if f"regime_card.sent date={d['date']}" in line and sent_line is None:
                sent_line = line
            if "regime_watch.send_failed" in line:
                failed += 1
    out["log_regime_card_sent"] = ({"time_local": sent_line[:23],
                                    "line_sha256": hashlib.sha256(sent_line.encode("utf-8")).hexdigest()}
                                   if sent_line else None)
    out["send_failed_lines_that_day"] = failed
    out["success_basis"] = (f"send_fn вернул успешных отправок {d['sent_ok']} из {d['recipients']}"
                            if d.get("sent_ok") is not None else
                            "в логе есть «regime_card.sent», строк «regime_watch.send_failed» за день — "
                            f"{failed} (каждая неудача bot.send_message логируется)")
    return out


def build(run_id: str | None = None) -> dict:
    rows = [json.loads(x) for x in (DIR / "snapshots.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    full = [r for r in rows if r.get("settings_observed") and all(v == "ok" for v in (r.get("status") or {"x": 0}).values())]
    rec = next(r for r in full if r["run_id"] == run_id) if run_id else full[-1]
    ref = {s["id"]: s for s in json.loads(REF.read_text(encoding="utf-8"))["sources"]}
    seen_all = rec["settings_observed"]
    vp = DIR / "visual_checks.jsonl"
    visual = [json.loads(x) for x in vp.read_text(encoding="utf-8").splitlines() if x.strip()] if vp.exists() else []
    sources = []
    for key, sid in SOURCE_IDS.items():
        seen = seen_all.get(key) or {}
        observed, evidence = derive(key, seen, rec)
        exp = (ref.get(sid) or {}).get("settings")
        f = (rec.get("files") or {}).get(key)
        src = {"id": sid, "mac_key": key, "status": rec["status"].get(key), "url": seen.get("url"),
               "captured_utc": rec.get(f"{key}_captured") or (f or {}).get("captured"),
               "read_started_utc": None, "read_started_reason": "отдельно по источнику не пишется; есть started прогона",
               "settings_expected": {k: v for k, v in exp.items() if k not in NO_CMP} if exp else None,
               "settings_observed": observed, "observed_evidence": evidence,
               "mac_self_check": compare(exp, observed) if exp else None,
               "provider_freshness": None,
               "provider_freshness_reason": "страница не показывает время обновления данных провайдера — неизвестно"}
        if key in ("levels", "liquidations"):
            parsed = rec.get(key) or {}
            src["local_files"] = [{"name": f"raw_{rec['run_id'][:10].replace('-', '')}.txt (фрагмент {key})",
                                   "type": "text/plain", "sha256_of_fragment": (rec.get("text_sha256") or {}).get(key),
                                   "published": False}]
            if key == "levels":
                src["numbers_loaded"] = bool(parsed.get("price")) and bool(parsed.get("zones_short") or parsed.get("zones_long"))
                src["parsed_fields"] = {"zones_short": len(parsed.get("zones_short") or []),
                                        "zones_long": len(parsed.get("zones_long") or []), "near_field": bool(parsed.get("near"))}
                src["note"] = "отдельный источник (liquidation-levels); не та же heatmap Model 1; на нём строится C1"
            else:
                src["numbers_loaded"] = bool(parsed.get("total_24h"))
                src["parsed_fields"] = {"windows": sorted(parsed.get("windows") or {}),
                                        "exchanges_rows": len(parsed.get("exchanges") or {})}
        else:
            src["local_files"] = [{"name": f["file"].split("/")[-1], "type": "image/jpeg", "sha256": f["sha256"],
                                   "published": False}] if f else None
            ck = (f or {}).get("chart_check")
            if ck:
                src["chart_check"] = {**ck, "basis": "сборщик: загрузчик «Загрузка…/Loading» не виден в момент снимка "
                                                     "+ доля пикселей не цвета фона на JPEG выше порога"}
            elif f:                                             # прогон до 19.10 ~11:35 — проверка по файлу
                p = DIR / "shots" / f["file"]
                sha_ok = _sha_file(p) == f["sha256"]
                img = image_check(p, key) if sha_ok else None
                src["chart_check"] = {"loader_visible_at_capture": None,
                                      "loader_reason": "в этом прогоне сборщик загрузчик ещё не проверял",
                                      "file_sha256_reverified": sha_ok, "image": img,
                                      "checked_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                      "ok": bool(img and img["nonblank"])}
            vis = [v for v in visual if v["run_id"] == rec["run_id"] and v["source"] == key]
            src["visual_check"] = vis[-1] if vis else None
            src["chart_loaded"] = bool(src.get("chart_check", {}).get("ok")) and \
                (src["visual_check"] is None or src["visual_check"]["chart_rendered"])
        sources.append(src)
    c1dir = DIR / "c1"
    man = json.loads((c1dir / "base_manifest.json").read_text(encoding="utf-8"))
    dl = DIR / "delivery_log.jsonl"
    dlines = [x for x in dl.read_text(encoding="utf-8").splitlines() if x.strip()] if dl.exists() else []
    delivered = [json.loads(x) | {"line_sha256": hashlib.sha256(x.encode("utf-8")).hexdigest()} for x in dlines]
    delivery = [d | _delivery_evidence(d) for d in delivered if d.get("coinglass_block_in_card")]
    code = {p: _sha_file(ROOT / p) for p in ("services/coinglass_web/collector.py", "services/coinglass_web/c1.py",
                                             "services/coinglass_web/section.py", "services/coinglass_web/handover.py",
                                             "services/regime_watch.py", "app_runner.py")}
    return {
        "role": "Mac handover metadata — derived only; no raw DOM/JPEG, prices, market series, Telegram IDs, keys, account",
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "reference_file": str(REF.relative_to(ROOT)), "reference_sha256": _sha_file(REF),
        "run": {"run_id": rec["run_id"], "started_utc": rec.get("started"), "finished_utc": rec.get("finished"),
                "trigger": ("по расписанию launchd com.bot7.coinglass-web (07–23 Варшавы, минута 0)"
                            if datetime.fromisoformat(rec["run_id"]).minute == 0
                            and datetime.fromisoformat(rec["run_id"]).second < 30
                            else "ручной прогон того же модуля, что запускает launchd com.bot7.coinglass-web"),
                "browser": "Playwright Chromium headless, locale ru-RU, viewport 1400x2400"},
        "sources": sources,
        "c1_registry": [{k: r.get(k) for k in ("slot", "run_id", "status", "impl")} for r in c1._read("registry.jsonl")],
        "c1_readiness": {"protocol": c1.PROTOCOL, "impl": c1.IMPL,
                         "first_slot_local": "2026-10-19T07:00+02:00",
                         "base": {k: man[k] for k in ("symbol", "market", "first_ts_utc", "last_ts_utc", "rows",
                                                       "missing_minutes", "npz_sha256", "dates_sha256",
                                                       "frozen_source_sha256", "rest_minutes_added", "tz")}
                         | {"dates_first": man["dates"][0], "dates_last": man["dates"][-1], "dates_n": len(man["dates"])},
                         "base_complete_windows_check": "q_vector: complete 730/730 на фазах 07:01, 07:06, 07:11"},
        "delivery": {"log": "state/coinglass/delivery_log.jsonl (локально)", "log_sha256": _sha_file(dl),
                     "records": delivery or None,
                     "reason_if_null": None if delivery else
                     "журнал доставки введён 18.10.2026 ~23:50 Варшавы; первая утренняя карточка с ним — 19.10.2026 "
                     "08:00–11:00 Варшавы; сегодняшняя карточка (18.10, утро) ушла до появления блока CoinGlass"},
        "code_sha256": code,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id")
    a = ap.parse_args()
    doc = build(a.run_id)
    OUT.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    for s in doc["sources"]:
        print(s["id"], s["status"], s["mac_self_check"], "chart_loaded" if "chart_loaded" in s else "",
              s.get("chart_loaded", ""))
    print("delivery:", "есть" if doc["delivery"]["records"] else "нет —", doc["delivery"]["reason_if_null"] or "")
    print("->", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
