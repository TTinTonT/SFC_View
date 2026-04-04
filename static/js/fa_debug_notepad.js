/**
 * Shared notepad: sidebar (FA Debug) or floating corners (Testing).
 * window.initFaDebugNotepad({ mode, storagePrefix, onLayoutChange? })
 */
(function () {
  function $(id) {
    return document.getElementById(id);
  }

  function el(tag, attrs, children) {
    const e = document.createElement(tag);
    if (attrs) Object.assign(e, attrs);
    if (attrs && attrs.className) e.className = attrs.className;
    if (attrs && attrs.style) e.style.cssText = attrs.style;
    if (attrs && attrs.title) e.title = attrs.title;
    if (children) {
      children.forEach((c) => {
        e.appendChild(typeof c === 'string' ? document.createTextNode(c) : c);
      });
    }
    return e;
  }

  const CORNERS = ['tl', 'tr', 'bl', 'br'];

  function applyCornerClass(np, corner) {
    CORNERS.forEach((c) => np.classList.remove('notepad-corner-' + c));
    const c = CORNERS.indexOf(corner) >= 0 ? corner : 'tl';
    np.classList.add('notepad-corner-' + c);
    return c;
  }

  window.initFaDebugNotepad = function initFaDebugNotepad(config) {
    const mode = config && config.mode === 'corner' ? 'corner' : 'sidebar';
    const prefix = (config && config.storagePrefix) || 'fa-debug-notepad';
    const KEY_CONTENT = prefix + '-content';
    const KEY_EXPANDED = prefix + '-expanded';
    const KEY_CORNER = prefix + '-corner';
    const KEY_WIDTH = prefix + '-width';
    const KEY_HEIGHT = prefix + '-height';
    const onLayoutChange = typeof config.onLayoutChange === 'function' ? config.onLayoutChange : function () {};

    const DEF_FLOAT_W = 260;
    const DEF_FLOAT_H = 320;
    const MIN_FLOAT_W = 200;
    const MIN_FLOAT_H = 120;

    let notepadExpanded = true;
    try {
      notepadExpanded = localStorage.getItem(KEY_EXPANDED) !== 'false';
    } catch (_) {}
    let saveTimer = null;

    if (mode === 'sidebar') {
      const id = 'notepad-sidebar';
      let np = $(id);
      if (np) {
        onLayoutChange();
        return;
      }
      np = el('div', { id: id, className: 'notepad-sidebar' });
      np.classList.toggle('expanded', notepadExpanded);
      np.classList.toggle('collapsed', !notepadExpanded);
      document.body.insertBefore(np, document.body.firstChild);

      const toggle = el('button', { type: 'button', className: 'notepad-sidebar-toggle' });
      const toggleSpan = document.createElement('span');
      toggleSpan.textContent = 'Notepad';
      toggle.appendChild(toggleSpan);
      const toggleIcon = document.createElement('span');
      toggleIcon.textContent = notepadExpanded ? '−' : '+';
      toggle.appendChild(toggleIcon);
      toggle.addEventListener('click', () => {
        notepadExpanded = !notepadExpanded;
        np.classList.toggle('expanded', notepadExpanded);
        np.classList.toggle('collapsed', !notepadExpanded);
        toggleIcon.textContent = notepadExpanded ? '−' : '+';
        const body = np.querySelector('.notepad-sidebar-body');
        if (body) body.style.display = notepadExpanded ? 'flex' : 'none';
        try {
          localStorage.setItem(KEY_EXPANDED, notepadExpanded ? 'true' : 'false');
        } catch (_) {}
        onLayoutChange();
      });
      np.appendChild(toggle);

      const body = el('div', { className: 'notepad-sidebar-body' });
      body.style.display = notepadExpanded ? 'flex' : 'none';
      const toolbar = el('div', { className: 'notepad-toolbar' });
      const copyBtn = el('button', { type: 'button' });
      copyBtn.textContent = 'Copy';
      copyBtn.addEventListener('click', () => {
        const ta = np.querySelector('.notepad-textarea');
        if (ta) navigator.clipboard?.writeText(ta.value || '').then(() => {}).catch(() => {});
      });
      toolbar.appendChild(copyBtn);
      body.appendChild(toolbar);
      const ta = el('textarea', { className: 'notepad-textarea' });
      ta.placeholder = 'Note, paste text...';
      try {
        ta.value = localStorage.getItem(KEY_CONTENT) || '';
      } catch (_) {}
      const saveNotepad = () => {
        try {
          localStorage.setItem(KEY_CONTENT, ta.value);
        } catch (_) {}
      };
      ta.addEventListener('input', () => {
        if (saveTimer) clearTimeout(saveTimer);
        saveTimer = setTimeout(() => {
          saveNotepad();
          saveTimer = null;
        }, 300);
      });
      ta.addEventListener('blur', saveNotepad);
      body.appendChild(ta);
      np.appendChild(body);
      onLayoutChange();
      return;
    }

    /* corner mode */
    const id = 'testing-notepad';
    if ($(id)) {
      return;
    }

    let corner = 'tl';
    try {
      const s = localStorage.getItem(KEY_CORNER);
      if (s && CORNERS.indexOf(s) >= 0) corner = s;
    } catch (_) {}

    const np = el('div', { id: id, className: 'notepad-floating' });
    np.classList.toggle('expanded', notepadExpanded);
    np.classList.toggle('collapsed', !notepadExpanded);
    applyCornerClass(np, corner);
    document.body.appendChild(np);

    let floatW = DEF_FLOAT_W;
    let floatH = DEF_FLOAT_H;
    try {
      const sw = parseInt(localStorage.getItem(KEY_WIDTH), 10);
      const sh = parseInt(localStorage.getItem(KEY_HEIGHT), 10);
      if (sw >= MIN_FLOAT_W) floatW = sw;
      if (sh >= MIN_FLOAT_H) floatH = sh;
    } catch (_) {}

    function clampFloatSize(w, h) {
      const maxW = Math.max(MIN_FLOAT_W, Math.floor(window.innerWidth * 0.9));
      const maxH = Math.max(MIN_FLOAT_H, Math.floor(window.innerHeight * 0.85));
      return {
        w: Math.min(maxW, Math.max(MIN_FLOAT_W, Math.round(w))),
        h: Math.min(maxH, Math.max(MIN_FLOAT_H, Math.round(h))),
      };
    }

    function applyFloatSize() {
      if (!notepadExpanded) return;
      const { w, h } = clampFloatSize(floatW, floatH);
      floatW = w;
      floatH = h;
      np.style.width = w + 'px';
      np.style.height = h + 'px';
      np.style.maxHeight = 'none';
    }

    function persistFloatSize() {
      try {
        localStorage.setItem(KEY_WIDTH, String(floatW));
        localStorage.setItem(KEY_HEIGHT, String(floatH));
      } catch (_) {}
    }

    if (notepadExpanded) {
      applyFloatSize();
    }

    const head = el('div', { className: 'notepad-floating-head' });
    const dragHandle = el('button', {
      type: 'button',
      className: 'notepad-drag-handle',
      title: 'Drag to move (snap to nearest corner)',
    });
    dragHandle.setAttribute('aria-label', 'Drag notepad');
    dragHandle.appendChild(document.createTextNode('⋮⋮'));
    head.appendChild(dragHandle);

    const toggle = el('button', { type: 'button', className: 'notepad-sidebar-toggle' });
    const toggleSpan = document.createElement('span');
    toggleSpan.textContent = 'Notepad';
    toggle.appendChild(toggleSpan);
    const toggleIcon = document.createElement('span');
    toggleIcon.textContent = notepadExpanded ? '−' : '+';
    toggle.appendChild(toggleIcon);
    toggle.addEventListener('click', () => {
      notepadExpanded = !notepadExpanded;
      np.classList.toggle('expanded', notepadExpanded);
      np.classList.toggle('collapsed', !notepadExpanded);
      toggleIcon.textContent = notepadExpanded ? '−' : '+';
      const bodyEl = np.querySelector('.notepad-sidebar-body');
      if (bodyEl) bodyEl.style.display = notepadExpanded ? 'flex' : 'none';
      if (notepadExpanded) {
        applyFloatSize();
      } else {
        np.style.width = '';
        np.style.height = '';
        np.style.maxHeight = '';
      }
      try {
        localStorage.setItem(KEY_EXPANDED, notepadExpanded ? 'true' : 'false');
      } catch (_) {}
    });
    head.appendChild(toggle);
    np.appendChild(head);

    const body = el('div', { className: 'notepad-sidebar-body' });
    body.style.display = notepadExpanded ? 'flex' : 'none';
    const toolbar = el('div', { className: 'notepad-toolbar' });
    const copyBtn = el('button', { type: 'button' });
    copyBtn.textContent = 'Copy';
    copyBtn.addEventListener('click', () => {
      const ta = np.querySelector('.notepad-textarea');
      if (ta) navigator.clipboard?.writeText(ta.value || '').then(() => {}).catch(() => {});
    });
    toolbar.appendChild(copyBtn);
    body.appendChild(toolbar);
    const ta = el('textarea', { className: 'notepad-textarea' });
    ta.placeholder = 'Note, paste text...';
    try {
      ta.value = localStorage.getItem(KEY_CONTENT) || '';
    } catch (_) {}
    const saveNotepad = () => {
      try {
        localStorage.setItem(KEY_CONTENT, ta.value);
      } catch (_) {}
    };
    ta.addEventListener('input', () => {
      if (saveTimer) clearTimeout(saveTimer);
      saveTimer = setTimeout(() => {
        saveNotepad();
        saveTimer = null;
      }, 300);
    });
    ta.addEventListener('blur', saveNotepad);
    body.appendChild(ta);
    np.appendChild(body);

    const resizeHandle = el('div', {
      className: 'notepad-resize-handle',
      title: 'Drag to resize',
    });
    resizeHandle.setAttribute('aria-hidden', 'true');
    np.appendChild(resizeHandle);

    let resizing = false;
    let resizeStartX = 0;
    let resizeStartY = 0;
    let resizeStartW = 0;
    let resizeStartH = 0;

    function onResizeDown(e) {
      if (!notepadExpanded || e.button !== 0) return;
      e.preventDefault();
      e.stopPropagation();
      resizing = true;
      const rect = np.getBoundingClientRect();
      resizeStartX = e.clientX;
      resizeStartY = e.clientY;
      resizeStartW = rect.width;
      resizeStartH = rect.height;
      np.classList.add('notepad-resizing');
      try {
        resizeHandle.setPointerCapture(e.pointerId);
      } catch (_) {}
    }

    function onResizeMove(e) {
      if (!resizing) return;
      const dx = e.clientX - resizeStartX;
      const dy = e.clientY - resizeStartY;
      const next = clampFloatSize(resizeStartW + dx, resizeStartH + dy);
      floatW = next.w;
      floatH = next.h;
      np.style.width = floatW + 'px';
      np.style.height = floatH + 'px';
      np.style.maxHeight = 'none';
    }

    function onResizeUp(e) {
      if (!resizing) return;
      resizing = false;
      np.classList.remove('notepad-resizing');
      try {
        resizeHandle.releasePointerCapture(e.pointerId);
      } catch (_) {}
      persistFloatSize();
    }

    resizeHandle.addEventListener('pointerdown', onResizeDown);
    resizeHandle.addEventListener('pointermove', onResizeMove);
    resizeHandle.addEventListener('pointerup', onResizeUp);
    resizeHandle.addEventListener('pointercancel', onResizeUp);

    let dragging = false;
    let startX = 0;
    let startY = 0;
    let startLeft = 0;
    let startTop = 0;

    function snapToQuadrant() {
      const rect = np.getBoundingClientRect();
      const cx = rect.left + rect.width / 2;
      const cy = rect.top + rect.height / 2;
      const vw = window.innerWidth;
      const vh = window.innerHeight;
      let next = 'br';
      if (cx < vw / 2 && cy < vh / 2) next = 'tl';
      else if (cx >= vw / 2 && cy < vh / 2) next = 'tr';
      else if (cx < vw / 2 && cy >= vh / 2) next = 'bl';
      corner = applyCornerClass(np, next);
      try {
        localStorage.setItem(KEY_CORNER, corner);
      } catch (_) {}
      np.style.left = '';
      np.style.top = '';
      np.style.right = '';
      np.style.bottom = '';
      if (notepadExpanded) {
        applyFloatSize();
      }
    }

    function onPointerDown(e) {
      if (e.button !== 0) return;
      dragging = true;
      const rect = np.getBoundingClientRect();
      startX = e.clientX;
      startY = e.clientY;
      startLeft = rect.left;
      startTop = rect.top;
      CORNERS.forEach((c) => np.classList.remove('notepad-corner-' + c));
      np.style.left = rect.left + 'px';
      np.style.top = rect.top + 'px';
      np.style.right = 'auto';
      np.style.bottom = 'auto';
      np.style.width = rect.width + 'px';
      np.style.height = rect.height + 'px';
      np.style.maxHeight = 'none';
      try {
        dragHandle.setPointerCapture(e.pointerId);
      } catch (_) {}
      e.preventDefault();
    }

    function onPointerMove(e) {
      if (!dragging) return;
      const dx = e.clientX - startX;
      const dy = e.clientY - startY;
      let nl = startLeft + dx;
      let nt = startTop + dy;
      const rect = np.getBoundingClientRect();
      const w = rect.width;
      const h = rect.height;
      const pad = 4;
      nl = Math.max(pad, Math.min(nl, window.innerWidth - w - pad));
      nt = Math.max(pad, Math.min(nt, window.innerHeight - h - pad));
      np.style.left = nl + 'px';
      np.style.top = nt + 'px';
    }

    function onPointerUp(e) {
      if (!dragging) return;
      dragging = false;
      try {
        dragHandle.releasePointerCapture(e.pointerId);
      } catch (_) {}
      snapToQuadrant();
    }

    dragHandle.addEventListener('pointerdown', onPointerDown);
    dragHandle.addEventListener('pointermove', onPointerMove);
    dragHandle.addEventListener('pointerup', onPointerUp);
    dragHandle.addEventListener('pointercancel', onPointerUp);

    let winResizeTimer = null;
    window.addEventListener('resize', () => {
      if (!notepadExpanded) return;
      clearTimeout(winResizeTimer);
      winResizeTimer = setTimeout(() => {
        applyFloatSize();
        persistFloatSize();
      }, 120);
    });
  };
})();
