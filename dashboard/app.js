// Sprinto outreach dashboard: reads data.json (written by `python -m outreach.export_dashboard`) and draws it.
(function () {
  const SVG = 'http://www.w3.org/2000/svg';
  const STAGES = ['Scraped', 'Qualified', 'Contact found', 'Emailed'];
  const LABELS = { emailed: 'Emailed', drafted: 'Drafted', disqualified: 'Disqualified', manual_review: 'Manual review', no_poc: 'No contact', failed: 'Failed', awaiting_model: 'Waiting' };
  const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
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

  let DATA = null;
  let picked = null;

  function dropGroup(r) {
    if (/^ICP score/.test(r)) return 'Score below threshold';
    if (/Vanta|Drata|Secureframe|compliance platform|runs compliance/i.test(r)) return 'Already uses a compliance platform';
    if (/competitor/i.test(r)) return 'Compliance vendor (competitor)';
    if (/software|SaaS/i.test(r)) return 'Not a SaaS business';
    if (/SOC 2 and ISO 27001/.test(r)) return 'Already holds SOC 2 + ISO 27001';
    if (/public|acquired/i.test(r)) return 'Public or acquired';
    if (/consumers/i.test(r)) return 'Consumer-only';
    return 'Other';
  }

  function totals(d) {
    const cs = d.companies;
    return {
      researched: cs.length,
      scraped: cs.filter((c) => stageIdx(c) >= 0).length,
      qualified: cs.filter((c) => stageIdx(c) >= 1).length,
      contacts: cs.filter((c) => stageIdx(c) >= 2).length,
      drafted: cs.filter((c) => c.email_subject).length,
      emailed: cs.filter((c) => c.outcome === 'emailed').length,
      pages: cs.reduce((s, c) => s + (+c.extra_pages_read || 0), 0),
    };
  }

  function textWidth(svg, strings, cls) {
    const g = sv('g', { visibility: 'hidden' });
    svg.appendChild(g);
    let w = 0;
    strings.forEach((s) => { const t = sv('text', { class: cls || '' }, s); g.appendChild(t); w = Math.max(w, t.getComputedTextLength()); });
    g.remove();
    return w;
  }

  // Horizontal bars: rows of {label, value}
  function hbars(box, rows, color, aria) {
    box.replaceChildren();
    if (!rows.length) { box.appendChild(el('div', { class: 'empty' }, 'Nothing to show for this run.')); return; }
    const W = Math.max(260, box.clientWidth || 400), rowH = 34, H = rows.length * rowH + 4;
    const svg = sv('svg', { viewBox: `0 0 ${W} ${H}`, height: H, role: 'img', 'aria-label': aria });
    box.appendChild(svg);
    const left = Math.min(textWidth(svg, rows.map((r) => r.label), 'strong') + 14, W * 0.55);
    const max = Math.max(1, ...rows.map((r) => r.value));
    const span = W - left - 34;
    rows.forEach((r, i) => {
      const y = i * rowH;
      const w = Math.max(2, (r.value / max) * span);
      svg.appendChild(sv('text', { x: 0, y: y + rowH / 2 + 4, class: 'strong' }, r.label));
      svg.appendChild(sv('rect', { x: left, y: y + 7, width: w, height: rowH - 14, rx: 3, fill: color }));
      svg.appendChild(sv('text', { x: left + w + 6, y: y + rowH / 2 + 4, class: 'strong' }, String(r.value)));
    });
  }

  function drawScores(box) {
    const d = DATA, T = d.threshold;
    const reasons = {};
    d.scores.forEach((s) => (reasons[s.domain] = reasons[s.domain] || []).push(s));
    const rows = d.companies.map((c) => ({ ...c, score: +c.icp_score || 0 })).sort((a, b) => b.score - a.score);
    box.replaceChildren();
    const W = Math.max(300, box.clientWidth || 700), rowH = 34, top = 24, H = rows.length * rowH + top + 4;
    const svg = sv('svg', { viewBox: `0 0 ${W} ${H}`, height: H, role: 'img', 'aria-label': 'ICP score by company: ' + rows.map((r) => `${r.company} ${r.score}`).join(', ') });
    box.appendChild(svg);
    const endLabel = (r) => `${r.score}  ${LABELS[r.outcome] || r.outcome}`;
    const left = Math.min(textWidth(svg, rows.map((r) => r.company), 'strong') + 14, W * 0.4);
    const right = textWidth(svg, rows.map(endLabel)) + 12;
    const minS = Math.min(0, ...rows.map((r) => r.score));
    const maxS = Math.max(T + 2, ...rows.map((r) => r.score));
    const x = (v) => left + ((v - minS) / (maxS - minS)) * (W - left - right);
    for (let t = Math.ceil(minS); t <= maxS; t++) {
      svg.appendChild(sv('line', { x1: x(t), x2: x(t), y1: top - 4, y2: H - 2, stroke: css('--line') }));
      if (t !== T) svg.appendChild(sv('text', { x: x(t), y: 11, 'text-anchor': 'middle' }, String(t)));
    }
    const tip = el('div', { class: 'tip' });
    tip.hidden = true;
    box.appendChild(tip);
    rows.forEach((r, i) => {
      const y = top + i * rowH;
      const qualified = stageIdx(r) >= 1;
      svg.appendChild(sv('text', { x: 0, y: y + rowH / 2 + 4, class: 'strong' }, r.company));
      const x0 = x(Math.min(0, r.score)), w = Math.max(2, Math.abs(x(r.score) - x(0)));
      const bar = sv('rect', { x: x0, y: y + 7, width: w, height: rowH - 14, rx: 3, class: 'bar', tabindex: 0, fill: qualified ? css('--accent') : css('--bar-muted'), 'aria-label': `${r.company}, ${r.score} points, ${LABELS[r.outcome] || r.outcome}` });
      svg.appendChild(bar);
      svg.appendChild(sv('text', { x: Math.max(x(r.score), x(0)) + 6, y: y + rowH / 2 + 4 }, endLabel(r)));
      const show = (ev) => {
        const b = el('b', null, `${r.company}: ${r.score} points · ${LABELS[r.outcome] || r.outcome}`);
        const ul = el('ul');
        (reasons[r.domain] || []).forEach((s) => ul.appendChild(el('li', null, `${s.points > 0 ? '+' : ''}${s.points} ${s.reason}`)));
        tip.replaceChildren(b, el('div', null, r.reason), ul);
        tip.hidden = false;
        const bx = box.getBoundingClientRect();
        const px = ev.clientX ? ev.clientX - bx.left + 12 : x(r.score);
        const py = ev.clientY ? ev.clientY - bx.top + 14 : y + rowH;
        tip.style.left = Math.max(0, Math.min(px, bx.width - tip.offsetWidth - 4)) + 'px';
        tip.style.top = py + 'px';
      };
      bar.addEventListener('pointermove', show);
      bar.addEventListener('focus', show);
      bar.addEventListener('pointerleave', () => (tip.hidden = true));
      bar.addEventListener('blur', () => (tip.hidden = true));
      bar.addEventListener('click', () => select(r.domain, true));
      bar.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); select(r.domain, true); } });
    });
    const tl = sv('line', { x1: x(T), x2: x(T), y1: top - 6, y2: H, stroke: css('--fg'), 'stroke-dasharray': '4 3', 'stroke-width': 1.25, opacity: 0.55 });
    svg.appendChild(tl);
    svg.appendChild(sv('text', { x: x(T), y: 11, 'text-anchor': 'middle', class: 'strong' }, `qualify at ${T}`));
  }

  function drawDetail() {
    const box = document.getElementById('detail');
    const c = DATA.companies.find((r) => r.domain === picked) || DATA.companies[0];
    if (!c) return;
    const left = el('div');
    left.appendChild(el('h3', null, 'Decision'));
    const dl = el('dl');
    const pill = el('span', { class: 'pill', 'data-o': c.outcome }, LABELS[c.outcome] || c.outcome);
    [['Outcome', pill], ['Domain', c.domain], ['ICP score', String(+c.icp_score || 0)], ['Model fit', c.fit || '—'], ['Why', c.reason], ['Why now', c.why_now || '—'],
     ['Certifications', c.certifications || 'None found'], ['Contact', c.contact_role ? `${c.contact_role} (${c.contact_source})` : '—'],
     ['Email subject', c.email_subject || '—'], ['Hook', c.hook_fact || '—'], ['Draft attempts', c.draft_attempts ? String(c.draft_attempts) : '—']]
      .forEach(([k, v]) => { dl.appendChild(el('dt', null, k)); const dd = el('dd'); typeof v === 'string' ? (dd.textContent = v) : dd.appendChild(v); dl.appendChild(dd); });
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
      if (s.url) { t.appendChild(document.createTextNode(' ')); t.appendChild(el('code', null, s.url)); }
      if (s.result) t.appendChild(document.createTextNode(' → ' + s.result));
      li.appendChild(t);
      steps.appendChild(li);
    });
    right.appendChild(steps);
    box.replaceChildren(left, right);
  }

  function select(domain, scroll) {
    picked = domain;
    document.getElementById('pick').value = domain;
    drawDetail();
    if (scroll) document.getElementById('company').scrollIntoView({ behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'start' });
  }

  function drawTable() {
    const order = { emailed: 0, drafted: 1, no_poc: 2, manual_review: 3, disqualified: 4, failed: 5 };
    const rows = [...DATA.companies].sort((a, b) => (order[a.outcome] ?? 9) - (order[b.outcome] ?? 9) || (+b.icp_score || 0) - (+a.icp_score || 0));
    document.getElementById('rows').replaceChildren(...rows.map((c) => {
      const tr = el('tr', { tabindex: 0 });
      const o = el('td'); o.appendChild(el('span', { class: 'pill', 'data-o': c.outcome }, LABELS[c.outcome] || c.outcome));
      tr.append(el('td', null, c.company), o, el('td', { class: 'num' }, c.icp_score), el('td', { class: 'why' }, c.reason), el('td', null, c.contact_role || '—'), el('td', null, c.email_subject || '—'));
      tr.addEventListener('click', () => select(c.domain, true));
      tr.addEventListener('keydown', (e) => { if (e.key === 'Enter') select(c.domain, true); });
      return tr;
    }));
  }

  function drawCharts() {
    const t = totals(DATA);
    hbars(document.getElementById('funnel-chart'),
      [['Scraped', t.scraped], ['Qualified', t.qualified], ['Contact found', t.contacts], ['Emailed', t.emailed]].map(([label, value]) => ({ label, value })),
      css('--accent'), `Companies reaching each step: scraped ${t.scraped}, qualified ${t.qualified}, contact found ${t.contacts}, emailed ${t.emailed}`);
    const groups = {};
    DATA.companies.filter((c) => c.outcome === 'disqualified').forEach((c) => { const g = dropGroup(c.reason); groups[g] = (groups[g] || 0) + 1; });
    const drops = Object.entries(groups).map(([label, value]) => ({ label, value })).sort((a, b) => b.value - a.value);
    hbars(document.getElementById('drop-chart'), drops, css('--bar-muted'), 'Disqualified companies by reason: ' + drops.map((r) => `${r.label} ${r.value}`).join(', '));
    drawScores(document.getElementById('score-chart'));
  }

  function render() {
    const t = totals(DATA);
    document.querySelectorAll('[data-k]').forEach((n) => { n.textContent = String(t[n.dataset.k] ?? '—'); });
    const max = t.researched || 1;
    document.querySelectorAll('#steps li').forEach((li) => {
      const v = t[li.querySelector('b').dataset.k] || 0;
      li.dataset.zero = String(v === 0);
      let f = li.querySelector('.fill'); if (!f) { f = el('span', { class: 'fill' }); li.appendChild(f); }
      f.style.width = (v / max) * 100 + '%';
    });
    const lede = document.getElementById('lede');
    lede.replaceChildren(
      el('b', null, String(t.qualified)), document.createTextNode(` of the ${t.researched} companies researched fit Sprinto's ICP, and `),
      el('b', null, String(t.emailed)), document.createTextNode(t.emailed === 1 ? ' personalised email was' : ' personalised emails were'),
      document.createTextNode(" sent to the Growth Lead's inbox for review."));
    const gen = new Date(DATA.generated);
    document.getElementById('meta').textContent = `Run "${DATA.run}" · exported ${gen.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })} · emails go to the Growth Lead's own inbox, never to the prospect`;
    document.getElementById('qual-note').textContent = `Passed every gate and scored ${DATA.threshold} or more`;
    document.getElementById('foot').textContent = `Data: dashboard/data.json, exported from the pipeline's decision traces. Contacts are listed by role only.`;

    const sel = document.getElementById('pick');
    sel.replaceChildren(...DATA.companies.map((c) => new Option(`${c.company} (${LABELS[c.outcome] || c.outcome})`, c.domain)));
    picked = picked || (DATA.companies.find((c) => c.outcome === 'emailed') || DATA.companies[0] || {}).domain;
    sel.value = picked;
    sel.onchange = () => select(sel.value, false);

    drawCharts();
    drawDetail();
    drawTable();
  }

  fetch('data.json', { cache: 'no-store' })
    .then((r) => { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
    .then((d) => { DATA = d; render(); })
    .catch((e) => { document.getElementById('lede').textContent = `Couldn't load data.json (${e.message}). Run python -m outreach.export_dashboard and redeploy.`; });

  let rt;
  addEventListener('resize', () => { clearTimeout(rt); rt = setTimeout(() => DATA && drawCharts(), 120); });
  matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => DATA && drawCharts());
})();
