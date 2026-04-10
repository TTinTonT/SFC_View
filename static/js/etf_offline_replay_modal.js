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
  var STATION_CHOICES = ["FLA", "FLB", "AST", "FTS", "FCT", "NVL", "RIN"];
  /** Default execution host (replay + ô IP); FA mặc định khi tray không có ssh_host. */
  var DEFAULT_EXEC_HOST = "10.16.138.67";

  /** ssh_host từ ETF row — IP/hostname jump mà WebSocket Terminal (jump host) dùng. */
  function looksLikeTraySshHost(s) {
    var t = String(s == null ? "" : s).trim();
    if (!t || /^N\/A$/i.test(t) || /^NA$/i.test(t) || t === "-") return false;
    return true;
  }

  function setTrayHostHint(mode, detail) {
    var el = $("etf-or-tray-hint");
    if (!el) return;
    if (mode === "ok" && detail) {
      el.textContent =
        "Tray: dùng ssh_host (cùng đích với Terminal jump host trên trang Testing) — " + detail;
    } else if (mode === "missing") {
      el.textContent =
        "Không tìm thấy ssh_host (jump) trong cache tray cho SN này — dùng mặc định " +
        DEFAULT_EXEC_HOST +
        " (FA). Sửa ô IP để đổi jump; terminal jump được tạo lại.";
    } else {
      el.textContent = "";
    }
  }

  /** Điền ô IP = ssh_host từ overview (giống ?host= khi mở jump); không có thì default FA. */
  function applyExecutionHostFromTrayOverview(sn, done) {
    sn = String(sn || "").trim();
    if (!sn) {
      if ($("etf-or-host")) $("etf-or-host").value = DEFAULT_EXEC_HOST;
      setTrayHostHint("missing");
      if (done) done();
      return;
    }
    fetch("/api/debug/testing/overview?sn=" + encodeURIComponent(sn), {
      credentials: "same-origin",
      headers: { Accept: "application/json" },
    })
      .then(function (r) {
        return r.json();
      })
      .then(function (ov) {
        var row = ov && ov.tray && ov.tray.row;
        var sshH = row && row.ssh_host;
        if (ov && ov.tray && ov.tray.connected && looksLikeTraySshHost(sshH)) {
          var v = String(sshH).trim();
          if ($("etf-or-host")) $("etf-or-host").value = v;
          setTrayHostHint("ok", v);
          reconnectJumpTerminalForExecHost();
        } else {
          if ($("etf-or-host")) $("etf-or-host").value = DEFAULT_EXEC_HOST;
          setTrayHostHint("missing");
          reconnectJumpTerminalForExecHost();
        }
        if (done) done();
      })
      .catch(function () {
        if ($("etf-or-host")) $("etf-or-host").value = DEFAULT_EXEC_HOST;
        setTrayHostHint("missing");
        reconnectJumpTerminalForExecHost();
        if (done) done();
      });
  }

  /** Tạo lại WebSocket Terminal (jump host) tới IP trong ô — thay session jump cũ. */
  function reconnectJumpTerminalForExecHost() {
    var host = ($("etf-or-host") && $("etf-or-host").value) || "";
    host = String(host).trim();
    if (!host) return;
    var rowKey = window.termRowKey;
    var sshEl = $("term-ssh");
    var sn = (($("input-sn") && $("input-sn").value) || "").trim() || rowKey;
    if (!rowKey || !sshEl) return;
    if (typeof window.etfReconnectJumpSshOnly === "function") {
      window.etfReconnectJumpSshOnly(rowKey, sn, host, sshEl);
    } else if (typeof window.etfCreateSnTerminals === "function") {
      window.etfCreateSnTerminals(sn || rowKey, rowKey, null, {
        sshEl: sshEl,
        row: { ssh_host: host },
      });
      if (typeof window.etfFitTerminals === "function") {
        setTimeout(function () {
          try {
            window.etfFitTerminals(rowKey);
          } catch (e) {}
        }, 150);
      }
    }
  }

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
      if (!o || typeof o !== "object") return { hosts: [], tags: [], bays: [], bayHostPairs: [] };
      return {
        hosts: Array.isArray(o.hosts) ? o.hosts : [],
        tags: Array.isArray(o.tags) ? o.tags : [],
        bays: Array.isArray(o.bays) ? o.bays : [],
        bayHostPairs: Array.isArray(o.bayHostPairs) ? o.bayHostPairs : [],
      };
    } catch (e) {
      return { hosts: [], tags: [], bays: [], bayHostPairs: [] };
    }
  }

  function saveTcsMeta(ips, tags, bays) {
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
    m.bays = dedupe(m.bays.concat(bays || []));
    try {
      localStorage.setItem(LS_TCS, JSON.stringify(m));
    } catch (e) {}
  }

  function saveBayHostPair(bay, host) {
    var b = String(bay || "").trim().toUpperCase();
    var h = String(host || "").trim();
    if (!b || !h) return;
    var m = loadTcsMeta();
    var pairs = Array.isArray(m.bayHostPairs) ? m.bayHostPairs.slice() : [];
    var found = false;
    pairs = pairs.map(function (p) {
      if (p && String(p.bay || "").toUpperCase() === b) {
        found = true;
        return { bay: b, host: h };
      }
      return p;
    });
    if (!found) pairs.push({ bay: b, host: h });
    m.bayHostPairs = pairs.slice(-100);
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

  function refreshBayDatalist() {
    var dl = $("etf-or-bay-list");
    if (!dl) return;
    var m = loadTcsMeta();
    dl.innerHTML = "";
    (m.bays || []).forEach(function (b) {
      var opt = document.createElement("option");
      opt.value = b;
      dl.appendChild(opt);
    });
  }

  function parseBayLocation(s) {
    var t = String(s || "").trim().toUpperCase().replace(/-/g, "_");
    var m = t.match(/(MTF|FA)_([A-Z]{3})_(\d{1,4})/);
    if (!m) return null;
    return { prefix: m[1], station: m[2], slot: m[3], full: m[0] };
  }

  function deriveBayFromMachineName(machineName) {
    var s = String(machineName || "").trim().toUpperCase().replace(/-/g, "_");
    var m = s.match(/(?:^|_)(MTF|FA)_([A-Z]{3})_(\d{1,4})(?:$|_)/);
    if (!m) return null;
    return { prefix: m[1], station: m[2], slot: m[3], full: m[1] + "_" + m[2] + "_" + m[3] };
  }

  function syncBayInputFromParts() {
    var p = (($("etf-or-bay-prefix") && $("etf-or-bay-prefix").value) || "FA").toUpperCase();
    var st = (($("etf-or-bay-station") && $("etf-or-bay-station").value) || "").toUpperCase();
    var slot = (($("etf-or-bay-slot") && $("etf-or-bay-slot").value) || "").trim();
    if (!slot || !st) return;
    var t = p + "_" + st + "_" + slot;
    if ($("etf-or-test-bay")) $("etf-or-test-bay").value = t;
  }

  function syncBayPartsFromInput() {
    var p = parseBayLocation(($("etf-or-test-bay") && $("etf-or-test-bay").value) || "");
    if (!p) return;
    if ($("etf-or-bay-prefix")) $("etf-or-bay-prefix").value = p.prefix;
    if ($("etf-or-bay-station")) {
      if (STATION_CHOICES.indexOf(p.station) >= 0) $("etf-or-bay-station").value = p.station;
    }
    if ($("etf-or-bay-slot")) $("etf-or-bay-slot").value = p.slot;
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
      execution_host: (($("etf-or-host") && $("etf-or-host").value) || "").trim() || DEFAULT_EXEC_HOST,
      slot_number: (($("etf-or-bay-slot") && $("etf-or-bay-slot").value) || "").trim(),
      test_bay_location: (($("etf-or-test-bay") && $("etf-or-test-bay").value) || "").trim(),
      allow_incomplete_or_special: true,
    };
    api("/api/etf/offline-replay/prepare", { selectedRun: state.selected, overrides: overrides }).then(function (res) {
      if (!res.ok || !res.json || !res.json.ok) {
        if ($("etf-or-preview")) $("etf-or-preview").textContent = (res.json && res.json.error) || "Preview failed.";
        return;
      }
      var j = res.json;
      var meta = j.tcsMeta || {};
      var machineName = (meta.uut_machine_name || (state.selected && state.selected.machine) || "").trim();
      var bayGuess = deriveBayFromMachineName(machineName);
      if (!bayGuess && j.resolvedExecutionProfile && j.resolvedExecutionProfile.test_bay_location) {
        bayGuess = parseBayLocation(j.resolvedExecutionProfile.test_bay_location);
      }
      if (bayGuess) {
        if ($("etf-or-bay-prefix")) $("etf-or-bay-prefix").value = bayGuess.prefix;
        if ($("etf-or-bay-station") && STATION_CHOICES.indexOf(bayGuess.station) >= 0) $("etf-or-bay-station").value = bayGuess.station;
        if ($("etf-or-bay-slot")) $("etf-or-bay-slot").value = bayGuess.slot;
        if ($("etf-or-test-bay")) $("etf-or-test-bay").value = bayGuess.full;
      } else {
        var stFromSelected = (((state.selected && state.selected.station) || "").toUpperCase().replace("SYSTEM_", ""));
        if ($("etf-or-bay-station") && STATION_CHOICES.indexOf(stFromSelected) >= 0) $("etf-or-bay-station").value = stFromSelected;
        syncBayInputFromParts();
      }
      var finalBay = (($("etf-or-test-bay") && $("etf-or-test-bay").value) || (bayGuess && bayGuess.full) || (overrides.test_bay_location || "")).trim();
      var execHostUi = (($("etf-or-host") && $("etf-or-host").value) || "").trim() || DEFAULT_EXEC_HOST;
      saveTcsMeta([execHostUi], meta.machine_tags || [], [finalBay]);
      if (finalBay && execHostUi) saveBayHostPair(finalBay, execHostUi);
      refreshHostDatalist();
      refreshBayDatalist();
      if ($("etf-or-tcs")) {
        var tlines = [];
        if ((meta.test_server_ips || []).length) {
          tlines.push("log test_server_ip (reference only): " + (meta.test_server_ips || []).join(", "));
        }
        if ((meta.machine_tags || []).length) tlines.push("machine_tag: " + (meta.machine_tags || []).join(", "));
        if (machineName) tlines.push("uut_machine_name: " + machineName);
        if (($("etf-or-test-bay") && $("etf-or-test-bay").value)) tlines.push("test_bay_location(ui): " + $("etf-or-test-bay").value);
        if (j.resolvedSku) tlines.push("resolved SKU: " + j.resolvedSku);
        $("etf-or-tcs").textContent = tlines.join("\n");
      }
      if ($("etf-or-datafile")) $("etf-or-datafile").value = j.datafilePreview || "";
      if ($("etf-or-datafile-wrap")) $("etf-or-datafile-wrap").hidden = false;
      if ($("etf-or-preview")) $("etf-or-preview").textContent = formatPrepareMeta(j);
      if ($("etf-or-prepare-run")) $("etf-or-prepare-run").disabled = false;
      if (!j.runnable && /cannot be resolved to port/i.test((j.reasons || []).join(";"))) {
        $("etf-or-preview").textContent += "\n\nHint: adjust TEST_BAY_LOCATION or slot to resolve PORT.";
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

    function onFullSuccess(previewNote, notifBody) {
      if ("Notification" in window) {
        if (Notification.permission === "granted") {
          new Notification("Raw offline test started", { body: notifBody || "Command sent to terminal." });
        } else if (Notification.permission === "default") {
          Notification.requestPermission();
        }
      }
      if ($("etf-or-preview")) $("etf-or-preview").textContent += "\n\n" + previewNote;
      if (prepared.status_url) {
        updateReplayStatusBadge("running", "Polling backend for PASS/FAIL…", null);
        state.prepared = prepared;
        startReplayPoll();
      }
      closeModal();
    }

    var host = (($("etf-or-host") && $("etf-or-host").value) || "").trim() || DEFAULT_EXEC_HOST;
    /** Password for nested `ssh root@host` from jump (site default root/root). */
    var SSH_NESTED_ROOT_PASSWORD = "root";
    var passDelayMs = 800;
    var replayAfterPassMs = 2200;

    var sshOpts = "-o StrictHostKeyChecking=accept-new -o ConnectTimeout=15";
    var sshLine = "ssh " + sshOpts + " root@" + host + "\n";
    var r1 = window.etfSendSshText(rowKey, sshLine);
    if (!r1 || !r1.ok) {
      if ($("etf-or-preview")) $("etf-or-preview").textContent += "\n\nCannot send SSH line to terminal.";
      return;
    }
    if ($("etf-or-preview")) {
      $("etf-or-preview").textContent +=
        "\n\nSSH to root@" + host + " sent; will send password then replay…";
    }

    setTimeout(function () {
      var rp = window.etfSendSshText(rowKey, SSH_NESTED_ROOT_PASSWORD + "\n");
      if (!rp || !rp.ok) {
        if ($("etf-or-preview")) $("etf-or-preview").textContent += "\n\nFailed to send SSH password to terminal.";
        return;
      }
      setTimeout(function () {
        var r2 = window.etfSendSshText(rowKey, cmd + "\n");
        if (!r2 || !r2.ok) {
          if ($("etf-or-preview")) $("etf-or-preview").textContent += "\n\nFailed to send replay command (SSH panel closed?).";
          return;
        }
        onFullSuccess(
          "SSH to " + host + " (password sent) then replay command sent.",
          "Replay command sent on root@" + host + "."
        );
      }, replayAfterPassMs);
    }, passDelayMs);
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
      execution_host: (($("etf-or-host") && $("etf-or-host").value) || "").trim() || DEFAULT_EXEC_HOST,
      slot_number: (($("etf-or-bay-slot") && $("etf-or-bay-slot").value) || "").trim(),
      test_bay_location: (($("etf-or-test-bay") && $("etf-or-test-bay").value) || "").trim(),
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
      var execHostRun = (($("etf-or-host") && $("etf-or-host").value) || "").trim() || DEFAULT_EXEC_HOST;
      saveTcsMeta([execHostRun], meta.machine_tags || [], [overrides.test_bay_location || ""]);
      if (overrides.test_bay_location && execHostRun) saveBayHostPair(overrides.test_bay_location, execHostRun);
      refreshHostDatalist();
      refreshBayDatalist();
      if ($("etf-or-tcs")) {
        var tlines = [];
        if ((meta.test_server_ips || []).length) {
          tlines.push("log test_server_ip (reference only): " + (meta.test_server_ips || []).join(", "));
        }
        if ((meta.machine_tags || []).length) tlines.push("machine_tag: " + (meta.machine_tags || []).join(", "));
        if (meta.uut_machine_name) tlines.push("uut_machine_name: " + meta.uut_machine_name);
        if (overrides.test_bay_location) tlines.push("test_bay_location(ui): " + overrides.test_bay_location);
        if (j.resolvedSku) tlines.push("resolved SKU: " + j.resolvedSku);
        $("etf-or-tcs").textContent = tlines.join("\n");
      }
      if ($("etf-or-preview")) $("etf-or-preview").textContent = formatPrepareMeta(j);
      if (!j.runnable) {
        if (/cannot be resolved to port/i.test((j.reasons || []).join(";"))) {
          $("etf-or-preview").textContent += "\n\nHint: adjust TEST_BAY_LOCATION or slot to resolve PORT.";
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
    if ($("etf-or-host")) $("etf-or-host").value = DEFAULT_EXEC_HOST;
    if ($("etf-or-tray-hint")) $("etf-or-tray-hint").textContent = "";
    if ($("etf-or-bay-prefix") && !$("etf-or-bay-prefix").value) $("etf-or-bay-prefix").value = "FA";
    if ($("etf-or-bay-station") && !$("etf-or-bay-station").value) $("etf-or-bay-station").value = "FLA";
    refreshHostDatalist();
    refreshBayDatalist();
    if ($("etf-or-tcs")) $("etf-or-tcs").textContent = "";
    if ($("etf-or-replay-status")) $("etf-or-replay-status").textContent = "";
    state.selected = null;
    state.prepared = null;
    state.cleanupCalled = false;
    resetReplayConsoleUi();
    syncBayInputFromParts();
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
        var bayFast = deriveBayFromMachineName(state.selected.machine || "");
        if (bayFast) {
          if ($("etf-or-bay-prefix")) $("etf-or-bay-prefix").value = bayFast.prefix;
          if ($("etf-or-bay-station") && STATION_CHOICES.indexOf(bayFast.station) >= 0) $("etf-or-bay-station").value = bayFast.station;
          if ($("etf-or-bay-slot")) $("etf-or-bay-slot").value = bayFast.slot;
          if ($("etf-or-test-bay")) $("etf-or-test-bay").value = bayFast.full;
        }
        applyExecutionHostFromTrayOverview(state.selected.sn, function () {
          loadPreparePreview();
        });
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
    var hostInp = $("etf-or-host");
    if (hostInp) {
      hostInp.addEventListener("change", function () {
        reconnectJumpTerminalForExecHost();
      });
    }
    ["etf-or-bay-prefix", "etf-or-bay-station", "etf-or-bay-slot"].forEach(function (id) {
      var el = $(id);
      if (!el) return;
      el.addEventListener("change", function () {
        syncBayInputFromParts();
        var modal = $("etf-offline-replay-modal");
        if (!modal || modal.getAttribute("aria-hidden") === "true") return;
        if (state.selected) loadPreparePreview();
      });
    });
    var bayInput = $("etf-or-test-bay");
    if (bayInput) {
      bayInput.addEventListener("change", function () {
        syncBayPartsFromInput();
        var v = (bayInput.value || "").trim();
        if (v) saveTcsMeta([], [], [v]);
        refreshBayDatalist();
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

