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
  const expandedPanels = new Map(); // value: { ai, term, bmc, host } or legacy "ai"|"term"|"both"
  const panelRowKeyToSn = new Map();

  function getPanelFlags(rowKey) {
    const v = expandedPanels.get(rowKey);
    if (!v) return { ai: false, term: false, bmc: false, host: false };
    if (typeof v === "object" && v !== null) return { ai: !!v.ai, term: !!v.term, bmc: !!v.bmc, host: !!v.host };
    if (v === "ai") return { ai: true, term: false, bmc: false, host: false };
    if (v === "term") return { ai: false, term: true, bmc: false, host: false };
    if (v === "both") return { ai: true, term: true, bmc: false, host: false };
    return { ai: false, term: false, bmc: false, host: false };
  }

  function actionFromFlags(flags) {
    if (flags.ai && flags.term) return "both";
    if (flags.ai) return "ai";
    if (flags.term) return "term";
    return null;
  }

  function setPanelFlags(rowKey, flags) {
    if (flags.ai || flags.term || flags.bmc || flags.host) {
      expandedPanels.set(rowKey, { ai: !!flags.ai, term: !!flags.term, bmc: !!flags.bmc, host: !!flags.host });
    } else {
      if (typeof window.etfCloseSnPanel === "function") window.etfCloseSnPanel(rowKey);
      expandedPanels.delete(rowKey);
    }
  }

  function titleLabelFromFlags(flags) {
    const parts = [];
    if (flags.ai) parts.push("AI Debug");
    if (flags.term) parts.push("Terminal Debug");
    if (flags.bmc) parts.push("BMC Terminal");
    if (flags.host) parts.push("Host Terminal");
    return parts.length ? parts.join(" + ") : "";
  }

  function terminalHeightFromFlags(flags) {
    const n = [flags.ai, flags.term, flags.bmc, flags.host].filter(Boolean).length;
    return n ? Math.min(Math.max(225 * n, 450), 900) : 450;
  }
  const pinnedSns = new Set();
  const roomCache = {};
  let lastDisplayRows = [];
  let sfcSnMap = {};
  let assySnMap = {};
  let macVerifyKeysCache = { bmc: "", sys: "" };

  function getMacVerifyKeys() {
    return {
      bmc: macVerifyKeysCache.bmc || "BMC MAC",
      sys: macVerifyKeysCache.sys || "SYS MAC",
    };
  }

  function fetchMacVerifyKeys() {
    return fetch("/api/etf/mac-verify-keys")
      .then((r) => r.json())
      .then((data) => {
        if (data && data.ok) {
          macVerifyKeysCache = {
            bmc: (data.bmc || "").trim(),
            sys: (data.sys || "").trim(),
          };
        }
        syncMacKeyInputs();
      })
      .catch(() => { syncMacKeyInputs(); });
  }

  function syncMacKeyInputs() {
    const keys = getMacVerifyKeys();
    const bmcEl = document.getElementById("etf-mac-key-bmc");
    const sysEl = document.getElementById("etf-mac-key-sys");
    if (bmcEl) bmcEl.value = keys.bmc || "N/A";
    if (sysEl) sysEl.value = keys.sys || "N/A";
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

  const tbody = document.getElementById("etf-tbody");
  const dutCountEl = document.getElementById("dut-count");
  const lastUpdatedEl = document.getElementById("last-updated");
  const nextUpdateEl = document.getElementById("next-update");
  const filterInput = document.getElementById("etf-filter");
  const btnRescan = document.getElementById("btn-rescan");
  const btnVerifyMac = document.getElementById("btn-verify-mac");
  const inputBmcKey = document.getElementById("etf-mac-key-bmc");
  const inputSysKey = document.getElementById("etf-mac-key-sys");
  const BMC_KEY_TOOLTIP = "Key in SFC AssyInfo (all_keys) used to get BMC MAC for comparison with DHCP. Belongs to fields returned from Verify MAC.";
  const SYS_KEY_TOOLTIP = "Key in SFC AssyInfo (all_keys) used to get SYS MAC for comparison with DHCP. Belongs to fields returned from Verify MAC.";

  function saveAndLock(input, lockBtn) {
    if (!input || !lockBtn) return;
    const val = (input.value || "").trim();
    const displayVal = val || "N/A";
    const isBmc = input.id === "etf-mac-key-bmc";
    const payload = isBmc ? { bmc: val } : { sys: val };
    fetch("/api/etf/mac-verify-keys", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
      .then((r) => r.json())
      .then((data) => {
        if (data && data.ok) {
          macVerifyKeysCache.bmc = (data.bmc || "").trim();
          macVerifyKeysCache.sys = (data.sys || "").trim();
        }
        input.value = displayVal;
        input.readOnly = true;
        lockBtn.textContent = "🔒";
        lockBtn.title = "Click to unlock/edit";
        syncMacKeyInputs();
        const displayRows = filterQuery && filterQuery.trim() ? searchRows : allRows.filter(matchFilter);
        renderTable(displayRows);
      })
      .catch(() => {
        input.value = displayVal;
        input.readOnly = true;
        lockBtn.textContent = "🔒";
        lockBtn.title = "Click to unlock/edit";
      });
  }

  document.querySelectorAll(".mac-key-lock").forEach((btn) => {
    btn.addEventListener("click", () => {
      const id = btn.dataset.target;
      const input = id ? document.getElementById(id) : null;
      if (!input) return;
      const isLocked = input.readOnly;
      if (isLocked) {
        input.readOnly = false;
        input.value = input.value === "N/A" ? "" : input.value;
        btn.textContent = "🔓";
        btn.title = "Click to lock and save";
        input.focus();
      } else {
        saveAndLock(input, btn);
      }
    });
  });
  if (inputBmcKey && !inputBmcKey.dataset.bound) {
    inputBmcKey.dataset.bound = "1";
    inputBmcKey.title = BMC_KEY_TOOLTIP;
    inputBmcKey.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        const lockBtn = document.querySelector('.mac-key-lock[data-target="etf-mac-key-bmc"]');
        saveAndLock(inputBmcKey, lockBtn);
      }
    });
    inputBmcKey.addEventListener("blur", () => {
      if (!inputBmcKey.readOnly) {
        const lockBtn = document.querySelector('.mac-key-lock[data-target="etf-mac-key-bmc"]');
        saveAndLock(inputBmcKey, lockBtn);
      }
    });
  }
  if (inputSysKey && !inputSysKey.dataset.bound) {
    inputSysKey.dataset.bound = "1";
    inputSysKey.title = SYS_KEY_TOOLTIP;
    inputSysKey.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        const lockBtn = document.querySelector('.mac-key-lock[data-target="etf-mac-key-sys"]');
        saveAndLock(inputSysKey, lockBtn);
      }
    });
    inputSysKey.addEventListener("blur", () => {
      if (!inputSysKey.readOnly) {
        const lockBtn = document.querySelector('.mac-key-lock[data-target="etf-mac-key-sys"]');
        saveAndLock(inputSysKey, lockBtn);
      }
    });
  }

  function escapeHtml(s) {
    if (s == null || s === undefined) return "";
    const div = document.createElement("div");
    div.textContent = String(s);
    return div.innerHTML;
  }

  function copyText(text) {
    const value = String(text || "");
    if (!value) return Promise.resolve(false);
    if (navigator.clipboard && window.isSecureContext) {
      return navigator.clipboard.writeText(value).then(() => true).catch(() => false);
    }
    const ta = document.createElement("textarea");
    ta.value = value;
    ta.setAttribute("readonly", "");
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    ta.style.left = "-9999px";
    document.body.appendChild(ta);
    ta.select();
    ta.setSelectionRange(0, ta.value.length);
    let ok = false;
    try {
      ok = document.execCommand("copy");
    } catch (_) {
      ok = false;
    }
    document.body.removeChild(ta);
    return Promise.resolve(ok);
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

  function onSnMenuToggle(rowKey, sn, mode) {
    const flags = getPanelFlags(rowKey);
    const next = !flags[mode];
    if (mode === "ai" && !next) {
      if (typeof window.etfAiEndSession === "function") window.etfAiEndSession(rowKey);
    }
    setPanelFlags(rowKey, { ...flags, [mode]: next });
    renderTable(allRows);
    const menu = [...document.querySelectorAll(".sn-menu")].find((m) => m.dataset.rowKey === rowKey);
    if (menu) menu.classList.add("open");
  }

  function bindSnDebugButtons(tr) {
    tr.querySelectorAll(".sn-debug-btn[data-action='start-session']").forEach((btn) => {
      btn.addEventListener("click", () => { if (typeof window.etfAiStartSession === "function") window.etfAiStartSession(btn.dataset.rowKey || ""); });
    });
    tr.querySelectorAll(".sn-debug-btn[data-action='end-session']").forEach((btn) => {
      btn.addEventListener("click", () => { if (typeof window.etfAiEndSession === "function") window.etfAiEndSession(btn.dataset.rowKey || ""); });
    });
    tr.querySelectorAll(".sn-debug-btn[data-action='upload']").forEach((btn) => {
      btn.addEventListener("click", () => { if (typeof window.etfAiUpload === "function") window.etfAiUpload(btn.dataset.rowKey || ""); });
    });
  }

  function syncPanelToFlags(tr, rowKey) {
    const flags = getPanelFlags(rowKey);
    const terminalsWrap = tr.querySelector(".sn-debug-terminals");
    const header = tr.querySelector(".sn-debug-header");
    const titleEl = header?.querySelector(".sn-debug-title");
    let aiControls = header?.querySelector(".sn-debug-ai-controls");
    const row = lastDisplayRows.find((r) => (r.sn || r.pn || r.bmc_ip) === rowKey);
    const snDisplay = panelRowKeyToSn.get(rowKey) || rowKey;
    const _sysIpVal = String(row?.sys_ip || "").trim().toUpperCase();
    const sysIpNA = !_sysIpVal || _sysIpVal === "N/A" || _sysIpVal === "NA" || _sysIpVal === "-";
    const flagsHost = flags.host && !sysIpNA;

    let hasAi = tr.querySelector(".sn-debug-ai-container") !== null;
    let hasSsh = tr.querySelector(".sn-debug-ssh-container") !== null;
    let hasBmc = tr.querySelector(".sn-debug-bmc-container") !== null;
    let hasHost = tr.querySelector(".sn-debug-host-container") !== null;

    if (hasAi && !flags.ai) {
      if (typeof window.etfAiEndSession === "function") window.etfAiEndSession(rowKey);
      if (typeof window.etfDestroySnTerminal === "function") window.etfDestroySnTerminal(rowKey, "ai");
      const el = tr.querySelector(".sn-debug-ai-container");
      if (el) el.remove();
      hasAi = false;
    }
    if (!hasAi && flags.ai && terminalsWrap) {
      const aiContainer = document.createElement("div");
      aiContainer.className = "sn-debug-terminal sn-debug-ai-container";
      aiContainer.style.cssText = "min-height:150px;flex:1";
      terminalsWrap.appendChild(aiContainer);
      if (typeof window.etfCreateSnTerminals === "function") {
        window.etfCreateSnTerminals(row?.sn || rowKey, rowKey, "ai", { aiEl: aiContainer, sshEl: null, bmcEl: null, hostEl: null, row });
        setTimeout(() => { if (typeof window.etfFitTerminals === "function") window.etfFitTerminals(rowKey); }, 150);
      }
      if (!aiControls && header) {
        aiControls = document.createElement("div");
        aiControls.className = "sn-debug-ai-controls";
        header.insertBefore(aiControls, header.querySelector(".sn-debug-hide"));
      }
      if (aiControls) {
        aiControls.innerHTML = "<button type=\"button\" class=\"sn-debug-btn\" data-row-key=\"" + escapeHtml(rowKey) + "\" data-action=\"start-session\">Start Session</button><button type=\"button\" class=\"sn-debug-btn\" data-row-key=\"" + escapeHtml(rowKey) + "\" data-action=\"end-session\">End Session</button><button type=\"button\" class=\"sn-debug-btn\" data-row-key=\"" + escapeHtml(rowKey) + "\" data-action=\"upload\">Upload</button>";
        aiControls.style.display = "";
        bindSnDebugButtons(tr);
      }
      hasAi = true;
    }

    if (hasSsh && !flags.term) {
      if (typeof window.etfDestroySnTerminal === "function") window.etfDestroySnTerminal(rowKey, "ssh");
      const el = tr.querySelector(".sn-debug-ssh-container");
      if (el) el.remove();
      hasSsh = false;
    }
    if (!hasSsh && flags.term && terminalsWrap) {
      const sshContainer = document.createElement("div");
      sshContainer.className = "sn-debug-terminal sn-debug-ssh-container";
      sshContainer.style.cssText = "min-height:150px;flex:1";
      terminalsWrap.appendChild(sshContainer);
      if (typeof window.etfCreateSnTerminals === "function") {
        window.etfCreateSnTerminals(row?.sn || rowKey, rowKey, "term", { aiEl: null, sshEl: sshContainer, bmcEl: null, hostEl: null, row });
        setTimeout(() => { if (typeof window.etfFitTerminals === "function") window.etfFitTerminals(rowKey); }, 150);
      }
      hasSsh = true;
    }

    if (hasBmc && !flags.bmc) {
      if (typeof window.etfDestroySnTerminal === "function") window.etfDestroySnTerminal(rowKey, "bmc");
      const el = tr.querySelector(".sn-debug-bmc-container");
      if (el) el.remove();
      hasBmc = false;
    }
    if (!hasBmc && flags.bmc && terminalsWrap && row?.bmc_ip) {
      const bmcContainer = document.createElement("div");
      bmcContainer.className = "sn-debug-terminal sn-debug-bmc-container";
      bmcContainer.style.cssText = "min-height:150px;flex:1";
      terminalsWrap.appendChild(bmcContainer);
      if (typeof window.etfCreateSnTerminals === "function") {
        window.etfCreateSnTerminals(row?.sn || rowKey, rowKey, "bmc", { aiEl: null, sshEl: null, bmcEl: bmcContainer, hostEl: null, row });
        setTimeout(() => { if (typeof window.etfFitTerminals === "function") window.etfFitTerminals(rowKey); }, 150);
      }
      hasBmc = true;
    }

    if (hasHost && !flagsHost) {
      if (typeof window.etfDestroySnTerminal === "function") window.etfDestroySnTerminal(rowKey, "host");
      const note = tr.querySelector(".sn-debug-host-note");
      if (note) note.remove();
      const el = tr.querySelector(".sn-debug-host-container");
      if (el) el.remove();
      hasHost = false;
    }
    if (!hasHost && flagsHost && terminalsWrap && row?.sys_ip) {
      const hostNote = document.createElement("div");
      hostNote.className = "sn-debug-host-note";
      hostNote.style.cssText = "font-size:0.75rem;color:var(--color-muted);padding:0.25rem 0.5rem;background:var(--bg-card);";
      hostNote.textContent = "Note: After power-on, host may take 4–5 minutes to boot; SSH will work once OS is up.";
      terminalsWrap.appendChild(hostNote);
      const hostContainer = document.createElement("div");
      hostContainer.className = "sn-debug-terminal sn-debug-host-container";
      hostContainer.style.cssText = "min-height:150px;flex:1";
      terminalsWrap.appendChild(hostContainer);
      if (typeof window.etfCreateSnTerminals === "function") {
        window.etfCreateSnTerminals(row?.sn || rowKey, rowKey, "host", { aiEl: null, sshEl: null, bmcEl: null, hostEl: hostContainer, row });
        setTimeout(() => { if (typeof window.etfFitTerminals === "function") window.etfFitTerminals(rowKey); }, 150);
      }
      hasHost = true;
    }

    const effectiveFlags = { ...flags, host: flags.host && !sysIpNA };
    const titleLabel = titleLabelFromFlags(effectiveFlags);
    if (titleEl) titleEl.textContent = snDisplay + " – " + titleLabel;
    const ac = tr.querySelector(".sn-debug-ai-controls");
    if (ac) ac.style.display = flags.ai ? "" : "none";
    if (terminalsWrap) terminalsWrap.style.height = terminalHeightFromFlags(effectiveFlags) + "px";
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
      window.etfUpdatePinnedSns(Array.from(pinnedSns).map((k) => ({
        rowKey: k,
        sn: lastDisplayRows.find((r) => (r.sn || r.pn || r.bmc_ip) === k)?.sn || k,
        room: currentRoom,
      })));
    }
  }

  window.etfUnpinSn = function (rowKey) {
    pinnedSns.delete(rowKey);
    renderTable(allRows);
    if (typeof window.etfUpdatePinnedSns === "function") {
      window.etfUpdatePinnedSns(Array.from(pinnedSns).map((k) => ({
        rowKey: k,
        sn: lastDisplayRows.find((r) => (r.sn || r.pn || r.bmc_ip) === k)?.sn || k,
        room: currentRoom,
      })));
    }
  };

  function renderTable(rows) {
    allRows = rows || [];
    const isSearchMode = filterQuery && filterQuery.trim() !== "";
    let displayRows = isSearchMode ? searchRows : allRows.filter(matchFilter);
    if (currentRoom !== "etf" && ["room6", "room7", "room8"].includes(currentRoom)) {
      displayRows = [...displayRows].sort((a, b) => {
        const slotA = (sfcSnMap[a.sn] || {}).slot_no || "";
        const slotB = (sfcSnMap[b.sn] || {}).slot_no || "";
        const numA = parseInt(slotA, 10);
        const numB = parseInt(slotB, 10);
        const hasA = !isNaN(numA);
        const hasB = !isNaN(numB);
        if (!hasA && !hasB) return 0;
        if (!hasA) return 1;
        if (!hasB) return -1;
        return numA - numB;
      });
    }
    dutCountEl.textContent = displayRows.length;

    if (displayRows.length === 0 && expandedPanels.size === 0) {
      const msg = isSearchMode && searchInFlight ? "Searching..." : "No DUTs";
      tbody.innerHTML = '<tr><td colspan="10" style="color: var(--color-muted); text-align: center; padding: 2rem;">' + escapeHtml(msg) + "</td></tr>";
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
      const flags = getPanelFlags(rowKey);
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
      const bmcKeyLabel = macKeys.bmc || "BMC MAC";
      const bmcTitle = bmcMatch === false
        ? ("SFC(" + bmcKeyLabel + "): " + (bmcMacSfc || "-") + " | DHCP: " + (bmcMacDhcp || "-"))
        : ("SFC(" + bmcKeyLabel + "): " + (bmcMacSfc || "-"));
      const bmcDiffInline = bmcMatch === false
        ? '<div class="mac-diff-inline" title="' + escapeHtml(bmcMacSfc + " vs " + bmcMacDhcp) + '">SFC: ' + escapeHtml(bmcMacSfc || "-") + " | DHCP: " + escapeHtml(bmcMacDhcp) + "</div>"
        : "";
      const sysDisplay = sysMacDhcpNA ? escapeHtml(sysMacSfc || "-") : escapeHtml(sysMacDhcp);
      const sysKeyLabel = macKeys.sys || "SYS MAC";
      const sysTitle = sysMacDhcpNA
        ? ("DHCP: N/A (showing SFC " + sysKeyLabel + "): " + (sysMacSfc || "-"))
        : (sysMatch === false
          ? ("SFC(" + sysKeyLabel + "): " + (sysMacSfc || "-") + " | DHCP: " + (sysMacDhcp || "-"))
          : ("SFC(" + sysKeyLabel + "): " + (sysMacSfc || "-") + " | DHCP: " + (sysMacDhcp || "-")));
      const sysDiffInline = sysMatch === false
        ? '<div class="mac-diff-inline" title="' + escapeHtml((sysMacSfc || "-") + " vs " + sysMacDhcp) + '">SFC: ' + escapeHtml(sysMacSfc || "-") + " | DHCP: " + escapeHtml(sysMacDhcp) + "</div>"
        : "";
      const sysIpVal = String(r.sys_ip || "").trim().toUpperCase();
      const sysIpNA = !sysIpVal || sysIpVal === "N/A" || sysIpVal === "NA" || sysIpVal === "-";

      htmlParts.push(`<tr data-sn="${escapeHtml(r.sn)}" data-row-key="${escapeHtml(rowKey)}">
        <td class="etf-td"><div class="etf-cell-inner etf-cell-inner--sn">
          <div class="sn-cell">
            <button type="button" class="sn-btn" data-sn="${escapeHtml(r.sn)}" data-row-key="${escapeHtml(rowKey)}" title="Debug options">${escapeHtml(snDisplay)}</button>
            <div class="sn-menu" data-row-key="${escapeHtml(rowKey)}">
              <label class="sn-menu-item"><input type="checkbox" data-action="ai" ${flags.ai ? "checked" : ""}> AI Debug</label>
              <label class="sn-menu-item"><input type="checkbox" data-action="term" ${flags.term ? "checked" : ""}> Terminal Debug</label>
              <label class="sn-menu-item"><input type="checkbox" data-action="bmc" ${flags.bmc ? "checked" : ""}> BMC Terminal</label>
              ${!sysIpNA ? '<label class="sn-menu-item"><input type="checkbox" data-action="host" ' + (flags.host ? "checked" : "") + '> Host Terminal</label>' : ""}
            </div>
            <button type="button" class="sn-copy-btn" data-sn="${escapeHtml(r.sn)}" title="Copy SN">Copy</button>
            <button type="button" class="pin-btn etf-pin-btn pin-icon-btn" data-row-key="${escapeHtml(rowKey)}" data-sn="${escapeHtml(r.sn)}" title="${isPinned ? "Unpin" : "Pin"}"><svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" stroke="currentColor" stroke-width="1.5"><path d="M16 12V4h1V2H7v2h1v8l-2 2v2h5.2v6h1.6v-6H18v-2l-2-2z"/></svg></button>
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
        <td class="etf-td etf-td-action">${r.sn ? (`<button type="button" class="etf-online-test-btn" data-sn="${escapeHtml(r.sn)}" title="Online test / Retest">Test</button>`) : '<span style="color:var(--color-muted);font-size:0.8rem">—</span>'}</td>
      </tr>`);

      if ((flags.ai || flags.term || flags.bmc || flags.host) && !savedPanels.has(rowKey)) {
        const showAi = flags.ai;
        const showSsh = flags.term;
        const showBmc = flags.bmc;
        const showHost = flags.host && !sysIpNA;
        const effectiveFlags = { ...flags, host: showHost };
        const titleLabel = titleLabelFromFlags(effectiveFlags);
        const termHeight = terminalHeightFromFlags(effectiveFlags);
        htmlParts.push(`<tr class="sn-debug-row" data-row-key="${escapeHtml(rowKey)}">
          <td colspan="10" class="sn-debug-panel" data-row-key="${escapeHtml(rowKey)}">
            <div class="sn-debug-panel-inner">
              <div class="sn-debug-header">
                <span class="sn-debug-title">${escapeHtml(snDisplay)} – ${escapeHtml(titleLabel)}</span>
                <div class="sn-debug-ai-controls">${showAi ? '<button type="button" class="sn-debug-btn" data-row-key="' + escapeHtml(rowKey) + '" data-action="start-session">Start Session</button><button type="button" class="sn-debug-btn" data-row-key="' + escapeHtml(rowKey) + '" data-action="end-session">End Session</button><button type="button" class="sn-debug-btn" data-row-key="' + escapeHtml(rowKey) + '" data-action="upload">Upload</button>' : ""}</div>
                <button type="button" class="sn-debug-hide" data-row-key="${escapeHtml(rowKey)}">Hide</button>
              </div>
              <div class="sn-debug-resize" data-row-key="${escapeHtml(rowKey)}" title="Drag to resize"></div>
              <div class="sn-debug-terminals" style="height: ${termHeight}px">
                ${showAi ? '<div class="sn-debug-terminal sn-debug-ai-container" style="min-height:150px;flex:1"></div>' : ""}
                ${showSsh ? '<div class="sn-debug-terminal sn-debug-ssh-container" style="min-height:150px;flex:1"></div>' : ""}
                ${showBmc ? '<div class="sn-debug-terminal sn-debug-bmc-container" style="min-height:150px;flex:1"></div>' : ""}
                ${showHost ? '<div class="sn-debug-host-note" style="font-size:0.75rem;color:var(--color-muted);padding:0.25rem 0.5rem;background:var(--bg-card);">Note: After power-on, host may take 4–5 minutes to boot; SSH will work once OS is up.</div><div class="sn-debug-terminal sn-debug-host-container" style="min-height:150px;flex:1"></div>' : ""}
              </div>
            </div>
          </td>
        </tr>`);
      }
    });

    disconnectedRowKeys.forEach((rowKey) => {
      const snDisplay = panelRowKeyToSn.get(rowKey) || rowKey;
      htmlParts.push(`<tr class="sn-disconnected-row" data-row-key="${escapeHtml(rowKey)}">
        <td colspan="10" style="padding: 0.75rem 1rem; background: rgba(245, 158, 11, 0.15); border-left: 4px solid #f59e0b; color: var(--color-text); font-size: 0.9rem;">
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
      syncPanelToFlags(saved, rowKey);
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
      syncPanelToFlags(saved, rowKey);
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

    tbody.querySelectorAll(".sn-menu input[data-action]").forEach((input) => {
      input.addEventListener("change", (e) => {
        e.stopPropagation();
        const menu = input.closest(".sn-menu");
        const rowKey = menu?.dataset.rowKey || "";
        const mode = input.dataset.action || "ai";
        const row = lastDisplayRows.find((r) => (r.sn || r.pn || r.bmc_ip) === rowKey);
        const sn = row?.sn || rowKey;
        onSnMenuToggle(rowKey, sn, mode);
      });
    });

    tbody.querySelectorAll(".etf-pin-btn").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        onPinSn(btn.dataset.rowKey || "", btn.dataset.sn || "");
      });
    });

    tbody.querySelectorAll(".etf-online-test-btn").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        openOnlineTest((btn.dataset.sn || "").trim());
      });
    });

    tbody.querySelectorAll(".sn-copy-btn").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        const sn = (btn.dataset.sn || "").trim();
        if (!sn) return;
        copyText(sn).then((ok) => {
          const oldTitle = btn.title || "Copy SN";
          btn.title = ok ? "Copied!" : "Copy failed";
          const oldText = btn.textContent;
          btn.textContent = ok ? "Copied" : "Retry";
          setTimeout(() => {
            btn.title = oldTitle;
            btn.textContent = oldText || "Copy";
          }, 900);
        });
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
      const flags = typeof act === "object" && act !== null ? act : getPanelFlags(rowKey);
      if (!flags.ai && !flags.term && !flags.bmc && !flags.host) return;
      if (typeof window.etfCreateSnTerminals === "function") {
        const panel = tbody.querySelector(`.sn-debug-panel[data-row-key="${escapeHtml(rowKey)}"]`);
        if (panel) {
          const aiEl = panel.querySelector(".sn-debug-ai-container");
          const sshEl = panel.querySelector(".sn-debug-ssh-container");
          const bmcEl = panel.querySelector(".sn-debug-bmc-container");
          const hostEl = panel.querySelector(".sn-debug-host-container");
          const row = lastDisplayRows.find((r) => (r.sn || r.pn || r.bmc_ip) === rowKey);
          const payload = { aiEl: flags.ai ? aiEl : null, sshEl: flags.term ? sshEl : null, bmcEl: flags.bmc ? bmcEl : null, hostEl: flags.host ? hostEl : null, row };
          window.etfCreateSnTerminals(row?.sn || rowKey, rowKey, payload);
          setTimeout(() => { if (typeof window.etfFitTerminals === "function") window.etfFitTerminals(rowKey); }, 150);
        }
      }
    });

    if (pinnedSns.size > 0 && typeof window.etfUpdatePinnedSns === "function") {
      window.etfUpdatePinnedSns(Array.from(pinnedSns).map((k) => ({
        rowKey: k,
        sn: lastDisplayRows.find((r) => (r.sn || r.pn || r.bmc_ip) === k)?.sn || k,
        room: currentRoom,
      })));
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
    if (isRescan) {
      btnRescan.disabled = true;
      const rTxt = btnRescan?.querySelector(".btn-text");
      const rSpin = btnRescan?.querySelector(".btn-spinner");
      if (rTxt) rTxt.classList.add("hidden");
      if (rSpin) rSpin.classList.remove("hidden");
    }
    return Promise.all([
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
            renderTable(data.rows);
          } else {
            allRows = data.rows || [];
            dutCountEl.textContent = (allRows.filter(matchFilter)).length;
          }
          verifyMacForRows(data.rows || []);
          lastUpdatedEl.textContent = data.last_updated || "-";
          nextUpdateSec = POLL_INTERVAL_MS / 1000;
          if (countdownInterval) clearInterval(countdownInterval);
          countdownInterval = setInterval(() => {
            nextUpdateSec--;
            if (nextUpdateSec <= 0) nextUpdateSec = POLL_INTERVAL_MS / 1000;
            nextUpdateEl.textContent = nextUpdateSec + "s";
          }, 1000);
        } else if (data.error) {
          tbody.innerHTML = '<tr><td colspan="10" style="color: var(--color-danger); text-align: center; padding: 2rem;">' + escapeHtml(data.error) + "</td></tr>";
        }
      })
      .catch((err) => {
        const msg = (err && err.message && err.message.includes('fetch')) ? "Cannot connect to server. Check if backend is running (python app.py)" : String(err);
        tbody.innerHTML = '<tr><td colspan="10" style="color: var(--color-danger); text-align: center; padding: 2rem;">' + escapeHtml(msg) + "</td></tr>";
      })
      .finally(() => {
        if (isRescan) {
          btnRescan.disabled = false;
          const rTxt = btnRescan?.querySelector(".btn-text");
          const rSpin = btnRescan?.querySelector(".btn-spinner");
          if (rTxt) rTxt.classList.remove("hidden");
          if (rSpin) rSpin.classList.add("hidden");
        }
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
    const vTxt = btnVerifyMac?.querySelector(".btn-text");
    const vSpin = btnVerifyMac?.querySelector(".btn-spinner");
    if (vTxt) vTxt.textContent = "Verifying...";
    if (vTxt) vTxt.classList.add("hidden");
    if (vSpin) vSpin.classList.remove("hidden");
    return fetch("/api/sfc/assy-info", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sns: uniq }),
    })
      .then((res) => res.json())
      .then((data) => {
        assySnMap = data.sn_map || {};
        renderTable(allRows);
        return true;
      })
      .catch(() => false)
      .finally(() => {
        verifyInFlight = false;
        btnVerifyMac.disabled = false;
        const vTxt = btnVerifyMac?.querySelector(".btn-text");
        const vSpin = btnVerifyMac?.querySelector(".btn-spinner");
        if (vTxt) { vTxt.textContent = "Verify MAC"; vTxt.classList.remove("hidden"); }
        if (vSpin) vSpin.classList.add("hidden");
      });
  }

  function schedulePoll() {
    if (pollTimer) clearTimeout(pollTimer);
    pollTimer = setTimeout(() => {
      fetchData(false);
      schedulePoll();
    }, POLL_INTERVAL_MS);
  }

  let otCtx = { sn: "", wip: null, prepare: null, emp: "SJOP", selectedMachineId: null };

  function otShowStep(step) {
    const steps = ["loading", "repair", "config", "machines", "result"];
    steps.forEach((s) => {
      const el = document.getElementById("etf-ot-step-" + s);
      if (el) el.style.display = s === step ? "block" : "none";
    });
  }

  function closeOnlineTestModal() {
    const modal = document.getElementById("etf-online-test-modal");
    if (modal) modal.setAttribute("aria-hidden", "true");
  }

  function otShowResult(ok, msg, detail) {
    otShowStep("result");
    const el = document.getElementById("etf-ot-result-msg");
    if (el) {
      el.textContent = msg;
      el.style.color = ok ? "#16a34a" : "#dc2626";
    }
    const det = document.getElementById("etf-ot-result-detail");
    if (det) det.textContent = detail || "";
  }

  function loadOtReasonCodes() {
    return fetch("/api/etf/online-test/reason-codes")
      .then((r) => r.json())
      .then((data) => {
        const sel = document.getElementById("etf-ot-reason");
        if (!sel || !data.ok || !data.reason_codes) return;
        sel.innerHTML = data.reason_codes.map((x) =>
          "<option value=\"" + escapeHtml(x.code) + "\">" + escapeHtml(x.code + " — " + (x.desc || "")) + "</option>"
        ).join("");
      });
  }

  function otUpdatePnPreview() {
    const base = (document.getElementById("etf-ot-pn")?.value || "").trim();
    const station = (document.getElementById("etf-ot-station")?.value || "").trim();
    const preview = document.getElementById("etf-ot-pn-preview");
    if (preview) preview.textContent = (base && station) ? "PN \u2192 " + base + "_" + station : "";
    const delBtn = document.getElementById("etf-ot-pn-del");
    if (delBtn) {
      const sel = document.getElementById("etf-ot-pn");
      const opt = sel?.options[sel.selectedIndex];
      delBtn.style.display = (opt && opt.dataset.custom === "1") ? "" : "none";
    }
  }

  function otRenderBases(bases) {
    const pn = document.getElementById("etf-ot-pn");
    if (!pn) return;
    pn.innerHTML = bases.map((b) =>
      "<option value=\"" + escapeHtml(b.base) + "\" data-custom=\"" + (b.is_default ? "0" : "1") + "\">"
      + escapeHtml(b.base) + (b.is_default ? "" : " (custom)") + "</option>"
    ).join("");
    otUpdatePnPreview();
  }

  function showOtConfig() {
    const d = otCtx.wip;
    const hint = document.getElementById("etf-ot-config-hint");
    if (hint) hint.textContent = "Next station: " + (d.next_station || "-") + ". Select station then PN base.";
    const snRo = document.getElementById("etf-ot-sn-ro");
    if (snRo) snRo.value = otCtx.sn;
    const empEl = document.getElementById("etf-ot-emp");
    if (empEl && !empEl.value) empEl.value = "SJOP";
    const st = document.getElementById("etf-ot-station");
    if (st) {
      st.innerHTML = (d.filtered_stations || []).map((g) =>
        "<option value=\"" + escapeHtml(g) + "\"" + (g === d.default_station ? " selected" : "") + ">" + escapeHtml(g) + "</option>"
      ).join("");
    }
    return fetch("/api/etf/online-test/pn-list")
      .then((r) => r.json())
      .then((data) => {
        if (data.ok && data.bases) otRenderBases(data.bases);
        otShowStep("config");
      });
  }

  function renderOtMachineList() {
    const filEl = document.getElementById("etf-ot-machine-filter");
    const filterRaw = (filEl && filEl.value) || "";
    const filter = filterRaw.trim().toLowerCase();
    const list = document.getElementById("etf-ot-machine-list");
    if (!list || !otCtx.prepare) return;
    const machines = otCtx.prepare.machines || [];
    const filtered = !filter
      ? machines
      : machines.filter((m) => {
        const t = (
          (m.text || "") + " " + (m.key || "") + " " + String(m.value || "") + " " +
          (m.user || "") + " " + (m.occupier || "")
        ).toLowerCase();
        return t.indexOf(filter) >= 0;
      });
    list.innerHTML = filtered.map((m) => {
      const id = m.value;
      const occ = (m.user || m.occupier || "").trim();
      const occHtml = occ ? "<span class=\"occ\">In use: " + escapeHtml(occ) + "</span>" : "";
      return "<div class=\"etf-ot-machine-item\" data-mid=\"" + escapeHtml(String(id)) + "\"><strong>#" +
        escapeHtml(String(id)) + "</strong> " + escapeHtml(m.text || m.key || "") + " " + occHtml + "</div>";
    }).join("");
    list.querySelectorAll(".etf-ot-machine-item").forEach((el) => {
      el.addEventListener("click", () => {
        list.querySelectorAll(".etf-ot-machine-item").forEach((x) => x.classList.remove("selected"));
        el.classList.add("selected");
        otCtx.selectedMachineId = parseInt(el.dataset.mid, 10);
        const picked = document.getElementById("etf-ot-machine-picked");
        if (picked) picked.textContent = "Selected machine ID: " + otCtx.selectedMachineId;
        const startBtn = document.getElementById("etf-ot-start");
        if (startBtn) startBtn.disabled = isNaN(otCtx.selectedMachineId);
      });
    });
  }

  function openOnlineTest(sn) {
    const modal = document.getElementById("etf-online-test-modal");
    if (!modal || !sn) return;
    otCtx = { sn: sn.trim().toUpperCase(), wip: null, prepare: null, emp: "SJOP", selectedMachineId: null };
    modal.setAttribute("aria-hidden", "false");
    otShowStep("loading");
    fetch("/api/etf/online-test/wip?sn=" + encodeURIComponent(otCtx.sn))
      .then((r) => r.json())
      .then((data) => {
        if (!data.ok) {
          otShowResult(false, data.error || "WIP request failed", "");
          return;
        }
        otCtx.wip = data;
        const title = document.getElementById("etf-ot-title");
        if (title) title.textContent = data.button_label || "Online Test";
        if (data.is_repair) {
          loadOtReasonCodes().then(() => {
            const badge = document.getElementById("etf-ot-repair-badge");
            if (badge) badge.textContent = "Retest (repair)";
            const remark = document.getElementById("etf-ot-remark");
            if (remark) remark.value = "Retest";
            const reEm = document.getElementById("etf-ot-repair-emp");
            if (reEm && !reEm.value) reEm.value = "SJOP";
            otShowStep("repair");
          });
        } else {
          showOtConfig().catch((e) => otShowResult(false, String(e.message || e), ""));
        }
      })
      .catch((e) => otShowResult(false, String(e.message || e), ""));
  }

  (function bindOnlineTestModal() {
    document.getElementById("etf-ot-close")?.addEventListener("click", closeOnlineTestModal);
    document.getElementById("etf-ot-done")?.addEventListener("click", closeOnlineTestModal);
    document.querySelector("#etf-online-test-modal .etf-ot-backdrop")?.addEventListener("click", closeOnlineTestModal);

    document.getElementById("etf-ot-repair-run")?.addEventListener("click", () => {
      const reason = document.getElementById("etf-ot-reason")?.value || "";
      const remark = document.getElementById("etf-ot-remark")?.value || "Retest";
      const emp = document.getElementById("etf-ot-repair-emp")?.value || "SJOP";
      if (!reason) {
        window.alert("Select reason code");
        return;
      }
      fetch("/api/etf/online-test/repair", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sn: otCtx.sn, reason_code: reason, remark, emp }),
      })
        .then((r) => r.json())
        .then((data) => {
          if (!data.ok) {
            window.alert(data.error || "Repair failed");
            return;
          }
          return fetch("/api/etf/online-test/wip?sn=" + encodeURIComponent(otCtx.sn)).then((r) => r.json());
        })
        .then((data) => {
          if (!data || !data.ok) return;
          otCtx.wip = data;
          const t = document.getElementById("etf-ot-title");
          if (t) t.textContent = data.button_label || "Online Test";
          return showOtConfig();
        })
        .catch((e) => window.alert(String(e)));
    });

    document.getElementById("etf-ot-pn")?.addEventListener("change", otUpdatePnPreview);
    document.getElementById("etf-ot-station")?.addEventListener("change", otUpdatePnPreview);

    document.getElementById("etf-ot-pn-add")?.addEventListener("click", () => {
      const inp = document.getElementById("etf-ot-pn-new");
      const v = (inp && inp.value || "").trim();
      if (!v) return;
      fetch("/api/etf/online-test/pn-list", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ base: v }),
      })
        .then((r) => r.json())
        .then((data) => {
          if (!data.ok || !data.bases) return;
          otRenderBases(data.bases);
          const pn = document.getElementById("etf-ot-pn");
          if (pn) pn.value = v;
          otUpdatePnPreview();
          if (inp) inp.value = "";
        });
    });

    document.getElementById("etf-ot-pn-del")?.addEventListener("click", () => {
      const pn = document.getElementById("etf-ot-pn");
      const base = (pn?.value || "").trim();
      if (!base) return;
      const opt = pn.options[pn.selectedIndex];
      if (!opt || opt.dataset.custom !== "1") {
        window.alert("Cannot remove a default base.");
        return;
      }
      if (!window.confirm("Remove custom base \"" + base + "\"?")) return;
      fetch("/api/etf/online-test/pn-list", {
        method: "DELETE",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ base: base }),
      })
        .then((r) => r.json())
        .then((data) => {
          if (!data.ok || !data.bases) return;
          otRenderBases(data.bases);
        });
    });

    document.getElementById("etf-ot-prepare")?.addEventListener("click", () => {
      const base = (document.getElementById("etf-ot-pn")?.value || "").trim();
      const station = (document.getElementById("etf-ot-station")?.value || "").trim();
      const emp = document.getElementById("etf-ot-emp")?.value || "SJOP";
      if (!base) {
        window.alert("Select a PN base");
        return;
      }
      if (!station) {
        window.alert("Select a station");
        return;
      }
      const pn = base + "_" + station;
      otCtx.emp = emp;
      fetch("/api/etf/online-test/prepare", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ pn_name: pn }),
      })
        .then((r) => r.json())
        .then((data) => {
          if (!data.ok) {
            window.alert(data.error || "Prepare failed");
            return;
          }
          otCtx.prepare = data;
          otCtx.selectedMachineId = null;
          const fil = document.getElementById("etf-ot-machine-filter");
          if (fil) fil.value = "";
          const picked = document.getElementById("etf-ot-machine-picked");
          if (picked) picked.textContent = "";
          const startBtn = document.getElementById("etf-ot-start");
          if (startBtn) startBtn.disabled = true;
          renderOtMachineList();
          otShowStep("machines");
        })
        .catch((e) => window.alert(String(e)));
    });

    document.getElementById("etf-ot-back-config")?.addEventListener("click", () => {
      otShowStep("config");
    });

    document.getElementById("etf-ot-start")?.addEventListener("click", () => {
      const p = otCtx.prepare;
      if (!p || otCtx.selectedMachineId == null || isNaN(otCtx.selectedMachineId)) return;
      const body = {
        sn: otCtx.sn,
        pn_name: p.pn_name,
        emp: otCtx.emp || document.getElementById("etf-ot-emp")?.value || "SJOP",
        machine_id: otCtx.selectedMachineId,
        shelf_proc_data: p.shelf_proc_data,
        scan_items: p.scan_items,
        env_items: p.env_items,
        sfc_ext: p.sfc_ext || "",
        units: p.units,
      };
      fetch("/api/etf/online-test/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      })
        .then((r) => r.json())
        .then((data) => {
          if (!data.ok) {
            otShowResult(false, data.error || "Start failed", "");
            return;
          }
          let detail = "";
          try {
            detail = JSON.stringify(data.steps || data, null, 2);
            if (detail.length > 5000) detail = detail.slice(0, 5000) + "…";
          } catch (e2) {
            detail = String(e2);
          }
          otShowResult(true, "Started. Log ID: " + (data.log_id != null ? data.log_id : "(see detail)"), detail);
        })
        .catch((e) => otShowResult(false, String(e.message || e), ""));
    });

    document.getElementById("etf-ot-machine-filter")?.addEventListener("input", () => {
      renderOtMachineList();
    });
  })();

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
        tbody.innerHTML = '<tr><td colspan="10" style="color: var(--color-muted); text-align: center; padding: 2rem;">Loading...</td></tr>';
      }
      fetchData(false);
      schedulePoll();
    });
  });

  fetchData(false).then(() => {
    fetch(`/api/etf/reset?room=${currentRoom}`, { method: "POST" }).catch(() => {});
  });
  schedulePoll();
  function initMacKeyInputs() {
    syncMacKeyInputs();
    fetchMacVerifyKeys();
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initMacKeyInputs);
  } else {
    initMacKeyInputs();
  }
  setTimeout(syncMacKeyInputs, 100);

  updateLastEndDurations();
  setInterval(updateLastEndDurations, 1000);
})();
