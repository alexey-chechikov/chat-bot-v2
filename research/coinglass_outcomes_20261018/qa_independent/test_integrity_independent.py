"""Independent synthetic admission/integrity QA; no real files, requests or market data."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import evaluator as e

A = 1792163700000
DAY = 96 * e.STEP


def analysis():
    groups = {sid: {"semantic_hash": e.HASHES[sid], "semantics": deepcopy(e.DEFINITIONS[sid])} for sid in e.DEFINITIONS}
    body = {"schema":"daily-context-analytics-v1", "created_at_ms":A-1,
            "input_run_id":"2026-10-16/run_1792162117321", "order_permission":False, "synthetic":False,
            "prospective_plan":[{"source_id":sid,"semantic_hash":e.HASHES[sid],"created_at_ms":A-1,"anchor_start_ms":A} for sid in e.BAR_IDS],
            "current_sources":groups}
    return {"id":"analysis_"+str(A-1),"body":body,"input":{"path":"invented-analysis", "sha256":hashlib.sha256(e.encoded(body)).hexdigest()}}


def bar(t):
    return {"bar_start_ms":t,"bar_end_ms":t+e.STEP,"closed":True,
            "open":"100","high":"102","low":"99","close":"101",
            "base_volume":"10","quote_volume":"1000","taker_buy_base":"6","taker_buy_quote":"600"}


def history():
    received = A + DAY + e.STEP
    sources = []
    for sid in e.BAR_IDS:
        definition = deepcopy(e.DEFINITIONS[sid])
        settings = deepcopy(definition["settings"])
        settings["requested_closed_bars"] = 384
        settings["request"] = {"received_at_ms":received}
        sources.append({"id":sid,"url":definition["source_path"],"market_scope":definition["market_scope"],
                        "aggregation":definition["aggregation"],"legacy_definition":definition,"settings":settings,
                        "values":[{"name":"observations","type":"json","value":[bar(t) for t in range(A,A+DAY,e.STEP)]}]})
    return {"schema":e.HISTORY_SCHEMA,"synthetic":False,"collected_at_ms":received-1000,
            "finished_at_ms":received,"cutoff_ms":received,"sources":sources}


def compute(histories, a=None):
    return e.compute([], [a or analysis()], [], histories, A+DAY+2*e.STEP)


def record(report):
    return next(r for r in report["records"] if r["record_kind"]=="machine_analysis" and r["source_id"]==e.BAR_IDS[0] and r["horizon_minutes"]==15)


class Admission(unittest.TestCase):
    def test_control_compatible_actual_extended_settings(self):
        self.assertEqual(record(compute([history()]))["status"],"MATURE")

    def test_actual_eth_symbol_cannot_be_admitted_with_legacy_btc_label(self):
        h=history()
        h["sources"][0]["settings"]["symbol"]="ETHUSDT"
        self.assertNotEqual(record(compute([h]))["status"],"MATURE")

    def test_url_query_symbol_cannot_contradict_definition(self):
        h=history()
        h["sources"][0]["url"] += "?symbol=ETHUSDT&interval=15m"
        self.assertNotEqual(record(compute([h]))["status"],"MATURE")

    def test_actual_1m_interval_cannot_be_admitted_with_legacy_15m_label(self):
        h=history()
        h["sources"][0]["settings"]["interval"]="1m"
        self.assertNotEqual(record(compute([h]))["status"],"MATURE")

    def test_frozen_object_must_agree_with_its_hash(self):
        a=analysis()
        a["body"]["current_sources"][e.BAR_IDS[0]]["semantics"]["settings"]["symbol"]="ETHUSDT"
        self.assertNotEqual(record(compute([history()],a))["status"],"MATURE")

    def test_missing_optional_flow_revision_does_not_conflict_price(self):
        one=history(); two=deepcopy(one)
        one["sources"][0]["values"][0]["value"][0].pop("base_volume")
        result=record(compute([one,two]))
        self.assertEqual(result["status"],"MATURE")

    def test_changed_optional_flow_revision_does_not_conflict_price(self):
        one=history(); two=deepcopy(one)
        two["sources"][0]["values"][0]["value"][0]["taker_buy_base"]="7"
        result=record(compute([one,two]))
        self.assertEqual(result["status"],"MATURE")
        self.assertNotEqual(result["flow"]["status"],"AVAILABLE")
        self.assertIsNone(result["flow"]["metrics"])

    def test_price_revision_still_is_conflict(self):
        one=history(); two=deepcopy(one)
        two["sources"][0]["values"][0]["value"][0]["close"]="101.5"
        self.assertEqual(record(compute([one,two]))["status"],"CONFLICT")


class FrozenInputFiles(unittest.TestCase):
    def setUp(self):
        self.testbase=(ROOT/"local"/"test_temp").resolve()
        self.testbase.mkdir(parents=True,exist_ok=True)
        self.tmp=tempfile.TemporaryDirectory(dir=self.testbase)
        self.base=Path(self.tmp.name).resolve()
        assert self.base.is_relative_to(self.testbase) and self.base != self.testbase
        self.local=self.base/"daily"; self.local.mkdir()
        self.hr=self.base/"history_1"; self.hr.mkdir()
        self.out=self.base/"supplements"
        self.run_id="2026-10-16/run_1792162117321"
        self.run_path=self.local/self.run_id/"report.json"
        h=history()
        self.daily={"schema":"daily-as-seen-v1","synthetic":False,"order_permission":False,
                    "archived_at_ms":1792162117321,"sources":deepcopy(h["sources"])}
        for s in self.daily["sources"]:
            s["settings"]["requested_closed_bars"]=96
            s["settings"]["request"]["received_at_ms"]=self.daily["archived_at_ms"]-1
            s["values"][0]["value"]=[]
        self.write(self.run_path,self.daily)
        self.write(self.hr/"history.json",h)
        self.a=analysis()["body"]
        self.a["input_report_sha256"]=hashlib.sha256(self.run_path.read_bytes()).hexdigest()
        self.a["history_inputs"]=[{"id":self.run_id,"sha256":self.a["input_report_sha256"]}]
        self.analysis_path=self.local/"analytics"/("analysis_"+str(A-1))/"report.json"
        self.write(self.analysis_path,self.a)

    def tearDown(self):
        assert self.base.resolve().is_relative_to(self.testbase) and self.base.resolve() != self.testbase
        self.tmp.cleanup()

    @staticmethod
    def write(path,body):
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(body),encoding="utf-8")

    def run_eval(self):
        return e.evaluate(self.local,[self.hr],self.out,_now_ms=A+DAY+2*e.STEP)

    def test_control_original_input_sha_matches(self):
        _, report, _ = self.run_eval()
        self.assertEqual(record(report)["status"],"MATURE")

    def test_daily_mutated_before_first_supplement_is_refused(self):
        self.daily["new_field"]="changed after analysis"
        self.write(self.run_path,self.daily)
        with self.assertRaises(ValueError):
            self.run_eval()

    def test_history_input_sha_mutation_refused_on_first_admission(self):
        self.a["history_inputs"][0]["sha256"]="f"*64
        self.write(self.analysis_path,self.a)
        with self.assertRaises(ValueError):
            self.run_eval()

    def test_future_daily_input_relative_to_analysis_is_refused(self):
        later=A+1
        self.run_path.unlink()
        self.run_id="2026-10-16/run_"+str(later)
        self.run_path=self.local/self.run_id/"report.json"
        self.daily["archived_at_ms"]=later
        for s in self.daily["sources"]:
            s["settings"]["request"]["received_at_ms"]=later-1
        self.write(self.run_path,self.daily)
        self.a["input_run_id"]=self.run_id
        self.a["input_report_sha256"]=hashlib.sha256(self.run_path.read_bytes()).hexdigest()
        self.a["history_inputs"]=[{"id":self.run_id,"sha256":self.a["input_report_sha256"]}]
        self.write(self.analysis_path,self.a)
        with self.assertRaises(ValueError):
            self.run_eval()

    def test_missing_frozen_daily_input_cannot_be_silently_substituted(self):
        self.run_path.unlink()
        with self.assertRaises(ValueError):
            self.run_eval()


class CollectorIntegration(unittest.TestCase):
    @staticmethod
    def frozen_at(anchor):
        a=analysis()
        a["id"]="analysis_"+str(anchor-1)
        a["body"]["created_at_ms"]=anchor-1
        for plan in a["body"]["prospective_plan"]:
            plan["created_at_ms"]=anchor-1
            plan["anchor_start_ms"]=anchor
        a["input"]["sha256"]=hashlib.sha256(e.encoded(a["body"])).hexdigest()
        return a

    def test_real_collector_abi_with_fake_network_has_exact_price_and_OI(self):
        import history_fetch as fetch
        import test_history_fetch as fixture
        client=fixture.FakeClient()
        h,daily,evidence=fetch.collect(client,include_premium=True,clock=lambda:fixture.NOW,synthetic=True)
        a=self.frozen_at(fixture.END-DAY)
        result=e.compute([], [a], [], [h], fixture.NOW)
        for r in result["records"]:
            self.assertEqual(r["status"],"MATURE")
            self.assertEqual(r["baseline_open"],"100")
            self.assertEqual(r["end_close"],"101")
            self.assertEqual(r["return_pct"],"1.00")
            self.assertEqual(r["oi"]["status"],"AVAILABLE")
        self.assertEqual(len(client.urls),6)
        self.assertEqual(len(evidence),12)
        self.assertEqual(len(result["source_issues"]),0)

    def test_real_collector_clock_failure_bundle_is_not_price_input(self):
        import history_fetch as fetch
        import test_history_fetch as fixture
        client=fixture.FakeClient(fail="/fapi/v1/time")
        h,daily,evidence=fetch.collect(client,include_premium=True,clock=lambda:fixture.NOW,synthetic=True)
        a=self.frozen_at(fixture.END-DAY)
        result=e.compute([], [a], [], [h], fixture.NOW)
        self.assertIsNone(h["cutoff_ms"])
        self.assertEqual(len(client.urls),1)
        self.assertTrue(all(r["status"]!="MATURE" and r["baseline_open"] is None for r in result["records"]))
        self.assertFalse(result["history_admissions"][0]["admitted"])


if __name__ == "__main__":
    unittest.main()
