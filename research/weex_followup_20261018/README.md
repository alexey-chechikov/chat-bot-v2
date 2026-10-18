# WEEX follow-up offline audit at 2959c7a

See [REPORT.md](REPORT.md) for verified fixes, remaining counterexamples and limitations of the starting comparison snapshot.

Run from any directory with standard Python 3.11+:

```text
python -X utf8 -B path/to/research/weex_followup_20261018/audit_followup_offline.py
```

The installed runtime used for the recorded run was `C:\Users\Kemper\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe`. No extra packages are required. It checks all six inert source files against VERIFIED_SOURCES.json before selecting methods from their AST. It never imports production modules, reads live configuration/state or calls a network client. Every order, fee, time, balance assumption and state in the harness is synthetic.

`results.json` contains ten scenarios. A successful run includes reproduction of remaining bad behaviour; this is not approval of the strategy or certification of the live system. `SOURCE_PINS.json` records the exact public GitHub paths and Git object identities. `VERIFIED_SOURCES.json` additionally pins SHA256. `BUNDLE_SHA256.json` pins the complete audit package excluding itself.
