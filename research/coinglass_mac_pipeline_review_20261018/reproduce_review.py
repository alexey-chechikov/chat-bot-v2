"""Finite synthetic reproductions of reviewed functions; no production imports/network."""
from __future__ import annotations

import ast
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE = HERE / 'source_snapshot/services/coinglass_web/outcomes.py'
tree = ast.parse(SOURCE.read_text(encoding='utf-8'))
names = {'first_touch', '_snapshots', 'done_keys', 'update', 'stats'}
functions = ast.Module(body=[n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names], type_ignores=[])
ns = {'json': json, 'math': math, 'datetime': datetime, 'timedelta': timedelta, 'timezone': timezone,
      'HORIZONS': {'24h': 86400}}
exec(compile(functions, str(SOURCE), 'exec'), ns)
results = []


def fixture(name, snapshots=(), outcomes=()):
    p = (HERE / 'reproduction_cases' / name).resolve()
    assert p.is_relative_to(HERE.resolve())
    p.mkdir(parents=True, exist_ok=True)
    for filename, rows in [('snapshots.jsonl', snapshots), ('outcomes.jsonl', outcomes)]:
        (p / filename).write_text(''.join(json.dumps(r) + '\n' for r in rows), encoding='utf-8')
    ns['DIR'] = p
    return p


def snap(ts, **extra):
    return {'ts': ts, 'levels': {'price': 100., 'zones_short': [{'lo': 101., 'hi': 102.}],
                               'zones_long': [{'lo': 98., 'hi': 99.}]}, **extra}


def bars(a, b, skip=None, hit_first=False):
    return [[t, '100', '102' if hit_first and i == 0 else '100', '100', '100']
            for i, t in enumerate(range(a, b, 60000)) if i != skip]


def main():
    # The morning itself had no touch. stats selects a later hour AFTER filtering.
    morning = {'ts': '2026-10-17T05:00:00+00:00', 'horizon': '24h', 'outcome': 'none', 'base_up': .5}
    later = {**morning, 'ts': '2026-10-17T06:00:00+00:00', 'outcome': 'upper'}
    fixture('first_day_selected_after_outcome', outcomes=[morning, later])
    actual = ns['stats']('24h', True)
    assert actual['n'] == 1 and actual['obs_up'] == 1.
    results.append({'case': 'first_daily_origin_replaced_after_filtering', 'bug_reproduced': True,
                    'fixed_morning_outcome': 'none', 'current_stats': actual})

    s = snap('2026-10-17T05:00:00+00:00')
    p = fixture('missing_minute_committed', snapshots=[s])
    ns['_klines'] = lambda a, b: bars(a, b, skip=10)
    count = ns['update'](datetime(2026, 10, 18, 7, tzinfo=timezone.utc))
    outcome = json.loads((p / 'outcomes.jsonl').read_text(encoding='utf-8'))
    assert count == 1 and outcome['outcome'] == 'none'
    results.append({'case': '1439_of_1440_minutes_recorded_as_final_none', 'bug_reproduced': True,
                    'minute_grid_complete': False, 'current_outcome': outcome['outcome'],
                    'required_result': 'unknown_coverage; missing minute could contain first touch'})

    s = snap('2026-10-17T05:00:59+00:00', fixture_levels_received_at='2026-10-17T05:02:10+00:00')
    p = fixture('browser_start_used_as_available_time', snapshots=[s])
    observed = {}

    def klines(a, b):
        observed['path_start_ms'] = a
        return bars(a, b, hit_first=True)

    ns['_klines'] = klines
    ns['update'](datetime(2026, 10, 18, 7, tzinfo=timezone.utc))
    outcome = json.loads((p / 'outcomes.jsonl').read_text(encoding='utf-8'))
    received = int(datetime.fromisoformat(s['fixture_levels_received_at']).timestamp() * 1000)
    assert outcome['outcome'] == 'upper' and observed['path_start_ms'] < received
    results.append({'case': 'pre_availability_bar_counts_as_future_hit', 'bug_reproduced': True,
                    'current_outcome': outcome['outcome'], **observed, 'levels_received_ms': received,
                    'seconds_early': (received - observed['path_start_ms']) / 1000})

    old = {'ts': s['ts'], 'horizon': '24h', 'outcome': 'upper', 'base_up': .5, 'rule_version': 'v0'}
    fixture('version_not_in_dedup_key', snapshots=[{**s, 'rule_version': 'v1'}], outcomes=[old])
    ns['_klines'] = lambda *_: (_ for _ in ()).throw(AssertionError('should skip before fetching'))
    count = ns['update'](datetime(2026, 10, 18, 7, tzinfo=timezone.utc))
    assert count == 0
    results.append({'case': 'v0_key_suppresses_v1_same_snapshot', 'bug_reproduced': True,
                    'new_v1_outcomes': count, 'current_key': ['ts', 'horizon'],
                    'required_key': ['snapshot_id', 'rule_version', 'horizon']})

    # Exact finite-horizon driftless random-walk counterexample, not market data.
    # Start 0, barriers +2/-1, one fair +/-1 step: upper 0, lower 1/2, neither 1/2.
    eventual_formula = 1 / (2 + 1)
    finite_upper = 0.
    finite_lower = .5
    finite_conditional_upper = finite_upper / (finite_upper + finite_lower)
    assert eventual_formula != finite_conditional_upper
    results.append({'case': 'eventual_probability_not_finite_conditional_probability', 'counterexample_verified': True,
                    'model': 'fair unit-step random walk; start0; barriers+2/-1; horizon1step',
                    'distance_formula': eventual_formula, 'upper_before_deadline': finite_upper,
                    'lower_before_deadline': finite_lower, 'neither': .5,
                    'upper_conditional_on_exit_before_deadline': finite_conditional_upper})
    output = {'source_commit': '13e40a7198d51c9627b585ccd8a517b3dee11ebf',
              'synthetic_only': True, 'network_requests': 0, 'production_imports': False,
              'reproductions': results, 'verified': len(results)}
    (HERE / 'REPRODUCTIONS.json').write_text(json.dumps(output, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'synthetic_reproductions_verified': len(results), 'network_requests': 0}))


if __name__ == '__main__':
    main()
