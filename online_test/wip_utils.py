# -*- coding: utf-8 -*-
"""WIP serialization and L10 queue site normalization."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

WIP_KEYS = [
    "SERIAL_NUMBER",
    "MO_NUMBER",
    "MODEL_NAME",
    "STATION_NAME",
    "LINE_NAME",
    "GROUP_NAME",
    "NEXT_STATION",
]


def wip_keys() -> List[str]:
    return list(WIP_KEYS)


def serialize_wip(wip: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    return {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in (wip or {}).items()}


def route_items(route_cols: Any, route_rows: Any) -> List[Dict[str, Any]]:
    route: List[Dict[str, Any]] = []
    for r in route_rows or []:
        d = dict(zip(route_cols, r))
        route.append(
            {
                "step": d.get("STEP"),
                "group_name": d.get("GROUP_NAME") or "",
                "group_next": d.get("GROUP_NEXT") or "",
            }
        )
    return route


def norm_l10_queue_site(raw: Any) -> str:
    t = str(raw or "sj").strip().lower()
    return t if t in ("sj", "sv") else "sj"
