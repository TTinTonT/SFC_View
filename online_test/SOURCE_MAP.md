# Source map (SFC_View originals)

This bundle is a **copy** of the Online Test surface from SFC_View. When updating behavior, compare with these paths in the main repo:

| Bundle path | Original in SFC_View |
|-------------|----------------------|
| `online_test/blueprint.py` | `fa_debug/routes.py` — `/api/etf/online-test/*`, `/api/debug/l10-test/online-queue*` |
| `online_test/queue.py` | `fa_debug/l10_online_test_queue.py` |
| `online_test/crabber_ctx.py` | `fa_debug/routes.py` — `_crabber_profile_scope` |
| `online_test/sn_locks.py` | `fa_debug/routes.py` — `_get_sn_lock` |
| `online_test/wip_utils.py` | `fa_debug/routes.py` — `_WIP_KEYS`, `_serialize_wip`, `_route_items`, `_norm_l10_queue_site` |
| `online_test/pn_bases.py` | `fa_debug/routes.py` — `_default_online_test_pn_bases`, `_load_custom_pn_bases`, `_save_custom_pn_bases`, `_merge_pn_base_list` |
| `online_test/deps.py` | `fa_debug/auth.py` — `resolve_sfis_emp` (import when available) |
| `online_test/static/etf_online_test_modal.js` | `static/js/etf_online_test_modal.js` |
| `online_test/templates/partials/etf_online_test_modal.html` | `templates/partials/etf_online_test_modal.html` |
| `online_test/tests/test_queue.py` | `tests/test_l10_online_test_queue.py` |

**Not copied** (remain as shared packages on `PYTHONPATH`):

- `crabber/online_test.py`, `crabber/profile.py`, `crabber/client.py` (`sn_has_active_crabber_test`)
- `sfis_tool/*` (Oracle WIP, repair, reason codes, jump route)
