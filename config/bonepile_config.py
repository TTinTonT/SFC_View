# -*- coding: utf-8 -*-
"""Bonepile configuration: allowed sheets, block list paths."""

import os

from config.app_config import ANALYTICS_CACHE_DIR

# Sheets to process (block-list style: only these are allowed; all others ignored)
BONEPILE_ALLOWED_SHEETS = ["TS2-SKU1100", "VR-TS1", "TS2-SKU002", "TS2-SKU010"]

# Cache of BP SNs from NV disposition sheets
BP_SN_CACHE_PATH = os.path.join(ANALYTICS_CACHE_DIR, "bp_sn_cache.json")
