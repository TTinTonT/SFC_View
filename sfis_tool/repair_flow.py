# -*- coding: utf-8 -*-
"""Helpers for Repair page flow-state modes and node rendering."""

import re


def normalize_station_name(name):
    """Normalize separators to underscore and collapse repeats."""
    if not name:
        return ""
    txt = str(name).strip().upper()
    txt = re.sub(r"[\s\-]+", "_", txt)
    txt = re.sub(r"_+", "_", txt)
    return txt


def build_groups_ordered(route_items):
    """Build ordered group list from route rows."""
    ordered = []
    if not route_items:
        return ordered
    first = (route_items[0].get("group_name") or "").strip()
    if first:
        ordered.append(first)
    for item in route_items:
        nxt = (item.get("group_next") or "").strip()
        if nxt and nxt not in ordered:
            ordered.append(nxt)
    return ordered


def compute_rc500_jump_next_param(conn, sn, next_station, group_name):
    """
    RC500 auto jump: sit one route step *before* the post-repair goal.

    get_jump_param_from_route(sn, X) finds GROUP_NAME where GROUP_NEXT = X.
    To land SN in group P (predecessor of goal G), pass X = G (the GROUP_NEXT
    after P).

    Derives goal from WIP NEXT_STATION (strip R_ prefix). If goal is found in
    the ordered route chain, returns ordered[idx] for that goal; else "".
    """
    from .jump_route import get_route_list

    goal = normalize_station_name(next_station or "")
    if goal.startswith("R_"):
        goal = goal[2:]
    if not goal:
        g0 = normalize_station_name(group_name or "")
        if g0.startswith("R_"):
            goal = g0[2:]
    if not goal:
        return ""

    cols, rows = get_route_list(conn, sn)
    if not rows:
        return ""
    route_items = []
    for row in rows:
        d = dict(zip(cols, row))
        route_items.append({
            "group_name": d.get("GROUP_NAME") or d.get("group_name"),
            "group_next": d.get("GROUP_NEXT") or d.get("group_next"),
        })
    ordered = build_groups_ordered(route_items)
    if len(ordered) < 2:
        return ""

    goal_u = goal.upper()
    idx = None
    for i, g in enumerate(ordered):
        gu = normalize_station_name(g)
        if gu == goal_u:
            idx = i
            break
    if idx is None:
        for i, g in enumerate(ordered):
            gu = normalize_station_name(g)
            if gu.endswith("_" + goal_u) or goal_u.endswith("_" + gu) or goal_u in gu or gu in goal_u:
                idx = i
                break
    if idx is None or idx < 1:
        return ""
    return (ordered[idx] or "").strip()


def slice_main_segment(groups_ordered, start_name="AOI_FIN_ASSY", end_name="T_VI"):
    """Return segment between two nodes (inclusive)."""
    if not groups_ordered:
        return [], False
    try:
        start_idx = groups_ordered.index(start_name)
        end_idx = groups_ordered.index(end_name)
        if start_idx <= end_idx:
            return groups_ordered[start_idx:end_idx + 1], True
        return [], False
    except ValueError:
        return [], False


def _parse_base_and_suffix(normalized):
    if not normalized:
        return "", ""
    if normalized.startswith("R_"):
        return normalized[2:], "R"
    m = re.match(r"^([A-Z0-9]+)_(DI|DO|RI|RO)$", normalized)
    if m:
        return m.group(1), m.group(2)
    return "", ""


def detect_repair_mode(wip):
    """
    Detect ui mode:
      - repair_dido: base_DI/DO/RI/RO/R_base recognized
      - repair_r_only: station starts with R_
      - main_line: fallback
    """
    names = [
        wip.get("GROUP_NAME"),
        wip.get("STATION_NAME"),
        wip.get("NEXT_STATION"),
    ]
    parsed = []
    for n in names:
        norm = normalize_station_name(n)
        if norm:
            base, suffix = _parse_base_and_suffix(norm)
            if base and suffix:
                parsed.append((base, suffix, norm))
    if not parsed:
        return {"ui_mode": "main_line"}
    base = parsed[0][0]
    suffixes = {p[1] for p in parsed if p[0] == base}
    if "R" in suffixes and (suffixes & {"DI", "DO", "RI", "RO"}):
        return {"ui_mode": "repair_dido", "base": base}
    if "R" in suffixes:
        return {"ui_mode": "repair_r_only", "base": base}
    return {"ui_mode": "repair_dido", "base": base}


