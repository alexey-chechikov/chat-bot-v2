"""Одна неудача чтения — не тревога.

10.09: за неделю 197 записей HALT «API недоступен», в каждой список
остановленных пустой — служба объявляла тревогу и ничего не делала,
потому что API был недоступен и для остановки тоже. Это шум, который
маскирует настоящий отказ.
"""
from services.risk_guard.loop import evaluate

ERR = {"error": "GinAreaServerError: ", "rows": []}
CFG = {"deposit_usd": 2160.92, "kill_pct": 10, "warn_pct": 5}


def test_single_failure_is_not_halt():
    d = evaluate(ERR, CFG, api_fails=1)
    assert d["action"] == "NONE"
    assert "1/3" in d["reason"]


def test_second_failure_still_not_halt():
    assert evaluate(ERR, CFG, api_fails=2)["action"] == "NONE"


def test_third_consecutive_failure_halts():
    d = evaluate(ERR, CFG, api_fails=3)
    assert d["action"] == "HALT"
    assert "3 раз подряд" in d["reason"]


def test_streak_threshold_is_configurable():
    cfg = {**CFG, "api_fail_streak": 5}
    assert evaluate(ERR, cfg, api_fails=4)["action"] == "NONE"
    assert evaluate(ERR, cfg, api_fails=5)["action"] == "HALT"


def test_default_api_fails_zero_does_not_halt():
    """Вызов без счётчика не должен молча превращаться в тревогу."""
    assert evaluate(ERR, CFG)["action"] == "NONE"
