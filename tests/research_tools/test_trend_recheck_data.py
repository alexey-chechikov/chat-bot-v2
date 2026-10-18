"""Входные данные протокола docs/TREND_4H_RECHECK_PROTOCOL_2026-10-15.md §1: месячные архивы UM 1m
(research/trend_recheck/fetch_um_monthly.py) и ранний файл P1 со сверкой шва (research/trend_recheck/build_early.py).

Сеть запрещена conftest'ом: data.binance.vision — поддельный загрузчик, архивы — собранные в тесте zip."""
from __future__ import annotations

import hashlib
import json
import zipfile
from datetime import datetime, timezone

import pytest

from tests.research_tools._util import load

SYM = "FAKEUSDT"
MONTH = "2024-05"
NAME = f"{SYM}-1m-{MONTH}.zip"
CUT = 1715731200000                                   # 2024-05-15 00:00 UTC
HDR = "open_time,open,high,low,close,volume,close_time,quote_volume,count,taker_buy_volume,taker_buy_quote_volume,ignore"


def _ms(s: str) -> int:
    return int(datetime.fromisoformat(s).replace(tzinfo=timezone.utc).timestamp() * 1000)


def _kline(ts: int, o="100.00", h="101.00", lo="99.00", c="100.50", v="5.000", tb="2.000", n="7", unit=1) -> str:
    return f"{ts * unit},{o},{h},{lo},{c},{v},{(ts + 59_999) * unit if unit == 1 else ts * unit + 59_999_999},1.0,{n},{tb},1.0,0"


def _zip(path, lines: list[str], member: str | None = None) -> bytes:
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(member or path.name.replace(".zip", ".csv"), "\n".join(lines) + "\n")
    return path.read_bytes()


def _checksum(blob: bytes, name: str = NAME) -> bytes:
    return f"{hashlib.sha256(blob).hexdigest()}  {name}\n".encode()


# ---------------------------------------------------------------- fetch_um_monthly.fetch_month
class Server:
    def __init__(self, fm, zips: dict[str, bytes], sums: dict[str, bytes]):
        self.fm, self.calls = fm, []
        self.data = {f"{fm.BASE}/{SYM}/1m/{k}": v for k, v in zips.items()}
        self.data.update({f"{fm.BASE}/{SYM}/1m/{k}.CHECKSUM": v for k, v in sums.items()})

    def __call__(self, url: str):
        self.calls.append(url)
        return self.data.get(url)                         # None = 404, как http_get


@pytest.fixture
def fm():
    return load("research/trend_recheck/fetch_um_monthly.py")


def test_fetch_month_new_then_cached_is_verified_again(tmp_path, fm):
    good = _zip(tmp_path / NAME, [_kline(CUT)])
    (tmp_path / NAME).unlink()
    srv = Server(fm, {NAME: good}, {NAME: _checksum(good)})
    st, _, sha = fm.fetch_month(tmp_path, SYM, MONTH, getter=srv)
    assert st == "new" and sha == hashlib.sha256(good).hexdigest()
    assert (tmp_path / NAME).read_bytes() == good
    assert (tmp_path / f"{NAME}.CHECKSUM").read_bytes() == _checksum(good)   # сохранён для build_early
    srv.calls.clear()
    st, _, _ = fm.fetch_month(tmp_path, SYM, MONTH, getter=srv)
    assert st == "ok"
    assert srv.calls == [f"{fm.BASE}/{SYM}/1m/{NAME}.CHECKSUM"]               # кэш сверен, zip не качался


def test_bad_cache_is_quarantined_and_refetched(tmp_path, fm):
    good = _zip(tmp_path / NAME, [_kline(CUT)])
    (tmp_path / NAME).write_bytes(b"PK junk")
    srv = Server(fm, {NAME: good}, {NAME: _checksum(good)})
    st, why, _ = fm.fetch_month(tmp_path, SYM, MONTH, getter=srv)
    assert st == "refetched" and "не сошёлся" in why
    assert (tmp_path / NAME).read_bytes() == good
    assert (tmp_path / f"{NAME}.bad").read_bytes() == b"PK junk"


