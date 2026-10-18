"""Дополнение §7а протокола docs/TREND_4H_RECHECK_PROTOCOL_2026-10-15.md: ряд XRP с днями из дневных архивов
(research/trend_recheck/xrp_fill.py) — только в памяти, вставка только в дыры, архив сверяется с .CHECKSUM, соседний
день дневного архива обязан совпасть с минутами из месячных архивов. Архивы — синтетические, во временной папке."""
import hashlib
import io
import zipfile

import numpy as np
import pytest

from tests.research_trend.tr_fx import _load

xf = _load("tr_xrp_fill", "xrp_fill.py")

SYM = "XRPUSDT"
MIN = 60_000
DAY = 86_400_000
D24 = xf.day_ms("2022-02-24")
FILL, CHECK = "2022-02-26", "2022-02-25"


def _px(ts: np.ndarray) -> np.ndarray:
    return 0.7 + (ts // MIN % 1000) * 1e-4


def _as_written(x: np.ndarray) -> np.ndarray:
    return np.array([float(f"{v:.4f}") for v in x])                       # как число после записи в CSV


def _minutes(hole: bool = True) -> dict:
    ts = D24 + np.arange(5 * 1440, dtype=np.int64) * MIN                   # 2022-02-24 … 02-28
    if hole:
        ts = ts[(ts < xf.day_ms(FILL)) | (ts >= xf.day_ms(FILL) + DAY)]
    p = _px(ts)
    return {"ts": ts, "o": _as_written(p), "h": _as_written(p + 1e-4), "l": _as_written(p - 1e-4),
            "c": _as_written(p), "v": np.ones(len(ts)), "p1_rows": len(ts), "p2_rows": 0}


def _write_day(root, day: str, n: int = 1440, shift: float = 0.0, bad_sum: bool = False) -> None:
    a = xf.day_ms(day)
    ts = a + np.arange(n, dtype=np.int64) * MIN
    p = _px(ts) + shift
    buf = io.StringIO()
    buf.write("open_time,open,high,low,close,volume,close_time,quote_volume,count,taker_buy_volume,"
              "taker_buy_quote_volume,ignore\n")
    for t, x in zip(ts, p):
        buf.write(f"{t},{x:.4f},{x + 1e-4:.4f},{x - 1e-4:.4f},{x:.4f},1.0,{t + MIN - 1},0.7,3,0.5,0.35,0\n")
    name = f"{SYM}-1m-{day}"
    zb = io.BytesIO()
    with zipfile.ZipFile(zb, "w") as z:
        z.writestr(f"{name}.csv", buf.getvalue())
    blob = zb.getvalue()
    d = root / SYM
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.zip").write_bytes(blob)
    sha = hashlib.sha256(blob + (b"x" if bad_sum else b"")).hexdigest()
    (d / f"{name}.zip.CHECKSUM").write_text(f"{sha}  {name}.zip\n")


def _fill(m, root):
    return xf.fill(m, days=(FILL,), check_days=(CHECK,), root=root, fetch_report=None)


def test_fill_inserts_only_into_hole(tmp_path):
    _write_day(tmp_path, FILL)
    _write_day(tmp_path, CHECK)
    m = _minutes()
    out, rep = _fill(m, tmp_path)
    full = _minutes(hole=False)
    assert np.array_equal(out["ts"], full["ts"]) and np.allclose(out["c"], full["c"])
    assert rep["inserted_minutes"] == 1440 and rep["p1_missing_after"] == 0
    assert rep["check_vs_monthly"][CHECK]["numeric_equal_ohlcv"] == 1440
    assert len(m["ts"]) == 4 * 1440                                        # исходный ряд не изменён


def test_fill_refuses_when_day_is_not_a_hole(tmp_path):
    _write_day(tmp_path, FILL)
    _write_day(tmp_path, CHECK)
    with pytest.raises(xf.DataError):
        _fill(_minutes(hole=False), tmp_path)


def test_fill_refuses_on_checksum_mismatch(tmp_path):
    _write_day(tmp_path, FILL, bad_sum=True)
    _write_day(tmp_path, CHECK)
    with pytest.raises(xf.DataError):
        _fill(_minutes(), tmp_path)


def test_fill_refuses_when_check_day_disagrees_with_monthly(tmp_path):
    _write_day(tmp_path, FILL)
    _write_day(tmp_path, CHECK, shift=0.0001)
    with pytest.raises(xf.DataError):
        _fill(_minutes(), tmp_path)


def test_fill_refuses_short_day(tmp_path):
    _write_day(tmp_path, FILL, n=1439)
    _write_day(tmp_path, CHECK)
    with pytest.raises(xf.DataError):
        _fill(_minutes(), tmp_path)
