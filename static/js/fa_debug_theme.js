/**
 * Dark/light theme for FA Debug shell (localStorage: fa-debug-theme).
 * Safe on pages without #theme-toggle (no-op).
 */
(function () {
  function $(id) {
    return document.getElementById(id);
  }
  function initTheme() {
    var dark = localStorage.getItem('fa-debug-theme') === 'dark';
    document.documentElement.classList.toggle('dark', dark);
    var sunEl = $('sun-icon');
    var moonEl = $('moon-icon');
    if (sunEl) sunEl.classList.toggle('hidden', !dark);
    if (moonEl) moonEl.classList.toggle('hidden', dark);
  }
  function toggleTheme() {
    var dark = !document.documentElement.classList.contains('dark');
    document.documentElement.classList.toggle('dark', dark);
    localStorage.setItem('fa-debug-theme', dark ? 'dark' : 'light');
    var sunEl = $('sun-icon');
    var moonEl = $('moon-icon');
    if (sunEl) sunEl.classList.toggle('hidden', !dark);
    if (moonEl) moonEl.classList.toggle('hidden', dark);
  }
  function init() {
    var btn = $('theme-toggle');
    if (!btn) return;
    initTheme();
    btn.addEventListener('click', toggleTheme);
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
