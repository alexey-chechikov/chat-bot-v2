"""Archive explicitly supplied public daily context. Offline, standard library only."""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import os
from pathlib import Path
import re
import shutil
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit, quote
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

SCHEMA = "daily-as-seen-v1"
STATUSES = {"OK", "PARTIAL", "MISSING", "FAILED"}
EVIDENCE_KINDS = {"dom_text", "site_export", "screenshot"}
DAY_MS = 86400000


def warsaw():
    try:
        return ZoneInfo("Europe/Warsaw")
    except ZoneInfoNotFoundError as exc:
        raise ValueError("Europe/Warsaw timezone data unavailable; no guessed offset") from exc


def timestamp(value, name):
    if type(value) is not int or value < 0:
        raise ValueError(f"{name} must be a nonnegative UTC epoch millisecond integer")
    try:
        datetime.fromtimestamp(value / 1000, timezone.utc)
    except (ValueError, OverflowError, OSError) as exc:
        raise ValueError(f"{name} outside supported datetime range") from exc
    return value


def utc(value):
    return datetime.fromtimestamp(value / 1000, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def day_key(value):
    return datetime.fromtimestamp(value / 1000, timezone.utc).astimezone(warsaw()).date().isoformat()


def finite_json(value):
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("non-finite JSON number")
    if isinstance(value, dict):
        for child in value.values():
            finite_json(child)
    elif isinstance(value, list):
        for child in value:
            finite_json(child)


def flags(value):
    if not isinstance(value, list) or any(not isinstance(x, str) or not x for x in value):
        raise ValueError("quality_flags must be a list of nonempty strings")
    return list(dict.fromkeys(value))


def md(value):
    return html.escape(str(value), quote=False).replace("\\", "\\\\").replace("|", "\\|").replace("`", "\\`").replace("\r", " ").replace("\n", " ")


def evidence_record(evidence, source_id, index, input_dir):
    if not isinstance(evidence, dict) or evidence.get("kind") not in EVIDENCE_KINDS:
        raise ValueError("invalid evidence kind")
    given = evidence.get("path")
    if not isinstance(given, str) or not given:
        raise ValueError("evidence path required")
    # A public input cannot authorize reads from arbitrary account/config paths.
    rel = Path(given.replace("\\", "/"))
    if rel.is_absolute() or ".." in rel.parts or not rel.parts or rel.parts[0] != "evidence" or ":" in given:
        raise ValueError("evidence paths must be relative evidence/... without parent traversal")
    input_root = input_dir.resolve()
    evidence_root = (input_dir / "evidence").resolve()
    if evidence_root == input_root or not evidence_root.is_relative_to(input_root):
        raise ValueError("evidence root escapes input directory")
    resolved = (input_dir / rel).resolve()
    if not resolved.is_relative_to(evidence_root):
        raise ValueError("evidence path escapes evidence directory")
    supplied = evidence.get("sha256")
    if supplied is not None and (not isinstance(supplied, str) or not re.fullmatch(r"[a-fA-F0-9]{64}", supplied)):
        raise ValueError("evidence sha256 must be 64 hex characters or null")
    archived = f"evidence/{source_id}/{index:03d}_{rel.name}"
    result = {"kind": evidence["kind"], "path": archived, "original_relative_path": given,
              "supplied_sha256": supplied, "sha256": None, "integrity": "missing"}
    if not resolved.is_file():
        result["path"] = None
        return result, None, "evidence_missing"
    if resolved.stat().st_size > 32 * 1024 * 1024:
        raise ValueError("evidence file exceeds 32 MiB limit")
    body = resolved.read_bytes()
    actual = hashlib.sha256(body).hexdigest()
    result["sha256"] = actual
    result["integrity"] = "computed" if supplied is None else ("matched" if supplied.lower() == actual else "mismatch")
    return result, (archived, body), "evidence_hash_mismatch" if result["integrity"] == "mismatch" else None


def build_report(data, archived_ms, input_dir):
    """Validate and derive context metadata. Never infer a trade/action label."""
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        raise ValueError("schema must be daily-as-seen-v1")
    if any(key in data for key in ("run_id", "archived_at_ms", "archive_date", "output_path")):
        raise ValueError("archive identity/time/path are generated locally and cannot be supplied")
    finite_json(data)
    if data.get("timezone") != "Europe/Warsaw" or type(data.get("synthetic")) is not bool:
        raise ValueError("timezone Europe/Warsaw and explicit synthetic boolean required")
    for key in ("order_permission", "trade_primary", "auto_allowed_primary"):
        if key in data and data[key] is not False:
            raise ValueError(f"{key} must be false; this archive cannot authorize trades")
    for key in ("primary_labels", "trade_primary_labels"):
        if data.get(key):
            raise ValueError("trade-primary labels are outside daily-context schema")
    collected = timestamp(data.get("collected_at_ms"), "collected_at_ms")
    finished = timestamp(data.get("finished_at_ms"), "finished_at_ms")
    timestamp(archived_ms, "archived_at_ms")
    if finished < collected or finished > archived_ms + 2000:
        raise ValueError("finished must follow collected and cannot be in the future")
    day = day_key(collected)
    if "daily_date" in data and data["daily_date"] != day:
        raise ValueError("daily_date cannot override collected-at Europe/Warsaw day")
    if not data["synthetic"] and day != day_key(archived_ms):
        raise ValueError("real daily archive refuses backfill/backdating: collection day must be today's Warsaw day")
    source_list = data.get("sources")
    if not isinstance(source_list, list) or not source_list:
        raise ValueError("sources must be a nonempty explicit list, including failed/missing sources")
    top_flags = flags(data.get("quality_flags", []))
    seen_ids = set()
    processed = []
    copies = []
    for source in source_list:
        if not isinstance(source, dict):
            raise ValueError("source must be an object")
        sid = source.get("id")
        if not isinstance(sid, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", sid) or sid in seen_ids:
            raise ValueError("source id must be unique safe text")
        seen_ids.add(sid)
        status = source.get("status")
        if status not in STATUSES:
            raise ValueError("source status must be OK/PARTIAL/MISSING/FAILED")
        url = source.get("url")
        sf = flags(source.get("quality_flags", []))
        if url is None:
            sf.append("source_url_unknown")
        elif not isinstance(url, str) or urlsplit(url).scheme not in ("http", "https") or not urlsplit(url).netloc or urlsplit(url).username or urlsplit(url).password:
            raise ValueError("source url must be public http(s) without credentials, or null")
        asof = source.get("event_asof_ms")
        age = None
        if asof is None:
            sf.append("asof_unknown")
        else:
            timestamp(asof, "event_asof_ms")
            age = finished - asof
            threshold = source.get("stale_after_ms", DAY_MS)
            if type(threshold) is not int or threshold < 0:
                raise ValueError("stale_after_ms must be nonnegative integer")
            if age < 0:
                sf.append("future_asof")
            elif age > threshold:
                sf.append("stale_asof")
        lag_status = source.get("lag_status", "unknown")
        lag = source.get("provider_lag_ms")
        if lag_status not in ("unknown", "known"):
            raise ValueError("lag_status must be unknown or known")
        if lag_status == "known":
            if type(lag) is not int or lag < 0:
                raise ValueError("known provider lag requires nonnegative provider_lag_ms")
        elif lag is not None:
            raise ValueError("unknown provider lag must remain null; as-of age is not provider lag")
        else:
            sf.append("provider_lag_unknown")
        settings = source.get("settings", {})
        if not isinstance(settings, dict):
            raise ValueError("settings must be an object")
        values = source.get("values")
        if values is not None and not isinstance(values, list):
            raise ValueError("values must be typed list or null")
        names = set()
        present_values = False
        for value in values or []:
            if not isinstance(value, dict) or not isinstance(value.get("name"), str) or not value["name"] or value["name"] in names:
                raise ValueError("typed value names must be present and unique")
            names.add(value["name"])
            typ, item = value.get("type"), value.get("value")
            if typ not in ("number", "string", "boolean", "json") or "value" not in value or "unit" not in value:
                raise ValueError("each value requires name, type, value and explicit unit (or null)")
            unit = value["unit"]
            if unit is not None and (not isinstance(unit, str) or not unit):
                raise ValueError("unit must be nonempty string or null")
            if item is None:
                sf.append("missing_value")
                continue
            present_values = True
            if (typ == "number" and type(item) not in (int, float)) or (typ == "string" and not isinstance(item, str)) or (typ == "boolean" and type(item) is not bool):
                raise ValueError("value does not match declared type")
            if typ == "number" and unit is None:
                sf.append("unit_unknown")
        if status in ("FAILED", "MISSING") and present_values:
            raise ValueError("failed/missing source cannot contain observed values; use null, never zero")
        if not present_values:
            sf.append("source_values_missing")
        scope = source.get("market_scope", "unknown")
        aggregation = source.get("aggregation", "unknown")
        if not isinstance(scope, str) or not isinstance(aggregation, str):
            raise ValueError("market_scope and aggregation must be strings")
        if scope == "unknown":
            sf.append("market_scope_unknown")
        if aggregation == "group_aggregate":
            sf.append("group_aggregate_not_bbo")
        forming = source.get("forming_bar")
        if forming is not None and type(forming) is not bool:
            raise ValueError("forming_bar must be boolean or null")
        if forming:
            sf.append("forming_bar")
        evidence = source.get("evidence", [])
        if not isinstance(evidence, list):
            raise ValueError("evidence must be a list")
        evidence_records = []
        for index, item in enumerate(evidence):
            record, copy, warning = evidence_record(item, sid, index, input_dir)
            evidence_records.append(record)
            if copy is not None:
                copies.append(copy)
            if warning:
                sf.append(warning)
        processed.append({"id": sid, "status": status, "url": url, "event_asof_ms": asof,
                          "event_asof_utc": utc(asof) if asof is not None else None,
                          "event_age_at_finish_ms": age, "lag_status": lag_status, "provider_lag_ms": lag,
                          "stale_after_ms": source.get("stale_after_ms", DAY_MS), "settings": settings,
                          "values": values, "market_scope": scope, "aggregation": aggregation,
                          "forming_bar": forming, "evidence": evidence_records,
                          "has_observed_values": present_values, "quality_flags": list(dict.fromkeys(sf))})
    known_asofs = {s["event_asof_ms"] for s in processed if s["event_asof_ms"] is not None}
    if len(known_asofs) > 1:
        top_flags.append("mixed_asof")
    if known_asofs and any(s["event_asof_ms"] is None for s in processed):
        top_flags.append("mixed_known_unknown_asof")
    scopes = {s["market_scope"] for s in processed}
    if "futures" in scopes and "spot" in scopes:
        top_flags.append("mixed_market_scopes_kept_separate")
    if not any(s["has_observed_values"] for s in processed):
        overall = "FAILED"
    elif top_flags or any(s["status"] != "OK" or s["quality_flags"] for s in processed):
        overall = "PARTIAL"
    else:
        overall = "OK"
    report = {"schema": SCHEMA, "role": "daily_context_only", "synthetic": data["synthetic"],
              "daily_date": day, "timezone": "Europe/Warsaw", "status": overall,
              "collected_at_ms": collected, "finished_at_ms": finished, "archived_at_ms": archived_ms,
              "collected_at_utc": utc(collected), "finished_at_utc": utc(finished), "archived_at_utc": utc(archived_ms),
              "collected_at_warsaw": datetime.fromtimestamp(collected / 1000, timezone.utc).astimezone(warsaw()).isoformat(timespec="milliseconds"),
              "sources": processed, "source_groups": {scope: [s["id"] for s in processed if s["market_scope"] == scope] for scope in sorted(scopes)},
              "quality_flags": list(dict.fromkeys(top_flags)), "order_permission": False,
              "trade_primary_labels_created": False, "predictions_created": False}
    return report, copies


def summary(report):
    lines = [f"# Ежедневный контекст — {report['daily_date']} (Europe/Warsaw)", "",
             f"Статус: **{report['status']}**. {'СИНТЕТИЧЕСКИЙ ПРИМЕР.' if report['synthetic'] else 'Публичные данные как видны при сборе.'}", "",
             f"Начало UTC: {report['collected_at_utc']}; завершение UTC: {report['finished_at_utc']}.",
             f"Время начала в Варшаве: {report['collected_at_warsaw']}.",
             "Назначение: ежедневный контекст. Прогнозы и trade-primary labels не создаются. Разрешение на ордера: **false**.", ""]
    for scope, ids in report["source_groups"].items():
        lines += [f"## {md(scope)}", ""]
        for source in report["sources"]:
            if source["id"] not in ids:
                continue
            link = f"[источник]({quote(source['url'], safe=':/?=&%#')})" if source["url"] else "URL неизвестен"
            lines += [f"### {md(source['id'])} — {source['status']}", "", link,
                      f"As-of: {source['event_asof_utc'] or 'неизвестен'}. Задержка провайдера: {source['provider_lag_ms'] if source['lag_status']=='known' else 'неизвестна'}{' ms' if source['lag_status']=='known' else ''}.",
                      f"Вид агрегации: {md(source['aggregation'])}{' — агрегат групп, не BBO' if source['aggregation']=='group_aggregate' else ''}.",
                      "Настройки: " + md(json.dumps(source["settings"], ensure_ascii=False, sort_keys=True)), ""]
            if not source["values"]:
                lines += ["Нет значений; отсутствие данных не означает ноль.", ""]
            else:
                lines += ["| Показатель | Значение | Единица |", "|---|---|---|"]
                for value in source["values"]:
                    rendered = "нет данных" if value["value"] is None else json.dumps(value["value"], ensure_ascii=False)
                    lines.append(f"| {md(value['name'])} | {md(rendered)} | {md(value['unit']) if value['unit'] is not None else 'неизвестна/не применяется'} |")
                lines.append("")
            lines += ["Качество: " + (", ".join(md(x) for x in source["quality_flags"]) or "явных флагов нет"), ""]
    lines += ["Общие флаги: " + (", ".join(md(x) for x in report["quality_flags"]) or "нет"), "",
              "Futures и spot не объединяются в один стакан. Возраст as-of не подменяет задержку провайдера."]
    return "\n".join(lines) + "\n"


def write_new(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(body)
        handle.flush()
        os.fsync(handle.fileno())


def archive_file(input_path, outroot, *, _clock=None):
    input_path, outroot = Path(input_path).resolve(), Path(outroot).resolve()
    raw = input_path.read_bytes()
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("input must be a JSON object")
    if _clock is not None and data.get("synthetic") is not True:
        raise ValueError("injected clock is available only for synthetic fixtures")
    actual_ms = (_clock() if _clock is not None else time.time_ns() // 1000000)
    report, copies = build_report(data, actual_ms, input_path.parent)
    report["input_sha256"] = hashlib.sha256(raw).hexdigest()
    report["utility_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    report["test_clock_injected"] = _clock is not None
    day_dir = outroot / ("synthetic" if report["synthetic"] else "") / report["daily_date"]
    day_dir.mkdir(parents=True, exist_ok=True)
    target = day_dir / f"run_{actual_ms}"
    lock = day_dir / f".run_{actual_ms}.reserve"
    # Exclusive reservation coordinates concurrent instances. Windows rename also
    # refuses any existing destination; no replace/overwrite operation is used.
    lock_fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    stage = None
    try:
        if target.exists():
            raise FileExistsError(f"archive already exists: {target}")
        stage = day_dir / f".run_{actual_ms}.staging_{uuid4().hex}"
        stage.mkdir(exist_ok=False)
        write_new(stage / "input.json", raw)
        for relative, content in copies:
            write_new(stage / relative, content)
        write_new(stage / "report.json", json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8"))
        write_new(stage / "summary.md", summary(report).encode("utf-8"))
        if target.exists():
            raise FileExistsError(f"archive already exists: {target}")
        os.rename(stage, target)
        stage = None
    finally:
        os.close(lock_fd)
        lock.unlink()
        if stage is not None and stage.exists():
            # Delete only this newly allocated staging directory, after verifying
            # its resolved absolute parent and unique staging name.
            resolved = stage.resolve()
            if resolved.parent != day_dir.resolve() or ".staging_" not in resolved.name:
                raise RuntimeError("refusing cleanup outside newly created staging directory")
            shutil.rmtree(resolved)
    return target, report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--outroot", required=True, type=Path)
    args = parser.parse_args()
    try:
        target, report = archive_file(args.input, args.outroot)
    except (ValueError, OSError, TypeError, KeyError) as exc:
        parser.exit(2, f"archive refused: {exc}\n")
    print(json.dumps({"archive": str(target), "status": report["status"], "synthetic": report["synthetic"], "order_permission": False}, ensure_ascii=False))


if __name__ == "__main__":
    main()
