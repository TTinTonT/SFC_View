# -*- coding: utf-8 -*-
"""
Kitting / de-kit (Change OK): fetch_assy_tree, dekit_nodes, insert_assy_row, validators.
"""
from repair_module.sql.kitting_sql import (
    KITTING_FETCH_ASSY_TREE,
    KITTING_COUNT_DEKITTED,
    KITTING_INSERT_SELECT,
    KITTING_CHECK_VENDOR_IN_OTHER_TRAY,
)

DEPTH_LIMIT = 5
MAX_TREE_NODES = 200


def _is_config_vendor(vendor_sn):
    s = str(vendor_sn or "").strip().upper()
    return bool(s.startswith("CONFIG") and s[6:].isdigit())


def fetch_assy_tree(conn, sn, assy_flag=None):
    """Load assy rows for SN. Returns (cols, rows)."""
    cur = conn.cursor()
    try:
        cur.execute(KITTING_FETCH_ASSY_TREE, {"sn": sn.upper()})
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
        if assy_flag in ("Y", "N"):
            idx_flag = next((i for i, c in enumerate(cols) if c.upper() == "ASSY_FLAG"), -1)
            if idx_flag >= 0:
                rows = [r for r in rows if (str(r[idx_flag] or "").upper() == assy_flag)]
        return cols, rows
    finally:
        cur.close()


def count_dekitted_parts(conn, sn):
    """Count ASSY_FLAG='N' rows in kitting group."""
    cur = conn.cursor()
    try:
        cur.execute(KITTING_COUNT_DEKITTED, [sn.upper()])
        return cur.fetchone()[0]
    finally:
        cur.close()


def build_numbered_tree(cols, rows):
    """Build tree keyed by VENDOR_SN/FATHER_SN (legacy shape). Returns (numbered_list, vendor_to_row)."""
    col_idx = {c.upper(): i for i, c in enumerate(cols)}
    idx_vendor = col_idx.get("VENDOR_SN", -1)
    idx_father = col_idx.get("FATHER_SN", -1)
    idx_assy_ord = col_idx.get("ASSY_ORD", -1)

    vendor_to_row = {}
    rows_list = []
    for r in rows:
        row_dict = {cols[i]: r[i] for i in range(len(cols))}
        vsn = r[idx_vendor] if idx_vendor >= 0 else None
        father = row_dict.get("FATHER_SN") if idx_father >= 0 else None
        if vsn is not None:
            node_key = (vsn, father)
            vendor_to_row[node_key] = row_dict
            rows_list.append((vsn, father, row_dict))

    vendor_sns_set = {vsn for vsn, _, _ in rows_list}
    children_of = {}
    for vsn, father, _ in rows_list:
        if father is not None and father in vendor_sns_set:
            children_of.setdefault(father, []).append((vsn, father))

    roots = [(vsn, father) for vsn, father, _ in rows_list if father is None or father not in vendor_sns_set]

    def sort_key(node_key):
        r = vendor_to_row.get(node_key, {})
        return (r.get("ASSY_ORD") if idx_assy_ord >= 0 else None) or 0

    roots = sorted(roots, key=sort_key)
    for k in children_of:
        children_of[k] = sorted(children_of[k], key=lambda nk: sort_key(nk))

    def parent_node_key_of(node_key):
        vsn, father = node_key
        if father is None:
            return None
        return next((k for k in vendor_to_row if k[0] == father), None)

    flat = []

    def walk(node_key, depth):
        vsn, father = node_key
        row = vendor_to_row[node_key]
        is_father = vsn in children_of
        pnk = parent_node_key_of(node_key)
        flat.append((node_key, row, is_father, pnk, depth))
        for child_key in children_of.get(vsn, []):
            walk(child_key, depth + 1)

    for rk in roots:
        walk(rk, 0)

    return [(i, *t) for i, t in enumerate(flat, 1)], vendor_to_row


