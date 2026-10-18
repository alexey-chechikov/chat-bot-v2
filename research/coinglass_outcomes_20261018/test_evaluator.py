"""Invented public inputs only; no market requests or real archive reads."""
from copy import deepcopy
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import evaluator as e

A = 1792163700000
DAY = 96*e.STEP


def analysis(created=A-1, ident=None, run="2026-10-16/run_1792162117321"):
    ident=ident or "analysis_"+str(created)
    body={"schema":"daily-context-analytics-v1","created_at_ms":created,"input_run_id":run,
          "order_permission":False,"synthetic":False,
          "prospective_plan":[{"source_id":sid,"semantic_hash":e.HASHES[sid],"created_at_ms":created,
                               "anchor_start_ms":e.anchor_at(created)} for sid in e.BAR_IDS],
          "current_sources":{sid:{"semantic_hash":e.HASHES[sid],"semantics":deepcopy(e.DEFINITIONS[sid])} for sid in e.DEFINITIONS}}
    raw=json.dumps(body).encode()
    return {"id":ident,"body":body,"input":{"path":"invented/"+ident,"sha256":hashlib.sha256(raw).hexdigest()}}


def note(created=A+1, bound=None, run="2026-10-16/run_1792162117321"):
    body={"schema":"analyst-note-v1","created_at_ms":created,"input_run":run,"order_permission":False}
    if bound is not None:
        body["analysis_id"]=bound["id"]; body["analysis_report_sha256"]=bound["input"]["sha256"]
    return {"id":"note_"+str(created),"body":body,"input":{"path":"invented/note_"+str(created),"sha256":"1"*64}}


def bar(t,index=0,zero=False):
    price=Decimal(100)+Decimal(index)/100
    return {"bar_start_ms":t,"bar_end_ms":t+e.STEP,"closed":True,"open":str(price),
            "close":str(price+Decimal(".005")),"high":str(price+1),"low":str(price-1),
            "base_volume":"0" if zero else "10","quote_volume":"0" if zero else "1000",
            "taker_buy_base":"0" if zero else "6","taker_buy_quote":"0" if zero else "600"}


def history(start=A-3*DAY,end=A+DAY,received=None,with_oi=True):
    received=received if received is not None else end+e.STEP
    sources=[]
    for sid in e.BAR_IDS:
        definition=deepcopy(e.DEFINITIONS[sid])
        settings=deepcopy(definition["settings"])
        settings.update(requested_closed_bars=384,request={"received_at_ms":received})
        sources.append({"id":sid,"url":definition["source_path"],"market_scope":definition["market_scope"],
                        "aggregation":definition["aggregation"],"legacy_definition":definition,
                        "settings":settings,"values":[{"name":"observations","type":"json",
                        "value":[bar(t,i) for i,t in enumerate(range(start,end,e.STEP))]}]})
    if with_oi:
        definition=deepcopy(e.DEFINITIONS[e.OI_ID])
        settings=deepcopy(definition["settings"])
        settings.update(expected_points=385,request={"received_at_ms":received})
        sources.append({"id":e.OI_ID,"url":definition["source_path"],"market_scope":"futures",
                        "aggregation":definition["aggregation"],"legacy_definition":definition,
                        "settings":settings,"values":[{"name":"observations","type":"json",
                        "value":[{"timestamp_ms":t,"sum_open_interest":"100","sum_open_interest_value":"10000",
                                  "quantity_unit":"provider_native_open_interest_units","value_unit":"provider_reported_notional_value"}
                                 for t in range(start,end+e.STEP,e.STEP)]}]})
    return {"schema":e.HISTORY_SCHEMA,"synthetic":False,"collected_at_ms":received-1000,
            "finished_at_ms":received,"cutoff_ms":received,"sources":sources}


def evaluate_inputs(histories=None,notes=None,analyses=None,now=None):
    return e.compute([],analyses or [analysis()],notes or [],histories or [history()],now or A+DAY+e.STEP)


def record(report,kind="machine_analysis",sid=e.BAR_IDS[0],minutes=15):
    return next(r for r in report["records"] if r["record_kind"]==kind and r["source_id"]==sid and r["horizon_minutes"]==minutes)


