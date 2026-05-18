"""Generic paper-signal tracker: каждый TG-эмиттер пишет hypothetical
paper-trade при emit. Outcome evaluator закрывает по TP/SL/timeout
на 1m данных. Weekly aggregator → per-source PnL/win-rate отчёт.

Usage from emitter:
    from services.paper_signal_tracker.journal import record_paper_signal
    record_paper_signal(
        source="cascade_alert", side="LONG", entry=80000.0,
        stop_pct=-0.5, tp_pct=0.75, hold_h=4, context="long_liq_5btc",
    )

Outcome evaluator runs as async loop in app_runner, ticks каждые 5 мин.
"""
