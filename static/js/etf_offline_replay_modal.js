/* Raw offline replay modal for Testing page. */
(function () {
  function $(id) { return document.getElementById(id); }
  function esc(s) {
    var d = document.createElement("div");
    d.textContent = String(s == null ? "" : s);
    return d.innerHTML;
  }

  var state = { selected: null, prepared: null };
  var LS_TCS = "etfOfflineReplayTcsMeta";

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

  function openModal() {
    var modal = $("etf-offline-replay-modal");
    if (!modal) return;
    var snTop = $("input-sn");
    var sn = ((snTop && snTop.value) || "").trim();
    if ($("etf-or-sn")) $("etf-or-sn").value = sn;
    if ($("etf-or-list")) $("etf-or-list").innerHTML = "";
    if ($("etf-or-picked")) $("etf-or-picked").textContent = "";
    if ($("etf-or-preview")) $("etf-or-preview").textContent = "";
    if ($("etf-or-run")) $("etf-or-run").disabled = true;
    if ($("etf-or-host") && !$("etf-or-host").value) $("etf-or-host").value = "10.16.138.67";
    refreshHostDatalist();
    if ($("etf-or-tcs")) $("etf-or-tcs").textContent = "";
    state.selected = null;
    state.prepared = null;
    modal.setAttribute("aria-hidden", "false");
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
        var disabled = r.incomplete_or_special ? "opacity:0.6;" : "";
        html += '<button type="button" class="etf-ot-machine-item etf-or-run-row" style="width:100%;text-align:left;' + disabled + '" ' +
          'data-node="' + esc(r.node_log_id) + '" data-exe="' + esc(r.exe_log_id) + '" data-station="' + esc(r.station) + '" ' +
          'data-procedure="' + esc(r.procedure) + '" data-revision="' + esc(r.revision) + '" data-pn="' + esc(r.pn_name) + '" ' +
          'data-log-time="' + esc(r.log_time) + '" data-sn="' + esc(r.sn) + '" data-machine="' + esc(r.machine) + '" data-result="' + esc(r.result) + '">' +
          esc((r.log_time || "") + " | " + (r.result || "-") + " | " + (r.machine || "-") + " | tp=" + (r.procedure || "-") + " rev=" + (r.revision || "-")) +
          (r.incomplete_or_special ? ' <span class="occ">(blocked)</span>' : "") +
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
      });
    });
  }

  function prepareReplay() {
    if (!state.selected) { $("etf-or-preview").textContent = "Select one run first."; return; }
    var overrides = {
      execution_host: (($("etf-or-host") && $("etf-or-host").value) || "").trim(),
      slot_number: (($("etf-or-slot") && $("etf-or-slot").value) || "").trim(),
      allow_incomplete_or_special: !!($("etf-or-allow-incomplete") && $("etf-or-allow-incomplete").checked),
      sku: (($("etf-or-sku") && $("etf-or-sku").value) || "").trim(),
    };
    api("/api/etf/offline-replay/prepare", { selectedRun: state.selected, overrides: overrides }).then(function (res) {
      if (!res.ok || !res.json || !res.json.ok) {
        $("etf-or-preview").textContent = (res.json && res.json.error) || "Prepare failed.";
        return;
      }
      state.prepared = res.json;
      var meta = res.json.tcsMeta || {};
      var ips = meta.test_server_ips || [];
      var tags = meta.machine_tags || [];
      saveTcsMeta(ips, tags);
      refreshHostDatalist();
      if ($("etf-or-tcs")) {
        var tlines = [];
        if (ips.length) tlines.push("test_server_ip: " + ips.join(", "));
        if (tags.length) tlines.push("machine_tag: " + tags.join(", "));
        if (res.json.resolvedSku) tlines.push("resolved SKU: " + res.json.resolvedSku);
        $("etf-or-tcs").textContent = tlines.join("\n");
      }
      var lines = [];
      lines.push("runnable: " + String(!!res.json.runnable));
      if (Array.isArray(res.json.reasons) && res.json.reasons.length) lines.push("reasons: " + res.json.reasons.join("; "));
      if (res.json.resolvedExecutionProfile && res.json.resolvedExecutionProfile.test_bay_location) {
        lines.push("test_bay_location: " + res.json.resolvedExecutionProfile.test_bay_location);
      }
      if (res.json.commandPreview) lines.push("command: " + res.json.commandPreview);
      if (res.json.datafilePreview) lines.push("datafile:\n" + res.json.datafilePreview);
      $("etf-or-preview").textContent = lines.join("\n\n");
      $("etf-or-run").disabled = !(res.json.runnable && res.json.commandPreview);
      if (!res.json.runnable && /cannot be resolved to port/i.test((res.json.reasons || []).join(";"))) {
        $("etf-or-preview").textContent += "\n\nHint: Fill Slot (e.g. 08) to resolve PORT.";
      }
    }).catch(function (e) {
      $("etf-or-preview").textContent = "Prepare failed: " + (e && e.message ? e.message : e);
    });
  }

  function runOnTerminal() {
    if (!state.prepared || !state.prepared.commandPreview) return;
    var rowKey = (window.termRowKey || (($("input-sn") && $("input-sn").value) || "").trim().toUpperCase());
    if (typeof window.etfSendSshText !== "function") {
      $("etf-or-preview").textContent += "\n\nCannot send command: etfSendSshText missing.";
      return;
    }
    var send = window.etfSendSshText(rowKey, state.prepared.commandPreview + "\n");
    if (!send || !send.ok) {
      $("etf-or-preview").textContent += "\n\nCannot send command to terminal.";
      return;
    }
    if ("Notification" in window) {
      if (Notification.permission === "granted") {
        new Notification("Raw offline test started", { body: "Command sent to jump host terminal." });
      } else if (Notification.permission === "default") {
        Notification.requestPermission();
      }
    }
    $("etf-or-preview").textContent += "\n\nCommand sent to jump terminal.";
  }

  function bind() {
    var openBtn = $("btn-offline-replay");
    if (openBtn) openBtn.addEventListener("click", openModal);
    var closeBtn = $("etf-or-close");
    if (closeBtn) closeBtn.addEventListener("click", closeModal);
    var searchBtn = $("etf-or-search");
    if (searchBtn) {
      searchBtn.addEventListener("click", function () {
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
      });
    }
    var prepareBtn = $("etf-or-prepare");
    if (prepareBtn) prepareBtn.addEventListener("click", prepareReplay);
    var runBtn = $("etf-or-run");
    if (runBtn) runBtn.addEventListener("click", runOnTerminal);
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", bind);
  else bind();
})();

