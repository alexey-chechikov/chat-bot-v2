"""Ревью GPT 13.10 §6: tools/ginarea_regime_check.py — ключ пропуска = точные концы отрезка UTC (мс) + символ +
сторона + sha256 полного ЭФФЕКТИВНОГО конфига, поставленного боту + sha256 данных режима; старые записи без этих
полей не переиспользуются; so/ioo записываются, ненулевые — предупреждение; значимые параметры сверяются после
установки. GinArea не вызывается: API и бэктест поддельные, работает настоящий gts.set_config / run_one."""
from __future__ import annotations

import hashlib
import json
import types
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from services.ginarea_api.models import DefaultGridParams
from tests.research_tools._util import load

BASE = {"gs": 0.4, "gsr": None, "maxOp": 400, "side": 2, "obap": True,
        "gap": {"isg": 0.1, "tog": 0.3, "minS": None, "maxS": None},
        "q": {"minQ": 0.002, "maxQ": 0.01, "qr": 1.2}, "border": {"bottom": None, "top": None},
        "so": 0.4, "ioo": 0.06, "s": 2}
A = datetime(2026, 10, 1, tzinfo=timezone.utc)
B8 = datetime(2026, 10, 13, 8, tzinfo=timezone.utc)
B12 = datetime(2026, 10, 13, 12, tzinfo=timezone.utc)


class FakeApi:
    def __init__(self, drop_on_readback: str | None = None):
        self.params = DefaultGridParams.from_dict(BASE)
        self.drop = drop_on_readback

    def set_params(self, bot, p):
        self.params = p

    def get_params(self, bot):
        if not self.drop:
            return self.params
        d = self.params.to_dict()
        d[self.drop] = None                                   # GinArea «не приняла» параметр
        return DefaultGridParams.from_dict(d)


class FakeBt:
    def __init__(self, api: FakeApi):
        self.api = api
        self.runs: list = []

    def list_tests(self, bot):
        return []

    def run_test(self, bot, a, b, poll_interval=None, timeout=None):
        self.runs.append((a, b))
        stat = types.SimpleNamespace(profit=1.0, currentProfit=2.0, tradeVolume=3.0, position=0.0)
        return types.SimpleNamespace(id=len(self.runs), status=types.SimpleNamespace(name="FINISHED"),
                                     params=self.api.params, stat=stat, statHistory=[])


def _dc(shift: float = 0.0) -> pd.Series:
    idx = pd.date_range("2025-06-01", "2026-10-13", freq="D", tz="UTC")
    return pd.Series(100.0 + np.arange(len(idx)) * 0.1 + shift, index=idx)


@pytest.fixture
def env(tmp_path, monkeypatch):
    mod = load("tools/ginarea_regime_check.py")
    gts = mod.gts
    api = FakeApi()
    bt = FakeBt(api)
    out = tmp_path / "regime.jsonl"
    monkeypatch.setattr(mod, "OUT", out)
    monkeypatch.setattr(gts, "PAUSE", 0.0)
    monkeypatch.setattr(gts, "ARCHIVE", tmp_path / "archive.jsonl")
    monkeypatch.setattr(gts, "_api", lambda bots: (api, bt))
    monkeypatch.setattr(gts, "_base", lambda a, bot: DefaultGridParams.from_dict(BASE))
    state = {"segs": [(True, A, B8)], "dc": _dc()}
    monkeypatch.setattr(mod, "segments", lambda *a, **k: list(state["segs"]))
    monkeypatch.setattr(mod, "daily_closes", lambda *a, **k: state["dc"], raising=False)
    return types.SimpleNamespace(mod=mod, api=api, bt=bt, out=out, state=state, monkeypatch=monkeypatch)


def _records(out) -> list[dict]:
    return [json.loads(x) for x in out.read_text(encoding="utf-8").splitlines()]


def test_old_records_without_hashes_not_reused(env):
    old = [{"gs": 0.6, "target": 1.4, "from": "2026-10-01", "to": "2026-10-13", "side": s, "current_profit": 5.0}
           for s in (1, 2)]
    env.out.write_text("".join(json.dumps(r) + "\n" for r in old), encoding="utf-8")
    env.mod.main()
    assert len(env.bt.runs) == 2, "старая запись по датам переиспользована"


def test_intraday_end_change_reruns_exact_key_reused(env):
    env.mod.main()
    assert len(env.bt.runs) == 2                              # режим + наоборот
    env.state["segs"] = [(True, A, B12)]                      # тот же день, конец 12:00 вместо 08:00
    env.mod.main()
    assert len(env.bt.runs) == 4, "другой час конца отрезка дал тот же ключ"
    env.mod.main()
    assert len(env.bt.runs) == 4                              # полностью совпавший ключ — пропуск


def test_spec_change_reruns(env):
    env.mod.main()
    env.monkeypatch.setattr(env.mod, "SPEC", env.mod.SPEC.replace("maxOp=50", "maxOp=60"))
    env.mod.main()
    assert len(env.bt.runs) == 4, "смена SPEC (maxOp) взяла старый результат"


def test_data_change_reruns(env):
    env.mod.main()
    env.state["dc"] = _dc(shift=0.5)
    env.mod.main()
    assert len(env.bt.runs) == 4, "другие данные режима взяли старый результат"


def test_record_has_key_fields_and_effective_so_ioo(env, capsys):
    env.mod.main()
    recs = _records(env.out)
    assert len(recs) == 2
    for r in recs:
        need = {"symbol", "from_ms", "to_ms", "config", "config_sha256", "data_sha256", "so", "ioo"}
        assert need <= r.keys(), f"в записи нет полей ключа: {sorted(need - r.keys())}"
        assert r["symbol"] == "BTCUSDT"
        assert (r["from_ms"], r["to_ms"]) == (int(A.timestamp() * 1000), int(B8.timestamp() * 1000))
        cfg = r["config"]
        canon = json.dumps(cfg, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        assert r["config_sha256"] == hashlib.sha256(canon.encode()).hexdigest()
        assert len(r["data_sha256"]) == 64
        assert (cfg["gs"], cfg["gap"]["tog"], cfg["maxOp"], cfg["side"]) == (0.6, 1.4, 50, r["side"])
        assert (r["so"], r["ioo"]) == (0.4, 0.06) == (cfg["so"], cfg["ioo"])
    assert {r["side"] for r in recs} == {1, 2}
    assert "so=0.4" in capsys.readouterr().out                # ненулевые so/ioo унаследованы — предупреждение


def test_explicit_zero_so_ioo_recorded_without_warning(env, capsys):
    env.monkeypatch.setattr(env.mod, "SPEC", env.mod.SPEC + ",so=0,ioo=0")
    env.mod.main()
    recs = _records(env.out)
    assert [(r["so"], r["ioo"]) for r in recs] == [(0, 0), (0, 0)]
    out = capsys.readouterr().out
    assert "so=0 ioo=0" in out and "ВНИМАНИЕ" not in out


def test_readback_mismatch_of_significant_param_stops(env):
    env.api.drop = "so"
    with pytest.raises(SystemExit):
        env.mod.main()
    assert env.bt.runs == [], "тест запущен с непроверенным конфигом"