def build_numbered_tree_preserve_order(cols, rows):
    """
    Build numbered tree in SQL order (ASSY_SEQ); node key = (SN, VENDOR_SN, FATHER_SN).
    """
    rows_in_order = []
    vendor_to_keys = {}
    children_by_key = {}

    for r in rows:
        row_dict = {cols[i]: r[i] for i in range(len(cols))}
        sn = row_dict.get("SN") or row_dict.get("SERIAL_NUMBER")
        vsn = row_dict.get("VENDOR_SN")
        father = row_dict.get("FATHER_SN")
        if not sn or not vsn:
            continue
        nk = (str(sn), str(vsn), father if father is None else str(father))
        rows_in_order.append((nk, row_dict))
        vendor_to_keys.setdefault((str(sn), str(vsn)), []).append(nk)

    def parent_of(node_key):
        sn, _, father = node_key
        if father is None:
            return None
        candidates = vendor_to_keys.get((sn, str(father))) or []
        return candidates[0] if candidates else None

    for nk, _ in rows_in_order:
        pnk = parent_of(nk)
        if pnk is not None:
            children_by_key.setdefault(pnk, []).append(nk)

    if len(rows_in_order) > MAX_TREE_NODES:
        raise ValueError(f"Tree has too many nodes ({len(rows_in_order)}). Max allowed: {MAX_TREE_NODES}.")

    depth_cache = {}

    def get_depth(node_key, stack=None):
        stack = stack or set()
        if node_key in depth_cache:
            return depth_cache[node_key]
        if node_key in stack:
            raise ValueError(f"Cycle detected at node {node_key[1]}. Please contact IT to fix data.")
        stack.add(node_key)
        pnk = parent_of(node_key)
        depth = 0 if pnk is None else 1 + get_depth(pnk, stack)
        stack.discard(node_key)
        if depth > DEPTH_LIMIT:
            raise ValueError(
                f"Tree depth exceeds limit (max {DEPTH_LIMIT}). "
                f"Node {node_key[1]} at depth {depth}. Please contact IT to fix data."
            )
        depth_cache[node_key] = depth
        return depth

    num_by_key = {}
    for i, (nk, _) in enumerate(rows_in_order):
        num_by_key[nk] = i + 1

    numbered_list = []
    vendor_to_row = {}
    for i, (nk, row) in enumerate(rows_in_order):
        num = i + 1
        is_father = nk in children_by_key
        pnk = parent_of(nk)
        parent_num = num_by_key.get(pnk) if pnk else None
        depth = get_depth(nk)
        vendor_to_row[nk] = row
        numbered_list.append((num, nk, row, is_father, parent_num, depth))
    return numbered_list, vendor_to_row


def collect_subtree_nodes(numbered_list, root_key):
    """Collect subtree node_keys in numbered_list order."""
    by_parent = {}
    for _, nk, _, _, parent_num, _ in numbered_list:
        by_parent.setdefault(parent_num, []).append(nk)
    num_by_key = {nk: num for num, nk, _, _, _, _ in numbered_list}
    root_num = num_by_key.get(root_key)
    if root_num is None:
        return []
    out = []
    stack = [root_num]
    seen = set()
    while stack:
        if len(out) > MAX_TREE_NODES:
            raise ValueError(f"Subtree exceeds max nodes {MAX_TREE_NODES}.")
        pnum = stack.pop(0)
        for nk in by_parent.get(pnum, []):
            if nk in seen:
                continue
            seen.add(nk)
            out.append(nk)
            child_num = num_by_key.get(nk)
            if child_num is not None:
                stack.append(child_num)
    return [root_key] + [nk for nk in out if nk != root_key]


def expand_selection_to_flat(numbered_list, vendor_to_row, selected_numbers):
    """Expand selection: father -> full subtree."""
    selected_set = set(int(str(x).strip()) for x in selected_numbers if str(x).strip().isdigit())
    by_num = {t[0]: t for t in numbered_list}
    added_node_keys = set()
    flat = []

    for num in sorted(by_num.keys()):
        if num not in selected_set:
            continue
        t = by_num[num]
        _, node_key, row, is_father, parent_node_key, depth = t
        if node_key in added_node_keys:
            continue
        if is_father:
            subtree_keys = _collect_subtree(node_key, vendor_to_row)
            for t2 in numbered_list:
                nk = t2[1]
                if nk in added_node_keys or nk not in subtree_keys:
                    continue
                added_node_keys.add(nk)
                flat.append(t2)
        else:
            added_node_keys.add(node_key)
            flat.append(t)
    return flat


