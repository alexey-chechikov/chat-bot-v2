"""One finite public OI archive. No credentials, continuous feeds or trading."""
from __future__ import annotations

import csv
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

BASE = 'https://fapi.binance.com/futures/data/openInterestHist'
PERIOD = 900_000
START = int(datetime(2026, 9, 18, tzinfo=timezone.utc).timestamp() * 1000)
END = int(datetime(2026, 10, 15, tzinfo=timezone.utc).timestamp() * 1000)
SYMBOLS = ('BTCUSDT', 'ETHUSDT')
ROOT = Path(__file__).resolve().parent


def validate(rows, symbol, start, end):
    if not isinstance(rows, list):
        raise ValueError('response is not a list')
    answer = []
    last = None
    for row in rows:
        if row.get('symbol') != symbol:
            raise ValueError('wrong symbol')
        ts = row.get('timestamp')
        if isinstance(ts, bool) or not isinstance(ts, int):
            raise ValueError('timestamp not integer milliseconds')
        if not start <= ts < end or ts % PERIOD:
            raise ValueError('timestamp outside requested grid/window')
        if last is not None and ts <= last:
            raise ValueError('duplicate/non-increasing timestamp')
        for key in ('sumOpenInterest', 'sumOpenInterestValue'):
            try:
                value = Decimal(str(row[key]))
            except (InvalidOperation, KeyError) as exc:
                raise ValueError('invalid OI') from exc
            if not value.is_finite() or value < 0:
                raise ValueError('nonfinite/negative OI')
        answer.append({k: row[k] for k in ('timestamp', 'sumOpenInterest', 'sumOpenInterestValue')})
        last = ts
    return answer


def coverage(rows, start, end):
    present = {r['timestamp'] for r in rows}
    expected = set(range(start, end, PERIOD))
    missing = sorted(expected - present)
    return {'expected_points': len(expected), 'observed_points': len(present),
            'missing_count': len(missing), 'missing_timestamps': missing,
            'historical_received_time': None, 'publication_lag_ms': None}


def save_new(path, data):
    with path.open('xb') as f:
        f.write(data)


def main():
    out = ROOT / 'public_oi'
    out.mkdir(exist_ok=True)
    summary = {'source': BASE, 'period_ms': PERIOD, 'start_ms_inclusive': START,
               'end_ms_exclusive': END, 'is_continuous_collector': False,
               'historical_received_time': None, 'publication_lag_ms': None,
               'code_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
               'assumptions_sha256': hashlib.sha256((ROOT/'ASSUMPTIONS.md').read_bytes()).hexdigest(),
               'requests': [], 'symbols': {}, 'errors': []}
    for symbol in SYMBOLS:
        result = []
        failed = False
        for i, start in enumerate(range(START, END, 500*PERIOD)):
            end = min(start+500*PERIOD, END)
            query = urlencode({'symbol': symbol, 'period': '15m', 'limit': 500,
                               'startTime': start, 'endTime': end-1})
            url = BASE+'?'+query
            cache = out / f'{symbol}_{i:02d}.json'
            rowmeta = {'url': url, 'cache': cache.name, 'requested_start_ms': start,
                       'requested_end_ms_exclusive': end}
            if cache.exists():
                raw = cache.read_bytes()
                rowmeta['from_cache'] = True
                rowmeta['received_ms_this_run'] = None
            else:
                rowmeta['requested_ms'] = time.time_ns() // 1_000_000
                try:
                    req = Request(url, headers={'User-Agent': 'Codex-public-research/1.0'})
                    with urlopen(req, timeout=20) as response:
                        if response.status != 200:
                            raise ValueError(f'HTTP {response.status}')
                        raw = response.read(2_000_001)
                    rowmeta['received_ms_this_run'] = time.time_ns() // 1_000_000
                    if len(raw) > 2_000_000:
                        raise ValueError('oversized public response')
                except (HTTPError, URLError, TimeoutError, ValueError, OSError) as exc:
                    summary['errors'].append({'symbol': symbol, 'url': url,
                                              'error': str(exc), 'no_retry': True})
                    failed = True
                    break
            try:
                parsed = validate(json.loads(raw), symbol, start, end)
            except (ValueError, TypeError, AttributeError) as exc:
                summary['errors'].append({'symbol': symbol, 'url': url, 'error': str(exc)})
                failed = True
                break
            if not cache.exists():
                save_new(cache, raw)
            rowmeta['sha256'] = hashlib.sha256(raw).hexdigest()
            rowmeta['rows'] = len(parsed)
            summary['requests'].append(rowmeta)
            result.extend(parsed)
        timestamps = [r['timestamp'] for r in result]
        if len(timestamps) != len(set(timestamps)):
            raise ValueError('duplicate timestamps across pages')
        entry = coverage(result, START, END)
        entry['status'] = 'INCOMPLETE' if failed else ('COMPLETE_GRID' if not entry['missing_count'] else 'GAPS')
        if result:
            path = out / f'{symbol}_oi_15m.csv'
            import io
            buf = io.StringIO(newline='')
            writer = csv.DictWriter(buf, fieldnames=['timestamp','sumOpenInterest','sumOpenInterestValue'], lineterminator='\n')
            writer.writeheader()
            writer.writerows(result)
            data = buf.getvalue().encode()
            if path.exists() and path.read_bytes() != data:
                raise ValueError('refuse overwrite changed archive')
            if not path.exists():
                save_new(path, data)
            entry.update(csv=path.name, sha256=hashlib.sha256(data).hexdigest(),
                         first_timestamp=min(timestamps), last_timestamp=max(timestamps))
        summary['symbols'][symbol] = entry
    save_new(out/'manifest.json', (json.dumps(summary, indent=2)+'\n').encode())
    print(json.dumps({'symbols': {k:{f:v for f,v in x.items() if f!='missing_timestamps'} for k,x in summary['symbols'].items()},
                      'errors': summary['errors']}, indent=2))
    return 1 if summary['errors'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
