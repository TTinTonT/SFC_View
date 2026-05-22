# -*- coding: utf-8 -*-
"""Paths and defaults for the portable online_test bundle."""

from __future__ import annotations

import os

_BUNDLE_DIR = os.path.dirname(os.path.abspath(__file__))
_DATA_DIR = os.path.join(_BUNDLE_DIR, "data")


def get_pn_bases_json_path() -> str:
    """
    JSON file for custom PN bases (same format as SFC_View: {\"custom\": [\"...\"]}).
    Override with env ONLINE_TEST_PN_BASES_PATH; default: <bundle>/data/crabber_test_pns.json
    """
    override = (os.environ.get("ONLINE_TEST_PN_BASES_PATH") or "").strip()
    if override:
        return override
    return os.path.join(_DATA_DIR, "crabber_test_pns.json")
