# -*- coding: utf-8 -*-
"""Application configuration: paths, timezone, SFC settings."""

import os

try:
    import pytz
except ImportError:
    pytz = None  # type: ignore

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ANALYTICS_CACHE_DIR = os.path.join(APP_DIR, "analytics_cache")

# SFC API: extend request range by N hours to avoid missing data
EXTEND_HOURS = 2

# California timezone for date ranges
CA_TZ = pytz.timezone("America/Los_Angeles") if pytz else None

# Station order for Test Flow Analysis (matches Bonepile_view)
STATIONS_ORDER = ["FLA", "FLB", "AST", "FTS", "FCT", "RIN", "NVL"]
