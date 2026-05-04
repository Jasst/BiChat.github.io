// static/js/mobile-sidebar.js
(function() {
  window.toggleSidebar = function() {
    const sidebar = document.getElementById('sidebar');
    const overlay = document.getElementById('sidebarOverlay');
    if (!sidebar) return;
    sidebar.classList.toggle('open');
    if (overlay) {
      overlay.classList.toggle('active', sidebar.classList.contains('open'));
      document.body.style.overflow = sidebar.classList.contains('open') ? 'hidden' : '';
    }
  };

  window.closeSidebar = function() {
    const sidebar = document.getElementById('sidebar');
    const overlay = document.getElementById('sidebarOverlay');
    if (sidebar) sidebar.classList.remove('open');
    if (overlay) overlay.classList.remove('active');
    document.body.style.overflow = '';
  };

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') window.closeSidebar?.();
  });
})();