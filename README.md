# SFC View

Flask app for SFC Fail Result analytics, bonepile upload/disposition, ETF status, and debug tools. Port and paths are configurable.

## Structure

```
SFC_View/
├── app.py                 # Flask entrypoint; thin routes delegate to services
├── config/                 # Central configuration
│   ├── app_config.py       # Paths, Flask, SFC, export formatting
│   ├── analytics_config.py # Pass rules, stations_order, timezone, error-stats defaults
│   ├── analytics_config.json
│   ├── pass_rules.py       # Part number → pass station (uses analytics_config)
│   ├── bonepile_config.py  # BONEPILE_IGNORED_SHEETS, BP_SN_CACHE_PATH
│   ├── debug_config.py     # FA Debug: poll interval, WS terminal, SSH, Crabber
│   └── etf_config.py       # ETF: ROOMS (SSH, script_path, state_dir), poll interval
├── sfc/                    # SFC API client and HTML parser
│   ├── client.py           # request_fail_result (login, session, fetch)
│   └── parser.py           # parse_fail_result_html, rows_to_csv
├── analytics/               # Analytics computation and service layer
│   ├── compute.py          # compute_all (summary, tray_summary, sku_rows, test_flow)
│   ├── sn_list.py          # compute_sn_list (drill-down)
│   ├── error_stats.py      # compute_error_stats, compute_error_stats_sn_list
│   ├── pass_fail.py        # is_sn_passed
│   ├── bp_check.py         # add_bp_to_rows
│   └── service.py          # run_analytics_query, get_sn_list, run_error_stats, run_fail_result_rows
├── bonepile_disposition.py # Upload/parse NV workbook, BP cache, disposition stats/SN list, clear_disposition_cache
├── etf/                     # ETF Status blueprint
├── fa_debug/                # FA Debug Place blueprint
└── templates/               # analytics_dashboard, etf_status, fa_debug
```

## Install and run

```bash
pip install -r requirements.txt
python app.py
```

Open http://localhost:5556 (or the port set by `FLASK_PORT`).

## Configuration

- **config/app_config.py** – Central: `APP_DIR`, `ANALYTICS_CACHE_DIR`, template paths, `FLASK_HOST`/`FLASK_PORT`/`FLASK_DEBUG`, SFC URL/user/password, disposition XLSX fill colors.
- **config/analytics_config.json** – Pass rules, `stations_order`, `timezone`, `extend_hours`, `top_k_errors_default`, etc. Edited via UI (Pass Rules) or file.
- **config/bonepile_config.py** – `BONEPILE_IGNORED_SHEETS`, `BP_SN_CACHE_PATH`.
- **config/debug_config.py** – `POLL_INTERVAL_SEC`, `LOOKBACK_HOURS`, `WS_TERMINAL_URL`, `UPLOAD_URL`, SSH and Crabber URLs (env overrides).
- **config/etf_config.py** – `ROOMS` (per-room SSH, script_path, state_dir), `ETF_POLL_INTERVAL_SEC`, `SFC_TRAY_STATUS_URL`, `SFC_LEVEL_GRADE` (env overrides).

Environment variables (examples): `SFC_BASE_URL`, `SFC_USER`, `SFC_PWD`, `FLASK_PORT`, `FLASK_DEBUG`, `ETF_POLL_INTERVAL_SEC`, `SFC_TRAY_STATUS_URL`, `SFC_LEVEL_GRADE`, and per-room ETF/SSH vars (see etf_config.py, debug_config.py).

## Main APIs

- **POST /api/query** – Apply filter; body `{ start_datetime, end_datetime, aggregation? }` → summary, tray_summary, sku_rows, test_flow, unassigned_part_numbers.
- **GET/POST /api/analytics/pass-rules** – Get or save pass rules.
- **POST /api/sn-list** – SN drill-down; uses last query result.
- **POST /api/error-stats** – Error stats (top K, fail by station, TTC).
- **POST /api/error-stats-sn-list** – Error-stats drill-down SN list.
- **POST /api/export** – Export CSV or XLSX (summary, sku, disposition_summary, disposition_by_sku, error_stats, or default fail_result CSV).
- **POST /api/clear-cache** – Clear disposition cache and in-memory query result.
- **GET /api/bonepile/status**, **POST /api/bonepile/upload**, **POST /api/bonepile/parse**, **GET /api/bonepile/disposition**, **POST /api/bonepile/disposition/sn-list** – Bonepile upload and disposition.
- **GET /api/sfc/tray-status** – Proxy SFC Test_Fixture_Status (POST JSON `{"Level_Grade":"L10"}`); returns `{ ok, sn_map }` for ETF Tray Status (Slot, Last End Time as live duration, SFC Remark).

Legacy: **POST /api/fail_result** returns rows + CSV (dashboard uses /api/query).
