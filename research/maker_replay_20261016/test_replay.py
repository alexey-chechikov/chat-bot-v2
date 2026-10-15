import unittest

from replay import Engine


def frame(seq, ms, raw=None):
    return {"seq": seq, "ms": ms, "raw": raw or {"event": "noop"}}


def book(seq, ms, bid=100, ask=100.01, qty=10, U=1, u=2, snapshot=False):
    return frame(seq, ms, {"e": "depthSnapshot" if snapshot else "depth", "s": "ETHUSDT", "U": U, "u": u,
                           "b": [[str(bid), str(qty)]], "a": [[str(ask), str(qty)]]})


def trades(seq, ms, rows, snapshot=False):
    return frame(seq, ms, {"e": "tradeSnapshot" if snapshot else "trade", "s": "ETHUSDT", "d": [
        {"t": tid, "T": ms - 50, "p": str(price), "q": str(qty), "m": maker}
        for tid, price, qty, maker in rows]})


def initialized(delay=100, queue=0, end=10000):
    engine = Engine(end, delay_ms=delay, queue_factor=queue, min_levels=1, quote_usd=100)
    engine.frame(book(1, 0, snapshot=True, u=1))
    return engine


class CausalReplayTests(unittest.TestCase):
    def test_stale_noop_frame_triggers_risk_without_new_book(self):
        e = initialized()
        e.frame(trades(2, 200, [("entry", 100, 1, True)]))
        e.frame(frame(3, 1501))
        self.assertEqual(e.position, 1)
        self.assertFalse(e.fresh())
        self.assertTrue(e.liquidating)
        self.assertTrue(e.episode["coverage_uncertain"])

    def test_first_late_fill_already_below_stop_never_submits_tp(self):
        e = initialized()
        e.frame(frame(2, 150, {"e": "depth", "s": "ETHUSDT", "U": 1, "u": 2,
                             "b": [["100", "0"], ["99", "10"]],
                             "a": [["100.01", "0"], ["99.01", "10"]]}))
        e.frame(trades(3, 200, [("late_entry", 100, 1, True)]))
        self.assertEqual(e.position, 1)
        self.assertTrue(e.liquidating)
        self.assertTrue(any(x["event"] == "liquidation_trigger" and x["reason"] == "stop" for x in e.ledger))
        self.assertFalse(any(x["event"] == "submit" and x["kind"] == "exit" for x in e.ledger))

    def test_stale_risk_exit_without_price_retains_unresolved_inventory(self):
        e = initialized()
        e.frame(trades(2, 200, [("entry", 100, 1, True)]))
        e.frame(frame(3, 1501))
        e.frame(frame(4, 1900))
        self.assertEqual(e.position, 1)
        self.assertTrue(e.liquidating)
        self.assertTrue(e.episode["unresolved"])
        self.assertTrue(any(x["event"] == "forced_exit_unresolved" for x in e.ledger))

    def test_same_time_frame_precedes_virtual_ack(self):
        e = initialized()
        e.frame(trades(2, 100, [("same_clock_tick", 100, 1, True)]))
        self.assertEqual(e.position, 0)
        e.frame(trades(3, 200, [("later_frame", 100, 1, True)]))
        self.assertEqual(e.position, 1)

    def test_no_fill_before_virtual_ack(self):
        e = initialized()
        e.frame(trades(2, 50, [("early", 100, 1, True)]))
        e.frame(frame(3, 150))
        self.assertEqual(e.position, 0)
        e.frame(trades(4, 200, [("after", 100, 1, True)]))
        self.assertAlmostEqual(e.position, 1)
        self.assertTrue(e.fills[0]["receipt_after_virtual_ack_only"])

    def test_frame_is_atomic_even_with_zero_scenario_delay(self):
        e = initialized(delay=0)
        e.frame(frame(2, 50))
        e.frame(trades(3, 100, [("sell", 100, 1, True), ("buy", 100.08, 1, False)]))
        self.assertEqual(len(e.fills), 1)
        self.assertEqual(e.position, 1)
        self.assertEqual(e.order.kind, "exit")

    def test_l2_shrink_grants_no_queue_credit(self):
        e = initialized(queue=1)
        e.frame(frame(2, 150))
        self.assertEqual(e.order.queue, 10)
        e.frame(book(3, 170, qty=1, U=1, u=2))
        e.frame(trades(4, 200, [("one", 100, 1, True)]))
        self.assertEqual(e.position, 0)
        self.assertEqual(e.order.queue, 9)

    def test_batch_volume_consumed_once_and_partial_retained(self):
        e = initialized()
        e.frame(frame(2, 150))
        e.frame(trades(3, 200, [("a", 100, .4, True), ("b", 100, .4, True)]))
        self.assertAlmostEqual(e.position, .8)
        self.assertEqual(len(e.fills), 1)
        self.assertAlmostEqual(e.order.remaining, .2)
        self.assertTrue(e.order.cancel_pending)

    def test_cancel_request_is_not_terminal_late_fill_counts(self):
        e = initialized(delay=500)
        e.frame(book(2, 900, U=1, u=2))
        e.frame(trades(3, 1100, [("first", 100, .4, True)]))
        e.frame(trades(4, 1400, [("late", 100, .3, True)]))
        self.assertAlmostEqual(e.position, .7)
        e.frame(frame(5, 1700))
        e.frame(trades(6, 1800, [("too_late", 100, .3, True)]))
        self.assertAlmostEqual(e.position, .7)
        self.assertEqual(e.order.kind, "exit")
        self.assertEqual(sum(x["event"] == "virtual_cancel_ack" for x in e.ledger), 1)

    def test_unknown_price_queue_is_not_zero_even_optimistic(self):
        e = initialized(queue=0)
        e.frame(trades(2, 200, [("entry", 100, 1, True)]))
        e.frame(frame(3, 350))
        self.assertIsNone(e.order.queue)
        e.frame(trades(4, 400, [("target", 100.08, 10, False)]))
        self.assertEqual(e.position, 1)
        self.assertEqual(e.episode["unknown_queue_orders"], 1)

    def test_snapshot_is_bootstrap_not_new_flow_and_dedup_is_forward(self):
        e = initialized()
        e.frame(trades(2, 150, [("old", 100, 2, True)], snapshot=True))
        e.frame(trades(3, 200, [("old", 100, 2, True)]))
        self.assertEqual(e.position, 0)
        e.frame(trades(4, 250, [("new", 100, .3, True)]))
        e.frame(trades(5, 300, [("new", 100, .3, True)], snapshot=True))
        self.assertAlmostEqual(e.position, .3)

    def test_gap_retains_inventory_and_incomplete_cost(self):
        e = initialized(end=2000)
        e.frame(trades(2, 200, [("entry", 100, 1, True)]))
        e.frame(book(3, 400, U=999, u=1000))
        e.frame(frame(4, 700))
        self.assertEqual(e.position, 1)
        e.finish()
        self.assertTrue(e.episodes[-1]["unresolved"])
        self.assertIsNone(e.episodes[-1]["scenario_cost_per_M"])

    def test_boundary_cancels_before_taker_walk_and_does_not_exit_at_mid(self):
        e = initialized(end=2000)
        e.frame(trades(2, 200, [("entry", 100, 1, True)]))
        e.frame(book(3, 1700, U=1, u=2))
        e.frame(frame(4, 2000))
        e.finish()
        self.assertEqual(e.position, 0)
        self.assertEqual(e.fills[-1]["price"], 100)
        self.assertEqual(e.fills[-1]["liquidity"], "forced_taker")
        self.assertAlmostEqual(e.episodes[0]["scenario_cost_per_M"], 100)
        self.assertTrue(e.episodes[0]["truncated"])
        self.assertIsNone(e.fills[0]["received_mid_markout_30s_bp"])
        cancel_ack = next(x for x in e.ledger if x["event"] == "virtual_cancel_ack")
        exit_fill = next(x for x in e.ledger if x["event"] == "fill" and x["side"] == "sell")
        self.assertLess(cancel_ack["ms"], exit_fill["ms"])

    def test_stop_trigger_during_cancel_keeps_exposure_until_exit(self):
        e = initialized(delay=500, end=3000)
        e.frame(trades(2, 600, [("partial", 100, .4, True)]))
        # Replace old bid rather than leave the 100 bid in the incremental book.
        raw = {"e": "depth", "s": "ETHUSDT", "U": 1, "u": 2,
               "b": [["100", "0"], ["99", "10"]], "a": [["100.01", "0"], ["99.01", "10"]]}
        e.frame(frame(3, 700, raw))
        e.frame(frame(4, 1000))
        self.assertAlmostEqual(e.position, .4)
        self.assertTrue(any(x["event"] == "liquidation_trigger" and x["reason"] == "stop" for x in e.ledger))
        e.frame(book(5, 1550, bid=99, ask=99.01, U=2, u=3))
        e.frame(frame(6, 1700))
        self.assertEqual(e.position, 0)
        self.assertGreaterEqual(e.fills[-1]["ms"], 1600)

    def test_insufficient_depth_blocks_entry(self):
        e = Engine(5000, min_levels=15)
        e.frame(book(1, 0, snapshot=True, u=1))
        self.assertIsNone(e.order)
        self.assertEqual(e.coverage["invalid_depth_frames"], 1)

    def test_stale_arrival_rejected(self):
        e = initialized(delay=1001, end=5000)
        e.frame(frame(2, 1200))
        self.assertEqual(e.position, 0)
        self.assertTrue(any(x["event"] == "postonly_reject" for x in e.ledger))

    def test_price_becomes_marketable_before_arrival_rejected(self):
        e = initialized()
        e.frame(frame(2, 50, {"e": "depth", "s": "ETHUSDT", "U": 1, "u": 2,
                            "b": [["100", "0"], ["99.9", "10"]],
                            "a": [["100.01", "0"], ["99.95", "10"]]}))
        e.frame(frame(3, 150))
        self.assertEqual(e.position, 0)
        self.assertTrue(any(x["event"] == "postonly_reject" and x["reason"] == "marketable" for x in e.ledger))

    def test_expiry_requests_cancel_and_late_fill_remains_possible(self):
        e = initialized(delay=500)
        for i, ms in enumerate((900, 1800, 2700, 3600, 4500), 2):
            e.frame(book(i, ms, U=i - 1, u=i))
        e.frame(trades(7, 5100, [("after_ttl_request", 100, .2, True)]))
        e.frame(trades(8, 5400, [("before_cancel_ack", 100, .2, True)]))
        self.assertAlmostEqual(e.position, .4)
        e.frame(trades(9, 5600, [("after_cancel_ack", 100, .2, True)]))
        self.assertAlmostEqual(e.position, .4)
        self.assertTrue(any(x["event"] == "cancel_request" and x["reason"] == "ttl" and x["ms"] == 5000 for x in e.ledger))

    def test_unknown_side_cannot_create_passive_fill(self):
        e = initialized()
        e.frame(trades(2, 200, [("bad_side", 100, 100, None)]))
        self.assertEqual(e.position, 0)
        self.assertEqual(e.coverage["invalid_trade_rows"], 1)

    def test_reduce_only_cannot_sell_more_than_inventory(self):
        e = initialized()
        e.frame(trades(2, 200, [("entry", 100, .2, True)]))
        with self.assertRaises(ValueError):
            e.fill("sell", 100, .3, "forced_taker")


if __name__ == "__main__":
    unittest.main()
