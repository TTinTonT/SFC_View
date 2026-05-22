# -*- coding: utf-8 -*-
"""Request-scoped Crabber SJ/SV profile (copy of fa_debug/routes._crabber_profile_scope)."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from flask import request


@contextmanager
def crabber_profile_scope() -> Iterator[bool]:
    """Set Crabber tuple from crabber_profile query/body; yield False if invalid."""
    from crabber.profile import (
        clear_crabber_context,
        normalize_crabber_profile,
        set_crabber_context_for_profile,
    )

    raw = None
    if request.method == "GET":
        raw = request.args.get("crabber_profile")
    else:
        data = request.get_json(silent=True) or {}
        raw = data.get("crabber_profile")
        if raw is None:
            raw = request.args.get("crabber_profile")
    try:
        pk = normalize_crabber_profile(raw)
    except ValueError:
        yield False
        return
    set_crabber_context_for_profile(pk)
    try:
        yield True
    finally:
        clear_crabber_context()
