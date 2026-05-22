# -*- coding: utf-8 -*-
"""Per-SN threading locks (same pattern as SFC_View fa_debug/routes._get_sn_lock)."""

from __future__ import annotations

import threading
from typing import Any

_guard = threading.Lock()
_locks: dict[str, threading.Lock] = {}


def get_sn_lock(sn: str) -> threading.Lock:
    key = (sn or "").strip().upper()
    with _guard:
        lk = _locks.get(key)
        if lk is None:
            lk = threading.Lock()
            _locks[key] = lk
        return lk
