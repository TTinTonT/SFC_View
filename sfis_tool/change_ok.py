# -*- coding: utf-8 -*-
"""
Change OK (de-kit/kit): fetch_assy_tree, count_dekitted_parts, build_numbered_tree,
expand_selection_to_flat, dekit_nodes, insert_assy_row.
"""
from .sql_queries import (
    KITTING_FETCH_ASSY_TREE,
    KITTING_COUNT_DEKITTED,
    KITTING_DEKIT_UPDATE,
    KITTING_INSERT_SELECT,
)


def fetch_assy_tree(conn, sn, assy_flag='Y'):
    """Lấy row R_ASSY_COMPONENT_T cho SN, ASSY_FLAG=assy_flag. Trả về (cols, rows)."""
    cur = conn.cursor()
    try:
        cur.execute(KITTING_FETCH_ASSY_TREE, {"sn": sn.upper(), "flag": assy_flag})
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
        return cols, rows
    finally:
        cur.close()


def count_dekitted_parts(conn, sn):
    """Đếm số part ASSY_FLAG='N' trong KITTING_GROUP."""
    cur = conn.cursor()
    try:
        cur.execute(KITTING_COUNT_DEKITTED, [sn.upper()])
        return cur.fetchone()[0]
    finally:
        cur.close()


def build_numbered_tree(cols, rows):
    """Dựng cây theo FATHER_SN. Trả về (numbered_list, vendor_to_row)."""
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

    vendor_sns_set = set(vsn for vsn, _, _ in rows_list)
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
    Build numbered tree preserving the order of `rows` (SQL order).
    Returns (numbered_list, vendor_to_row). numbered_list is list of
    (num, node_key, row, is_father, parent_node_key, depth) in same order as rows.
    """
    col_idx = {c.upper(): i for i, c in enumerate(cols)}
    idx_vendor = col_idx.get("VENDOR_SN", -1)
    idx_father = col_idx.get("FATHER_SN", -1)

    vendor_to_row = {}
    rows_in_order = []
    for r in rows:
        row_dict = {cols[i]: r[i] for i in range(len(cols))}
        vsn = r[idx_vendor] if idx_vendor >= 0 else None
        father = row_dict.get("FATHER_SN") if idx_father >= 0 else None
        if vsn is not None:
            node_key = (vsn, father)
            vendor_to_row[node_key] = row_dict
            rows_in_order.append((node_key, row_dict))

    vendor_sns_set = set(nk[0] for nk, _ in rows_in_order)
    children_of = {}
    for node_key, _ in rows_in_order:
        vsn, father = node_key
        if father is not None and father in vendor_sns_set:
            children_of.setdefault(father, []).append(node_key)

    def parent_node_key_of(node_key):
        vsn, father = node_key
        if father is None:
            return None
        return next((k for k in vendor_to_row if k[0] == father), None)

    depth_cache = {}

    def get_depth(node_key):
        if node_key in depth_cache:
            return depth_cache[node_key]
        pnk = parent_node_key_of(node_key)
        d = 0 if pnk is None else 1 + get_depth(pnk)
        depth_cache[node_key] = d
        return d

    num_by_key = {}
    for i, (node_key, _) in enumerate(rows_in_order):
        num_by_key[node_key] = i + 1

    numbered_list = []
    for i, (node_key, row) in enumerate(rows_in_order):
        num = i + 1
        vsn, father = node_key
        is_father = vsn in children_of
        pnk = parent_node_key_of(node_key)
        parent_num = num_by_key.get(pnk) if pnk else None
        depth = get_depth(node_key)
        numbered_list.append((num, node_key, row, is_father, parent_num, depth))

    return numbered_list, vendor_to_row


def expand_selection_to_flat(numbered_list, vendor_to_row, selected_numbers):
    """Mở rộng selection: father -> cả cụm. Trả về list (num, node_key, row, is_father, parent_node_key, depth)."""
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
    """Trả về set node_key thuộc cây con của root."""
    parent_vsns = set(k[0] for k in vendor_to_row)
    children_of = {}
    for (vsn, father), row in vendor_to_row.items():
        if father is not None and father in parent_vsns:
            children_of.setdefault(father, []).append((vsn, father))
    out = {root_node_key}
    stack = [root_node_key]
    while stack:
        v, f = stack.pop()
        for ck in children_of.get(v, []):
            out.add(ck)
            stack.append(ck)
    return out


def dekit_nodes(conn, sn, node_keys, emp):
    """UPDATE ASSY_FLAG='N' cho từng row (VENDOR_SN, FATHER_SN)."""
    if not node_keys:
        return 0, ""
    cur = conn.cursor()
    try:
        total = 0
        for v, f in node_keys:
            cur.execute(KITTING_DEKIT_UPDATE, {"sn": sn.upper(), "emp": (emp or "").strip(), "v": v, "f": f})
            total += cur.rowcount
        conn.commit()
        return total, ""
    except Exception as e:
        conn.rollback()
        return 0, str(e)
    finally:
        cur.close()


def insert_assy_row(conn, sn, old_vendor_sn, old_father_sn, new_vendor_sn, new_father_sn, emp):
    """INSERT row mới từ row cũ (sau de-kit)."""
    cur = conn.cursor()
    try:
        cur.execute(KITTING_INSERT_SELECT, {"sn": sn.upper(), "old": old_vendor_sn, "old_f": old_father_sn})
        row = cur.fetchone()
        if not row:
            return False, "Row not found"
        cols = [d[0] for d in cur.description]
        col_idx = {c.upper(): i for i, c in enumerate(cols)}
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
        conn.commit()
        return True, ""
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        cur.close()
