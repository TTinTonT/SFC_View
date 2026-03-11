# -*- coding: utf-8 -*-
"""
Script tổng hợp: Nhập SN + form → 3 options (Repair | Kitting | Resume Kitting) → thực hiện.
"""
from config import REASON_CODES, REPAIR_ACTIONS, DUTY_TYPES
from db import get_conn
from wip import get_station_and_next, validate_next_station_r
from repair_ok import (
    execute_repair_ok,
    check_has_unrepaired,
    get_group_info,
    jump_routing,
    resolve_jump_target,
    get_jump_param_from_route,
)
from change_ok import (
    fetch_assy_tree,
    count_dekitted_parts,
    build_numbered_tree,
    expand_selection_to_flat,
    dekit_nodes,
    insert_assy_row,
)


def _do_repair_and_jump(conn, sn, next_station, station_name, line_name, group_name, emp,
                        reason_code, duty_station, remark, repair_action):
    """Thực hiện Repair OK + Jump."""
    repair_station = (
        (next_station if (next_station and str(next_station).startswith("R_")) else None)
        or station_name or str(next_station or "")
    )
    rows_ok, success, err, repair_time = execute_repair_ok(
        conn, sn, repair_station, emp, reason_code, duty_station, remark, repair_action
    )
    if not success:
        return False, err
    desired_target = resolve_jump_target(reason_code, group_name)
    target_group = get_jump_param_from_route(conn, sn, desired_target)
    info = get_group_info(conn, line_name or "", target_group)
    if info:
        ok = jump_routing(
            conn, sn,
            info["LINE_NAME"], info["SECTION_NAME"], info["GROUP_NAME"], info["STATION_NAME"],
            emp, in_station_time=repair_time
        )
        if ok:
            print(f"Jump station OK: {group_name} -> {desired_target} (param={target_group})")
        else:
            print("Jump: UPDATE không ảnh hưởng dòng nào.")
    else:
        print(f"GetGroupInfo không tìm thấy target {target_group}, bỏ qua jump.")
    return True, None


def _input_form():
    """Nhập EMP, Reason, Action, Duty, Remark. Trả về (emp, reason_code, repair_action, duty_station, remark)."""
    emp = input("EMP ID: ").strip()
    if not emp:
        return None
    print("\nReason Code:")
    for i, r in enumerate(REASON_CODES, 1):
        print(f"  {i}. {r[0]} - {r[1]}")
    rc_choice = input("Chọn (1/2) [1]: ").strip() or "1"
    idx = int(rc_choice) - 1 if rc_choice in ("1", "2") else 0
    reason_code = REASON_CODES[idx][0]

    print("\nRepair Action:")
    for i, act in enumerate(REPAIR_ACTIONS, 1):
        print(f"  {i}. {act}")
    ra_choice = input(f"Chọn (1-{len(REPAIR_ACTIONS)}) [1]: ").strip() or "1"
    try:
        ra_idx = max(0, min(int(ra_choice) - 1, len(REPAIR_ACTIONS) - 1))
    except ValueError:
        ra_idx = 0
    repair_action = REPAIR_ACTIONS[ra_idx]

    print("\nDuty Type:")
    for i, dt in enumerate(DUTY_TYPES, 1):
        print(f"  {i}. {dt}")
    dt_choice = input(f"Chọn (1-{len(DUTY_TYPES)}) [1]: ").strip() or "1"
    try:
        dt_idx = max(0, min(int(dt_choice) - 1, len(DUTY_TYPES) - 1))
    except ValueError:
        dt_idx = 0
    duty_station = DUTY_TYPES[dt_idx]

    remark = input("Remark: ").strip()
    return emp, reason_code, repair_action, duty_station, remark


