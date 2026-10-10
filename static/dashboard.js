/*
 * Page interactions for the dashboard (leaderboard sorting/search,
 * advanced-stats toggle, player profiles, nav highlighting).
 * Inlined into index.html at build time by generate_dashboard.py.
 */
(function () {
  'use strict';

  /* ---- leaderboard sorting ----------------------------------------- */
  // Each sortable <th> has data-col (cell index) and data-type
  // ("number" | "string"). Cells carry their raw value in data-sort.
  function cellValue(row, col, type) {
    var cell = row.cells[col];
    var raw = cell.getAttribute('data-sort');
    if (raw === null) raw = cell.textContent.trim();
    if (type === 'number') {
      var n = parseFloat(raw);
      return isFinite(n) ? n : -Infinity;  // missing values sort lowest
    }
    return raw.toLowerCase();
  }

  function sortBy(th) {
    var table = th.closest('table');
    var tbody = table.tBodies[0];
    var col = parseInt(th.getAttribute('data-col'), 10);
    var type = th.getAttribute('data-type') || 'number';
    var current = th.getAttribute('aria-sort');
    // Numbers start high-to-low, names start A-Z
    var first = th.getAttribute('data-first') ||
      (type === 'string' ? 'ascending' : 'descending');
    var next = current === first
      ? (first === 'ascending' ? 'descending' : 'ascending') : first;
    table.querySelectorAll('th[aria-sort]').forEach(function (h) {
      h.removeAttribute('aria-sort');
      var a = h.querySelector('.arrow');
      if (a) a.textContent = '↕';
    });
    th.setAttribute('aria-sort', next);
    var arrow = th.querySelector('.arrow');
    if (arrow) arrow.textContent = next === 'ascending' ? '▲' : '▼';
    var dir = next === 'ascending' ? 1 : -1;

    var rows = Array.prototype.slice.call(tbody.rows);
    rows.sort(function (a, b) {
      var av = cellValue(a, col, type), bv = cellValue(b, col, type);
      if (av < bv) return -1 * dir;
      if (av > bv) return 1 * dir;
      return 0;
    });
    rows.forEach(function (r) { tbody.appendChild(r); });
  }

  /* ---- profiles ---------------------------------------------------- */
  function setProfile(slug, open) {
    var body = document.getElementById('profile-body-' + slug);
    var btn = document.getElementById('profile-btn-' + slug);
    if (!body) return false;
    body.classList.toggle('open', open);
    if (btn) btn.setAttribute('aria-expanded', open ? 'true' : 'false');
    return true;
  }
  window.toggleProfile = function (slug) {
    var body = document.getElementById('profile-body-' + slug);
    if (body) setProfile(slug, !body.classList.contains('open'));
  };
  // Open a profile from elsewhere on the page and bring it into view
  window.showProfile = function (slug) {
    if (!setProfile(slug, true)) return;
    var card = document.getElementById('profile-' + slug);
    card.scrollIntoView({ behavior: 'smooth', block: 'start' });
    card.classList.remove('flash');
    void card.offsetWidth;  // restart the highlight animation
    card.classList.add('flash');
  };

  document.addEventListener('DOMContentLoaded', function () {
    var table = document.getElementById('playerTable');

    if (table) {
      table.querySelectorAll('th.sortable').forEach(function (th) {
        th.addEventListener('click', function () { sortBy(th); });
        th.addEventListener('keydown', function (e) {
          if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); sortBy(th); }
        });
      });
      table.querySelectorAll('tbody tr[data-slug]').forEach(function (tr) {
        tr.addEventListener('click', function () { window.showProfile(tr.getAttribute('data-slug')); });
        tr.addEventListener('keydown', function (e) {
          if (e.key === 'Enter') window.showProfile(tr.getAttribute('data-slug'));
        });
      });
    }

    /* ---- search ---------------------------------------------------- */
    var search = document.getElementById('playerSearch');
    var noMatch = document.getElementById('noMatch');
    var count = document.getElementById('boardCount');
    if (search && table) {
      search.addEventListener('input', function () {
        var q = search.value.trim().toLowerCase();
        var shown = 0;
        Array.prototype.forEach.call(table.tBodies[0].rows, function (tr) {
          var hit = !q || tr.getAttribute('data-name').indexOf(q) !== -1;
          tr.style.display = hit ? '' : 'none';
          if (hit) shown++;
        });
        if (noMatch) noMatch.style.display = shown ? 'none' : 'block';
        if (count) count.textContent = q
          ? shown + ' of ' + table.tBodies[0].rows.length + ' players'
          : count.getAttribute('data-default');
      });
    }

    /* ---- advanced columns toggle ----------------------------------- */
    var advBtn = document.getElementById('advToggle');
    var board = document.getElementById('board');
    if (advBtn && board) {
      advBtn.addEventListener('click', function () {
        var on = board.classList.toggle('show-adv');
        advBtn.setAttribute('aria-pressed', on ? 'true' : 'false');
        advBtn.textContent = on ? 'Show fewer stats' : 'Show more stats';
      });
    }

    /* ---- nav: highlight the section in view ------------------------ */
    var links = document.querySelectorAll('.topnav a.navlink');
    if ('IntersectionObserver' in window && links.length) {
      var byId = {};
      links.forEach(function (a) { byId[a.getAttribute('href').slice(1)] = a; });
      var obs = new IntersectionObserver(function (entries) {
        entries.forEach(function (en) {
          if (!en.isIntersecting) return;
          links.forEach(function (a) { a.classList.remove('current'); });
          var a = byId[en.target.id];
          if (a) a.classList.add('current');
        });
      }, { rootMargin: '-45% 0px -50% 0px' });
      Object.keys(byId).forEach(function (id) {
        var s = document.getElementById(id);
        if (s) obs.observe(s);
      });
    }
  });
})();