def test_still_bad_after_refetch_fails_and_writes_nothing(tmp_path, fm):
    good = _zip(tmp_path / NAME, [_kline(CUT)])
    (tmp_path / NAME).write_bytes(b"PK junk")
    srv = Server(fm, {NAME: b"PK other junk"}, {NAME: _checksum(good)})
    st, why, sha = fm.fetch_month(tmp_path, SYM, MONTH, getter=srv)
    assert st == "bad" and sha is None and "попытка 2" in why
    assert not (tmp_path / NAME).exists()
    assert sum(1 for u in srv.calls if u.endswith(".zip")) == 2


@pytest.mark.parametrize("checksum", [None, b"zzz  " + NAME.encode(), b"0" * 64 + b"  OTHER.zip"])
def test_unverified_checksum_is_not_accepted(tmp_path, fm, checksum):
    good = _zip(tmp_path / NAME, [_kline(CUT)])
    srv = Server(fm, {NAME: good}, {} if checksum is None else {NAME: checksum})
    st, _, sha = fm.fetch_month(tmp_path, SYM, MONTH, getter=srv)
    assert st == "unverified" and sha is None
    assert (tmp_path / NAME).read_bytes() == good                             # кэш не тронут


def test_month_range_and_prev(fm):
    assert fm.month_range("2023-11", "2024-02") == ["2023-11", "2023-12", "2024-01", "2024-02"]
    assert fm.prev_month("2020-01") == "2019-12"


# ---------------------------------------------------------------- build_early
@pytest.fixture
def be():
    return load("research/trend_recheck/build_early.py")


def _archive(tmp_path, lines, member=None, good_sum=True):
    d = tmp_path / "arch" / SYM
    d.mkdir(parents=True, exist_ok=True)
    blob = _zip(d / NAME, lines, member)
    (d / f"{NAME}.CHECKSUM").write_bytes(_checksum(blob if good_sum else blob + b"x"))
    return d / NAME


def test_header_and_headerless_archives_read_the_same(tmp_path, be):
    rows = [_kline(CUT), _kline(CUT + 60_000, o="7172", v="0.000")]
    no_hdr, st1 = be.read_archive(_archive(tmp_path, rows), SYM, MONTH)
    with_hdr, st2 = be.read_archive(_archive(tmp_path, [HDR, *rows]), SYM, MONTH)
    assert with_hdr == no_hdr and st2.get("header") == 1 and "header" not in st1
    assert with_hdr[0][1] == (str(CUT), "100.00", "101.00", "99.00", "100.50", "5.000", "2.000", "7")


def test_microsecond_open_time_is_refused(tmp_path, be):
    a = _archive(tmp_path, [_kline(CUT, unit=1000)])
    with pytest.raises(be.DataError, match="миллисекунд"):
        be.read_archive(a, SYM, MONTH)


def test_checksum_mismatch_and_foreign_member_are_refused(tmp_path, be):
    a = _archive(tmp_path, [_kline(CUT)], good_sum=False)
    with pytest.raises(be.DataError, match="sha256"):
        be.read_archive(a, SYM, MONTH)
    b = _archive(tmp_path, [_kline(CUT)], member="../evil.csv")
    with pytest.raises(be.DataError, match="состав архива"):
        be.read_archive(b, SYM, MONTH)


def test_outside_month_and_off_grid_rows_are_dropped(tmp_path, be):
    a = _archive(tmp_path, [_kline(_ms("2024-04-30 23:59")), _kline(CUT + 30_000), _kline(CUT)])
    rows, st = be.read_archive(a, SYM, MONTH)
    assert [t for t, _ in rows] == [CUT]
    assert st["outside_month"] == 1 and st["off_grid"] == 1 and st["unsorted"] == 0


def test_normalize_matches_existing_style(be):
    style = {c: {"decimals": d, "zero": z} for c, d, z in
             (("open", 2, "0.00"), ("high", 2, "0.00"), ("low", 2, "0.00"), ("close", 2, "0.00"),
              ("volume", 3, "0"), ("taker_buy", 3, "0"))}
    pad = be.Counter()
    r = be.normalize(("1", "7172", "7179.04", "7171.8", "7175.31", "0.000", "42", "9"), style, pad, "t")
    assert r == ("1", "7172.00", "7179.04", "7171.80", "7175.31", "0", "42.000", "9")
    assert pad == {"open": 1, "low": 1, "taker_buy": 1, "volume:zero": 1}
    with pytest.raises(be.DataError):
        be.normalize(("1", "7172.001", "1.00", "1.00", "1.00", "1.000", "1.000", "1"), style, pad, "t")
    with pytest.raises(be.DataError):
        be.normalize(("1", "1e3", "1.00", "1.00", "1.00", "1.000", "1.000", "1"), style, pad, "t")


