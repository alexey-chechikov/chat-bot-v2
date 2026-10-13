"""Запись стакана/сделок WEEX: снимок + изменения по номерам, пропуск → переподписка, дубли сделок не пишутся."""
import asyncio
import csv
import json

from services.weex_book import recorder as rc

E0 = 1_791_700_000_000


def snap(u=10, b=(("100.0", "2"),), a=(("100.1", "3"),)):
    return {"e": "depthSnapshot", "E": E0, "s": "BTCUSDT", "U": u - 5, "u": u, "d": "SNAPSHOT", "b": list(b), "a": list(a)}


def chg(U, u, b=(), a=(), E=E0 + 500):
    return {"e": "depth", "E": E, "s": "BTCUSDT", "U": U, "u": u, "d": "CHANGED", "b": list(b), "a": list(a)}


def test_book_sequence_and_gap():
    bk = rc.Book()
    bk.snapshot(snap())
    assert bk.change(chg(10, 12, b=[("100.0", "0"), ("99.9", "1")]))
    assert bk.top(1) == (99.9, 1.0, 100.1, 3.0)
    assert not bk.change(chg(13, 14))                   # U != последнему u — пропуск
    assert not bk.ok


class FakeWS:
    def __init__(self, msgs, stop):
        self.msgs, self.stop, self.sent = list(msgs), stop, []

    async def send(self, s):
        self.sent.append(json.loads(s))

    async def recv(self):
        if not self.msgs:
            self.stop.set()
            return json.dumps({"event": "ping", "time": "0"})
        return json.dumps(self.msgs.pop(0))


def run_session(tmp_path, msgs):
    stop = asyncio.Event()
    ws = FakeWS(msgs, stop)
    w = rc.Writer(tmp_path)
    asyncio.run(rc._session(ws, ("BTCUSDT",), w, stop))
    w.close()
    return ws


def rows(tmp_path, kind):
    f = next(tmp_path.glob(f"BTCUSDT_*_{kind}.csv"))
    return list(csv.reader(f.open()))[1:]


def test_session_writes_book_on_change_and_dedups_trades(tmp_path):
    t = {"T": E0 + 100, "t": "id1", "p": "100.1", "q": "0.01", "m": False}
    msgs = [chg(1, 2),                                   # до снимка — пропускается
            snap(), chg(10, 11), chg(11, 12, b=[("100.0", "5")]),
            {"e": "tradeSnapshot", "E": E0, "s": "BTCUSDT", "d": [t]},
            {"e": "trade", "E": E0 + 200, "s": "BTCUSDT", "d": [t, {**t, "t": "id2", "m": True}]}]
    ws = run_session(tmp_path, msgs)
    book = rows(tmp_path, "book")
    assert len(book) == 2                                # снимок + одно реальное изменение верха
    assert float(book[-1][2]) == 5.0
    tr = rows(tmp_path, "trades")
    assert [r[4] for r in tr] == ["1"]                   # id1 был в снимке, записан только id2
    assert ws.sent[-1] == {"method": "PONG", "id": 1}


def test_gap_triggers_resubscribe(tmp_path):
    ws = run_session(tmp_path, [snap(), chg(10, 11), chg(20, 21)])
    rc_time = [m for m in ws.sent if m.get("method") in ("UNSUBSCRIBE", "SUBSCRIBE")]
    assert rc_time[-2]["method"] == "UNSUBSCRIBE" and rc_time[-1]["params"] == ["BTCUSDT@depth15"]


def test_v2_depth_trades_events_written(tmp_path):
    """P0 13.10: все уровни и номера обновлений в depth, ID сделки и исходное m в trades2, разрыв — в events."""
    t = {"T": E0 + 100, "t": "id9", "p": "100.1", "q": "0.01", "m": True}
    many = [(f"{100 - i / 10:.1f}", "1") for i in range(15)]
    run_session(tmp_path, [snap(b=many), chg(10, 11, a=[("100.2", "4")]),
                           {"e": "trade", "E": E0 + 200, "s": "BTCUSDT", "d": [t]}, chg(20, 21)])
    dep = rows(tmp_path, "depth")
    assert dep[0][0] == "snapshot" and len(json.loads(dep[0][7])) == 15 and dep[0][6] == "1"
    assert dep[1][:3] == ["delta", "10", "11"] and dep[1][6] == "1" and dep[1][4]
    assert dep[2][:3] == ["delta", "20", "21"] and dep[2][6] == "0"      # разрыв не применён
    tr2 = rows(tmp_path, "trades2")
    assert tr2[0][0] == "id9" and tr2[0][7] == "True" and tr2[0][3]       # ID сделки, m как пришло, recv_ms
    ev = [r[2] for r in rows(tmp_path, "events")]
    assert ev[:2] == ["connect", "snapshot"] and "gap" in ev and "resync" in ev
