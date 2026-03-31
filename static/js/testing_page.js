(function () {
    var inputSn = document.getElementById('input-sn');
    var inputEmpTop = document.getElementById('input-emp-top');
    var btnSearch = document.getElementById('btn-search');
    var snError = document.getElementById('sn-error');
    var resultMsg = document.getElementById('result-msg');
    var flowSection = document.getElementById('flow-section');
    var modeHint = document.getElementById('mode-hint');
    var allPassMsg = document.getElementById('all-pass-msg');
    var mainFlowRow = document.getElementById('main-flow-row');
    var repairChainRow = document.getElementById('repair-chain-row');
    var rOnlyWrap = document.getElementById('r-only-wrap');
    var currentActions = document.getElementById('current-actions');
    var currentNodeText = document.getElementById('current-node-text');
    var btnPass = document.getElementById('btn-pass');
    var btnFail = document.getElementById('btn-fail');
    var formSection = document.getElementById('form-section');
    var btnRepair = document.getElementById('btn-repair');
    var selReason = document.getElementById('sel-reason');
    var selAction = document.getElementById('sel-action');
    var selDuty = document.getElementById('sel-duty');
    var inputRemark = document.getElementById('input-remark');
    var treeSection = document.getElementById('tree-section');
    var treeTbody = document.getElementById('tree-tbody');
    var treeDekit = document.getElementById('tree-dekit');
    var treeKitting = document.getElementById('tree-kitting');
    var treeExpandAll = document.getElementById('tree-expand-all');
    var treeCollapseAll = document.getElementById('tree-collapse-all');
    var chkShowDekitted = document.getElementById('chk-show-dekitted');
    var dupBanner = document.getElementById('dup-banner');
    var selectionSummary = document.getElementById('selection-summary');
    var loadingOverlay = document.getElementById('loading-overlay');
    var loadingText = document.getElementById('loading-text');

    var failModal = document.getElementById('fail-modal');
    var failHistoryBody = document.getElementById('fail-history-body');
    var failEcInput = document.getElementById('fail-ec-input');
    var btnValidateEc = document.getElementById('btn-validate-ec');
    var btnUpdateFail = document.getElementById('btn-update-fail');
    var btnFailClose = document.getElementById('btn-fail-close');
    var ecValidMsg = document.getElementById('ec-valid-msg');

    var didoNextSection = document.getElementById('dido-next-section');
    var btnDidoNext = document.getElementById('btn-dido-next');
    var doFormSection = document.getElementById('do-form-section');
    var selDoReason = document.getElementById('sel-do-reason');
    var inputDoReasonDesc = document.getElementById('input-do-reason-desc');
    var inputDoRemark = document.getElementById('input-do-remark');
    var btnDoPass = document.getElementById('btn-do-pass');
    var btnDoFail = document.getElementById('btn-do-fail');
    var roNextWrap = document.getElementById('ro-next-wrap');
    var selRoNextReason = document.getElementById('sel-ro-next-reason');
    var inputRoNextReasonDesc = document.getElementById('input-ro-next-reason-desc');
    var inputRoNextRemark = document.getElementById('input-ro-next-remark');
    var btnRoNext = document.getElementById('btn-ro-next');
    var btnOnlineTest = document.getElementById('btn-online-test');
    var crabberTbody = document.getElementById('crabber-tbody');

    var termRowKey = '';
    var termStopWatch = null;
    var lastTrayRow = null;
    var crabberPollTimer = null;
    var CRABBER_POLL_MS = 60000;

    function stopCrabberPoll() {
      if (crabberPollTimer != null) {
        clearInterval(crabberPollTimer);
        crabberPollTimer = null;
      }
    }
    function crabberHistoryHasProc(tests) {
      if (!tests || !tests.length) return false;
      return tests.some(function (t) {
        return String((t && t.node_log_event) || '').toUpperCase() === 'PROC';
      });
    }
    function scheduleCrabberPollIfNeeded(crabber) {
      stopCrabberPoll();
      var tests = (crabber && crabber.ok && Array.isArray(crabber.tests)) ? crabber.tests : [];
      if (!crabberHistoryHasProc(tests)) return;
      var pollSn = termRowKey;
      crabberPollTimer = setInterval(function () {
        var sn = (inputSn.value || '').trim().toUpperCase();
        if (!sn || sn !== pollSn) {
          stopCrabberPoll();
          return;
        }
        api('/api/debug/testing/overview?sn=' + encodeURIComponent(sn)).then(function (res) {
          if (!res.json || !res.json.ok) {
            stopCrabberPoll();
            return;
          }
          if (termRowKey !== pollSn) {
            stopCrabberPoll();
            return;
          }
          var c = res.json.crabber;
          renderCrabberTable(c);
          var t2 = (c && c.ok && Array.isArray(c.tests)) ? c.tests : [];
          if (!crabberHistoryHasProc(t2)) stopCrabberPoll();
        }).catch(function () {
          stopCrabberPoll();
        });
      }, CRABBER_POLL_MS);
    }

    var options = { reason_codes: [], repair_actions: [], duty_types: [] };
    var debugReasonCodes = [];

    function rcEscAttr(s) {
      return String(s || '').replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;');
    }
    function rcEscHtml(s) {
      return String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }
    /** One <option>: value=code, data-desc=full desc, visible label = code — short desc (xem trước trong dropdown). */
    function reasonOptionHtml(r) {
      var code = String(r.code || '');
      var fullDesc = String(r.desc || '').trim();
      var short = fullDesc.length > 100 ? fullDesc.slice(0, 97) + '…' : fullDesc;
      var label = short ? (rcEscHtml(code) + ' — ' + rcEscHtml(short)) : rcEscHtml(code);
      return '<option value="' + rcEscAttr(code) + '" data-desc="' + rcEscAttr(fullDesc) + '">' + label + '</option>';
    }
    var flowState = null;
    var selectedRTarget = null;
    var ecValidated = false;
    var tree = [];
    var childrenByNum = {};
    var collapsedSet = new Set();
    var savedInputValues = {};
    var selectedRootNum = null;
    var hasInvalidDuplicate = false;
    var requestPending = false;
    var _focusTimer = null;
    var inputTextRuler = document.createElement('span');
    inputTextRuler.style.position = 'absolute';
    inputTextRuler.style.visibility = 'hidden';
    inputTextRuler.style.whiteSpace = 'pre';
    inputTextRuler.style.pointerEvents = 'none';
    document.body.appendChild(inputTextRuler);

    function api(path, opts) {
      var init = Object.assign({ credentials: 'same-origin', headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' } }, opts || {});
      if (init.body && typeof init.body !== 'string') init.body = JSON.stringify(init.body);
      var controller = new AbortController();
      var timeoutMs = (opts && opts.timeout_ms) || 60000;
      init.signal = controller.signal;
      var timer = setTimeout(function () { controller.abort(); }, timeoutMs);
      return fetch(path, init).then(function (r) {
        return r.json().then(function (j) { return { status: r.status, json: j }; }).catch(function (e) {
          throw e;
        });
      }).finally(function () {
        clearTimeout(timer);
      }).catch(function (e) {
        if (e && e.name === 'AbortError') throw new Error('Request timed out');
        throw e;
      });
    }
    function lockUI(msg) {
      requestPending = true;
      loadingText.textContent = msg || 'Processing...';
      loadingOverlay.classList.remove('hidden');
      [btnSearch, btnPass, btnFail, btnRepair, treeDekit, treeKitting, treeExpandAll, treeCollapseAll, btnValidateEc, btnUpdateFail, btnDidoNext, btnDoPass, btnDoFail, btnRoNext, btnOnlineTest].forEach(function (b) {
        if (b) b.disabled = true;
      });
    }
    function unlockUI() {
      requestPending = false;
      loadingOverlay.classList.add('hidden');
      [btnSearch, btnPass, btnFail, btnRepair, treeDekit, treeKitting, treeExpandAll, treeCollapseAll, btnValidateEc, btnUpdateFail, btnDidoNext, btnDoPass, btnDoFail, btnRoNext, btnOnlineTest].forEach(function (b) {
        if (b) b.disabled = false;
      });
      if (hasInvalidDuplicate) {
        treeDekit.disabled = true;
        treeKitting.disabled = true;
        btnRepair.disabled = true;
      }
    }
    function autoSizeInput(inp) {
      if (!inp) return;
      var cs = window.getComputedStyle(inp);
      inputTextRuler.style.font = cs.font;
      inputTextRuler.style.letterSpacing = cs.letterSpacing;
      var val = (inp.value || '');
      // Always keep at least two trailing spaces worth of room.
      inputTextRuler.textContent = val + '  ';
      var textWidth = Math.ceil(inputTextRuler.getBoundingClientRect().width);
      var pl = parseFloat(cs.paddingLeft) || 0;
      var pr = parseFloat(cs.paddingRight) || 0;
      var bl = parseFloat(cs.borderLeftWidth) || 0;
      var br = parseFloat(cs.borderRightWidth) || 0;
      var minPx = 28 * ((parseFloat(cs.fontSize) || 14) * 0.62);
      var w = Math.max(minPx, textWidth + pl + pr + bl + br + 2);
      inp.style.width = w + 'px';
    }
    function showErr(msg) {
      resultMsg.className = 'text-sm msg-error';
      resultMsg.textContent = msg || '';
      resultMsg.classList.toggle('hidden', !msg);
    }
    function showOk(msg) {
      resultMsg.className = 'text-sm msg-ok';
      resultMsg.textContent = msg || '';
      resultMsg.classList.toggle('hidden', !msg);
    }
    function normalizeNodeForMatch(name) {
      if (!name) return '';
      return String(name).trim().toUpperCase().replace(/[\s-]+/g, '_').replace(/_+/g, '_');
    }
    function drawFlow(container, nodes, currentNode) {
      var normalized = normalizeNodeForMatch(currentNode);
      var currentForHighlight = normalized && nodes.indexOf(normalized) >= 0 ? normalized : currentNode;
      container.innerHTML = '';
      for (var i = 0; i < nodes.length; i++) {
        if (i > 0) {
          var arr = document.createElement('span');
          arr.className = 'flow-arrow';
          arr.textContent = '→';
          container.appendChild(arr);
        }
        var n = document.createElement('span');
        n.className = 'flow-node' + (nodes[i] === currentForHighlight ? ' current' : '');
        n.textContent = nodes[i];
        container.appendChild(n);
      }
    }
    function resetView() {
      stopCrabberPoll();
      flowSection.classList.add('hidden');
      formSection.classList.add('hidden');
      didoNextSection.classList.add('hidden');
      doFormSection.classList.add('hidden');
      roNextWrap.classList.add('hidden');
      treeSection.classList.add('hidden');
      mainFlowRow.innerHTML = '';
      repairChainRow.innerHTML = '';
      rOnlyWrap.innerHTML = '';
      treeTbody.innerHTML = '';
      selectedRootNum = null;
      currentActions.classList.add('hidden');
      allPassMsg.classList.add('hidden');
      snError.classList.add('hidden');
      resultMsg.classList.add('hidden');
      if (crabberTbody) {
        crabberTbody.innerHTML = '<tr><td colspan="6" style="color:var(--color-muted)">—</td></tr>';
      }
      ['sum-room', 'sum-pn-tray', 'sum-wip', 'sum-bmc', 'sum-sys', 'sum-tray-msg'].forEach(function (id) {
        var el = document.getElementById(id);
        if (el) el.textContent = '—';
      });
    }
    function stopTermWatch() {
      if (typeof termStopWatch === 'function') termStopWatch();
      termStopWatch = null;
    }
    function renderOverviewPanels(overview) {
      var tray = overview.tray || {};
      var row = tray.row || {};
      var wip = overview.wip || {};
      var w = wip.wip || {};
      var elRoom = document.getElementById('sum-room');
      var elPn = document.getElementById('sum-pn-tray');
      var elWip = document.getElementById('sum-wip');
      var elBmc = document.getElementById('sum-bmc');
      var elSys = document.getElementById('sum-sys');
      var elMsg = document.getElementById('sum-tray-msg');
      if (elRoom) {
        var rm = tray.connected ? (row.room || '') : '';
        elRoom.textContent = rm ? String(rm).toUpperCase() : '—';
      }
      if (elPn) {
        elPn.textContent = (row.pn || '') || (w.MODEL_NAME || '') || '—';
      }
      if (elWip) {
        if (wip.ok) {
          var nextOnly = (w.NEXT_STATION || '').trim();
          elWip.textContent = nextOnly || '—';
        } else {
          elWip.textContent = wip.error || '—';
        }
      }
      if (elBmc) {
        var bmcParts = [row.bmc_mac, row.bmc_ip].filter(function (x) { return x && String(x).trim(); });
        elBmc.textContent = bmcParts.length ? bmcParts.join(' / ') : '—';
      }
      if (elSys) {
        var sysParts = [row.sys_mac, row.sys_ip].filter(function (x) { return x && String(x).trim(); });
        elSys.textContent = sysParts.length ? sysParts.join(' / ') : '—';
      }
      if (elMsg) {
        elMsg.textContent = tray.connected ? '' : (tray.message || 'Không tìm được kết nối đến SN này');
      }
    }
    function formatCrabberCali(iso) {
      var s = (iso && String(iso).trim()) ? String(iso).trim() : '';
      if (!s) return '';
      var d = new Date(s);
      if (isNaN(d.getTime())) return s;
      try {
        return new Intl.DateTimeFormat('en-US', {
          timeZone: 'America/Los_Angeles',
          year: 'numeric',
          month: '2-digit',
          day: '2-digit',
          hour: '2-digit',
          minute: '2-digit',
          second: '2-digit',
          hour12: true,
          timeZoneName: 'short',
        }).format(d);
      } catch (e1) {
        return s;
      }
    }
    function renderCrabberTable(crabber) {
      if (!crabberTbody) return;
      var tests = (crabber && crabber.ok && Array.isArray(crabber.tests)) ? crabber.tests : [];
      if (!tests.length) {
        stopCrabberPoll();
        var err = (crabber && crabber.error) ? crabber.error : 'No Crabber rows (check API or SN).';
        crabberTbody.innerHTML = '<tr><td colspan="6" style="color:var(--color-muted)">' + rcEscHtml(err) + '</td></tr>';
        return;
      }
      crabberTbody.innerHTML = tests.map(function (t) {
        var startIso = (t.log_time && String(t.log_time).trim()) ? t.log_time : (t.test_time || '');
        var startDisp = formatCrabberCali(startIso);
        var endIso = (t.sfc_event_date && String(t.sfc_event_date).trim()) ? String(t.sfc_event_date).trim() : '';
        var endDisp = endIso ? formatCrabberCali(endIso) : '—';
        return '<tr><td>' + rcEscHtml(startDisp) + '</td><td>' + rcEscHtml(endDisp) + '</td><td>' + rcEscHtml(t.station || '') + '</td><td>' + rcEscHtml(t.result || '') + '</td><td>' + rcEscHtml(t.pn || '') + '</td><td>' + rcEscHtml(t.machine || '') + '</td></tr>';
      }).join('');
    }
    function renderTree() {
      if (!tree || !tree.length) {
        treeSection.classList.add('hidden');
        treeTbody.innerHTML = '';
        return;
      }
      treeSection.classList.remove('hidden');
      treeTbody.querySelectorAll('.tree-new-sn').forEach(function (inp) {
        var n = inp.getAttribute('data-num');
        if (n) savedInputValues[n] = inp.value;
      });

      var numToNode = {};
      tree.forEach(function (n) { numToNode[n.num] = n; });
      function hasChildren(num) {
        return childrenByNum[num] && childrenByNum[num].length > 0;
      }
      function isVisible(num) {
        var node = numToNode[num];
        if (!node) return false;
        if ((node.depth || 0) === 0) return true;
        if (collapsedSet.has(node.parent_num)) return false;
        return isVisible(node.parent_num);
      }
      var selectedNums = new Set(getSubtreeNums(selectedRootNum));
      var selectedNodesCount = selectedNums.size;
      if (selectedNodesCount) {
        var rootNode = numToNode[selectedRootNum] || {};
        selectionSummary.textContent = 'Selected: ' + (rootNode.vendor_sn || selectedRootNum) + ' + ' + Math.max(0, selectedNodesCount - 1) + ' children';
      } else {
        selectionSummary.textContent = 'Select a subtree, or enter New SN on any rows (any branches) to kit several parts in one run.';
      }
      var visible = tree.filter(function (node) { return isVisible(node.num); });
      if (!chkShowDekitted.checked) {
        visible = visible.filter(function (node) { return String(node.assy_flag || '').toUpperCase() !== 'N'; });
      }
      visible.sort(function (a, b) { return (a.num || 0) - (b.num || 0); });

      var LINE_W = 22;
      var BAR_W = 11;
      treeTbody.innerHTML = visible.map(function (node) {
        var esc = function (s) { return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); };
        var copyBtn = function (text) { return '<button type="button" class="tree-copy-btn" data-copy="' + esc(text) + '">Copy</button>'; };
        var rowClass = node.assy_flag === 'N' ? 'tree-row-flag-n' : 'tree-row-flag-y';
        if (selectedNums.has(node.num)) rowClass += ' tree-row-selected';
        if (node.num === selectedRootNum) rowClass += ' tree-row-selected-root';
        var depth = node.depth || 0;
        var shadows = [];
        for (var k = 0; k < depth; k++) {
          var pos = BAR_W + k * LINE_W;
          shadows.push('inset ' + pos + 'px 0 0 ' + (2 - pos) + 'px var(--color-border)');
        }
        var numCellStyle = 'padding-left:' + (8 + depth * LINE_W) + 'px;';
        if (shadows.length) numCellStyle += 'box-shadow:' + shadows.join(',') + ';';
        var hbarStyle = depth > 0 ? ('left:' + ((depth - 1) * LINE_W) + 'px;width:' + BAR_W + 'px;') : '';
        var hbarHtml = depth > 0 ? '<span class="tree-hbar" style="' + hbarStyle + '"></span>' : '';
        var toggleHtml = hasChildren(node.num)
          ? '<span class="tree-toggle" data-num="' + node.num + '">' + (collapsedSet.has(node.num) ? '&#9654;' : '&#9660;') + '</span>'
          : '<span class="tree-toggle" style="visibility:hidden">&#9660;</span>';
        return '<tr class="' + rowClass + '" data-num="' + node.num + '" data-vendor-sn="' + (node.vendor_sn || '') + '" data-father-sn="' + (node.father_sn != null ? node.father_sn : '') + '" data-parent-num="' + (node.parent_num != null ? node.parent_num : '') + '">' +
          '<td class="tree-td-num py-1 pr-2" style="' + numCellStyle + '">' + toggleHtml + hbarHtml + (node.num || '') + '<span class="flag-badge ' + (String(node.assy_flag || '').toUpperCase() === 'N' ? 'flag-n' : 'flag-y') + '">' + (String(node.assy_flag || '').toUpperCase() || 'Y') + '</span></td>' +
          '<td class="py-1 pr-2">' + esc(node.sub_model_name || '') + '</td>' +
          '<td class="py-1 pr-2">' + esc(node.model_name || '') + '</td>' +
          '<td class="py-1 pr-2 tree-copy-cell"><span>' + (node.father_sn || '') + '</span>' + copyBtn(node.father_sn || '') + '</td>' +
          '<td class="py-1 pr-2 tree-copy-cell"><span>' + (node.vendor_sn || '') + '</span>' + copyBtn(node.vendor_sn || '') + '</td>' +
          '<td class="py-1"><input type="text" class="tree-new-sn tree-new-sn-input ' + (selectedNums.has(node.num) ? 'in-scope' : 'out-scope') + '" data-num="' + node.num + '" data-parent-num="' + (node.parent_num != null ? node.parent_num : '') + '" placeholder="' + (selectedNums.has(node.num) ? 'Required - enter new SN' : 'New SN') + '"></td>' +
          '<td class="py-1 pr-2">' + (node.stack || '') + '</td>' +
          '<td class="py-1 pr-2">' + (node.in_station_time || '') + '</td>' +
          '</tr>';
      }).join('');

      Object.keys(savedInputValues).forEach(function (n) {
        var inp = treeTbody.querySelector('.tree-new-sn[data-num="' + n + '"]');
        if (inp) {
          inp.value = savedInputValues[n];
          autoSizeInput(inp);
        }
      });
    }
    function loadTree(sn) {
      return api('/api/debug/repair/assy-tree?sn=' + encodeURIComponent(sn)).then(function (res) {
        if (res.json && !res.json.ok && res.json.error) {
          showErr('Tree: ' + res.json.error);
        }
        tree = (res.json && res.json.ok) ? (res.json.tree || []) : [];
        var invalid = (res.json && res.json.invalid_duplicates) ? res.json.invalid_duplicates : [];
        hasInvalidDuplicate = invalid.length > 0;
        if (hasInvalidDuplicate) {
          dupBanner.textContent = 'WARNING: Duplicate vendor SN detected (ASSY_FLAG=Y, non-CONFIG): ' + invalid.join(', ') + '. Please contact IT to fix data via IT Kitting page before proceeding.';
          dupBanner.classList.remove('hidden');
          treeDekit.disabled = true;
          treeKitting.disabled = true;
          btnRepair.disabled = true;
        } else {
          dupBanner.classList.add('hidden');
        }
        childrenByNum = {};
        tree.forEach(function (n) {
          if (n.parent_num != null) {
            if (!childrenByNum[n.parent_num]) childrenByNum[n.parent_num] = [];
            childrenByNum[n.parent_num].push(n.num);
          }
        });
        collapsedSet = new Set();
        Object.keys(childrenByNum).forEach(function (n) { collapsedSet.add(parseInt(n, 10)); });
        savedInputValues = {};
        selectedRootNum = null;
        renderTree();
      }).catch(function () {
        tree = [];
        childrenByNum = {};
        collapsedSet = new Set();
        savedInputValues = {};
        selectedRootNum = null;
        hasInvalidDuplicate = false;
        dupBanner.classList.add('hidden');
        renderTree();
      });
    }
    function getSubtreeNums(rootNum) {
      if (!rootNum) return [];
      var out = [];
      var q = [rootNum];
      var seen = new Set();
      while (q.length) {
        var n = q.shift();
        if (seen.has(n)) continue;
        seen.add(n);
        out.push(n);
        (childrenByNum[n] || []).forEach(function (c) { q.push(c); });
      }
      return out;
    }
    function buildKitList(requireSelection) {
      var list = [];
      var byNum = {};
      tree.forEach(function (n) { byNum[n.num] = n; });
      var subtreeNums = getSubtreeNums(selectedRootNum);
      var newByNum = {};
      var candidateNumsSet = new Set();
      var filledOutsideSubtree = false;

      function getNewSnForNum(num) {
        var inp = treeTbody.querySelector('.tree-new-sn[data-num="' + num + '"]');
        return inp ? (inp.value || '').trim() : (savedInputValues[String(num)] || '').trim();
      }

      // Cross-branch: any row with New SN in the tree is included in the kit batch.
      tree.forEach(function (n) {
        var v = getNewSnForNum(n.num);
        if (v) {
          newByNum[n.num] = v;
          candidateNumsSet.add(n.num);
        }
      });
      if (selectedRootNum) {
        var subtreeNumsSet = new Set(subtreeNums);
        tree.forEach(function (n) {
          var v = getNewSnForNum(n.num);
          if (v && !subtreeNumsSet.has(n.num)) filledOutsideSubtree = true;
        });
        // If user typed New SN outside the highlighted subtree, kit only filled rows (multi-branch). Otherwise keep "whole subtree must be filled" behavior.
        if (!filledOutsideSubtree) {
          subtreeNums.forEach(function (num) {
            candidateNumsSet.add(num);
            var v = getNewSnForNum(num);
            if (v) newByNum[num] = v;
          });
        }
      }

      if (requireSelection) {
        if (!selectedRootNum && candidateNumsSet.size === 0) {
          return { error: 'Enter New SN for at least one part (any row), or select a subtree to kit.' };
        }
        if (selectedRootNum && !subtreeNums.length) {
          return { error: 'Please select one row to continue.' };
        }
      } else {
        if (!selectedRootNum && candidateNumsSet.size === 0) {
          return { list: [] };
        }
      }

      // Walk upward from each candidate; include ancestors that have a filled New SN (parent chain).
      Array.from(candidateNumsSet).forEach(function (num) {
        var n = byNum[num];
        while (n && n.parent_num != null && byNum[n.parent_num]) {
          var p = n.parent_num;
          var pv = getNewSnForNum(p);
          if (pv) {
            candidateNumsSet.add(p);
            newByNum[p] = pv;
          }
          n = byNum[p];
        }
      });

      if (selectedRootNum && !filledOutsideSubtree) {
        for (var j = 0; j < subtreeNums.length; j++) {
          if (!newByNum[subtreeNums[j]]) {
            return { error: 'Please enter New SN for all nodes in the selected subtree.' };
          }
        }
      }

      var candidateNums = Array.from(candidateNumsSet);
      for (var i = 0; i < candidateNums.length; i++) {
        var num = candidateNums[i];
        if (!newByNum[num]) {
          return { error: 'Please enter New SN for every part included in this kit batch.' };
        }
      }

      candidateNums.sort(function (a, b) { return a - b; });
      candidateNums.forEach(function (num) {
        var n = byNum[num];
        if (!n) return;
        var newSn = newByNum[n.num];
        if (!newSn) return;
        var parentNum = n.parent_num;
        var newFather = null;
        if (parentNum != null && byNum[parentNum]) {
          if (newByNum[parentNum]) newFather = newByNum[parentNum];
          else newFather = n.father_sn || null;
        }
        list.push({
          old_vendor_sn: n.vendor_sn,
          old_father_sn: n.father_sn,
          new_vendor_sn: newSn,
          new_father_sn: newFather
        });
      });
      return { list: list };
    }
    function renderRBranches(targets) {
      rOnlyWrap.classList.remove('hidden');
      rOnlyWrap.innerHTML = '';
      var rc500Placed = false;
      var rc36Placed = false;
      (targets || []).forEach(function (item, idx) {
        var row = document.createElement('div');
        row.className = 'flow-branch';
        var left = document.createElement('span');
        left.className = 'flow-node';
        left.textContent = item.from;
        var arr = document.createElement('span');
        arr.className = 'flow-arrow';
        arr.textContent = '→';
        var right = document.createElement('button');
        right.type = 'button';
        right.className = 'flow-node';
        right.textContent = item.to;
        right.addEventListener('click', function () { selectedRTarget = item.to; showOk('Selected target: ' + item.to); });
        row.appendChild(left); row.appendChild(arr); row.appendChild(right);
        var fromName = (item.from || '').toUpperCase();
        var toName = (item.to || '').toUpperCase();
        if (!rc500Placed && fromName === 'R_FLB' && toName === 'FLB') {
          var rc500Btn = document.createElement('button');
          rc500Btn.id = 'btn-rc500';
          rc500Btn.className = 'btn-warning-like';
          rc500Btn.type = 'button';
          rc500Btn.textContent = 'RC500';
          row.appendChild(rc500Btn);
          rc500Placed = true;
        }
        if (!rc36Placed && fromName === 'R_FLB' && toName === 'FLA') {
          var rc36Btn = document.createElement('button');
          rc36Btn.id = 'btn-rc36';
          rc36Btn.className = 'btn-warning-like';
          rc36Btn.type = 'button';
          rc36Btn.textContent = 'RC36';
          row.appendChild(rc36Btn);
          rc36Placed = true;
        }
        if (idx === 0 && !selectedRTarget) selectedRTarget = item.to;
        rOnlyWrap.appendChild(row);
      });
      if (!rc500Placed) {
        var topRow = document.createElement('div');
        topRow.className = 'mt-2';
        topRow.innerHTML = '<button id="btn-rc500" class="btn-warning-like" type="button">RC500</button>';
        rOnlyWrap.appendChild(topRow);
      }
      if (!rc36Placed) {
        var rc36Row = document.createElement('div');
        rc36Row.className = 'mt-2';
        rc36Row.innerHTML = '<button id="btn-rc36" class="btn-warning-like" type="button">RC36</button>';
        rOnlyWrap.appendChild(rc36Row);
      }
      var rc500El = document.getElementById('btn-rc500');
      var rc36El = document.getElementById('btn-rc36');
      if (rc500El) rc500El.addEventListener('click', onRc500);
      if (rc36El) rc36El.addEventListener('click', onRc36);
    }
    function renderFlowState() {
      if (!flowState || !flowState.ok) return;
      var data = flowState;
      var wip = data.wip || {};
      var current = (wip.NEXT_STATION || '').trim() || (wip.GROUP_NAME || '').trim();
      flowSection.classList.remove('hidden');
      currentNodeText.textContent = current || '-';
      modeHint.textContent = 'Mode: ' + (data.ui_mode || 'main_line');
      allPassMsg.classList.toggle('hidden', !data.all_pass);
      mainFlowRow.classList.add('hidden');
      repairChainRow.classList.add('hidden');
      rOnlyWrap.classList.add('hidden');
      currentActions.classList.add('hidden');
      formSection.classList.add('hidden');

      if (data.ui_mode === 'main_line') {
        var nodes = (data.segment_main && data.segment_main.length) ? data.segment_main : (data.groups_ordered || []);
        mainFlowRow.classList.remove('hidden');
        drawFlow(mainFlowRow, nodes, current);
        currentActions.classList.remove('hidden');
      } else if (data.ui_mode === 'repair_dido') {
        repairChainRow.classList.remove('hidden');
        drawFlow(repairChainRow, data.repair_chain_nodes || [], current);
        var didoStation = (data.current_dido_station || '').toUpperCase();
        var base = (data.base || '').trim();
        didoNextSection.classList.add('hidden');
        doFormSection.classList.add('hidden');
        formSection.classList.add('hidden');
        roNextWrap.classList.add('hidden');
        if (didoStation === 'DI' || didoStation === 'RI') {
          didoNextSection.classList.remove('hidden');
          btnDidoNext.dataset.station = didoStation;
          btnDidoNext.dataset.base = base;
        } else if (didoStation === 'DO') {
          doFormSection.classList.remove('hidden');
          loadDebugReasonCodes().then(function () {
            selDoReason.innerHTML = '<option value="" data-desc="">-- Select --</option>' + (debugReasonCodes || []).map(reasonOptionHtml).join('');
            selDoReason.dataset.base = base;
            selDoReason.value = '';
            inputDoReasonDesc.value = '';
            inputDoRemark.value = '';
          });
        } else if (didoStation === 'RO') {
          formSection.classList.remove('hidden');
          roNextWrap.classList.remove('hidden');
          loadDebugReasonCodes().then(function () {
            selRoNextReason.innerHTML = '<option value="" data-desc="">-- Select reason --</option>' + (debugReasonCodes || []).map(reasonOptionHtml).join('');
            selRoNextReason.dataset.base = base;
            selRoNextReason.value = '';
            if (inputRoNextReasonDesc) inputRoNextReasonDesc.value = '';
          });
        } else {
          formSection.classList.remove('hidden');
        }
      } else if (data.ui_mode === 'repair_r_only') {
        renderRBranches(data.r_only_targets || []);
        formSection.classList.remove('hidden');
      }
    }
    function loadDebugReasonCodes() {
      return api('/api/debug/repair/debug-reason-codes').then(function (res) {
        if (res.json && res.json.ok) debugReasonCodes = res.json.reason_codes || [];
        else debugReasonCodes = [];
        return debugReasonCodes;
      }).catch(function () { debugReasonCodes = []; return []; });
    }
    function loadOptions() {
      return api('/api/debug/repair/options').then(function (res) {
        if (!res.json.ok) return;
        options = res.json;
        selReason.innerHTML = (options.reason_codes || []).map(function (r) { return '<option value="' + (r.code || r) + '">' + (r.label || r.code || r) + '</option>'; }).join('');
        selAction.innerHTML = (options.repair_actions || []).map(function (a) { return '<option value="' + a + '">' + a + '</option>'; }).join('');
        selDuty.innerHTML = (options.duty_types || []).map(function (d) { return '<option value="' + d + '">' + d + '</option>'; }).join('');
        selReason.value = 'RC500';
        if ((options.repair_actions || []).indexOf('RETEST') >= 0) selAction.value = 'RETEST';
        if ((options.duty_types || []).indexOf('TEST FIXTURE') >= 0) selDuty.value = 'TEST FIXTURE';
      });
    }
    function doSearch() {
      if (requestPending) return;
      resetView();
      var sn = (inputSn.value || '').trim();
      if (!sn) { snError.textContent = 'Enter SN'; snError.classList.remove('hidden'); return; }
      lockUI('Loading data...');
      stopTermWatch();
      var prevKey = termRowKey;
      termRowKey = sn.toUpperCase();
      if (prevKey && prevKey !== termRowKey && typeof window.etfCloseSnPanel === 'function') {
        try { window.etfCloseSnPanel(prevKey); } catch (e1) {}
      }
      var ovUrl = '/api/debug/testing/overview?sn=' + encodeURIComponent(sn);
      var fsUrl = '/api/debug/repair/flow-state?sn=' + encodeURIComponent(sn);
      Promise.all([api(ovUrl).catch(function () { return { json: { ok: false } }; }), api(fsUrl)])
        .then(function (pair) {
          var ovRes = pair[0];
          var fsRes = pair[1];
          if (ovRes.json && ovRes.json.ok) {
            renderOverviewPanels(ovRes.json);
            renderCrabberTable(ovRes.json.crabber);
            scheduleCrabberPollIfNeeded(ovRes.json.crabber);
            lastTrayRow = (ovRes.json.tray && ovRes.json.tray.row) ? ovRes.json.tray.row : null;
            var els = {
              ai: document.getElementById('term-ai'),
              ssh: document.getElementById('term-ssh'),
              bmc: document.getElementById('term-bmc'),
              host: document.getElementById('term-host'),
            };
            if (window.etfTerminalHelpers) {
              window.etfTerminalHelpers.openFourTerminals(sn, termRowKey, lastTrayRow || {}, els);
              termStopWatch = window.etfTerminalHelpers.watchClosedSshAndReconnect(termRowKey, sn, lastTrayRow || {}, els);
            }
          } else {
            stopCrabberPoll();
            renderCrabberTable({ ok: false, tests: [], error: 'Overview failed' });
          }
          flowState = fsRes.json;
          if (!fsRes.json.ok) {
            snError.textContent = fsRes.json.error || 'Search failed';
            snError.classList.remove('hidden');
            return loadTree(sn);
          }
          renderFlowState();
          return loadTree(sn);
        })
        .catch(function () {
          snError.textContent = 'Request failed';
          snError.classList.remove('hidden');
        })
        .finally(function () {
          unlockUI();
        });
    }
    function onPass() {
      if (requestPending) return;
      if (!flowState || !flowState.wip) return;
      var sn = (inputSn.value || '').trim();
      var target = ((flowState.wip || {}).NEXT_STATION || '').trim();
      if (!target) { showErr('NEXT_STATION is empty'); return; }
      lockUI('Passing current station...');
      api('/api/debug/repair/pass-jump', {
        method: 'POST',
        body: { sn: sn, target_group: target, emp_no: (inputEmpTop.value || 'SJOP').trim() || 'SJOP' }
      }).then(function (res) {
        if (!res.json.ok) { showErr(res.json.error || 'Pass jump failed'); return; }
        showOk('Jump completed.');
        unlockUI();
        doSearch();
      }).catch(function (e) { showErr(e && e.message ? e.message : 'Request failed'); }).finally(function () { unlockUI(); });
    }
    function openFailModal() {
      if (!flowState || !flowState.wip) return;
      var sn = (inputSn.value || '').trim();
      ecValidated = false;
      ecValidMsg.textContent = '';
      failEcInput.value = '';
      failHistoryBody.innerHTML = '<tr><td colspan="7">Loading...</td></tr>';
      failModal.classList.remove('hidden');
      api('/api/debug/repair/fail-history?sn=' + encodeURIComponent(sn)).then(function (res) {
        if (!res.json.ok) { failHistoryBody.innerHTML = '<tr><td colspan="7">Error</td></tr>'; return; }
        var rows = res.json.rows || [];
        failHistoryBody.innerHTML = rows.map(function (r, idx) {
          var ec = (r.ERROR_CODE_MASTER || r.ERROR_CODE_IN_REPAIR || '');
          return '<tr><td>' + (r.TEST_TIME_CALI || '') + '</td><td>' + (r.REPAIR_TIME_CALI || '') + '</td><td>' + (r.GROUP_NAME || '') + '</td><td>' + (r.RECORD_TYPE || '') + '</td><td>' + (ec || '') + '</td><td>' + (r.ERROR_DESC || '') + '</td><td><button type="button" data-idx="' + idx + '" class="pick-ec px-2 py-1 rounded border border-[var(--color-border)]">Pick</button></td></tr>';
        }).join('') || '<tr><td colspan="7">No history</td></tr>';
        failHistoryBody.querySelectorAll('.pick-ec').forEach(function (btn) {
          btn.addEventListener('click', function () {
            var idx = parseInt(this.getAttribute('data-idx'), 10);
            var r = rows[idx] || {};
            failEcInput.value = (r.ERROR_CODE_MASTER || r.ERROR_CODE_IN_REPAIR || '').trim();
            ecValidated = false;
            ecValidMsg.textContent = '';
          });
        });
      });
    }
    function validateEc() {
      var ec = (failEcInput.value || '').trim();
      if (!ec) { showErr('Please enter an error code.'); return; }
      api('/api/debug/repair/validate-error-code', { method: 'POST', body: { error_code: ec } }).then(function (res) {
        if (!res.json.ok) { ecValidated = false; ecValidMsg.textContent = res.json.error || 'Validate failed'; ecValidMsg.className = 'text-sm msg-error'; return; }
        ecValidated = res.json.valid === true;
        ecValidMsg.textContent = ecValidated ? 'Error code is valid.' : 'Error code is invalid.';
        ecValidMsg.className = 'text-sm ' + (ecValidated ? 'ec-valid' : 'msg-error');
      });
    }
    function updateFail() {
      if (requestPending) return;
      var sn = (inputSn.value || '').trim();
      var ec = (failEcInput.value || '').trim();
      if (!ecValidated) { showErr('Please validate the error code first.'); return; }
      lockUI('Updating fail...');
      api('/api/debug/repair/fail-input', {
        method: 'POST',
        body: { sn: sn, error_code: ec, emp: (inputEmpTop.value || 'SJOP').trim() || 'SJOP' }
      }).then(function (res) {
        if (!res.json.ok) { showErr(res.json.error || 'Update fail failed'); return; }
        failModal.classList.add('hidden');
        showOk('Fail update completed.');
        unlockUI();
        doSearch();
      }).catch(function (e) { showErr(e && e.message ? e.message : 'Request failed'); }).finally(function () { unlockUI(); });
    }
    function doRepair(desiredTarget) {
      if (requestPending) return;
      var sn = (inputSn.value || '').trim();
      var emp = (inputEmpTop.value || 'SJOP').trim() || 'SJOP';
      if (!sn) { showErr('Search SN first'); return; }
      if (hasInvalidDuplicate) { showErr('Duplicate vendor SN data is invalid. Please fix via IT Kitting first.'); return; }
      if (!selReason.value || !selAction.value || !selDuty.value) { showErr('Please fill Reason/Action/Duty.'); return; }
      var kitBuilt = buildKitList(false);
      if (kitBuilt.error) { showErr(kitBuilt.error); return; }
      lockUI('Executing repair...');
      var requestId = (window.crypto && window.crypto.randomUUID) ? window.crypto.randomUUID() : String(Date.now());
      api('/api/debug/repair/execute', {
        method: 'POST',
        body: {
          action: 'repair',
          sn: sn,
          emp: emp,
          reason_code: selReason.value,
          repair_action: selAction.value,
          duty_station: selDuty.value,
          remark: inputRemark.value || '',
          kit_list: kitBuilt.list,
          desired_target: desiredTarget || '',
          request_id: requestId
        }
      }).then(function (res) {
        if (!res.json.ok) { showErr(res.json.error || 'Repair failed'); return; }
        showOk(res.json.message || 'Repair successful');
        unlockUI();
        doSearch();
      }).catch(function (e) {
        showErr(e && e.message ? e.message : 'Request failed');
      }).finally(function () {
        unlockUI();
      });
    }
    function doKitting(forceContinue, forceDekitOtherTray) {
      if (requestPending) return;
      if (typeof forceContinue !== 'boolean') forceContinue = false;
      if (typeof forceDekitOtherTray !== 'boolean') forceDekitOtherTray = false;
      var sn = (inputSn.value || '').trim();
      var emp = (inputEmpTop.value || 'SJOP').trim() || 'SJOP';
      if (!sn) { showErr('Search SN first.'); return; }
      if (hasInvalidDuplicate) { showErr('Duplicate vendor SN data is invalid. Please fix via IT Kitting first.'); return; }
      var kitBuilt = buildKitList(true);
      if (kitBuilt.error) { showErr(kitBuilt.error); return; }
      if (!confirm('Kit ' + kitBuilt.list.length + ' node(s)? This will dekit old and insert new.')) return;
      lockUI('Executing kitting...');
      var requestId = (window.crypto && window.crypto.randomUUID) ? window.crypto.randomUUID() : String(Date.now());
      api('/api/debug/repair/execute', {
        method: 'POST',
        body: {
          action: 'kitting',
          sn: sn,
          emp: emp,
          kit_list: kitBuilt.list,
          force_continue: forceContinue,
          force_dekit_other_tray: forceDekitOtherTray,
          request_id: requestId
        }
      }).then(function (res) {
        if (!res.json.ok && res.json.cross_tray_conflict) {
          var conflicts = res.json.conflicts || [];
          var lines = conflicts.map(function (c) {
            var childInfo = (c.child_count > 0)
              ? ' (+ ' + c.child_count + ' children will be dekitted)'
              : '';
            return '  - ' + c.vendor_sn + ' -> Tray ' + c.tray_sn + childInfo;
          });
          var msg = 'The following Vendor SN(s) are already kitted in other tray(s):\n\n'
            + lines.join('\n')
            + '\n\nContinue? System will dekit them (including all children) from those trays first.';
          if (confirm(msg)) {
            unlockUI();
            return doKitting(forceContinue, true);
          }
          showErr('Kitting cancelled.');
          return;
        }
        if (!res.json.ok && res.json.qa_locked) {
          var locked = (res.json.locked_sns || []).join(', ');
          if (confirm('QA lock detected for: ' + locked + '. Force continue?')) {
            unlockUI();
            return doKitting(true, forceDekitOtherTray);
          }
          showErr(res.json.error || 'Kitting blocked by QA lock');
          return;
        }
        if (!res.json.ok) { showErr(res.json.error || 'Kitting failed'); return; }
        showOk(res.json.message || 'Kitting successful');
        unlockUI();
        doSearch();
      }).catch(function (e) { showErr(e && e.message ? e.message : 'Request failed'); }).finally(function () { unlockUI(); });
    }
    function doDekit() {
      if (requestPending) return;
      var sn = (inputSn.value || '').trim();
      var emp = (inputEmpTop.value || 'SJOP').trim() || 'SJOP';
      var subtreeNums = getSubtreeNums(selectedRootNum);
      if (!sn) { showErr('Search SN first.'); return; }
      if (!subtreeNums.length) { showErr('Please select one row for dekit.'); return; }
      if (!confirm('Dekit ' + subtreeNums.length + ' node(s)? This will set ASSY_FLAG=N.')) return;
      var byNum = {};
      tree.forEach(function (n) { byNum[n.num] = n; });
      var keys = subtreeNums.sort(function (a, b) { return a - b; }).map(function (num) {
        var n = byNum[num];
        return { vendor_sn: n.vendor_sn, father_sn: n.father_sn };
      });
      lockUI('Executing dekit...');
      var requestId = (window.crypto && window.crypto.randomUUID) ? window.crypto.randomUUID() : String(Date.now());
      api('/api/debug/repair/execute', {
        method: 'POST',
        body: {
          action: 'dekit',
          sn: sn,
          emp: emp,
          dekit_keys: keys,
          request_id: requestId
        }
      }).then(function (res) {
        if (!res.json.ok) { showErr(res.json.error || 'Dekit failed'); return; }
        showOk(res.json.message || 'Dekit successful');
        unlockUI();
        doSearch();
      }).catch(function (e) { showErr(e && e.message ? e.message : 'Request failed'); }).finally(function () { unlockUI(); });
    }
    function onRc500() {
      if (!confirm('Confirm RC500 and move station?')) return;
      selReason.value = 'RC500';
      if ((options.repair_actions || []).indexOf('RETEST') >= 0) selAction.value = 'RETEST';
      if ((options.duty_types || []).indexOf('TEST FIXTURE') >= 0) selDuty.value = 'TEST FIXTURE';
      inputRemark.value = 'Retest';
      doRepair('FLB');
    }
    function onRc36() {
      if (!confirm('Confirm RC36 and move station back to FLA?')) return;
      selReason.value = 'RC36';
      if ((options.repair_actions || []).indexOf('RETEST') >= 0) selAction.value = 'RETEST';
      if ((options.duty_types || []).indexOf('TEST FIXTURE') >= 0) selDuty.value = 'TEST FIXTURE';
      inputRemark.value = 'RC36 return to FLA';
      doRepair('FLA');
    }

    function onDidoNext() {
      if (requestPending) return;
      var sn = (inputSn.value || '').trim();
      var base = (btnDidoNext.dataset.base || '').trim();
      var station = (btnDidoNext.dataset.station || '').toUpperCase();
      if (!sn || !base) { showErr('Missing SN or base.'); return; }
      var endpoint = station === 'DI' ? '/api/debug/repair/di-next' : '/api/debug/repair/ri-next';
      lockUI('Moving to next station...');
      api(endpoint, { method: 'POST', body: { sn: sn, base: base, emp_no: (inputEmpTop.value || 'SJOP').trim() || 'SJOP' } }).then(function (res) {
        if (!res.json.ok) { showErr(res.json.error || 'Next failed'); return; }
        showOk('Moved to next station.');
        unlockUI();
        doSearch();
      }).catch(function (e) { showErr(e && e.message ? e.message : 'Request failed'); }).finally(function () { unlockUI(); });
    }
    function onDoPass() {
      if (requestPending) return;
      var sn = (inputSn.value || '').trim();
      var base = (selDoReason.dataset.base || '').trim();
      var reasonCode = (selDoReason.value || '').trim();
      if (!sn || !base || !reasonCode) { showErr('Please select a reason code.'); return; }
      lockUI('DO Pass...');
      api('/api/debug/repair/do-pass', {
        method: 'POST',
        body: { sn: sn, base: base, reason_code: reasonCode, remark: (inputDoRemark.value || '').trim(), emp: (inputEmpTop.value || 'SJOP').trim() || 'SJOP' }
      }).then(function (res) {
        if (!res.json.ok) { showErr(res.json.error || 'DO Pass failed'); return; }
        showOk('DO Pass completed.');
        unlockUI();
        doSearch();
      }).catch(function (e) { showErr(e && e.message ? e.message : 'Request failed'); }).finally(function () { unlockUI(); });
    }
    function onDoFail() {
      if (requestPending) return;
      var sn = (inputSn.value || '').trim();
      var base = (selDoReason.dataset.base || '').trim();
      var reasonCode = (selDoReason.value || '').trim();
      if (!sn || !base || !reasonCode) { showErr('Please select a reason code.'); return; }
      lockUI('DO Fail...');
      api('/api/debug/repair/do-fail', {
        method: 'POST',
        body: { sn: sn, base: base, reason_code: reasonCode, emp: (inputEmpTop.value || 'SJOP').trim() || 'SJOP' }
      }).then(function (res) {
        if (!res.json.ok) { showErr(res.json.error || 'DO Fail failed'); return; }
        showOk('DO Fail completed.');
        unlockUI();
        doSearch();
      }).catch(function (e) { showErr(e && e.message ? e.message : 'Request failed'); }).finally(function () { unlockUI(); });
    }
    function onRoNext() {
      if (requestPending) return;
      var sn = (inputSn.value || '').trim();
      var base = (selRoNextReason.dataset.base || '').trim();
      var reasonCode = (selRoNextReason.value || '').trim();
      if (!sn || !base || !reasonCode) { showErr('Please select a reason code for RO Next.'); return; }
      lockUI('RO Next...');
      api('/api/debug/repair/ro-next', {
        method: 'POST',
        body: { sn: sn, base: base, reason_code: reasonCode, remark: (inputRoNextRemark.value || '').trim(), emp: (inputEmpTop.value || 'SJOP').trim() || 'SJOP' }
      }).then(function (res) {
        if (!res.json.ok) { showErr(res.json.error || 'RO Next failed'); return; }
        showOk('RO Next completed.');
        unlockUI();
        doSearch();
      }).catch(function (e) { showErr(e && e.message ? e.message : 'Request failed'); }).finally(function () { unlockUI(); });
    }

    function syncReasonDescFromSelect(sel, inputEl) {
      if (!inputEl) return;
      var opt = sel.options[sel.selectedIndex];
      inputEl.value = opt && opt.getAttribute ? (opt.getAttribute('data-desc') || '') : '';
    }
    selDoReason.addEventListener('change', function () { syncReasonDescFromSelect(selDoReason, inputDoReasonDesc); });
    selDoReason.addEventListener('input', function () { syncReasonDescFromSelect(selDoReason, inputDoReasonDesc); });
    selRoNextReason.addEventListener('change', function () { syncReasonDescFromSelect(selRoNextReason, inputRoNextReasonDesc); });
    selRoNextReason.addEventListener('input', function () { syncReasonDescFromSelect(selRoNextReason, inputRoNextReasonDesc); });

    btnSearch.addEventListener('click', doSearch);
    inputSn.addEventListener('keydown', function (e) { if (e.key === 'Enter') { e.preventDefault(); if (!requestPending) doSearch(); } });
    btnPass.addEventListener('click', onPass);
    btnFail.addEventListener('click', openFailModal);
    btnRepair.addEventListener('click', function () { doRepair(selectedRTarget || ''); });
    btnDidoNext.addEventListener('click', onDidoNext);
    btnDoPass.addEventListener('click', onDoPass);
    btnDoFail.addEventListener('click', onDoFail);
    btnRoNext.addEventListener('click', onRoNext);
    treeDekit.addEventListener('click', doDekit);
    treeKitting.addEventListener('click', function () { doKitting(false, false); });
    btnValidateEc.addEventListener('click', validateEc);
    btnUpdateFail.addEventListener('click', updateFail);
    btnFailClose.addEventListener('click', function () { failModal.classList.add('hidden'); });
    treeTbody.addEventListener('click', function (e) {
      var copyBtn = e.target.closest('.tree-copy-btn');
      if (copyBtn) {
        e.preventDefault();
        e.stopPropagation();
        var text = copyBtn.getAttribute('data-copy') || '';
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(text).then(function () { showOk('Copied'); }, function () { showErr('Copy failed'); });
        } else {
          try {
            var ta = document.createElement('textarea');
            ta.value = text;
            ta.style.position = 'fixed';
            ta.style.left = '-9999px';
            document.body.appendChild(ta);
            ta.select();
            document.execCommand('copy');
            document.body.removeChild(ta);
            showOk('Copied');
          } catch (err) {
            showErr('Copy failed');
          }
        }
        return;
      }
      if (e.target.closest('.tree-new-sn-input')) return;
      var tg = e.target.closest('.tree-toggle[data-num]');
      if (tg) {
        var num = parseInt(tg.getAttribute('data-num'), 10);
        if (collapsedSet.has(num)) collapsedSet.delete(num);
        else collapsedSet.add(num);
        renderTree();
        return;
      }
      var tr = e.target.closest('tr[data-num]');
      if (!tr) return;
      if (_focusTimer) { clearTimeout(_focusTimer); _focusTimer = null; }
      selectedRootNum = parseInt(tr.getAttribute('data-num'), 10);
      renderTree();
    });
    treeTbody.addEventListener('input', function (e) {
      var inp = e.target.closest('.tree-new-sn-input');
      if (!inp) return;
      autoSizeInput(inp);
    });
    treeTbody.addEventListener('focusin', function (e) {
      var inp = e.target.closest('.tree-new-sn-input');
      if (!inp) return;
      var num = inp.getAttribute('data-num');
      if (!num) return;
      var newRoot = parseInt(num, 10);
      if (selectedRootNum === newRoot) return;
      selectedRootNum = newRoot;
      renderTree();
      if (_focusTimer) clearTimeout(_focusTimer);
      _focusTimer = setTimeout(function () {
        _focusTimer = null;
        var newInp = treeTbody.querySelector('.tree-new-sn[data-num="' + num + '"]');
        if (newInp) newInp.focus();
      }, 0);
    });
    treeExpandAll.addEventListener('click', function () {
      collapsedSet.clear();
      renderTree();
    });
    treeCollapseAll.addEventListener('click', function () {
      collapsedSet = new Set();
      Object.keys(childrenByNum).forEach(function (n) { collapsedSet.add(parseInt(n, 10)); });
      renderTree();
    });
    chkShowDekitted.addEventListener('change', renderTree);

    if (btnOnlineTest) {
      btnOnlineTest.addEventListener('click', function () {
        var s = (inputSn.value || '').trim();
        if (!s) { showErr('Enter SN first'); return; }
        if (typeof window.etfOpenOnlineTestModal === 'function') window.etfOpenOnlineTestModal(s);
      });
    }
    var btnAiStart = document.getElementById('btn-ai-start');
    var btnAiEnd = document.getElementById('btn-ai-end');
    var btnAiUpload = document.getElementById('btn-ai-upload');
    if (btnAiStart) {
      btnAiStart.addEventListener('click', function () {
        if (!termRowKey) { showErr('Search SN first'); return; }
        if (typeof window.etfAiStartSession === 'function') window.etfAiStartSession(termRowKey);
      });
    }
    if (btnAiEnd) {
      btnAiEnd.addEventListener('click', function () {
        if (!termRowKey) return;
        if (typeof window.etfAiEndSession === 'function') window.etfAiEndSession(termRowKey);
      });
    }
    if (btnAiUpload) {
      btnAiUpload.addEventListener('click', function () {
        if (!termRowKey) { showErr('Search SN first'); return; }
        if (typeof window.etfAiUpload === 'function') window.etfAiUpload(termRowKey);
      });
    }

    window.addEventListener('beforeunload', stopCrabberPoll);

    loadOptions();
})();
