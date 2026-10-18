"""Run independent synthetic tests and record exact source hashes locally."""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import time
import unittest

import test_integrity_independent as tests

ROOT=Path(__file__).resolve().parents[1]


def main():
    stream=io.StringIO()
    suite=unittest.defaultTestLoader.loadTestsFromModule(tests)
    result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    paths=("evaluator.py","history_fetch.py","qa_independent/test_integrity_independent.py","qa_independent/run_qa.py")
    report={"created_at_ms":time.time_ns()//1_000_000,"synthetic_only":True,"real_network_requests":0,
            "real_archive_reads":0,"tests_run":result.testsRun,"failures":len(result.failures),
            "errors":len(result.errors),"skipped":len(result.skipped),"successful":result.wasSuccessful(),
            "source_sha256":{p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in paths},
            "output":stream.getvalue()}
    (Path(__file__).resolve().parent/"QA_RESULTS.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(stream.getvalue(),end="")
    return 0 if result.wasSuccessful() else 1


if __name__=="__main__":
    raise SystemExit(main())
