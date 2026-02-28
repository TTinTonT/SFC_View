(function () {
  const POLL_INTERVAL_MS = 60000;
  let currentRoom = "etf";
  let allRows = [];
  let filterQuery = "";
  let searchRows = [];
  let searchInFlight = false;
  let searchDebounceTimer = null;
  let pollTimer = null;
  let nextUpdateSec = 0;
  let countdownInterval = null;
  const expandedPanels = new Map();
  const panelRowKeyToSn = new Map();
  const pinnedSns = new Set();
  const roomCache = {};
  let lastDisplayRows = [];
  let sfcSnMap = {};
  let assySnMap = {};
  const MAC_VERIFY_BMC_KEY = "etf_mac_verify_bmc_key";
  const MAC_VERIFY_SYS_KEY = "etf_mac_verify_sys_key";
  const ASSY_VERIFY_INTERVAL_MS = 5 * 60 * 1000;

  function getMacVerifyKeys() {
    try {
      return {
        bmc: localStorage.getItem(MAC_VERIFY_BMC_KEY) || "BMC MAC",
        sys: localStorage.getItem(MAC_VERIFY_SYS_KEY) || "SYS MAC",
      };
    } catch (e) {
      return { bmc: "BMC MAC", sys: "SYS MAC" };
    }
  }

  function getAllKeysOptions() {
    const keys = new Set(["BMC MAC", "SYS MAC"]);
    Object.values(assySnMap).forEach((a) => {
      if (a && a.all_keys && typeof a.all_keys === "object") {
        Object.keys(a.all_keys).forEach((k) => keys.add(k));
      }
    });
    return Array.from(keys).sort();
  }

  function renderMacKeySuggestions() {
    const dl = document.getElementById("etf-mac-key-options");
    if (!dl) return;
    const opts = getAllKeysOptions();
    dl.innerHTML = opts.map((k) => '<option value="' + escapeHtml(k) + '"></option>').join("");
  }

  const tbody = document.getElementById("etf-tbody");
  const dutCountEl = document.getElementById("dut-count");
  const lastUpdatedEl = document.getElementById("last-updated");
  const nextUpdateEl = document.getElementById("next-update");
  const filterInput = document.getElementById("etf-filter");
  const btnRescan = document.getElementById("btn-rescan");
  const btnVerifyMac = document.getElementById("btn-verify-mac");
  const inputBmcKey = document.getElementById("etf-mac-key-bmc");
  const inputSysKey = document.getElementById("etf-mac-key-sys");
  const btnSaveMacKeys = document.getElementById("btn-save-mac-keys");

  function syncMacKeyInputsFromStorage() {
    if (!inputBmcKey || !inputSysKey) return;
    const keys = getMacVerifyKeys();
    inputBmcKey.value = keys.bmc;
    inputSysKey.value = keys.sys;
  }

  function saveMacKeysFromInputs() {
    const bmc = (inputBmcKey?.value || "").trim() || "BMC MAC";
    const sys = (inputSysKey?.value || "").trim() || "SYS MAC";
    try {
      localStorage.setItem(MAC_VERIFY_BMC_KEY, bmc);
      localStorage.setItem(MAC_VERIFY_SYS_KEY, sys);
    } catch (e) {}
    if (inputBmcKey) inputBmcKey.value = bmc;
    if (inputSysKey) inputSysKey.value = sys;
    const displayRows = filterQuery && filterQuery.trim() ? searchRows : allRows.filter(matchFilter);
    renderTable(displayRows);
  }

  if (btnSaveMacKeys) btnSaveMacKeys.addEventListener("click", saveMacKeysFromInputs);
  if (inputBmcKey && !inputBmcKey.dataset.bound) {
    inputBmcKey.dataset.bound = "1";
    inputBmcKey.addEventListener("keydown", (e) => { if (e.key === "Enter") saveMacKeysFromInputs(); });
    inputBmcKey.addEventListener("blur", () => { if ((inputBmcKey.value || "").trim()) saveMacKeysFromInputs(); });
  }
  if (inputSysKey && !inputSysKey.dataset.bound) {
    inputSysKey.dataset.bound = "1";
    inputSysKey.addEventListener("keydown", (e) => { if (e.key === "Enter") saveMacKeysFromInputs(); });
    inputSysKey.addEventListener("blur", () => { if ((inputSysKey.value || "").trim()) saveMacKeysFromInputs(); });
  }

  function escapeHtml(s) {
    if (s == null || s === undefined) return "";
    const div = document.createElement("div");
    div.textContent = String(s);
    return div.innerHTML;
  }

  /** Parse SFC last end time "YYYY/MM/DD HH:mm:ss" to Date (local). Returns null if invalid. */
  function parseLastEndTime(s) {
    if (!s || typeof s !== "string") return null;
    const m = s.trim().match(/^(\d{4})\/(\d{2})\/(\d{2})\s+(\d{2}):(\d{2}):(\d{2})$/);
    if (!m) return null;
    return new Date(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +m[6]);
  }

  /** Format seconds to "Xd Xh Xm Xs", e.g. 2d 3h 5m 10s. */
  function formatDuration(seconds) {
    if (seconds < 0 || !Number.isFinite(seconds)) return "-";
    const d = Math.floor(seconds / 86400);
    const h = Math.floor((seconds % 86400) / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const sec = Math.floor(seconds % 60);
    const parts = [];
    if (d > 0) parts.push(d + "d");
    if (h > 0) parts.push(h + "h");
    if (m > 0) parts.push(m + "m");
    parts.push(sec + "s");
    return parts.join(" ");
  }

  function normalizeMac(m) {
    return (m || "").replace(/:/g, "").toLowerCase().trim();
  }

  function updateLastEndDurations() {
    const now = Date.now();
    document.querySelectorAll(".last-end-cell").forEach((td) => {
      const raw = td.dataset.lastEnd;
      const date = parseLastEndTime(raw);
      const target = td.querySelector(".last-end-value") || td;
      if (!date) {
        target.textContent = td.dataset.lastEnd ? "-" : "-";
        return;
      }
      const sec = (now - date.getTime()) / 1000;
      target.textContent = formatDuration(sec);
    });
  }

  function matchFilter(row) {
    if (!filterQuery || filterQuery.trim() === "") return true;
    const q = filterQuery.trim().toLowerCase();
    const sn = (row.sn || "").toLowerCase();
    const pn = (row.pn || "").toLowerCase();
    const macKeys = getMacVerifyKeys();
    const assy = assySnMap[row.sn] || {};
    const bmcMacSfc = (assy.all_keys && assy.all_keys[macKeys.bmc] !== undefined) ? String(assy.all_keys[macKeys.bmc]) : (assy.bmc_mac || "");
    const sysMacSfc = (assy.all_keys && assy.all_keys[macKeys.sys] !== undefined) ? String(assy.all_keys[macKeys.sys]) : (assy.sys_mac || "");
    const bmcMac = (row.bmc_mac || "").toLowerCase();
    const bmcIp = (row.bmc_ip || "").toLowerCase();
    const sysIp = (row.sys_ip || "").toLowerCase();
    const sysMac = (row.sys_mac || "").toLowerCase();
    const bmcMacSfcLower = bmcMacSfc.toLowerCase();
    const sysMacSfcLower = sysMacSfc.toLowerCase();
    const sfc = sfcSnMap[row.sn] || {};
    const fixture = (sfc.fixture_no || "").toLowerCase();
    const slot = (sfc.slot_no || "").toLowerCase();
    const status = (sfc.status || "").toLowerCase();
    const sfcRemark = (sfc.remark || "").toLowerCase();
    return sn.includes(q) || pn.includes(q) || bmcMac.includes(q) || bmcIp.includes(q) || sysIp.includes(q) || sysMac.includes(q) ||
      bmcMacSfcLower.includes(q) || sysMacSfcLower.includes(q) ||
      fixture.includes(q) || slot.includes(q) || status.includes(q) || sfcRemark.includes(q);
  }

  function closeAllMenus() {
    document.querySelectorAll(".sn-menu").forEach((m) => m.classList.remove("open"));
  }

  function onSnMenuAction(rowKey, sn, action) {
    closeAllMenus();
    expandedPanels.set(rowKey, action);
    renderTable(allRows);
    if (typeof window.etfCreateSnTerminals === "function") {
      const panel = document.querySelector(`.sn-debug-panel[data-row-key="${escapeHtml(rowKey)}"]`);
      if (panel) {
        const aiEl = panel.querySelector(".sn-debug-ai-container");
        const sshEl = panel.querySelector(".sn-debug-ssh-container");
        const row = lastDisplayRows.find((r) => (r.sn || r.pn || r.bmc_ip) === rowKey);
        window.etfCreateSnTerminals(sn, rowKey, action, { aiEl, sshEl, row });
        setTimeout(() => { if (typeof window.etfFitTerminals === "function") window.etfFitTerminals(rowKey); }, 150);
      }
    }
  }

  function onHidePanel(rowKey) {
    if (typeof window.etfCloseSnPanel === "function") window.etfCloseSnPanel(rowKey);
    expandedPanels.delete(rowKey);
    renderTable(allRows);
  }

  function onPinSn(rowKey, sn) {
    if (pinnedSns.has(rowKey)) {
      pinnedSns.delete(rowKey);
    } else {
      pinnedSns.add(rowKey);
    }
    renderTable(allRows);
    if (typeof window.etfUpdatePinnedSns === "function") {
      window.etfUpdatePinnedSns(Array.from(pinnedSns).map((k) => ({ rowKey: k, sn: lastDisplayRows.find((r) => (r.sn || r.pn || r.bmc_ip) === k)?.sn || k })));
    }
  }

  function renderTable(rows) {
    allRows = rows || [];
    const isSearchMode = filterQuery && filterQuery.trim() !== "";
    const displayRows = isSearchMode ? searchRows : allRows.filter(matchFilter);
    dutCountEl.textContent = displayRows.length;

    if (displayRows.length === 0 && expandedPanels.size === 0) {
      const msg = isSearchMode && searchInFlight ? "Searching..." : "No DUTs";
      tbody.innerHTML = '<tr><td colspan="9" style="color: var(--color-muted); text-align: center; padding: 2rem;">' + escapeHtml(msg) + "</td></tr>";
      return;
    }

    lastDisplayRows = displayRows;
    const displayRowKeys = new Set(displayRows.map((r) => (r.sn || r.pn || r.bmc_ip || "").trim()).filter(Boolean));
    const disconnectedRowKeys = [...expandedPanels.keys()].filter((k) => !displayRowKeys.has(k));

    displayRows.forEach((r) => {
      const rowKey = r.sn || r.pn || r.bmc_ip || "";
      if (rowKey) panelRowKeyToSn.set(rowKey, r.sn || rowKey);
    });

    const savedPanels = new Map();
    tbody.querySelectorAll("tr.sn-debug-row").forEach((tr) => {
      const rowKey = tr.dataset.rowKey || "";
      if (rowKey && expandedPanels.has(rowKey)) {
        savedPanels.set(rowKey, tr);
        tr.remove();
      }
    });

    const htmlParts = [];
    displayRows.forEach((r) => {
      const rowKey = r.sn || r.pn || r.bmc_ip || "";
      const snDisplay = r.sn || "-";
      const action = expandedPanels.get(rowKey);
      const isPinned = pinnedSns.has(rowKey);
      const sfc = sfcSnMap[r.sn] || {};
      const sfcSlot = escapeHtml(sfc.slot_no || "-");
      const rawLastEnd = (sfc.last_end_time || "").trim();
      const endDate = rawLastEnd ? parseLastEndTime(rawLastEnd) : null;
      const lastEndDisplay = endDate ? formatDuration((Date.now() - endDate.getTime()) / 1000) : "-";
      const sfcRemarkVal = escapeHtml(sfc.remark || "-");

      const assy = assySnMap[r.sn] || {};
      const macKeys = getMacVerifyKeys();
      const bmcMacSfc = (assy.all_keys && assy.all_keys[macKeys.bmc] !== undefined) ? assy.all_keys[macKeys.bmc] : (assy.bmc_mac || "");
      const sysMacSfc = (assy.all_keys && assy.all_keys[macKeys.sys] !== undefined) ? assy.all_keys[macKeys.sys] : (assy.sys_mac || "");
      const bmcMacDhcp = r.bmc_mac || "-";
      const sysMacDhcpRaw = r.sys_mac || "";
      const sysMacDhcpNA = !sysMacDhcpRaw || String(sysMacDhcpRaw).trim().toUpperCase() === "N/A" || sysMacDhcpRaw === "-";
      const sysMacDhcp = sysMacDhcpRaw || "-";
      const bmcMatch = bmcMacSfc ? normalizeMac(bmcMacSfc) === normalizeMac(bmcMacDhcp) : null;
      const sysMatch = sysMacDhcpNA ? null : (sysMacSfc ? normalizeMac(sysMacSfc) === normalizeMac(sysMacDhcp) : null);
      const bmcIcon = bmcMatch === true ? '<span class="mac-icon mac-ok" title="Match">✓</span>' : bmcMatch === false ? '<span class="mac-icon mac-fail" title="Mismatch">✗</span>' : "";
      const sysIcon = sysMatch === true ? '<span class="mac-icon mac-ok" title="Match">✓</span>' : sysMatch === false ? '<span class="mac-icon mac-fail" title="Mismatch">✗</span>' : "";
      const bmcTitle = bmcMatch === false
        ? ("SFC(" + macKeys.bmc + "): " + (bmcMacSfc || "-") + " | DHCP: " + (bmcMacDhcp || "-"))
        : ("SFC(" + macKeys.bmc + "): " + (bmcMacSfc || "-"));
      const bmcDiffInline = bmcMatch === false
        ? '<div class="mac-diff-inline" title="' + escapeHtml(bmcMacSfc + " vs " + bmcMacDhcp) + '">SFC: ' + escapeHtml(bmcMacSfc || "-") + " | DHCP: " + escapeHtml(bmcMacDhcp) + "</div>"
        : "";
      const sysDisplay = sysMacDhcpNA ? escapeHtml(sysMacSfc || "-") : escapeHtml(sysMacDhcp);
      const sysTitle = sysMacDhcpNA
        ? ("DHCP: N/A (showing SFC " + macKeys.sys + "): " + (sysMacSfc || "-"))
        : (sysMatch === false
          ? ("SFC(" + macKeys.sys + "): " + (sysMacSfc || "-") + " | DHCP: " + (sysMacDhcp || "-"))
          : ("SFC(" + macKeys.sys + "): " + (sysMacSfc || "-") + " | DHCP: " + (sysMacDhcp || "-")));
      const sysDiffInline = sysMatch === false
        ? '<div class="mac-diff-inline" title="' + escapeHtml((sysMacSfc || "-") + " vs " + sysMacDhcp) + '">SFC: ' + escapeHtml(sysMacSfc || "-") + " | DHCP: " + escapeHtml(sysMacDhcp) + "</div>"
        : "";

      htmlParts.push(`<tr data-sn="${escapeHtml(r.sn)}" data-row-key="${escapeHtml(rowKey)}">
        <td class="etf-td"><div class="etf-cell-inner etf-cell-inner--sn">
          <div class="sn-cell">
            <button type="button" class="sn-btn" data-sn="${escapeHtml(r.sn)}" data-row-key="${escapeHtml(rowKey)}" title="Debug options">${escapeHtml(snDisplay)}</button>
            <div class="sn-menu" data-row-key="${escapeHtml(rowKey)}">
              <button type="button" data-action="ai">AI Debug</button>
              <button type="button" data-action="term">Terminal Debug</button>
              <button type="button" data-action="both">Both</button>
            </div>
            <button type="button" class="pin-btn etf-pin-btn" data-row-key="${escapeHtml(rowKey)}" data-sn="${escapeHtml(r.sn)}" title="Pin">${isPinned ? "📍" : "📌"}</button>
          </div>
        </div></td>
        <td class="etf-td"><div class="etf-cell-inner" title="${escapeHtml(r.pn)}">${escapeHtml(r.pn)}</div></td>
        <td class="etf-td"><div class="etf-cell-inner etf-cell-inner--mac" title="${escapeHtml(bmcTitle)}"><span class="mac-line">${escapeHtml(bmcMacDhcp)}${bmcIcon}</span>${bmcDiffInline}</div></td>
        <td class="etf-td"><div class="etf-cell-inner" title="${escapeHtml(r.bmc_ip)}">${escapeHtml(r.bmc_ip)}</div></td>
        <td class="etf-td"><div class="etf-cell-inner" title="${escapeHtml(r.sys_ip)}">${escapeHtml(r.sys_ip)}</div></td>
        <td class="etf-td"><div class="etf-cell-inner etf-cell-inner--mac" title="${escapeHtml(sysTitle)}"><span class="mac-line">${sysDisplay}${sysIcon}</span>${sysDiffInline}</div></td>
        <td class="etf-td"><div class="etf-cell-inner">${escapeHtml(sfcSlot)}</div></td>
        <td class="etf-td last-end-cell" data-last-end="${escapeHtml(rawLastEnd)}"><div class="etf-cell-inner etf-cell-inner--time"><span class="last-end-value">${lastEndDisplay}</span></div></td>
        <td class="etf-td"><div class="etf-cell-inner" title="${sfcRemarkVal}">${sfcRemarkVal}</div></td>
      </tr>`);

      if (action && !savedPanels.has(rowKey)) {
        const showAi = action === "ai" || action === "both";
        const showSsh = action === "term" || action === "both";
        htmlParts.push(`<tr class="sn-debug-row" data-row-key="${escapeHtml(rowKey)}">
          <td colspan="9" class="sn-debug-panel" data-row-key="${escapeHtml(rowKey)}">
            <div class="sn-debug-panel-inner">
              <div class="sn-debug-header">
                <span class="sn-debug-title">${escapeHtml(snDisplay)} – ${action === "ai" ? "AI Debug" : action === "term" ? "Terminal Debug" : "AI + Terminal"}</span>
                <div class="sn-debug-ai-controls">${showAi ? '<button type="button" class="sn-debug-btn" data-row-key="' + escapeHtml(rowKey) + '" data-action="start-session">Start Session</button><button type="button" class="sn-debug-btn" data-row-key="' + escapeHtml(rowKey) + '" data-action="end-session">End Session</button><button type="button" class="sn-debug-btn" data-row-key="' + escapeHtml(rowKey) + '" data-action="upload">Upload</button>' : ""}</div>
                <button type="button" class="sn-debug-hide" data-row-key="${escapeHtml(rowKey)}">Hide</button>
              </div>
              <div class="sn-debug-resize" data-row-key="${escapeHtml(rowKey)}" title="Drag to resize"></div>
              <div class="sn-debug-terminals" style="height: ${(showAi && showSsh ? 900 : 450)}px">
                ${showAi ? '<div class="sn-debug-terminal sn-debug-ai-container" style="min-height:150px;flex:1"></div>' : ""}
                ${showSsh ? '<div class="sn-debug-terminal sn-debug-ssh-container" style="min-height:150px;flex:1"></div>' : ""}
              </div>
            </div>
          </td>
        </tr>`);
      }
    });

    disconnectedRowKeys.forEach((rowKey) => {
      const snDisplay = panelRowKeyToSn.get(rowKey) || rowKey;
      const action = expandedPanels.get(rowKey);
      htmlParts.push(`<tr class="sn-disconnected-row" data-row-key="${escapeHtml(rowKey)}">
        <td colspan="9" style="padding: 0.75rem 1rem; background: rgba(245, 158, 11, 0.15); border-left: 4px solid #f59e0b; color: var(--color-text); font-size: 0.9rem;">
          <span style="font-weight: 600;">SN: ${escapeHtml(snDisplay)}</span> — Tray disconnected / cannot ping. Terminal output preserved. Close when done.
        </td>
      </tr>`);
    });

    tbody.innerHTML = htmlParts.join("");

    displayRows.forEach((r, i) => {
      const rowKey = r.sn || r.pn || r.bmc_ip || "";
      const saved = savedPanels.get(rowKey);
      if (!saved) return;
      const dataRows = tbody.querySelectorAll("tr:not(.sn-debug-row):not(.sn-disconnected-row)");
      const targetRow = dataRows[i];
      if (targetRow) targetRow.after(saved);
    });

    disconnectedRowKeys.forEach((rowKey) => {
      const saved = savedPanels.get(rowKey);
      if (!saved) return;
      const banner = saved.querySelector(".sn-disconnect-banner");
      if (!banner) {
        const header = saved.querySelector(".sn-debug-header");
        if (header) {
          const div = document.createElement("div");
          div.className = "sn-disconnect-banner";
          div.style.cssText = "background: rgba(245, 158, 11, 0.2); border-left: 4px solid #f59e0b; padding: 0.5rem 0.75rem; margin-bottom: 0.5rem; font-size: 0.8125rem; color: var(--color-text);";
          div.textContent = "Tray disconnected / cannot ping. You can continue viewing terminal output. Click Hide when done.";
          header.before(div);
        }
      }
      const placeholderRow = [...tbody.querySelectorAll("tr.sn-disconnected-row")].find((tr) => tr.dataset.rowKey === rowKey);
      if (placeholderRow) placeholderRow.after(saved);
    });

    tbody.querySelectorAll(".sn-btn").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        closeAllMenus();
        const menu = btn.nextElementSibling;
        if (menu && menu.classList.contains("sn-menu")) {
          menu.classList.toggle("open");
        }
      });
    });

    tbody.querySelectorAll(".sn-menu button").forEach((menuBtn) => {
      menuBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        const menu = menuBtn.closest(".sn-menu");
        const rowKey = menu?.dataset.rowKey || "";
        const action = menuBtn.dataset.action || "both";
        const row = lastDisplayRows.find((r) => (r.sn || r.pn || r.bmc_ip) === rowKey);
        const sn = (row?.sn || rowKey);
        onSnMenuAction(rowKey, sn, action);
      });
    });

    tbody.querySelectorAll(".etf-pin-btn").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        onPinSn(btn.dataset.rowKey || "", btn.dataset.sn || "");
      });
    });

    tbody.querySelectorAll(".sn-debug-hide").forEach((btn) => {
      btn.addEventListener("click", () => onHidePanel(btn.dataset.rowKey || ""));
    });

    tbody.querySelectorAll(".sn-debug-btn[data-action='start-session']").forEach((btn) => {
      btn.addEventListener("click", () => { if (typeof window.etfAiStartSession === "function") window.etfAiStartSession(btn.dataset.rowKey || ""); });
    });
    tbody.querySelectorAll(".sn-debug-btn[data-action='end-session']").forEach((btn) => {
      btn.addEventListener("click", () => { if (typeof window.etfAiEndSession === "function") window.etfAiEndSession(btn.dataset.rowKey || ""); });
    });
    tbody.querySelectorAll(".sn-debug-btn[data-action='upload']").forEach((btn) => {
      btn.addEventListener("click", () => { if (typeof window.etfAiUpload === "function") window.etfAiUpload(btn.dataset.rowKey || ""); });
    });

    expandedPanels.forEach((act, rowKey) => {
      if (savedPanels.has(rowKey)) return;
      if (typeof window.etfCreateSnTerminals === "function") {
        const panel = tbody.querySelector(`.sn-debug-panel[data-row-key="${escapeHtml(rowKey)}"]`);
        if (panel) {
          const aiEl = panel.querySelector(".sn-debug-ai-container");
          const sshEl = panel.querySelector(".sn-debug-ssh-container");
          const row = lastDisplayRows.find((r) => (r.sn || r.pn || r.bmc_ip) === rowKey);
          window.etfCreateSnTerminals(row?.sn || rowKey, rowKey, act, { aiEl, sshEl, row });
          setTimeout(() => { if (typeof window.etfFitTerminals === "function") window.etfFitTerminals(rowKey); }, 150);
        }
      }
    });

    if (pinnedSns.size > 0 && typeof window.etfUpdatePinnedSns === "function") {
      window.etfUpdatePinnedSns(Array.from(pinnedSns).map((k) => ({ rowKey: k, sn: lastDisplayRows.find((r) => (r.sn || r.pn || r.bmc_ip) === k)?.sn || k })));
    }

    setupResizeHandles();
  }

  function setupResizeHandles() {
    tbody.querySelectorAll(".sn-debug-resize").forEach((handle) => {
      if (handle.dataset.resizeBound) return;
      handle.dataset.resizeBound = "1";
      let startY = 0;
      let startHeight = 0;
      handle.addEventListener("mousedown", (e) => {
        e.preventDefault();
        document.body.style.cursor = "ns-resize";
        document.body.style.userSelect = "none";
        const panel = handle.closest(".sn-debug-panel-inner");
        const terminals = panel?.querySelector(".sn-debug-terminals");
        if (!terminals) return;
        startY = e.clientY;
        startHeight = terminals.offsetHeight;
        const onMove = (ev) => {
          const dy = ev.clientY - startY;
          const newH = Math.max(200, Math.min(800, startHeight + dy));
          startY = ev.clientY;
          startHeight = newH;
          const children = panel.querySelectorAll(".sn-debug-terminal");
          const h = children.length > 0 ? Math.floor(newH / children.length) + "px" : newH + "px";
          terminals.style.height = newH + "px";
          children.forEach((t) => { t.style.height = h; });
          if (typeof window.etfFitTerminals === "function") window.etfFitTerminals(handle.dataset.rowKey || "");
        };
        const rowKey = handle.dataset.rowKey || "";
        const onUp = () => {
          document.removeEventListener("mousemove", onMove);
          document.removeEventListener("mouseup", onUp);
          document.body.style.cursor = "";
          document.body.style.userSelect = "";
          if (typeof window.etfFitTerminals === "function") window.etfFitTerminals(rowKey);
        };
        document.addEventListener("mousemove", onMove);
        document.addEventListener("mouseup", onUp);
      });
    });
  }

  function fetchData(isRescan) {
    const url = isRescan ? `/api/etf/reset?room=${currentRoom}` : `/api/etf/data?room=${currentRoom}`;
    const opts = isRescan ? { method: "POST" } : {};
    if (isRescan) btnRescan.disabled = true;
    Promise.all([
      fetch(url, opts).then((res) => res.json()),
      fetch("/api/sfc/tray-status")
        .then((res) => res.json().then((data) => ({ ok: data.ok && res.ok, sn_map: data.sn_map || {} })))
        .catch(() => ({ ok: false, sn_map: {} })),
    ])
      .then(([data, sfcData]) => {
        sfcSnMap = (sfcData.ok && sfcData.sn_map) ? sfcData.sn_map : {};
        if (data.ok && Array.isArray(data.rows)) {
          roomCache[currentRoom] = { rows: data.rows, last_updated: data.last_updated || "-" };
          const rowsJson = JSON.stringify(data.rows.map((r) => (r.sn || "") + (r.pn || "") + (r.bmc_ip || "")));
          const lastKey = "_etfLastRowsJson_" + currentRoom;
          if (rowsJson !== (window[lastKey] || "")) {
            window[lastKey] = rowsJson;
            // restore cached assy map for this room if present
            assySnMap = roomCache[currentRoom]?.assySnMap || assySnMap || {};
            renderMacKeySuggestions();
            renderTable(data.rows);
          } else {
            allRows = data.rows || [];
            dutCountEl.textContent = (allRows.filter(matchFilter)).length;
          }
          lastUpdatedEl.textContent = data.last_updated || "-";
          nextUpdateSec = POLL_INTERVAL_MS / 1000;
          if (countdownInterval) clearInterval(countdownInterval);
          countdownInterval = setInterval(() => {
            nextUpdateSec--;
            if (nextUpdateSec <= 0) nextUpdateSec = POLL_INTERVAL_MS / 1000;
            nextUpdateEl.textContent = nextUpdateSec + "s";
          }, 1000);
        } else if (data.error) {
          tbody.innerHTML = '<tr><td colspan="13" style="color: var(--color-danger); text-align: center; padding: 2rem;">' + escapeHtml(data.error) + "</td></tr>";
        }
      })
      .catch((err) => {
        const msg = (err && err.message && err.message.includes('fetch')) ? "Cannot connect to server. Check if backend is running (python app.py)" : String(err);
        tbody.innerHTML = '<tr><td colspan="13" style="color: var(--color-danger); text-align: center; padding: 2rem;">' + escapeHtml(msg) + "</td></tr>";
      })
      .finally(() => {
        if (isRescan) btnRescan.disabled = false;
      });
  }

  let verifyInFlight = false;
  function verifyMacForRows(rows, { forceAll = true } = {}) {
    if (!btnVerifyMac || verifyInFlight) return Promise.resolve(false);
    const sns = (rows || []).map((r) => r?.sn).filter(Boolean);
    const uniq = Array.from(new Set(sns));
    if (!uniq.length) return Promise.resolve(false);
    verifyInFlight = true;
    btnVerifyMac.disabled = true;
    btnVerifyMac.textContent = "Verifying...";
    return fetch("/api/sfc/assy-info", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sns: uniq }),
    })
      .then((res) => res.json())
      .then((data) => {
        assySnMap = data.sn_map || {};
        roomCache[currentRoom] = roomCache[currentRoom] || {};
        roomCache[currentRoom].assySnMap = assySnMap;
        roomCache[currentRoom].assy_last_updated = Date.now();
        renderMacKeySuggestions();
        renderTable(allRows);
        return true;
      })
      .catch(() => false)
      .finally(() => {
        verifyInFlight = false;
        btnVerifyMac.disabled = false;
        btnVerifyMac.textContent = "Verify MAC";
      });
  }

  function schedulePoll() {
    if (pollTimer) clearTimeout(pollTimer);
    pollTimer = setTimeout(() => {
      fetchData(false);
      schedulePoll();
    }, POLL_INTERVAL_MS);
  }

  document.addEventListener("click", (e) => {
    if (!e.target.closest(".sn-cell")) closeAllMenus();
  });

  function runSearch() {
    const q = (filterInput.value || "").trim();
    filterQuery = filterInput.value;
    if (!q) {
      searchRows = [];
      searchInFlight = false;
      renderTable(allRows);
      return;
    }
    searchInFlight = true;
    renderTable(allRows);
    fetch("/api/etf/search?q=" + encodeURIComponent(q))
      .then((r) => r.json())
      .then((data) => {
        searchRows = (data.ok && Array.isArray(data.rows)) ? data.rows : [];
        searchInFlight = false;
        renderTable(allRows);
      })
      .catch(() => {
        searchRows = [];
        searchInFlight = false;
        renderTable(allRows);
      });
  }

  filterInput.addEventListener("input", () => {
    filterQuery = filterInput.value;
    if (searchDebounceTimer) clearTimeout(searchDebounceTimer);
    if ((filterQuery || "").trim()) {
      searchDebounceTimer = setTimeout(runSearch, 300);
    } else {
      searchRows = [];
      searchInFlight = false;
      renderTable(allRows);
    }
  });

  btnRescan.addEventListener("click", () => {
    // full rescan; clear cached assy map for current room then refetch + verify
    if (roomCache[currentRoom]) {
      roomCache[currentRoom].assySnMap = {};
      roomCache[currentRoom].assy_last_updated = 0;
    }
    assySnMap = {};
    fetchData(true);
    schedulePoll();
    // verify will run shortly after fetchData completes; also kick immediately using current rows
    setTimeout(() => { verifyMacForRows(allRows); }, 1200);
  });

  if (btnVerifyMac) btnVerifyMac.addEventListener("click", () => verifyMacForRows(allRows));

  document.querySelectorAll(".etf-tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      document.querySelectorAll(".etf-tab").forEach((t) => t.classList.remove("active"));
      tab.classList.add("active");
      currentRoom = tab.dataset.room;
      expandedPanels.forEach((_, rowKey) => { if (typeof window.etfCloseSnPanel === "function") window.etfCloseSnPanel(rowKey); });
      expandedPanels.clear();
      const cached = roomCache[currentRoom];
      if (cached?.rows) {
        renderTable(cached.rows);
        lastUpdatedEl.textContent = cached.last_updated || "-";
      } else {
        tbody.innerHTML = '<tr><td colspan="9" style="color: var(--color-muted); text-align: center; padding: 2rem;">Loading...</td></tr>';
      }
      fetchData(false);
      schedulePoll();
    });
  });

  fetchData(false);
  schedulePoll();
  syncMacKeyInputsFromStorage();
  renderMacKeySuggestions();
  setInterval(() => {
    // auto-verify every 5 minutes; store with room cache
    verifyMacForRows(allRows);
  }, ASSY_VERIFY_INTERVAL_MS);

  updateLastEndDurations();
  setInterval(updateLastEndDurations, 1000);
})();
