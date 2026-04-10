/**
 * FA Debug Place - KPI, timeline, drill-down, pin, xterm, theme.
 */
(function () {
  let rows = [];
  let summary = { total: 0, pass: 0, fail: 0 };
  /** SN -> bool, same semantics as KPI pass (server analytics pass_rules). */
  let snPass = {};
  let timelineFilterQuery = "";
  let timelineNextUpdateSec = 60;
  let timelineCountdownInterval = null;
  const POLL_MS = (() => {
    const c = typeof window !== 'undefined' ? window.FA_DEBUG_CONFIG : null;
    const n = c && Number(c.pollIntervalMs);
    return n > 0 ? n : 60000;
  })();
  let fetchDataInFlight = false;

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
    if (fetchDataInFlight) return Promise.resolve();
    fetchDataInFlight = true;
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
    return fetch(url, {
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
        snPass = data.sn_pass && typeof data.sn_pass === 'object' ? data.sn_pass : {};
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
      })
      .finally(() => { fetchDataInFlight = false; })
      .then(() => undefined);
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
          const resStr = (r.result || "").toLowerCase();
          const off = r.crabber_offline === true ? "offline" : "";
          const unc = (r.crabber_log_unc || "").toLowerCase();
          return sn.includes(q) || pn.includes(q) || st.includes(q) || ec.includes(q) || fm.includes(q)
            || resStr.includes(q) || (off && off.includes(q)) || unc.includes(q);
        })
      : rows;
    displayRows.forEach((r) => {
      const result = (r.result || '').toUpperCase();
      const isPass = result === 'PASS' || result === 'ALL PASS';
      const isTesting = result.includes('TESTING');
      const isOffline = r.crabber_offline === true;
      let badgeClass = 'timeline-result-badge--fail';
      if (result === 'ALL PASS') badgeClass = 'timeline-result-badge--all-pass';
      else if (isPass) badgeClass = 'timeline-result-badge--pass';
      else if (isTesting && isOffline) badgeClass = 'timeline-result-badge--testing-offline';
      else if (isTesting) badgeClass = 'timeline-result-badge--testing';
      const row = el('div', {
        className: 'timeline-row',
      });
      const bpNa = r.is_bonepile ? 'BP' : 'NA';
      const errTitle = r.failure_msg ? `title="${(r.failure_msg || '').replace(/"/g, '&quot;')}"` : '';
      const uncPath = (r.crabber_log_unc || '').trim();
      const uncCell = uncPath
        ? ((typeof CrabberLogUnc !== 'undefined' && CrabberLogUnc.copyBtnHtml)
          ? CrabberLogUnc.copyBtnHtml(uncPath)
          : `<span class="text-xs">${escapeHtml(uncPath)}</span>`)
        : makeLogPathCell(r.serial_number);
      row.innerHTML = [
        `<span class="timeline-result-badge ${badgeClass}">${escapeHtml(r.result || '-')}</span>`,
        `<span><button type="button" class="pin-btn pin-icon-btn" data-sn="${escapeAttr(r.serial_number)}" title="Pin"><svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" stroke="currentColor" stroke-width="1.5"><path d="M16 12V4h1V2H7v2h1v8l-2 2v2h5.2v6h1.6v-6H18v-2l-2-2z"/></svg></button> ${escapeHtml(r.serial_number || '')}</span>`,
        `<span>${escapeHtml(r.part_number || '')}</span>`,
        `<span>${bpNa}</span>`,
        `<span>${escapeHtml(r.test_time || '')}</span>`,
        `<span ${errTitle}>${escapeHtml(r.station || '')} ${r.error_code ? `(${escapeHtml(r.error_code)})` : ''}</span>`,
        `<span class="timeline-unc-cell">${uncCell}</span>`,
      ].join('');
      body.appendChild(row);

      const pinBtn = row.querySelector('.pin-btn');
      if (pinBtn) pinBtn.addEventListener('click', (e) => { e.stopPropagation(); togglePin(r.serial_number, r); });
      const logPathBtn = row.querySelector('.log-path-btn');
      if (logPathBtn) logPathBtn.addEventListener('click', (e) => { e.stopPropagation(); fetchAndShowLogPath(logPathBtn, r.serial_number); });
      row.addEventListener('click', (e) => {
        if (e.target.closest('.pin-btn') || e.target.closest('.log-path-btn') || e.target.closest('.crabber-unc-copy')) return;
        openDrillDown(r);
      });
    });
  }

  function makeLogPathCell(sn) {
    if (!sn) return '-';
    return '<button type="button" class="log-path-btn" data-sn="' + escapeAttr(sn) + '" title="Get UNC from Crabber log path">Get UNC</button>';
  }

  function uncFromCrabberLogPath(path) {
    const raw = String(path || '').trim();
    if (!raw) return '';
    if (raw.startsWith('\\\\')) return raw;
    const m = raw.match(/\/mnt\/l10\/(\d{4})\/(\d{2})\/(\d{2})\/([^\/\s]+)/i);
    if (!m) return '';
    const y = m[1];
    const mo = m[2];
    const d = m[3];
    const logId = m[4];
    const root = (window.CRABBER_LOG_UNC_ROOT || '').trim();
    if (!root) return '';
    if (typeof CrabberLogUnc !== 'undefined' && CrabberLogUnc.buildPath) {
      const iso = y + '-' + mo + '-' + d + 'T00:00:00Z';
      return CrabberLogUnc.buildPath(root, iso, logId) || '';
    }
    return root.replace(/[\\/]+$/, '') + '\\' + y + '\\' + mo + '\\' + d + '\\' + logId;
  }

  function fetchAndShowLogPath(btnOrCell, sn) {
    const cell = btnOrCell && btnOrCell.classList && btnOrCell.classList.contains('log-path-btn')
      ? btnOrCell.closest('.timeline-unc-cell, .log-path-cell') || btnOrCell.parentElement
      : btnOrCell;
    if (!cell || !sn) return;
    cell.innerHTML = '<span class="text-muted">...</span>';
    fetch('/api/debug/log-path?sn=' + encodeURIComponent(sn))
      .then((r) => r.json())
      .then((data) => {
        const unc = (data && data.ok && data.path) ? uncFromCrabberLogPath(data.path) : '';
        if (unc) {
          cell.innerHTML = (typeof CrabberLogUnc !== 'undefined' && CrabberLogUnc.copyBtnHtml)
            ? CrabberLogUnc.copyBtnHtml(unc)
            : '<span class="text-xs" title="' + escapeAttr(unc) + '">' + escapeHtml(unc) + '</span>';
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
      if (source.filter === 'pass') {
        return rows.filter((r) => {
          const x = (r.result || '').toUpperCase();
          return x === 'PASS' || x === 'ALL PASS';
        });
      }
      return rows;
    }
    const sn = source.serial_number || '';
    return rows.filter((r) => (r.serial_number || '') === sn);
  }

  function latestRowForSn(sn) {
    const t = (sn || '').trim();
    if (!t) return null;
    let best = null;
    let bestMs = -Infinity;
    rows.forEach((r) => {
      if ((r.serial_number || '').trim() !== t) return;
      const ms = r.test_time_dt ? new Date(r.test_time_dt).getTime() : 0;
      if (best == null || ms >= bestMs) {
        best = r;
        bestMs = ms;
      }
    });
    return best;
  }

  /**
   * KPI Pass/Fail/Total counts use server sn_pass + pass_rules (latest row per SN).
   * Drill-down must list the same SN set, one representative row each (newest in merged timeline).
   */
  function drillDownRowsForKpiFilter(filter) {
    if (!snPass || typeof snPass !== 'object' || !Object.keys(snPass).length) return null;
    const sns = Object.keys(snPass).filter((k) => {
      if (filter === 'pass') return snPass[k] === true;
      if (filter === 'fail') return snPass[k] === false;
      return true;
    });
    const out = [];
    sns.forEach((sn) => {
      const r = latestRowForSn(sn);
      if (r) out.push(r);
    });
    out.sort((a, b) => {
      const tb = b.test_time_dt ? new Date(b.test_time_dt).getTime() : 0;
      const ta = a.test_time_dt ? new Date(a.test_time_dt).getTime() : 0;
      return tb - ta;
    });
    return out;
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

  function fetchRoomForSn(sn) {
    if (!sn || !sn.trim()) return Promise.resolve(null);
    return fetch('/api/etf/search?q=' + encodeURIComponent(sn.trim()))
      .then((r) => r.json())
      .then((data) => (data.ok && data.rows && data.rows[0]) ? data.rows[0] : null)
      .catch(() => null);
  }

  function openDrillDown(rowOrFilter) {
    const modal = $('modal-drill');
    const titleEl = $('modal-drill-title');
    const subtitleEl = $('modal-drill-subtitle');
    const roomEl = $('modal-drill-room');
    const tbody = $('modal-drill-tbody');
    if (!modal || !tbody) return;
    const isFilter = rowOrFilter && 'filter' in rowOrFilter;
    let snRows;
    if (isFilter && (rowOrFilter.filter === 'pass' || rowOrFilter.filter === 'fail' || rowOrFilter.filter === 'total')) {
      const aligned = drillDownRowsForKpiFilter(rowOrFilter.filter);
      if (aligned != null) snRows = aligned;
    }
    if (snRows == null) {
      const filteredRows = getRowsForDrillDown(rowOrFilter);
      snRows = groupBySn(filteredRows);
    }
    const filterLabel = isFilter ? (rowOrFilter.filter === 'fail' ? 'Fail' : rowOrFilter.filter === 'pass' ? 'Pass' : 'Total') : '';
    const singleSn = !isFilter && rowOrFilter ? (rowOrFilter.serial_number || '') : '';
    if (titleEl) titleEl.textContent = isFilter ? filterLabel + ' \u2022 ' + filterLabel : ('SN: ' + (singleSn || '-'));
    const dateStart = $('date-start')?.value || '';
    const dateEnd = $('date-end')?.value || '';
    const rangeStr = dateStart && dateEnd ? dateStart.slice(0, 16) + ' \u2192 ' + dateEnd.slice(0, 16) + ' (CA)' : '';
    if (subtitleEl) subtitleEl.textContent = (rangeStr ? rangeStr + ' \u2022 ' : '') + snRows.length + ' SN';
    if (roomEl) roomEl.textContent = '';
    if (!snRows.length) {
      tbody.innerHTML = '<tr><td colspan="9" style="color: var(--color-muted);">No data</td></tr>';
    } else {
      tbody.innerHTML = snRows.map((r) => {
        const res = (r.result || '').toUpperCase();
        const isFail = res === 'FAIL';
        const badgeClass = isFail ? 'fail' : 'pass';
        const bpVal = r.is_bonepile ? 'Yes' : 'No';
        const lastStation = r.station || '-';
        const failureMsg = r.failure_msg || r.error_code || '-';
        const sn = r.serial_number || '';
        return '<tr>' +
          '<td>' + escapeHtml(sn) + '</td>' +
          '<td><span class="result-badge ' + badgeClass + '">' + (res || '-') + '</span></td>' +
          '<td>' + escapeHtml(r.part_number || '-') + '</td>' +
          '<td>' + escapeHtml(lastStation) + '</td>' +
          '<td>' + escapeHtml(r.test_time || '-') + '</td>' +
          '<td>' + escapeHtml(bpVal) + '</td>' +
          '<td class="room-cell" data-sn="' + escapeAttr(sn) + '">-</td>' +
          '<td>' + escapeHtml(String(failureMsg).slice(0, 80)) + (String(failureMsg).length > 80 ? '...' : '') + '</td>' +
          '<td class="timeline-unc-cell">' + ((r.crabber_log_unc || '').trim()
            ? ((typeof CrabberLogUnc !== 'undefined' && CrabberLogUnc.copyBtnHtml)
              ? CrabberLogUnc.copyBtnHtml((r.crabber_log_unc || '').trim())
              : '<span class="text-xs">' + escapeHtml((r.crabber_log_unc || '').trim()) + '</span>')
            : (sn ? '<button type="button" class="log-path-btn" data-sn="' + escapeAttr(sn) + '" title="Get UNC from Crabber log path">Get UNC</button>' : '-')) + '</td>' +
          '</tr>';
      }).join('');
    }
    modal.classList.add('active');

    const uniqueSns = [...new Set(snRows.map((r) => (r.serial_number || '').trim()).filter(Boolean))];
    uniqueSns.forEach((sn) => {
      fetchRoomForSn(sn).then((row) => {
        if (!row || !row.room) return;
        const label = row.ssh_host ? row.room + ' (' + row.ssh_host + ')' : row.room;
        if (singleSn && roomEl) roomEl.textContent = 'Room: ' + label;
        tbody.querySelectorAll('.room-cell').forEach((td) => { if (td.dataset.sn === sn) td.textContent = label; });
      });
    });
  }

  function closeDrillDown() {
    const modal = $('modal-drill');
    if (modal) modal.classList.remove('active');
  }

  const pinned = new Map();
  let pinPanelExpanded = true;

  function togglePin(sn, row) {
    const key = (sn || '').trim();
    if (!key) return;
    if (pinned.has(key)) {
      pinned.delete(key);
    } else {
      pinned.set(key, { sn: key, row, lastData: JSON.stringify(row), lastResult: '', blink: false, expanded: false, pinnedAt: Date.now(), room: row?.room || '–', lastNotifiedAt: 0 });
    }
    renderPinPanel();
  }

  function parseTestTime(row) {
    if (!row) return null;
    const dt = row.test_time_dt;
    if (dt != null) {
      const t = typeof dt === 'string' ? new Date(dt) : dt;
      if (t && typeof t.getTime === 'function' && isFinite(t.getTime())) return t.getTime();
    }
    const s = (row.test_time || '').trim();
    if (!s) return null;
    const m = s.match(/^(\d{4})\/(\d{2})\/(\d{2})\s+(\d{2}):(\d{2}):(\d{2})/);
    if (m) {
      const d = new Date(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +m[6]);
      return isFinite(d.getTime()) ? d.getTime() : null;
    }
    const d = new Date(s.replace(/\//g, '-').replace(' ', 'T'));
    return isFinite(d.getTime()) ? d.getTime() : null;
  }

  /** Newest test row for an SN (timeline order is not guaranteed — PROC + SFC rows interleave). */
  function newestRowForSn(list) {
    if (!list || list.length === 0) return null;
    let best = list[0];
    let bestT = parseTestTime(best);
    if (bestT == null) bestT = -Infinity;
    for (let i = 1; i < list.length; i++) {
      const r = list[i];
      const t = parseTestTime(r);
      const tt = t != null ? t : -Infinity;
      if (tt > bestT) {
        bestT = tt;
        best = r;
      }
    }
    return best;
  }

  function classifyPinnedResult(latest) {
    const resUpper = (latest?.result || '').toUpperCase();
    const offline = latest?.crabber_offline === true || resUpper.includes('OFFLINE');
    const isTesting = resUpper.includes('TESTING');

    if (resUpper === 'PASS') return { kind: 'pass', label: 'PASS' };
    if (resUpper === 'ALL PASS') return { kind: 'all-pass', label: 'ALL PASS' };
    if (resUpper === 'FAIL') return { kind: 'fail', label: 'FAIL' };
    if (isTesting) return { kind: offline ? 'testing-offline' : 'testing', label: offline ? 'TESTING (OFFLINE)' : 'TESTING' };
    return { kind: 'unknown', label: latest?.result || '' };
  }

  /** SFC tray last_end_time "YYYY/MM/DD HH:mm:ss" → epoch ms (local), same as Testing table. */
  function parseEtfSfcEndMs(s) {
    if (!s || typeof s !== 'string') return null;
    const m = s.trim().match(/^(\d{4})\/(\d{2})\/(\d{2})\s+(\d{2}):(\d{2}):(\d{2})$/);
    if (!m) return null;
    const d = new Date(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +m[6]);
    return isFinite(d.getTime()) ? d.getTime() : null;
  }

  function classifyEtfSfcRemark(remark) {
    const u = (remark || '').toUpperCase();
    if (u.includes('FAIL')) return { kind: 'fail', label: remark || 'FAIL' };
    if (u.includes('PASS')) return { kind: 'pass', label: remark || 'PASS' };
    return { kind: 'unknown', label: remark || '–' };
  }

  function checkPinnedUpdates(newRows) {
    if (pinned.size === 0) return;
    const bySn = {};
    newRows.forEach((r) => {
      const s = (r.serial_number || '').trim();
      if (!s) return;
      if (!bySn[s]) bySn[s] = [];
      bySn[s].push(r);
    });
    const now = Date.now();
    pinned.forEach((p) => {
      const snKey = (p.sn || '').trim();
      const list = bySn[snKey] || [];
      const latest = newestRowForSn(list);
      if (!latest) return;
      p.row = latest;
      const newData = JSON.stringify(latest);
      const pinTime = p.pinnedAt != null ? p.pinnedAt : now;
      if (newData !== p.lastData) {
        p.lastData = newData;
        const testTime = parseTestTime(latest);
        const afterPin = testTime != null && testTime > pinTime;
        const classified = classifyPinnedResult(latest);
        p.lastResult = classified.label;

        if (afterPin && classified.kind !== 'unknown') {
          p.blink = classified.kind;
          if (typeof Notification !== 'undefined' && Notification.permission === 'granted') {
            p.lastNotifiedAt = now;
            const body = (classified.label || latest.result || 'Update') +
              (latest.station ? (' | ' + latest.station) : '') +
              (latest.test_time ? (' | ' + latest.test_time) : '');
            new Notification('FA Debug: ' + p.sn, { body });
          }
        }
      }
    });
    renderPinPanel();
  }

  const NOTEPAD_WIDTH_EXPANDED = 260;
  const NOTEPAD_WIDTH_COLLAPSED = 40;

  function updateLeftSidebars() {
    const notepadEl = $('notepad-sidebar');
    const app = document.getElementById('app-wrapper') || document.querySelector('.app-wrapper');
    if (app) {
      let leftPad = '';
      if (notepadEl) {
        leftPad = notepadEl.classList.contains('expanded') ? NOTEPAD_WIDTH_EXPANDED : NOTEPAD_WIDTH_COLLAPSED;
      }
      app.style.paddingLeft = leftPad ? leftPad + 'px' : '';
    }
    const pinW = 0;
    if (app) app.style.marginRight = pinW ? pinW + 'px' : '';
  }

  function renderNotepadSidebar() {
    if (typeof window.initFaDebugNotepad === 'function') {
      window.initFaDebugNotepad({
        mode: 'sidebar',
        storagePrefix: 'fa-debug-notepad',
        onLayoutChange: updateLeftSidebars,
      });
    }
    updateLeftSidebars();
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
      updateLeftSidebars();
      return;
    }
    let sidebar = $('pin-sidebar');
    if (!sidebar) {
      sidebar = el('div', { id: 'pin-sidebar', className: 'pin-sidebar' });
      document.body.appendChild(sidebar);
    }
    sidebar.innerHTML = '';
    const body = el('div', { className: 'pin-sidebar-body' });
    pinned.forEach((p) => {
      const res = (p.row?.result || '').toUpperCase();
      const testTime = parseTestTime(p.row);
      const pinTime = p.pinnedAt != null ? p.pinnedAt : 0;
      const afterPin = testTime != null && pinTime > 0 && testTime > pinTime;
      const classified = classifyPinnedResult(p.row);
      let status = 'unknown';
      if (afterPin) status = classified.kind;
      const expanded = p.expanded;
      const div = el('div', { className: 'pin-sidebar-item' + (expanded ? '' : ' collapsed') });
      const iconSpan = document.createElement('span');
      const blinkClass = (p.blink && p.blink !== false) ? ' blink' : '';
      iconSpan.className = 'pin-icon ' + status + blinkClass;
      /* blink stays until user clicks (see click handler: p.blink = false) */
      const snSpan = el('span', { className: 'pin-sn' });
      snSpan.textContent = p.sn || '–';
      snSpan.title = p.sn || '';
      const room = p.room != null ? p.room : (p.row?.room || '–');
      const err = res === 'FAIL' ? (p.row?.failure_msg || p.row?.error_code || '') : '';
      const statusRemark = (res || '–') + (err ? ' | ' + err : '');
      const pinTimeStr = p.pinnedAt != null ? (function () {
        const d = new Date(p.pinnedAt);
        return 'Pinned ' + d.getHours().toString().padStart(2, '0') + ':' + d.getMinutes().toString().padStart(2, '0');
      }()) : '';
      const detailsText = room + ' | ' + statusRemark + (pinTimeStr ? ' | ' + pinTimeStr : '');
      const details = el('div', { className: 'pin-details' });
      details.textContent = detailsText;
      details.title = detailsText;
      const unpinBtn = el('button', { type: 'button', className: 'unpin' });
      unpinBtn.textContent = '×';
      unpinBtn.title = 'Unpin';
      div.appendChild(iconSpan);
      div.appendChild(snSpan);
      div.appendChild(details);
      div.appendChild(unpinBtn);
      unpinBtn.addEventListener('click', (e) => { e.stopPropagation(); pinned.delete(p.sn); renderPinSidebar(); });
      div.addEventListener('click', (e) => {
        if (!e.target.classList.contains('unpin')) {
          p.expanded = !p.expanded;
          p.blink = false;
          div.classList.toggle('collapsed', !p.expanded);
          renderPinSidebar();
        }
      });
      div.title = expanded ? 'Click to collapse' : 'Click to expand';
      body.appendChild(div);
    });
    etfPinnedSns.forEach((ep) => {
      const rowKey = ep.rowKey;
      const sn = ep.sn || rowKey || '–';
      const room = ep.room || 'ETF';
      const endMs = parseEtfSfcEndMs(ep.sfcLastEnd || '');
      const pinnedAt = ep.pinnedAt != null ? ep.pinnedAt : 0;
      const afterPin = endMs != null && pinnedAt > 0 && endMs > pinnedAt;
      const classified = classifyEtfSfcRemark(ep.sfcRemark || '');
      let status = 'unknown';
      if (afterPin) status = classified.kind !== 'unknown' ? classified.kind : 'testing';
      const expanded = !!ep.expanded;
      const div = el('div', { className: 'pin-sidebar-item' + (expanded ? '' : ' collapsed') });
      const iconSpan = document.createElement('span');
      const blinkClass = ep.blink && ep.blink !== false ? ' blink' : '';
      iconSpan.className = 'pin-icon ' + status + blinkClass;
      const snSpan = el('span', { className: 'pin-sn' });
      snSpan.textContent = sn;
      snSpan.title = sn;
      const remark = (ep.sfcRemark || '').trim() || '–';
      const pinTimeStr = pinnedAt > 0 ? (function () {
        const d = new Date(pinnedAt);
        return 'Pinned ' + d.getHours().toString().padStart(2, '0') + ':' + d.getMinutes().toString().padStart(2, '0');
      }()) : '';
      const detailsText = (room || 'ETF') + ' | ' + remark + (pinTimeStr ? ' | ' + pinTimeStr : '');
      const details = el('div', { className: 'pin-details' });
      details.textContent = detailsText;
      details.title = detailsText;
      const unpinBtn = el('button', { type: 'button', className: 'unpin' });
      unpinBtn.textContent = '×';
      unpinBtn.title = 'Unpin';
      div.appendChild(iconSpan);
      div.appendChild(snSpan);
      div.appendChild(details);
      div.appendChild(unpinBtn);
      unpinBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        if (typeof window.etfUnpinSn === 'function') window.etfUnpinSn(rowKey);
        else {
          const ix = etfPinnedSns.findIndex((x) => x.rowKey === rowKey);
          if (ix >= 0) etfPinnedSns.splice(ix, 1);
          renderPinSidebar();
        }
      });
      div.addEventListener('click', (e) => {
        if (!e.target.classList.contains('unpin')) {
          ep.expanded = !expanded;
          ep.blink = false;
          renderPinSidebar();
        }
      });
      div.title = expanded ? 'Click to collapse' : 'Click to expand';
      body.appendChild(div);
    });
    sidebar.appendChild(body);
    updateLeftSidebars();
  }

  function applyFilter() {
    const btn = $('apply-filter');
    const txt = btn?.querySelector('.btn-text');
    const spin = btn?.querySelector('.btn-spinner');
    if (txt) txt.classList.add('hidden');
    if (spin) spin.classList.remove('hidden');
    fetchData(true).finally(() => {
      if (txt) txt.classList.remove('hidden');
      if (spin) spin.classList.add('hidden');
    });
  }

  function init() {
    if (!document.getElementById('kpi-total-val')) {
      return;
    }
    setDefaultDates();
    renderNotepadSidebar();
    applyFilter();

    const applyBtn = $('apply-filter');
    if (applyBtn) applyBtn.addEventListener('click', applyFilter);

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

    $('timeline-body')?.addEventListener('click', (e) => {
      const btn = e.target.closest('.crabber-unc-copy');
      if (!btn) return;
      e.stopPropagation();
      if (typeof CrabberLogUnc !== 'undefined' && CrabberLogUnc.performCopy) {
        CrabberLogUnc.performCopy(btn);
      }
    });

    const endNowEl = $('end-now');
    const endDateWrap = $('end-date-wrap');
    const toggleEndDateVisibility = () => {
      if (endDateWrap) endDateWrap.style.display = endNowEl?.checked ? 'none' : '';
      const endEl = $('date-end');
      if (endEl) endEl.disabled = endNowEl?.checked ?? false;
    };
    if (endNowEl) {
      toggleEndDateVisibility();
      endNowEl.addEventListener('change', () => {
        toggleEndDateVisibility();
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

  window.etfUpdatePinnedSns = function (items) {
    const prevMap = new Map(etfPinnedSns.map((x) => [x.rowKey, x]));
    const now = Date.now();
    etfPinnedSns = (items || []).map((it) => {
      const prev = prevMap.get(it.rowKey);
      const pinnedAt = prev && prev.pinnedAt != null ? prev.pinnedAt : now;
      const sig = (it.sfcLastEnd || '') + '|' + (it.sfcRemark || '');
      const endMs = parseEtfSfcEndMs(it.sfcLastEnd || '');
      const afterPin = endMs != null && endMs > pinnedAt;
      const classified = classifyEtfSfcRemark(it.sfcRemark || '');
      const sigChanged = prev && sig !== (prev.lastSig || '');
      let blink = prev && prev.blink ? prev.blink : false;
      if (prev && afterPin && sigChanged) {
        blink = classified.kind !== 'unknown' ? classified.kind : 'testing';
      }
      return {
        ...it,
        pinnedAt,
        lastSig: sig,
        blink,
        expanded: prev && prev.expanded != null ? prev.expanded : false,
      };
    });
    renderPinSidebar();
  };

  function getConfig() {
    return window.FA_DEBUG_CONFIG || {};
  }

  function scrollTerminalToBottom(containerEl) {
    if (!containerEl?.isConnected) return;
    const viewport = containerEl?.querySelector?.('.xterm-viewport');
    if (!viewport) return;
    viewport.scrollTop = Math.max(0, viewport.scrollHeight - viewport.clientHeight);
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
      if (!containerEl?.isConnected) return;
      const rect = containerEl.getBoundingClientRect();
      if (rect.width < 1 || rect.height < 1) {
        try {
          if (term.cols < 2 || term.rows < 2) term.resize(80, 24);
        } catch (_) {}
        return;
      }
      if (fitAddon) { try { fitAddon.fit(); } catch (_) {} }
      try {
        if (term.cols < 2 || term.rows < 2) term.resize(80, 24);
      } catch (_) {}
      // Plain SSH panes (Testing): FitAddon often fits 1–2 extra rows; the active line + cursor render below the clip.
      // Shrink row count so the cursor stays inside the viewport, then scroll/focus.
      if (containerEl?.classList?.contains('terminal-pure-xterm')) {
        try {
          const next = Math.max(3, term.rows - 2);
          if (next < term.rows) term.resize(term.cols, next);
        } catch (_) {}
        requestAnimationFrame(() => {
          try {
            scrollTerminalToBottom(containerEl);
            term.focus();
          } catch (_) {}
          requestAnimationFrame(() => {
            try { scrollTerminalToBottom(containerEl); } catch (_) {}
          });
        });
      } else {
        scrollTerminalToBottomDebounced(containerEl);
      }
    };
    const doFitDebounced = () => {
      if (fitPending) return;
      fitPending = true;
      requestAnimationFrame(() => {
        doFit();
        setTimeout(() => { fitPending = false; }, 200);
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
      const term = new TerminalCls({ cursorBlink: false, theme: { background: '#1e1e1e', foreground: '#d4d4d4' } });
      fitAddon = initFitAddonAndOpen(term, containerEl);
      const cfg = getConfig();
      const url = cfg.wsUrl || '';
      const ws = url ? new WebSocket(url) : null;
      const ai = { term, ws, fitAddon };
      if (!ws) {
        try { if (term && containerEl?.isConnected) term.write('\r\n[AI terminal not configured. Set WS_TERMINAL_URL in config.]\r\n'); } catch (_) {}
      } else {
      try {
        term.writeln('\x1b[90mAI: click “Start session” if no output appears.\x1b[0m');
      } catch (_) {}
      ws.onopen = () => {};
      ws.onmessage = (e) => {
        decodeMsgAsPromise(e.data).then((txt) => {
          try { if (term && containerEl?.isConnected) term.write(txt); } catch (_) {}
          scrollTerminalToBottomDebounced(containerEl);
        }).catch(() => {});
      };
      ws.onerror = () => {};
      ws.onclose = () => {
        try {
          if (term && containerEl?.isConnected) {
            term.write('\r\n\r\n\x1b[33m[Session ended. Click Start Session to reconnect.]\x1b[0m\r\n');
            scrollTerminalToBottomDebounced(containerEl);
          }
        } catch (_) {}
      };
      term.onData((data) => {
        try { if (ai.ws && ai.ws.readyState === WebSocket.OPEN) ai.ws.send(data); } catch (_) {}
      });
      }
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
      const term = new TerminalCls({
        cursorBlink: true,
        theme: { background: '#1e1e1e', foreground: '#d4d4d4', cursor: '#f8f8f2' },
      });
      fitAddon = initFitAddonAndOpen(term, containerEl);
      const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
      let url = proto + '//' + location.host + '/ws/ssh';
      if (sshHost) url += '?host=' + encodeURIComponent(sshHost);
      const ws = new WebSocket(url);
      try {
        term.writeln('\x1b[90mConnecting to jump host (SSH)…\x1b[0m');
      } catch (_) {}
      ws.onopen = () => {};
      ws.onmessage = (e) => {
        decodeMsgAsPromise(e.data).then((txt) => {
          try { if (term && containerEl?.isConnected) term.write(txt); } catch (_) {}
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

  function createSshTerminalWithTypeTarget(rowKey, containerEl, wsType, targetIp, jumpHost) {
    const TerminalCls = typeof Terminal !== 'undefined' ? Terminal : (typeof window.Terminal !== 'undefined' ? window.Terminal : null);
    if (!containerEl || !TerminalCls || !targetIp) return null;
    let fitAddon = null;
    try {
      containerEl.innerHTML = '';
      containerEl.style.minHeight = '120px';
      const term = new TerminalCls({
        cursorBlink: true,
        theme: { background: '#1e1e1e', foreground: '#d4d4d4', cursor: '#f8f8f2' },
      });
      fitAddon = initFitAddonAndOpen(term, containerEl);
      const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
      let url = proto + '//' + location.host + '/ws/ssh?type=' + encodeURIComponent(wsType) + '&target=' + encodeURIComponent(targetIp);
      if (jumpHost) url += '&jump_host=' + encodeURIComponent(jumpHost);
      const ws = new WebSocket(url);
      try {
        const label = wsType === 'bmc' ? 'BMC' : 'Host';
        term.writeln('\x1b[90mConnecting (' + label + ' via jump)…\x1b[0m');
      } catch (_) {}
      ws.onopen = () => {};
      ws.onmessage = (e) => {
        decodeMsgAsPromise(e.data).then((txt) => {
          try { if (term && containerEl?.isConnected) term.write(txt); } catch (_) {}
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

  window.etfCreateSnTerminals = function(sn, rowKey, actionOrPayload, opts) {
    let panel = snDebugPanels.get(rowKey);
    if (!panel) {
      panel = { ai: null, ssh: null, bmc: null, host: null };
      snDebugPanels.set(rowKey, panel);
    }
    const isPayload = typeof actionOrPayload === 'object' && actionOrPayload !== null && (actionOrPayload.aiEl != null || actionOrPayload.sshEl != null || actionOrPayload.bmcEl != null || actionOrPayload.hostEl != null);
    const payload = isPayload ? actionOrPayload : (opts || {});
    const action = isPayload ? null : actionOrPayload;
    // Third-arg form: etfCreateSnTerminals(sn, rowKey, null, { aiEl, sshEl, ... }) — action is null but containers live on opts/payload.
    const useOptsContainers = !isPayload && actionOrPayload == null && (payload.aiEl != null || payload.sshEl != null || payload.bmcEl != null || payload.hostEl != null);
    const aiEl = (isPayload || useOptsContainers) ? (payload.aiEl || null) : ((action === 'ai' || action === 'both') && payload.aiEl) ? payload.aiEl : null;
    const sshEl = (isPayload || useOptsContainers) ? (payload.sshEl || null) : ((action === 'term' || action === 'both') && payload.sshEl) ? payload.sshEl : null;
    const bmcEl = (isPayload || useOptsContainers) ? (payload.bmcEl || null) : (action === 'bmc' && payload.bmcEl) ? payload.bmcEl : null;
    const hostEl = (isPayload || useOptsContainers) ? (payload.hostEl || null) : (action === 'host' && payload.hostEl) ? payload.hostEl : null;
    const row = payload.row;

    const run = () => {
      if (aiEl) {
        if (panel.ai) {
          try { panel.ai.ws?.close(); } catch (_) {}
          try { panel.ai.term?.dispose(); } catch (_) {}
          panel.ai = null;
        }
        panel.ai = createAiTerminalForSn(rowKey, aiEl);
      }
      if (sshEl) {
        const sshHost = (row && row.ssh_host) ? row.ssh_host : undefined;
        if (panel.ssh) {
          try { panel.ssh.ws?.close(); } catch (_) {}
          try { panel.ssh.term?.dispose(); } catch (_) {}
          panel.ssh = null;
        }
        panel.ssh = createSshTerminalForSn(rowKey, sshEl, sshHost);
      }
      if (bmcEl && row?.bmc_ip) {
        if (panel.bmc) {
          try { panel.bmc.ws?.close(); } catch (_) {}
          try { panel.bmc.term?.dispose(); } catch (_) {}
          panel.bmc = null;
        }
        panel.bmc = createSshTerminalWithTypeTarget(rowKey, bmcEl, 'bmc', row.bmc_ip, row.ssh_host);
      }
      if (hostEl && row?.sys_ip) {
        const sysIp = String(row.sys_ip || '').trim();
        if (sysIp && sysIp.toUpperCase() !== 'N/A' && sysIp !== '-') {
          if (panel.host) {
            try { panel.host.ws?.close(); } catch (_) {}
            try { panel.host.term?.dispose(); } catch (_) {}
            panel.host = null;
          }
          panel.host = createSshTerminalWithTypeTarget(rowKey, hostEl, 'host', sysIp, row.ssh_host);
        }
      }
    };
    requestAnimationFrame(() => requestAnimationFrame(run));
  };

  /**
   * Recreate only the jump-host SSH panel with a new ssh_host (same as Testing page WebSocket ?host=…).
   * Leaves AI/BMC/Host terminals unchanged. Caller supplies the #term-ssh (or equivalent) element.
   */
  window.etfReconnectJumpSshOnly = function (rowKey, sn, sshHost, sshEl) {
    if (!rowKey || !sshEl || typeof window.etfCreateSnTerminals !== "function") return;
    const h = (sshHost || "").trim();
    window.etfCreateSnTerminals(sn || rowKey, rowKey, null, {
      sshEl: sshEl,
      row: { ssh_host: h },
    });
    if (typeof window.etfFitTerminals === "function") {
      [0, 120, 400, 900].forEach(function (ms) {
        setTimeout(function () {
          try {
            window.etfFitTerminals(rowKey);
          } catch (_) {}
        }, ms);
      });
    }
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
    const url = cfg.wsUrl || '';
    if (!url) {
      try {
        const c = ai.term?.element?.closest?.('.sn-debug-ai-container');
        if (ai.term && c?.isConnected) ai.term.write('\r\n\r\n\x1b[33m[No WS URL configured. Set FA_DEBUG_CONFIG.wsUrl from backend.]\x1b[0m\r\n');
      } catch (_) {}
      return;
    }
    const ws = new WebSocket(url);
    ws.onopen = () => {};
    ws.onmessage = (e) => {
      decodeMsgAsPromise(e.data).then((txt) => {
        try {
          const c = ai.term?.element?.closest?.('.sn-debug-ai-container');
          if (ai.term && c?.isConnected) ai.term.write(txt);
          if (c) scrollTerminalToBottom(c);
        } catch (_) {}
      }).catch(() => {});
    };
    ws.onerror = () => {};
    ws.onclose = () => {
      try {
        const c = ai.term?.element?.closest?.('.sn-debug-ai-container');
        if (ai.term && c?.isConnected) {
          ai.term.write('\r\n\r\n\x1b[33m[Session ended. Click Start Session to reconnect.]\x1b[0m\r\n');
          if (c) scrollTerminalToBottom(c);
        }
      } catch (_) {}
    };
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
          const path = p ? escapeHtml(p) : '';
          return '<div class="upload-history-item" style="display:flex;flex-wrap:wrap;align-items:center;gap:0.5rem;padding:0.4rem 0;font-size:0.8125rem;border-bottom:1px solid var(--color-border);word-break:break-all;">' +
            '<span style="flex-shrink:0;">' + escapeHtml(e.filename) + '</span>' +
            '<span class="text-muted" style="flex-shrink:0;">' + escapeHtml(e.uploaded_at || '') + '</span>' +
            (sn !== '-' ? '<span class="text-muted" style="flex-shrink:0;">SN:' + sn + '</span>' : '') +
            (path ? '<span class="text-muted" style="min-width:0;overflow-wrap:break-word;">' + path + '</span>' : '') +
            '</div>';
        }).join('');
      })
      .catch(() => {});
  };

  window.etfDestroySnTerminal = function(rowKey, type) {
    const panel = snDebugPanels.get(rowKey);
    if (!panel) return;
    if (type === 'ai' && panel.ai) {
      try { panel.ai.ws?.close(); } catch (_) {}
      try { panel.ai.term?.dispose(); } catch (_) {}
      const container = panel.ai.term?.element?.closest?.('.sn-debug-ai-container');
      if (container?._fitObserver) { try { container._fitObserver.disconnect(); } catch (_) {} }
      panel.ai = null;
    }
    if ((type === 'ssh' || type === 'term') && panel.ssh) {
      try { panel.ssh.ws?.close(); } catch (_) {}
      try { panel.ssh.term?.dispose(); } catch (_) {}
      const container = panel.ssh.term?.element?.closest?.('.sn-debug-ssh-container');
      if (container?._fitObserver) { try { container._fitObserver.disconnect(); } catch (_) {} }
      panel.ssh = null;
    }
    if (type === 'bmc' && panel.bmc) {
      try { panel.bmc.ws?.close(); } catch (_) {}
      try { panel.bmc.term?.dispose(); } catch (_) {}
      const container = panel.bmc.term?.element?.closest?.('.sn-debug-bmc-container');
      if (container?._fitObserver) { try { container._fitObserver.disconnect(); } catch (_) {} }
      panel.bmc = null;
    }
    if (type === 'host' && panel.host) {
      try { panel.host.ws?.close(); } catch (_) {}
      try { panel.host.term?.dispose(); } catch (_) {}
      const container = panel.host.term?.element?.closest?.('.sn-debug-host-container');
      if (container?._fitObserver) { try { container._fitObserver.disconnect(); } catch (_) {} }
      panel.host = null;
    }
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
    if (panel.bmc) {
      try { panel.bmc.ws?.close(); } catch (_) {}
      try { panel.bmc.term?.dispose(); } catch (_) {}
      const container = panel.bmc.term?.element?.closest?.('.sn-debug-bmc-container');
      if (container?._fitObserver) { try { container._fitObserver.disconnect(); } catch (_) {} }
    }
    if (panel.host) {
      try { panel.host.ws?.close(); } catch (_) {}
      try { panel.host.term?.dispose(); } catch (_) {}
      const container = panel.host.term?.element?.closest?.('.sn-debug-host-container');
      if (container?._fitObserver) { try { container._fitObserver.disconnect(); } catch (_) {} }
    }
    snDebugPanels.delete(rowKey);
  };

  window.etfFitTerminals = function(rowKey) {
    const panel = snDebugPanels.get(rowKey);
    if (!panel) return;
    [panel.ai, panel.ssh, panel.bmc, panel.host].forEach((x) => {
      const el = x?.term?.element;
      if (x?.fitAddon && el?.isConnected) { try { x.fitAddon.fit(); } catch (_) {} }
    });
  };

  window.etfGetSnPanel = function(rowKey) {
    return snDebugPanels.get(rowKey) || null;
  };

  window.etfSendSshText = function(rowKey, text) {
    const panel = snDebugPanels.get(rowKey);
    if (!panel || !panel.ssh || !panel.ssh.ws) return { ok: false, error: "ssh panel not ready" };
    const ws = panel.ssh.ws;
    if (ws.readyState !== WebSocket.OPEN) return { ok: false, error: "ssh websocket not open" };
    try {
      ws.send(String(text == null ? "" : text));
      return { ok: true };
    } catch (e) {
      return { ok: false, error: e?.message || String(e) };
    }
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
