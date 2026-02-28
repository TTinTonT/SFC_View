# Refactor inventory (Step 1)

## Module map and responsibilities

| Module | Responsibility | Key entrypoints | Notes |
|--------|----------------|-----------------|--------|
| app.py | Flask entrypoint, routes, export XLSX/CSV builders, datetime parsing | index, api_query, api_export_csv, api_clear_cache, bonepile routes | Heavy: template paths, _build_export_xlsx, _build_dispo_*, _error_stats_to_csv, _parse_datetime. Should delegate to services. |
| config/app_config.py | App-level paths, re-exports from analytics_config | APP_DIR, ANALYTICS_CACHE_DIR, EXTEND_HOURS, CA_TZ, STATIONS_ORDER, TOP_K_ERRORS_DEFAULT | Thin; should own all app paths (templates, cache). |
| config/analytics_config.py | Analytics JSON load/save, pass_rules, stations_order, timezone, error_stats defaults | get_pass_rules, set_pass_rules, get_stations_order, get_ca_tz, get_extend_hours, get_top_k_errors_default, get_error_stats_ttc_buckets, get_error_stats_p90 | Central for analytics. |
| config/pass_rules.py | Map part_number -> pass station (uses analytics_config) | get_pass_station_for_part_number, is_sn_passed | Pure logic; used by analytics. |
| config/bonepile_config.py | BONEPILE_IGNORED_SHEETS, BP_SN_CACHE_PATH | - | BONEPILE_IGNORED_SHEETS is long list; could live in JSON. |
| config/debug_config.py | FA Debug: POLL_INTERVAL_SEC, LOOKBACK_HOURS, WS_TERMINAL_URL, UPLOAD_URL, SSH_*, CRABBER_* | - | All env-backed; keep as single source. |
| config/etf_config.py | ETF ROOMS (per-room SSH, script_path, state_dir) | - | Env-backed; keep. |
| analytics/compute.py | compute_all from SFC rows: summary, tray_summary, sku_rows, breakdown_rows, test_flow, unassigned_part_numbers | compute_all | Uses CA_TZ, STATIONS_ORDER, add_bp_to_rows, is_sn_passed. |
| analytics/sn_list.py | compute_sn_list for drill-down | compute_sn_list | Uses computed from compute_all. |
| analytics/error_stats.py | compute_error_stats, compute_error_stats_sn_list | compute_error_stats, compute_error_stats_sn_list | Uses STATIONS_ORDER, get_error_stats_ttc_buckets, get_error_stats_p90. |
| analytics/bp_check.py | add_bp_to_rows, load_bp_sn_set (wrapper to bonepile_disposition) | add_bp_to_rows, load_bp_sn_set | Thin wrapper. |
| analytics/pass_fail.py | is_sn_passed(rows_for_sn) | is_sn_passed | Uses pass_rules. |
| bonepile_disposition.py | Upload, parse, BP cache, disposition stats, SN list, RawState, jobs | ensure_db_ready, compute_disposition_stats, compute_disposition_sn_list, invalidate_bp_sn_cache, RawState, run_bonepile_parse_job, _parse_ca_input_datetime, utc_ms | Duplicates APP_DIR, ANALYTICS_CACHE_DIR, CA_TZ; should use config. |
| sfc/client.py | SFC login, request_fail_result (with extend_hours) | request_fail_result | SFC_BASE_URL, LOGIN_URL, FAIL_RESULT_URL, SFC_USER, SFC_PWD, GROUP_NAME, SESSION_TTL_SECONDS hardcoded or env. |
| sfc/parser.py | parse_fail_result_html, rows_to_csv | parse_fail_result_html, rows_to_csv | Column indices; stable. |
| etf/routes.py | Blueprint: /etf, /api/etf/*, scan, reset, remarks | - | Uses ROOMS, ANALYTICS_CACHE_DIR; ETF_POLL_INTERVAL_SEC=60 local. |
| fa_debug/routes.py | Blueprint: /debug, /api/debug-*, poller | - | Uses LOOKBACK_HOURS, POLL_INTERVAL_SEC, ANALYTICS_CACHE_DIR. |

## Hardcoded config (by category)

- **App-level:** app.py: APP_DIR, TEMPLATES_DIR, SKU_SUMMARY_TEMPLATE_PATH, TRAY_SUMMARY_TEMPLATE_PATH, SKU_DISPO_TEMPLATE_PATH, port 5556, host "0.0.0.0". scripts/update_tray_summary_template.py: TEMPLATE_PATH.
- **Analytics/export colors:** app.py: E8D5B7, FFF8E7 in _build_dispo_sn_list_xlsx.
- **Bonepile:** bonepile_disposition.py: APP_DIR, ANALYTICS_CACHE_DIR, DB_PATH, STATE_PATH, BONEPILE_UPLOAD_PATH, BP_SN_CACHE_PATH, CA_TZ="America/Los_Angeles", BONEPILE_REQUIRED_FIELDS. config/bonepile_config: BONEPILE_IGNORED_SHEETS (long list).
- **SFC:** sfc/client.py: SFC_BASE_URL default, SFC_USER, SFC_PWD, GROUP_NAME, SESSION_TTL_SECONDS=30*60, FAIL_RESULT_URL, LOGIN_URL.
- **ETF:** etf_config.py: ROOMS with default IPs and paths; etf/routes: ETF_POLL_INTERVAL_SEC=60, _remarks_path, _cache_dir from ANALYTICS_CACHE_DIR.
- **Debug:** debug_config.py: POLL_INTERVAL_SEC, LOOKBACK_HOURS, WS_TERMINAL_URL, UPLOAD_URL, SSH_*, CRABBER_*.
- **Timezone:** analytics_config.json default "America/Los_Angeles"; bonepile_disposition.py duplicates CA_TZ.

## Suspected dead / duplicate code

- app.py: _parse_datetime duplicated in fa_debug/routes.py as _parse_dt (similar logic). Consider single shared helper in a util or config.
- bonepile_disposition: Defines ANALYTICS_CACHE_DIR, APP_DIR, CA_TZ again; should import from config.
- config/app_config: TOP_K_ERRORS_DEFAULT from analytics_config; already centralized.
- No obvious unused routes; /api/fail_result is "Legacy" but may still be called.

## Next steps (from plan)

- Centralize all paths and template names in app_config.
- Move export colors and disposition XLSX defaults to config (or analytics_config).
- Make bonepile_disposition use config for paths and CA_TZ.
- Extract analytics and disposition "service" functions from app.py; thin routes.
- Standardize comments to English; remove redundant ones.
- Remove or quarantine unused code after verification.
