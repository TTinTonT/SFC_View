# Portable Online Test bundle (from SFC_View)

Self-contained **copy** of the ETF **Online Test** HTTP API and the **L10 per-fixture queue**, plus the shared **modal** JS/HTML. Use this folder in another Flask app (or keep it in SFC_View as reference only).

> **SFC_View constraint:** This repo’s original `fa_debug/routes.py`, `app.py`, etc. are **not** modified. To actually serve these routes **inside SFC_View**, you would register the blueprint yourself (optional); otherwise this folder is for **copy/export** only.

## What you get

| HTTP prefix | Purpose |
|-------------|---------|
| `/api/etf/online-test/wip` | WIP + next station + Crabber busy flag |
| `/api/etf/online-test/reason-codes` | DEBUG reason codes |
| `/api/etf/online-test/pn-list` | GET/POST/DELETE PN bases for Crabber |
| `/api/etf/online-test/repair` | Close repair + jump (retest) |
| `/api/etf/online-test/prepare` | Crabber PN mapping / shelf |
| `/api/etf/online-test/start` | Crabber start sequence |
| `/api/debug/l10-test/online-queue` | GET queue snapshot (sj + sv) |
| `/api/debug/l10-test/online-queue/enqueue` | POST |
| `/api/debug/l10-test/online-queue/complete` | POST |
| `/api/debug/l10-test/online-queue/abandon` | POST |
| `/api/debug/l10-test/online-queue/force-next` | POST |

Static (copy paths into your app’s static URL config):

- `static/etf_online_test_modal.js`
- `templates/partials/etf_online_test_modal.html`

## Dependencies (not vendored here)

1. **`sfis_tool`** — Oracle connection, WIP, repair, jump route, SQL for reason codes. Same package/layout as SFC_View, importable on `PYTHONPATH`.
2. **`crabber`** — `crabber/online_test.py`, `crabber/profile.py`, `crabber/client.py` (`sn_has_active_crabber_test`).

Environment variables: see `config.example.env` and SFC_View `config/README_CONFIG.md` (`CRABBER_*`, `CRABBER_SV_*`, Oracle settings for `sfis_tool`).

Optional:

- `ONLINE_TEST_PN_BASES_PATH` — JSON file for custom PN bases (default: `online_test/data/crabber_test_pns.json` under this bundle).

## Register in Flask (host project)

```python
from online_test import create_blueprint

app.register_blueprint(create_blueprint())
```

Use the **same** URL paths as above (no `url_prefix`) so existing `etf_online_test_modal.js` continues to work.

### Auth / EMP

- `online_test/deps.py` tries `from fa_debug.auth import resolve_sfis_emp` (works when this folder lives inside SFC_View).
- In another project, either provide a compatible `fa_debug.auth` module or rely on the built-in fallback (uses `request.current_user` if you set it, else `SJOP`).

### Permissions (403)

SFC_View maps `("/api/etf/online-test/", {"debug","testing"})` in `fa_debug` auth middleware. Your host app must allow these paths for the same roles, or adjust your middleware.

### L10 queue limitation

The queue is **in-memory per process** (same as SFC_View): one Gunicorn/uwsgi worker = one queue state. Do not rely on multi-worker promotion without external storage.

## Front-end wiring

1. Copy `static/etf_online_test_modal.js` and `templates/partials/etf_online_test_modal.html` into your app’s static/template tree **or** serve from this folder via `Flask(..., static_folder=..., template_folder=...)`.
2. On every page that opens Online Test (Testing, L10, ETF tray “Test” button), include the partial and load the script **after** `window.__DEFAULT_EMPLOYEE_ID__` if you use it.
3. Modal JS calls APIs with `crabber_profile` query/body (`sj` / `sv`) — same as SFC_View.

## Tests (queue only)

From repo root (with `online_test` on path):

```bash
python -m unittest online_test.tests.test_queue -v
```

## Traceability

See `SOURCE_MAP.md` for the mapping from each file here to the original SFC_View path.
