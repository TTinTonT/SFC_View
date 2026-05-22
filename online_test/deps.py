# -*- coding: utf-8 -*-
"""Optional imports from host app (fa_debug) with safe fallbacks."""

from __future__ import annotations

from typing import Any, Optional


def resolve_sfis_emp(request: Any, explicit: Optional[Any] = None, *, last_resort: str = "SJOP") -> str:
    """
    EMP for Oracle/SFIS. Prefer fa_debug.auth when this repo is SFC_View;
    otherwise mirror the same resolution rules.
    """
    try:
        from fa_debug.auth import resolve_sfis_emp as _host_resolve

        return _host_resolve(request, explicit, last_resort=last_resort)
    except ImportError:
        pass
    if explicit is not None:
        t = str(explicit).strip()
        if t:
            return t
    u = getattr(request, "current_user", None) or {}
    eid = str(u.get("employee_id") or "").strip()
    if eid:
        return eid
    un = str(u.get("username") or "").strip()
    if un:
        return un
    return last_resort
