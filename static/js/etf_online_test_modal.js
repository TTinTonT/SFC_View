/**
 * Online Test modal (shared by FA Debug / ETF Status / Testing page).
 * Depends on DOM ids: etf-online-test-modal, etf-ot-* (markup: templates/partials/etf_online_test_modal.html on Testing + L10).
 */
(function () {
  function escapeHtml(s) {
    if (s == null || s === undefined) return "";
    const div = document.createElement("div");
    div.textContent = String(s);
    return div.innerHTML;
  }

  /** Matches server default_emp_for_ui / resolve_sfis_emp fallback when inputs are empty. */
  function otProfileEmpFallback() {
    const w = typeof window !== "undefined" ? window : {};
    const d = String(w.__DEFAULT_EMPLOYEE_ID__ || "").trim();
    return d || "SJOP";
  }

  let otCtx = {
    sn: "",
    wip: null,
    prepare: null,
    emp: "",
    selectedMachineId: null,
    queueJobId: null,
    fixtureNo: null,
    slotNo: null,
    onStartSuccess: null,
    onStartFailure: null,
    onModalClosed: null,
    _otStartedSuccess: false,
  };
  let otApiBusy = 0;

  function otIsBusy() {
    return otApiBusy > 0;
  }
  function otPushBusy() {
    otApiBusy += 1;
    otSyncActionDisabledState();
  }
  function otPopBusy() {
    otApiBusy = Math.max(0, otApiBusy - 1);
    otSyncActionDisabledState();
  }
  function otSyncActionDisabledState() {
    const busy = otIsBusy();
    ["etf-ot-repair-run", "etf-ot-prepare", "etf-ot-pn-add", "etf-ot-pn-del"].forEach((id) => {
      const el = document.getElementById(id);
      if (el) el.disabled = busy;
    });
    const startBtn = document.getElementById("etf-ot-start");
    if (startBtn) {
      const mid = otCtx.selectedMachineId;
      startBtn.disabled = busy || mid == null || Number.isNaN(mid);
    }
  }

  function otShowStep(step) {
    const steps = ["loading", "repair", "config", "machines", "result"];
    steps.forEach((s) => {
      const el = document.getElementById("etf-ot-step-" + s);
      if (el) el.style.display = s === step ? "block" : "none";
    });
  }

  function closeOnlineTestModal() {
    const modal = document.getElementById("etf-online-test-modal");
    if (!modal) return;
    const cb = otCtx && otCtx.onModalClosed;
    const started = !!(otCtx && otCtx._otStartedSuccess);
    modal.setAttribute("aria-hidden", "true");
    if (typeof cb === "function") {
      try {
        cb({ started: started });
      } catch (e) {
        /* ignore */
      }
      otCtx.onModalClosed = null;
    }
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
    if (empEl && !String(empEl.value || "").trim()) empEl.value = otProfileEmpFallback();
    const st = document.getElementById("etf-ot-station");
    if (st) {
      st.innerHTML = (d.filtered_stations || []).map((g) =>
        "<option value=\"" + escapeHtml(g) + "\"" + (g === d.default_station ? " selected" : "") + ">" + escapeHtml(g) + "</option>"
      ).join("");
    }
    otPushBusy();
    return fetch("/api/etf/online-test/pn-list")
      .then((r) => r.json())
      .then((data) => {
        if (data.ok && data.bases) otRenderBases(data.bases);
        otShowStep("config");
      })
      .catch((e) => {
        otShowResult(false, String(e.message || e), "");
      })
      .finally(() => otPopBusy());
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
        if (startBtn) startBtn.disabled = otIsBusy() || isNaN(otCtx.selectedMachineId);
      });
    });
  }

  function openOnlineTest(sn, options) {
    options = options || {};
    const modal = document.getElementById("etf-online-test-modal");
    if (!modal || !sn) return;
    if (otIsBusy()) return;
    otCtx = {
      sn: sn.trim().toUpperCase(),
      wip: null,
      prepare: null,
      emp: (options.emp && String(options.emp).trim()) || otProfileEmpFallback(),
      selectedMachineId: null,
      queueJobId: options.queueJobId != null ? String(options.queueJobId) : null,
      fixtureNo: options.fixtureNo != null ? String(options.fixtureNo) : null,
      slotNo: options.slotNo != null ? String(options.slotNo) : null,
      onStartSuccess: typeof options.onStartSuccess === "function" ? options.onStartSuccess : null,
      onStartFailure: typeof options.onStartFailure === "function" ? options.onStartFailure : null,
      onModalClosed: typeof options.onModalClosed === "function" ? options.onModalClosed : null,
      _otStartedSuccess: false,
    };
    modal.setAttribute("aria-hidden", "false");
    otShowStep("loading");
    otPushBusy();
    fetch("/api/etf/online-test/wip?sn=" + encodeURIComponent(otCtx.sn))
      .then((r) => r.json())
      .then((data) => {
        if (!data.ok) {
          otShowResult(false, data.error || "WIP request failed", "");
          return;
        }
        if (data.crabber_test_in_progress) {
          otShowResult(
            false,
            "Crabber already has a test in progress for this SN (PROC/Testing). Finish or cancel before starting another.",
            "",
          );
          return;
        }
        otCtx.wip = data;
        const title = document.getElementById("etf-ot-title");
        if (title) title.textContent = data.button_label || "Online Test";
        if (data.is_repair) {
          return loadOtReasonCodes().then(() => {
            const badge = document.getElementById("etf-ot-repair-badge");
            if (badge) badge.textContent = "Retest (repair)";
            const remark = document.getElementById("etf-ot-remark");
            if (remark) remark.value = "Retest";
            const reEm = document.getElementById("etf-ot-repair-emp");
            if (reEm && !String(reEm.value || "").trim()) reEm.value = otProfileEmpFallback();
            otShowStep("repair");
          });
        }
        return showOtConfig();
      })
      .catch((e) => otShowResult(false, String(e.message || e), ""))
      .finally(() => otPopBusy());
  }

  (function bindOnlineTestModal() {
    document.getElementById("etf-ot-close")?.addEventListener("click", closeOnlineTestModal);
    document.getElementById("etf-ot-done")?.addEventListener("click", closeOnlineTestModal);
    document.querySelector("#etf-online-test-modal .etf-ot-backdrop")?.addEventListener("click", closeOnlineTestModal);

    document.getElementById("etf-ot-repair-run")?.addEventListener("click", () => {
      const reason = document.getElementById("etf-ot-reason")?.value || "";
      const remark = document.getElementById("etf-ot-remark")?.value || "Retest";
      const emp = (document.getElementById("etf-ot-repair-emp")?.value || "").trim();
      if (!reason) {
        window.alert("Select reason code");
        return;
      }
      otPushBusy();
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
          if (data.crabber_test_in_progress) {
            window.alert(
              "Crabber already has a test in progress for this SN. Finish or cancel before continuing.",
            );
            return;
          }
          otCtx.wip = data;
          const t = document.getElementById("etf-ot-title");
          if (t) t.textContent = data.button_label || "Online Test";
          return showOtConfig();
        })
        .catch((e) => window.alert(String(e)))
        .finally(() => otPopBusy());
    });

    document.getElementById("etf-ot-pn")?.addEventListener("change", otUpdatePnPreview);
    document.getElementById("etf-ot-station")?.addEventListener("change", otUpdatePnPreview);

    document.getElementById("etf-ot-pn-add")?.addEventListener("click", () => {
      const inp = document.getElementById("etf-ot-pn-new");
      const v = (inp && inp.value || "").trim();
      if (!v) return;
      otPushBusy();
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
        })
        .catch((e) => window.alert(String(e)))
        .finally(() => otPopBusy());
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
      otPushBusy();
      fetch("/api/etf/online-test/pn-list", {
        method: "DELETE",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ base: base }),
      })
        .then((r) => r.json())
        .then((data) => {
          if (!data.ok || !data.bases) return;
          otRenderBases(data.bases);
        })
        .catch((e) => window.alert(String(e)))
        .finally(() => otPopBusy());
    });

    document.getElementById("etf-ot-prepare")?.addEventListener("click", () => {
      const base = (document.getElementById("etf-ot-pn")?.value || "").trim();
      const station = (document.getElementById("etf-ot-station")?.value || "").trim();
      const emp = (document.getElementById("etf-ot-emp")?.value || "").trim();
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
      otPushBusy();
      fetch("/api/etf/online-test/prepare", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ pn_name: pn, sn: otCtx.sn || "" }),
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
        .catch((e) => window.alert(String(e)))
        .finally(() => otPopBusy());
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
        selected_station: (document.getElementById("etf-ot-station")?.value || "").trim(),
        emp: (otCtx.emp || document.getElementById("etf-ot-emp")?.value || "").trim(),
        machine_id: otCtx.selectedMachineId,
        shelf_proc_data: p.shelf_proc_data,
        scan_items: p.scan_items,
        env_items: p.env_items,
        sfc_ext: p.sfc_ext || "",
        units: p.units,
      };
      otPushBusy();
      fetch("/api/etf/online-test/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      })
        .then((r) => r.json())
        .then((data) => {
          if (!data.ok) {
            if (typeof otCtx.onStartFailure === "function") {
              try {
                otCtx.onStartFailure(data);
              } catch (e3) {
                /* ignore */
              }
            }
            otShowResult(false, data.error || "Start failed", "");
            return;
          }
          otCtx._otStartedSuccess = true;
          if (typeof otCtx.onStartSuccess === "function") {
            try {
              otCtx.onStartSuccess(data);
            } catch (e3) {
              /* ignore */
            }
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
        .catch((e) => {
          if (typeof otCtx.onStartFailure === "function") {
            try {
              otCtx.onStartFailure({ error: String(e.message || e) });
            } catch (e3) {
              /* ignore */
            }
          }
          otShowResult(false, String(e.message || e), "");
        })
        .finally(() => otPopBusy());
    });

    document.getElementById("etf-ot-machine-filter")?.addEventListener("input", () => {
      renderOtMachineList();
    });
  })();

  window.etfOpenOnlineTestModal = openOnlineTest;
})();
