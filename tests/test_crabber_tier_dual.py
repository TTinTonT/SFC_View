# -*- coding: utf-8 -*-
"""Dual Crabber (SJ/SV) tier resolution for Analytics."""
import unittest
from typing import List, Tuple
from unittest.mock import patch

import crabber.client as cc


def _resolve_profile(profile: str):
    if profile == "sj":
        return ("http://sj.example", "t1", "41", "SanJose")
    if profile == "sv":
        return ("http://sv.example", "t2", "41", "SV_Worker4")
    raise ValueError(profile)


class TestGetSnTierFromCrabberDual(unittest.TestCase):
    def test_tries_sv_after_sj_returns_none(self):
        attempts: List[Tuple[str, str]] = []

        def fake_tier(sn: str, base: str, token: str, timeout: int = 15):
            attempts.append((base, token))
            if "sv.example" in base:
                return "L10"
            return None

        with patch.object(cc, "_get_config", return_value=("http://sj.example", "t1")):
            with patch("crabber.profile.resolve_tuple_for_profile", side_effect=_resolve_profile):
                with patch.object(cc, "_get_sn_tier_with_base_token", side_effect=fake_tier):
                    out = cc.get_sn_tier_from_crabber("SN123")
        self.assertEqual(out, "L10")
        self.assertEqual(len(attempts), 2)
        self.assertIn("sj.example", attempts[0][0])
        self.assertIn("sv.example", attempts[1][0])

    def test_same_base_token_only_one_tier_attempt(self):
        attempts: List[Tuple[str, str]] = []

        def fake_tier(sn: str, base: str, token: str, timeout: int = 15):
            attempts.append((base, token))
            return "L11"

        def resolve_same(profile: str):
            return ("http://same.example", "tok", "1", "X")

        with patch.object(cc, "_get_config", return_value=("http://same.example", "tok")):
            with patch("crabber.profile.resolve_tuple_for_profile", side_effect=resolve_same):
                with patch.object(cc, "_get_sn_tier_with_base_token", side_effect=fake_tier):
                    out = cc.get_sn_tier_from_crabber("SN999")
        self.assertEqual(out, "L11")
        self.assertEqual(len(attempts), 1)

    def test_all_none_returns_none(self):
        with patch.object(cc, "_get_config", return_value=("http://sj.example", "t1")):
            with patch("crabber.profile.resolve_tuple_for_profile", side_effect=_resolve_profile):
                with patch.object(cc, "_get_sn_tier_with_base_token", return_value=None):
                    self.assertIsNone(cc.get_sn_tier_from_crabber("SNX"))


if __name__ == "__main__":
    unittest.main()
