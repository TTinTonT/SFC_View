/**
 * Trial Run shelf: Crabber released list + in-app prepare/start (trial_run=true).
 */
(function () {
  const PROJECT_ID = typeof window.__TRIAL_RUN_PROJECT_ID__ === "number" ? window.__TRIAL_RUN_PROJECT_ID__ : 48;

  function escapeHtml(s) {
    if (s == null || s === undefined) return "";
    const div = document.createElement("div");
    div.textContent = String(s);
    return div.innerHTML;
  }

  function profileEmp() {
    const d = String(typeof window !== "undefined" && window.__DEFAULT_EMPLOYEE_ID__ ? window.__DEFAULT_EMPLOYEE_ID__ : "").trim();
    return d || "SJOP";
  }

  let trBusy = 0;
  let trCtx = {
    card: null,
    prepare: null,
    sn: "",
    emp: "",
    selectedMachineId: null,
  };

  function pushBusy() {
    trBusy += 1;
    syncBusy();
  }
  function popBusy() {
    trBusy = Math.max(0, trBusy - 1);
    syncBusy();
  }
  function syncBusy() {
    const b = trBusy > 0;
    document.querySelectorAll(".tr-modal [data-tr-busy-disable]").forEach((el) => {
      el.disabled = b;
    });
  }

  function showModal(show) {
    const m = document.getElementById("tr-modal");
    if (!m) return;
    m.setAttribute("aria-hidden", show ? "false" : "true");
  }

  function showStep(step) {
    ["tr-step-config", "tr-step-machines", "tr-step-result"].forEach((id) => {
      const el = document.getElementById(id);
      if (el) el.style.display = "none";
    });
    const active = document.getElementById("tr-step-" + step);
    if (active) active.style.display = "block";
  }

  function setResult(ok, msg, detail) {
    showStep("result");
    const msgEl = document.getElementById("tr-result-msg");
    const detEl = document.getElementById("tr-result-detail");
    if (msgEl) {
      msgEl.textContent = msg;
      msgEl.style.color = ok ? "#16a34a" : "#dc2626";
    }
    if (detEl) detEl.textContent = detail || "";
  }

  function renderMachineList() {
    const filEl = document.getElementById("tr-machine-filter");
    const filterRaw = (filEl && filEl.value) || "";
    const filter = filterRaw.trim().toLowerCase();
    const list = document.getElementById("tr-machine-list");
    if (!list || !trCtx.prepare) return;
    const machines = trCtx.prepare.machines || [];
    const filtered = !filter
      ? machines
      : machines.filter((m) => {
          const t = (
            (m.text || "") +
            " " +
            (m.key || "") +
            " " +
            String(m.value || "") +
            " " +
            (m.user || "") +
            " " +
            (m.occupier || "")
          ).toLowerCase();
          return t.indexOf(filter) >= 0;
        });
    list.innerHTML = filtered
      .map((m) => {
        const id = m.value;
        const occ = (m.user || m.occupier || "").trim();
        const occHtml = occ ? '<span class="tr-occ">In use: ' + escapeHtml(occ) + "</span>" : "";
        return (
          '<div class="tr-machine-item" data-mid="' +
          escapeHtml(String(id)) +
          '"><strong>#' +
          escapeHtml(String(id)) +
          "</strong> " +
          escapeHtml(m.text || m.key || "") +
          " " +
          occHtml +
          "</div>"
        );
      })
      .join("");
    list.querySelectorAll(".tr-machine-item").forEach((el) => {
      el.addEventListener("click", () => {
        list.querySelectorAll(".tr-machine-item").forEach((x) => x.classList.remove("selected"));
        el.classList.add("selected");
        trCtx.selectedMachineId = parseInt(el.dataset.mid, 10);
        const picked = document.getElementById("tr-machine-picked");
        if (picked) picked.textContent = "Selected machine ID: " + trCtx.selectedMachineId;
        const startBtn = document.getElementById("tr-btn-start");
        if (startBtn) startBtn.disabled = trBusy > 0 || Number.isNaN(trCtx.selectedMachineId);
      });
    });
  }

  function loadStations() {
    const sel = document.getElementById("tr-filter-station");
    if (!sel) return;
    pushBusy();
    fetch("/api/debug/trial-run/stations")
      .then((r) => r.json())
      .then((data) => {
        if (!data.ok) {
          sel.innerHTML = '<option value="">(stations failed)</option>';
          return;
        }
        const opts = ['<option value="">All stations</option>'];
        (data.stations || []).forEach((s) => {
          opts.push(
            '<option value="' + escapeHtml(String(s.id)) + '">' + escapeHtml(s.name || String(s.id)) + "</option>",
          );
        });
        sel.innerHTML = opts.join("");
        loadShelf();
      })
      .catch(() => {
        sel.innerHTML = '<option value="">(network error)</option>';
        loadShelf();
      })
      .finally(() => popBusy());
  }

  function loadShelf() {
    const sel = document.getElementById("tr-filter-station");
    const grid = document.getElementById("tr-card-grid");
    const note = document.getElementById("tr-shelf-status");
    if (!grid) return;
    const stationId = sel ? String(sel.value || "").trim() : "";
    const qs =
      "project_id=" +
      encodeURIComponent(String(PROJECT_ID)) +
      "&page=1&page_size=240&station_id=" +
      encodeURIComponent(stationId || "null");
    pushBusy();
    if (note) note.textContent = "Loading…";
    fetch("/api/debug/trial-run/shelf?" + qs)
      .then((r) => r.json())
      .then((data) => {
        if (!data.ok) {
          grid.innerHTML = "";
          if (note) note.textContent = data.error || "Load failed";
          return;
        }
        const items = data.items || [];
        if (note) {
          let t = items.length + " procedure(s)";
          if (data.missing_pn_name_count) t += " — " + data.missing_pn_name_count + " missing pn_name (Trial run may fail until Crabber row includes PN).";
          note.textContent = t;
        }
        const linkIcon =
          '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></svg>';
        const docIcon =
          '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/><path d="M12 18v-6"/><path d="M9 15h6"/></svg>';
        grid.innerHTML = items
          .map((p) => {
            const trialRunOffered = p.is_pn_mapping === true;
            const rev = p.rev ? "#" + escapeHtml(p.rev) : "";
            const pn = (p.pn_name || "").trim();
            const badge = pn || "—";
            const meta =
              escapeHtml(p.modified_date || "") +
              (p.releaser ? "<br>released by " + escapeHtml(p.releaser) : "");
            const badgeClass = trialRunOffered ? "tr-card-badge" : "tr-card-badge tr-card-badge-unmapped";
            const badgeInner = trialRunOffered
              ? linkIcon + " <span>" + escapeHtml(badge) + "</span>"
              : "<span>" + escapeHtml(badge) + "</span>";
            const trialBtn = trialRunOffered
              ? '<button type="button" class="tr-btn tr-btn-trial" data-action="trial">Trial run</button>'
              : "";
            return (
              '<article class="tr-card" data-sp-id="' +
              escapeHtml(String(p.id)) +
              '" data-pn-name="' +
              escapeHtml(pn) +
              '" data-station="' +
              escapeHtml(p.station || "") +
              '" data-tp-label="' +
              escapeHtml(p.tp_label || "") +
              '" data-trial-run-offered="' +
              (trialRunOffered ? "1" : "0") +
              '">' +
              '<div class="tr-card-head"><span class="tr-card-doc" aria-hidden="true">' +
              docIcon +
              '</span><span class="tr-card-tp">' +
              escapeHtml(p.tp_label || "") +
              " " +
              rev +
              "</span></div>" +
              '<div class="' +
              badgeClass +
              '">' +
              badgeInner +
              "</div>" +
              '<div class="tr-card-project">' +
              escapeHtml(p.project || "") +
              "</div>" +
              '<div class="tr-card-testname">' +
              escapeHtml(p.station || "") +
              "</div>" +
              '<div class="tr-card-meta">' +
              meta +
              "</div>" +
              '<div class="tr-card-actions">' +
              trialBtn +
              '<button type="button" class="tr-btn tr-btn-sfc" data-action="sfc" disabled title="Not wired">SFC Settings</button>' +
              '<button type="button" class="tr-btn tr-btn-post" data-action="post" disabled title="Not wired">Post-action</button>' +
              "</div></article>"
            );
          })
          .join("");
      })
      .catch((e) => {
        grid.innerHTML = "";
        if (note) note.textContent = String(e.message || e);
      })
      .finally(() => popBusy());
  }

  function openTrialModal(card) {
    if (!card || card.dataset.trialRunOffered !== "1") {
      window.alert("Trial run is not available for this row (PN mapping required), matching Crabber.");
      return;
    }
    trCtx = {
      card,
      prepare: null,
      sn: "",
      emp: profileEmp(),
      selectedMachineId: null,
    };
    const spId = card.dataset.spId;
    const pn = (card.dataset.pnName || "").trim();
    if (!spId) {
      window.alert("Missing shelf procedure id");
      return;
    }
    if (!pn) {
      window.alert("This row has no pn_name in Crabber; cannot prepare. Check shelf API fields.");
      return;
    }
    const title = document.getElementById("tr-modal-title");
    if (title) title.textContent = "Trial run — " + (card.dataset.tpLabel || "") + " (" + spId + ")";
    const snEl = document.getElementById("tr-input-sn");
    const empEl = document.getElementById("tr-input-emp");
    if (snEl) snEl.value = "";
    if (empEl) empEl.value = trCtx.emp;
    showModal(true);
    showStep("config");
  }

  function bindGrid() {
    const grid = document.getElementById("tr-card-grid");
    if (!grid) return;
    grid.addEventListener("click", (e) => {
      const btn = e.target.closest(".tr-btn");
      if (!btn || btn.disabled) return;
      const action = btn.getAttribute("data-action");
      const card = btn.closest(".tr-card");
      if (!card) return;
      if (action === "trial") openTrialModal(card);
    });
  }

  function bindModal() {
    document.getElementById("tr-modal-close")?.addEventListener("click", () => showModal(false));
    document.querySelector("#tr-modal .tr-modal-backdrop")?.addEventListener("click", () => showModal(false));
    document.getElementById("tr-btn-prepare")?.addEventListener("click", () => {
      const sn = (document.getElementById("tr-input-sn")?.value || "").trim().toUpperCase();
      const emp = (document.getElementById("tr-input-emp")?.value || "").trim();
      if (!sn) {
        window.alert("Enter serial number (SCAN_SYSTEM_SN)");
        return;
      }
      if (!emp) {
        window.alert("Enter operator ID (OP_ID)");
        return;
      }
      const card = trCtx.card;
      if (!card) return;
      trCtx.sn = sn;
      trCtx.emp = emp;
      trCtx.prepare = null;
      trCtx.selectedMachineId = null;
      pushBusy();
      fetch("/api/debug/trial-run/prepare", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          sp_id: parseInt(card.dataset.spId, 10),
          pn_name: (card.dataset.pnName || "").trim(),
          sn: trCtx.sn,
        }),
      })
        .then((r) => r.json())
        .then((data) => {
          if (!data.ok) {
            setResult(false, data.error || "Prepare failed", "");
            return;
          }
          trCtx.prepare = data;
          const fil = document.getElementById("tr-machine-filter");
          if (fil) fil.value = "";
          const picked = document.getElementById("tr-machine-picked");
          if (picked) picked.textContent = "";
          const startBtn = document.getElementById("tr-btn-start");
          if (startBtn) startBtn.disabled = true;
          showStep("machines");
          renderMachineList();
        })
        .catch((e) => setResult(false, String(e.message || e), ""))
        .finally(() => popBusy());
    });
    document.getElementById("tr-machine-filter")?.addEventListener("input", renderMachineList);
    document.getElementById("tr-btn-back-machines")?.addEventListener("click", () => showStep("config"));
    document.getElementById("tr-btn-start")?.addEventListener("click", () => {
      const p = trCtx.prepare;
      const card = trCtx.card;
      if (!p || trCtx.selectedMachineId == null || Number.isNaN(trCtx.selectedMachineId) || !card) return;
      const body = {
        sn: trCtx.sn,
        pn_name: p.pn_name,
        selected_station: (card.dataset.station || "").trim(),
        emp: trCtx.emp,
        machine_id: trCtx.selectedMachineId,
        shelf_proc_data: p.shelf_proc_data,
        scan_items: p.scan_items,
        env_items: p.env_items,
        sfc_ext: p.sfc_ext || "",
        units: p.units,
        trial_run: true,
      };
      pushBusy();
      fetch("/api/etf/online-test/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      })
        .then((r) => r.json())
        .then((data) => {
          if (!data.ok) {
            setResult(false, data.error || "Start failed", "");
            return;
          }
          let detail = "";
          try {
            detail = JSON.stringify(data.steps || data, null, 2);
            if (detail.length > 5000) detail = detail.slice(0, 5000) + "…";
          } catch (e2) {
            detail = String(e2);
          }
          setResult(
            true,
            "Started (trial run). Log ID: " + (data.log_id != null ? data.log_id : "(see detail)"),
            detail,
          );
        })
        .catch((e) => setResult(false, String(e.message || e), ""))
        .finally(() => popBusy());
    });
    document.getElementById("tr-result-done")?.addEventListener("click", () => showModal(false));
  }

  document.getElementById("tr-btn-refresh-shelf")?.addEventListener("click", loadShelf);
  document.getElementById("tr-filter-station")?.addEventListener("change", loadShelf);

  document.addEventListener("DOMContentLoaded", () => {
    loadStations();
    bindGrid();
    bindModal();
  });
})();
