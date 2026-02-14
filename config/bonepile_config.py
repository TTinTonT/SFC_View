# -*- coding: utf-8 -*-
"""Bonepile configuration: allowed sheets, block list paths."""

import os

from config.app_config import ANALYTICS_CACHE_DIR

# Sheets to skip (blacklist: only these are ignored; all others are processed)
BONEPILE_IGNORED_SHEETS = ["1RU RC2", "Consolidation", "Contact", "Conversion SKU00-02", "Convert list", "DGX MP", "DGX MP (DOE P1.12) (2)", "DGX MP L11 BP", "DGX PS1", "Daily Retest-Rework-Convert", "Detail1", "ETF Use Tracking", "IGS SKU Rework Conversion chart",
 "L10 BP PIVOT", "MGX 1RU TS4", "MGX 2RU CR2 (277)", "MGX_1RU_TS4_BP_02242025", "Readme_first", "Sheet1", "Sheet2", "TS2-SKU002 Replace", "VR-L11 BP", "Sheet1"]

# Cache of BP SNs from NV disposition sheets
BP_SN_CACHE_PATH = os.path.join(ANALYTICS_CACHE_DIR, "bp_sn_cache.json")
