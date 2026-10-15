"""Ревью GPT 15.10 (docs/WEEX_GPT_REVIEW_AND_MANUAL_STRATEGIES_2026-10-15.md §2 п.7): уже скачанный zip aggTrades
не сверялся с .CHECKSUM — искусственный битый кэш принимался, отчёт писал «контрольная сумма не сошлась: нет».

Поддельный загрузчик вместо data.binance.vision (сеть в этих тестах запрещена conftest'ом)."""
from __future__ import annotations

import hashlib
import sys
from datetime import date

import pytest

from tests.research_tools._util import load

SYM = "FAKEUSDT"
D1, D2 = date(2026, 8, 19), date(2026, 8, 20)
GOOD = {D1: b"PK\x03\x04 good zip day 1", D2: b"PK\x03\x04 good zip day 2"}
JUNK = b"PK\x03\x04 truncated"


def _name(d: date) -> str:
    return f"{SYM}-aggTrades-{d.isoformat()}.zip"


def _checksum(blob: bytes, name: str) -> bytes:
    return f"{hashlib.sha256(blob).hexdigest()}  {name}\n".encode()


class FakeServer:
    """url → bytes; отсутствующий url — ошибка, как у get() после ретраев. Журнал запросов — calls."""

    def __init__(self, fa, files: dict | None = None, checksums: dict | None = None):
        self.calls: list[str] = []
        self.data: dict[str, bytes] = {}
        for d, blob in (GOOD if files is None else files).items():
            self.data[f"{fa.BASE}/{SYM}/{_name(d)}"] = blob
        for d, blob in (GOOD if checksums is None else checksums).items():
            self.data[f"{fa.BASE}/{SYM}/{_name(d)}.CHECKSUM"] = blob if blob.endswith(b"\n") else _checksum(blob, _name(d))

    def __call__(self, url: str) -> bytes:
        self.calls.append(url)
        if url not in self.data:
            raise OSError(f"404 {url}")
        return self.data[url]


def _setup(tmp_path, monkeypatch, server_kw=None):
    fa = load("research/atlas_data/fetch_aggtrades_daily.py")
    monkeypatch.setattr(fa, "ROOT", tmp_path)
    srv = FakeServer(fa, **(server_kw or {}))
    monkeypatch.setattr(fa, "get", srv)
    out = tmp_path / "backtests" / "aggtrades" / SYM
    out.mkdir(parents=True)
    return fa, srv, out


def _run_main(fa, monkeypatch, capsys, a=D1, b=D2):
    monkeypatch.setattr(sys, "argv", ["fetch_aggtrades_daily.py", SYM, a.isoformat(), b.isoformat()])
    rc = fa.main()
    return rc, capsys.readouterr().out


def test_invalid_cached_zip_is_reported_and_not_kept(tmp_path, monkeypatch, capsys):
    fa, srv, out = _setup(tmp_path, monkeypatch)
    (out / _name(D1)).write_bytes(JUNK)                         # кэш дня 1 битый, дня 2 — целый
    (out / _name(D2)).write_bytes(GOOD[D2])
    rc, text = _run_main(fa, monkeypatch, capsys)
    assert (out / _name(D1)).read_bytes() == GOOD[D1], "битый кэш остался под рабочим именем"
    assert D1.isoformat() in text, f"битый кэш не попал в отчёт: {text!r}"
    assert (out / (_name(D1) + ".bad")).read_bytes() == JUNK   # отложен, не удалён
    assert rc == 0                                              # перекачан и сверен
    assert f"{fa.BASE}/{SYM}/{_name(D2)}" not in srv.calls      # целый кэш не качается заново
    assert f"{fa.BASE}/{SYM}/{_name(D2)}.CHECKSUM" in srv.calls # но сверяется


def test_invalid_cached_zip_with_bad_download_fails(tmp_path, monkeypatch, capsys):
    fa, _, out = _setup(tmp_path, monkeypatch, {"files": {D1: JUNK + b"x", D2: GOOD[D2]}})
    (out / _name(D1)).write_bytes(JUNK)
    rc, text = _run_main(fa, monkeypatch, capsys)
    assert rc == 1
    assert not (out / _name(D1)).exists()                       # ни битый кэш, ни битая загрузка не приняты
    assert "не сошлась: ['2026-08-19']" in text
    assert (out / _name(D2)).read_bytes() == GOOD[D2]


def test_fetch_day_statuses(tmp_path, monkeypatch):
    fa, srv, out = _setup(tmp_path, monkeypatch)
    assert fa.fetch_day(out, SYM, D1) == ("new", "")
    assert fa.fetch_day(out, SYM, D1) == ("ok", "")             # повторный запуск: кэш сверен
    (out / _name(D1)).write_bytes(JUNK)
    st, why = fa.fetch_day(out, SYM, D1)
    assert st == "refetched" and "не сошёлся" in why
    assert [p.name for p in out.iterdir() if p.name.endswith(".tmp")] == []


def test_new_download_mismatch_is_not_written(tmp_path, monkeypatch, capsys):
    fa, _, out = _setup(tmp_path, monkeypatch, {"checksums": {D1: JUNK, D2: GOOD[D2]}})
    rc, text = _run_main(fa, monkeypatch, capsys)
    assert rc == 1 and not (out / _name(D1)).exists()
    assert "не сошлась: ['2026-08-19']" in text


@pytest.mark.parametrize("checksum", [None, b"not-a-sha256  x\n", b""])
def test_cached_zip_without_valid_checksum_is_unverified_not_accepted(tmp_path, monkeypatch, capsys, checksum):
    sums = {D2: GOOD[D2]} if checksum is None else {D1: checksum or b"\n", D2: GOOD[D2]}
    fa, _, out = _setup(tmp_path, monkeypatch, {"checksums": sums})
    (out / _name(D1)).write_bytes(GOOD[D1])
    rc, text = _run_main(fa, monkeypatch, capsys)
    assert rc == 1 and "не проверено: ['2026-08-19']" in text
    assert (out / _name(D1)).read_bytes() == GOOD[D1]           # без сверки кэш не трогается


def test_checksum_of_another_archive_is_rejected(tmp_path, monkeypatch):
    other = _checksum(GOOD[D1], _name(D2))                      # верный hex, но имя чужого архива
    fa, _, out = _setup(tmp_path, monkeypatch, {"checksums": {D1: other, D2: GOOD[D2]}})
    st, _ = fa.fetch_day(out, SYM, D1)
    assert st == "unverified" and not (out / _name(D1)).exists()
