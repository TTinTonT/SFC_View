# -*- coding: utf-8 -*-
from repair_module.core.db import get_conn
from repair_module.core.wip import get_station_and_next
from repair_module.core.routing import get_route_list
from repair_module.core.repair_actions import check_has_unrepaired
from repair_module.core.flow_state import (
    build_groups_ordered,
    slice_main_segment,
    detect_repair_mode,
    build_repair_chain,
    build_r_only_targets,
    get_dido_suffix_from_node,
    is_di_do_ri_ro_wip_node,
)
from repair_module.core.wip_serialize import WIP_KEYS, serialize_wip, route_items


def get_flow_state(sn: str):
    """Same as GET /api/debug/repair/flow-state?sn=..."""
    sn = (sn or "").strip().upper()
    if not sn:
        return {"ok": False, "error": "sn required"}
    try:
        conn = get_conn()
        try:
            row = get_station_and_next(conn, sn)
            if not row:
                return {"ok": False, "error": "No WIP for this SN"}
            wip = dict(zip(WIP_KEYS, row))
            route_cols, route_rows = get_route_list(conn, sn)
            route = route_items(route_cols, route_rows)
            groups_ordered = build_groups_ordered(route)
            main_segment, segment_found = slice_main_segment(groups_ordered, "AOI_FIN_ASSY", "T_VI")
            has_unrepaired = bool(check_has_unrepaired(conn, sn))
            mode_info = detect_repair_mode(wip) if has_unrepaired else {"ui_mode": "main_line"}
            ui_mode = mode_info.get("ui_mode") or "main_line"
            base = mode_info.get("base")
            repair_chain_nodes = build_repair_chain(base) if ui_mode == "repair_dido" else []
            r_only_targets = build_r_only_targets(base, groups_ordered) if ui_mode == "repair_r_only" else []
            current_node = (wip.get("NEXT_STATION") or "").strip() or (wip.get("GROUP_NAME") or "").strip()
            current_dido_station = get_dido_suffix_from_node(current_node) if ui_mode == "repair_dido" else ""
            tvi_idx = groups_ordered.index("T_VI") if "T_VI" in groups_ordered else -1
            current_idx = groups_ordered.index(current_node) if current_node in groups_ordered else -1
            if is_di_do_ri_ro_wip_node(current_node):
                all_pass = False
            else:
                all_pass = bool(tvi_idx >= 0 and current_idx >= tvi_idx)
            return {
                "ok": True,
                "wip": serialize_wip(wip),
                "route": route,
                "groups_ordered": groups_ordered,
                "segment_main": main_segment,
                "segment_found": segment_found,
                "has_unrepaired": has_unrepaired,
                "ui_mode": ui_mode,
                "repair_chain_nodes": repair_chain_nodes,
                "r_only_targets": r_only_targets,
                "current_dido_station": current_dido_station,
                "base": base or "",
                "all_pass": all_pass,
            }
        finally:
            conn.close()
    except Exception as e:
        return {"ok": False, "error": str(e)}
