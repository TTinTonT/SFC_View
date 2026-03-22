# -*- coding: utf-8 -*-
"""Helpers for Repair page flow-state modes and node rendering."""

import re


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


def normalize_station_name(name):
    """Normalize separators to underscore and collapse repeats."""
    if not name:
        return ""
    txt = str(name).strip().upper()
    txt = re.sub(r"[\s\-]+", "_", txt)
    txt = re.sub(r"_+", "_", txt)
    return txt


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