def _collect_subtree(root_node_key, vendor_to_row):
    """Return set of node_keys in subtree of root."""
    parent_vsns = {k[0] for k in vendor_to_row}
    children_of = {}
    for (vsn, father), row in vendor_to_row.items():
        if father is not None and father in parent_vsns:
            children_of.setdefault(father, []).append((vsn, father))
    out = {root_node_key}
    stack = [root_node_key]
    while stack:
        if len(out) > MAX_TREE_NODES:
            raise ValueError(f"Subtree exceeds max nodes {MAX_TREE_NODES}.")
        v, f = stack.pop()
        for ck in children_of.get(v, []):
            out.add(ck)
            stack.append(ck)
    return out


def _coerce_dekit_spec(key):
    if isinstance(key, dict):
        v = (key.get("vendor_sn") or "").strip()
        f = key.get("father_sn")
        if isinstance(f, str):
            f = f.strip() or None
        assy_seq = key.get("assy_seq")
        if assy_seq == "":
            assy_seq = None
        stack = key.get("stack")
        if stack is not None and isinstance(stack, str):
            stack = stack.strip() or None
        return {"vendor_sn": v, "father_sn": f, "assy_seq": assy_seq, "stack": stack}
    if isinstance(key, (list, tuple)) and len(key) == 3:
        _, v, f = key
        return {"vendor_sn": str(v or "").strip(), "father_sn": f, "assy_seq": None, "stack": None}
    v, f = key
    return {"vendor_sn": str(v or "").strip(), "father_sn": f, "assy_seq": None, "stack": None}


def _dekit_is_scoped(spec):
    return spec.get("assy_seq") is not None or spec.get("stack") is not None


def _execute_dekit_update(cur, sn, emp, spec):
    sql = (
        "UPDATE SFISM4.R_ASSY_COMPONENT_T "
        "SET ASSY_FLAG = 'N', IN_STATION_TIME = SYSDATE, EMP_NO = :emp "
        "WHERE SERIAL_NUMBER = :sn AND ASSY_FLAG = 'Y' AND VENDOR_SN = :v "
        "AND (FATHER_SN = :f OR (FATHER_SN IS NULL AND :f IS NULL))"
    )
    params = {
        "sn": sn.upper(),
        "emp": (emp or "").strip(),
        "v": spec["vendor_sn"],
        "f": spec["father_sn"],
    }
    if spec.get("assy_seq") is not None:
        sql += " AND ASSY_SEQ = :assy_seq"
        params["assy_seq"] = spec["assy_seq"]
    if spec.get("stack") is not None:
        sql += " AND NVL(STACK, CHR(0)) = NVL(:stack, CHR(0))"
        params["stack"] = spec["stack"]
    cur.execute(sql, params)
    return cur.rowcount


def dekit_nodes(conn, sn, node_keys, emp, auto_commit=True, skip_missing=False):
    """UPDATE ASSY_FLAG='N' per target; dict keys may include assy_seq/stack for a single physical row."""
    if not node_keys:
        return 0, ""
    cur = conn.cursor()
    try:
        total = 0
        for key in node_keys:
            spec = _coerce_dekit_spec(key)
            v = spec["vendor_sn"]
            f = spec["father_sn"]
            if not v:
                if skip_missing:
                    continue
                return 0, "Empty vendor_sn in dekit key"
            rc = _execute_dekit_update(cur, sn, emp, spec)
            if rc <= 0:
                if skip_missing:
                    continue
                return 0, f"Row not found/already dekitted: vendor_sn={v}, father_sn={f}"
            if _dekit_is_scoped(spec) and rc != 1:
                return (
                    0,
                    f"Expected exactly one row for scoped de-kit (vendor_sn={v}, assy_seq={spec.get('assy_seq')!r}, "
                    f"stack={spec.get('stack')!r}) but updated {rc}.",
                )
            total += rc
        if auto_commit:
            conn.commit()
        return total, ""
    except Exception as e:
        if auto_commit:
            conn.rollback()
        return 0, str(e)
    finally:
        cur.close()


