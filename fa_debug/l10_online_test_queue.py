"""
In-memory per-fixture online test queue for L10 page.

One active job per fixture (modal open / user completing flow). FIFO queue for
waiting jobs. Cooldown after a successful Crabber start blocks the next job.

Limitation: single Flask worker process only (see .cursor/rules/l10-test-page.mdc).
"""

from __future__ import annotations

import threading
import time
import uuid
from typing import Any

_MAX_COOLDOWN_SEC = 24 * 3600


def _norm_fixture(s: str) -> str:
    return (s or "").strip()


def _norm_sn(s: str) -> str:
    return (s or "").strip().upper()


def _norm_slot(s: str) -> str:
    return (s or "").strip()


_lock = threading.RLock()
# fixture_no -> state dict
_fixtures: dict[str, dict[str, Any]] = {}


def reset_all_for_tests() -> None:
    """Clear all queue state (unit tests only)."""
    with _lock:
        _fixtures.clear()


def _ensure(fixture_no: str) -> dict[str, Any]:
    fn = _norm_fixture(fixture_no)
    if fn not in _fixtures:
        _fixtures[fn] = {
            "cooldown_until": None,  # float epoch seconds or None
            "active": None,  # job dict or None
            "queued": [],  # list of job dicts
            # After abandon, do not auto-promote until next enqueue on this fixture.
            "skip_auto_promote": False,
        }
    return _fixtures[fn]


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


def enqueue(fixture_no: str, slot_no: str, sn: str) -> dict[str, Any]:
    """
    Add a job. Promotes to active if allowed.
    Returns { ok, job?, immediate, error?, position? }.
    """
    fn = _norm_fixture(fixture_no)
    sn_n = _norm_sn(sn)
    slot = _norm_slot(slot_no)
    if not fn or not sn_n:
        return {"ok": False, "error": "fixture_no and sn required"}
    job = {
        "id": str(uuid.uuid4()),
        "sn": sn_n,
        "slot_no": slot,
        "created_at": time.time(),
    }
    with _lock:
        st = _ensure(fn)
        st["skip_auto_promote"] = False
        _maybe_promote(st)
        if st["active"] is None:
            st["active"] = job
            return {"ok": True, "job": _job_public(job), "immediate": True, "position": 0}
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
                }
        st["queued"].append(job)
        return {
            "ok": True,
            "job": _job_public(job),
            "immediate": False,
            "position": len(st["queued"]),
        }


def complete(fixture_no: str, job_id: str, delay_min: int, delay_sec: int) -> dict[str, Any]:
    """After successful online test start: clear active, set cooldown from UI."""
    fn = _norm_fixture(fixture_no)
    jid = (job_id or "").strip()
    if not fn or not jid:
        return {"ok": False, "error": "fixture_no and job_id required"}
    try:
        dm = max(0, int(delay_min))
        ds = max(0, int(delay_sec))
    except (TypeError, ValueError):
        return {"ok": False, "error": "delay_min and delay_sec must be integers"}
    gap = min(dm * 60 + ds, _MAX_COOLDOWN_SEC)
    with _lock:
        st = _fixtures.get(fn)
        if not st:
            return {"ok": False, "error": "Unknown fixture"}
        act = st["active"]
        if not act or act["id"] != jid:
            return {"ok": False, "error": "No matching active job for this fixture"}
        st["active"] = None
        st["cooldown_until"] = time.time() + gap if gap > 0 else None
        st["skip_auto_promote"] = False
        _maybe_promote(st)
        snap = snapshot_fixture(fn)
    return {"ok": True, "fixture": snap}


def abandon(fixture_no: str, job_id: str) -> dict[str, Any]:
    """Modal closed without successful start: return active job to front of queue."""
    fn = _norm_fixture(fixture_no)
    jid = (job_id or "").strip()
    if not fn or not jid:
        return {"ok": False, "error": "fixture_no and job_id required"}
    with _lock:
        st = _fixtures.get(fn)
        if not st:
            return {"ok": False, "error": "Unknown fixture"}
        act = st["active"]
        if not act or act["id"] != jid:
            return {"ok": False, "error": "No matching active job"}
        st["active"] = None
        st["queued"].insert(0, act)
        st["skip_auto_promote"] = True
        snap = snapshot_fixture(fn)
    return {"ok": True, "fixture": snap}


def force_next(fixture_no: str, job_id: str | None = None) -> dict[str, Any]:
    """Clear cooldown; optionally move job_id to front; promote if possible."""
    fn = _norm_fixture(fixture_no)
    if not fn:
        return {"ok": False, "error": "fixture_no required"}
    jid = (job_id or "").strip() or None
    with _lock:
        st = _ensure(fn)
        st["cooldown_until"] = None
        st["skip_auto_promote"] = False
        if jid and st["queued"]:
            idx = next((i for i, j in enumerate(st["queued"]) if j["id"] == jid), None)
            if idx is not None and idx > 0:
                j = st["queued"].pop(idx)
                st["queued"].insert(0, j)
        _maybe_promote(st)
        snap = snapshot_fixture(fn)
    return {"ok": True, "fixture": snap}


def snapshot_fixture(fixture_no: str) -> dict[str, Any] | None:
    fn = _norm_fixture(fixture_no)
    now = time.time()
    with _lock:
        st = _fixtures.get(fn)
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
            "fixture_no": fn,
            "cooldown_until": cu,
            "cooldown_sec_remaining": int(remaining + 0.999) if remaining > 0 else 0,
            "active": _job_public(act) if act else None,
            "queued": [_job_public(j) for j in qlist],
            "queue_arrow": arrow,
        }


def snapshot_all() -> dict[str, dict[str, Any]]:
    with _lock:
        keys = list(_fixtures.keys())
    out: dict[str, dict[str, Any]] = {}
    for k in keys:
        snap = snapshot_fixture(k)
        if snap and (snap["active"] or snap["queued"] or snap["cooldown_sec_remaining"] > 0):
            out[k] = snap
    return out


def next_after_active(fixture_no: str) -> dict[str, Any] | None:
    """First queued job (next in line), for UI arrow."""
    fn = _norm_fixture(fixture_no)
    with _lock:
        st = _fixtures.get(fn)
        if not st or not st["queued"]:
            return None
        return _job_public(st["queued"][0])
