# Configuration

All default values live in `config/site_defaults.py`. Override with **environment variables**; optionally use **SITE** to switch profiles (e.g. Taiwan).

Priority: `ENV` → `SITE_PROFILES[SITE]` → `DEFAULT`.

---

## Environment variables

| Variable | Description | Example |
|----------|-------------|---------|
| **SITE** | Profile name in `site_defaults.SITE_PROFILES`. Use `default` or unset for San Jose defaults. | `taiwan` |
| **Flask** | | |
| FLASK_HOST | Bind address | `0.0.0.0` |
| FLASK_PORT | Port | `5556` |
| FLASK_DEBUG | 1/true/yes = debug | `true` |
| **SFC** | | |
| SFC_BASE_URL | SFC server base URL | `http://10.16.137.110` |
| SFC_ASSY_INFO_URL | Full AssyInfo URL (optional; default derived from SFC_BASE_URL) | |
| SFC_USER | SFC login user | `SFC` |
| SFC_PWD | SFC login password | |
| SFC_GROUP_NAME | Group filter | `'AST','FCT','FLA',...` |
| SFC_SESSION_TTL_SECONDS | Session TTL | `1800` |
| VALID_LOCATION | Location string for SN validation (e.g. San Jose) | `San Jose` |
| **SSH / Debug** | | |
| SSH_DHCP_HOST | DHCP jump host for terminal proxy | `10.16.138.67` |
| SSH_DHCP_USER | SSH user on DHCP host | `root` |
| SSH_DHCP_PASSWORD | SSH password | |
| WS_TERMINAL_URL | AI terminal WebSocket URL (injected to frontend) | `ws://host:5111/...` |
| UPLOAD_URL | Agent upload API URL | `http://host:5111/api/agent/upload` |
| AI_ADMIN_BASE_URL | AI admin API base | `http://host:5111` |
| UPLOAD_FIELD_NAME | Form field for upload | `file` |
| BMC_SSH_USER / BMC_SSH_PASSWORD | SSH to DUT BMC (SN menu) | `root` / `0penBmc` |
| HOST_SSH_USER / HOST_SSH_PASSWORD | SSH to host (nvidia@sys_ip) | `nvidia` / `nvidia` |
| **Crabber** | | |
| CRABBER_BASE_URL | Crabber API base | `http://10.16.138.66:8000` |
| CRABBER_TOKEN | API token | |
| **ETF** | | |
| SFC_TRAY_STATUS_URL | Tray status API | `http://10.16.137.115/SFCAPI/SFC/Test_Fixture_Status` |
| SFC_LEVEL_GRADE | Level grade (e.g. L10) | `L10` |
| ETF_POLL_INTERVAL_SEC | Poll interval seconds | `60` |
| ETF_SSH_HOST, ETF_SCRIPT_PATH, ETF_STATE_DIR | ETF room SSH/paths | |
| ROOM6_SSH_HOSTS | Comma-separated DHCP hosts (room6) | `10.16.138.71,10.16.138.79,...` |
| ROOM6_SSH_USER, ROOM6_SSH_PASS, ROOM6_SCRIPT_PATH, ROOM6_STATE_DIR | Room 6 | |
| ROOM7_SSH_HOST, ROOM7_SSH_USER, ROOM7_SSH_PASS, ROOM7_SCRIPT_PATH, ROOM7_STATE_DIR | Room 7 | |
| ROOM8_SSH_HOST, ROOM8_SSH_USER, ROOM8_SSH_PASS, ROOM8_SCRIPT_PATH, ROOM8_STATE_DIR | Room 8 | |
| **Analytics** | | |
| timezone | Default timezone (in analytics_config; can also set in site_defaults) | `America/Los_Angeles` |

---

## New site (e.g. Taiwan / new company)

1. Open `config/site_defaults.py`.
2. Add a profile in **SITE_PROFILES**:
   ```python
   SITE_PROFILES = {
       "taiwan": {
           "SFC_BASE_URL": "http://your-taiwan-sfc",
           "VALID_LOCATION": "Taiwan",
           "timezone": "Asia/Taipei",
           "SSH_DHCP_HOST": "10.x.x.x",
           "WS_TERMINAL_URL": "ws://...",
           # ... override only what differs from DEFAULT
       },
   }
   ```
3. Run with `SITE=taiwan` (e.g. `export SITE=taiwan` or set in .env / systemd / Docker).

No code changes needed; env and SITE_PROFILES override defaults.