def _setup_build(tmp_path, monkeypatch, be, arch_lines, existing_lines):
    frozen, out = tmp_path / "frozen", tmp_path / "out"
    frozen.mkdir()
    out.mkdir()
    _archive(tmp_path, arch_lines)
    monkeypatch.setattr(be, "ARCH", tmp_path / "arch")
    monkeypatch.setattr(be, "FROZEN", frozen)
    monkeypatch.setattr(be, "OUT", out)
    monkeypatch.setattr(be, "ROOT", tmp_path)
    (out / "um_monthly_fetch.json").write_text(json.dumps(
        {"symbols": {SYM: {"per_month": {MONTH: {"status": "new"}}}}}))
    (frozen / f"{SYM}_UM_1m.csv").write_bytes(
        ("ts,open,high,low,close,volume,taker_buy,trades\r\n" + "".join(x + "\r\n" for x in existing_lines)).encode())
    return frozen, out


def _existing(ts, o="100.00", v="5.000"):
    return f"{ts},{o},101.00,99.00,100.50,{v},2.000,7"


def test_build_writes_crlf_counts_gap_and_seam_ok(tmp_path, monkeypatch, be):
    t = CUT - 4 * 60_000                                             # 23:56, 23:57, [23:58 нет], 23:59 + дубль
    arch = [_kline(t), _kline(t + 60_000, o="100"), _kline(t + 3 * 60_000), _kline(t + 3 * 60_000),
            _kline(CUT), _kline(CUT + 60_000, v="0.000", tb="0.000")]
    frozen, out = _setup_build(tmp_path, monkeypatch, be, arch,
                               [_existing(CUT), _existing(CUT + 60_000, v="0").replace(",2.000,", ",0,")])
    rep, code = be.build(SYM)
    raw = (frozen / f"{SYM}_UM_1m_early.csv").read_bytes()
    assert raw.startswith(b"ts,open,high,low,close,volume,taker_buy,trades\r\n")
    lines = raw.decode().split("\r\n")
    assert lines[2] == f"{t + 60_000},100.00,101.00,99.00,100.50,5.000,2.000,7"     # «100» → «100.00»
    assert rep["rows"] == 3 and rep["missing_minutes"] == 1 and rep["duplicates_identical_dropped"] == 1
    assert rep["largest_gaps"][0]["minutes"] == 1
    assert rep["seam"]["identical"] == 2 and rep["seam"]["ok"] and code == 0
    assert rep["sha256"] == hashlib.sha256(raw).hexdigest()


def test_build_seam_mismatch_is_loud(tmp_path, monkeypatch, be):
    arch = [_kline(CUT - 60_000), _kline(CUT), _kline(CUT + 60_000)]
    frozen, _ = _setup_build(tmp_path, monkeypatch, be, arch, [_existing(CUT), _existing(CUT + 60_000, o="100.01")])
    before = (frozen / f"{SYM}_UM_1m.csv").read_bytes()
    rep, code = be.build(SYM)
    assert code == 3 and not rep["seam"]["ok"]
    assert rep["seam"]["different"] == 1 and rep["seam"]["different_by_field"] == {"open": 1}
    assert rep["seam"]["max_abs_diff"]["open"] == pytest.approx(0.01)
    assert (frozen / f"{SYM}_UM_1m.csv").read_bytes() == before                 # существующий файл не тронут


def test_build_conflicting_duplicate_refuses(tmp_path, monkeypatch, be):
    arch = [_kline(CUT - 60_000), _kline(CUT - 60_000, c="100.60")]
    frozen, _ = _setup_build(tmp_path, monkeypatch, be, arch, [_existing(CUT)])
    with pytest.raises(be.DataError, match="конфликтующий дубль"):
        be.build(SYM)
    assert not (frozen / f"{SYM}_UM_1m_early.csv").exists()
    assert not [p for p in frozen.iterdir() if p.name.endswith(".tmp")]
