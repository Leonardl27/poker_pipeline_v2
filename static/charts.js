/*
 * Inline SVG chart renderer for the poker dashboard.
 * Inlined into index.html at build time (no external requests).
 * Reads window.CHART_DATA (JSON emitted by chart_data.py) and renders
 * each chart into its container div with hover tooltips.
 */
(function () {
  'use strict';
  var NS = 'http://www.w3.org/2000/svg';
  var C = {
    bg: '#1a1a2e', panel: '#16213e', border: '#0f3460', accent: '#e94560',
    pos: '#4caf50', text: '#eeeeee', neutral: '#aaaaaa',
    series: ['#4caf50', '#2a9d8f', '#38bdf8', '#fb923c', '#e94560'],
    scatter: ['#2a9d8f', '#38bdf8', '#fb923c', '#e9c46a'],
    mid: '#e9c46a'
  };

  /* ---- shared tooltip ---------------------------------------------- */
  var tip = document.createElement('div');
  tip.className = 'chart-tip';
  tip.style.display = 'none';
  document.body.appendChild(tip);

  function moveTip(evt) {
    var pad = 14;
    var x = evt.pageX + pad;
    var y = evt.pageY + pad;
    var r = tip.getBoundingClientRect();
    var maxX = window.pageXOffset + document.documentElement.clientWidth - 8;
    if (x + r.width > maxX) x = evt.pageX - r.width - pad;
    tip.style.left = x + 'px';
    tip.style.top = y + 'px';
  }
  function attachTip(node, htmlFn) {
    node.addEventListener('mousemove', function (e) {
      tip.innerHTML = htmlFn();
      tip.style.display = 'block';
      moveTip(e);
    });
    node.addEventListener('mouseleave', function () {
      tip.style.display = 'none';
    });
  }

  /* ---- SVG + math helpers ------------------------------------------ */
  function el(parent, tag, attrs) {
    var e = document.createElementNS(NS, tag);
    if (attrs) for (var k in attrs) e.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(e);
    return e;
  }
  function txt(parent, x, y, str, attrs) {
    var e = el(parent, 'text', attrs || {});
    e.setAttribute('x', x);
    e.setAttribute('y', y);
    e.textContent = str;
    return e;
  }
  function svgIn(container, w, h) {
    var s = el(null, 'svg', { viewBox: '0 0 ' + w + ' ' + h });
    container.appendChild(s);
    return s;
  }
  function scale(d0, d1, r0, r1) {
    var dd = (d1 - d0) || 1;
    return function (v) { return r0 + (v - d0) / dd * (r1 - r0); };
  }
  function niceTicks(lo, hi, n) {
    var span = (hi - lo) || 1;
    var step = Math.pow(10, Math.floor(Math.log(span / n) / Math.LN10));
    var err = span / n / step;
    if (err >= 7.5) step *= 10;
    else if (err >= 3.5) step *= 5;
    else if (err >= 1.5) step *= 2;
    var out = [];
    for (var v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) {
      out.push(Math.round(v * 1000) / 1000);
    }
    return out;
  }
  function extent(arr) {
    return [Math.min.apply(null, arr), Math.max.apply(null, arr)];
  }
  function money(v) {
    var sign = v > 0 ? '+' : v < 0 ? '−' : '';
    return sign + '$' + Math.abs(v).toFixed(2);
  }
  function moneyClass(v) { return v >= 0 ? 'pos' : 'neg'; }
  function fmtNum(v) { return v.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ','); }

  function hex2rgb(h) {
    return [parseInt(h.slice(1, 3), 16), parseInt(h.slice(3, 5), 16),
            parseInt(h.slice(5, 7), 16)];
  }
  function lerpColor(a, b, t) {
    var ca = hex2rgb(a), cb = hex2rgb(b), out = [], i;
    for (i = 0; i < 3; i++) out.push(Math.round(ca[i] + (cb[i] - ca[i]) * t));
    return 'rgb(' + out.join(',') + ')';
  }
  /* red (negative) -> panel (zero) -> green (positive) */
  function divergingColor(v, vmax) {
    if (v === null || v === undefined) return C.bg;
    var t = Math.max(-1, Math.min(1, v / (vmax || 1)));
    return t < 0 ? lerpColor(C.panel, C.accent, -t)
                 : lerpColor(C.panel, C.pos, t);
  }
  /* red -> yellow -> green ramp for ordered categories */
  function rampColor(t) {
    return t < 0.5 ? lerpColor(C.accent, C.mid, t * 2)
                   : lerpColor(C.mid, C.pos, (t - 0.5) * 2);
  }

  function plotFrame(svg, m, W, H) {
    el(svg, 'rect', {
      x: m.l, y: m.t, width: W - m.l - m.r, height: H - m.t - m.b,
      fill: C.panel, rx: 4
    });
  }
  function yGrid(svg, ticks, Y, m, W, fmt) {
    ticks.forEach(function (t) {
      var y = Y(t);
      el(svg, 'line', { x1: m.l, y1: y, x2: W - m.r, y2: y,
        stroke: C.border, 'stroke-width': 0.6, opacity: 0.9 });
      txt(svg, m.l - 8, y + 4, fmt ? fmt(t) : t,
          { fill: C.neutral, 'font-size': 11, 'text-anchor': 'end' });
    });
  }

  /* ---- Player Archetypes (VPIP vs PFR quadrants) -------------------- */
  function renderArchetypes(root, d) {
    if (!d.players.length) return;
    var W = 1100, H = 620;
    var m = { t: 28, r: 40, b: 64, l: 70 };
    var svg = svgIn(root, W, H);

    var xe = extent(d.players.map(function (p) { return p.vpip; }));
    var ye = extent(d.players.map(function (p) { return p.pfr; }));
    var X = scale(xe[0] - 5, xe[1] + 5, m.l, W - m.r);
    var Y = scale(Math.min(ye[0], 0) - 1, ye[1] + 2.5, H - m.b, m.t);

    plotFrame(svg, m, W, H);
    yGrid(svg, niceTicks(Math.min(ye[0], 0) - 1, ye[1] + 2.5, 8), Y, m, W);
    niceTicks(xe[0] - 5, xe[1] + 5, 9).forEach(function (t) {
      var x = X(t);
      el(svg, 'line', { x1: x, y1: m.t, x2: x, y2: H - m.b,
        stroke: C.border, 'stroke-width': 0.6, opacity: 0.9 });
      txt(svg, x, H - m.b + 18, t, { fill: C.neutral, 'font-size': 11,
        'text-anchor': 'middle' });
    });

    el(svg, 'line', { x1: X(d.vpip_median), y1: m.t, x2: X(d.vpip_median),
      y2: H - m.b, stroke: C.neutral, 'stroke-dasharray': '5,4', opacity: 0.5 });
    el(svg, 'line', { x1: m.l, y1: Y(d.pfr_median), x2: W - m.r,
      y2: Y(d.pfr_median), stroke: C.neutral, 'stroke-dasharray': '5,4', opacity: 0.5 });

    var quads = [
      [m.l + 12, m.t + 20, 'start', 'TIGHT-AGGRESSIVE · "The Shark"'],
      [W - m.r - 12, m.t + 20, 'end', 'LOOSE-AGGRESSIVE · "The Maniac"'],
      [m.l + 12, H - m.b - 12, 'start', 'TIGHT-PASSIVE · "The Rock"'],
      [W - m.r - 12, H - m.b - 12, 'end', 'LOOSE-PASSIVE · "The Calling Station"']
    ];
    quads.forEach(function (q) {
      txt(svg, q[0], q[1], q[3], { fill: C.neutral, 'font-size': 12,
        'font-weight': 'bold', 'text-anchor': q[2], opacity: 0.65 });
    });

    var maxHands = Math.max.apply(null, d.players.map(function (p) { return p.hands; }));
    d.players.forEach(function (p) {
      var r = 7 + 14 * Math.sqrt(p.hands / maxHands);
      var dot = el(svg, 'circle', { cx: X(p.vpip), cy: Y(p.pfr), r: r,
        fill: p.profit >= 0 ? C.pos : C.accent, 'fill-opacity': 0.75,
        stroke: C.text, 'stroke-width': 0.8, cursor: 'pointer' });
      txt(svg, X(p.vpip), Y(p.pfr) - r - 5, p.name,
          { fill: C.text, 'font-size': 11, 'text-anchor': 'middle' });
      attachTip(dot, function () {
        return '<strong>' + p.name + '</strong><br>VPIP ' + p.vpip +
          '% · PFR ' + p.pfr + '%<br>' + fmtNum(p.hands) +
          ' hands · <span class="' + moneyClass(p.profit) + '">' +
          money(p.profit) + '</span>';
      });
    });

    txt(svg, (m.l + W - m.r) / 2, H - 14, 'VPIP% — how many hands they play',
        { fill: C.text, 'font-size': 12, 'text-anchor': 'middle' });
    txt(svg, 18, (m.t + H - m.b) / 2, 'PFR% — how often they raise preflop',
        { fill: C.text, 'font-size': 12, 'text-anchor': 'middle',
          transform: 'rotate(-90 18 ' + (m.t + H - m.b) / 2 + ')' });
  }

  /* ---- Hand Analysis (two horizontal bar charts) -------------------- */
  function renderHBar(root, items, colorFn, title, unit) {
    var W = 540, rowH = 34;
    var m = { t: 34, r: 64, b: 12, l: 140 };
    var H = m.t + m.b + rowH * items.length;
    var svg = svgIn(root, W, H);
    txt(svg, W / 2, 20, title, { fill: C.text, 'font-size': 14,
      'font-weight': 'bold', 'text-anchor': 'middle' });

    var maxV = Math.max.apply(null, items.map(function (it) { return it.count; }));
    var X = scale(0, maxV, m.l, W - m.r);

    items.forEach(function (it, i) {
      var y = m.t + i * rowH;
      var w = Math.max(X(it.count) - m.l, 1.5);
      var bar = el(svg, 'rect', { x: m.l, y: y + 6, width: w,
        height: rowH - 12, rx: 3, fill: colorFn(it, i), cursor: 'pointer' });
      txt(svg, m.l - 8, y + rowH / 2 + 4, it.label,
          { fill: C.text, 'font-size': 11.5, 'text-anchor': 'end' });
      txt(svg, m.l + w + 6, y + rowH / 2 + 4, fmtNum(it.count),
          { fill: C.neutral, 'font-size': 11 });
      attachTip(bar, function () {
        return '<strong>' + it.label + '</strong><br>' + fmtNum(it.count) +
          ' ' + unit;
      });
    });
  }

  function renderHandAnalysis(root, d) {
    var flex = document.createElement('div');
    flex.className = 'chart-flex';
    root.appendChild(flex);
    var left = document.createElement('div');
    var right = document.createElement('div');
    flex.appendChild(left);
    flex.appendChild(right);

    var nHands = d.hands.length;
    renderHBar(left, d.hands, function (it, i) {
      /* strongest hand listed first -> green at top, red at bottom */
      return rampColor(nHands > 1 ? 1 - i / (nHands - 1) : 0.5);
    }, 'Winning Hand Distribution', 'winning hands');
    renderHBar(right, d.actions, function () { return '#2a9d8f'; },
      'Action Distribution', 'events');
  }

  /* ---- Session Trends: cumulative lines + session heatmap ----------- */
  function renderTrendLines(root, d) {
    var W = 1100, H = 430;
    var m = { t: 26, r: 140, b: 62, l: 76 };
    var svg = svgIn(root, W, H);

    var allY = [];
    d.featured.forEach(function (f) {
      f.points.forEach(function (pt) { allY.push(pt.y); });
    });
    if (!allY.length) return;
    var ye = extent(allY);
    var pad = (ye[1] - ye[0]) * 0.08 + 10;
    var n = d.labels.length;
    var X = scale(0, Math.max(n - 1, 1), m.l, W - m.r);
    var Y = scale(ye[0] - pad, ye[1] + pad, H - m.b, m.t);

    plotFrame(svg, m, W, H);
    yGrid(svg, niceTicks(ye[0] - pad, ye[1] + pad, 8), Y, m, W,
          function (t) { return '$' + fmtNum(t); });
    if (ye[0] < 0 && ye[1] > 0) {
      el(svg, 'line', { x1: m.l, y1: Y(0), x2: W - m.r, y2: Y(0),
        stroke: C.neutral, 'stroke-width': 1, opacity: 0.5,
        'stroke-dasharray': '3,3' });
    }

    var lblStep = Math.ceil(n / 20);
    d.labels.forEach(function (lbl, i) {
      if (i % lblStep !== 0) return;
      var x = X(i);
      txt(svg, x, H - m.b + 16, lbl, { fill: C.neutral, 'font-size': 10,
        'text-anchor': 'end', transform: 'rotate(-40 ' + x + ' ' + (H - m.b + 16) + ')' });
    });

    d.featured.forEach(function (f, i) {
      var col = C.series[i % C.series.length];
      var pts = f.points.map(function (pt) {
        return X(pt.x).toFixed(1) + ',' + Y(pt.y).toFixed(1);
      }).join(' ');
      el(svg, 'polyline', { points: pts, fill: 'none', stroke: col,
        'stroke-width': 2.5, opacity: 0.9 });
      f.points.forEach(function (pt) {
        var dot = el(svg, 'circle', { cx: X(pt.x), cy: Y(pt.y), r: 4.5,
          fill: col, stroke: C.bg, 'stroke-width': 1, cursor: 'pointer' });
        attachTip(dot, function () {
          return '<strong>' + f.name + '</strong><br>' + d.labels[pt.x] +
            ' · cumulative <span class="' + moneyClass(pt.y) + '">' +
            money(pt.y) + '</span>';
        });
      });
      var last = f.points[f.points.length - 1];
      txt(svg, X(last.x) + 10, Y(last.y) + 4, f.name,
          { fill: col, 'font-size': 11.5, 'font-weight': 'bold' });
    });
    txt(svg, (m.l + W - m.r) / 2, H - 8, 'Session Date',
        { fill: C.text, 'font-size': 12, 'text-anchor': 'middle' });
  }

  function renderSessionHeatmap(root, d) {
    var cols = d.labels.length, rows = d.names.length;
    if (!cols || !rows) return;
    var m = { t: 36, r: 30, b: 66, l: 150 };
    var W = 1100;
    var cellW = (W - m.l - m.r) / cols;
    var cellH = 30;
    var H = m.t + m.b + cellH * rows;
    var svg = svgIn(root, W, H);
    txt(svg, W / 2, 20, 'Session Profit/Loss by Player',
        { fill: C.text, 'font-size': 14, 'font-weight': 'bold',
          'text-anchor': 'middle' });

    var vmax = 1;
    d.matrix.forEach(function (row) {
      row.forEach(function (v) {
        if (v !== null && Math.abs(v) > vmax) vmax = Math.abs(v);
      });
    });

    d.names.forEach(function (name, r) {
      txt(svg, m.l - 8, m.t + r * cellH + cellH / 2 + 4, name,
          { fill: C.text, 'font-size': 11, 'text-anchor': 'end' });
      d.matrix[r].forEach(function (v, c) {
        var x = m.l + c * cellW, y = m.t + r * cellH;
        var cell = el(svg, 'rect', { x: x + 0.5, y: y + 0.5,
          width: cellW - 1, height: cellH - 1,
          fill: divergingColor(v, vmax), cursor: v === null ? 'default' : 'pointer' });
        if (v !== null) {
          if (cellW > 36) {
            txt(svg, x + cellW / 2, y + cellH / 2 + 3.5,
                (v > 0 ? '+' : '') + Math.round(v),
                { fill: Math.abs(v) > vmax * 0.3 ? C.text : C.neutral,
                  'font-size': 9.5, 'font-weight': 'bold', 'text-anchor': 'middle' });
          }
          attachTip(cell, function () {
            return '<strong>' + name + '</strong><br>' + d.labels[c] +
              ' · <span class="' + moneyClass(v) + '">' + money(v) + '</span>';
          });
        }
      });
    });

    d.labels.forEach(function (lbl, c) {
      var x = m.l + c * cellW + cellW / 2;
      txt(svg, x, m.t + rows * cellH + 16, lbl,
          { fill: C.neutral, 'font-size': 10, 'text-anchor': 'end',
            transform: 'rotate(-40 ' + x + ' ' + (m.t + rows * cellH + 16) + ')' });
    });
  }

  function renderSessionTrends(root, d) {
    renderTrendLines(root, d);
    var gap = document.createElement('div');
    gap.style.height = '14px';
    root.appendChild(gap);
    renderSessionHeatmap(root, d);
  }

  /* ---- Player Momentum (small multiples) ---------------------------- */
  function renderMomentum(root, d) {
    if (!d.players.length) return;
    var grid = document.createElement('div');
    grid.className = 'momentum-grid';
    root.appendChild(grid);

    var ymax = 1;
    var maxN = 1;
    d.players.forEach(function (p) {
      maxN = Math.max(maxN, p.sessions.length);
      p.sessions.forEach(function (s) {
        if (Math.abs(s.profit) > ymax) ymax = Math.abs(s.profit);
      });
    });

    d.players.forEach(function (p) {
      var card = document.createElement('div');
      card.className = 'momentum-chart';
      var title = document.createElement('h5');
      title.textContent = p.name + ' ';
      if (p.trend) {
        var arrow = document.createElement('span');
        arrow.className = p.trend;
        arrow.textContent = p.trend === 'up' ? '↑' : '↓';
        title.appendChild(arrow);
      }
      card.appendChild(title);
      grid.appendChild(card);

      var W = 260, H = 120;
      var m = { t: 6, r: 4, b: 6, l: 4 };
      var svg = svgIn(card, W, H);
      var Y = scale(-ymax * 1.1, ymax * 1.1, H - m.b, m.t);
      var slotW = (W - m.l - m.r) / maxN;
      var barW = Math.max(slotW * 0.65, 2);

      el(svg, 'line', { x1: m.l, y1: Y(0), x2: W - m.r, y2: Y(0),
        stroke: C.border, 'stroke-width': 1 });

      p.sessions.forEach(function (s, i) {
        var x = m.l + i * slotW + (slotW - barW) / 2;
        var y0 = Y(0), y1 = Y(s.profit);
        var bar = el(svg, 'rect', {
          x: x, y: Math.min(y0, y1),
          width: barW, height: Math.max(Math.abs(y1 - y0), 1.5),
          fill: s.profit >= 0 ? C.pos : C.accent, 'fill-opacity': 0.9,
          rx: 1.5, cursor: 'pointer'
        });
        attachTip(bar, function () {
          return '<strong>' + p.name + '</strong><br>' + s.label +
            ' · <span class="' + moneyClass(s.profit) + '">' +
            money(s.profit) + '</span>';
        });
      });
    });
  }

  /* ---- Stat Correlations (matrix heatmap) --------------------------- */
  function renderCorrelations(root, d) {
    var n = d.labels.length;
    if (!n) return;
    var m = { t: 24, r: 30, b: 90, l: 110 };
    var W = 1100;
    var cell = Math.min((W - m.l - m.r) / n, 58);
    var H = m.t + m.b + cell * n;
    var svg = svgIn(root, W, H);

    d.labels.forEach(function (rowLbl, i) {
      txt(svg, m.l - 8, m.t + i * cell + cell / 2 + 4, rowLbl,
          { fill: C.text, 'font-size': 11, 'text-anchor': 'end' });
      d.labels.forEach(function (colLbl, j) {
        var v = d.matrix[i][j];
        var x = m.l + j * cell, y = m.t + i * cell;
        var rect = el(svg, 'rect', { x: x + 0.5, y: y + 0.5,
          width: cell - 1, height: cell - 1,
          fill: divergingColor(v, 1), cursor: 'pointer' });
        if (v !== null) {
          txt(svg, x + cell / 2, y + cell / 2 + 3.5, v.toFixed(2),
              { fill: Math.abs(v) > 0.3 ? C.text : C.neutral,
                'font-size': 9.5, 'font-weight': 'bold',
                'text-anchor': 'middle' });
          attachTip(rect, function () {
            return '<strong>' + rowLbl + ' × ' + colLbl +
              '</strong><br>Pearson r = ' + v.toFixed(2);
          });
        }
      });
    });

    d.labels.forEach(function (lbl, j) {
      var x = m.l + j * cell + cell / 2;
      txt(svg, x, m.t + n * cell + 16, lbl,
          { fill: C.text, 'font-size': 11, 'text-anchor': 'end',
            transform: 'rotate(-40 ' + x + ' ' + (m.t + n * cell + 16) + ')' });
    });
  }

  /* ---- Profit Drivers (scatter + regression panels) ----------------- */
  function renderProfitDrivers(root, d) {
    if (!d.panels.length) return;
    var flex = document.createElement('div');
    flex.className = 'chart-flex';
    root.appendChild(flex);

    d.panels.forEach(function (panel, idx) {
      var box = document.createElement('div');
      flex.appendChild(box);
      var W = 540, H = 360;
      var m = { t: 34, r: 24, b: 52, l: 76 };
      var svg = svgIn(box, W, H);
      txt(svg, W / 2, 20, panel.label + ' vs Profit',
          { fill: C.text, 'font-size': 13, 'font-weight': 'bold',
            'text-anchor': 'middle' });

      var xe = extent(panel.points.map(function (p) { return p.x; }));
      var ye = extent(panel.points.map(function (p) { return p.y; }));
      var xpad = (xe[1] - xe[0]) * 0.08 + 0.2;
      var ypad = (ye[1] - ye[0]) * 0.1 + 5;
      var X = scale(xe[0] - xpad, xe[1] + xpad, m.l, W - m.r);
      var Y = scale(ye[0] - ypad, ye[1] + ypad, H - m.b, m.t);

      plotFrame(svg, m, W, H);
      yGrid(svg, niceTicks(ye[0] - ypad, ye[1] + ypad, 6), Y, m, W,
            function (t) { return '$' + fmtNum(t); });
      niceTicks(xe[0] - xpad, xe[1] + xpad, 6).forEach(function (t) {
        txt(svg, X(t), H - m.b + 16, t,
            { fill: C.neutral, 'font-size': 10, 'text-anchor': 'middle' });
      });
      if (ye[0] < 0 && ye[1] > 0) {
        el(svg, 'line', { x1: m.l, y1: Y(0), x2: W - m.r, y2: Y(0),
          stroke: C.neutral, 'stroke-width': 0.7, opacity: 0.4 });
      }

      /* regression line across the observed x range */
      var yA = panel.slope * xe[0] + panel.intercept;
      var yB = panel.slope * xe[1] + panel.intercept;
      el(svg, 'line', { x1: X(xe[0]), y1: Y(yA), x2: X(xe[1]), y2: Y(yB),
        stroke: C.accent, 'stroke-width': 2, 'stroke-dasharray': '6,4',
        opacity: 0.85 });

      var col = C.scatter[idx % C.scatter.length];
      panel.points.forEach(function (p) {
        var dot = el(svg, 'circle', { cx: X(p.x), cy: Y(p.y), r: 6,
          fill: col, 'fill-opacity': 0.85, stroke: C.border,
          'stroke-width': 0.6, cursor: 'pointer' });
        attachTip(dot, function () {
          return '<strong>' + p.name + '</strong><br>' + panel.label + ' ' +
            p.x + ' · <span class="' + moneyClass(p.y) + '">' +
            money(p.y) + '</span>';
        });
      });

      var pStr = panel.p >= 0.001 ? 'p=' + panel.p.toFixed(3) : 'p<0.001';
      var badge = el(svg, 'g');
      el(badge, 'rect', { x: m.l + 8, y: m.t + 8, width: 92, height: 38,
        rx: 5, fill: C.bg, stroke: C.border, opacity: 0.92 });
      txt(badge, m.l + 16, m.t + 24, 'R² = ' + panel.r2.toFixed(3),
          { fill: C.text, 'font-size': 11, 'font-weight': 'bold' });
      txt(badge, m.l + 16, m.t + 39, pStr,
          { fill: C.neutral, 'font-size': 11 });

      txt(svg, (m.l + W - m.r) / 2, H - 8, panel.label,
          { fill: C.text, 'font-size': 11.5, 'text-anchor': 'middle' });
    });
  }

  /* ---- bootstrap ---------------------------------------------------- */
  function ready(fn) {
    if (document.readyState !== 'loading') fn();
    else document.addEventListener('DOMContentLoaded', fn);
  }
  ready(function () {
    var D = window.CHART_DATA || {};
    function go(id, fn, data) {
      var node = document.getElementById(id);
      if (!node || !data) return;
      try {
        fn(node, data);
      } catch (err) {
        node.innerHTML = '<p style="color:#aaa">Chart failed to render: ' +
          err.message + '</p>';
      }
    }
    go('chart-archetypes', renderArchetypes, D.archetypes);
    go('chart-hand-analysis', renderHandAnalysis, D.hand_analysis);
    go('chart-session-trends', renderSessionTrends, D.session_trends);
    go('chart-momentum', renderMomentum, D.momentum);
    go('chart-correlations', renderCorrelations, D.correlations);
    go('chart-profit-drivers', renderProfitDrivers, D.profit_drivers);
  });
})();
