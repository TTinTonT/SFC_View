(function () {
  const POLL_MS = 60000;
  const STORAGE_PREFIX = "l10TestExpanded:";
  const PACIFIC_TZ = "America/Los_Angeles";

  const gridEl = document.getElementById("l10-grid");
  const metaMainEl = document.getElementById("l10-meta-main");
  const metaCountEl = document.getElementById("l10-meta-countdown");
  const errEl = document.getElementById("l10-error");

  let lastPayload = null;
  let nextPollAt = 0;
  let countdownTimer = null;

  function esc(s) {
    if (s == null || s === undefined) return "";
    const d = document.createElement("div");
    d.textContent = String(s);
    return d.innerHTML;
  }

  /** Format instant (Date or ISO string) for display in California (Pacific). */
  function formatPacificInstant(input) {
    let d = input;
    if (typeof input === "string") {
      d = new Date(input);
    }
    if (!(d instanceof Date) || !Number.isFinite(d.getTime())) return "—";
    // Do not mix dateStyle/timeStyle with timeZoneName — throws RangeError in many engines.
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

  function renderFixtures(payload) {
    if (!gridEl) return;
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
      parts.push(`<div class="l10-card" data-fixture="${esc(fn)}">`);
      parts.push(
        `<button type="button" class="l10-card-h w-full text-left" data-toggle="${esc(fn)}" aria-expanded="${exp ? "true" : "false"}">` +
          `<span>${esc(fn)}</span>` +
          `<span><small>${visCount} / ${total} trays</small> ${chev}</span>` +
        `</button>`
      );
      parts.push(`<div class="l10-card-body">`);
      if (!vis.length) {
        parts.push(
          `<p class="text-xs" style="color:var(--color-muted)">No non-idle trays. Expand to see idle.</p>`
        );
      } else {
        vis.forEach((s, si) => {
          const sn = s.serial_number != null && String(s.serial_number).trim() !== "" ? String(s.serial_number) : "—";
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
            `</button>`
          );
          parts.push(
            `<div class="l10-tray-menu hidden" id="${trayId}-menu" role="menu" aria-label="Test actions">` +
              `<button type="button" role="menuitem" data-action="online" data-fixture="${esc(fn)}" data-slot="${esc(s.slot_no || "")}" data-sn="${esc(sn === "—" ? "" : sn)}">Online test</button>` +
              `<button type="button" role="menuitem" data-action="offline" data-fixture="${esc(fn)}" data-slot="${esc(s.slot_no || "")}" data-sn="${esc(sn === "—" ? "" : sn)}">Offline test</button>` +
              `<button type="button" role="menuitem" data-action="trial" data-fixture="${esc(fn)}" data-slot="${esc(s.slot_no || "")}" data-sn="${esc(sn === "—" ? "" : sn)}">Trial</button>` +
            `</div>`
          );
          parts.push(`</div>`);
        });
      }
      parts.push(`</div></div>`);
    });
    gridEl.innerHTML = parts.join("");

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
        closeAllTrayMenus();
        if (!sn) {
          window.alert("No serial number on this tray; cannot start test.");
          return;
        }
        window.alert(`Test action “${action}” for SN ${sn} (fixture ${fx}, slot ${slot}) — wiring TBD.`);
      });
    });
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
        if (!json.ok) {
          setErr(json.error || "Request failed");
          setMetaMain(
            (json.fetched_at
              ? `Last fetch (CA): <strong>${esc(formatPacificInstant(json.fetched_at))}</strong> · `
              : "") + "<strong>SFC: error</strong>"
          );
          if (metaCountEl) metaCountEl.textContent = "";
          renderFixtures({ fixtures: [] });
          startCountdown();
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

  fetchStatus();
  setInterval(fetchStatus, POLL_MS);
})();
