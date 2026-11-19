// Sprinto outreach dashboard: reads data.json (written by `python -m outreach.export_dashboard`) and draws it.
(function () {
  const SVG = 'http://www.w3.org/2000/svg';
  const STAGES = ['Scraped', 'Qualified', 'Contact found', 'Emailed'];
  const LABELS = { emailed: 'Emailed', drafted: 'Drafted', disqualified: 'Disqualified', manual_review: 'Manual review', no_poc: 'No contact', failed: 'Failed', awaiting_model: 'Waiting' };
  const C = { green: '#35c46c', greenSoft: '#bfeccf', orange: '#e8572a', orangeSoft: '#f6c3ae', forest: '#0b3a30', forestInk: '#062720', track: '#e7efea' };
  const stageIdx = (c) => STAGES.indexOf(c.furthest_stage);
  const el = (tag, attrs, text) => {
    const n = document.createElement(tag);
    Object.entries(attrs || {}).forEach(([k, v]) => (k === 'class' ? (n.className = v) : n.setAttribute(k, v)));
    if (text != null) n.textContent = text;
    return n;
  };
  const sv = (tag, attrs, text) => {
    const n = document.createElementNS(SVG, tag);
    Object.entries(attrs || {}).forEach(([k, v]) => n.setAttribute(k, v));
    if (text != null) n.textContent = text;
    return n;
  };
  const mix = (a, b, t) => {           // blend two #rrggbb colors
    const p = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
    const [x, y] = [p(a), p(b)];
    return '#' + x.map((v, i) => Math.round(v + (y[i] - v) * t).toString(16).padStart(2, '0')).join('');
  };

  let DATA = null;
  let picked = null;

  function dropGroup(r) {
    if (/^ICP score/.test(r)) return 'Score below threshold';
    if (/Vanta|Drata|Secureframe|compliance platform|runs compliance/i.test(r)) return 'Already uses a compliance platform';
    if (/competitor/i.test(r)) return 'Compliance vendor (competitor)';
    if (/software|SaaS/i.test(r)) return 'Not a SaaS business';
    if (/SOC 2 and ISO 27001/.test(r)) return 'Already holds SOC 2 + ISO 27001';
    if (/public|acquired/i.test(r)) return 'Public or acquired';
    return 'Other';
  }

  function totals(d) {
    const cs = d.companies;
    const conf = cs.map((c) => +c.contact_confidence).filter((v) => v > 0);
    const drafted = cs.filter((c) => c.email_subject);
    const groups = {};
    cs.filter((c) => c.outcome === 'disqualified').forEach((c) => { const g = dropGroup(c.reason); groups[g] = (groups[g] || 0) + 1; });
    const topDrop = Object.entries(groups).sort((a, b) => b[1] - a[1])[0];
    return {
      researched: cs.length,
      qualified: cs.filter((c) => stageIdx(c) >= 1).length,
      dropped: cs.filter((c) => c.outcome === 'disqualified').length,
      emailed: cs.filter((c) => c.outcome === 'emailed').length,
      contacts: cs.filter((c) => stageIdx(c) >= 2).length,
      pages: cs.reduce((s, c) => s + (+c.extra_pages_read || 0), 0),
      conf: conf.length ? Math.round(conf.reduce((a, b) => a + b, 0) / conf.length) : null,
      drafted: drafted.length,
      firstTry: drafted.filter((c) => +c.draft_attempts === 1).length,
      topDrop,
    };
  }

  // ---------- small drawings ----------
  function miniBars(box, values, colorFor) {
    const max = Math.max(1, ...values);
    box.replaceChildren(...values.map((v, i) => {
      const b = el('i');
      b.style.height = Math.max(6, (v / max) * 42) + 'px';
      b.style.background = colorFor(v, i);
      return b;
    }));
  }

  function gauge(box, pct) {
    const W = 200, H = 112, r = 78, cx = 100, cy = 100, sw = 26;
    const arc = (a0, a1) => {
      const p = (a) => [cx + r * Math.cos(Math.PI - a * Math.PI), cy - r * Math.sin(Math.PI - a * Math.PI)];
      const [x0, y0] = p(a0), [x1, y1] = p(a1);
      return `M${x0},${y0} A${r},${r} 0 0 1 ${x1},${y1}`;
    };
    const f = Math.max(0, Math.min(1, pct / 100));
    const svg = sv('svg', { viewBox: `0 0 ${W} ${H}` });
    svg.appendChild(sv('path', { d: arc(0, 1), stroke: C.forestInk, 'stroke-width': sw, fill: 'none' }));
    if (f > 0) svg.appendChild(sv('path', { d: arc(0, Math.max(0.001, f - 0.012)), stroke: C.green, 'stroke-width': sw, fill: 'none', class: 'val' }));
    box.replaceChildren(svg);
    box.setAttribute('aria-label', `Qualification rate ${Math.round(pct)}%`);
  }

  function ring(box, frac, label, color, track, textColor) {
    const r = 25, c = 2 * Math.PI * r;
    const svg = sv('svg', { viewBox: '0 0 62 62' });
    svg.appendChild(sv('circle', { cx: 31, cy: 31, r, fill: 'none', stroke: track, 'stroke-width': 6 }));
    svg.appendChild(sv('circle', { cx: 31, cy: 31, r, fill: 'none', stroke: color, 'stroke-width': 6, 'stroke-linecap': 'round',
      'stroke-dasharray': c, 'stroke-dashoffset': c * (1 - Math.max(0, Math.min(1, frac))), transform: 'rotate(-90 31 31)', class: 'val' }));
    svg.appendChild(sv('text', { x: 31, y: 35.5, 'text-anchor': 'middle', 'font-size': 12.5, 'font-weight': 700, fill: textColor, 'font-family': 'Plus Jakarta Sans, system-ui, sans-serif' }, label));
    box.replaceChildren(svg);
  }

  function barColor(c, minS, maxS) {
    if (stageIdx(c) >= 1) return C.green;
    const t = maxS > minS ? ((+c.icp_score || 0) - minS) / (maxS - minS) : 1;
    return mix(C.orangeSoft, C.orange, 0.25 + 0.75 * t);
  }

  function textWidth(svg, strings, cls) {
    const g = sv('g', { visibility: 'hidden' });
    svg.appendChild(g);
    let w = 0;
    strings.forEach((s) => { const t = sv('text', { class: cls || '' }, s); g.appendChild(t); w = Math.max(w, t.getComputedTextLength()); });
    g.remove();
    return w;
  }

  // ---------- ICP score chart ----------
  function scoreColors(rows) {
    const dropped = rows.filter((r) => stageIdx(r) < 1).map((r) => +r.icp_score || 0);
    const minS = Math.min(...dropped, 0), maxS = Math.max(...dropped, 1);
    return (r) => barColor(r, minS, maxS);
  }

  function drawScoreList() {
    const rows = DATA.companies.map((c) => ({ ...c, score: +c.icp_score || 0 })).sort((a, b) => b.score - a.score);
    const color = scoreColors(rows);
    document.getElementById('score-list').replaceChildren(...rows.map((r) => {
      const li = el('li', { tabindex: 0 });
      const sw = el('span', { class: 'sw' }); sw.style.background = color(r);
      li.append(sw, el('span', null, r.company), el('span', { class: 'val' }, `– ${r.score}`));
      li.addEventListener('click', () => openTrace(r.domain));
      li.addEventListener('keydown', (e) => { if (e.key === 'Enter') openTrace(r.domain); });
      return li;
    }));
  }

  function drawScoreChart(box, rowH, showNames) {
    const d = DATA, T = d.threshold;
    const reasons = {};
    d.scores.forEach((s) => (reasons[s.domain] = reasons[s.domain] || []).push(s));
    const rows = d.companies.map((c) => ({ ...c, score: +c.icp_score || 0 })).sort((a, b) => b.score - a.score);
    const color = scoreColors(rows);
    box.replaceChildren();
    const W = Math.max(260, box.clientWidth || 420), top = 20, H = rows.length * rowH + top + 2, labelY = H + 14;
    const svg = sv('svg', { viewBox: `0 0 ${W} ${labelY + 4}`, height: labelY + 4, role: 'img', 'aria-label': 'ICP score by company: ' + rows.map((r) => `${r.company} ${r.score}`).join(', ') });
    box.appendChild(svg);
    const left = showNames ? Math.min(textWidth(svg, rows.map((r) => r.company), 'strong') + 14, W * 0.4) : 0;
    const right = textWidth(svg, rows.map((r) => `${r.score}  ${LABELS[r.outcome] || r.outcome}`)) + 10;
    const lo = Math.min(0, ...rows.map((r) => r.score)), hi = Math.max(T + 2, ...rows.map((r) => r.score));
    const x = (v) => left + ((v - lo) / (hi - lo)) * (W - left - right);
    for (let t = Math.ceil(lo); t <= hi; t++) {
      svg.appendChild(sv('line', { x1: x(t), x2: x(t), y1: top - 4, y2: H, stroke: '#edf3ef' }));
      svg.appendChild(sv('text', { x: x(t), y: 10, 'text-anchor': 'middle' }, String(t)));
    }
    const tip = el('div', { class: 'tip' }); tip.hidden = true; box.appendChild(tip);
    const pad = Math.max(4, rowH * 0.18);
    rows.forEach((r, i) => {
      const y = top + i * rowH;
      if (showNames) svg.appendChild(sv('text', { x: 0, y: y + rowH / 2 + 4, class: 'strong' }, r.company));
      const w = Math.max(3, Math.abs(x(r.score) - x(0)));
      const bar = sv('rect', { x: x(Math.min(0, r.score)), y: y + pad, width: w, height: rowH - 2 * pad, rx: 5, class: 'bar', tabindex: 0,
        fill: color(r), 'aria-label': `${r.company}, ${r.score} points, ${LABELS[r.outcome] || r.outcome}` });
      svg.appendChild(bar);
      svg.appendChild(sv('text', { x: Math.max(x(r.score), x(0)) + 6, y: y + rowH / 2 + 4, class: 'strong' }, showNames ? `${r.score}  ${LABELS[r.outcome] || r.outcome}` : String(r.score)));
      const show = (ev) => {
        const head = el('b'); head.append(el('span', null, r.company), el('span', null, `${r.score} pts`));
        const ul = el('ul');
        (reasons[r.domain] || []).forEach((s) => ul.appendChild(el('li', null, `${s.points > 0 ? '+' : ''}${s.points} ${s.reason}`)));
        tip.replaceChildren(head, el('span', { class: 'lvl' }, LABELS[r.outcome] || r.outcome), el('div', null, r.reason), ul);
        tip.hidden = false;
        const bx = box.getBoundingClientRect();
        const px = ev.clientX ? ev.clientX - bx.left + 12 : x(r.score);
        const py = ev.clientY ? ev.clientY - bx.top + 14 : y + rowH;
        tip.style.left = Math.max(0, Math.min(px, bx.width - tip.offsetWidth - 4)) + 'px';
        tip.style.top = Math.min(py, bx.height - tip.offsetHeight) + 'px';
      };
      bar.addEventListener('pointermove', show);
      bar.addEventListener('focus', show);
      bar.addEventListener('pointerleave', () => (tip.hidden = true));
      bar.addEventListener('blur', () => (tip.hidden = true));
      bar.addEventListener('click', () => openTrace(r.domain));
      bar.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openTrace(r.domain); } });
    });
    svg.appendChild(sv('line', { x1: x(T), x2: x(T), y1: top - 6, y2: H, stroke: C.forestInk, 'stroke-dasharray': '4 3', 'stroke-width': 1.3 }));
    svg.appendChild(sv('text', { x: x(T), y: labelY, 'text-anchor': 'middle', class: 'strong' }, `qualify at ${T}`));
  }

  // Horizontal bars for the funnel and drop reasons: rows of {label, value}
  function hbars(box, rows, colorFor, aria) {
    box.replaceChildren();
    if (!rows.length) { box.appendChild(el('p', { class: 'sub' }, 'Nothing to show for this run.')); return; }
    const W = Math.max(240, box.clientWidth || 360), rowH = 34, H = rows.length * rowH;
    const svg = sv('svg', { viewBox: `0 0 ${W} ${H}`, height: H, role: 'img', 'aria-label': aria });
    box.appendChild(svg);
    const left = Math.min(textWidth(svg, rows.map((r) => r.label), 'strong') + 14, W * 0.55);
    const max = Math.max(1, ...rows.map((r) => r.value));
    const span = W - left - 30;
    rows.forEach((r, i) => {
      const y = i * rowH, w = Math.max(3, (r.value / max) * span);
      svg.appendChild(sv('text', { x: 0, y: y + rowH / 2 + 4, class: 'strong' }, r.label));
      svg.appendChild(sv('rect', { x: left, y: y + 8, width: w, height: rowH - 16, rx: 5, fill: colorFor(i) }));
      svg.appendChild(sv('text', { x: left + w + 6, y: y + rowH / 2 + 4, class: 'strong' }, String(r.value)));
    });
  }

  // ---------- trace + table ----------
  function drawCompanyList() {
    const order = { emailed: 0, drafted: 1, no_poc: 2, manual_review: 3, disqualified: 4, failed: 5 };
    const rows = [...DATA.companies].sort((a, b) => (order[a.outcome] ?? 9) - (order[b.outcome] ?? 9) || (+b.icp_score || 0) - (+a.icp_score || 0));
    document.getElementById('co-list').replaceChildren(...rows.map((c) => {
      const li = el('li');
      const b = el('button', { type: 'button', 'aria-current': String(c.domain === picked) });
      b.append(el('span', { class: 'co-name' }, c.company), el('span', { class: 'co-score' }, `${+c.icp_score || 0} pts`),
        el('span', { class: 'badge', 'data-o': c.outcome }, LABELS[c.outcome] || c.outcome));
      b.addEventListener('click', () => { picked = c.domain; drawCompanyList(); drawDetail(); });
      li.appendChild(b);
      return li;
    }));
  }

  function drawDetail() {
    const box = document.getElementById('detail');
    const c = DATA.companies.find((r) => r.domain === picked) || DATA.companies[0];
    if (!c) return;
    const head = el('div', { class: 'trace-title' });
    head.append(el('h2', null, c.company), el('span', { class: 'badge', 'data-o': c.outcome }, LABELS[c.outcome] || c.outcome), el('span', { class: 'fine' }, c.domain));

    const left = el('div');
    left.appendChild(el('h3', null, 'Decision'));
    const dl = el('dl');
    const contact = c.contact_role ? `${c.contact_role} (${c.contact_source}${c.contact_confidence ? `, ${c.contact_confidence}% confidence` : ''})` : '—';
    [['ICP score', String(+c.icp_score || 0)], ['Model fit', c.fit || '—'], ['Why', c.reason], ['Why now', c.why_now || '—'],
     ['Certifications', c.certifications || 'None found'], ['Contact', contact], ['Email subject', c.email_subject || '—'], ['Hook', c.hook_fact || '—'],
     ['Draft attempts', c.draft_attempts ? String(c.draft_attempts) : '—']]
      .forEach(([k, v]) => { dl.appendChild(el('dt', null, k)); dl.appendChild(el('dd', null, v)); });
    left.appendChild(dl);

    const right = el('div');
    right.appendChild(el('h3', null, 'Score points'));
    const pts = el('ul', { class: 'list' });
    const mine = DATA.scores.filter((s) => s.domain === c.domain);
    if (!mine.length) pts.appendChild(el('li', null, 'No points scored'));
    mine.forEach((s) => {
      const li = el('li');
      li.appendChild(el('span', { class: 'pts ' + (s.points > 0 ? 'pos' : s.points < 0 ? 'neg' : '') }, `${s.points > 0 ? '+' : ''}${s.points}`));
      li.appendChild(el('span', null, s.reason));
      pts.appendChild(li);
    });
    right.appendChild(pts);
    right.appendChild(el('h3', null, 'Agent loop'));
    const steps = el('ul', { class: 'list' });
    const mySteps = DATA.loop.filter((s) => s.domain === c.domain);
    if (!mySteps.length) steps.appendChild(el('li', null, 'No steps recorded'));
    mySteps.forEach((s) => {
      const li = el('li');
      li.appendChild(el('span', { class: 'pts' }, String(s.iteration)));
      const t = el('span', { class: 'step' });
      t.appendChild(el('b', null, s.action));
      if (s.url) t.appendChild(document.createTextNode(' ' + s.url));
      if (s.result) t.appendChild(document.createTextNode(' → ' + s.result));
      li.appendChild(t);
      steps.appendChild(li);
    });
    right.appendChild(steps);
    const body = el('div', { class: 'detail' });
    body.append(left, right);
    box.replaceChildren(head, body);
  }

  function openTrace(domain) {
    picked = domain;
    if (location.hash === '#trace') { drawCompanyList(); drawDetail(); }
    else location.hash = 'trace';
  }

  function drawTable() {
    const order = { emailed: 0, drafted: 1, no_poc: 2, manual_review: 3, disqualified: 4, failed: 5 };
    const rows = [...DATA.companies].sort((a, b) => (order[a.outcome] ?? 9) - (order[b.outcome] ?? 9) || (+b.icp_score || 0) - (+a.icp_score || 0));
    document.getElementById('rows').replaceChildren(...rows.map((c) => {
      const tr = el('tr', { tabindex: 0 });
      const o = el('td'); o.appendChild(el('span', { class: 'badge', 'data-o': c.outcome }, LABELS[c.outcome] || c.outcome));
      tr.append(el('td', null, c.company), o, el('td', { class: 'num' }, c.icp_score), el('td', { class: 'why' }, c.reason), el('td', null, c.contact_role || '—'), el('td', null, c.email_subject || '—'));
      tr.addEventListener('click', () => openTrace(c.domain));
      tr.addEventListener('keydown', (e) => { if (e.key === 'Enter') openTrace(c.domain); });
      return tr;
    }));
  }

  // ---------- pages ----------
  const VIEWS = ['dashboard', 'qualification', 'trace', 'companies', 'how'];
  let T = null;

  const LEDES = {
    dashboard: () => [el('b', null, String(T.qualified)), ` of ${T.researched} companies fit Sprinto's ICP; `, el('b', null, String(T.emailed)), ` personalised email${T.emailed === 1 ? ' is' : 's are'} waiting for review.`],
    qualification: () => [`Every company is scored against the ICP; `, el('b', null, String(T.dropped)), ` were dropped and `, el('b', null, String(T.qualified)), ` qualified at ${DATA.threshold}+ points.`],
    trace: () => ['Every decision the system made for one company: why it qualified, who to contact, and what the agent read.'],
    companies: () => [el('b', null, String(T.researched)), ' companies in this run. Click a row to open its decision.'],
    how: () => ['The 7 steps, the ICP rules and where the numbers come from.'],
  };

  function drawView(name) {
    if (!DATA) return;
    if (name === 'dashboard') { drawScoreList(); drawScoreChart(document.getElementById('score-chart'), 21, false); }
    if (name === 'qualification') {
      drawScoreChart(document.getElementById('q-score-chart'), 40, true);
      hbars(document.getElementById('funnel-chart'),
        [['Scraped', T.researched], ['Qualified', T.qualified], ['Contact found', T.contacts], ['Emailed', T.emailed]].map(([label, value]) => ({ label, value })),
        () => C.green, `Companies reaching each step: scraped ${T.researched}, qualified ${T.qualified}, contact found ${T.contacts}, emailed ${T.emailed}`);
      const groups = {};
      DATA.companies.filter((c) => c.outcome === 'disqualified').forEach((c) => { const g = dropGroup(c.reason); groups[g] = (groups[g] || 0) + 1; });
      const drops = Object.entries(groups).map(([label, value]) => ({ label, value })).sort((a, b) => b.value - a.value);
      hbars(document.getElementById('drop-chart'), drops, (i) => mix(C.orange, C.orangeSoft, Math.min(1, i * 0.35)),
        'Disqualified companies by reason: ' + drops.map((r) => `${r.label} ${r.value}`).join(', '));
    }
    if (name === 'trace') { drawCompanyList(); drawDetail(); }
    if (name === 'companies') drawTable();
  }

  function route() {
    const name = VIEWS.includes(location.hash.slice(1)) ? location.hash.slice(1) : 'dashboard';
    VIEWS.forEach((v) => { document.getElementById('view-' + v).hidden = v !== name; });
    document.querySelectorAll('[data-nav]').forEach((a) => {
      const on = a.dataset.nav === name;
      a.classList.toggle('active', on);
      if (on) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current');
    });
    const title = document.getElementById('view-' + name).dataset.title;
    document.getElementById('page-title').textContent = name === 'dashboard' ? 'Outreach dashboard' : title;
    document.title = `${title} · Sprinto Outreach Pipeline`;
    if (T) document.getElementById('page-lede').replaceChildren(...LEDES[name]());
    document.querySelector('.panel').scrollTop = 0;
    drawView(name);
  }

  function render() {
    const d = DATA;
    T = totals(d);
    document.querySelectorAll('[data-k]').forEach((n) => { n.textContent = String(T[n.dataset.k] ?? '—'); });
    document.querySelectorAll('.thr').forEach((n) => { n.textContent = d.threshold; });
    const gen = new Date(d.generated);
    document.getElementById('run-name').textContent = d.run;
    document.getElementById('run-date').textContent = 'Exported ' + gen.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' });

    const byScore = [...d.companies].sort((a, b) => (+b.icp_score || 0) - (+a.icp_score || 0));
    miniBars(document.getElementById('mini-researched'), byScore.map((c) => +c.icp_score || 0), (v, i) => (stageIdx(byScore[i]) >= 1 ? C.green : C.greenSoft));
    const droppedRows = byScore.filter((c) => c.outcome === 'disqualified');
    miniBars(document.getElementById('mini-dropped'), droppedRows.map((c) => +c.icp_score || 0), (v, i) => (i % 2 ? C.orangeSoft : C.orange));
    const reached = d.companies.filter((c) => +c.contact_confidence > 0);
    miniBars(document.getElementById('mini-emailed'), reached.map((c) => +c.contact_confidence), (v, i) => (i % 2 ? C.greenSoft : C.green));

    const setDelta = (id, arrow, strong, rest) => { const n = document.getElementById(id); n.replaceChildren(el('b', null, `${arrow} ${strong}`), document.createTextNode(' ' + rest)); };
    setDelta('d-researched', '↗', `${T.qualified} qualified`, `at score ${d.threshold}+`);
    if (T.topDrop) setDelta('d-dropped', '↘', String(T.topDrop[1]), T.topDrop[0].toLowerCase());
    setDelta('d-emailed', '↗', `${T.emailed} of ${T.qualified}`, 'qualified companies reached');

    const rate = T.researched ? (T.qualified / T.researched) * 100 : 0;
    document.getElementById('rate').textContent = Math.round(rate);
    gauge(document.getElementById('gauge'), rate);

    document.getElementById('conf').textContent = T.conf ?? '—';
    document.getElementById('conf-legend').replaceChildren(...reached.map((c) => {
      const li = el('li');
      li.append(el('span', { class: 'dot' }), el('span', null, `${c.company} · ${c.contact_role}`), el('span', null, `${c.contact_confidence}%`));
      return li;
    }));

    const cap = T.researched * 4;
    ring(document.getElementById('ring-pages'), cap ? T.pages / cap : 0, String(T.pages), C.orange, '#24463d', '#ffffff');
    ring(document.getElementById('ring-drafts'), T.drafted ? T.firstTry / T.drafted : 0, `${T.firstTry}/${T.drafted}`, C.green, '#cfe7da', '#0f1f1a');
    document.getElementById('draft-note').textContent = `${T.firstTry} of ${T.drafted} drafts passed every check (name, length, one ask, real hook) on the first try`;
    document.getElementById('chips').replaceChildren(...d.companies.filter((c) => c.outcome === 'emailed').map((c) => el('span', { class: 'chip' }, c.email_subject)));
    document.getElementById('foot').textContent = `Data: data.json from run "${d.run}", exported ${gen.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })}. Contacts are listed by role only.`;

    picked = picked || (d.companies.find((c) => c.outcome === 'emailed') || d.companies[0] || {}).domain;
    route();
  }

  addEventListener('hashchange', route);
  route();

  fetch('data.json', { cache: 'no-store' })
    .then((r) => { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
    .then((d) => { DATA = d; render(); })
    .catch((e) => { document.getElementById('page-lede').textContent = `Couldn't load data.json (${e.message}). Run python -m outreach.export_dashboard and redeploy.`; });

  let rt;
  addEventListener('resize', () => { clearTimeout(rt); rt = setTimeout(() => DATA && drawView(location.hash.slice(1) || 'dashboard'), 120); });
})();
