# Host injectables (when not using SFC_View as-is)

| Concern | SFC_View | Other Flask app |
|---------|----------|-----------------|
| Oracle / SFIS | `sfis_tool` on `PYTHONPATH` | Same: install or copy `sfis_tool` + Oracle config |
| Crabber HTTP | `crabber` package | Same |
| EMP for repair/start | `fa_debug.auth.resolve_sfis_emp` | Implement `request.current_user` with `employee_id`, or patch `online_test.deps.resolve_sfis_emp` |
| SN mutex | `online_test.sn_locks` (separate dict from Repair page) | Optional: share one global lock registry if you merge with another repair bundle |
