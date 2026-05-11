# -*- coding: utf-8 -*-
"""Request-scoped Crabber endpoint (San Jose vs SV)."""
from __future__ import annotations

from contextvars import ContextVar
from typing import Optional, Tuple

# (base_url, token, user_id, sitename)
_crabber_tuple_var: ContextVar[Optional[Tuple[str, str, str, str]]] = ContextVar(
    "crabber_tuple", default=None
)

VALID_PROFILES = frozenset({"sj", "sv"})


def normalize_crabber_profile(raw: Optional[str]) -> str:
    """Return 'sj' or 'sv'. Default sj."""
    s = (raw or "").strip().lower()
    if not s or s == "sj" or s == "sanjose" or s == "san_jose":
        return "sj"
    if s == "sv" or s == "sunnyvale":
        return "sv"
    raise ValueError("invalid crabber_profile")


def resolve_tuple_for_profile(profile: str) -> Tuple[str, str, str, str]:
    """Resolve (base, token, user_id, sitename) for allowlisted profile key."""
    from config import debug_config as dc

    if profile == "sj":
        base = (dc.CRABBER_BASE_URL or "").strip().rstrip("/")
        tok = (dc.CRABBER_TOKEN or "").strip()
        return base, tok, dc.CRABBER_USER_ID, (dc.CRABBER_SITENAME or "SanJose").strip()
    if profile == "sv":
        base = (dc.CRABBER_SV_BASE_URL or "").strip().rstrip("/") or (dc.CRABBER_BASE_URL or "").strip().rstrip(
            "/"
        )
        tok = (dc.CRABBER_SV_TOKEN or dc.CRABBER_TOKEN or "").strip()
        uid = str(dc.CRABBER_SV_USER_ID or dc.CRABBER_USER_ID or "41").strip()
        return base, tok, uid, (dc.CRABBER_SV_SITENAME or "SV_Worker4").strip()
    raise ValueError("invalid profile")


def set_crabber_context_for_profile(profile_key: str) -> Tuple[str, str, str, str]:
    """Store resolved tuple for this request context. Returns the tuple."""
    pk = normalize_crabber_profile(profile_key)
    t = resolve_tuple_for_profile(pk)
    _crabber_tuple_var.set(t)
    return t


def clear_crabber_context() -> None:
    _crabber_tuple_var.set(None)


def get_crabber_tuple() -> Tuple[str, str, str, str]:
    """Current request tuple, or San Jose globals if unset (CLI / backwards compat)."""
    t = _crabber_tuple_var.get()
    if t is not None:
        return t
    return resolve_tuple_for_profile("sj")
