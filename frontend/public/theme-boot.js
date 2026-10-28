// OpSyn theme boot — runs synchronously in <head>, before first paint, so the
// page never flashes the wrong theme. Keep in sync with src/store/theme.store.ts
// (same storage key and values). Default is light; 'system' follows the OS.
(function () {
  var pref = 'light';
  try {
    var saved = localStorage.getItem('opsyn-theme');
    if (saved === 'light' || saved === 'dark' || saved === 'system') pref = saved;
  } catch (e) { /* storage blocked — keep the default */ }
  var dark = pref === 'dark' ||
    (pref === 'system' && window.matchMedia && matchMedia('(prefers-color-scheme: dark)').matches);
  document.documentElement.dataset.theme = dark ? 'dark' : 'light';
})();
