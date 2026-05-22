# -*- coding: utf-8 -*-
"""PN base list for Crabber online test (ported from fa_debug/routes.py)."""

from __future__ import annotations

import json
import os
from typing import Any, List

from online_test.config import get_pn_bases_json_path

_DEFAULT_ONLINE_TEST_PN_BASES = [
    "VR200_L10",
]


def _load_custom_pn_bases() -> List[str]:
    path = get_pn_bases_json_path()
    if not os.path.isfile(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return [str(x).strip() for x in data if str(x).strip()]
        return [str(x).strip() for x in (data.get("custom") or data.get("extra") or []) if str(x).strip()]
    except Exception:
        return []


def _save_custom_pn_bases(custom_list: List[str]) -> None:
    path = get_pn_bases_json_path()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"custom": custom_list}, f, indent=2, ensure_ascii=False)


def merge_pn_base_list() -> List[dict[str, Any]]:
    """Return list of dicts: [{base, is_default}, ...]."""
    custom = _load_custom_pn_bases()
    seen: set[str] = set()
    out: List[dict[str, Any]] = []
    for p in _DEFAULT_ONLINE_TEST_PN_BASES:
        u = (p or "").strip()
        if u and u.upper() not in seen:
            seen.add(u.upper())
            out.append({"base": u, "is_default": True})
    for p in custom:
        u = (p or "").strip()
        if u and u.upper() not in seen:
            seen.add(u.upper())
            out.append({"base": u, "is_default": False})
    return out


def load_custom_pn_bases() -> List[str]:
    return _load_custom_pn_bases()


def save_custom_pn_bases(custom_list: List[str]) -> None:
    _save_custom_pn_bases(custom_list)
