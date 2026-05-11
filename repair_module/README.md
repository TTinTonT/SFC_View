# Repair module (SFC_View)

Python-only library that mirrors every **Repair page** backend API from SFC_View (`/api/debug/repair/*`). Use it in any host app (Flask, FastAPI, CLI): open an Oracle connection is handled internally via `get_conn()`.

**Not included:** HTML/JS, Flask routes, Jump Station page, standalone `dido.py`, IT Kitting SQL admin page.

## Requirements

- Python 3.10+ (recommended)
- Oracle Instant Client on the machine (or thin mode if applicable)
- `pip install -r repair_module/requirements.txt` (`oracledb`, `pytz`)

## Configuration

Edit **[config/db_config.py](config/db_config.py)**:

| Variable | Description |
|----------|-------------|
| `CONN_USER` | Oracle username |
| `CONN_PASSWORD` | Oracle password |
| `CONN_DSN` | DSN / service name |
| `ORACLE_CLIENT_DIR` | Path to Oracle Instant Client (optional if using thin client) |

Edit **[config/repair_config.py](config/repair_config.py)** for dropdown options: `REASON_CODES`, `REPAIR_ACTIONS`, `DUTY_TYPES`, `REPAIR_ACTION_RECORD_MAP`.

## Install in another project

1. Copy the entire `repair_module/` directory into your project root (or onto `PYTHONPATH`).
2. `pip install -r repair_module/requirements.txt`
3. Configure `repair_module/config/db_config.py` (and optionally `repair_config.py`).
4. Import:

```python
from repair_module import get_flow_state, execute_repair

state = get_flow_state("ABC123456")
print(state)

out = execute_repair({
    "sn": "ABC123456",
    "emp": "E12345",
    "action": "repair",
    "reason_code": "RC36",
    "desired_target": "FLA",
    "repair_action": "REPLACE",
    "duty_station": "TEST FIXTURE",
    "remark": "retest",
})
print(out)
```

**Employee ID:** SFC_View resolves `emp` / `emp_no` from the logged-in user. In this library you pass the SFIS employee string explicitly on every call that needs it.

## Module mapping (SFC_View → repair_module)

| SFC_View | repair_module |
|----------|----------------|
| `sfis_tool/repair_ok.py` | `core/repair_actions.py` |
| `sfis_tool/change_ok.py` | `core/kitting.py` |
| `sfis_tool/repair_flow.py` | `core/flow_state.py` |
| `sfis_tool/jump_route.py` (subset) | `core/routing.py` |
| `sfis_tool/oracle_sp.py` | `core/sfis_sp.py` |
| `sfis_tool/qa_lock.py` | `core/qa_lock.py` |
| `sfis_tool/sql_queries.py` (repair-related) | `sql/*.py` |
| `sfis_tool/config.py` | `config/db_config.py` + `config/repair_config.py` |
| `fa_debug/routes.py` SN lock + cache | `core/sn_locks.py` |
| `fa_debug/routes.py` `_dt_to_cali` | `core/time_utils.py` `format_time_pacific` |

## Service functions ↔ former HTTP API

Every function returns a **plain `dict`** (same shape as the former JSON body). Check `ok: bool`; on failure read `error` (string). Some endpoints add extra keys (`wip`, `rows`, `valid`, etc.).

| Function | Former route | Parameters |
|----------|--------------|------------|
| `get_repair_options()` | `GET /api/debug/repair/options` | None |
| `list_debug_reason_codes()` | `GET /api/debug/repair/debug-reason-codes` | None |
| `get_repair_wip(sn)` | `GET /api/debug/repair/wip` | **sn** (str) |
| `get_flow_state(sn)` | `GET /api/debug/repair/flow-state` | **sn** (str, uppercased internally) |
| `get_assy_tree(sn)` | `GET /api/debug/repair/assy-tree` | **sn** (str) |
| `get_fail_history(sn)` | `GET /api/debug/repair/fail-history` | **sn** (str) |
| `validate_error_code_service(error_code)` | `POST .../validate-error-code` | **error_code** (str) |
| `submit_fail_input(sn, error_code, emp="")` | `POST .../fail-input` | **sn**, **error_code**, **emp** |
| `di_next(sn, base, emp_no="")` | `POST .../di-next` | **sn**, **base**, **emp_no** |
| `ri_next(sn, base, emp_no="")` | `POST .../ri-next` | same |
| `do_pass(sn, base, reason_code, remark="", emp="")` | `POST .../do-pass` | **sn**, **base**, **reason_code**, remark, **emp** |
| `do_fail(sn, base, reason_code, emp="")` | `POST .../do-fail` | **sn**, **base**, **reason_code**, **emp** |
| `ro_next(sn, base, reason_code, remark="", emp="")` | `POST .../ro-next` | **sn**, **base**, **reason_code**, remark, **emp** |
| `pass_jump(sn, target_group, emp_no="")` | `POST .../pass-jump` | **sn**, **target_group**, **emp_no** |
| `execute_repair(data)` | `POST .../execute` | **data** dict — see below |

### `execute_repair(data)` payload

| Key | Type | Required | Description |
|-----|------|----------|-------------|
| `sn` | str | yes | Serial number |
| `emp` | str | for mutations | SFIS employee id |
| `action` | str | default `repair` | `repair` \| `dekit` \| `kitting` |
| `reason_code` | str | default `RC500` | e.g. `RC36`, `RC500` |
| `desired_target` | str | no | Jump target; use `__AUTO_RC500__` for auto RC500 |
| `repair_action` | str | default `REPLACE` | From `REPAIR_ACTIONS` |
| `duty_station` | str | default `TEST FIXTURE` | |
| `remark` | str | default `retest` | |
| `kit_list` | list[dict] | no | Each item: `old_vendor_sn`, `old_father_sn`, `new_vendor_sn`, `new_father_sn` |
| `dekit_keys` | list[dict] | for `dekit` | Each: `vendor_sn`, `father_sn`; optional `assy_seq`, `stack` pin one DB row when vendor SN repeats |
| `force_continue` | bool | no | Skip QA PPID lock check on kit |
| `force_dekit_other_tray` | bool | no | Allow cross-tray dekit when vendor conflicts |
| `request_id` | str | no | Idempotent replay cache key (TTL 300s, in-process only) |

**Concurrency:** `execute_repair` uses a per-process lock per SN (same as SFC_View). For multiple worker processes, behavior matches one Gunicorn worker per machine unless you add an external lock.

## Error semantics

- Normal business failures return `{"ok": False, "error": "..."}` without raising.
- Oracle / programming errors are caught and returned as `{"ok": False, "error": str(e)}` where applicable; `call_new_test_input_z` may still raise on unexpected DB errors (same as original).

## SQL layout

All SQL lives under `repair_module/sql/`:

- `wip_sql.py` — WIP lookup  
- `repair_sql.py` — repair + error-code validation  
- `kitting_sql.py` — assy tree / kit / dekit  
- `jump_sql.py` — route list + jump-station assy checks (used by flow-state / RC500)  
- `reason_code_sql.py` — DEBUG reason codes for DO/RO  
- `history_sql.py` — fail history  

## Packaging audit

See **[VERIFICATION_CHECKLIST.md](VERIFICATION_CHECKLIST.md)** for the route ↔ service mapping used to confirm coverage.

## License / origin

Extracted from the internal SFC_View project for reuse; adjust credentials and SQL for your environment.