def verify_dekit_targets(cur, sn, specs):
    for spec in specs:
        sql = (
            "SELECT COUNT(*), NVL(SUM(CASE WHEN UPPER(NVL(ASSY_FLAG, '')) = 'N' THEN 1 ELSE 0 END), 0) "
            "FROM SFISM4.R_ASSY_COMPONENT_T "
            "WHERE SERIAL_NUMBER = :sn AND VENDOR_SN = :v "
            "AND (FATHER_SN = :f OR (FATHER_SN IS NULL AND :f IS NULL))"
        )
        params = {"sn": sn.upper(), "v": spec["vendor_sn"], "f": spec["father_sn"]}
        if spec.get("assy_seq") is not None:
            sql += " AND ASSY_SEQ = :assy_seq"
            params["assy_seq"] = spec["assy_seq"]
        if spec.get("stack") is not None:
            sql += " AND NVL(STACK, CHR(0)) = NVL(:stack, CHR(0))"
            params["stack"] = spec["stack"]
        cur.execute(sql, params)
        ntot, nn = cur.fetchone()
        ntot = int(ntot or 0)
        nn = int(nn or 0)
        if ntot <= 0:
            return False, spec, "no matching row"
        if _dekit_is_scoped(spec):
            if ntot != 1 or nn != 1:
                return False, spec, f"scoped rowcount={ntot} n_flag_n={nn}"
        elif nn != ntot:
            return False, spec, f"legacy rowcount={ntot} n_flag_n={nn}"
    return True, None, ""


def dekit_specs_from_request_items(dekit_keys):
    specs = []
    for item in dekit_keys or []:
        if not isinstance(item, dict):
            continue
        spec = _coerce_dekit_spec(item)
        if spec["vendor_sn"]:
            specs.append(spec)
    return specs


def _dekit_tuple_from_nk_row(nk, row):
    st = row.get("STACK")
    if st is not None and isinstance(st, str):
        st = st.strip() or None
    return (str(nk[1]), "" if nk[2] is None else str(nk[2]), row.get("ASSY_SEQ"), st)


def _dekit_tuple_from_spec(spec):
    st = spec.get("stack")
    if isinstance(st, str) and not st.strip():
        st = None
    return (
        spec["vendor_sn"],
        "" if spec.get("father_sn") is None else str(spec["father_sn"]),
        spec.get("assy_seq"),
        st,
    )


def sort_dekit_specs_by_tree_depth(numbered_list, specs):
    depth_map = {}
    for _, nk, row, _, _, depth in numbered_list:
        depth_map[_dekit_tuple_from_nk_row(nk, row)] = depth
    return sorted(specs, key=lambda s: depth_map.get(_dekit_tuple_from_spec(s), 999))


def insert_assy_row(conn, sn, old_vendor_sn, old_father_sn, new_vendor_sn, new_father_sn, emp, auto_commit=True):
    """INSERT new row from de-kitted source row."""
    cur = conn.cursor()
    try:
        cur.execute(KITTING_INSERT_SELECT, {"sn": sn.upper(), "old": old_vendor_sn, "old_f": old_father_sn})
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
        col_idx = {c.upper(): i for i, c in enumerate(cols)}
        if not rows:
            return False, "source_not_found"
        row = rows[0]
        idx_vendor = col_idx.get("VENDOR_SN", -1)
        idx_father = col_idx.get("FATHER_SN", -1)

        values = list(row)
        if idx_vendor >= 0:
            values[idx_vendor] = new_vendor_sn
        if idx_father >= 0 and new_father_sn is not None:
            values[idx_father] = new_father_sn
        for i, c in enumerate(cols):
            if c and c.upper() == "ASSY_FLAG":
                values[i] = "Y"
                break
        for i, c in enumerate(cols):
            if c and c.upper() == "IN_STATION_TIME":
                cur.execute("SELECT SYSDATE FROM DUAL")
                values[i] = cur.fetchone()[0]
                break
        for i, c in enumerate(cols):
            if c and c.upper() == "EMP_NO":
                values[i] = (emp or "").strip()
                break

        col_list = ", ".join(cols)
        placeholders = ", ".join(f":p{i}" for i in range(len(cols)))
        ins_sql = f"INSERT INTO SFISM4.R_ASSY_COMPONENT_T ({col_list}) VALUES ({placeholders})"
        cur.execute(ins_sql, {f"p{i}": values[i] for i in range(len(cols))})
        if auto_commit:
            conn.commit()
        return True, ""
    except Exception as e:
        if auto_commit:
            conn.rollback()
        return False, str(e)
    finally:
        cur.close()


