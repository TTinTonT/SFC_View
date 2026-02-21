/**
 * FA Debug Place - KPI, timeline, drill-down, pin, xterm, theme.
 */
(function () {
  let rows = [];
  let summary = { total: 0, pass: 0, fail: 0 };
  let timelineFilterQuery = "";
  let timelineNextUpdateSec = 60;
  let timelineCountdownInterval = null;
  const POLL_MS = 60000;

  const $ = (id) => document.getElementById(id);
  const el = (tag, attrs, children) => {
    const e = document.createElement(tag);
    if (attrs) Object.assign(e, attrs);
    if (attrs && attrs.className) e.className = attrs.className;
    if (attrs && attrs.style) e.style.cssText = attrs.style;
    if (attrs && attrs.title) e.title = attrs.title;
    if (children) children.forEach(c => e.appendChild(typeof c === 'string' ? document.createTextNode(c) : c));
    return e;
  };

  function setDefaultDates() {
    const end = new Date();
    const start = new Date();
    start.setHours(start.getHours() - 24);
    const fmt = (d) => {
      const y = d.getFullYear();
      const m = String(d.getMonth() + 1).padStart(2, '0');
      const day = String(d.getDate()).padStart(2, '0');
      const h = String(d.getHours()).padStart(2, '0');
      const min = String(d.getMinutes()).padStart(2, '0');
      return `${y}-${m}-${day}T${h}:${min}`;
    };
    const startEl = $('date-start');
    const endEl = $('date-end');
    if (startEl) startEl.value = fmt(start);
    if (endEl) endEl.value = fmt(end);
  }

  function fmtDateTimeLocal(d) {
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    const h = String(d.getHours()).padStart(2, '0');
    const min = String(d.getMinutes()).padStart(2, '0');
    return `${y}-${m}-${day}T${h}:${min}`;
  }

  function fetchData(useCustomRange = false) {
    const startEl = $('date-start');
    const endEl = $('date-end');
    const endNowEl = $('end-now');
    const endTimeIsNow = endNowEl?.checked ?? false;
    let url = '/api/debug-data';
    let body = null;
    if (useCustomRange && startEl?.value) {
      const endVal = endTimeIsNow ? fmtDateTimeLocal(new Date()) : (endEl?.value || '');
      if (endVal) {
        url = '/api/debug-query';
        body = JSON.stringify({
          start_datetime: startEl.value.replace('T', ' '),
          end_datetime: endVal.replace('T', ' '),
        });
      } else {
        url = '/api/debug-query';
        body = '{}';
      }
    } else if (useCustomRange) {
      url = '/api/debug-query';
      body = '{}';
    }
    fetch(url, {
      method: body ? 'POST' : 'GET',
      headers: body ? { 'Content-Type': 'application/json' } : {},
      body: body,
    })
      .then((r) => r.json())
      .then((data) => {
        if (data.error) {
          console.error(data.error);
          return;
        }
        summary = data.summary || { total: 0, pass: 0, fail: 0 };
        rows = data.rows || [];
        checkPinnedUpdates(rows);
        render();
        timelineNextUpdateSec = POLL_MS / 1000;
        if (timelineCountdownInterval) clearInterval(timelineCountdownInterval);
        const nextEl = $('timeline-next-update');
        if (nextEl) nextEl.textContent = timelineNextUpdateSec + "s";
        timelineCountdownInterval = setInterval(() => {
          timelineNextUpdateSec--;
          if (timelineNextUpdateSec <= 0) timelineNextUpdateSec = POLL_MS / 1000;
          if (nextEl) nextEl.textContent = timelineNextUpdateSec + "s";
        }, 1000);
        const banner = document.getElementById('server-offline-banner');
        if (banner) banner.classList.remove('show');
      })
      .catch((err) => {
        console.error(err);
        const banner = document.getElementById('server-offline-banner');
        if (banner) banner.classList.add('show');
      });
  }

  function render() {
    $('kpi-fail-val').textContent = summary.fail ?? 0;
    $('kpi-pass-val').textContent = summary.pass ?? 0;
    $('kpi-total-val').textContent = summary.total ?? 0;

    const body = $('timeline-body');
    body.innerHTML = '';
    const q = (timelineFilterQuery || "").trim().toLowerCase();
    const displayRows = q
      ? rows.filter((r) => {
          const sn = (r.serial_number || "").toLowerCase();
          const pn = (r.part_number || "").toLowerCase();
          const st = (r.station || "").toLowerCase();
          const ec = (r.error_code || "").toLowerCase();
          const fm = (r.failure_msg || "").toLowerCase();
          return sn.includes(q) || pn.includes(q) || st.includes(q) || ec.includes(q) || fm.includes(q);
        })
      : rows;
    displayRows.forEach((r) => {
      const result = (r.result || '').toUpperCase();
      const isPass = result === 'PASS';
      const row = el('div', {
        className: 'timeline-row ' + (isPass ? 'pass' : 'fail'),
      });
      const bpNa = r.is_bonepile ? 'BP' : 'NA';
      const errTitle = r.failure_msg ? `title="${(r.failure_msg || '').replace(/"/g, '&quot;')}"` : '';
      const logPathCell = makeLogPathCell(r.serial_number);
      row.innerHTML = [
        `<span>${result || '-'}</span>`,
        `<span><button type="button" class="pin-btn" data-sn="${escapeAttr(r.serial_number)}" title="Pin">📌</button> ${escapeHtml(r.serial_number || '')}</span>`,
        `<span>${escapeHtml(r.part_number || '')}</span>`,
        `<span>${bpNa}</span>`,
        `<span>${escapeHtml(r.test_time || '')}</span>`,
        `<span ${errTitle}>${escapeHtml(r.station || '')} ${r.error_code ? `(${escapeHtml(r.error_code)})` : ''}</span>`,
        `<span class="log-path-cell">${logPathCell}</span>`,
      ].join('');
      body.appendChild(row);

      const pinBtn = row.querySelector('.pin-btn');
      if (pinBtn) pinBtn.addEventListener('click', (e) => { e.stopPropagation(); togglePin(r.serial_number, r); });
      const logPathBtn = row.querySelector('.log-path-btn');
      if (logPathBtn) logPathBtn.addEventListener('click', (e) => { e.stopPropagation(); fetchAndShowLogPath(logPathBtn, r.serial_number); });
      row.addEventListener('click', (e) => { if (!e.target.closest('.pin-btn') && !e.target.closest('.log-path-btn')) openDrillDown(r); });
    });
  }

  function makeLogPathCell(sn) {
    if (!sn) return '-';
    return '<button type="button" class="log-path-btn" data-sn="' + escapeAttr(sn) + '" title="Get log path from Crabber">Get log</button>';
  }
  function fetchAndShowLogPath(btnOrCell, sn) {
    const cell = btnOrCell && btnOrCell.classList && btnOrCell.classList.contains('log-path-btn') ? btnOrCell.closest('.log-path-cell') || btnOrCell.parentElement : btnOrCell;
    if (!cell || !sn) return;
    cell.innerHTML = '<span class="text-muted">...</span>';
    fetch('/api/debug/log-path?sn=' + encodeURIComponent(sn))
      .then((r) => r.json())
      .then((data) => {
        if (data.ok && data.path) {
          const path = data.path;
          const isUrl = /^https?:\/\//i.test(path);
          if (isUrl) {
            cell.innerHTML = '<a href="' + escapeAttr(path) + '" target="_blank" rel="noopener">Open log</a>';
          } else {
            cell.innerHTML = '<span title="' + escapeAttr(path) + '">' + escapeHtml(path.length > 30 ? path.slice(0, 30) + '...' : path) + '</span>';
          }
        } else {
          cell.innerHTML = '<span class="text-muted">N/A</span>';
        }
      })
      .catch(() => { cell.innerHTML = '<span class="text-muted">Error</span>'; });
  }

  function escapeHtml(s) {
    if (s == null) return '';
    const d = document.createElement('div');
    d.textContent = s;
    return d.innerHTML;
  }
  function escapeAttr(s) {
    return escapeHtml(s).replace(/'/g, '&#39;');
  }

  function getRowsForDrillDown(source) {
    if (source.filter) {
      if (source.filter === 'fail') return rows.filter((r) => (r.result || '').toUpperCase() === 'FAIL');
      if (source.filter === 'pass') return rows.filter((r) => (r.result || '').toUpperCase() === 'PASS');
      return rows;
    }
    const sn = source.serial_number || '';
    return rows.filter((r) => (r.serial_number || '') === sn);
  }

  function groupBySn(rowsToGroup) {
    const bySn = {};
    rowsToGroup.forEach((r) => {
      const s = (r.serial_number || '').trim();
      if (!s) return;
      if (!bySn[s]) bySn[s] = [];
      bySn[s].push(r);
    });
    return Object.entries(bySn).map(([sn, list]) => {
      const sorted = list.slice().sort((a, b) => {
        const ta = a.test_time_dt ? new Date(a.test_time_dt).getTime() : 0;
        const tb = b.test_time_dt ? new Date(b.test_time_dt).getTime() : 0;
        return tb - ta;
      });
      return sorted[0];
    });
  }

  function openDrillDown(rowOrFilter) {
    const modal = $('modal-drill');
    const titleEl = $('modal-drill-title');
    const subtitleEl = $('modal-drill-subtitle');
    const tbody = $('modal-drill-tbody');
    if (!modal || !tbody) return;
    const filteredRows = getRowsForDrillDown(rowOrFilter);
    const snRows = groupBySn(filteredRows);
    const isFilter = rowOrFilter && 'filter' in rowOrFilter;
    const filterLabel = isFilter ? (rowOrFilter.filter === 'fail' ? 'Fail' : rowOrFilter.filter === 'pass' ? 'Pass' : 'Total') : '';
    const singleSn = !isFilter && rowOrFilter ? (rowOrFilter.serial_number || '') : '';
    if (titleEl) titleEl.textContent = isFilter ? filterLabel + ' \u2022 ' + filterLabel : ('SN: ' + (singleSn || '-'));
    const dateStart = $('date-start')?.value || '';
    const dateEnd = $('date-end')?.value || '';
    const rangeStr = dateStart && dateEnd ? dateStart.slice(0, 16) + ' \u2192 ' + dateEnd.slice(0, 16) + ' (CA)' : '';
    if (subtitleEl) subtitleEl.textContent = (rangeStr ? rangeStr + ' \u2022 ' : '') + snRows.length + ' SN';
    if (!snRows.length) {
      tbody.innerHTML = '<tr><td colspan="7" style="color: var(--color-muted);">No data</td></tr>';
    } else {
      tbody.innerHTML = snRows.map((r) => {
        const res = (r.result || '').toUpperCase();
        const isFail = res === 'FAIL';
        const badgeClass = isFail ? 'fail' : 'pass';
        const bpVal = r.is_bonepile ? 'Yes' : 'No';
        const lastStation = r.station || '-';
        const failureMsg = r.failure_msg || r.error_code || '-';
        return '<tr>' +
          '<td>' + escapeHtml(r.serial_number || '') + '</td>' +
          '<td><span class="result-badge ' + badgeClass + '">' + (res || '-') + '</span></td>' +
          '<td>' + escapeHtml(r.part_number || '-') + '</td>' +
          '<td>' + escapeHtml(lastStation) + '</td>' +
          '<td>' + escapeHtml(r.test_time || '-') + '</td>' +
          '<td>' + escapeHtml(bpVal) + '</td>' +
          '<td>' + escapeHtml(String(failureMsg).slice(0, 80)) + (String(failureMsg).length > 80 ? '...' : '') + '</td>' +
          '<td class="log-path-cell">' + (r.serial_number ? '<button type="button" class="log-path-btn" data-sn="' + escapeAttr(r.serial_number) + '" title="Get log path from Crabber">Get log</button>' : '-') + '</td>' +
          '</tr>';
      }).join('');
    }
    modal.classList.add('active');
  }

  function closeDrillDown() {
    const modal = $('modal-drill');
    if (modal) modal.classList.remove('active');
  }

  const pinned = new Map();
  let pinPanelExpanded = true;

  function togglePin(sn, row) {
    if (pinned.has(sn)) {
      pinned.delete(sn);
    } else {
      pinned.set(sn, { sn, row, lastData: JSON.stringify(row), blink: false, expanded: false });
    }
    renderPinPanel();
  }

  function checkPinnedUpdates(newRows) {
    if (pinned.size === 0) return;
    const bySn = {};
    newRows.forEach((r) => {
      const s = r.serial_number || '';
      if (!bySn[s]) bySn[s] = [];
      bySn[s].push(r);
    });
    pinned.forEach((p) => {
      const list = bySn[p.sn] || [];
      const latest = list[0];
      const newData = latest ? JSON.stringify(latest) : '';
      if (newData && newData !== p.lastData) {
        p.lastData = newData;
        p.row = latest;
        p.blink = true;
        if (typeof Notification !== 'undefined' && Notification.permission === 'granted') {
          new Notification('FA Debug: ' + p.sn, { body: 'New data for pinned tray' });
        }
      }
    });
    renderPinPanel();
  }

  function renderPinPanel() {
    renderPinSidebar();
  }

  function renderPinSidebar() {
    const hasTimeline = pinned.size > 0;
    const hasEtf = etfPinnedSns.length > 0;
    if (!hasTimeline && !hasEtf) {
      const sb = $('pin-sidebar');
      if (sb) sb.remove();
      const app = document.getElementById('app-wrapper') || document.querySelector('.app-wrapper');
      if (app) app.style.marginLeft = '';
      return;
    }
    let sidebar = $('pin-sidebar');
    if (!sidebar) {
      sidebar = el('div', { id: 'pin-sidebar', className: 'pin-sidebar' });
      document.body.insertBefore(sidebar, document.body.firstChild);
    }
    const app = document.getElementById('app-wrapper') || document.querySelector('.app-wrapper');
    if (app) app.style.marginLeft = '220px';
    const header = el('div', { className: 'pin-sidebar-header' });
    const toggleBtn = el('button', { type: 'button' });
    toggleBtn.textContent = pinPanelExpanded ? '−' : '+';
    header.appendChild(document.createTextNode('Pinned '));
    header.appendChild(toggleBtn);
    toggleBtn.addEventListener('click', () => {
      pinPanelExpanded = !pinPanelExpanded;
      toggleBtn.textContent = pinPanelExpanded ? '−' : '+';
      const b = sidebar.querySelector('.pin-sidebar-body');
      if (b) b.style.display = pinPanelExpanded ? 'block' : 'none';
    });
    sidebar.innerHTML = '';
    sidebar.appendChild(header);
    const body = el('div', { className: 'pin-sidebar-body' });
    body.style.display = pinPanelExpanded ? 'block' : 'none';
    pinned.forEach((p) => {
      const res = (p.row?.result || '').toUpperCase();
      const status = res === 'PASS' ? 'pass' : res === 'FAIL' ? 'fail' : 'unknown';
      const div = el('div', { className: 'pin-sidebar-item ' + (p.expanded ? 'expanded' : '') });
      div.innerHTML = `<span class="pin-icon ${status}"></span><span class="pin-sn">${escapeHtml(p.sn)}</span><button type="button" class="unpin">×</button>`;
      if (p.blink) {
        p.blink = false;
        div.classList.add('blink');
        setTimeout(() => div.classList.remove('blink'), 2000);
      }
      div.querySelector('.unpin')?.addEventListener('click', (e) => { e.stopPropagation(); pinned.delete(p.sn); renderPinSidebar(); });
      div.addEventListener('click', (e) => {
        if (!e.target.classList.contains('unpin')) {
          p.expanded = !p.expanded;
          div.classList.toggle('expanded', p.expanded);
          const details = div.querySelector('.pin-details');
          if (details) details.style.display = p.expanded ? 'block' : 'none';
        }
      });
      const details = el('div', { className: 'pin-details' });
      details.innerHTML = 'Chi tiet se duoc tich hop sau khi co API';
      details.style.display = p.expanded ? 'block' : 'none';
      div.appendChild(details);
      body.appendChild(div);
    });
    etfPinnedSns.forEach(({ rowKey, sn }) => {
      const div = el('div', { className: 'pin-sidebar-item' });
      div.innerHTML = `<span class="pin-icon unknown"></span><span class="pin-sn">${escapeHtml(sn || rowKey)}</span>`;
      div.title = 'ETF SN – Chi tiet sau khi co API';
      div.addEventListener('click', () => {
        div.classList.toggle('expanded');
        const details = div.querySelector('.pin-details');
        if (details) details.style.display = details.style.display === 'none' ? 'block' : 'none';
      });
      const details = el('div', { className: 'pin-details' });
      details.innerHTML = 'Chi tiet se duoc tich hop sau khi co API';
      details.style.display = 'none';
      div.appendChild(details);
      body.appendChild(div);
    });
    sidebar.appendChild(body);
  }

  function applyFilter() {
    fetchData(true);
  }

  function initTheme() {
    const dark = localStorage.getItem('fa-debug-theme') === 'dark';
    document.documentElement.classList.toggle('dark', dark);
    const sunEl = $('sun-icon');
    const moonEl = $('moon-icon');
    if (sunEl) sunEl.classList.toggle('hidden', !dark);
    if (moonEl) moonEl.classList.toggle('hidden', dark);
  }

  function toggleTheme() {
    const dark = !document.documentElement.classList.contains('dark');
    document.documentElement.classList.toggle('dark', dark);
    localStorage.setItem('fa-debug-theme', dark ? 'dark' : 'light');
    const sunEl = $('sun-icon');
    const moonEl = $('moon-icon');
    if (sunEl) sunEl.classList.toggle('hidden', !dark);
    if (moonEl) moonEl.classList.toggle('hidden', dark);
  }

  function init() {
    setDefaultDates();
    initTheme();
    fetchData(false);

    const applyBtn = $('apply-filter');
    if (applyBtn) applyBtn.addEventListener('click', applyFilter);

    $('theme-toggle')?.addEventListener('click', toggleTheme);
    $('modal-close')?.addEventListener('click', closeDrillDown);
    $('modal-drill')?.addEventListener('click', (e) => {
      const logBtn = e.target.closest('.log-path-btn');
      if (logBtn) {
        e.stopPropagation();
        fetchAndShowLogPath(logBtn, logBtn.getAttribute('data-sn'));
        return;
      }
      if (e.target.id === 'modal-drill') closeDrillDown();
    });

    $('kpi-fail')?.addEventListener('click', () => { if (summary.fail > 0) openDrillDown({ filter: 'fail' }); });
    $('kpi-pass')?.addEventListener('click', () => { if (summary.pass > 0) openDrillDown({ filter: 'pass' }); });
    $('kpi-total')?.addEventListener('click', () => { if (summary.total > 0) openDrillDown({ filter: 'total' }); });

    const timelineFilterEl = $('timeline-filter');
    if (timelineFilterEl) timelineFilterEl.addEventListener('input', () => { timelineFilterQuery = timelineFilterEl.value; render(); });

    const endNowEl = $('end-now');
    if (endNowEl) {
      endNowEl.addEventListener('change', () => {
        const endEl = $('date-end');
        if (endEl) endEl.disabled = endNowEl.checked;
        if (endNowEl.checked) fetchData(true);
      });
    }

    $('btn-refresh-upload-history')?.addEventListener('click', () => { if (typeof window.etfRefreshUploadHistory === 'function') window.etfRefreshUploadHistory(); });
    $('btn-clear-upload-history')?.addEventListener('click', () => {
      if (!confirm('Clear upload list from local cache? AI server will not be affected.')) return;
      fetch('/api/fa-debug/upload-history-clear', { method: 'DELETE' })
        .then((r) => r.json())
        .then((data) => {
          if (data.error) alert('Clear failed: ' + data.error);
          else { alert('History cleared'); if (typeof window.etfRefreshUploadHistory === 'function') window.etfRefreshUploadHistory(); }
        })
        .catch((err) => alert('Clear failed: ' + (err?.message || err)));
    });

    setInterval(() => {
      const endNowEl = $('end-now');
      if (endNowEl?.checked) {
        fetchData(true);
      } else {
        fetchData(false);
      }
    }, POLL_MS);

    if (typeof window.etfRefreshUploadHistory === 'function') window.etfRefreshUploadHistory();
  }

  const snDebugPanels = new Map();
  let etfPinnedSns = [];

  function getConfig() {
    return window.FA_DEBUG_CONFIG || { wsUrl: 'ws://10.16.138.80:5111/api/agent/terminal', uploadUrl: 'http://10.16.138.80:5111/api/agent-uploads/upload' };
  }

  function scrollTerminalToBottom(containerEl) {
    const viewport = containerEl?.querySelector?.('.xterm-viewport');
    if (viewport) viewport.scrollTop = viewport.scrollHeight;
  }

  const scrollDebounce = new WeakMap();
  function scrollTerminalToBottomDebounced(containerEl) {
    if (!containerEl) return;
    const t = scrollDebounce.get(containerEl);
    if (t && Date.now() - t < 80) return;
    scrollDebounce.set(containerEl, Date.now());
    scrollTerminalToBottom(containerEl);
  }

  function initFitAddonAndOpen(term, containerEl) {
    let fitAddon = null;
    try {
      const FitCls = (typeof FitAddon !== 'undefined' ? FitAddon : null) || window?.FitAddon?.FitAddon || window?.FitAddon;
      if (FitCls) {
        fitAddon = new FitCls();
        term.loadAddon(fitAddon);
      }
    } catch (_) { fitAddon = null; }
    term.open(containerEl);
    let fitPending = null;
    const doFit = () => {
      if (fitAddon) { try { fitAddon.fit(); } catch (_) {} }
      scrollTerminalToBottomDebounced(containerEl);
    };
    const doFitDebounced = () => {
      if (fitPending) return;
      fitPending = true;
      requestAnimationFrame(() => {
        doFit();
        setTimeout(() => { fitPending = false; }, 100);
      });
    };
    setTimeout(doFit, 80);
    setTimeout(doFit, 300);
    if (fitAddon && typeof ResizeObserver !== 'undefined') {
      try {
        const ro = new ResizeObserver(doFitDebounced);
        ro.observe(containerEl);
        containerEl._fitObserver = ro;
      } catch (_) {}
    }
    return fitAddon;
  }

  function decodeMsg(data) {
    if (typeof data === 'string') return data;
    if (data instanceof Blob) return new Promise((res, rej) => { const r = new FileReader(); r.onload = () => res(r.result); r.onerror = rej; r.readAsText(data); });
    if (data instanceof ArrayBuffer) return new TextDecoder('utf-8').decode(data);
    return Promise.reject(new Error('Unknown type'));
  }
  function decodeMsgAsPromise(data) {
    const v = decodeMsg(data);
    return v && typeof v.then === 'function' ? v : Promise.resolve(v);
  }

  function createAiTerminalForSn(rowKey, containerEl) {
    const TerminalCls = typeof Terminal !== 'undefined' ? Terminal : (typeof window.Terminal !== 'undefined' ? window.Terminal : null);
    if (!containerEl || !TerminalCls) return null;
    let fitAddon = null;
    try {
      containerEl.innerHTML = '';
      containerEl.style.minHeight = '120px';
      const term = new TerminalCls({ cursorBlink: true, theme: { background: '#1e1e1e', foreground: '#d4d4d4' } });
      fitAddon = initFitAddonAndOpen(term, containerEl);
      const cfg = getConfig();
      const url = cfg.wsUrl || 'ws://10.16.138.80:5111/api/agent/terminal';
      const ws = new WebSocket(url);
      const ai = { term, ws, fitAddon };
      ws.onopen = () => {};
      ws.onmessage = (e) => {
        decodeMsgAsPromise(e.data).then((txt) => {
          term?.write(txt);
          scrollTerminalToBottomDebounced(containerEl);
        }).catch(() => {});
      };
      ws.onerror = () => {};
      ws.onclose = () => {};
      term.onData((data) => { if (ai.ws && ai.ws.readyState === WebSocket.OPEN) ai.ws.send(data); });
      return ai;
    } catch (err) {
      console.error('AI Terminal error:', err);
      containerEl.innerHTML = '<span style="color:#fca5a5;font-size:12px;">Terminal error: ' + (err?.message || 'Unknown') + '</span>';
      return null;
    }
  }

  function createSshTerminalForSn(rowKey, containerEl, sshHost) {
    const TerminalCls = typeof Terminal !== 'undefined' ? Terminal : (typeof window.Terminal !== 'undefined' ? window.Terminal : null);
    if (!containerEl || !TerminalCls) return null;
    let fitAddon = null;
    try {
      containerEl.innerHTML = '';
      containerEl.style.minHeight = '120px';
      const term = new TerminalCls({ cursorBlink: true, theme: { background: '#1e1e1e', foreground: '#d4d4d4' } });
      fitAddon = initFitAddonAndOpen(term, containerEl);
      const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
      let url = proto + '//' + location.host + '/ws/ssh';
      if (sshHost) url += '?host=' + encodeURIComponent(sshHost);
      const ws = new WebSocket(url);
      ws.onopen = () => {};
      ws.onmessage = (e) => {
        decodeMsgAsPromise(e.data).then((txt) => {
          term?.write(txt);
          scrollTerminalToBottomDebounced(containerEl);
        }).catch(() => {});
      };
      ws.onerror = () => {};
      ws.onclose = () => {};
      term.onData((data) => { if (ws && ws.readyState === WebSocket.OPEN) ws.send(data); });
      return { term, ws, fitAddon };
    } catch (err) {
      console.error('SSH Terminal error:', err);
      containerEl.innerHTML = '<span style="color:#fca5a5;font-size:12px;">SSH error: ' + (err?.message || 'Unknown') + '</span>';
      return null;
    }
  }

  window.etfCreateSnTerminals = function(sn, rowKey, action, { aiEl, sshEl, row }) {
    let panel = snDebugPanels.get(rowKey);
    if (!panel) {
      panel = { ai: null, ssh: null };
      snDebugPanels.set(rowKey, panel);
    }
    const sshHost = (row && row.ssh_host) ? row.ssh_host : undefined;
    const showAi = (action === 'ai' || action === 'both') && aiEl;
    const showSsh = (action === 'term' || action === 'both') && sshEl;
    const run = () => {
      if (showAi && aiEl) {
        if (panel.ai) {
          try { panel.ai.ws?.close(); } catch (_) {}
          try { panel.ai.term?.dispose(); } catch (_) {}
          panel.ai = null;
        }
        panel.ai = createAiTerminalForSn(rowKey, aiEl);
      }
      if (showSsh && sshEl) {
        if (panel.ssh) {
          try { panel.ssh.ws?.close(); } catch (_) {}
          try { panel.ssh.term?.dispose(); } catch (_) {}
          panel.ssh = null;
        }
        panel.ssh = createSshTerminalForSn(rowKey, sshEl, sshHost);
      }
    };
    requestAnimationFrame(() => requestAnimationFrame(run));
  };

  window.etfAiStartSession = function(rowKey) {
    const panel = snDebugPanels.get(rowKey);
    if (!panel?.ai?.term) return;
    const ai = panel.ai;
    if (ai.ws && ai.ws.readyState === WebSocket.OPEN) return;
    try {
      if (ai.ws) ai.ws.close();
    } catch (_) {}
    const cfg = getConfig();
    const url = cfg.wsUrl || 'ws://10.16.138.80:5111/api/agent/terminal';
    const ws = new WebSocket(url);
    ws.onopen = () => {};
    ws.onmessage = (e) => {
      decodeMsgAsPromise(e.data).then((txt) => {
        ai.term?.write(txt);
        const container = ai.term?.element?.closest?.('.sn-debug-ai-container');
        if (container) scrollTerminalToBottom(container);
      }).catch(() => {});
    };
    ws.onerror = () => {};
    ws.onclose = () => {};
    ai.ws = ws;
  };

  window.etfAiEndSession = function(rowKey) {
    const panel = snDebugPanels.get(rowKey);
    if (!panel?.ai) return;
    try {
      if (panel.ai.ws) {
        panel.ai.ws.close(1000, "user ended session");
        panel.ai.ws = null;
      }
    } catch (_) {}
  };

  function extractFilePaths(data) {
    if (!data || typeof data !== 'object') return [];
    if (Array.isArray(data.paths)) return data.paths;
    if (typeof data.path === 'string') return [data.path];
    if (typeof data.file_path === 'string') return [data.file_path];
    if (Array.isArray(data.files)) return data.files.map((f) => (typeof f === 'string' ? f : f.path || f.file_path || f)).filter(Boolean);
    if (Array.isArray(data.uploaded)) return data.uploaded.map((f) => (typeof f === 'string' ? f : f.path || f.file_path)).filter(Boolean);
    if (data.result && typeof data.result === 'object') return extractFilePaths(data.result);
    return [];
  }

  window.etfAiUpload = function(rowKey) {
    const url = '/api/fa-debug/agent-upload';
    const input = document.createElement('input');
    input.type = 'file';
    input.multiple = true;
    input.onchange = () => {
      const files = input.files;
      if (!files?.length) return;
      const fd = new FormData();
      const key = files.length === 1 ? 'file' : 'files';
      for (let i = 0; i < files.length; i++) fd.append(key, files[i]);
      if (rowKey) fd.append('row_key', rowKey);
      fetch(url, { method: 'POST', body: fd })
        .then(async (r) => {
          const text = await r.text();
          let data;
          try { data = JSON.parse(text); } catch (_) { data = {}; }
          if (!r.ok) {
            const detail = data.detail || data.error;
            const msg = typeof detail === 'object' ? JSON.stringify(detail) : (detail || r.statusText);
            throw new Error(r.status + ': ' + msg);
          }
          if (data.error) throw new Error(data.error);
          const paths = extractFilePaths(data);
          const panel = snDebugPanels.get(rowKey);
          if (paths.length > 0 && panel?.ai?.ws && panel.ai.ws.readyState === WebSocket.OPEN) {
            paths.forEach((p) => { try { panel.ai.ws.send(p + '\n'); } catch (_) {} });
          }
          alert(paths.length > 0 ? 'Upload OK\n' + paths.join('\n') : 'Upload OK');
          if (typeof window.etfRefreshUploadHistory === 'function') window.etfRefreshUploadHistory();
        })
        .catch((err) => { console.warn('Upload failed:', err); alert('Upload failed: ' + (err?.message || err)); });
    };
    input.click();
  };

  window.etfRefreshUploadHistory = function() {
    fetch('/api/fa-debug/upload-history')
      .then((r) => r.json())
      .then((data) => {
        const entries = data.entries || [];
        const el = $('upload-history-list');
        if (!el) return;
        if (!entries.length) {
          el.innerHTML = '<div class="text-muted" style="font-size: 0.875rem;">No file uploaded yet.</div>';
          return;
        }
        el.innerHTML = entries.map((e) => {
          const sn = e.row_key ? escapeHtml(e.row_key) : '-';
          const p = (e.path || '').trim();
          const path = p ? escapeHtml(p.length > 50 ? p.slice(0, 50) + '...' : p) : '';
          return '<div class="upload-history-item" style="display:flex;align-items:center;gap:0.5rem;padding:0.4rem 0;font-size:0.8125rem;border-bottom:1px solid var(--color-border);">' +
            '<span title="' + escapeAttr(e.filename) + '">' + escapeHtml(e.filename) + '</span>' +
            '<span class="text-muted">' + escapeHtml(e.uploaded_at || '') + '</span>' +
            (sn !== '-' ? '<span class="text-muted">SN:' + sn + '</span>' : '') +
            (path ? '<span class="text-muted" title="' + escapeAttr(e.path || '') + '">' + path + '</span>' : '') +
            '</div>';
        }).join('');
      })
      .catch(() => {});
  };

  window.etfCloseSnPanel = function(rowKey) {
    const panel = snDebugPanels.get(rowKey);
    if (!panel) return;
    if (panel.ai) {
      try { panel.ai.ws?.close(); } catch (_) {}
      try { panel.ai.term?.dispose(); } catch (_) {}
      const container = panel.ai.term?.element?.closest?.('.sn-debug-ai-container');
      if (container?._fitObserver) { try { container._fitObserver.disconnect(); } catch (_) {} }
    }
    if (panel.ssh) {
      try { panel.ssh.ws?.close(); } catch (_) {}
      try { panel.ssh.term?.dispose(); } catch (_) {}
      const container = panel.ssh.term?.element?.closest?.('.sn-debug-ssh-container');
      if (container?._fitObserver) { try { container._fitObserver.disconnect(); } catch (_) {} }
    }
    snDebugPanels.delete(rowKey);
  };

  window.etfFitTerminals = function(rowKey) {
    const panel = snDebugPanels.get(rowKey);
    if (!panel) return;
    [panel.ai, panel.ssh].forEach((x) => {
      if (x?.fitAddon) { try { x.fitAddon.fit(); } catch (_) {} }
    });
  };

  window.etfUpdatePinnedSns = function(items) {
    etfPinnedSns = items || [];
    renderPinSidebar();
  };

  function onReady() {
    init();
  }
  function onWindowLoad() {
    // Terminals now created per-SN via etfCreateSnTerminals
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', onReady);
  } else {
    onReady();
  }
  if (document.readyState === 'complete') {
    onWindowLoad();
  } else {
    window.addEventListener('load', onWindowLoad);
  }
})();