class Outcomes(unittest.TestCase):
    def test_exact_four_horizons_and_raw_return_independent_formula(self):
        report=evaluate_inputs()
        self.assertEqual(report["status_counts"]["MATURE"],8)
        r=record(report,minutes=1440)
        expected=(Decimal("103.835")/Decimal("102.88")-1)*100
        self.assertEqual(Decimal(r["return_pct"]),expected)
        self.assertEqual(r["expected_bars"],96)
        self.assertFalse(r["PnL"])

    def test_spot_and_perpetual_are_independent_series(self):
        h=history()
        h["sources"][1]["values"][0]["value"]=[]
        result=evaluate_inputs([h])
        self.assertEqual(record(result)["status"],"MATURE")
        self.assertEqual(record(result,sid=e.BAR_IDS[1])["status"],"MISSING")

    def test_horizon_not_elapsed_and_refresh_grace(self):
        early=history(end=A,received=A+100)
        result=evaluate_inputs([early],now=A+100)
        self.assertEqual(record(result)["status"],"PENDING")
        result=evaluate_inputs([early],now=A+e.STEP)
        self.assertEqual(record(result)["status"],"PENDING")

    def test_missing_intrawindow_candle_not_endpoint_shortcut(self):
        h=history()
        h["sources"][0]["values"][0]["value"]=[b for b in h["sources"][0]["values"][0]["value"] if b["bar_start_ms"]!=A+e.STEP]
        result=evaluate_inputs([h])
        self.assertEqual(record(result,minutes=15)["status"],"MATURE")
        r=record(result,minutes=60)
        self.assertEqual(r["status"],"MISSING")
        self.assertIsNone(r["return_pct"])
        self.assertEqual(r["missing_timestamps"],[A+e.STEP])

    def test_forming_last_bar_not_admitted(self):
        h=history()
        h["sources"][0]["values"][0]["value"][-1]["closed"]=False
        r=record(evaluate_inputs([h]),minutes=1440)
        self.assertEqual(r["status"],"MISSING")

    def test_conflict_survives_third_matching_revision(self):
        one=history(); two=deepcopy(one)
        row=next(r for r in two["sources"][0]["values"][0]["value"] if r["bar_start_ms"]==A)
        row["close"]=str(Decimal(row["close"])+Decimal(".01"))
        result=evaluate_inputs([one,two,deepcopy(one)])
        r=record(result)
        self.assertEqual(r["status"],"CONFLICT")
        self.assertEqual(r["conflicting_timestamps"],[A])
        self.assertIsNone(r["baseline_open"])

    def test_declared_conflict_cannot_be_resurrected_by_another_archive(self):
        one=history(); two=deepcopy(one)
        two["sources"][0]["conflicting_timestamps"]=[A]
        two["sources"][0]["values"][0]["value"]=[r for r in two["sources"][0]["values"][0]["value"] if r["bar_start_ms"]!=A]
        r=record(evaluate_inputs([one,two,deepcopy(one)]))
        self.assertEqual(r["status"],"CONFLICT")

    def test_identical_duplicate_is_not_conflict(self):
        h=history()
        result=evaluate_inputs([h,deepcopy(h)])
        self.assertEqual(record(result)["status"],"MATURE")

    def test_price_mature_with_missing_oi_and_flow(self):
        h=history(with_oi=False)
        row=next(r for r in h["sources"][0]["values"][0]["value"] if r["bar_start_ms"]==A)
        row.pop("base_volume")
        r=record(evaluate_inputs([h]))
        self.assertEqual(r["status"],"MATURE")
        self.assertEqual(r["flow"]["status"],"MISSING")
        self.assertEqual(r["oi"]["status"],"MISSING")

    def test_zero_volume_F_null(self):
        h=history()
        rows=h["sources"][0]["values"][0]["value"]
        for i,b in enumerate(rows):
            if b["bar_start_ms"]==A: rows[i]=bar(A,i,zero=True)
        r=record(evaluate_inputs([h]))
        self.assertEqual(r["flow"]["status"],"AVAILABLE")
        self.assertIsNone(r["flow"]["metrics"]["F_volume_weighted_fraction"])

    def test_oi_conflict_does_not_erase_complete_price(self):
        one=history(); two=deepcopy(one)
        row=next(r for r in two["sources"][2]["values"][0]["value"] if r["timestamp_ms"]==A)
        row["sum_open_interest"]="101"
        r=record(evaluate_inputs([one,two]))
        self.assertEqual(r["status"],"MATURE")
        self.assertEqual(r["oi"]["status"],"CONFLICT")

    def test_flow_enrichment_and_conflict_do_not_erase_price(self):
        one=history(); rich=deepcopy(one)
        row=next(r for r in one["sources"][0]["values"][0]["value"] if r["bar_start_ms"]==A)
        row.pop("base_volume")
        result=record(evaluate_inputs([one,rich]))
        self.assertEqual(result["status"],"MATURE")
        self.assertEqual(result["flow"]["status"],"AVAILABLE")
        changed=deepcopy(rich)
        row=next(r for r in changed["sources"][0]["values"][0]["value"] if r["bar_start_ms"]==A)
        row["base_volume"]="11"
        result=record(evaluate_inputs([rich,changed,deepcopy(rich)]))
        self.assertEqual(result["status"],"MATURE")
        self.assertEqual(result["flow"]["status"],"CONFLICT")

    def test_wrong_definition_and_product_do_not_merge(self):
        for field,value in (("market_scope","futures"),("url","https://untrusted.invalid/api/v3/klines")):
            h=history(); h["sources"][0][field]=value
            self.assertEqual(record(evaluate_inputs([h]))["status"],"PENDING")
        h=history(); h["sources"][0]["legacy_definition"]["settings"]["requested_closed_bars"]=384
        self.assertNotEqual(record(evaluate_inputs([h]))["status"],"MATURE")

    def test_forged_legacy_definition_cannot_override_actual_query_or_settings(self):
        for patch in ({"symbol":"ETHUSDT"},{"interval":"1m"},{"units":"contracts"}):
            h=history(); h["sources"][0]["settings"].update(patch)
            self.assertNotEqual(record(evaluate_inputs([h]))["status"],"MATURE")
        for query in ("symbol=ETHUSDT&interval=15m","symbol=BTCUSDT&symbol=ETHUSDT&interval=15m","symbol=BTCUSDT&interval=1m"):
            h=history(); h["sources"][0]["url"]+="?"+query
            self.assertNotEqual(record(evaluate_inputs([h]))["status"],"MATURE")

    def test_bad_oi_units_remain_missing(self):
        h=history()
        for r in h["sources"][2]["values"][0]["value"]: r["quantity_unit"]="USD"
        self.assertEqual(record(evaluate_inputs([h]))["oi"]["status"],"MISSING")

    def test_future_receipt_not_admitted(self):
        result=evaluate_inputs([history(received=A+2*DAY)],now=A+DAY+e.STEP)
        self.assertNotEqual(record(result)["status"],"MATURE")
        self.assertFalse(result["history_admissions"][0]["admitted"])

    def test_three_day_gap_covered_only_by_extended_history(self):
        h=history(end=A+3*DAY,start=A-DAY,received=A+3*DAY+e.STEP)
        self.assertEqual(record(evaluate_inputs([h],now=A+3*DAY+e.STEP),minutes=1440)["status"],"MATURE")
        old=history(start=A+2*DAY,end=A+3*DAY,received=A+3*DAY+e.STEP)
        self.assertEqual(record(evaluate_inputs([old],now=A+3*DAY+e.STEP))["status"],"MISSING")


