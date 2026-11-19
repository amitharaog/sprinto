// Sprinto outreach dashboard: reads data.json (written by `python -m outreach.export_dashboard`) and draws it.
// Each fact is shown on exactly one page; pages are switched from the sidebar (#overview, #qualification, ...).
(function () {
  const SVG = 'http://www.w3.org/2000/svg';
  const STAGES = ['Scraped', 'Qualified', 'Contact found', 'Emailed'];
  const LABELS = { emailed: 'Emailed', drafted: 'Drafted', disqualified: 'Disqualified', manual_review: 'Manual review', no_poc: 'No contact', failed: 'Failed', awaiting_model: 'Waiting' };
  const C = { green: '#35c46c', greenSoft: '#bfeccf', orange: '#e8572a', orangeSoft: '#f6c3ae', forestInk: '#062720', grid: '#edf3ef' };
  const VIEWS = ['overview', 'qualification', 'value', 'future', 'trace'];

  let DATA = null;
  let picked = null;

  // ---------- helpers ----------
  const stageIdx = (c) => STAGES.indexOf(c.furthest_stage);
  const isQualified = (c) => stageIdx(c) >= 1;
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
  const mix = (a, b, t) => {
    const p = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
    const [x, y] = [p(a), p(b)];
    return '#' + x.map((v, i) => Math.round(v + (y[i] - v) * t).toString(16).padStart(2, '0')).join('');
  };
  const money = (v) => {
    v = +v || 0;
    if (v >= 1e6) return '$' + (v / 1e6).toFixed(v >= 1e7 ? 0 : 1) + 'M';
    if (v >= 1e4) return '$' + (v / 1e3).toFixed(v >= 1e5 ? 0 : 1).replace(/\.0$/, '') + 'k';
    return '$' + Math.round(v).toLocaleString('en-US');
  };
  const pct = (p) => `${Math.round((+p || 0) * 100)}%`;
  const fmtDate = (iso) => (iso ? new Date(iso + 'T00:00:00Z').toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' }) : '—');
  // "ICP score 6 >= 5. B2B HR/payroll SaaS..." -> "B2B HR/payroll SaaS..." (the score is shown separately)
  const plainReason = (r) => (r || '').replace(/^ICP score \d+ >= \d+\.\s*/, '');
  const textWidth = (svg, strings, cls) => {
    const g = sv('g', { visibility: 'hidden' });
    svg.appendChild(g);
    let w = 0;
    strings.forEach((s) => { const t = sv('text', { class: cls || '' }, s); g.appendChild(t); w = Math.max(w, t.getComputedTextLength()); });
    g.remove();
    return w;
  };
  const clickable = (node, domain) => {
    node.addEventListener('click', () => openTrace(domain));
    node.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openTrace(domain); } });
  };

  function totals() {
    const cs = DATA.companies;
    return {
      researched: cs.length,
      qualified: cs.filter(isQualified).length,
      emailed: cs.filter((c) => c.outcome === 'emailed').length,
      recheck: cs.filter((c) => c.future_label === 'Re-check now').length,
    };
  }
  const valued = () => DATA.companies.filter((c) => +c.acv_mid > 0).sort((a, b) => (+b.expected_value) - (+a.expected_value));

  // ---------- Overview ----------
  function drawOverview() {
    const rows = valued();
    const tb = document.getElementById('lead-rows');
    if (!rows.length) { tb.replaceChildren(el('tr', null).appendChild(el('td', { colspan: 5, class: 'muted' }, 'No qualified companies in this run.')).parentNode); return; }
    tb.replaceChildren(...rows.map((c) => {
      const tr = el('tr', { tabindex: 0 });
      const co = el('td'); co.append(el('b', null, c.company), el('span', { class: 'cell-sub' }, c.email_subject ? `“${c.email_subject}”` : ''));
      const who = el('td'); who.append(document.createTextNode(c.contact_role || '—'), el('span', { class: 'cell-sub' }, c.contact_confidence ? `${c.contact_confidence}% confidence` : ''));
      const ev = el('td', { class: 'num' }); ev.appendChild(el('b', null, money(c.expected_value)));
      tr.append(co, who, el('td', { class: 'muted' }, c.why_now || '—'), el('td', { class: 'num' }, `${money(c.acv_low)}–${money(c.acv_high)}`), ev);
      clickable(tr, c.domain);
      return tr;
    }));
  }

  // ---------- Qualification ----------
  function scoreColor(rows) {
    const dropped = rows.filter((r) => !isQualified(r)).map((r) => +r.icp_score || 0);
    const lo = Math.min(...dropped, 0), hi = Math.max(...dropped, 1);
    return (r) => (isQualified(r) ? C.green : mix(C.orangeSoft, C.orange, 0.25 + 0.75 * (hi > lo ? ((+r.icp_score || 0) - lo) / (hi - lo) : 1)));
  }

  function drawScoreChart() {
    const box = document.getElementById('score-chart'), T = DATA.threshold;
    const reasons = {};
    DATA.scores.forEach((s) => (reasons[s.domain] = reasons[s.domain] || []).push(s));
    const rows = DATA.companies.map((c) => ({ ...c, score: +c.icp_score || 0 })).sort((a, b) => b.score - a.score);
    const color = scoreColor(rows);
    box.replaceChildren();
    const W = Math.max(280, box.clientWidth || 600), rowH = 40, top = 20, H = rows.length * rowH + top, labelY = H + 14;
    const svg = sv('svg', { viewBox: `0 0 ${W} ${labelY + 4}`, height: labelY + 4, role: 'img', 'aria-label': 'ICP score by company: ' + rows.map((r) => `${r.company} ${r.score}`).join(', ') });
    box.appendChild(svg);
    const outcome = (r) => LABELS[r.outcome] || r.outcome;
    const left = Math.min(textWidth(svg, rows.map((r) => r.company), 'strong') + 14, W * 0.35);
    const right = textWidth(svg, rows.map((r) => `${r.score}  ${outcome(r)}`)) + 10;
    const lo = Math.min(0, ...rows.map((r) => r.score)), hi = Math.max(T + 2, ...rows.map((r) => r.score));
    const x = (v) => left + ((v - lo) / (hi - lo)) * (W - left - right);
    for (let t = Math.ceil(lo); t <= hi; t++) {
      svg.appendChild(sv('line', { x1: x(t), x2: x(t), y1: top - 4, y2: H, stroke: C.grid }));
      svg.appendChild(sv('text', { x: x(t), y: 10, 'text-anchor': 'middle' }, String(t)));
    }
    const tip = el('div', { class: 'tip' }); tip.hidden = true; box.appendChild(tip);
    rows.forEach((r, i) => {
      const y = top + i * rowH;
      svg.appendChild(sv('text', { x: 0, y: y + rowH / 2 + 4, class: 'strong' }, r.company));
      const bar = sv('rect', { x: x(Math.min(0, r.score)), y: y + 9, width: Math.max(3, Math.abs(x(r.score) - x(0))), height: rowH - 18, rx: 5,
        class: 'bar', tabindex: 0, fill: color(r), 'aria-label': `${r.company}, ${r.score} points, ${outcome(r)}` });
      svg.appendChild(bar);
      svg.appendChild(sv('text', { x: Math.max(x(r.score), x(0)) + 6, y: y + rowH / 2 + 4, class: 'strong' }, `${r.score}  ${outcome(r)}`));
      const show = (ev) => {
        const head = el('b'); head.append(el('span', null, r.company), el('span', null, `${r.score} pts`));
        const ul = el('ul');
        (reasons[r.domain] || []).forEach((s) => ul.appendChild(el('li', null, `${s.points > 0 ? '+' : ''}${s.points} ${s.reason}`)));
        tip.replaceChildren(head, el('div', null, plainReason(r.reason)), ul);
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
      clickable(bar, r.domain);
    });
    svg.appendChild(sv('line', { x1: x(T), x2: x(T), y1: top - 6, y2: H, stroke: C.forestInk, 'stroke-dasharray': '4 3', 'stroke-width': 1.3 }));
    svg.appendChild(sv('text', { x: x(T), y: labelY, 'text-anchor': 'middle', class: 'strong' }, `qualify at ${T}`));
  }

  function dropGroup(r) {
    if (/^ICP score/.test(r)) return 'Score below threshold';
    if (/Vanta|Drata|Secureframe|compliance platform|runs compliance/i.test(r)) return 'Already on a compliance platform';
    if (/competitor/i.test(r)) return 'Compliance vendor';
    if (/software|SaaS/i.test(r)) return 'Not a SaaS business';
    if (/SOC 2 and ISO 27001/.test(r)) return 'Holds SOC 2 + ISO 27001';
    if (/public|acquired/i.test(r)) return 'Public or acquired';
    return 'Other';
  }

  function drawDropChart() {
    const box = document.getElementById('drop-chart');
    const groups = {};
    DATA.companies.filter((c) => c.outcome === 'disqualified').forEach((c) => { (groups[dropGroup(c.reason)] = groups[dropGroup(c.reason)] || []).push(c.company); });
    const rows = Object.entries(groups).map(([label, names]) => ({ label, names, value: names.length })).sort((a, b) => b.value - a.value);
    box.replaceChildren();
    if (!rows.length) { box.appendChild(el('p', { class: 'fine' }, 'No companies were dropped.')); return; }
    const W = Math.max(240, box.clientWidth || 360), rowH = 52, H = rows.length * rowH;
    const svg = sv('svg', { viewBox: `0 0 ${W} ${H}`, height: H, role: 'img', 'aria-label': 'Dropped companies by reason: ' + rows.map((r) => `${r.label} ${r.value}`).join(', ') });
    box.appendChild(svg);
    const max = Math.max(...rows.map((r) => r.value));
    rows.forEach((r, i) => {
      const y = i * rowH, w = Math.max(4, (r.value / max) * (W - 30));
      svg.appendChild(sv('text', { x: 0, y: y + 13, class: 'strong' }, r.label));
      svg.appendChild(sv('rect', { x: 0, y: y + 20, width: w, height: 12, rx: 6, fill: mix(C.orange, C.orangeSoft, Math.min(1, i * 0.35)) }));
      svg.appendChild(sv('text', { x: w + 6, y: y + 30, class: 'strong' }, String(r.value)));
      svg.appendChild(sv('text', { x: 0, y: y + 46 }, r.names.join(', ')));
    });
  }

  // ---------- Pipeline value ----------
  function drawValue() {
    const rows = valued(), sum = (k) => rows.reduce((t, c) => t + (+c[k] || 0), 0);
    const a = DATA.value_assumptions;
    document.getElementById('v-acv').textContent = money(sum('acv_mid'));
    document.getElementById('v-acv-range').textContent = rows.length ? `Range ${money(sum('acv_low'))}–${money(sum('acv_high'))}, midpoint shown` : 'No qualified companies';
    document.getElementById('v-ev').textContent = money(sum('expected_value'));
    document.getElementById('v-3y').textContent = money(sum('three_year_value'));
    document.getElementById('v-3y-note').textContent = `If all close, ${pct(a.annual_retention)} kept each year`;

    const box = document.getElementById('value-chart');
    box.replaceChildren();
    if (rows.length) {
      const W = Math.max(280, box.clientWidth || 600), rowH = 32, top = 18, H = rows.length * rowH + top;
      const svg = sv('svg', { viewBox: `0 0 ${W} ${H}`, height: H, role: 'img',
        'aria-label': 'Estimated annual contract value: ' + rows.map((c) => `${c.company} ${money(c.acv_low)} to ${money(c.acv_high)}`).join(', ') });
      box.appendChild(svg);
      const left = Math.min(textWidth(svg, rows.map((c) => c.company), 'strong') + 14, W * 0.3);
      const ranges = rows.map((c) => `${money(c.acv_low)}–${money(c.acv_high)}`);
      const right = textWidth(svg, ranges) + 12;
      const max = Math.max(...rows.map((c) => +c.acv_high)) * 1.05;
      const x = (v) => left + (v / max) * (W - left - right);
      const step = max > 60000 ? 20000 : 10000;
      for (let t = 0; t <= max; t += step) {
        svg.appendChild(sv('line', { x1: x(t), x2: x(t), y1: top - 4, y2: H, stroke: C.grid }));
        svg.appendChild(sv('text', { x: x(t), y: 10, 'text-anchor': 'middle' }, money(t)));
      }
      rows.forEach((c, i) => {
        const cy = top + i * rowH + rowH / 2;
        const g = sv('g', { class: 'bar', tabindex: 0, 'aria-label': `${c.company}: ${ranges[i]} a year` });
        g.appendChild(sv('text', { x: 0, y: cy + 4, class: 'strong' }, c.company));
        g.appendChild(sv('rect', { x: x(+c.acv_low), y: cy - 6, width: Math.max(4, x(+c.acv_high) - x(+c.acv_low)), height: 12, rx: 6, fill: C.greenSoft }));
        g.appendChild(sv('circle', { cx: x(+c.acv_mid), cy, r: 6, fill: C.green, stroke: '#fff', 'stroke-width': 2 }));
        g.appendChild(sv('text', { x: x(+c.acv_high) + 8, y: cy + 4 }, ranges[i]));
        clickable(g, c.domain);
        svg.appendChild(g);
      });
    }

    document.getElementById('value-rows').replaceChildren(...rows.map((c) => {
      const tr = el('tr', { tabindex: 0 });
      const ev = el('td', { class: 'num' }); ev.appendChild(el('b', null, money(c.expected_value)));
      tr.append(el('td', null, c.company), el('td', { class: 'num' }, c.headcount ? String(c.headcount) : '—'),
        el('td', { class: 'num' }, c.raised_usd ? money(c.raised_usd) : '—'), el('td', null, (c.frameworks_new || '—').replace(/; /g, ', ')),
        el('td', { class: 'num' }, pct(c.win_probability)), ev, el('td', { class: 'num' }, money(c.three_year_value)));
      clickable(tr, c.domain);
      return tr;
    }));

    let prev = 0;
    document.getElementById('a-price').replaceChildren(...a.price_first_framework.map((b) => {
      const label = b.max_employees ? `${prev + 1}–${b.max_employees} employees` : `${prev + 1}+ employees`;
      prev = b.max_employees || prev;
      const li = el('li'); li.append(el('span', null, label), el('span', null, `$${b.low / 1000}k–$${b.high / 1000}k`)); return li;
    }));
    document.getElementById('a-uplift').textContent = `+${pct(a.extra_framework_uplift[0])} to +${pct(a.extra_framework_uplift[1])} of the first`;
    document.getElementById('a-win').replaceChildren(...Object.entries(a.win_probability).map(([fit, p]) => {
      const li = el('li'); li.append(el('span', null, `Fit: ${fit}`), el('span', null, pct(p))); return li;
    }), (() => { const li = el('li'); li.append(el('span', null, 'Per point above threshold'), el('span', null, `+${Math.round(a.win_probability_per_extra_point * 100)} pt`)); return li; })());
    document.getElementById('a-ret').textContent = 'Sources: Vendr-based Sprinto median ~$15k/yr; ISO 27001 on SOC 2 adds 40–70%. Company size and funding: Hunter.io.';
  }

  // ---------- Future leads ----------
  function drawFuture() {
    const order = { high: 0, medium: 1, low: 2, none: 3 };
    const cards = DATA.companies.filter((c) => c.future_category && c.future_category !== 'lead_now')
      .sort((a, b) => (order[a.future_priority] ?? 9) - (order[b.future_priority] ?? 9) || (+b.icp_score || 0) - (+a.icp_score || 0));
    document.getElementById('future-cards').replaceChildren(...cards.map((c) => {
      const card = el('article', { class: 'card fcard', 'data-p': c.future_priority || 'none', tabindex: 0 });
      const head = el('div', { class: 'fhead' });
      head.append(el('h2', null, c.company), el('span', { class: 'badge', 'data-p': c.future_priority }, c.future_label));
      const meta = [`Score ${+c.icp_score || 0}`];
      if (c.points_short !== '' && c.points_short != null) meta.push(`${c.points_short} short`);
      if (c.recheck_date && c.future_label !== 'Re-check now') meta.push(`re-check ${fmtDate(c.recheck_date)}`);
      card.append(head, el('p', { class: 'fmeta' }, meta.join(' · ')), el('p', { class: 'fnote' }, c.future_note));
      const items = c.future_category === 'near_miss'
        ? (c.company_data || '').split(' | ').filter(Boolean)            // near misses: the company-specific evidence
        : (c.watch_for || '').split(' | ').filter(Boolean).slice(0, 3);   // others: their own triggers
      if (items.length) { const ul = el('ul'); items.forEach((t) => ul.appendChild(el('li', null, t))); card.appendChild(ul); }
      clickable(card, c.domain);
      return card;
    }));
    document.getElementById('signals').replaceChildren(...(DATA.near_miss_signals || []).map((s) => {
      const li = el('li'); li.append(el('span', null, s.signal), el('span', null, `+${s.points}`)); return li;
    }));
  }

  // ---------- Decision trace ----------
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

    const facts = [['Decision', plainReason(c.reason)]];
    if (c.why_now) facts.push(['Why now', c.why_now]);
    facts.push(['Certifications', c.certifications || 'None found']);
    if (c.headcount) facts.push(['Company', `${c.headcount} employees${c.raised_usd ? `, ${money(c.raised_usd)} raised` : ''}`]);
    if (c.acv_mid) facts.push(['Value', `${money(c.acv_low)}–${money(c.acv_high)} a year, ${money(c.expected_value)} expected (${pct(c.win_probability)} win)`]);
    if (c.contact_role) facts.push(['Contact', `${c.contact_role} · ${c.contact_source}${c.contact_confidence ? `, ${c.contact_confidence}%` : ''}`]);
    if (c.email_subject) facts.push(['Email', `“${c.email_subject}”`]);
    if (c.hook_fact) facts.push(['Hook', c.hook_fact]);
    if (c.future_category && c.future_category !== 'lead_now') facts.push(['Next', `${c.future_label}${c.recheck_date && c.future_label !== 'Re-check now' ? `, ${fmtDate(c.recheck_date)}` : ''}`]);

    const left = el('div');
    left.appendChild(el('h3', null, 'Decision'));
    const dl = el('dl');
    facts.forEach(([k, v]) => { dl.appendChild(el('dt', null, k)); dl.appendChild(el('dd', null, v)); });
    left.appendChild(dl);

    const right = el('div');
    right.appendChild(el('h3', null, `Score · ${+c.icp_score || 0} points`));
    const pts = el('ul', { class: 'list' });
    const mine = DATA.scores.filter((s) => s.domain === c.domain);
    if (!mine.length) pts.appendChild(el('li', null, 'No points scored'));
    mine.forEach((s) => {
      const li = el('li');
      li.append(el('span', { class: 'pts ' + (s.points > 0 ? 'pos' : s.points < 0 ? 'neg' : '') }, `${s.points > 0 ? '+' : ''}${s.points}`), el('span', null, s.reason));
      pts.appendChild(li);
    });
    right.appendChild(pts);
    right.appendChild(el('h3', null, 'Agent loop'));
    const steps = el('ul', { class: 'list' });
    DATA.loop.filter((s) => s.domain === c.domain).forEach((s) => {
      const li = el('li');
      const t = el('span', { class: 'step' });
      t.appendChild(el('b', null, s.action));
      if (s.url) t.appendChild(document.createTextNode(' ' + s.url));
      if (s.result) t.appendChild(document.createTextNode(' → ' + s.result));
      li.append(el('span', { class: 'pts' }, String(s.iteration)), t);
      steps.appendChild(li);
    });
    right.appendChild(steps);
    const body = el('div', { class: 'detail' });
    body.append(left, right);
    box.replaceChildren(head, body);
  }

  function openTrace(domain) {
    picked = domain;
    if (location.hash === '#trace') { drawCompanyList(); drawDetail(); } else location.hash = 'trace';
  }

  // ---------- routing ----------
  function drawView(name) {
    if (!DATA) return;
    if (name === 'overview') drawOverview();
    if (name === 'qualification') { drawScoreChart(); drawDropChart(); }
    if (name === 'value') drawValue();
    if (name === 'future') drawFuture();
    if (name === 'trace') { drawCompanyList(); drawDetail(); }
  }

  function route() {
    const name = VIEWS.includes(location.hash.slice(1)) ? location.hash.slice(1) : 'overview';
    VIEWS.forEach((v) => { document.getElementById('view-' + v).hidden = v !== name; });
    document.querySelectorAll('[data-nav]').forEach((a) => {
      const on = a.dataset.nav === name;
      a.classList.toggle('active', on);
      if (on) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current');
    });
    const title = document.getElementById('view-' + name).dataset.title;
    document.getElementById('page-title').textContent = title;
    document.title = `${title} · Sprinto Outreach Pipeline`;
    document.querySelector('.panel').scrollTop = 0;
    drawView(name);
  }

  function render() {
    const t = totals();
    document.querySelectorAll('[data-k]').forEach((n) => { n.textContent = String(t[n.dataset.k] ?? '—'); });
    document.querySelectorAll('.thr').forEach((n) => { n.textContent = DATA.threshold; });
    document.getElementById('run-name').textContent = DATA.run;
    document.getElementById('run-date').textContent = 'Exported ' + new Date(DATA.generated).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' });
    picked = picked || (valued()[0] || DATA.companies[0] || {}).domain;
    route();
  }

  addEventListener('hashchange', route);
  route();
  fetch('data.json', { cache: 'no-store' })
    .then((r) => { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
    .then((d) => { DATA = d; render(); })
    .catch((e) => { document.getElementById('page-title').textContent = `Couldn't load data.json (${e.message})`; });

  let rt;
  addEventListener('resize', () => { clearTimeout(rt); rt = setTimeout(() => drawView(location.hash.slice(1) || 'overview'), 120); });
})();
