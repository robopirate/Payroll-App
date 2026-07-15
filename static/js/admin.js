/* ─── Robo Pirate Admin Portal JS ─── */

(function() {
  'use strict';

  const sidebar = document.getElementById('adminSidebar');
  const overlay = document.getElementById('adminSidebarOverlay');
  const toggle = document.getElementById('adminSidebarToggle');

  function openSidebar() {
    if (!sidebar || !overlay) return;
    sidebar.classList.add('open');
    overlay.classList.add('open');
    document.body.style.overflow = 'hidden';
  }

  function closeSidebar() {
    if (!sidebar || !overlay) return;
    sidebar.classList.remove('open');
    overlay.classList.remove('open');
    document.body.style.overflow = '';
  }

  if (toggle) toggle.addEventListener('click', openSidebar);
  if (overlay) overlay.addEventListener('click', closeSidebar);

  // Close sidebar when clicking a nav link on mobile
  document.querySelectorAll('.admin-nav a').forEach(function(link) {
    link.addEventListener('click', function() {
      if (window.innerWidth < 992) closeSidebar();
    });
  });

  // Close on Escape
  document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') closeSidebar();
  });

  // Auto-dismiss Bootstrap alerts after 6 seconds
  document.querySelectorAll('.alert-dismissible').forEach(function(alert) {
    setTimeout(function() {
      var btn = alert.querySelector('.btn-close');
      if (btn) btn.click();
    }, 6000);
  });

  // Confirm destructive actions
  document.querySelectorAll('[data-confirm]').forEach(function(el) {
    el.addEventListener('click', function(e) {
      var msg = el.getAttribute('data-confirm') || 'Are you sure?';
      if (!confirm(msg)) {
        e.preventDefault();
        e.stopImmediatePropagation();
      }
    });
  });
})();