class Notes(unittest.TestCase):
    def test_late_note_has_own_later_anchor(self):
        a=analysis(); n=note(bound=a)
        report=evaluate_inputs(notes=[n],analyses=[a])
        machine=record(report); human=record(report,"human_note")
        self.assertEqual(machine["anchor_ms"],A)
        self.assertEqual(human["anchor_ms"],A+e.STEP)
        self.assertNotEqual(human["baseline_open"],machine["baseline_open"])
        self.assertFalse(report["human_conditions_automatically_assessed"])

    def test_first_legacy_note_binds_unique_run_and_later_machine(self):
        a=analysis(created=A+1); n=note(created=A-1)
        targets=e.record_targets([a],[n]); human=next(t for t in targets if t["kind"]=="human_note")
        self.assertEqual(human["binding"],"unique_input_run")
        self.assertEqual(human["anchor_ms"],A+e.STEP)

    def test_ambiguous_run_not_silently_bound(self):
        one,two=analysis(),analysis(created=A+1)
        n=note()
        report=evaluate_inputs(notes=[n],analyses=[one,two])
        human=record(report,"human_note")
        self.assertEqual(human["status"],"MISSING")
        self.assertIsNone(human["return_pct"])

    def test_declared_hash_and_anchor_mutation_refused(self):
        a=analysis(); n=note(bound=a)
        n["body"]["analysis_report_sha256"]="f"*64
        with self.assertRaises(ValueError): e.record_targets([a],[n])

    def test_frozen_semantic_object_must_match_its_hash(self):
        a=analysis()
        a["body"]["current_sources"][e.BAR_IDS[0]]["semantics"]["settings"]["symbol"]="ETHUSDT"
        self.assertEqual(record(evaluate_inputs(analyses=[a]))["status"],"MISSING")
        a=analysis()
        a["body"]["current_sources"][e.OI_ID]["semantics"]["settings"]["units"]="USD"
        r=record(evaluate_inputs(analyses=[a]))
        self.assertEqual(r["status"],"MATURE")
        self.assertEqual(r["oi"]["status"],"MISSING")
        n=note(bound=a); n["body"]["earliest_forward_anchor_ms"]=A
        with self.assertRaises(ValueError): e.record_targets([a],[n])

    def test_three_notes_choose_true_predecessor_not_first(self):
        a=analysis()
        notes=[note(A+i*e.STEP+1,bound=a) for i in range(3)]
        report=evaluate_inputs(notes=list(reversed(notes)),analyses=[a])
        self.assertEqual(report["latest_note_id"],notes[-1]["id"])
        self.assertEqual(report["immediately_previous_note_id"],notes[-2]["id"])

    def test_unknown_text_conditions_never_scored(self):
        a=analysis(); n=note(bound=a)
        n["body"]["future_condition_plan"]={"strengthen":"invented arbitrary text"}
        report=evaluate_inputs(notes=[n],analyses=[a])
        human=next(t for t in report["targets"] if t["kind"]=="human_note")
        self.assertEqual(human["text_conditions"]["status"],"NOT_AUTOMATICALLY_ASSESSED")


