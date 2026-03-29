/**
 * Shared helpers for ETF-style SN terminals (Testing page, FA Debug tray).
 * Requires fa_debug.js (etfCreateSnTerminals, etfDestroySnTerminal, etfFitTerminals, etfGetSnPanel).
 */
(function () {
  function pickBestEtfRow(rows, sn) {
    const q = (sn || "").trim().toLowerCase();
    if (!q || !rows || !rows.length) return null;
    for (let i = 0; i < rows.length; i++) {
      const r = rows[i];
      if (String(r.sn || "").trim().toLowerCase() === q) return r;
    }
    return rows[0];
  }

  function openFourTerminals(sn, rowKey, row, els) {
    if (typeof window.etfCreateSnTerminals !== "function") return;
    window.etfCreateSnTerminals(sn || rowKey, rowKey, null, {
      aiEl: els.ai || null,
      sshEl: els.ssh || null,
      bmcEl: els.bmc || null,
      hostEl: els.host || null,
      row: row || {},
    });
    [0, 120, 400, 900, 2000].forEach(function (ms) {
      setTimeout(function () {
        if (typeof window.etfFitTerminals === "function") window.etfFitTerminals(rowKey);
      }, ms);
    });
  }

  /**
   * Poll SSH/BMC/Host panels and recreate a terminal when its WebSocket has closed (e.g. network blip).
   * AI session is left to user (Start Session) — not auto-reconnected.
   */
  function watchClosedSshAndReconnect(rowKey, sn, row, els, opts) {
    const intervalMs = (opts && opts.intervalMs) || 2000;
    const types = [
      { key: "ssh", el: els.ssh, t: "term" },
      { key: "bmc", el: els.bmc, t: "bmc" },
      { key: "host", el: els.host, t: "host" },
    ];
    let timer = null;
    function tick() {
      if (typeof window.etfGetSnPanel !== "function" || typeof window.etfDestroySnTerminal !== "function") return;
      const panel = window.etfGetSnPanel(rowKey);
      if (!panel) return;
      types.forEach(({ key, el, t }) => {
        if (!el) return;
        const slot = panel[key];
        const ws = slot && slot.ws;
        if (!slot || !ws) return;
        if (ws.readyState !== WebSocket.CLOSED) return;
        if (slot._testingReconnecting) return;
        slot._testingReconnecting = true;
        try {
          window.etfDestroySnTerminal(rowKey, t === "term" ? "ssh" : t);
        } catch (_) {}
        setTimeout(() => {
          slot._testingReconnecting = false;
          if (typeof window.etfCreateSnTerminals === "function") {
            const one = {};
            if (t === "term") one.sshEl = el;
            else if (t === "bmc") one.bmcEl = el;
            else if (t === "host") one.hostEl = el;
            one.row = row || {};
            window.etfCreateSnTerminals(sn || rowKey, rowKey, null, one);
            setTimeout(() => {
              if (typeof window.etfFitTerminals === "function") window.etfFitTerminals(rowKey);
            }, 150);
          }
        }, 400);
      });
    }
    timer = setInterval(tick, intervalMs);
    return function stop() {
      if (timer) clearInterval(timer);
      timer = null;
    };
  }

  window.etfTerminalHelpers = {
    pickBestEtfRow: pickBestEtfRow,
    openFourTerminals: openFourTerminals,
    watchClosedSshAndReconnect: watchClosedSshAndReconnect,
  };
})();
