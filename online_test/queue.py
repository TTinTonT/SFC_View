"""
In-memory per-fixture online test queue for L10 page (portable copy).

Keys are scoped by site (sj vs sv): internal storage ``sj::<fixture_no>``, ``sv::<fixture_no>`` so duplicate
fixture names across datacenters do not collide.

Limitation: single Flask worker process only (see README).
"""

from __future__ import annotations

import threading
import time
import uuid
from typing import Any, Optional

_MAX_COOLDOWN_SEC = 24 * 3600


def _norm_fixture(s: str) -> str:
    return (s or "").strip()


def _norm_site(site: Optional[str]) -> str:
    t = (site or "sj").strip().lower()
    return t if t in ("sj", "sv") else "sj"


def _compound_key(fixture_no: str, site: str) -> str:
    return f"{_norm_site(site)}::{_norm_fixture(fixture_no)}"


def _suffix_from_compound(compound: str) -> str:
    if "::" not in compound:
        return compound
    return compound.split("::", 1)[1]


def _norm_sn(s: str) -> str:
    return (s or "").strip().upper()


def _norm_slot(s: str) -> str:
    return (s or "").strip()


_lock = threading.RLock()
# compound_key ('sj::MTF 1') -> state dict
_fixtures: dict[str, dict[str, Any]] = {}


def reset_all_for_tests() -> None:
    """Clear all queue state (unit tests only)."""
    with _lock:
        _fixtures.clear()


def _ensure_key(compound_key: str) -> dict[str, Any]:
    if compound_key not in _fixtures:
        _fixtures[compound_key] = {
            "cooldown_until": None,
            "active": None,
            "queued": [],
            "skip_auto_promote": False,
        }
    return _fixtures[compound_key]


def _job_public(job: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": job["id"],
        "sn": job["sn"],
        "slot_no": job["slot_no"],
        "created_at": job["created_at"],
    }


def _maybe_promote(st: dict[str, Any]) -> None:
    """If no active job and cooldown elapsed, promote head of queue to active."""
    now = time.time()
    if st.get("skip_auto_promote"):
        return
    if st["active"] is not None:
        return
    cu = st["cooldown_until"]
    if cu is not None and now < cu:
        return
    if not st["queued"]:
        return
    st["active"] = st["queued"].pop(0)


def enqueue(
    fixture_no: str,
    slot_no: str,
    sn: str,
    *,
    site: Optional[str] = None,
) -> dict[str, Any]:
    """Add a job. Promotes to active if allowed."""
    fk = _compound_key(fixture_no, site or "sj")
    sn_n = _norm_sn(sn)
    slot = _norm_slot(slot_no)
    suffix = _suffix_from_compound(fk)
    if not suffix or not sn_n:
        return {"ok": False, "error": "fixture_no and sn required"}
    job = {
        "id": str(uuid.uuid4()),
        "sn": sn_n,
        "slot_no": slot,
        "created_at": time.time(),
    }
    site_n = _norm_site(site)
    with _lock:
        st = _ensure_key(fk)
        st["skip_auto_promote"] = False
        _maybe_promote(st)
        if st["active"] is None:
            st["active"] = job
            return {"ok": True, "job": _job_public(job), "immediate": True, "position": 0, "site": site_n}
        if st["active"] and st["active"]["sn"] == sn_n:
            return {"ok": False, "error": "This SN already has the active slot for this fixture."}
        for i, q in enumerate(st["queued"]):
            if q["sn"] == sn_n:
                st["skip_auto_promote"] = False
                _maybe_promote(st)
                now_active = st["active"] is not None and st["active"]["id"] == q["id"]
                return {
                    "ok": True,
                    "job": _job_public(q),
                    "immediate": bool(now_active),
                    "position": i + 1 if not now_active else 0,
                    "already_queued": True,
                    "site": site_n,
                }
        st["queued"].append(job)
        return {
            "ok": True,
            "job": _job_public(job),
            "immediate": False,
            "position": len(st["queued"]),
            "site": site_n,
        }


def complete(
    fixture_no: str,
    job_id: str,
    delay_min: int,
    delay_sec: int,
    *,
    site: Optional[str] = None,
) -> dict[str, Any]:
    """After successful online test start: clear active, set cooldown from UI."""
    fk = _compound_key(fixture_no, site or "sj")
    jid = (job_id or "").strip()
    suffix = _suffix_from_compound(fk)
    if not suffix or not jid:
        return {"ok": False, "error": "fixture_no and job_id required"}
    try:
        dm = max(0, int(delay_min))
        ds = max(0, int(delay_sec))
    except (TypeError, ValueError):
        return {"ok": False, "error": "delay_min and delay_sec must be integers"}
    gap = min(dm * 60 + ds, _MAX_COOLDOWN_SEC)
    site_n = _norm_site(site)
    with _lock:
        st = _fixtures.get(fk)
        if not st:
            return {"ok": False, "error": "Unknown fixture"}
        act = st["active"]
        if not act or act["id"] != jid:
            return {"ok": False, "error": "No matching active job for this fixture"}
        st["active"] = None
        st["cooldown_until"] = time.time() + gap if gap > 0 else None
        st["skip_auto_promote"] = False
        _maybe_promote(st)
        snap = snapshot_fixture(suffix, site=site_n)
    return {"ok": True, "fixture": snap}


