# -*- coding: utf-8 -*-
"""
Per-process SN locks and idempotent response cache for repair execute (matches SFC_View behavior).
"""
import threading
import time

_sn_locks_guard = threading.Lock()
_sn_locks = {}
_request_cache = {}
_REQ_TTL_SEC = 300


def get_sn_lock(sn):
    key = (sn or "").strip().upper()
    with _sn_locks_guard:
        lk = _sn_locks.get(key)
        if lk is None:
            lk = threading.Lock()
            _sn_locks[key] = lk
        return lk


def cache_repair_response(sn, request_id, resp_obj):
    if not request_id:
        return
    key = ((sn or "").strip().upper(), str(request_id).strip())
    now = int(time.time())
    _request_cache[key] = (now + _REQ_TTL_SEC, resp_obj)
    expired = [k for k, v in _request_cache.items() if v[0] < now]
    for k in expired:
        _request_cache.pop(k, None)


def get_cached_repair_response(sn, request_id):
    if not request_id:
        return None
    key = ((sn or "").strip().upper(), str(request_id).strip())
    now = int(time.time())
    item = _request_cache.get(key)
    if not item:
        return None
    expire_ts, resp = item
    if expire_ts < now:
        _request_cache.pop(key, None)
        return None
    return resp
