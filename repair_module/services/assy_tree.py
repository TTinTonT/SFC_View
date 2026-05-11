# -*- coding: utf-8 -*-
from repair_module.core.db import get_conn
from repair_module.core.kitting import (
    fetch_assy_tree,
    build_numbered_tree_preserve_order,
    validate_tree_integrity,
)


def get_assy_tree(sn: str):
    """Same as GET /api/debug/repair/assy-tree?sn=..."""
    sn = (sn or "").strip()
    if not sn:
        return {"ok": False, "error": "sn required"}
    try:
        conn = get_conn()
        try:
            cols, rows = fetch_assy_tree(conn, sn)
            if not rows:
                return {"ok": True, "tree": []}
            ok_tree, duplicate_vendor_sns = validate_tree_integrity(conn, sn)
            numbered_list, _ = build_numbered_tree_preserve_order(cols, rows)
            tree = []
            for t in numbered_list:
                num, node_key, row, is_father, parent_num, depth = t
                sn_key, vendor_sn, father_sn = node_key
                assy_flag = row.get("ASSY_FLAG") or "Y"
                tree.append(
                    {
                        "num": num,
                        "sn": sn_key,
                        "vendor_sn": vendor_sn,
                        "father_sn": father_sn,
                        "sub_model_name": (row.get("SUB_MODEL_NAME") or ""),
                        "model_name": (row.get("MODEL_NAME") or ""),
                        "in_station_time": (row.get("IN_STATION_TIME") or ""),
                        "stack": (row.get("STACK") or ""),
                        "assy_flag": assy_flag,
                        "assy_seq": row.get("ASSY_SEQ"),
                        "depth": depth,
                        "is_father": is_father,
                        "parent_num": parent_num,
                    }
                )
            return {
                "ok": True,
                "tree": tree,
                "invalid_duplicates": duplicate_vendor_sns,
                "tree_valid": ok_tree,
            }
        finally:
            conn.close()
    except Exception as e:
        return {"ok": False, "error": str(e)}