def main():
    print("=== SFIS Tool - Repair / Kitting / Resume Kitting ===\n")

    sn = input("SN: ").strip()
    if not sn:
        print("SN required.")
        return

    try:
        conn = get_conn()
    except Exception as e:
        print("Connection error:", e)
        return

    try:
        row = get_station_and_next(conn, sn)
        if not row:
            print("No WIP for SN:", sn)
            return

        serial, mo, model, station_name, line_name, group_name, next_station = (
            row[0], row[1], row[2], row[3], row[4], row[5], row[6]
        )
        print(f"SN: {serial}, MO: {mo}, Model: {model}")
        print(f"Current station: {station_name}, Line: {line_name}, Group: {group_name}")
        print(f"Next station: {next_station or '(none)'}\n")

        valid, msg = validate_next_station_r(next_station)
        if not valid:
            print(msg)
            return

        if not check_has_unrepaired(conn, sn):
            print("No un-repaired record for SN. SN must have r_repair_t with repair_time IS NULL.")
            return

        form = _input_form()
        if not form:
            print("EMP ID required.")
            return
        emp, reason_code, repair_action, duty_station, remark = form

        dekitted_count = count_dekitted_parts(conn, sn)
        can_resume = dekitted_count > 0

        print("\n--- Chọn thao tác ---")
        print("  1. Repair          - Chỉ Repair OK + Jump")
        print("  2. Kitting         - De-kit/kit component rồi Repair OK + Jump")
        if can_resume:
            print("  3. Resume Kitting  - Tiếp tục kit phần đã de-kit chưa xong")
        choice = input("Chọn (1/2/3): ").strip()

        if choice == "1":
            ok, err = _do_repair_and_jump(
                conn, sn, next_station, station_name, line_name, group_name, emp,
                reason_code, duty_station, remark, repair_action
            )
            if ok:
                print("Repair OK. Rows updated.")
            else:
                print("Repair OK FAILED:", err)
            return

        if choice == "2":
            cols, rows = fetch_assy_tree(conn, sn, assy_flag='Y')
            if not rows:
                print("No kitting components (ASSY_FLAG='Y', group in KITTING_GROUP_V) for this SN.")
                return
            numbered_list, vendor_to_row = build_numbered_tree(cols, rows)
            print("\n--- Component tree (kitting groups) ---")
            for t in numbered_list:
                num, node_key, r, is_father, parent_node_key, depth = t
                vsn = node_key[0]
                group = r.get("GROUP_NAME") or ""
                flag = r.get("ASSY_FLAG") or "Y"
                pn = r.get("CUST_PN") or r.get("SUB_MODEL_NAME") or ""
                rev = r.get("CUST_REV") or r.get("SUB_REV") or "N/A"
                mid = f" {pn} Rev:{rev}" if pn else ""
                prefix = f"  {num}.● " if depth == 0 else f"  {num}.  " + "  " * (depth - 1) + "├── "
                print(f"{prefix}[{vsn}]{mid} ({group}) FLAG={flag}")

            sel_input = input(
                "\nChọn số thứ tự component muốn de-kit/thay (nhiều số cách nhau space/dấu phẩy, 0 = bỏ qua): "
            ).strip()
            if sel_input == "0" or not sel_input:
                ok, err = _do_repair_and_jump(
                    conn, sn, next_station, station_name, line_name, group_name, emp,
                    reason_code, duty_station, remark, repair_action
                )
                if ok:
                    print("Repair OK (no kitting). Rows updated.")
                else:
                    print("Repair OK FAILED:", err)
                return
            parts = sel_input.replace(",", " ").split()
            selected_numbers = [p.strip() for p in parts if p.strip()]
            sel_flat = expand_selection_to_flat(numbered_list, vendor_to_row, selected_numbers)
            if not sel_flat:
                print("Không có component nào được chọn.")
                return

            print("\n--- De-kit ---")
            n, err = dekit_nodes(conn, sn, [t[1] for t in sel_flat], emp)
            if err:
                print("De-kit FAILED:", err)
                return
            print(f"De-kit OK. Rows updated: {n}")

            print("\n--- Nhập SN mới cho từng node (cha trước, con sau) ---")
            new_sn_list = []
            new_vendor_by_old = {}
            external_new_father = {}
            for num, node_key, r, is_father, parent_node_key, depth in sel_flat:
                old_father = node_key[1]
                if parent_node_key is not None:
                    new_father = new_vendor_by_old.get(parent_node_key)
                elif old_father is not None:
                    if old_father not in external_new_father:
                        external_new_father[old_father] = input(
                            f"Parent [{old_father}] đã kit trước. Nhập SN mới của parent: "
                        ).strip()
                        if not external_new_father[old_father]:
                            print("SN parent không được để trống.")
                            return
                    new_father = external_new_father[old_father]
                else:
                    new_father = None
                new_v = input(f"SN mới cho component {num} [{node_key[0]}]: ").strip()
                if not new_v:
                    print("SN mới không được để trống.")
                    return
                new_sn_list.append((node_key[0], node_key[1], new_v, new_father))
                new_vendor_by_old[node_key] = new_v

            print("\n--- Kit ---")
            for old_v, old_f, new_v, new_father in new_sn_list:
                ok, err = insert_assy_row(conn, sn, old_v, old_f, new_v, new_father, emp)
                if not ok:
                    print(f"INSERT FAILED for {old_v} -> {new_v}: {err}")
                    return
            print("Kit OK. Inserted", len(new_sn_list), "rows.")

            ok, err = _do_repair_and_jump(
                conn, sn, next_station, station_name, line_name, group_name, emp,
                reason_code, duty_station, remark, repair_action
            )
            if ok:
                print("Repair OK. Rows updated.")
            else:
                print("Repair OK FAILED:", err)
            return

        if choice == "3" and can_resume:
            cols, rows = fetch_assy_tree(conn, sn, assy_flag='N')
            if not rows:
                print("Không tìm thấy part de-kit (có thể đã kit xong).")
                return
            numbered_list, vendor_to_row = build_numbered_tree(cols, rows)
            print("\n--- Part đã de-kit (resume kit) ---")
            for t in numbered_list:
                num, node_key, r, is_father, parent_node_key, depth = t
                vsn = node_key[0]
                group = r.get("GROUP_NAME") or ""
                flag = r.get("ASSY_FLAG") or "N"
                pn = r.get("CUST_PN") or r.get("SUB_MODEL_NAME") or ""
                rev = r.get("CUST_REV") or r.get("SUB_REV") or "N/A"
                mid = f" {pn} Rev:{rev}" if pn else ""
                prefix = f"  {num}.● " if depth == 0 else f"  {num}.  " + "  " * (depth - 1) + "├── "
                print(f"{prefix}[{vsn}]{mid} ({group}) FLAG={flag}")

            sel_flat = list(numbered_list)
            print("\n--- Nhập SN mới cho từng node (cha trước, con sau) ---")
            new_sn_list = []
            new_vendor_by_old = {}
            external_new_father = {}
            for num, node_key, r, is_father, parent_node_key, depth in sel_flat:
                old_father = node_key[1]
                if parent_node_key is not None:
                    new_father = new_vendor_by_old.get(parent_node_key)
                elif old_father is not None:
                    if old_father not in external_new_father:
                        external_new_father[old_father] = input(
                            f"Parent [{old_father}] đã kit trước. Nhập SN mới của parent: "
                        ).strip()
                        if not external_new_father[old_father]:
                            print("SN parent không được để trống.")
                            return
                    new_father = external_new_father[old_father]
                else:
                    new_father = None
                new_v = input(f"SN mới cho component {num} [{node_key[0]}]: ").strip()
                if not new_v:
                    print("SN mới không được để trống.")
                    return
                new_sn_list.append((node_key[0], node_key[1], new_v, new_father))
                new_vendor_by_old[node_key] = new_v

            print("\n--- Kit ---")
            for old_v, old_f, new_v, new_father in new_sn_list:
                ok, err = insert_assy_row(conn, sn, old_v, old_f, new_v, new_father, emp)
                if not ok:
                    print(f"INSERT FAILED for {old_v} -> {new_v}: {err}")
                    return
            print("Kit OK. Inserted", len(new_sn_list), "rows.")

            ok, err = _do_repair_and_jump(
                conn, sn, next_station, station_name, line_name, group_name, emp,
                reason_code, duty_station, remark, repair_action
            )
            if ok:
                print("Repair OK. Rows updated.")
            else:
                print("Repair OK FAILED:", err)
            return

        print("Lựa chọn không hợp lệ.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
