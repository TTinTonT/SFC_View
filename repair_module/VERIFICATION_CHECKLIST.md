# Read-only packaging audit

Compare `fa_debug/routes.py` Repair handlers with `repair_module/services/`.

| Route | Service function | Status |
|-------|------------------|--------|
| `GET /api/debug/repair/options` | `services/options.py` → `get_repair_options` | PASS |
| `GET /api/debug/repair/debug-reason-codes` | `services/debug_reason_codes.py` → `list_debug_reason_codes` | PASS |
| `GET /api/debug/repair/wip` | `services/repair_wip.py` → `get_repair_wip` | PASS |
| `GET /api/debug/repair/flow-state` | `services/flow_state.py` → `get_flow_state` | PASS |
| `POST /api/debug/repair/di-next` | `services/di_next.py` → `di_next` | PASS |
| `POST /api/debug/repair/ri-next` | `services/ri_next.py` → `ri_next` | PASS |
| `POST /api/debug/repair/do-pass` | `services/do_pass.py` → `do_pass` | PASS |
| `POST /api/debug/repair/do-fail` | `services/do_fail.py` → `do_fail` | PASS |
| `POST /api/debug/repair/ro-next` | `services/ro_next.py` → `ro_next` | PASS |
| `POST /api/debug/repair/pass-jump` | `services/pass_jump.py` → `pass_jump` | PASS |
| `GET /api/debug/repair/fail-history` | `services/fail_history.py` → `get_fail_history` | PASS |
| `POST /api/debug/repair/validate-error-code` | `services/error_code.py` → `validate_error_code_service` | PASS |
| `POST /api/debug/repair/fail-input` | `services/fail_input.py` → `submit_fail_input` | PASS |
| `GET /api/debug/repair/assy-tree` | `services/assy_tree.py` → `get_assy_tree` | PASS |
| `POST /api/debug/repair/execute` | `services/execute.py` → `execute_repair` | PASS |

**Import boundary:** No `fa_debug`, `sfis_tool`, or `flask` imports under `repair_module/**/*.py` (only string mentions in docs/comments). Third-party: `oracledb`, `pytz`; stdlib otherwise.

**SQL:** Repair-related constants from `sfis_tool/sql_queries.py` are split into `repair_module/sql/*.py` (IT-only `KITTING_SQL_*` omitted per scope).
