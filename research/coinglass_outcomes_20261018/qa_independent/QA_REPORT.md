# Independent Codex QA — synthetic inputs only

Checked `evaluator.py` and its integration with `history_fetch.collect` against IMPLEMENTATION_CONTRACT.md. No production module, private state, real archive, network client or market dataset was used. No root implementation file was edited by this reviewer.

Four integrity issues identified during review were corrected by the implementation author and then covered by independent regression tests:

1. Extended history must verify actual symbol/interval/settings and URL query, rather than relying only on the supplied legacy semantic label.
2. Frozen analysis semantic objects must agree with their recorded hashes; matching a stale hash alone is insufficient.
3. Optional flow revisions must not create a false conflict in unchanged OHLC. Contradictory valid flow remains unavailable/CONFLICT independently of MATURE price.
4. First admission must verify the frozen analysis input_run/history-input identities, byte hashes and archive times against the actual admitted daily report files. An empty previous-supplement cache must not permit a modified or future input to enter.

A final integration check also required the failed-clock history bundle to be explicitly non-admitted. The bundle remains usable as failure evidence, with no MATURE price result and no invented zero price.

Final independent result: **15 tests passed, 0 failures/errors, 0 real network requests, 0 real archive reads**. `QA_RESULTS.json` records actual test time, detailed output and exact source SHA256. These are independent tests in this folder; add them to the author's focused suite count, do not count this review as a real-data success.

The ordinary collector integration uses the real new collection function with a memory FakeClient: six simulated public GETs, twelve invented evidence objects, both spot/perpetual paths MATURE at all four horizons, independently known open100/close101/return1%, and exact OI endpoint context. The failed-clock integration makes one simulated GET and admits no price history. No socket is opened.

Filesystem tests create only invented daily reports, analysis reports, public history and supplements under the new helper's `local/test_temp` directory. Before recursive temporary cleanup, the resolved absolute target is checked to remain strictly inside that test base. Original daily files, pilot database, analyst notes and bots remain untouched.

Reproduce:

```text
python -X utf8 -B research/coinglass_outcomes_20261018/qa_independent/run_qa.py
```

The evaluator implements numerical path supplements; this review does not validate any market hypothesis, trading edge or profitability. Activation and external independent reading remain separate from synthetic QA.