class Files(unittest.TestCase):
    def setUp(self):
        self.testbase=Path(__file__).resolve().parent/"local"/"test_temp"
        self.testbase.mkdir(parents=True,exist_ok=True)
        self.tmp=tempfile.TemporaryDirectory(dir=self.testbase); self.root=Path(self.tmp.name)
        self.local=self.root/"daily"; self.local.mkdir()
        self.out=self.root/"supplements"; self.hr=self.root/"history_1"; self.hr.mkdir()
        self.a=analysis()
        run=self.a["body"]["input_run_id"]
        report={"schema":"daily-as-seen-v1","synthetic":False,"archived_at_ms":int(run.split("run_")[1]),
                "order_permission":False,"sources":[]}
        rp=self.local/run/"report.json"; self.write(rp,report)
        self.a["body"]["input_report_sha256"]=hashlib.sha256(rp.read_bytes()).hexdigest()
        self.ap=self.local/"analytics"/self.a["id"]/"report.json"
        self.write(self.ap,self.a["body"])
        self.write(self.hr/"history.json",history())

    def tearDown(self):
        assert self.root.resolve().is_relative_to(self.testbase.resolve())
        self.tmp.cleanup()

    @staticmethod
    def write(path,body):
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(body),encoding="utf-8")

    def run_eval(self,now=A+DAY+e.STEP):
        return e.evaluate(self.local,[self.hr],self.out,_now_ms=now)

    def test_idempotent_repeat_and_immutable_input_mutation(self):
        first,report,reused=self.run_eval()
        before=(first/"report.json").read_bytes()
        second,again,reused=self.run_eval(now=A+DAY+2*e.STEP)
        self.assertTrue(reused); self.assertEqual(first,second)
        self.assertEqual((first/"report.json").read_bytes(),before)
        body=json.loads(self.ap.read_bytes()); body["new_field"]="mutation"; self.write(self.ap,body)
        with self.assertRaisesRegex(ValueError,"frozen input modified"): self.run_eval()

    def test_maturity_without_new_daily_run_creates_new_supplement(self):
        self.write(self.hr/"history.json",history(end=A+4*e.STEP,received=A+5*e.STEP))
        first,report,_=self.run_eval(now=A+6*e.STEP)
        self.assertEqual(record(report,minutes=1440)["status"],"PENDING")
        second,later,reused=self.run_eval(now=A+DAY+2*e.STEP)
        self.assertFalse(reused); self.assertNotEqual(first,second)
        self.assertTrue((first/"report.json").exists())

    def test_new_history_without_daily_run_completes_old_outcomes(self):
        self.write(self.hr/"history.json",history(end=A+4*e.STEP,received=A+5*e.STEP))
        first,_,_=self.run_eval(now=A+6*e.STEP)
        other=self.root/"history_2"; other.mkdir()
        self.write(other/"history.json",history())
        second,report,reused=e.evaluate(self.local,[self.hr,other],self.out,_now_ms=A+DAY+e.STEP)
        self.assertFalse(reused); self.assertNotEqual(first,second)
        self.assertEqual(record(report,minutes=1440)["status"],"MATURE")

    def test_modified_supplement_not_reused(self):
        path,_,_=self.run_eval()
        (path/"summary.md").write_text("changed",encoding="utf-8")
        with self.assertRaises(ValueError): self.run_eval()

    def test_transient_windows_rename_keeps_atomic_publication(self):
        real=e.os.rename; calls=[]
        def transient(src,dst):
            calls.append(1)
            if len(calls)==1: raise PermissionError("invented transient handle")
            return real(src,dst)
        with patch.object(e.os,"rename",side_effect=transient),patch.object(e.time,"sleep"):
            path,_,_=self.run_eval()
        self.assertEqual(len(calls),2)
        self.assertTrue((path/"integrity.json").is_file())

    def test_note_path_cannot_read_arbitrary_analysis(self):
        n=note(bound=self.a)
        n["body"].pop("analysis_report_sha256")
        n["body"]["analysis_path"]=str(self.root/"not-read-account.env")
        self.write(self.local/"analyst_notes"/n["id"]/"note.json",n["body"])
        _,report,_=self.run_eval()
        self.assertEqual(record(report,"human_note")["anchor_ms"],A+e.STEP)

    def test_explicit_read_escape_and_output_original_folder_refused(self):
        with self.assertRaises(ValueError): e.read_json(self.ap,self.hr)
        with self.assertRaises(ValueError): e.evaluate(self.local,[self.hr],self.local/"analyst_notes"/"new",_now_ms=A+DAY+e.STEP)

    def test_supplement_cannot_be_written_into_old_daily_date_folder(self):
        with self.assertRaises(ValueError): e.evaluate(self.local,[self.hr],self.local/"2026-10-16"/"other",_now_ms=A+DAY+e.STEP)

    def test_future_analysis_identity_refused(self):
        with self.assertRaises(ValueError): self.run_eval(now=A-2)

    def test_original_daily_hash_binding_checked_on_first_admission(self):
        rp=self.local/self.a["body"]["input_run_id"]/"report.json"
        r=json.loads(rp.read_bytes()); r["modified"]=True; self.write(rp,r)
        with self.assertRaisesRegex(ValueError,"daily input SHA"): self.run_eval()

    def test_public_export_has_no_narrative_paths_or_CoinGlass(self):
        _,report,_=self.run_eval(); public=e.verification_export(report)
        raw=json.dumps(public)
        self.assertNotIn("input_run",raw); self.assertNotIn(str(self.local),raw)
        self.assertNotIn("source_issues",raw); self.assertNotIn("text_conditions",raw)
        self.assertFalse(public["raw_CoinGlass_included"])
        self.assertEqual(public["records"][0]["anchor_ms"],A)


if __name__=="__main__": unittest.main()
