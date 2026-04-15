"""Unit tests for fa_debug.l10_online_test_queue (in-memory per fixture)."""

import unittest

from fa_debug import l10_online_test_queue as q


class L10OnlineTestQueueTest(unittest.TestCase):
    def setUp(self):
        q.reset_all_for_tests()

    def test_immediate_then_queue(self):
        r1 = q.enqueue("MTF1", "01", "SN111")
        self.assertTrue(r1["ok"])
        self.assertTrue(r1["immediate"])
        r2 = q.enqueue("MTF1", "02", "SN222")
        self.assertTrue(r2["ok"])
        self.assertFalse(r2["immediate"])
        self.assertEqual(r2["position"], 1)

    def test_complete_zero_delay_promotes_next(self):
        q.enqueue("FX", "1", "A")
        q.enqueue("FX", "2", "B")
        snap = q.snapshot_fixture("FX")
        self.assertIsNotNone(snap and snap["active"])
        jid = snap["active"]["id"]
        c = q.complete("FX", jid, 0, 0)
        self.assertTrue(c["ok"])
        snap2 = q.snapshot_fixture("FX")
        self.assertIsNotNone(snap2)
        self.assertEqual(snap2["active"]["sn"], "B")

    def test_abandon_returns_job_to_queue(self):
        q.enqueue("FY", "1", "Z1")
        snap = q.snapshot_fixture("FY")
        jid = snap["active"]["id"]
        a = q.abandon("FY", jid)
        self.assertTrue(a["ok"])
        snap2 = q.snapshot_fixture("FY")
        self.assertIsNone(snap2["active"])
        self.assertEqual(len(snap2["queued"]), 1)
        self.assertEqual(snap2["queued"][0]["sn"], "Z1")

    def test_force_clears_cooldown(self):
        q.enqueue("FZ", "1", "S1")
        snap = q.snapshot_fixture("FZ")
        jid = snap["active"]["id"]
        q.complete("FZ", jid, 5, 0)
        snap2 = q.snapshot_fixture("FZ")
        self.assertGreater(snap2["cooldown_sec_remaining"], 0)
        f = q.force_next("FZ", None)
        self.assertTrue(f["ok"])
        snap3 = q.snapshot_fixture("FZ")
        self.assertEqual(snap3["cooldown_sec_remaining"], 0)


if __name__ == "__main__":
    unittest.main()
