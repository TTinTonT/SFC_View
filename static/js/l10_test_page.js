(function () {
  const POLL_MS = 60000;
  const QUEUE_POLL_MS = 2500;
  const STORAGE_PREFIX = "l10TestExpanded:";
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

  const gridEl = document.getElementById("l10-grid");
  const metaMainEl = document.getElementById("l10-meta-main");
  const metaCountEl = document.getElementById("l10-meta-countdown");
  const errEl = document.getElementById("l10-error");

  let lastPayload = null;
  let nextPollAt = 0;
  let countdownTimer = null;
  /** @type {Record<string, any>} */
  let onlineQueueMap = {};
  /** When user was queued, open modal once job becomes active: { fixture, jobId, slot, sn } */
  let pendingModal = null;
  let arrowResizeBound = false;
  let queueDelegateBound = false;

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

  function readCooldownInputs() {
    const minEl = document.getElementById("l10-cd-min");
    const secEl = document.getElementById("l10-cd-sec");
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

  function isExpanded(fixtureNo) {
    try {
      return sessionStorage.getItem(STORAGE_PREFIX + fixtureNo) === "1";
    } catch (_) {
      return false;
    }
  }

  function setExpanded(fixtureNo, on) {
    try {
      sessionStorage.setItem(STORAGE_PREFIX + fixtureNo, on ? "1" : "0");
    } catch (_) {}
  }

  function trayClass(bucket) {
    const b = bucket || "unknown";
    const map = {
      idle: "l10-tray--idle",
      testing: "l10-tray--testing",
      testing_pass: "l10-tray--testing_pass",
      testing_fail: "l10-tray--testing_fail",
      on_hold: "l10-tray--on_hold",
      unknown: "l10-tray--unknown",
    };
    return map[b] || "l10-tray--unknown";
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

  function mergeOnlineQueueFromJson(json) {
    if (json && json.online_queue && typeof json.online_queue === "object") {
      onlineQueueMap = json.online_queue;
    }
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

  function hydrateQueueBars() {
    document.querySelectorAll(".l10-queuebar[data-fixture]").forEach((el) => {
      const fn = el.getAttribute("data-fixture") || "";
      const q = onlineQueueMap[fn];
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

  function drawQueueArrows() {
    document.querySelectorAll(".l10-card--fixture").forEach((card) => {
      const fn = card.getAttribute("data-fixture") || "";
      const q = onlineQueueMap[fn];
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
      const mid = "l10-ah-" + String(fn).replace(/[^a-zA-Z0-9_-]/g, "_");
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

  function bindQueueForceDelegation() {
    if (queueDelegateBound || !gridEl) return;
    queueDelegateBound = true;
    gridEl.addEventListener("click", function (ev) {
      const btn = ev.target && ev.target.closest && ev.target.closest("[data-l10-force]");
      if (!btn || !gridEl.contains(btn)) return;
      ev.stopPropagation();
      const fn = btn.getAttribute("data-l10-force") || "";
      if (!fn) return;
      postJson("/api/debug/l10-test/online-queue/force-next", { fixture_no: fn }).then(({ json }) => {
        if (!json.ok) {
          window.alert(json.error || "Force failed");
          return;
        }
        if (json.fixture) onlineQueueMap[fn] = json.fixture;
        pollOnlineQueue();
      });
    });
  }

  function tryOpenPendingModal() {
    if (!pendingModal || isEtfModalOpen()) return;
    if (typeof window.etfOpenOnlineTestModal !== "function") return;
    const q = onlineQueueMap[pendingModal.fixture];
    if (q && q.active && q.active.id === pendingModal.jobId) {
      const pm = pendingModal;
      pendingModal = null;
      openOnlineTestForQueueJob(pm.fixture, pm.slot, pm.sn, pm.jobId);
    }
  }

  function openOnlineTestForQueueJob(fixture, slot, sn, jobId) {
    window.etfOpenOnlineTestModal(sn, {
      queueJobId: jobId,
      fixtureNo: fixture,
      slotNo: slot,
      onStartSuccess: function () {
        const cd = readCooldownInputs();
        postJson("/api/debug/l10-test/online-queue/complete", {
          fixture_no: fixture,
          job_id: jobId,
          delay_min: cd.delay_min,
          delay_sec: cd.delay_sec,
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
        }).then(() => pollOnlineQueue());
      },
    });
  }

  function startOnlineTestFlow(fixture, slot, sn, bucket) {
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
    fetch("/api/etf/online-test/wip?sn=" + encodeURIComponent(snU))
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
        }).then(({ json }) => {
          if (!json.ok) {
            window.alert(json.error || "Enqueue failed");
            return;
          }
          if (json.immediate) {
            pendingModal = null;
            openOnlineTestForQueueJob(fixture, slot, snU, json.job.id);
          } else {
            pendingModal = {
              fixture: fixture,
              jobId: json.job.id,
              slot: slot,
              sn: snU,
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
        onlineQueueMap = data.fixtures || {};
        tryOpenPendingModal();
        hydrateQueueBars();
        drawQueueArrows();
      })
      .catch(function () {
        /* ignore */
      });
  }

  function renderFixtures(payload) {
    if (!gridEl) return;
    /* Menus moved to document.body must be removed before replacing grid (old wrap nodes go away). */
    document.querySelectorAll("body > .l10-tray-menu").forEach((m) => m.remove());
    const fixtures = payload.fixtures || [];
    if (!fixtures.length) {
      gridEl.innerHTML =
        '<p class="text-sm" style="color:var(--color-muted)">No fixtures returned.</p>';
      return;
    }

    const parts = [];
    fixtures.forEach((fx, fi) => {
      const fn = fx.fixture_no || "(unknown)";
      const slots = fx.slots || [];
      const exp = isExpanded(fn);
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
          const st = esc(s.status || "—");
          const gn = esc(s.group_name || "—");
          const bp = esc(s.build_phase || "—");
          const trayId = `l10m-${fi}-${si}`;
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
              `<div class="l10-tray-row1"><span>Slot ${esc(s.slot_no || "—")}</span><span>${st}</span></div>` +
              `<div class="l10-tray-row2">` +
              `<span class="l10-tray-sn-part">${esc(sn)}</span>` +
              `<span class="l10-tray-gb">${gn} · ${bp}</span>` +
              `</div>` +
              `</button>`,
          );
          parts.push(
            `<div class="l10-tray-menu hidden" id="${trayId}-menu" role="menu" aria-label="Test actions">` +
              `<button type="button" role="menuitem" data-action="online" data-fixture="${esc(fn)}" data-slot="${esc(s.slot_no || "")}" data-sn="${esc(sn === "—" ? "" : sn)}" data-bucket="${esc(s.ui_bucket || "")}">Online test</button>` +
              `<button type="button" role="menuitem" data-action="offline" data-fixture="${esc(fn)}" data-slot="${esc(s.slot_no || "")}" data-sn="${esc(sn === "—" ? "" : sn)}">Offline test</button>` +
              `<button type="button" role="menuitem" data-action="trial" data-fixture="${esc(fn)}" data-slot="${esc(s.slot_no || "")}" data-sn="${esc(sn === "—" ? "" : sn)}">Trial</button>` +
              `</div>`,
          );
          parts.push(`</div>`);
        });
      }
      parts.push(`</div></div></div>`);
    });
    gridEl.innerHTML = parts.join("");

    hydrateQueueBars();
    requestAnimationFrame(function () {
      drawQueueArrows();
    });

    gridEl.querySelectorAll("[data-toggle]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const fn = btn.getAttribute("data-toggle") || "";
        const next = !isExpanded(fn);
        setExpanded(fn, next);
        closeAllTrayMenus();
        const src = lastPayload || payload;
        if (src) renderFixtures(src);
      });
    });

    gridEl.querySelectorAll(".l10-tray-btn[data-tray-menu]").forEach((btn) => {
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

    gridEl.querySelectorAll(".l10-tray-menu [data-action]").forEach((item) => {
      item.addEventListener("click", (ev) => {
        ev.stopPropagation();
        const action = item.getAttribute("data-action");
        const sn = (item.getAttribute("data-sn") || "").trim();
        const fx = item.getAttribute("data-fixture") || "";
        const slot = item.getAttribute("data-slot") || "";
        const bucket = item.getAttribute("data-bucket") || "";
        closeAllTrayMenus();
        if (action === "online") {
          startOnlineTestFlow(fx, slot, sn, bucket);
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
          drawQueueArrows();
        },
        { passive: true },
      );
    }
  }

  function setMetaMain(html) {
    if (metaMainEl) metaMainEl.innerHTML = html;
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

  function fetchStatus() {
    return fetch("/api/debug/l10-test/status")
      .then((r) => r.json().then((j) => ({ ok: r.ok, json: j })))
      .then(({ json }) => {
        lastPayload = json;
        mergeOnlineQueueFromJson(json);
        tryOpenPendingModal();
        if (!json.ok) {
          setErr(json.error || "Request failed");
          setMetaMain(
            (json.fetched_at
              ? `Last fetch (CA): <strong>${esc(formatPacificInstant(json.fetched_at))}</strong> · `
              : "") + "<strong>SFC: error</strong>",
          );
          if (metaCountEl) metaCountEl.textContent = "";
          renderFixtures({ fixtures: [] });
          startCountdown();
          hydrateQueueBars();
          return;
        }
        setErr("");
        setMetaMain(buildMetaHtml(json));
        startCountdown();
        renderFixtures(json);
      })
      .catch((e) => {
        setErr(String(e.message || e));
        setMetaMain("Fetch failed");
        if (metaCountEl) metaCountEl.textContent = "";
        renderFixtures({ fixtures: [] });
        startCountdown();
      });
  }

  document.addEventListener("click", (ev) => {
    if (ev.target.closest(".l10-tray-btn") || ev.target.closest(".l10-tray-menu")) return;
    closeAllTrayMenus();
  });

  bindQueueForceDelegation();
  fetchStatus();
  setInterval(fetchStatus, POLL_MS);
  pollOnlineQueue();
  setInterval(pollOnlineQueue, QUEUE_POLL_MS);
})();