def abandon(fixture_no: str, job_id: str, *, site: Optional[str] = None) -> dict[str, Any]:
    """Modal closed without successful start: return active job to front of queue."""
    fk = _compound_key(fixture_no, site or "sj")
    jid = (job_id or "").strip()
    suffix = _suffix_from_compound(fk)
    if not suffix or not jid:
        return {"ok": False, "error": "fixture_no and job_id required"}
    site_n = _norm_site(site)
    with _lock:
        st = _fixtures.get(fk)
        if not st:
            return {"ok": False, "error": "Unknown fixture"}
        act = st["active"]
        if not act or act["id"] != jid:
            return {"ok": False, "error": "No matching active job"}
        st["active"] = None
        st["queued"].insert(0, act)
        st["skip_auto_promote"] = True
        snap = snapshot_fixture(suffix, site=site_n)
    return {"ok": True, "fixture": snap}


def force_next(
    fixture_no: str,
    job_id: Optional[str] = None,
    *,
    site: Optional[str] = None,
) -> dict[str, Any]:
    """Clear cooldown; optionally move job_id to front; promote if possible."""
    fk = _compound_key(fixture_no, site or "sj")
    suffix = _suffix_from_compound(fk)
    if not suffix:
        return {"ok": False, "error": "fixture_no required"}
    jid = (job_id or "").strip() or None
    site_n = _norm_site(site)
    with _lock:
        st = _ensure_key(fk)
        st["cooldown_until"] = None
        st["skip_auto_promote"] = False
        if jid and st["queued"]:
            idx = next((i for i, j in enumerate(st["queued"]) if j["id"] == jid), None)
            if idx is not None and idx > 0:
                j = st["queued"].pop(idx)
                st["queued"].insert(0, j)
        _maybe_promote(st)
        snap = snapshot_fixture(suffix, site=site_n)
    return {"ok": True, "fixture": snap}


def _snapshot_inner(compound_key: str, site_n: str, fn_display: str) -> Optional[dict[str, Any]]:
    now = time.time()
    with _lock:
        st = _fixtures.get(compound_key)
        if not st:
            return None
        _maybe_promote(st)
        cu = st["cooldown_until"]
        remaining = max(0.0, float(cu) - now) if cu is not None else 0.0
        act = st["active"]
        qlist = st["queued"]
        arrow = None
        if act and qlist:
            arrow = {"from_slot": act["slot_no"], "to_slot": qlist[0]["slot_no"]}
        return {
            "fixture_no": fn_display,
            "site": site_n,
            "cooldown_until": cu,
            "cooldown_sec_remaining": int(remaining + 0.999) if remaining > 0 else 0,
            "active": _job_public(act) if act else None,
            "queued": [_job_public(j) for j in qlist],
            "queue_arrow": arrow,
        }


def snapshot_fixture(fixture_no: str, *, site: Optional[str] = None) -> Optional[dict[str, Any]]:
    """Public fixture name + site -> queue snapshot."""
    site_n = _norm_site(site)
    fk = _compound_key(fixture_no, site_n)
    return _snapshot_inner(fk, site_n, _norm_fixture(fixture_no))


def snapshot_site(site: str) -> dict[str, dict[str, Any]]:
    """Map short fixture_no -> snapshot for one site only (fixtures with activity)."""
    site_n = _norm_site(site)
    prefix = f"{site_n}::"
    with _lock:
        keys = [k for k in _fixtures.keys() if k.startswith(prefix)]
    out: dict[str, dict[str, Any]] = {}
    for ck in keys:
        suffix = _suffix_from_compound(ck)
        snap = _snapshot_inner(ck, site_n, suffix)
        if snap and (snap["active"] or snap["queued"] or snap["cooldown_sec_remaining"] > 0):
            out[suffix] = snap
    return out


def snapshot_queues_by_site() -> dict[str, dict[str, dict[str, Any]]]:
    return {"sj": snapshot_site("sj"), "sv": snapshot_site("sv")}


def next_after_active(fixture_no: str, *, site: Optional[str] = None) -> Optional[dict[str, Any]]:
    """First queued job (next in line), for UI arrow."""
    fk = _compound_key(fixture_no, site or "sj")
    with _lock:
        st = _fixtures.get(fk)
        if not st or not st["queued"]:
            return None
        return _job_public(st["queued"][0])
