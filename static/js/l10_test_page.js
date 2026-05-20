(function () {
  const POLL_MS = 60000;
  const QUEUE_POLL_MS = 2500;
  const STORAGE_PREFIX = "l10TestExpanded:";
  const CRAB_FA_EXPAND_PREFIX = "l10CrabberFaExp:";
  const CRAB_FA_POLL_MS = 45000;
  const PACIFIC_TZ = "America/Los_Angeles";

  /** Each full load of this page starts with all fixtures collapsed (ignore stale sessionStorage). */
  function clearFixtureExpandOnLoad() {
    try {
      const keys = [];
      for (let i = 0; i < sessionStorage.length; i++) {
        const k = sessionStorage.key(i);
        if (k && k.startsWith(STORAGE_PREFIX)) keys.push(k);
      }
      keys.forEach((k) => sessionStorage.removeItem(k));
    } catch (_) {}
  }
  clearFixtureExpandOnLoad();

  function crabberProfileQuery() {
    try {
      let v = sessionStorage.getItem("sfc_crabber_profile") || "sj";
      if (v !== "sj" && v !== "sv") v = "sj";
      return "&crabber_profile=" + encodeURIComponent(v);
    } catch (_) {
      return "&crabber_profile=sj";
    }
  }

  const MTF_TAB_KEY = "l10_mtf_active_site";
  const gridElSj = document.getElementById("l10-grid-sj");
  const gridElSv = document.getElementById("l10-grid-sv");
  const metaMainEl = document.getElementById("l10-meta-main");
  const metaCountEl = document.getElementById("l10-meta-countdown");
  const errEl = document.getElementById("l10-error");

  let lastPayloadBySite = { sj: null, sv: null };
  let nextPollAt = 0;
  let countdownTimer = null;
  /** Per-site fixture_no -> queue snapshot from server */
  let onlineQueues = { sj: {}, sv: {} };
  /** When user was queued, open modal once job becomes active: { fixture, jobId, slot, sn } */
  let pendingModal = null;
  let arrowResizeBound = false;
  const crabFaRegionsEl = document.getElementById("l10-crabber-fa-regions");
  const crabFaMetaEl = document.getElementById("l10-crabber-fa-meta");
  let lastCrabFaPayload = null;
  /** SV Crabber FA slot fields keyed by SN upper (merged into ETF SV DHCP table). */
  let lastCrabberSvSlotBySn = Object.create(null);
  let crabberFaTrayClickBound = false;

  /** Persist merged tray fields per SN (session) so rows keep Slot/Fixture/Last end/Remark when Crabber drops the tray. */
  const ETF_SV_STICKY_KEY = "l10EtfSvTraySticky:v1";

  function loadEtfSvSticky() {
    try {
      const raw = sessionStorage.getItem(ETF_SV_STICKY_KEY);
      const o = raw ? JSON.parse(raw) : {};
      return o && typeof o === "object" ? o : {};
    } catch (_) {
      return {};
    }
  }

  function saveEtfSvSticky(map) {
    try {
      sessionStorage.setItem(ETF_SV_STICKY_KEY, JSON.stringify(map));
    } catch (_) {}
  }

  function firstNonEmptyStr() {
    for (let i = 0; i < arguments.length; i++) {
      const v = arguments[i];
      if (v == null) continue;
      const s = String(v).trim();
      if (s) return s;
    }
    return "";
  }

  /** testing | pass | fail | unknown — optional crabLatest from per-SN Crabber search_log (newest row). */
  function etfSvStatusBucket(status, remark, crabLatest) {
    if (crabLatest && typeof crabLatest === "object") {
      const ev = String(crabLatest.node_log_event || "").trim().toUpperCase();
      const cr = String(crabLatest.result || "").trim();
      const crU = cr.toUpperCase();
      if (ev === "PROC" || crU === "TESTING" || /^TESTING\b/i.test(cr)) return "testing";
      if (/\bFAIL(ED)?\b/i.test(cr)) return "fail";
      if (/\bPASS(ED)?\b/i.test(cr) || /\bALL\s+PASS\b/i.test(crU)) return "pass";
    }
    const st = String(status || "").trim();
    const rm = String(remark || "").trim();
    const stU = st.toUpperCase();
    const rmU = rm.toUpperCase();
    if (/\bFAIL(ED)?\b/i.test(st) || /\bFAIL(ED)?\b/i.test(rm)) return "fail";
    if (/\bPASS(ED)?\b/i.test(st) || /\bALL\s+PASS\b/i.test(stU) || /\bPASS(ED)?\b/i.test(rm))
      return "pass";
    if (/\bTESTING\b/i.test(st) || /^TESTING\b/i.test(rmU) || /\bTESTING\b/i.test(rm)) return "testing";
    return "unknown";
  }

  function esc(s) {
    if (s == null || s === undefined) return "";
    const d = document.createElement("div");
    d.textContent = String(s);
    return d.innerHTML;
  }

  function escAttr(s) {
    return String(s || "")
      .replace(/&/g, "&amp;")
      .replace(/"/g, "&quot;")
      .replace(/</g, "&lt;");
  }

  function formatPacificInstant(input) {
    let d = input;
    if (typeof input === "string") {
      d = new Date(input);
    }
    if (!(d instanceof Date) || !Number.isFinite(d.getTime())) return "—";
    const baseOpts = {
      timeZone: PACIFIC_TZ,
      year: "numeric",
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
      second: "2-digit",
      hour12: true,
    };
    try {
      return new Intl.DateTimeFormat("en-US", { ...baseOpts, timeZoneName: "short" }).format(d);
    } catch (_) {
      return new Intl.DateTimeFormat("en-US", baseOpts).format(d) + " (Pacific)";
    }
  }

  /** Parse Crabber ISO, SFC "YYYY/MM/DD HH:mm:ss", or other last-end strings. */
  function parseLastEndToDate(raw) {
    if (raw == null) return null;
    const s = String(raw).trim();
    if (!s) return null;
    const sfc = s.match(/^(\d{4})\/(\d{2})\/(\d{2})\s+(\d{2}):(\d{2}):(\d{2})$/);
    if (sfc) {
      const d = new Date(+sfc[1], +sfc[2] - 1, +sfc[3], +sfc[4], +sfc[5], +sfc[6]);
      return Number.isFinite(d.getTime()) ? d : null;
    }
    const d = new Date(s);
    return Number.isFinite(d.getTime()) ? d : null;
  }

  /** User-facing Last end: Pacific (CA) instead of raw ISO stamp. */
  function formatLastEndDisplay(raw) {
    if (!raw) return "—";
    const d = parseLastEndToDate(raw);
    if (!d) {
      const t = String(raw).trim();
      return t || "—";
    }
    return formatPacificInstant(d);
  }

  function readCooldownForSite(site) {
    const isSv = site === "sv";
    const minEl = document.getElementById(isSv ? "l10-cd-min-sv" : "l10-cd-min");
    const secEl = document.getElementById(isSv ? "l10-cd-sec-sv" : "l10-cd-sec");
    let dm = parseInt((minEl && minEl.value) || "0", 10);
    let ds = parseInt((secEl && secEl.value) || "0", 10);
    if (!Number.isFinite(dm) || dm < 0) dm = 0;
    if (!Number.isFinite(ds) || ds < 0) ds = 0;
    if (ds > 59) ds = 59;
    if (dm > 180) dm = 180;
    return { delay_min: dm, delay_sec: ds };
  }

  function slotSortKey(slotNo) {
    const d = String(slotNo || "").replace(/\D/g, "");
    if (d) {
      const n = parseInt(d, 10);
      return Number.isFinite(n) ? n : 1e9;
    }
    return 1e9;
  }

  function sortSlotsExpanded(slots) {
    return slots.slice().sort((a, b) => {
      const ai = (a.ui_bucket || "") === "idle" ? 1 : 0;
      const bi = (b.ui_bucket || "") === "idle" ? 1 : 0;
      if (ai !== bi) return ai - bi;
      return slotSortKey(a.slot_no) - slotSortKey(b.slot_no);
    });
  }

  function visibleSlots(slots, expanded) {
    if (expanded) return sortSlotsExpanded(slots);
    return slots.filter((s) => (s.ui_bucket || "") !== "idle");
  }

  function expandStorageKey(site, fixtureNo) {
    const s = site === "sv" ? "sv" : "sj";
    return STORAGE_PREFIX + s + ":" + fixtureNo;
  }

  function isExpanded(site, fixtureNo) {
    try {
      return sessionStorage.getItem(expandStorageKey(site, fixtureNo)) === "1";
    } catch (_) {
      return false;
    }
  }

  function setExpanded(site, fixtureNo, on) {
    try {
      sessionStorage.setItem(expandStorageKey(site, fixtureNo), on ? "1" : "0");
    } catch (_) {}
  }

  function trayClass(bucket) {
    const b = bucket || "unknown";
    const map = {
      idle: "l10-tray--idle",
      testing: "l10-tray--testing",
      verify: "l10-tray--verify",
      testing_pass: "l10-tray--testing_pass",
      testing_fail: "l10-tray--testing_fail",
      on_hold: "l10-tray--on_hold",
      unknown: "l10-tray--unknown",
    };
    return map[b] || "l10-tray--unknown";
  }

  function getMtfTab() {
    try {
      const v = sessionStorage.getItem(MTF_TAB_KEY);
      return v === "sv" ? "sv" : "sj";
    } catch (_) {
      return "sj";
    }
  }

  function applyMtfTab() {
    const t = getMtfTab();
    const panelSj = document.getElementById("l10-mtf-panel-sj");
    const panelSv = document.getElementById("l10-mtf-panel-sv");
    const tabSj = document.getElementById("l10-tab-sj");
    const tabSv = document.getElementById("l10-tab-sv");
    if (panelSj) panelSj.classList.toggle("hidden", t !== "sj");
    if (panelSv) panelSv.classList.toggle("hidden", t !== "sv");
    if (tabSj) {
      const on = t === "sj";
      tabSj.classList.toggle("is-active", on);
      tabSj.setAttribute("aria-selected", on ? "true" : "false");
      tabSj.tabIndex = on ? 0 : -1;
    }
    if (tabSv) {
      const on = t === "sv";
      tabSv.classList.toggle("is-active", on);
      tabSv.setAttribute("aria-selected", on ? "true" : "false");
      tabSv.tabIndex = on ? 0 : -1;
    }
    refreshMtfMetaLine();
    syncErrToActiveTab();
  }

  function setMtfTab(site) {
    const v = site === "sv" ? "sv" : "sj";
    try {
      sessionStorage.setItem(MTF_TAB_KEY, v);
    } catch (_) {}
    applyMtfTab();
  }

  function refreshMtfMetaLine() {
    if (!metaMainEl) return;
    const t = getMtfTab();
    const j = t === "sv" ? lastPayloadBySite.sv : lastPayloadBySite.sj;
    const label = t === "sv" ? "SV MTF (Sunnyvale)" : "SJ MTF (San José)";
    if (!j) {
      metaMainEl.innerHTML = "<strong>" + esc(label) + ":</strong> —";
      return;
    }
    const err = !j.ok;
    metaMainEl.innerHTML =
      "<strong>" +
      esc(label) +
      ":</strong> " +
      (err
        ? '<span style="color:#dc2626">' + esc(j.error || "fetch failed") + "</span>"
        : buildMetaHtml(j));
  }

  function syncErrToActiveTab() {
    const tab = getMtfTab();
    const j = tab === "sv" ? lastPayloadBySite.sv : lastPayloadBySite.sj;
    if (j == null) {
      setErr("");
      return;
    }
    if (!j.ok) {
      setErr(
        (j && j.error) || (tab === "sv" ? "SV MTF tray status failed" : "SJ MTF tray status failed"),
      );
    } else {
      setErr("");
    }
  }

  function closeAllTrayMenus() {
    document.querySelectorAll(".l10-tray-menu").forEach((el) => {
      el.classList.add("hidden");
      el.style.left = "";
      el.style.top = "";
      const wrap = el._l10ReturnWrap;
      if (el.parentElement === document.body) {
        if (wrap && document.documentElement.contains(wrap)) {
          wrap.appendChild(el);
        } else {
          el.remove();
        }
      }
      el._l10ReturnWrap = null;
    });
    document.querySelectorAll(".l10-tray-btn[aria-expanded]").forEach((btn) => {
      btn.setAttribute("aria-expanded", "false");
    });
  }

  function positionTrayMenu(btn, menu) {
    const br = btn.getBoundingClientRect();
    const mw = 160;
    const left = Math.min(br.right + 6, window.innerWidth - mw - 8);
    const top = Math.max(8, Math.min(br.top, window.innerHeight - 120));
    menu.style.left = `${left}px`;
    menu.style.top = `${top}px`;
  }

  function isEtfModalOpen() {
    const m = document.getElementById("etf-online-test-modal");
    return m && m.getAttribute("aria-hidden") !== "true";
  }

  function postJson(url, body) {
    return fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    }).then((r) => r.json().then((j) => ({ ok: r.ok, status: r.status, json: j })));
  }

  function hydrateQueueBars(rootEl) {
    if (!rootEl) return;
    const site = rootEl.getAttribute("data-site") === "sv" ? "sv" : "sj";
    const map = onlineQueues[site] || {};
    rootEl.querySelectorAll(".l10-queuebar[data-fixture]").forEach((el) => {
      const fn = el.getAttribute("data-fixture") || "";
      const q = map[fn];
      if (!q || (!q.active && (!q.queued || !q.queued.length) && (q.cooldown_sec_remaining || 0) <= 0)) {
        el.innerHTML =
          '<span>Online queue: idle</span><button type="button" class="l10-force-btn" data-l10-force="' +
          escAttr(fn) +
          '">Force / clear wait</button>';
        return;
      }
      const bits = [];
      if ((q.cooldown_sec_remaining || 0) > 0) {
        bits.push(`Cooldown <strong>${q.cooldown_sec_remaining}s</strong> until next start allowed`);
      }
      if (q.active) {
        bits.push(
          `Running: <strong>Slot ${esc(String(q.active.slot_no || "—"))}</strong> · SN <strong>${esc(String(q.active.sn || ""))}</strong>`
        );
      }
      if (q.queued && q.queued.length) {
        const w = q.queued
          .map((j) => `Slot ${esc(String(j.slot_no || "—"))} (${esc(String(j.sn || ""))})`)
          .join(", ");
        bits.push(`Queued (${q.queued.length}): ${w}`);
      }
      el.innerHTML =
        "<span>" +
        bits.join(' <span style="opacity:.5">·</span> ') +
        '</span><button type="button" class="l10-force-btn" data-l10-force="' +
        escAttr(fn) +
        '">Force / clear wait</button>';
    });
  }

  function drawQueueArrows(rootEl) {
    if (!rootEl) return;
    const site = rootEl.getAttribute("data-site") === "sv" ? "sv" : "sj";
    const map = onlineQueues[site] || {};
    rootEl.querySelectorAll(".l10-card--fixture").forEach((card) => {
      if (card.hasAttribute("data-l10-skip-queue")) return;
      const fn = card.getAttribute("data-fixture") || "";
      const q = map[fn];
      const body = card.querySelector(".l10-card-body");
      const svg = body && body.querySelector(".l10-queue-svg");
      if (!body || !svg) return;
      if (!q || !q.queue_arrow) {
        svg.innerHTML = "";
        return;
      }
      const fromS = String(q.queue_arrow.from_slot || "");
      const toS = String(q.queue_arrow.to_slot || "");
      const sel = (slot) => body.querySelector('.l10-tray-btn[data-slot-no="' + escAttr(slot) + '"]');
      const btnFrom = sel(fromS);
      const btnTo = sel(toS);
      if (!btnFrom || !btnTo) {
        svg.innerHTML = "";
        return;
      }
      const br = body.getBoundingClientRect();
      const w = Math.max(1, body.clientWidth);
      const h = Math.max(1, body.clientHeight);
      const mid =
        "l10-ah-" + site + "-" + String(fn).replace(/[^a-zA-Z0-9_-]/g, "_");
      svg.setAttribute("viewBox", "0 0 " + w + " " + h);
      svg.setAttribute("width", String(w));
      svg.setAttribute("height", String(h));
      const r1 = btnFrom.getBoundingClientRect();
      const r2 = btnTo.getBoundingClientRect();
      const x1 = r1.left + r1.width / 2 - br.left;
      const y1 = r1.top + r1.height / 2 - br.top;
      const x2 = r2.left + r2.width / 2 - br.left;
      const y2 = r2.top + r2.height / 2 - br.top;
      svg.innerHTML =
        '<defs><marker id="' +
        mid +
        '" markerWidth="8" markerHeight="8" refX="6" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#6366f1"/></marker></defs>' +
        '<line x1="' +
        x1 +
        '" y1="' +
        y1 +
        '" x2="' +
        x2 +
        '" y2="' +
        y2 +
        '" stroke="#6366f1" stroke-width="2" marker-end="url(#' +
        mid +
        ')" opacity="0.85"/>';
    });
  }

  function bindQueueForceFor(gridRoot) {
    if (!gridRoot || gridRoot.dataset.l10ForceBound === "1") return;
    gridRoot.dataset.l10ForceBound = "1";
    const site = gridRoot.getAttribute("data-site") === "sv" ? "sv" : "sj";
    gridRoot.addEventListener("click", function (ev) {
      const btn = ev.target && ev.target.closest && ev.target.closest("[data-l10-force]");
      if (!btn || !gridRoot.contains(btn)) return;
      ev.stopPropagation();
      const fn = btn.getAttribute("data-l10-force") || "";
      if (!fn) return;
      postJson("/api/debug/l10-test/online-queue/force-next", { fixture_no: fn, site: site }).then(
        ({ json }) => {
          if (!json.ok) {
            window.alert(json.error || "Force failed");
            return;
          }
          if (json.fixture) onlineQueues[site][fn] = json.fixture;
          pollOnlineQueue();
        },
      );
    });
  }

  function tryOpenPendingModal() {
    if (!pendingModal || isEtfModalOpen()) return;
    if (typeof window.etfOpenOnlineTestModal !== "function") return;
    const qs = pendingModal.site === "sv" ? "sv" : "sj";
    const map = onlineQueues[qs] || {};
    const q = map[pendingModal.fixture];
    if (q && q.active && q.active.id === pendingModal.jobId) {
      const pm = pendingModal;
      pendingModal = null;
      openOnlineTestForQueueJob(pm.fixture, pm.slot, pm.sn, pm.jobId, pm.site || "sj");
    }
  }

  function openOnlineTestForQueueJob(fixture, slot, sn, jobId, site) {
    const st = site === "sv" ? "sv" : "sj";
    window.etfOpenOnlineTestModal(sn, {
      queueJobId: jobId,
      fixtureNo: fixture,
      slotNo: slot,
      onStartSuccess: function () {
        const cd = readCooldownForSite(st);
        postJson("/api/debug/l10-test/online-queue/complete", {
          fixture_no: fixture,
          job_id: jobId,
          delay_min: cd.delay_min,
          delay_sec: cd.delay_sec,
          site: st,
        }).then(({ json }) => {
          if (!json.ok) {
            window.alert(json.error || "Queue complete failed (cooldown may be wrong).");
          }
          pollOnlineQueue();
        });
      },
      onStartFailure: function () {
        /* user may close modal → abandon */
      },
      onModalClosed: function (ev) {
        if (ev && ev.started) return;
        postJson("/api/debug/l10-test/online-queue/abandon", {
          fixture_no: fixture,
          job_id: jobId,
          site: st,
        }).then(() => pollOnlineQueue());
      },
    });
  }

  function startOnlineTestFlow(fixture, slot, sn, bucket, site) {
    const st = site === "sv" ? "sv" : "sj";
    let snU = String(sn || "")
      .trim()
      .toUpperCase();
    const isIdle = String(bucket || "") === "idle";
    if (!snU && isIdle) {
      const entered = window.prompt(`Slot ${slot || "—"} is idle. Enter SN to run Online test:`, "");
      snU = String(entered || "")
        .trim()
        .toUpperCase();
    }
    if (!snU) {
      window.alert("No serial number on this tray; cannot start test.");
      return;
    }
    if (typeof window.etfOpenOnlineTestModal !== "function") {
      window.alert("Online test modal is not loaded.");
      return;
    }
    fetch("/api/etf/online-test/wip?sn=" + encodeURIComponent(snU) + crabberProfileQuery())
      .then((r) => r.json())
      .then((wip) => {
        if (!wip.ok) {
          window.alert(wip.error || "WIP request failed");
          return;
        }
        if (wip.crabber_test_in_progress) {
          window.alert(
            "Crabber already has a test in progress for this SN. Finish or cancel before starting online test.",
          );
          return;
        }
        return postJson("/api/debug/l10-test/online-queue/enqueue", {
          fixture_no: fixture,
          slot_no: slot,
          sn: snU,
          site: st,
        }).then(({ json }) => {
          if (!json.ok) {
            window.alert(json.error || "Enqueue failed");
            return;
          }
          if (json.immediate) {
            pendingModal = null;
            openOnlineTestForQueueJob(fixture, slot, snU, json.job.id, st);
          } else {
            pendingModal = {
              fixture: fixture,
              jobId: json.job.id,
              slot: slot,
              sn: snU,
              site: st,
            };
            window.alert(
              "Queued for this test base (position " +
                (json.position != null ? json.position : "?") +
                "). The Online test window will open when it is your turn.",
            );
            pollOnlineQueue();
          }
        });
      })
      .catch((e) => window.alert(String(e.message || e)));
  }

  function pollOnlineQueue() {
    fetch("/api/debug/l10-test/online-queue")
      .then((r) => r.json())
      .then((data) => {
        if (!data.ok) return;
        onlineQueues.sj = typeof data.sj === "object" && data.sj !== null ? data.sj : {};
        onlineQueues.sv = typeof data.sv === "object" && data.sv !== null ? data.sv : {};
        tryOpenPendingModal();
        hydrateQueueBars(gridElSj);
        hydrateQueueBars(gridElSv);
        drawQueueArrows(gridElSj);
        drawQueueArrows(gridElSv);
      })
      .catch(function () {
        /* ignore */
      });
  }

  function crabberFaExpandKey(region, etfIdx) {
    return CRAB_FA_EXPAND_PREFIX + region + ":" + etfIdx;
  }

  function isCrabberFaExpanded(region, etfIdx) {
    try {
      return sessionStorage.getItem(crabberFaExpandKey(region, etfIdx)) === "1";
    } catch (_) {
      return false;
    }
  }

  function setCrabberFaExpanded(region, etfIdx, on) {
    try {
      sessionStorage.setItem(crabberFaExpandKey(region, etfIdx), on ? "1" : "0");
    } catch (_) {}
  }

  function mapCrabberRowToTrayShape(s) {
    return Object.assign({}, s, {
      ui_bucket: s.occupied ? "testing" : "idle",
      slot_no: String(s.slot_within_etf != null ? s.slot_within_etf : ""),
      serial_number: s.sn || "",
    });
  }

  function visibleCrabberFaSlots(slots, expanded) {
    return visibleSlots(slots.map(mapCrabberRowToTrayShape), expanded);
  }

  function bindCrabberFaTrayOpens() {
    if (crabberFaTrayClickBound || !crabFaRegionsEl) return;
    crabberFaTrayClickBound = true;
    crabFaRegionsEl.addEventListener("click", function (ev) {
      const btn =
        ev.target && ev.target.closest && ev.target.closest("[data-crabber-sn]");
      if (!btn || !crabFaRegionsEl.contains(btn)) return;
      const sn = (btn.getAttribute("data-crabber-sn") || "").trim().toUpperCase();
      if (!sn || typeof window.etfOpenOnlineTestModal !== "function") return;
      closeAllTrayMenus();
      window.etfOpenOnlineTestModal(sn);
    });
    crabFaRegionsEl.addEventListener("click", function (ev) {
      const btn =
        ev.target && ev.target.closest && ev.target.closest("[data-crab-toggle]");
      if (!btn || !crabFaRegionsEl.contains(btn)) return;
      const rg = btn.getAttribute("data-crab-toggle") || "";
      const etf = parseInt(btn.getAttribute("data-crab-etf") || "0", 10);
      if (!rg || !etf) return;
      ev.stopPropagation();
      const next = !isCrabberFaExpanded(rg, etf);
      setCrabberFaExpanded(rg, etf, next);
      if (lastCrabFaPayload) renderCrabberFaDashboard(lastCrabFaPayload);
    });
  }

  function buildCrabberSvSlotMap(sv) {
    const map = Object.create(null);
    if (!sv || !sv.ok || !Array.isArray(sv.fixtures)) return map;
    sv.fixtures.forEach(function (fx) {
      const fixtureNo = String(fx.fixture_no || "").trim();
      (fx.slots || []).forEach(function (s) {
        if (!s || !s.occupied) return;
        const sn = String(s.serial_number || s.sn || "").trim();
        if (!sn) return;
        const key = sn.toUpperCase();
        const gs = s.global_slot != null ? s.global_slot : s.slot_within_etf || "";
        const slotDisp = String(
          s.slot_no != null && String(s.slot_no).trim() !== "" ? s.slot_no : gs,
        );
        map[key] = {
          slot_no: slotDisp,
          fixture_no: fixtureNo,
          last_end_time: String(s.log_time || "").trim().slice(0, 24),
          remark: [String(s.result || "").trim(), String(s.machine || "").trim()]
            .filter(Boolean)
            .join(" · "),
        };
      });
    });
    return map;
  }

  function renderCrabberFaDashboard(data) {
    if (!crabFaRegionsEl) return;
    bindCrabberFaTrayOpens();
    if (!data || !data.ok) {
      /* Keep lastCrabberSvSlotBySn so ETF SV merge does not clear on transient poll errors. */
      crabFaRegionsEl.innerHTML =
        '<p class="text-sm" style="color:var(--color-muted)">Crabber FA dashboard unavailable.</p>';
      if (crabFaMetaEl) crabFaMetaEl.textContent = "";
      return;
    }
    const sj = data.sj || {};
    const sv = data.sv || {};
    lastCrabberSvSlotBySn = buildCrabberSvSlotMap(sv);
    if (crabFaMetaEl) {
      crabFaMetaEl.textContent =
        `Sampled Crabber logs: ${data.max_pages || "—"} page(s) per site · SJ FA·L10·PROC hits: ${sj.matching_rows ?? "—"} · SV: ${sv.matching_rows ?? "—"} (${data.slots_per_etf || 13} slots/ETF).`;
    }

    function etfSvMergedBlockHtml() {
      return (
        '<div class="l10-etf-sv-block l10-etf-sv-block--merged" id="l10-etf-sv-block">' +
        '<h4 class="l10-etf-sv-merge-title">ETF SV — DHCP tray scan</h4>' +
        '<p class="text-xs l10-etf-sv-merge-desc" style="color:var(--color-muted);">Same TSV as Debug → ETF (<code>room=etf_sv</code>). FRU/SN is read by the scan script <strong>on</strong> <code>ETF_SV_SSH_HOST</strong> (default <strong>10.24.10.190</strong>). Each listed SN also queries <strong>Crabber SV</strong> (<code>/api/debug/l10-test/crabber-latest-for-sns</code>) for the newest test log row (pass / fail / testing). Crabber FA dashboard + SV SFC still fill Slot / Fixture when present; sticky session merge unchanged. Row tint: <strong>yellow</strong> = testing, <strong>green</strong> = pass, <strong>red</strong> = fail. <span class="l10-etf-sv-legend-scan">white</span> = DHCP-only (no status yet). Deploy: <code>python scripts/deploy_scan_tray_etf_sv.py</code></p>' +
        '<div id="l10-etf-sv-meta" class="text-xs mb-2" style="color:var(--color-muted);"></div>' +
        '<div class="l10-etf-sv-scroll">' +
        '<table class="l10-etf-sv-table" aria-label="ETF Sunnyvale DHCP trays">' +
        "<thead><tr><th>SN</th><th>PN</th><th>BMC IP</th><th>SYS IP</th><th>Slot</th><th>Fixture</th><th>Last end</th><th>Remark</th></tr></thead>" +
        '<tbody id="l10-etf-sv-tbody"></tbody></table></div></div>'
      );
    }

    function sideHtml(regionKey, regionTitle, side) {
      const parts = [];
      const isSv = regionKey === "sv";
      if (isSv) {
        parts.push('<div class="l10-fa-col-sv">');
        parts.push('<div class="l10-fa-region l10-fa-region--sv-scan-only">');
        parts.push(`<h3 class="l10-fa-region-title">${esc(regionTitle)}</h3>`);
        if (!side || !side.ok) {
          parts.push(
            `<p class="msg-error text-xs">${esc((side && side.error) || "Crabber fetch failed.")}</p>`,
          );
        } else {
          const fixtures = side.fixtures || [];
          if (!fixtures.length) {
            parts.push(
              `<p class="text-xs" style="color:var(--color-muted);margin-bottom:0.35rem">No FA / L10 / PROC rows in this sample.</p>`,
            );
          } else {
            parts.push(
              '<p class="text-xs" style="color:var(--color-muted);margin-bottom:0.35rem">Active FA slots from Crabber are merged into the table below by serial number (Slot / Fixture / Last end / Remark).</p>',
            );
          }
        }
        parts.push(etfSvMergedBlockHtml());
        parts.push("</div></div>");
        return parts.join("");
      }
      parts.push('<div class="l10-fa-region">');
      parts.push(`<h3 class="l10-fa-region-title">${esc(regionTitle)}</h3>`);
      if (!side || !side.ok) {
        parts.push(
          `<p class="msg-error text-xs">${esc((side && side.error) || "Crabber fetch failed.")}</p>`,
        );
        parts.push("</div>");
        return parts.join("");
      }
      const fixtures = side.fixtures || [];
      if (!fixtures.length) {
        parts.push(
          `<p class="text-xs" style="color:var(--color-muted);margin-bottom:0.35rem">No FA / L10 / PROC rows in this sample.</p>`,
        );
      }
      fixtures.forEach((fx) => {
        const etfIdx = fx.etf_index != null ? fx.etf_index : 1;
        const fnLabel = fx.fixture_no || `FA ETF ${etfIdx}`;
        const slots = fx.slots || [];
        const exp = isCrabberFaExpanded(regionKey, etfIdx);
        const vis = visibleCrabberFaSlots(slots, exp);
        const total = slots.length || 13;
        const chev = exp ? "▼" : "▶";
        const cardFix = `${regionKey}-etf-${etfIdx}`;
        parts.push(
          `<div class="l10-card l10-card--fixture" data-fixture="${escAttr(cardFix)}" data-l10-skip-queue="1">`,
        );
        parts.push('<div class="l10-card-inner">');
        parts.push(
          `<button type="button" class="l10-card-h w-full text-left" data-crab-toggle="${esc(regionKey)}" data-crab-etf="${etfIdx}" aria-expanded="${exp ? "true" : "false"}">` +
            `<span>${esc(fnLabel)}</span>` +
            `<span><small>${vis.length} / ${total} slots</small> ${chev}</span>` +
            `</button>`,
        );
        parts.push(`<div class="l10-card-body">`);
        if (!vis.length) {
          parts.push(
            `<p class="text-xs" style="color:var(--color-muted)">No occupied slots—expand for full rack.</p>`,
          );
        } else {
          vis.forEach((s) => {
            const gs = String(s.global_slot != null ? s.global_slot : s.slot_within_etf || "");
            const snDisp =
              s.serial_number != null && String(s.serial_number).trim() !== ""
                ? String(s.serial_number)
                : String(s.sn || "").trim() !== ""
                  ? String(s.sn)
                  : "—";
            const snRaw = snDisp !== "—" ? String(snDisp).trim() : "";
            const st = esc(s.result || (s.occupied ? "PROC" : "—"));
            const sub = `${esc(s.machine || "")}`.trim();
            const sub2 = esc(formatLastEndDisplay(String(s.log_time || "").trim()));
            parts.push('<div class="l10-tray-wrap">');
            parts.push(
              `<button type="button" class="l10-tray-btn ${esc(trayClass(s.ui_bucket))}"` +
                (snRaw ? ` data-crabber-sn="${escAttr(snRaw)}"` : "") +
                ` title="Global slot ${escAttr(gs)}${snRaw ? " · SN " + escAttr(snRaw) : ""}">`,
            );
            parts.push(
              `<div class="l10-tray-row1"><span>Slot ${esc(String(s.slot_no || gs))}</span><span>${st}</span></div>`,
            );
            parts.push(
              `<div class="l10-tray-row2">` +
                `<span class="l10-tray-sn-part">${esc(snDisp)}</span>` +
                `<span class="l10-tray-gb">${sub || " —"} · ${sub2 || " —"}</span>` +
                `</div>`,
            );
            parts.push(`</button></div>`);
          });
        }
        parts.push(`</div></div></div>`);
      });
      parts.push("</div>");
      return parts.join("");
    }

    crabFaRegionsEl.innerHTML =
      '<div class="l10-fa-regions-inner">' +
      sideHtml("sj", "FA — San Jose (Crabber)", sj) +
      sideHtml("sv", "FA — SV / SunnyVale (Crabber)", sv) +
      "</div>";
    requestAnimationFrame(function () {
      drawQueueArrows(gridElSj);
      drawQueueArrows(gridElSv);
    });
    fetchEtfSvPanel();
  }

  function rowFromSvDashboard(row, snMap) {
    const sn = String(row.sn || "").trim();
    return !!(sn && snMap && snMap[sn]);
  }

  function rowFromCrabberSv(row, crabMap) {
    const sn = String(row.sn || "").trim().toUpperCase();
    return !!(sn && crabMap && crabMap[sn]);
  }

  function etfSvSlotSortKey(snMap, crabMap, sn, stickyMap, latestMap) {
    const s = String(sn || "").trim();
    const su = s.toUpperCase();
    let slot = "";
    if (s && snMap && snMap[s]) slot = String((snMap[s] || {}).slot_no || "");
    else if (s && crabMap && crabMap[su]) slot = String((crabMap[su] || {}).slot_no || "");
    else if (su && stickyMap && stickyMap[su])
      slot = String((stickyMap[su] || {}).slot_no || "");
    else if (su && latestMap && latestMap[su] && latestMap[su].ok && latestMap[su].latest)
      slot = String((latestMap[su].latest.slot_hint || "").trim());
    const n = parseInt(String(slot).replace(/\D/g, ""), 10);
    return Number.isFinite(n) ? n : 1e9;
  }

  function rowFromCrabLatest(row, latestMap) {
    const snU = String(row.sn || "").trim().toUpperCase();
    if (!snU || !latestMap) return false;
    const e = latestMap[snU];
    return !!(e && e.ok && e.latest);
  }

  function rowFromStickyEtfSv(row, stickyMap) {
    const snU = String(row.sn || "").trim().toUpperCase();
    if (!snU || !stickyMap) return false;
    const o = stickyMap[snU];
    return !!(o && firstNonEmptyStr(o.slot_no, o.fixture_no, o.remark, o.status));
  }

  function etfSvMergeSortTier(row, snMap, crabMap, stickyMap, latestMap) {
    if (rowFromSvDashboard(row, snMap)) return 0;
    if (rowFromCrabberSv(row, crabMap)) return 1;
    if (stickyMap && rowFromStickyEtfSv(row, stickyMap)) return 1;
    if (latestMap && rowFromCrabLatest(row, latestMap)) return 1;
    return 2;
  }

  function sortEtfSvRows(rows, snMap, crabMap, stickyMap, latestMap) {
    const cm = crabMap || Object.create(null);
    const sm = stickyMap || {};
    const lm = latestMap || {};
    return [...(rows || [])].sort((a, b) => {
      const ta = etfSvMergeSortTier(a, snMap, cm, sm, lm);
      const tb = etfSvMergeSortTier(b, snMap, cm, sm, lm);
      if (ta !== tb) return ta - tb;
      const sna = String(a.sn || "").trim();
      const snb = String(b.sn || "").trim();
      return etfSvSlotSortKey(snMap, cm, sna, sm, lm) - etfSvSlotSortKey(snMap, cm, snb, sm, lm);
    });
  }

  function renderEtfSvPanel(rows, snMap, lastUpdated, etfOk, etfErr, sfcOk, crabLatestBySn) {
    const etfSvTbody = document.getElementById("l10-etf-sv-tbody");
    const etfSvMeta = document.getElementById("l10-etf-sv-meta");
    if (!etfSvTbody) return;
    const rws = Array.isArray(rows) ? rows : [];
    if (etfSvMeta) {
      const bits = [];
      if (!etfOk) bits.push("DHCP: " + String(etfErr || "unavailable"));
      else bits.push("DHCP rows: " + rws.length + (lastUpdated ? " · " + lastUpdated : ""));
      bits.push(sfcOk ? "SV dashboard: OK" : "SV dashboard: offline");
      etfSvMeta.textContent = bits.join(" · ");
    }
    if (!rws.length) {
      etfSvTbody.innerHTML =
        '<tr><td colspan="8" class="l10-etf-sv-td-muted">No ETF SV scan rows yet (room <code>etf_sv</code>; background poller or open Debug → ETF).</td></tr>';
      return;
    }
    const crab = lastCrabberSvSlotBySn || Object.create(null);
    const latest = crabLatestBySn && typeof crabLatestBySn === "object" ? crabLatestBySn : {};
    const sticky = loadEtfSvSticky();
    const sorted = sortEtfSvRows(rws, snMap, crab, sticky, latest);
    const parts = [];
    sorted.forEach((r) => {
      const sn = String(r.sn || "").trim();
      const snU = sn.toUpperCase();
      const fromDash = rowFromSvDashboard(r, snMap);
      const fromCrab = rowFromCrabberSv(r, crab);
      const fromLatest = rowFromCrabLatest(r, latest);
      const sfc = (snMap && snMap[sn]) || {};
      const cb = (crab && crab[snU]) || {};
      const clEnt = latest[snU];
      const cl = clEnt && clEnt.ok && clEnt.latest ? clEnt.latest : null;
      const liveSlot = firstNonEmptyStr(cb.slot_no, cl && cl.slot_hint, sfc.slot_no);
      const liveFix = firstNonEmptyStr(cb.fixture_no, sfc.fixture_no);
      const liveLet = firstNonEmptyStr(cb.last_end_time, cl && String(cl.log_time || "").trim(), sfc.last_end_time);
      const remarkCrab = String(cb.remark || "").trim();
      const remarkSfc = String(sfc.remark || "").trim().slice(0, 120);
      const remarkFromSearch = cl
        ? [String(cl.result || "").trim(), String(cl.machine || "").trim()].filter(Boolean).join(" · ")
        : "";
      const combinedDashSfc =
        remarkCrab && remarkSfc ? remarkCrab + " · " + remarkSfc : remarkCrab || remarkSfc;
      const liveRemark = firstNonEmptyStr(combinedDashSfc, remarkFromSearch);
      const liveStatus = firstNonEmptyStr(sfc.status, cl && String(cl.result || "").trim());
      const stPrev = sticky[snU] || {};
      const slotDisp = firstNonEmptyStr(liveSlot, stPrev.slot_no);
      const fixDisp = firstNonEmptyStr(liveFix, stPrev.fixture_no);
      const letRaw = firstNonEmptyStr(liveLet, stPrev.last_end_time);
      const remark = firstNonEmptyStr(liveRemark, stPrev.remark);
      const statusForRow = firstNonEmptyStr(liveStatus, stPrev.status);
      if (liveSlot || liveFix || liveLet || liveRemark || liveStatus || remarkFromSearch) {
        const next = { ...stPrev };
        if (liveSlot) next.slot_no = liveSlot;
        if (liveFix) next.fixture_no = liveFix;
        if (liveLet) next.last_end_time = liveLet;
        if (liveRemark) next.remark = liveRemark;
        if (liveStatus) next.status = liveStatus;
        sticky[snU] = next;
      }
      const bucket = etfSvStatusBucket(statusForRow, remark, cl);
      const hasOverlay = !!(slotDisp || fixDisp || letRaw || remark);
      let trc = "l10-etf-sv-tr ";
      if (bucket === "fail") trc += "l10-etf-sv-tr--st-fail";
      else if (bucket === "pass") trc += "l10-etf-sv-tr--st-pass";
      else if (bucket === "testing") trc += "l10-etf-sv-tr--st-testing";
      else if (fromDash || fromCrab || fromLatest || hasOverlay) trc += "l10-etf-sv-tr--dash";
      else trc += "l10-etf-sv-tr--scan";
      parts.push(
        `<tr class="${trc}">` +
          `<td class="l10-etf-sv-td">${esc(sn || "—")}</td>` +
          `<td class="l10-etf-sv-td">${esc(String(r.pn || "—"))}</td>` +
          `<td class="l10-etf-sv-td l10-etf-sv-mono">${esc(String(r.bmc_ip || "—"))}</td>` +
          `<td class="l10-etf-sv-td l10-etf-sv-mono">${esc(String(r.sys_ip || "—"))}</td>` +
          `<td class="l10-etf-sv-td">${esc(slotDisp || "—")}</td>` +
          `<td class="l10-etf-sv-td">${esc(fixDisp || "—")}</td>` +
          `<td class="l10-etf-sv-td" title="${escAttr(letRaw)}">${esc(formatLastEndDisplay(letRaw))}</td>` +
          `<td class="l10-etf-sv-td" title="${escAttr(remark)}">${esc(remark || "—")}</td>` +
          `</tr>`,
      );
    });
    saveEtfSvSticky(sticky);
    etfSvTbody.innerHTML = parts.join("");
  }

  function fetchEtfSvPanel() {
    if (!document.getElementById("l10-etf-sv-tbody")) return;
    const pj = function (url) {
      return fetch(url)
        .then((r) => r.json().then((j) => ({ httpOk: r.ok, json: j })))
        .catch(() => ({ httpOk: false, json: { ok: false, error: "network" } }));
    };
    Promise.all([pj("/api/etf/data?room=etf_sv"), pj("/api/sfc/tray-status-sv")]).then(function (pair) {
      const ej = pair[0].json;
      const sj = pair[1].json;
      const rows = ej && ej.ok && Array.isArray(ej.rows) ? ej.rows : [];
      const snMap = sj && sj.ok && sj.sn_map && typeof sj.sn_map === "object" ? sj.sn_map : {};
      const sns = rows
        .map(function (row) {
          return String(row.sn || "").trim();
        })
        .filter(Boolean)
        .slice(0, 30);
      if (!sns.length) {
        renderEtfSvPanel(rows, snMap, ej && ej.last_updated, !!(ej && ej.ok), ej && ej.error, !!(sj && sj.ok), {});
        return;
      }
      return fetch("/api/debug/l10-test/crabber-latest-for-sns", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sns: sns, crabber_profile: "sv" }),
      })
        .then(function (r) {
          return r.json().catch(function () {
            return { ok: false };
          });
        })
        .then(function (cj) {
          const bySn = cj && cj.ok && cj.by_sn && typeof cj.by_sn === "object" ? cj.by_sn : {};
          renderEtfSvPanel(
            rows,
            snMap,
            ej && ej.last_updated,
            !!(ej && ej.ok),
            ej && ej.error,
            !!(sj && sj.ok),
            bySn,
          );
        })
        .catch(function () {
          renderEtfSvPanel(
            rows,
            snMap,
            ej && ej.last_updated,
            !!(ej && ej.ok),
            ej && ej.error,
            !!(sj && sj.ok),
            {},
          );
        });
    });
  }

  function fetchCrabberFaDashboard() {
    if (!crabFaRegionsEl) return;
    fetch("/api/debug/l10-test/crabber-fa-dashboard?max_pages=6")
      .then((r) => r.json())
      .then((data) => {
        lastCrabFaPayload = data;
        renderCrabberFaDashboard(data);
      })
      .catch(() => {
        if (crabFaMetaEl) crabFaMetaEl.textContent = "Crabber FA poll failed (network).";
        renderCrabberFaDashboard({ ok: false });
      });
  }

  function renderFixtures(payload, gridRoot, site) {
    if (!gridRoot) return;
    const st = site === "sv" ? "sv" : "sj";
    /* Menus moved to document.body must be removed before replacing grid (old wrap nodes go away). */
    document.querySelectorAll("body > .l10-tray-menu").forEach((m) => m.remove());
    const fixtures = payload.fixtures || [];
    if (!fixtures.length) {
      gridRoot.innerHTML =
        '<p class="text-sm" style="color:var(--color-muted)">No fixtures returned.</p>';
      return;
    }

    const parts = [];
    fixtures.forEach((fx, fi) => {
      const fn = fx.fixture_no || "(unknown)";
      const slots = fx.slots || [];
      const exp = isExpanded(st, fn);
      const vis = visibleSlots(slots, exp);
      const total = slots.length;
      const visCount = vis.length;
      const chev = exp ? "▼" : "▶";
      parts.push(`<div class="l10-card l10-card--fixture" data-fixture="${esc(fn)}">`);
      parts.push(`<div class="l10-card-inner">`);
      parts.push(
        `<button type="button" class="l10-card-h w-full text-left" data-toggle="${esc(fn)}" aria-expanded="${exp ? "true" : "false"}">` +
          `<span>${esc(fn)}</span>` +
          `<span><small>${visCount} / ${total} trays</small> ${chev}</span>` +
        `</button>`,
      );
      parts.push(`<div class="l10-queuebar" data-fixture="${esc(fn)}"></div>`);
      parts.push(`<div class="l10-card-body"><svg class="l10-queue-svg" data-fixture="${esc(fn)}" aria-hidden="true"></svg>`);
      if (!vis.length) {
        parts.push(
          `<p class="text-xs" style="color:var(--color-muted)">No non-idle trays. Expand to see idle.</p>`,
        );
      } else {
        vis.forEach((s, si) => {
          const sn =
            s.serial_number != null && String(s.serial_number).trim() !== ""
              ? String(s.serial_number)
              : "—";
          const stEsc = esc(s.status || "—");
          const gn = esc(s.group_name || "—");
          const bp = esc(s.build_phase || "—");
          const trayId = `l10m-${st}-${fi}-${si}`;
          const trayTip =
            "Slot " +
            String(s.slot_no || "—") +
            " — " +
            String(s.status || "—") +
            (sn !== "—" ? " — SN " + String(sn) : "");
          const trayTitleAttr = esc(trayTip).replace(/"/g, "&quot;");
          parts.push(`<div class="l10-tray-wrap">`);
          parts.push(
            `<button type="button" class="l10-tray-btn ${trayClass(s.ui_bucket)}" id="${trayId}" ` +
              `data-tray-menu="${trayId}-menu" aria-expanded="false" aria-haspopup="true" ` +
              `data-fixture-no="${esc(fn)}" data-slot-no="${esc(s.slot_no || "")}" data-sn="${esc(sn === "—" ? "" : sn)}" ` +
              `title="${trayTitleAttr}">` +
              `<div class="l10-tray-row1"><span>Slot ${esc(s.slot_no || "—")}</span><span>${stEsc}</span></div>` +
              `<div class="l10-tray-row2">` +
              `<span class="l10-tray-sn-part">${esc(sn)}</span>` +
              `<span class="l10-tray-gb">${gn} · ${bp}</span>` +
              `</div>` +
              `</button>`,
          );
          parts.push(
            `<div class="l10-tray-menu hidden" id="${trayId}-menu" role="menu" aria-label="Test actions">` +
              `<button type="button" role="menuitem" data-action="online" data-fixture="${esc(fn)}" data-slot="${esc(s.slot_no || "")}" data-sn="${esc(sn === "—" ? "" : sn)}" data-bucket="${esc(s.ui_bucket || "")}" data-site="${esc(st)}">Online test</button>` +
              `<button type="button" role="menuitem" data-action="offline" data-fixture="${esc(fn)}" data-slot="${esc(s.slot_no || "")}" data-sn="${esc(sn === "—" ? "" : sn)}">Offline test</button>` +
              `<button type="button" role="menuitem" data-action="trial" data-fixture="${esc(fn)}" data-slot="${esc(s.slot_no || "")}" data-sn="${esc(sn === "—" ? "" : sn)}">Trial</button>` +
              `</div>`,
          );
          parts.push(`</div>`);
        });
      }
      parts.push(`</div></div></div>`);
    });
    gridRoot.innerHTML = parts.join("");

    hydrateQueueBars(gridRoot);
    requestAnimationFrame(function () {
      drawQueueArrows(gridRoot);
    });

    gridRoot.querySelectorAll("[data-toggle]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const fn = btn.getAttribute("data-toggle") || "";
        const next = !isExpanded(st, fn);
        setExpanded(st, fn, next);
        closeAllTrayMenus();
        const src = lastPayloadBySite[st] || payload;
        if (src) renderFixtures(src, gridRoot, st);
      });
    });

    gridRoot.querySelectorAll(".l10-tray-btn[data-tray-menu]").forEach((btn) => {
      btn.addEventListener("click", (ev) => {
        ev.stopPropagation();
        const menuId = btn.getAttribute("data-tray-menu");
        const menu = menuId ? document.getElementById(menuId) : null;
        const open = btn.getAttribute("aria-expanded") === "true";
        closeAllTrayMenus();
        if (!open && menu) {
          if (!menu._l10ReturnWrap) menu._l10ReturnWrap = menu.parentElement;
          document.body.appendChild(menu);
          menu.classList.remove("hidden");
          positionTrayMenu(btn, menu);
          btn.setAttribute("aria-expanded", "true");
        }
      });
    });

    gridRoot.querySelectorAll(".l10-tray-menu [data-action]").forEach((item) => {
      item.addEventListener("click", (ev) => {
        ev.stopPropagation();
        const action = item.getAttribute("data-action");
        const sn = (item.getAttribute("data-sn") || "").trim();
        const fx = item.getAttribute("data-fixture") || "";
        const slot = item.getAttribute("data-slot") || "";
        const bucket = item.getAttribute("data-bucket") || "";
        const siteMenu = item.getAttribute("data-site") === "sv" ? "sv" : "sj";
        closeAllTrayMenus();
        if (action === "online") {
          startOnlineTestFlow(fx, slot, sn, bucket, siteMenu);
          return;
        }
        if (!sn) {
          window.alert("No serial number on this tray; cannot start test.");
          return;
        }
        window.alert(
          `Test action “${action}” for SN ${sn} (fixture ${fx}, slot ${slot}) — wiring TBD.`,
        );
      });
    });

    if (!arrowResizeBound) {
      arrowResizeBound = true;
      window.addEventListener(
        "resize",
        function () {
          drawQueueArrows(gridElSj);
          drawQueueArrows(gridElSv);
        },
        { passive: true },
      );
    }
  }

  function setErr(msg) {
    if (!errEl) return;
    if (msg) {
      errEl.textContent = msg;
      errEl.classList.remove("hidden");
    } else {
      errEl.textContent = "";
      errEl.classList.add("hidden");
    }
  }

  function startCountdown() {
    if (countdownTimer) clearInterval(countdownTimer);
    nextPollAt = Date.now() + POLL_MS;
    function tick() {
      if (!metaCountEl) return;
      const sec = Math.max(0, Math.ceil((nextPollAt - Date.now()) / 1000));
      metaCountEl.textContent = sec > 0 ? ` · Next refresh in ${sec}s` : " · Refreshing…";
    }
    tick();
    countdownTimer = setInterval(tick, 1000);
  }

  function buildMetaHtml(json) {
    if (json.fetched_at) {
      return `Last fetch (CA): <strong>${esc(formatPacificInstant(json.fetched_at))}</strong>`;
    }
    return "Last fetch: —";
  }

  function fetchBothTrayStatuses() {
    const pj = function (path) {
      return fetch(path)
        .then((r) => r.json().then((j) => ({ httpOk: r.ok, json: j })))
        .catch(() => ({ httpOk: false, json: { ok: false, error: "network" } }));
    };
    return Promise.all([pj("/api/debug/l10-test/status"), pj("/api/debug/l10-test/status-sv")]).then(
      function (pair) {
        const sjR = pair[0];
        const svR = pair[1];
        const sjJson = sjR.json;
        const svJson = svR.json;

        lastPayloadBySite.sj = sjJson;
        lastPayloadBySite.sv = svJson;
        if (sjJson && typeof sjJson.online_queue === "object" && sjJson.online_queue !== null) {
          onlineQueues.sj = sjJson.online_queue;
        }
        if (svJson && typeof svJson.online_queue === "object" && svJson.online_queue !== null) {
          onlineQueues.sv = svJson.online_queue;
        }
        tryOpenPendingModal();

        refreshMtfMetaLine();
        syncErrToActiveTab();

        if (metaCountEl) metaCountEl.textContent = "";
        renderFixtures(sjJson && sjJson.fixtures !== undefined ? sjJson : { fixtures: [] }, gridElSj, "sj");
        renderFixtures(svJson && svJson.fixtures !== undefined ? svJson : { fixtures: [] }, gridElSv, "sv");
        startCountdown();
        hydrateQueueBars(gridElSj);
        hydrateQueueBars(gridElSv);
        drawQueueArrows(gridElSj);
        drawQueueArrows(gridElSv);
      },
    );
  }

  document.addEventListener("click", (ev) => {
    if (ev.target.closest(".l10-tray-btn") || ev.target.closest(".l10-tray-menu")) return;
    closeAllTrayMenus();
  });

  (function bindMtfTabs() {
    const bSj = document.getElementById("l10-tab-sj");
    const bSv = document.getElementById("l10-tab-sv");
    if (bSj) {
      bSj.addEventListener("click", function () {
        if (getMtfTab() === "sj") return;
        setMtfTab("sj");
      });
    }
    if (bSv) {
      bSv.addEventListener("click", function () {
        if (getMtfTab() === "sv") return;
        setMtfTab("sv");
      });
    }
    applyMtfTab();
  })();

  bindQueueForceFor(gridElSj);
  bindQueueForceFor(gridElSv);
  fetchCrabberFaDashboard();
  setInterval(fetchCrabberFaDashboard, CRAB_FA_POLL_MS);
  fetchEtfSvPanel();
  setInterval(fetchEtfSvPanel, POLL_MS);
  fetchBothTrayStatuses();
  setInterval(fetchBothTrayStatuses, POLL_MS);
  pollOnlineQueue();
  setInterval(pollOnlineQueue, QUEUE_POLL_MS);
})();

