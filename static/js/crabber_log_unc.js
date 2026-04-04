/**
 * Shared: Oberon L10 UNC log folder path from CRABBER_LOG_UNC_ROOT + log_time (UTC ISO) + log id.
 * Must match crabber/log_unc_path.py. Used by FA Debug timeline + Testing Crabber table.
 */
(function (global) {
  'use strict';

  function escAttr(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;')
      .replace(/"/g, '&quot;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
  }

  function escHtmlText(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
  }

  function fallbackExecCopy(text) {
    try {
      var ta = document.createElement('textarea');
      ta.value = text;
      ta.setAttribute('readonly', '');
      ta.style.position = 'fixed';
      ta.style.left = '-9999px';
      document.body.appendChild(ta);
      ta.select();
      ta.setSelectionRange(0, text.length);
      var ok = document.execCommand('copy');
      document.body.removeChild(ta);
      return ok;
    } catch (e) {
      return false;
    }
  }

  /**
   * Read full UNC from button (hidden span — avoids data-* + backslashes being mangled).
   * @param {HTMLElement} btn
   * @returns {string}
   */
  function pathFromButton(btn) {
    if (!btn) return '';
    var span = btn.querySelector('.crabber-unc-path');
    if (span && span.textContent) return String(span.textContent).replace(/\r|\n/g, '').trim();
    return String(btn.getAttribute('data-copy') || '').trim();
  }

  /**
   * Copy path to clipboard + brief label feedback.
   * @param {HTMLElement} btn
   */
  function performCopy(btn) {
    var path = pathFromButton(btn);
    if (!path) return;
    var label = btn.querySelector('.crabber-unc-label');
    var orig = label ? label.textContent : 'Copy';
    function showOk() {
      if (label) label.textContent = 'Copied!';
      btn.classList.add('crabber-unc-copied');
      window.setTimeout(function () {
        if (label) label.textContent = orig;
        btn.classList.remove('crabber-unc-copied');
      }, 2000);
    }
    function showFail() {
      if (label) label.textContent = 'Failed';
      window.setTimeout(function () {
        if (label) label.textContent = orig;
      }, 2000);
    }
    function done(ok) {
      if (ok) showOk();
      else showFail();
    }
    if (navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
      navigator.clipboard.writeText(path).then(function () { done(true); }).catch(function () {
        done(fallbackExecCopy(path));
      });
    } else {
      done(fallbackExecCopy(path));
    }
  }

  /**
   * @param {string} root UNC prefix e.g. \\10.16.137.111\Oberon\L10
   * @param {string} logTimeIso ISO string (Z or offset)
   * @param {string|number} logId Crabber node_log_id (Oberon folder segment; not exe_log_id)
   * @returns {string}
   */
  function buildPath(root, logTimeIso, logId) {
    var r = String(root || '').trim().replace(/[\\/]+$/, '');
    if (!r || !logTimeIso || logId == null || String(logId).trim() === '') return '';
    var iso = String(logTimeIso).trim();
    if (iso.endsWith('Z')) iso = iso.slice(0, -1) + '+00:00';
    var d = new Date(iso);
    if (isNaN(d.getTime())) return '';
    var y = d.getUTCFullYear();
    var m = String(d.getUTCMonth() + 1).padStart(2, '0');
    var day = String(d.getUTCDate()).padStart(2, '0');
    var lid = String(logId).trim();
    return r + '\\' + y + '\\' + m + '\\' + day + '\\' + lid;
  }

  /**
   * @param {string} path full UNC folder path
   * @returns {string} HTML (button or em dash)
   */
  function copyBtnHtml(path) {
    if (!path) {
      return '<span class="text-muted crabber-unc-empty" style="color:var(--color-muted)">—</span>';
    }
    return (
      '<button type="button" class="crabber-unc-copy btn-ghost btn-mini" title="' +
      escAttr('Copy: ' + path) +
      '">' +
      '<span class="crabber-unc-path" aria-hidden="true">' +
      escHtmlText(path) +
      '</span>' +
      '<span class="crabber-unc-label">Copy</span></button>'
    );
  }

  global.CrabberLogUnc = {
    buildPath: buildPath,
    copyBtnHtml: copyBtnHtml,
    escAttr: escAttr,
    escHtmlText: escHtmlText,
    pathFromButton: pathFromButton,
    performCopy: performCopy,
  };
})(typeof window !== 'undefined' ? window : this);
