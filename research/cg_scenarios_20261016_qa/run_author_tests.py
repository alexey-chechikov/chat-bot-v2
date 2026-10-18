"""Run the builder's tests with a sandbox-safe, task-owned temp directory."""
from pathlib import Path
import hashlib
import io
import json
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parent
SOURCE=ROOT.parent/'cg_scenarios_20261016'
temp_root=(ROOT/'unit_tmp').resolve()
assert temp_root.is_relative_to(ROOT.resolve())
temp_root.mkdir(exist_ok=True)
tempfile.tempdir=str(temp_root)
sys.path.insert(0,str(SOURCE))
suite=unittest.defaultTestLoader.loadTestsFromName('test_scenario_card')
buffer=io.StringIO()
result=unittest.TextTestRunner(stream=buffer,verbosity=2).run(suite)
(ROOT/'AUTHOR_TEST_OUTPUT.txt').write_text(buffer.getvalue(),encoding='utf-8')
report={'tests_run':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),
        'skipped':len(result.skipped),'success':result.wasSuccessful(),
        'temp_redirect':'task-owned writable unit_tmp; no source code edits',
        'source_sha256':hashlib.sha256((SOURCE/'scenario_card.py').read_bytes()).hexdigest(),
        'tests_sha256':hashlib.sha256((SOURCE/'test_scenario_card.py').read_bytes()).hexdigest()}
(ROOT/'AUTHOR_TEST_RESULTS.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(report))
if not result.wasSuccessful():
    print(buffer.getvalue())
    raise SystemExit(1)