def snapshot_tree(conn, sn):
    cols, rows = fetch_assy_tree(conn, sn)
    out = {}
    for r in rows:
        row_dict = {cols[i]: r[i] for i in range(len(cols))}
        key = (str(row_dict.get("VENDOR_SN") or ""), str(row_dict.get("FATHER_SN") or ""))
        out[key] = {
            "ASSY_FLAG": str(row_dict.get("ASSY_FLAG") or ""),
            "EMP_NO": row_dict.get("EMP_NO"),
            "IN_STATION_TIME": row_dict.get("IN_STATION_TIME"),
            "VENDOR_SN": row_dict.get("VENDOR_SN"),
            "FATHER_SN": row_dict.get("FATHER_SN"),
        }
    return out


def validate_tree_integrity(conn, sn):
    cols, rows = fetch_assy_tree(conn, sn)
    numbered_list, _ = build_numbered_tree_preserve_order(cols, rows)
    dup = {}
    for _, _, row, _, _, _ in numbered_list:
        vsn = str(row.get("VENDOR_SN") or "").strip().upper()
        assy_flag = str(row.get("ASSY_FLAG") or "").strip().upper()
        sub_model = str(row.get("SUB_MODEL_NAME") or "").strip().upper()
        is_pn_like_component = sub_model.endswith("-PN")
        if not vsn or assy_flag != "Y" or _is_config_vendor(vsn) or is_pn_like_component:
            continue
        dup[vsn] = dup.get(vsn, 0) + 1
    invalid = sorted([k for k, c in dup.items() if c > 1])
    if invalid:
        return False, invalid
    return True, []


def validate_kit_request(conn, sn, kit_list):
    cols, rows = fetch_assy_tree(conn, sn)
    numbered_list, _ = build_numbered_tree_preserve_order(cols, rows)
    existing = {}
    depth_map = {}
    for _, nk, row, _, _, depth in numbered_list:
        key = (str(nk[0]), str(nk[1]), "" if nk[2] is None else str(nk[2]))
        existing[key] = row
        depth_map[key] = depth
    mapped = {}
    errors = []
    for item in kit_list:
        ov = (item.get("old_vendor_sn") or "").strip()
        of = item.get("old_father_sn")
        ofs = "" if of is None else str(of).strip()
        nv = (item.get("new_vendor_sn") or "").strip()
        if not ov or not nv:
            errors.append("Each kit item must have old_vendor_sn and new_vendor_sn.")
            continue
        key = (sn.upper(), ov, ofs)
        row = existing.get(key)
        if not row:
            errors.append(f"Node not found in DB for ({ov}, {ofs or 'NULL'}).")
            continue
        flag = str(row.get("ASSY_FLAG") or "").upper()
        if flag not in ("Y", "N"):
            errors.append(
                f"Invalid ASSY_FLAG for node ({ov}, {ofs or 'NULL'}): expected Y or N, got {flag!r}."
            )
            continue
        mapped[key] = {"new_vendor_sn": nv, "new_father_sn": (item.get("new_father_sn") or "").strip()}
    for key, payload in mapped.items():
        _, _, old_father = key
        if not old_father:
            continue
        parent_candidates = [k for k in mapped if k[1] == old_father]
        if not parent_candidates:
            continue
        parent_key = sorted(parent_candidates, key=lambda k: depth_map.get(k, 999))[0]
        expected_parent_new = mapped[parent_key]["new_vendor_sn"]
        if payload["new_father_sn"] != expected_parent_new:
            errors.append(
                f"Parent must be kitted before child: parent {old_father} -> {expected_parent_new}, "
                f"child has new_father_sn={payload['new_father_sn']!r}"
            )
    return len(errors) == 0, errors, depth_map


