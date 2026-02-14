# -*- coding: utf-8 -*-
"""Bonepile configuration: allowed sheets, block list paths."""

import os

from config.app_config import ANALYTICS_CACHE_DIR

# Sheets to skip (blacklist: only these are ignored; all others are processed)
BONEPILE_IGNORED_SHEETS = ["TS2-MGX-FG", "TS2-SKU020"]

# Cache of BP SNs from NV disposition sheets
BP_SN_CACHE_PATH = os.path.join(ANALYTICS_CACHE_DIR, "bp_sn_cache.json")
