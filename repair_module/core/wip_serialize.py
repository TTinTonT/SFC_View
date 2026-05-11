# -*- coding: utf-8 -*-
"""WIP dict keys and JSON-serializable helpers (same as fa_debug routes)."""

WIP_KEYS = [
    "SERIAL_NUMBER",
    "MO_NUMBER",
    "MODEL_NAME",
    "STATION_NAME",
    "LINE_NAME",
    "GROUP_NAME",
    "NEXT_STATION",
]


def serialize_wip(wip):
    return {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in (wip or {}).items()}


def route_items(route_cols, route_rows):
    route = []
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