def build_repair_chain(base):
    """Display-only chain for DI/DO/RI/RO/R_xxx."""
    if not base:
        return []
    return [f"{base}_DI", f"{base}_DO", f"{base}_RI", f"{base}_RO", f"R_{base}"]


def get_dido_suffix_from_node(node):
    """Return DI/DO/RI/RO suffix from group/station name, or empty string."""
    if not node:
        return ""
    base, suffix = _parse_base_and_suffix(normalize_station_name(node))
    if suffix in ("DI", "DO", "RI", "RO"):
        return suffix
    return ""


def build_r_only_targets(base, route_groups):
    """Build R_xxx target options for repair_r_only mode."""
    out = []
    if not base:
        return out
    seen = set()
    for target in [base, "FLA"]:
        if target and target not in seen:
            out.append({"from": f"R_{base}", "to": target})
            seen.add(target)
    for g in route_groups or []:
        gg = (g or "").strip().upper()
        if gg and gg not in seen and gg in (base, "FLA"):
            out.append({"from": f"R_{base}", "to": gg})
            seen.add(gg)
    return out


_WIP_KEYS_MAIN_LINE = [
    "SERIAL_NUMBER",
    "MO_NUMBER",
    "MODEL_NAME",
    "STATION_NAME",
    "LINE_NAME",
    "GROUP_NAME",
    "NEXT_STATION",
]


def is_di_do_ri_ro_wip_node(node: str) -> bool:
    """
    True if WIP NEXT_STATION/GROUP_NAME is on the DI/DO/RI/RO rework path.

    Those nodes may appear after T_VI in the flattened route list but are not
    main-line completion; they must not satisfy main-line all_pass (Repair + Debug timeline).
    """
    n = normalize_station_name(node or "")
    if not n:
        return False
    if n.startswith("R_"):
        n = n[2:]
    if "_" not in n:
        return False
    last = n.rsplit("_", 1)[-1].upper()
    return last in ("DI", "DO", "RI", "RO")


def main_line_all_pass_for_sn(conn, sn: str) -> bool:
    """
    Same rule as Repair /api/debug/repair/flow-state field all_pass:
    WIP current node (NEXT_STATION or GROUP_NAME) is at or past T_VI on the ordered route.

    Nodes on the DI/DO/RI/RO rework suffix path (e.g. FCT_DI) never count as main-line
    all pass even if they appear after T_VI in a flattened route list.
    """
    from .jump_route import get_route_list
    from .wip import get_station_and_next

    sn_u = (sn or "").strip().upper()
    if not sn_u:
        return False
    row = get_station_and_next(conn, sn_u)
    if not row:
        return False
    wip = dict(zip(_WIP_KEYS_MAIN_LINE, row))
    route_cols, route_rows = get_route_list(conn, sn_u)
    route_items = []
    for r in route_rows or []:
        d = dict(zip(route_cols, r))
        route_items.append(
            {
                "step": d.get("STEP"),
                "group_name": d.get("GROUP_NAME") or "",
                "group_next": d.get("GROUP_NEXT") or "",
            }
        )
    groups_ordered = build_groups_ordered(route_items)
    current_node = (wip.get("NEXT_STATION") or "").strip() or (wip.get("GROUP_NAME") or "").strip()
    tvi_idx = groups_ordered.index("T_VI") if "T_VI" in groups_ordered else -1
    current_idx = groups_ordered.index(current_node) if current_node in groups_ordered else -1
    if is_di_do_ri_ro_wip_node(current_node):
        return False
    return bool(tvi_idx >= 0 and current_idx >= tvi_idx)
