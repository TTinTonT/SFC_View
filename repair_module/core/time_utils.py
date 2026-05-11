# -*- coding: utf-8 -*-
"""Timezone formatting for fail-history timestamps."""

import pytz


def format_time_pacific(val):
    """Convert datetime to America/Los_Angeles formatted string, or return str(val)."""
    if val is None:
        return ""
    try:
        ca_tz = pytz.timezone("America/Los_Angeles")
        if hasattr(val, "isoformat"):
            dt = val
            if dt.tzinfo is None:
                dt = pytz.UTC.localize(dt)
            return dt.astimezone(ca_tz).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        pass
    return str(val) if val else ""