def check_vendor_in_other_trays(conn, new_vendor_sns, current_sn):
    """Returns list of conflict dicts; empty if none."""
    current_upper = (current_sn or "").strip().upper()
    raw_conflicts = []
    seen = set()
    cur = conn.cursor()
    try:
        for vsn in new_vendor_sns:
            vsn_clean = (vsn or "").strip().upper()
            if not vsn_clean or _is_config_vendor(vsn_clean) or vsn_clean in seen:
                continue
            seen.add(vsn_clean)
            cur.execute(
                KITTING_CHECK_VENDOR_IN_OTHER_TRAY,
                {"vendor_sn": vsn_clean, "current_sn": current_upper},
            )
            cols = [d[0] for d in cur.description]
            for row in cur.fetchall():
                rd = dict(zip(cols, row))
                tray = (rd.get("TRAY_SN") or "").strip()
                if not tray or tray.upper() == current_upper:
                    continue
                father = rd.get("FATHER_SN")
                raw_conflicts.append(
                    {
                        "vendor_sn": vsn_clean,
                        "tray_sn": tray,
                        "father_sn": None if father is None else str(father),
                        "sub_model_name": str(rd.get("SUB_MODEL_NAME") or ""),
                    }
                )
    finally:
        cur.close()

    if not raw_conflicts:
        return []

    by_tray = {}
    for c in raw_conflicts:
        by_tray.setdefault(c["tray_sn"], []).append(c)

    enriched = []
    for tray_sn, conflicts_in_tray in by_tray.items():
        try:
            cols_t, rows_t = fetch_assy_tree(conn, tray_sn)
            if not rows_t:
                for c in conflicts_in_tray:
                    c["child_count"] = 0
                    enriched.append(c)
                continue
            numbered_list, _ = build_numbered_tree_preserve_order(cols_t, rows_t)
        except (ValueError, Exception):
            for c in conflicts_in_tray:
                c["child_count"] = 0
                enriched.append(c)
            continue

        for c in conflicts_in_tray:
            vsn_upper = c["vendor_sn"].strip().upper()
            child_count = 0
            for _, nk, row, _, _, _ in numbered_list:
                row_vsn = str(nk[1] or "").strip().upper()
                row_flag = str(row.get("ASSY_FLAG") or "").strip().upper()
                if row_vsn == vsn_upper and row_flag == "Y":
                    subtree = collect_subtree_nodes(numbered_list, nk)
                    child_count += max(0, len(subtree) - 1)
            c["child_count"] = child_count
            enriched.append(c)

    return enriched


def dekit_vendor_from_other_tray(conn, tray_sn, vendor_sn, emp, auto_commit=False):
    """Dekit vendor_sn and descendants on another tray."""
    cols, rows = fetch_assy_tree(conn, tray_sn)
    if not rows:
        return 0, ""

    numbered_list, _ = build_numbered_tree_preserve_order(cols, rows)

    target_keys = []
    vsn_want = vendor_sn.strip().upper()
    for _, nk, row, _, _, _ in numbered_list:
        row_vsn = str(nk[1] or "").strip().upper()
        row_flag = str(row.get("ASSY_FLAG") or "").strip().upper()
        if row_vsn == vsn_want and row_flag == "Y":
            target_keys.append(nk)

    if not target_keys:
        return 0, ""

    all_keys = set()
    for root_key in target_keys:
        for nk in collect_subtree_nodes(numbered_list, root_key):
            all_keys.add(nk)

    if not all_keys:
        return 0, ""

    depth_map = {nk: depth for _, nk, _, _, _, depth in numbered_list}
    flag_map = {nk: row for _, nk, row, _, _, _ in numbered_list}

    def _row_to_dekit_spec(nk, row):
        st = row.get("STACK")
        if st is not None and isinstance(st, str) and not st.strip():
            st = None
        return {
            "vendor_sn": str(nk[1] or "").strip(),
            "father_sn": nk[2],
            "assy_seq": row.get("ASSY_SEQ"),
            "stack": st,
        }

    node_keys_for_dekit = [
        _row_to_dekit_spec(nk, flag_map[nk])
        for nk in sorted(all_keys, key=lambda k: depth_map.get(k, 0), reverse=True)
        if str(flag_map.get(nk, {}).get("ASSY_FLAG") or "").upper() == "Y"
    ]

    if not node_keys_for_dekit:
        return 0, ""

    return dekit_nodes(
        conn,
        tray_sn,
        node_keys_for_dekit,
        emp,
        auto_commit=auto_commit,
        skip_missing=True,
    )
