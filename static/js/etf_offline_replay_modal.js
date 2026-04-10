/* Raw offline replay modal for Testing page. */
(function () {
  function $(id) { return document.getElementById(id); }
  function esc(s) {
    var d = document.createElement("div");
    d.textContent = String(s == null ? "" : s);
    return d.innerHTML;
  }

  var state = {
    selected: null,
    prepared: null,
    pollTimer: null,
    cleanupCalled: false,
    replayConsoleText: null,
    replayConsoleReadError: "",
  };
  var LS_TCS = "etfOfflineReplayTcsMeta";

  function stopReplayPoll() {
    if (state.pollTimer) {
      clearInterval(state.pollTimer);
      state.pollTimer = null;
    }
  }

  function updateInlineReplayStatus(status, summary) {
    var el = $("etf-offline-replay-inline-status");
    if (!el) return;
    var s = String(status || "").toLowerCase();
    el.className = "self-center text-xs font-medium whitespace-nowrap";
    var text = "Replay: —";
    if (s === "pass") {
      el.classList.add("text-green-600");
      text = "Replay: PASS";
    } else if (s === "fail") {
      el.classList.add("text-red-600");
      text = "Replay: FAIL";
    } else if (s === "running") {
      el.classList.add("text-[var(--color-muted)]");
      text = "Replay: running…";
    } else if (s === "prepared") {
      el.classList.add("text-[var(--color-muted)]");
      text = "Replay: waiting…";
    } else if (s === "timeout") {
      el.classList.add("text-amber-600");
      text = "Replay: timeout";
    } else if (s === "error") {
      el.classList.add("text-amber-600");
      text = "Replay: error";
    } else if (s === "unknown") {
      el.classList.add("text-[var(--color-muted)]");
      text = "Replay: unknown";
    } else {
      el.classList.add("text-[var(--color-muted)]");
      text = "Replay: " + String(status || "—");
    }
    el.textContent = text;
    if (summary) el.setAttribute("title", summary);
    else el.removeAttribute("title");
  }

  function updateReplayStatusBadge(status, summary, full) {
    updateInlineReplayStatus(status, summary);
    var el = $("etf-or-replay-status");
    if (!el) return;
    var lines = ["Replay status: " + String(status || "-")];
    if (summary) lines.push("Summary: " + summary);
    if (full && full.remote_console_log_path) lines.push("Console log (remote): " + full.remote_console_log_path);
    if (full && full.remote_exit_code !== undefined && full.remote_exit_code !== null) lines.push("Exit code: " + full.remote_exit_code);
    el.textContent = lines.join("\n");
  }

  function syncConsoleLogButton() {
    var vbtn = $("etf-or-view-console");
    if (!vbtn) return;
    vbtn.hidden = state.replayConsoleText === null;
  }

  function resetReplayConsoleUi() {
    state.replayConsoleText = null;
    state.replayConsoleReadError = "";
    var vbtn = $("etf-or-view-console");
    var vpre = $("etf-or-console-view");
    if (vbtn) vbtn.hidden = true;
    if (vpre) {
      vpre.hidden = true;
      vpre.textContent = "";
    }
    syncConsoleLogButton();
  }

  function fetchReplayStatusOnce() {
    if (!state.prepared || !state.prepared.status_url) return;
    fetch(state.prepared.status_url, {
      credentials: "same-origin",
      headers: { Accept: "application/json" },
    })
      .then(function (r) { return r.json(); })
      .then(function (j) {
        if (!j || j.ok === false) {
          updateReplayStatusBadge("error", (j && j.error) || "status error", null);
          return;
        }
        updateReplayStatusBadge(j.status, j.error_summary, j);
        if ((j.status === "pass" || j.status === "fail") && j.replay_run_id && !state.cleanupCalled) {
          state.cleanupCalled = true;
          fetch(
            "/api/etf/offline-replay/cleanup/" + encodeURIComponent(j.replay_run_id),
            { method: "POST", credentials: "same-origin", headers: { Accept: "application/json" } }
          )
            .then(function (r) { return r.json(); })
            .then(function (cj) {
              if (cj && cj.ok) {
                state.replayConsoleText = typeof cj.console_text === "string" ? cj.console_text : "";
                state.replayConsoleReadError = cj && cj.console_read_error ? String(cj.console_read_error) : "";
                syncConsoleLogButton();
              }
            })
            .catch(function () {});
        }
        if (j.status === "pass" || j.status === "fail" || j.status === "timeout" || j.status === "error") {
          stopReplayPoll();
        }
      })
      .catch(function () {
        updateReplayStatusBadge("error", "status poll failed", null);
      });
  }

  function startReplayPoll() {
    stopReplayPoll();
    if (!state.prepared || !state.prepared.status_url) return;
    var interval = Math.max(2000, Number(state.prepared.retry_after_ms) || 3000);
    fetchReplayStatusOnce();
    state.pollTimer = setInterval(fetchReplayStatusOnce, interval);
  }

  function loadTcsMeta() {
    try {
      var raw = localStorage.getItem(LS_TCS);
      var o = raw ? JSON.parse(raw) : null;
      if (!o || typeof o !== "object") return { hosts: [], tags: [] };
      return {
        hosts: Array.isArray(o.hosts) ? o.hosts : [],
        tags: Array.isArray(o.tags) ? o.tags : [],
      };
    } catch (e) {
      return { hosts: [], tags: [] };
    }
  }

  function saveTcsMeta(ips, tags) {
    function dedupe(arr) {
      var seen = {};
      var out = [];
      (arr || []).forEach(function (x) {
        var s = String(x || "").trim();
        if (!s || seen[s]) return;
        seen[s] = true;
        out.push(s);
      });
      return out;
    }
    var m = loadTcsMeta();
    m.hosts = dedupe(m.hosts.concat(ips || []));
    m.tags = dedupe(m.tags.concat(tags || []));
    try {
      localStorage.setItem(LS_TCS, JSON.stringify(m));
    } catch (e) {}
  }

  function refreshHostDatalist() {
    var dl = $("etf-or-host-list");
    if (!dl) return;
    var m = loadTcsMeta();
    dl.innerHTML = "";
    m.hosts.forEach(function (h) {
      var opt = document.createElement("option");
      opt.value = h;
      dl.appendChild(opt);
    });
  }

  function api(path, body) {
    return fetch(path, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "Accept": "application/json" },
      body: JSON.stringify(body || {}),
    }).then(function (r) { return r.json().then(function (j) { return { ok: r.ok, json: j }; }); });
  }

  function searchRuns() {
    var sn = (($("etf-or-sn") && $("etf-or-sn").value) || "").trim().toUpperCase();
    if (!sn) return;
    api("/api/etf/offline-replay/search", { sn: sn }).then(function (res) {
      if (!res.ok || !res.json || !res.json.ok) {
        $("etf-or-list").innerHTML = '<div class="etf-ot-machine-item">Search failed: ' + esc((res.json && res.json.error) || "") + "</div>";
        return;
      }
      renderRuns(res.json.runs_by_station || {});
    }).catch(function (e) {
      $("etf-or-list").innerHTML = '<div class="etf-ot-machine-item">Search failed: ' + esc(e && e.message ? e.message : e) + "</div>";
    });
  }

  function formatPrepareMeta(j) {
    var lines = [];
    lines.push("runnable: " + String(!!j.runnable));
    if (Array.isArray(j.reasons) && j.reasons.length) lines.push("reasons: " + j.reasons.join("; "));
    if (j.resolvedExecutionProfile && j.resolvedExecutionProfile.test_bay_location) {
      lines.push("test_bay_location: " + j.resolvedExecutionProfile.test_bay_location);
    }
    if (j.resolvedSku) lines.push("resolved SKU (from log): " + j.resolvedSku);
    lines.push("— Edit datafile above if needed, then click Prepare & run. —");
    return lines.join("\n");
  }

  function loadPreparePreview() {
    if (!state.selected) return;
    state.prepared = null;
    if ($("etf-or-prepare-run")) $("etf-or-prepare-run").disabled = true;
    var overrides = {
      execution_host: (($("etf-or-host") && $("etf-or-host").value) || "").trim(),
      slot_number: (($("etf-or-slot") && $("etf-or-slot").value) || "").trim(),
      allow_incomplete_or_special: true,
    };
    api("/api/etf/offline-replay/prepare", { selectedRun: state.selected, overrides: overrides }).then(function (res) {
      if (!res.ok || !res.json || !res.json.ok) {
        if ($("etf-or-preview")) $("etf-or-preview").textContent = (res.json && res.json.error) || "Preview failed.";
        return;
      }
      var j = res.json;
      var meta = j.tcsMeta || {};
      saveTcsMeta(meta.test_server_ips || [], meta.machine_tags || []);
      refreshHostDatalist();
      if ($("etf-or-tcs")) {
        var tlines = [];
        if ((meta.test_server_ips || []).length) tlines.push("test_server_ip: " + (meta.test_server_ips || []).join(", "));
        if ((meta.machine_tags || []).length) tlines.push("machine_tag: " + (meta.machine_tags || []).join(", "));
        if (j.resolvedSku) tlines.push("resolved SKU: " + j.resolvedSku);
        $("etf-or-tcs").textContent = tlines.join("\n");
      }
      if ($("etf-or-datafile")) $("etf-or-datafile").value = j.datafilePreview || "";
      if ($("etf-or-datafile-wrap")) $("etf-or-datafile-wrap").hidden = false;
      if ($("etf-or-preview")) $("etf-or-preview").textContent = formatPrepareMeta(j);
      if ($("etf-or-prepare-run")) $("etf-or-prepare-run").disabled = false;
      if (!j.runnable && /cannot be resolved to port/i.test((j.reasons || []).join(";"))) {
        $("etf-or-preview").textContent += "\n\nHint: Fill Slot (e.g. 08) to resolve PORT.";
      }
    }).catch(function (e) {
      if ($("etf-or-preview")) $("etf-or-preview").textContent = "Preview failed: " + (e && e.message ? e.message : e);
    });
  }

  function sendPreparedToTerminal(prepared) {
    var cmd = (prepared && (prepared.wrappedCommand || prepared.commandPreview)) || "";
    if (!prepared || !cmd) return;
    var rowKey = (window.termRowKey || (($("input-sn") && $("input-sn").value) || "").trim().toUpperCase());
    if (typeof window.etfSendSshText !== "function") {
      if ($("etf-or-preview")) $("etf-or-preview").textContent += "\n\nCannot send command: etfSendSshText missing.";
      return;
    }
    var send = window.etfSendSshText(rowKey, cmd + "\n");
    if (!send || !send.ok) {
      if ($("etf-or-preview")) $("etf-or-preview").textContent += "\n\nCannot send command to terminal.";
      return;
    }
    if ("Notification" in window) {
      if (Notification.permission === "granted") {
        new Notification("Raw offline test started", { body: "Command sent to jump host terminal." });
      } else if (Notification.permission === "default") {
        Notification.requestPermission();
      }
    }
    if ($("etf-or-preview")) $("etf-or-preview").textContent += "\n\nCommand sent to jump terminal.";
    if (prepared.status_url) {
      updateReplayStatusBadge("running", "Polling backend for PASS/FAIL…", null);
      state.prepared = prepared;
      startReplayPoll();
    }
    closeModal();
  }

  function prepareAndRun() {
    if (!state.selected) {
      if ($("etf-or-preview")) $("etf-or-preview").textContent = "Select one run first.";
      return;
    }
    stopReplayPoll();
    state.cleanupCalled = false;
    resetReplayConsoleUi();
    if ($("etf-or-replay-status")) $("etf-or-replay-status").textContent = "";
    var ta = $("etf-or-datafile");
    var df = (ta && ta.value) ? ta.value.trim() : "";
    var overrides = {
      execution_host: (($("etf-or-host") && $("etf-or-host").value) || "").trim(),
      slot_number: (($("etf-or-slot") && $("etf-or-slot").value) || "").trim(),
      allow_incomplete_or_special: true,
    };
    if (df) overrides.datafile_text = ta.value;
    api("/api/etf/offline-replay/prepare", { selectedRun: state.selected, overrides: overrides }).then(function (res) {
      if (!res.ok || !res.json || !res.json.ok) {
        if ($("etf-or-preview")) $("etf-or-preview").textContent = (res.json && res.json.error) || "Prepare failed.";
        return;
      }
      var j = res.json;
      var meta = j.tcsMeta || {};
      saveTcsMeta(meta.test_server_ips || [], meta.machine_tags || []);
      refreshHostDatalist();
      if ($("etf-or-tcs")) {
        var tlines = [];
        if ((meta.test_server_ips || []).length) tlines.push("test_server_ip: " + (meta.test_server_ips || []).join(", "));
        if ((meta.machine_tags || []).length) tlines.push("machine_tag: " + (meta.machine_tags || []).join(", "));
        if (j.resolvedSku) tlines.push("resolved SKU: " + j.resolvedSku);
        $("etf-or-tcs").textContent = tlines.join("\n");
      }
      if ($("etf-or-preview")) $("etf-or-preview").textContent = formatPrepareMeta(j);
      if (!j.runnable) {
        if (/cannot be resolved to port/i.test((j.reasons || []).join(";"))) {
          $("etf-or-preview").textContent += "\n\nHint: Fill Slot (e.g. 08) to resolve PORT.";
        }
        return;
      }
      if (!(j.wrappedCommand || j.commandPreview)) {
        $("etf-or-preview").textContent += "\n\nNo command to send.";
        return;
      }
      sendPreparedToTerminal(j);
    }).catch(function (e) {
      if ($("etf-or-preview")) $("etf-or-preview").textContent = "Prepare failed: " + (e && e.message ? e.message : e);
    });
  }

  function openModal() {
    var modal = $("etf-offline-replay-modal");
    if (!modal) return;
    var snTop = $("input-sn");
    var sn = ((snTop && snTop.value) || "").trim();
    if ($("etf-or-sn")) $("etf-or-sn").value = sn;
    if ($("etf-or-list")) $("etf-or-list").innerHTML = "";
    if ($("etf-or-picked")) $("etf-or-picked").textContent = "";
    if ($("etf-or-preview")) $("etf-or-preview").textContent = "";
    if ($("etf-or-datafile")) $("etf-or-datafile").value = "";
    if ($("etf-or-datafile-wrap")) $("etf-or-datafile-wrap").hidden = true;
    if ($("etf-or-prepare-run")) $("etf-or-prepare-run").disabled = true;
    if ($("etf-or-host") && !$("etf-or-host").value) $("etf-or-host").value = "10.16.138.67";
    refreshHostDatalist();
    if ($("etf-or-tcs")) $("etf-or-tcs").textContent = "";
    if ($("etf-or-replay-status")) $("etf-or-replay-status").textContent = "";
    state.selected = null;
    state.prepared = null;
    state.cleanupCalled = false;
    resetReplayConsoleUi();
    modal.setAttribute("aria-hidden", "false");
    var snU = (($("etf-or-sn") && $("etf-or-sn").value) || "").trim().toUpperCase();
    if (snU) searchRuns();
  }

  function closeModal() {
    var modal = $("etf-offline-replay-modal");
    if (modal) modal.setAttribute("aria-hidden", "true");
  }

  function renderRuns(grouped) {
    var list = $("etf-or-list");
    if (!list) return;
    var html = "";
    Object.keys(grouped || {}).sort().forEach(function (station) {
      html += '<div class="etf-ot-machine-item" style="font-weight:700;background:var(--color-surface)">' + esc(station) + "</div>";
      (grouped[station] || []).forEach(function (r) {
        html += '<button type="button" class="etf-ot-machine-item etf-or-run-row" style="width:100%;text-align:left;" ' +
          'data-node="' + esc(r.node_log_id) + '" data-exe="' + esc(r.exe_log_id) + '" data-station="' + esc(r.station) + '" ' +
          'data-procedure="' + esc(r.procedure) + '" data-revision="' + esc(r.revision) + '" data-pn="' + esc(r.pn_name) + '" ' +
          'data-log-time="' + esc(r.log_time) + '" data-sn="' + esc(r.sn) + '" data-machine="' + esc(r.machine) + '" data-result="' + esc(r.result) + '">' +
          esc((r.log_time || "") + " | " + (r.result || "-") + " | " + (r.machine || "-") + " | tp=" + (r.procedure || "-") + " rev=" + (r.revision || "-")) +
          (r.incomplete_or_special ? ' <span class="occ">(incomplete)</span>' : "") +
          "</button>";
      });
    });
    list.innerHTML = html || '<div class="etf-ot-machine-item">No run found</div>';
    list.querySelectorAll(".etf-or-run-row").forEach(function (btn) {
      btn.addEventListener("click", function () {
        list.querySelectorAll(".etf-or-run-row").forEach(function (x) { x.classList.remove("selected"); });
        this.classList.add("selected");
        state.selected = {
          node_log_id: this.getAttribute("data-node") || "",
          exe_log_id: this.getAttribute("data-exe") || "",
          station: this.getAttribute("data-station") || "",
          procedure: this.getAttribute("data-procedure") || "",
          revision: this.getAttribute("data-revision") || "",
          pn_name: this.getAttribute("data-pn") || "",
          log_time: this.getAttribute("data-log-time") || "",
          sn: this.getAttribute("data-sn") || "",
          machine: this.getAttribute("data-machine") || "",
          result: this.getAttribute("data-result") || "",
        };
        $("etf-or-picked").textContent = "Picked node_log_id=" + state.selected.node_log_id + " station=" + state.selected.station;
        loadPreparePreview();
      });
    });
  }

  function bind() {
    var openBtn = $("btn-offline-replay");
    if (openBtn) openBtn.addEventListener("click", openModal);
    var closeBtn = $("etf-or-close");
    if (closeBtn) closeBtn.addEventListener("click", closeModal);
    var searchBtn = $("etf-or-search");
    if (searchBtn) searchBtn.addEventListener("click", searchRuns);
    var prBtn = $("etf-or-prepare-run");
    if (prBtn) prBtn.addEventListener("click", prepareAndRun);
    var slotEl = $("etf-or-slot");
    if (slotEl) {
      slotEl.addEventListener("change", function () {
        var modal = $("etf-offline-replay-modal");
        if (!modal || modal.getAttribute("aria-hidden") === "true") return;
        if (state.selected) loadPreparePreview();
      });
    }
    var vbtn = $("etf-or-view-console");
    if (vbtn) {
      vbtn.addEventListener("click", function () {
        var pre = $("etf-or-console-view");
        if (!pre) return;
        var willShow = !!pre.hidden;
        if (willShow) {
          var body = state.replayConsoleText !== null ? state.replayConsoleText : "";
          if (state.replayConsoleText === null) {
            pre.textContent = "No console snapshot yet.";
          } else if (body === "" && !state.replayConsoleReadError) {
            pre.textContent = "(Console snapshot empty.)";
          } else {
            pre.textContent = body + (state.replayConsoleReadError ? "\n\n[Read note: " + state.replayConsoleReadError + "]" : "");
          }
        }
        pre.hidden = !willShow;
      });
    }
  }

  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "visible" && state.pollTimer && state.prepared && state.prepared.status_url) {
      fetchReplayStatusOnce();
    }
  });

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", bind);
  else bind();
})();

