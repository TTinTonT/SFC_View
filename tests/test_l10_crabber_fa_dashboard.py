# -*- coding: utf-8 -*-
import unittest

from fa_debug.l10_crabber_fa_dashboard import (
    FA_SLOTS_PER_ETF,
    build_fa_etf_fixture_list,
    parse_global_slot_fa_machine,
)


class TestFaMachineSlot(unittest.TestCase):
    def test_parse_example(self):
        self.assertEqual(
            parse_global_slot_fa_machine(
                "VR-NVL72_AST_AUTO_L10_ETF-AST_FA_013",
            ),
            13,
        )

    def test_parse_lowercase(self):
        self.assertEqual(parse_global_slot_fa_machine("X_fa_001"), 1)

    def test_rejects_no_fa(self):
        self.assertIsNone(parse_global_slot_fa_machine("VR-_MTF_013"))

    def test_rejects_no_tail_digits(self):
        self.assertIsNone(parse_global_slot_fa_machine("VR-NVL-FA"))


class TestBuildEtfFixtures(unittest.TestCase):
    def test_single_etf_partial_slots(self):
        rows = [
            {
                "global_slot": 2,
                "log_time": "2024-01-02",
                "sn": "AAA",
                "machine": "_FA_002",
                "station": "X",
                "result": "Testing",
                "pn_name": "",
                "occupied": True,
                "node_log_event": "PROC",
            },
            {
                "global_slot": 13,
                "log_time": "2024-01-03",
                "sn": "BBB",
                "machine": "_FA_013",
                "station": "X",
                "result": "Testing",
                "pn_name": "",
                "occupied": True,
                "node_log_event": "PROC",
            },
        ]
        fixtures = build_fa_etf_fixture_list(rows)
        self.assertEqual(len(fixtures), 1)
        self.assertEqual(fixtures[0]["etf_index"], 1)
        self.assertEqual(len(fixtures[0]["slots"]), FA_SLOTS_PER_ETF)
        occ = sum(1 for s in fixtures[0]["slots"] if s["occupied"])
        self.assertEqual(occ, 2)

    def test_second_etf_boundary(self):
        rows = [
            {
                "global_slot": 14,
                "log_time": "t1",
                "sn": "S",
                "machine": "_FA_014",
                "station": "X",
                "result": "Testing",
                "pn_name": "",
                "occupied": True,
                "node_log_event": "PROC",
            },
        ]
        fx = build_fa_etf_fixture_list(rows)
        self.assertEqual(len(fx), 2)
        self.assertEqual(fx[1]["etf_index"], 2)
        self.assertTrue(any(s["occupied"] for s in fx[1]["slots"]))
        self.assertFalse(any(s["occupied"] for s in fx[0]["slots"]))

    def test_dedupe_keeps_newer_log(self):
        rows = [
            {"global_slot": 5, "log_time": "2024-01-01", "sn": "OLD", "_": ""},
            {"global_slot": 5, "log_time": "2024-01-05", "sn": "NEW", "_": ""},
        ]
        fx = build_fa_etf_fixture_list(rows)
        sn = next(s["sn"] for s in fx[0]["slots"] if s["occupied"])
        self.assertEqual(sn, "NEW")


if __name__ == "__main__":
    unittest.main()
