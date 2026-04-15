# -*- coding: utf-8 -*-
"""Tests for L10 tray classify + group (SFC Test_Fixture_Status)."""

import unittest

from fa_debug.l10_test_status import classify_tray, group_fixtures_from_sfc_payload


def _row(**kw):
    base = {
        "Fixture_No": "MTF 1",
        "Slot_No": "01",
        "Serial_Number": None,
        "Build_Phase": "N/A",
        "Group_Name": "N/A",
        "Status": "Empty",
        "Last_End_Time": None,
        "Error_Desc": None,
        "Remark": None,
    }
    base.update(kw)
    return base


class TestClassifyTray(unittest.TestCase):
    def test_remark_always_on_hold_even_if_pass(self):
        r = _row(Status="Pass", Group_Name="FCT", Remark="Hold for X")
        self.assertEqual(classify_tray(r), "on_hold")

    def test_idle_empty_na_no_remark(self):
        r = _row(Status="Empty", Group_Name="N/A", Remark=None)
        self.assertEqual(classify_tray(r), "idle")

    def test_verify_group_na_is_testing(self):
        r = _row(Status="Verify", Group_Name="N/A", Remark=None, Serial_Number="123")
        self.assertEqual(classify_tray(r), "testing")

    def test_empty_group_not_na_is_testing(self):
        r = _row(Status="Empty", Group_Name="FCT", Remark=None)
        self.assertEqual(classify_tray(r), "testing")

    def test_pass_group_not_na(self):
        r = _row(Status="Pass", Group_Name="FCT", Remark=None)
        self.assertEqual(classify_tray(r), "testing_pass")

    def test_fail_group_not_na(self):
        r = _row(Status="Fail", Group_Name="FCT", Remark=None)
        self.assertEqual(classify_tray(r), "testing_fail")

    def test_pass_group_na_unknown(self):
        r = _row(Status="Pass", Group_Name="N/A", Remark=None)
        self.assertEqual(classify_tray(r), "unknown")


class TestGroupFixtures(unittest.TestCase):
    def test_sorts_slots(self):
        payload = {
            "DATA": [
                _row(Slot_No="02", Fixture_No="MTF 1"),
                _row(Slot_No="10", Fixture_No="MTF 1"),
                _row(Slot_No="01", Fixture_No="MTF 1"),
            ]
        }
        out = group_fixtures_from_sfc_payload(payload)
        self.assertEqual(len(out), 1)
        slots = out[0]["slots"]
        self.assertEqual([s["slot_no"] for s in slots], ["01", "02", "10"])

    def test_multiple_fixtures_order(self):
        payload = {
            "DATA": [
                _row(Fixture_No="MTF 2", Slot_No="01"),
                _row(Fixture_No="MTF 10", Slot_No="01"),
                _row(Fixture_No="MTF 1", Slot_No="01"),
            ]
        }
        out = group_fixtures_from_sfc_payload(payload)
        self.assertEqual([f["fixture_no"] for f in out], ["MTF 1", "MTF 2", "MTF 10"])


if __name__ == "__main__":
    unittest.main()
