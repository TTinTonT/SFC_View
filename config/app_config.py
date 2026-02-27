# -*- coding: utf-8 -*-
"""Application configuration: paths, timezone, SFC settings."""

import os

from config.analytics_config import (
    get_ca_tz,
    get_extend_hours,
    get_stations_order,
    get_top_k_errors_default,
)

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ANALYTICS_CACHE_DIR = os.path.join(APP_DIR, "analytics_cache")

# SFC API: extend request range by N hours (from analytics_config)
EXTEND_HOURS = get_extend_hours()

# California timezone for date ranges (from analytics_config)
CA_TZ = get_ca_tz()

# Station order for Test Flow Analysis (from analytics_config)
STATIONS_ORDER = get_stations_order()

# Error Stats: default Top K errors (from analytics_config)
TOP_K_ERRORS_DEFAULT = get_top_k_errors_default()
