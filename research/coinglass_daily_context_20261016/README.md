# Offline daily context archive

The user subsequently requested a visible daily analytical review. See [ANALYTICS_PROTOCOL.md](ANALYTICS_PROTOCOL.md) for delivery and interpretation rules, and [ANALYTICS_README.md](ANALYTICS_README.md) for the separate offline metrics/outcome helper. The current scheduled task is "Ежедневная аналитика CoinGlass", daily at 17:00 Europe/Warsaw; raw collection remains finite and local.

Python standard library only; Python 3.12 preferred. The host must provide IANA `Europe/Warsaw` timezone data (`zoneinfo`); the utility refuses to guess a UTC offset when unavailable.

Run only with explicit paths:

```powershell
python -B research/coinglass_daily_context_20261016/archive_daily.py --input C:/bot7/research/coinglass_daily_context_20261016/daily_input.json --outroot C:/bot7/research/coinglass_daily_context_20261016/local
```

The input file is supplied separately by the bounded browser-assisted collection described in [DAILY_COLLECTION_PROTOCOL.md](DAILY_COLLECTION_PROTOCOL.md). The archive utility does not open a browser, make requests, start a recurring task or read any collector/account state. Recurrence belongs to the Codex app; this directory installs no operating-system scheduler or background service.

Real output: `local/YYYY-MM-DD/run_<actual archive UTC milliseconds>/{input.json,report.json,summary.md,evidence/...}`. Synthetic output: `local/synthetic/YYYY-MM-DD/run_<actualms>/...`. Existing runs are never overwritten. The JSON and summary are staged and published together; a failure before publication removes only the utility's own staging directory. A collision is an error: rerun later rather than inventing a run timestamp. No latest index is written.

## Input contract

```json
{
  "schema": "daily-as-seen-v1",
  "timezone": "Europe/Warsaw",
  "synthetic": true,
  "collected_at_ms": 1792137600000,
  "finished_at_ms": 1792137720000,
  "quality_flags": [],
  "sources": [{
    "id": "public_source_id",
    "status": "PARTIAL",
    "url": "https://example.test/public",
    "event_asof_ms": null,
    "lag_status": "unknown",
    "provider_lag_ms": null,
    "stale_after_ms": 86400000,
    "market_scope": "futures",
    "aggregation": "group_aggregate",
    "forming_bar": null,
    "settings": {"symbol": "BTC", "window": "1d"},
    "values": [{"name": "displayed_metric", "type": "number", "value": null, "unit": "USD"}],
    "evidence": [{"kind": "dom_text", "path": "evidence/page.txt", "sha256": null}],
    "quality_flags": []
  }]
}
```

The JSON above is explicitly synthetic. For real collection, set `synthetic:false` and replace example timestamps/URLs/settings/values with actual observations; the real current-Warsaw-day guard applies. `example.test` is a synthetic placeholder, not an installed source. No public URL protocol is embedded in this utility; root supplies source constants and settings.

A runnable invented fixture is `synthetic_example.json`; it always archives below the separate `synthetic/` namespace. It is not a real daily record.

Statuses: `OK`, `PARTIAL`, `MISSING`, `FAILED`. Values: `type` in `number|string|boolean|json`, `value` matching the type or null, explicit `unit` string or null. A missing source can use `values:null`, `[]` or typed null values. FAILED/MISSING with non-null values is refused. Zero is never substituted for null.

`event_asof_ms` may be null. `lag_status:unknown` requires `provider_lag_ms:null`; knowing event age never makes provider lag known. Evidence kinds: `dom_text|site_export|screenshot`. Paths must be local relative `evidence/...`; the named files are copied into each immutable run and their SHA256 recorded. A null supplied SHA is allowed and the archive computes its own digest. A supplied mismatch is retained as a quality warning, not a claim of verified evidence.

`daily_date` is optional and, if present, must equal the derived Warsaw collection day. `run_id`, `archived_at_ms`, `archive_date`, `output_path` cannot be supplied. Real runs reject old collection days. Synthetic fixtures remain separate even when dated historically. No primary labels, automatic trading permission, predictions or old journal writes are created.

## Verification

```powershell
python -B -m unittest discover -s research/coinglass_daily_context_20261016 -p test_archive_daily.py -v
```

Tests are invented synthetic fixtures and local temporary files only. They cover atomic failure, overwrite refusal, Warsaw day and backdating guards, missing/future/stale as-of, provider-lag honesty, partial/failed status, typed nulls, forming bars, separate spot/futures aggregates, evidence integrity/path restrictions, and always-false order permission. See ASSUMPTIONS.md for interpretation limits.
