# Tool SFIS - Repair, Kitting, Jump Route

Tool Python cho SFIS: Repair OK, Change OK (de-kit/kit), Jump Route (T11). Các module nhỏ, có thể import từng function sang app khác.

## Yêu cầu

- Python 3
- `oracledb` (`pip install oracledb`)
- Oracle Instant Client (chỉnh `ORACLE_CLIENT_DIR` trong `config.py`)

## Cấu hình

Sửa file **`config.py`**:

- `CONN_USER`, `CONN_PASSWORD`, `CONN_DSN` – kết nối Oracle
- `ORACLE_CLIENT_DIR` – đường dẫn Oracle Instant Client
- `REASON_CODES`, `REPAIR_ACTIONS`, `DUTY_TYPES` – lựa chọn form

## Cách chạy

| Script | Lệnh | Mô tả |
|--------|------|-------|
| **Main (tổng hợp)** | `python main.py` | SN + form → 3 options: Repair \| Kitting \| Resume Kitting |
| Jump Route (T11) | `python jump_route.py` | Chọn route, jump R_WIP_TRACKING_T |

## Cấu trúc file

| File | Mô tả |
|------|-------|
| `config.py` | Cấu hình DB, Reason codes, Repair actions, Duty types |
| `sql_queries.py` | Tất cả câu SQL |
| `db.py` | Kết nối DB: `get_conn()` |
| `wip.py` | Module WIP |
| `repair_ok.py` | Module Repair OK (check_has_unrepaired, execute_repair_ok, jump_routing, ...) |
| `change_ok.py` | Module Change OK (de-kit/kit: fetch_assy_tree, dekit_nodes, insert_assy_row, ...) |
| `main.py` | Script tổng hợp: form → 3 options |
| `jump_route.py` | Script Jump Route (T11) |

## Mô tả module và function

### config.py

- `CONN_USER`, `CONN_PASSWORD`, `CONN_DSN`, `ORACLE_CLIENT_DIR`
- `REASON_CODES`, `REPAIR_ACTIONS`, `DUTY_TYPES`
- `REPAIR_ACTION_RECORD_MAP` (map Repair action -> RECORD_TYPE)

### sql_queries.py

Chứa tất cả SQL dưới dạng constant. Sửa ở đây khi cần đổi query.

### db.py

- **`get_conn()`** – Trả về connection Oracle. Dùng `try/except` khi gọi.

### wip.py

- **`get_station_and_next(conn, sn)`** – Lấy SN, MO, Model, STATION, LINE, GROUP, NEXT_STATION. Trả về tuple hoặc None.
- **`validate_next_station_r(next_station)`** – Kiểm tra next station hợp lệ cho Repair OK. Trả về `(valid: bool, msg: str)`.

### repair_ok.py

- **`check_has_unrepaired(conn, sn)`** – Kiểm tra SN có r_repair_t với repair_time IS NULL.
- **`execute_repair_ok(conn, sn, repair_station, emp, reason_code, duty_station, remark, repair_action)`** – UPDATE r_repair_t. Trả về `(rows, success, err, repair_time)`.
- **`get_group_info(conn, v_line, v_group)`** – Lấy LINE, SECTION, GROUP, STATION cho target group. Trả về dict hoặc None.
- **`resolve_jump_target(reason_code, current_group)`** – RC36->FLA, RC500 bỏ R_. Trả về target string.
- **`get_jump_param_from_route(conn, sn, desired_target)`** – Lấy GROUP_NAME từ C_ROUTE_CONTROL_T.
- **`jump_routing(conn, sn, v_line, v_section, v_group, v_station, emp, in_station_time=None)`** – UPDATE R_WIP_TRACKING_T. Trả về bool.

### change_ok.py

- **`fetch_assy_tree(conn, sn, assy_flag)`** – Lấy R_ASSY_COMPONENT_T. Trả về `(cols, rows)`.
- **`count_dekitted_parts(conn, sn)`** – Đếm part ASSY_FLAG='N' trong KITTING_GROUP.
- **`build_numbered_tree(cols, rows)`** – Dựng cây component. Trả về `(numbered_list, vendor_to_row)`.
- **`expand_selection_to_flat(numbered_list, vendor_to_row, selected_numbers)`** – Mở rộng selection (father -> cả cụm).
- **`dekit_nodes(conn, sn, node_keys, emp)`** – UPDATE ASSY_FLAG='N'. Trả về `(total, err_msg)`.
- **`insert_assy_row(conn, sn, old_v, old_f, new_v, new_f, emp)`** – INSERT row mới (kit). Trả về `(ok: bool, err_msg)`.

### main.py

- **`main()`** – Script tổng hợp: Nhập SN → form (EMP, Reason, Action, Duty, Remark) → 3 options (Repair \| Kitting \| Resume Kitting) → thực hiện.

### jump_route.py

- **`main()`** – CLI: SN -> hiển thị route -> chọn -> CheckJumpStation (optional) -> jump.
- **`get_wip(conn, sn)`** – Lấy WIP 1 SN.
- **`get_route_list(conn, sn)`** – Lấy route có thể jump (FLAG=0).
- **`check_jump_station(conn, target_group, sn)`** – CheckJumpStation (ASSY_VIP).

## Import trong app khác

```python
# Chỉ cần Repair OK
from sfis_tool.repair_ok import execute_repair_ok, check_has_unrepaired, jump_routing

# Chỉ cần de-kit/kit
from sfis_tool.change_ok import fetch_assy_tree, dekit_nodes, insert_assy_row

# WIP + validation
from sfis_tool.wip import get_station_and_next, validate_next_station_r
```

Thêm `sfis_tool` vào `PYTHONPATH` hoặc copy thư mục vào project.
