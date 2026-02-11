# -*- coding: utf-8 -*-
"""Bonepile check: wrap load_bp_sn_set and add is_bonepile to rows."""

from typing import List, Set

from bonepile_disposition import load_bp_sn_set as _load_bp_sn_set


def load_bp_sn_set() -> Set[str]:
    """Load set of BP SNs from cache (NV disposition sheets)."""
    return _load_bp_sn_set()


def add_bp_to_rows(rows: List[dict]) -> List[dict]:
    """Add is_bonepile (bool) to each row. Modifies in place, returns rows."""
    bp_set = load_bp_sn_set()
    for r in rows:
        sn = (r.get("serial_number") or "").strip()
        r["is_bonepile"] = sn in bp_set
    return rows
