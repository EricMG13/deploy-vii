// Small SVG chart kit returning React elements. Every mark is focusable and names its series, value and provenance.
window.RBOTCharts = function (React, th) {
  const h = React.createElement;
  const num = s => { if (s == null) return NaN; const t = String(s).replace(/,/g, ''); const m = t.match(/^\((.*)\)$/); return m ? -parseFloat(m[1]) : parseFloat(t); };
  const F = { fontFamily: th.font, fontSize: 11, fill: th.ink2, fontVariantNumeric: 'tabular-nums' };
  const FB = Object.assign({}, F, { fill: th.ink, fontWeight: 600 });
  const nice = (max) => { if (max <= 0) return 1; const p = Math.pow(10, Math.floor(Math.log10(max))); const n = max / p; const s = n <= 1 ? 1 : n <= 2 ? 2 : n <= 2.5 ? 2.5 : n <= 5 ? 5 : 10; return s * p; };
  const ticksFor = (min, max, n) => { const span = max - min; const step = nice(span / (n || 4)); const t = []; for (let v = Math.ceil(min / step) * step; v <= max + 1e-9; v += step) t.push(+v.toFixed(6)); return t; };
  const prov = d => d && d.v == null ? 'gap' : (d && d.prov) || 'cited';
  const mark = (key, x, y, label, extra) => h('g', { key, tabIndex: 0, role: 'img', 'aria-label': label, style: { outline: 'none' } }, h('title', null, label), extra, h('rect', { x: x - 12, y: y - 12, width: 24, height: 24, fill: 'transparent' }));
  const palette = [th.c1, th.c2, th.c3, th.c4, th.c5 || th.neutral];
  const shapeEl = (i, x, y, color, hollow) => { const r = 4; const fill = hollow ? th.paper : color; const stroke = color; if (i % 3 === 1) return h('rect', { x: x - r, y: y - r, width: r * 2, height: r * 2, fill, stroke, strokeWidth: 1.5 }); if (i % 3 === 2) return h('path', { d: `M${x} ${y - r - 1}L${x + r + 1} ${y}L${x} ${y + r + 1}L${x - r - 1} ${y}Z`, fill, stroke, strokeWidth: 1.5 }); return h('circle', { cx: x, cy: y, r, fill, stroke, strokeWidth: 1.5 }); };

  function frame(w, hh, kids) { return h('svg', { width: w, height: hh, viewBox: `0 0 ${w} ${hh}`, style: { display: 'block', overflow: 'visible', fontFamily: th.font }, role: 'group' }, kids); }

  // Line strip: categories × series (gaps break the line and print n/a)
  function lineStrip(spec, o) {
    const w = o.w || 300, hh = o.h || 150, pad = { l: 34, r: o.labels === false ? 10 : 48, t: 14, b: 26 };
    const cats = spec.categories; const vals = spec.series.flatMap(s => s.values.map(d => num(d.v))).filter(v => !isNaN(v));
    const max = nice(Math.max(...vals, 0) * 1.15), min = 0; const tk = ticksFor(min, max, 3);
    const X = i => pad.l + (cats.length === 1 ? (w - pad.l - pad.r) / 2 : i * (w - pad.l - pad.r) / (cats.length - 1)); const Y = v => pad.t + (hh - pad.t - pad.b) * (1 - (v - min) / (max - min));
    const kids = [];
    tk.forEach(t => { kids.push(h('line', { key: 'g' + t, x1: pad.l, x2: w - pad.r, y1: Y(t), y2: Y(t), stroke: th.grid, strokeWidth: 1 })); kids.push(h('text', { key: 'tl' + t, x: pad.l - 6, y: Y(t) + 4, textAnchor: 'end', style: F }, String(t))); });
    const pitch = cats.length > 1 ? (w - pad.l - pad.r) / (cats.length - 1) : w; const tight = pitch < 56;
    cats.forEach((c, i) => { if (tight && i !== 0 && i !== cats.length - 1) { kids.push(h('line', { key: 'tk' + i, x1: X(i), x2: X(i), y1: hh - pad.b, y2: hh - pad.b + 4, stroke: th.ink2 })); return; } kids.push(h('text', { key: 'c' + i, x: X(i), y: hh - 8, textAnchor: i === cats.length - 1 && tight ? 'end' : i === 0 && tight ? 'start' : 'middle', style: Object.assign({}, F, tight ? { fontSize: 10 } : {}) }, o.shortCats ? (tight ? c.replace('LTM Q2 2026', 'LTM Q2 26').replace(/^FY20/, "FY") : c.replace('LTM Q2 2026', 'LTM Q2 26').replace(/^FY20/, 'FY')) : c)); });
    const endLabels = [];
    spec.series.forEach((s, si) => {
      const col = s.color || palette[si]; let path = ''; let pen = false;
      s.values.forEach((d, i) => { const v = num(d.v); if (isNaN(v)) { pen = false; return; } path += (pen ? 'L' : 'M') + X(i) + ' ' + Y(v); pen = true; });
      kids.push(h('path', { key: 'p' + si, d: path, fill: 'none', stroke: col, strokeWidth: 2, strokeDasharray: s.illustrative ? '4 3' : undefined }));
      s.values.forEach((d, i) => { const v = num(d.v); const p = prov(d); if (isNaN(v)) { if (si === 0) kids.push(h('g', { key: 'na' + si + i }, h('line', { x1: X(i), x2: X(i), y1: pad.t, y2: hh - pad.b, stroke: th.grid, strokeDasharray: '2 3' }), h('text', { x: X(i), y: pad.t + 2, textAnchor: 'middle', style: Object.assign({}, F, { fontStyle: 'italic' }) }, 'n/a'))); return; }
        const label = `${s.label}, ${cats[i]}: ${d.v}${spec.unit === 'x' ? 'x' : ''} (${p}${d.ref ? ' ' + d.ref : ''})`;
        kids.push(mark('m' + si + i, X(i), Y(v), label, shapeEl(si, X(i), Y(v), col, p === 'illustrative' || p === 'model')));
        if (o.labels !== false && i === s.values.length - 1) endLabels.push({ si, i, y: Y(v), x: X(i), col, text: d.v + (spec.unit === 'x' ? 'x' : '') });
      });
    });
    endLabels.sort((a, b) => a.y - b.y);
    for (let k = 1; k < endLabels.length; k++) { const gap = endLabels[k].y - endLabels[k - 1].y; if (gap < 12) { const push = (12 - gap) / 2; endLabels[k - 1].y -= push; endLabels[k].y += push; } }
    endLabels.forEach(l => kids.push(h('text', { key: 'lb' + l.si + l.i, x: l.x + 9, y: l.y + 4, style: Object.assign({}, FB, { fill: l.col }) }, l.text)));
    return frame(w, hh, kids);
  }

  // Grouped or stacked columns
  function columns(spec, o) {
    const w = o.w || 320, hh = o.h || 160, pad = { l: 40, r: 8, t: 18, b: 26 }; const cats = spec.categories; const stacked = !!o.stacked;
    const totals = cats.map((_, i) => stacked ? spec.series.reduce((a, s) => a + (isNaN(num(s.values[i] && s.values[i].v)) ? 0 : Math.max(0, num(s.values[i].v))), 0) : Math.max(...spec.series.map(s => num(s.values[i] && s.values[i].v)).filter(v => !isNaN(v)), 0));
    const negs = spec.series.flatMap(s => s.values.map(d => num(d && d.v))).filter(v => !isNaN(v) && v < 0);
    const rawMax = Math.max(...totals); const max = spec.unit === '%' && rawMax <= 100 ? 100 : nice(rawMax * 1.12), min = negs.length ? -nice(Math.abs(Math.min(...negs)) * 1.12) : 0; const tk = ticksFor(min, max, spec.unit === '%' ? 4 : 3);
    const gw = (w - pad.l - pad.r) / cats.length; const Y = v => pad.t + (hh - pad.t - pad.b) * (1 - (v - min) / (max - min));
    const kids = [];
    tk.forEach(t => { kids.push(h('line', { key: 'g' + t, x1: pad.l, x2: w - pad.r, y1: Y(t), y2: Y(t), stroke: t === 0 ? th.ink2 : th.grid })); kids.push(h('text', { key: 't' + t, x: pad.l - 6, y: Y(t) + 4, textAnchor: 'end', style: F }, t.toLocaleString())); });
    cats.forEach((c, i) => {
      kids.push(h('text', { key: 'c' + i, x: pad.l + gw * (i + 0.5), y: hh - 8 + (gw < 48 && i % 2 ? 10 : 0), textAnchor: 'middle', style: Object.assign({}, F, gw < 48 ? { fontSize: 10 } : {}) }, o.shortCats ? c.replace('LTM Q2 2026', 'LTM Q2 26').replace(/^FY20/, 'FY') : (gw < 48 ? c.replace(' (rest)', 'r').replace('Thereafter', 'After') : c)));
      let acc = 0; const n = spec.series.length; const bw = stacked ? Math.min(gw * 0.56, 44) : Math.min(gw / (n + 1), 28);
      spec.series.forEach((s, si) => { const d = s.values[i]; const v = num(d && d.v); if (isNaN(v)) { if (!stacked && d && d.v == null) kids.push(h('text', { key: 'na' + i + si, x: pad.l + gw * (i + 0.5) - (n - 1) * bw / 2 + si * bw, y: Y(0) - 6, textAnchor: 'middle', style: Object.assign({}, F, { fontStyle: 'italic' }) }, 'n/a')); return; }
        const col = s.color || palette[si]; const p = prov(d);
        const x = stacked ? pad.l + gw * (i + 0.5) - bw / 2 : pad.l + gw * (i + 0.5) - (n * bw) / 2 + si * bw; const y0 = stacked ? acc : 0; const y1 = stacked ? acc + v : v; if (stacked) acc += v;
        const top = Y(Math.max(y0, y1)), bot = Y(Math.min(y0, y1)); const label = `${s.label}, ${c}: ${d.v} ${spec.unit || ''} (${p}${d.ref ? ' ' + d.ref : ''})`;
        kids.push(mark('b' + i + si, x + bw / 2, (top + bot) / 2, label, h('rect', { x: x + (stacked ? 0 : 1), y: top, width: bw - (stacked ? 0 : 2), height: Math.max(1, bot - top), fill: p === 'illustrative' || p === 'synthetic' ? `url(#hatch-${si})` : col, stroke: col, strokeWidth: 1 })));
        if (o.labels !== false && !stacked && bw >= 22) kids.push(h('text', { key: 'l' + i + si, x: x + bw / 2, y: v >= 0 ? top - 4 : bot + 11, textAnchor: 'middle', style: Object.assign({}, FB, { fontSize: 10 }) }, d.v));
      });
      if (stacked && o.labels !== false && totals[i] > 0) kids.push(h('text', { key: 'tt' + i, x: pad.l + gw * (i + 0.5), y: Y(totals[i]) - 4, textAnchor: 'middle', style: Object.assign({}, FB, { fontSize: 10 }) }, totals[i].toLocaleString()));
    });
    const defs = h('defs', { key: 'd' }, palette.map((c, i) => h('pattern', { key: i, id: 'hatch-' + i, width: 6, height: 6, patternUnits: 'userSpaceOnUse', patternTransform: 'rotate(45)' }, h('rect', { width: 6, height: 6, fill: th.paper }), h('rect', { width: 2, height: 6, fill: c }))));
    return frame(w, hh, [defs].concat(kids));
  }

  // Waterfall bridge
  function waterfall(spec, o) {
    const w = o.w || 640, hh = o.h || 200, pad = { l: 44, r: 8, t: 18, b: ((w - 52) / spec.steps.length) < 56 ? 58 : 40 }; const steps = spec.steps; let run = 0; const bars = [];
    steps.forEach(s => { const v = num(s.d.v); if (s.kind === 'total') { bars.push({ s, a: 0, b: v }); run = v; } else { bars.push({ s, a: run, b: run + v }); run += v; } });
    const all = bars.flatMap(b => [b.a, b.b]); const max = nice(Math.max(...all) * 1.1), min = Math.min(0, ...all); const tk = ticksFor(min, max, 4);
    const gw = (w - pad.l - pad.r) / steps.length; const bw = Math.min(gw * 0.64, 48); const Y = v => pad.t + (hh - pad.t - pad.b) * (1 - (v - min) / (max - min));
    const kids = [];
    tk.forEach(t => { kids.push(h('line', { key: 'g' + t, x1: pad.l, x2: w - pad.r, y1: Y(t), y2: Y(t), stroke: th.grid })); kids.push(h('text', { key: 't' + t, x: pad.l - 6, y: Y(t) + 4, textAnchor: 'end', style: F }, t.toLocaleString())); });
    bars.forEach((b, i) => { const x = pad.l + gw * (i + 0.5) - bw / 2; const top = Y(Math.max(b.a, b.b)), bot = Y(Math.min(b.a, b.b)); const v = num(b.s.d.v); const col = b.s.kind === 'total' ? th.c3 : b.s.kind === 'residual' ? th.neg : v >= 0 ? th.c1 : th.c2; const p = prov(b.s.d);
      kids.push(mark('w' + i, x + bw / 2, (top + bot) / 2, `${b.s.label}: ${b.s.d.v} (${p}${b.s.d.ref ? ' ' + b.s.d.ref : ''})`, h('rect', { x, y: top, width: bw, height: Math.max(2, bot - top), fill: p === 'synthetic' || p === 'illustrative' ? 'url(#wf-hatch)' : col, stroke: col })));
      if (i < bars.length - 1) kids.push(h('line', { key: 'c' + i, x1: x + bw, x2: pad.l + gw * (i + 1.5) - bw / 2, y1: Y(b.b), y2: Y(b.b), stroke: th.ink2, strokeDasharray: '2 2' }));
      kids.push(h('text', { key: 'l' + i, x: x + bw / 2, y: top - 4, textAnchor: 'middle', style: Object.assign({}, FB, { fontSize: 10 }) }, b.s.d.v));
      const lab = (b.s.short || b.s.label); const parts = lab.length > 14 ? lab.split(' ').reduce((a, wd) => { if (!a.length || (a[a.length - 1] + ' ' + wd).length > 14) a.push(wd); else a[a.length - 1] += ' ' + wd; return a; }, []) : [lab];
      const stagger = gw < 56 ? (i % 2) * 22 : 0;
      parts.slice(0, 2).forEach((pt, k) => kids.push(h('text', { key: 'x' + i + k, x: x + bw / 2, y: hh - 30 + stagger + k * 10, textAnchor: 'middle', style: Object.assign({}, F, { fontSize: gw < 56 ? 9 : 10 }) }, pt)));
      if (gw < 56) kids.push(h('line', { key: 'xl' + i, x1: x + bw / 2, x2: x + bw / 2, y1: hh - pad.b + 2, y2: hh - 36 + stagger, stroke: th.grid }));
    });
    const defs = h('defs', { key: 'd' }, h('pattern', { id: 'wf-hatch', width: 6, height: 6, patternUnits: 'userSpaceOnUse', patternTransform: 'rotate(45)' }, h('rect', { width: 6, height: 6, fill: th.paper }), h('rect', { width: 2, height: 6, fill: th.c4 })));
    return frame(w, hh, [defs].concat(kids));
  }

  // Bullet: current vs threshold, ceiling or floor
  function bullet(spec, o) {
    const w = o.w || 520, rowH = o.rowH || 34, pad = { l: o.labelW || 190, r: 70, t: 8, b: 22 }; const rows = spec.rows; const hh = pad.t + rows.length * rowH + pad.b;
    const max = nice(Math.max(...rows.flatMap(r => [num(r.threshold.v), num(r.current.v)])) * 1.1); const X = v => pad.l + (w - pad.l - pad.r) * v / max; const tk = ticksFor(0, max, 4);
    const kids = [];
    tk.forEach(t => { kids.push(h('line', { key: 'g' + t, x1: X(t), x2: X(t), y1: pad.t, y2: hh - pad.b, stroke: th.grid })); kids.push(h('text', { key: 't' + t, x: X(t), y: hh - 6, textAnchor: 'middle', style: F }, t + (spec.unit === 'x' ? 'x' : ''))); });
    rows.forEach((r, i) => { const y = pad.t + i * rowH + rowH / 2; const c = num(r.current.v), t = num(r.threshold.v); const ceiling = r.direction === 'max'; const ok = ceiling ? c <= t : c >= t; const tone = ok ? th.pos : th.neg; const tight = Math.abs(c - t) / t < 0.1;
      kids.push(h('text', { key: 'l' + i, x: pad.l - 10, y: y + 4, textAnchor: 'end', style: FB }, r.label.replace(/ \(.*\)/, '')));
      kids.push(h('text', { key: 'ls' + i, x: pad.l - 10, y: y + 15, textAnchor: 'end', style: Object.assign({}, F, { fontSize: 10 }) }, (r.label.match(/\((.*)\)/) || [, ''])[1] + (ceiling ? ' · ceiling' : ' · floor')));
      kids.push(h('rect', { key: 'bg' + i, x: pad.l, y: y - 9, width: X(max) - pad.l, height: 18, fill: th.track }));
      kids.push(mark('c' + i, X(c) / 2 + pad.l / 2, y, `${r.label}: current ${r.current.v}${spec.unit} against ${ceiling ? 'ceiling' : 'floor'} ${r.threshold.v}${spec.unit}; headroom ${r.headroom ? r.headroom.v : 'n/a'} (${prov(r.current)} ${r.current.ref || ''})`, h('rect', { x: pad.l, y: y - 6, width: X(c) - pad.l, height: 12, fill: th.c1 })));
      kids.push(h('g', { key: 'th' + i }, h('rect', { x: X(t) - 1.5, y: y - 12, width: 3, height: 24, fill: tight && ok ? th.caut : tone }), h('text', { x: X(t) + 6, y: y - 13, textAnchor: 'start', style: Object.assign({}, F, { fontSize: 10, fill: tight && ok ? th.caut : tone, fontWeight: 600 }) }, (ceiling ? 'ceiling ' : 'floor ') + r.threshold.v + spec.unit)));
      kids.push(h('text', { key: 'cv' + i, x: X(c) + 6, y: y + 4, style: Object.assign({}, FB, { fill: th.c1 }) }, r.current.v + spec.unit));
      kids.push(h('text', { key: 'hr' + i, x: w - 2, y: y + 4, textAnchor: 'end', style: Object.assign({}, FB, { fill: tight && ok ? th.caut : tone }) }, (ok ? (tight ? 'Tight ' : 'Headroom ') : 'Breached ') + (r.headroom ? r.headroom.v + spec.unit : '')));
    });
    return frame(w, hh, kids);
  }

  // Dumbbell: from (hollow) to (filled)
  function dumbbell(spec, o) {
    const w = o.w || 560, rowH = o.rowH || 30, pad = { l: o.labelW || 150, r: 60, t: 10, b: 24 }; const rows = spec.rows; const hh = pad.t + rows.length * rowH + pad.b;
    const vals = rows.flatMap(r => [num(r.from.v), num(r.to.v)]).filter(v => !isNaN(v)); const rawMax = Math.max(...vals, 0) * 1.1; const step = nice(rawMax / 4); const max = Math.ceil(rawMax / step) * step, min = Math.min(0, -Math.ceil(Math.abs(Math.min(...vals, 0)) * 1.1 / step) * step); const X = v => pad.l + (w - pad.l - pad.r) * (v - min) / (max - min); const tk = ticksFor(min, max, 4);
    const kids = [];
    tk.forEach(t => { kids.push(h('line', { key: 'g' + t, x1: X(t), x2: X(t), y1: pad.t, y2: hh - pad.b, stroke: t === 0 ? th.ink2 : th.grid })); kids.push(h('text', { key: 't' + t, x: X(t), y: hh - 6, textAnchor: 'middle', style: F }, t.toLocaleString())); });
    rows.forEach((r, i) => { const y = pad.t + i * rowH + rowH / 2; const a = num(r.from.v), b = num(r.to.v); const down = b < a; const col = th.c1;
      kids.push(h('text', { key: 'l' + i, x: pad.l - 10, y: y + 4, textAnchor: 'end', style: FB }, r.label));
      kids.push(h('line', { key: 'ln' + i, x1: X(a), x2: X(b), y1: y, y2: y, stroke: down ? th.neg : th.pos, strokeWidth: 3 }));
      kids.push(mark('f' + i, X(a), y, `${r.label}, ${spec.fromLabel}: ${r.from.v} (${prov(r.from)} ${r.from.ref || ''})`, h('circle', { cx: X(a), cy: y, r: 5, fill: th.paper, stroke: th.ink2, strokeWidth: 1.5 })));
      kids.push(mark('t' + i, X(b), y, `${r.label}, ${spec.toLabel}: ${r.to.v} (${prov(r.to)} ${r.to.ref || ''})`, h('circle', { cx: X(b), cy: y, r: 5.5, fill: col })));
      // Labels always sit outside the pair; the pair is widened to at least 36px of label room, and nothing is drawn left of pad.l
      const lo = Math.min(X(a), X(b)), hi = Math.max(X(a), X(b)); const aIsLo = X(a) <= X(b);
      const close = hi - lo < 36;
      const loX = close ? lo - 9 : lo - 9, hiX = hi + 9;
      const loLabel = aIsLo ? r.from.v : r.to.v, hiLabel = aIsLo ? r.to.v : r.from.v;
      const loStyle = aIsLo ? F : Object.assign({}, FB, { fill: col }), hiStyle = aIsLo ? Object.assign({}, FB, { fill: col }) : F;
      const roomLeft = loX - pad.l > 28;
      if (roomLeft) kids.push(h('text', { key: 'fa' + i, x: loX, y: y + 4, textAnchor: 'end', style: loStyle }, loLabel));
      else kids.push(h('text', { key: 'fa' + i, x: lo, y: y - 9, textAnchor: 'middle', style: loStyle }, loLabel));
      kids.push(h('text', { key: 'tb' + i, x: hiX, y: y + 4, textAnchor: 'start', style: hiStyle }, hiLabel));
    });
    return frame(w, hh, kids);
  }

  // Scatter: yield against maturity; points carry a group (issuer) and a short label
  function scatter(spec, o) {
    const w = o.w || 420, hh = o.h || 200, pad = { l: 40, r: 110, t: 14, b: 26 }; const pts = spec.points.filter(p => !isNaN(num(p.y.v)));
    const yr = s => { const d = new Date(s); return d.getFullYear() + (d.getMonth() + 0.5) / 12; };
    const xs = pts.map(p => yr(p.x)), ys = pts.map(p => num(p.y.v));
    const x0 = Math.floor(Math.min(...xs)) - 0.5, x1 = Math.ceil(Math.max(...xs)) + 0.5; const yMax = Math.ceil(Math.max(...ys) * 1.08), yMin = Math.floor(Math.min(...ys) * 0.9);
    const X = v => pad.l + (w - pad.l - pad.r) * (v - x0) / (x1 - x0), Y = v => pad.t + (hh - pad.t - pad.b) * (1 - (v - yMin) / (yMax - yMin));
    const kids = []; const tk = ticksFor(yMin, yMax, 4);
    tk.forEach(t => { kids.push(h('line', { key: 'g' + t, x1: pad.l, x2: w - pad.r, y1: Y(t), y2: Y(t), stroke: th.grid })); kids.push(h('text', { key: 't' + t, x: pad.l - 6, y: Y(t) + 4, textAnchor: 'end', style: F }, t + '%')); });
    for (let y = Math.ceil(x0); y <= Math.floor(x1); y++) kids.push(h('text', { key: 'x' + y, x: X(y), y: hh - 8, textAnchor: 'middle', style: F }, String(y)));
    const groups = []; pts.forEach(p => { if (!groups.includes(p.group)) groups.push(p.group); });
    const gcol = g => g === (spec.issuer || groups[0]) ? th.c1 : [th.c2, th.c4, th.c5][Math.max(0, groups.indexOf(g) - 1) % 3];
    const labs = pts.map((p, i) => ({ i, y: Y(num(p.y.v)) })).sort((a, b) => a.y - b.y);
    for (let k = 1; k < labs.length; k++) { if (labs[k].y - labs[k - 1].y < 12) labs[k].y = labs[k - 1].y + 12; }
    pts.forEach((p, i) => { const x = X(yr(p.x)), y = Y(num(p.y.v)); const col = gcol(p.group); const pv = prov(p.y); const isIss = col === th.c1;
      kids.push(mark('p' + i, x, y, `${p.label}: ${p.y.v}% yield, matures ${p.x} (${pv} ${p.y.ref || ''})`, shapeEl(isIss ? 0 : 1, x, y, col, pv === 'synthetic')));
      const ly = labs.find(l => l.i === i).y; kids.push(h('text', { key: 'l' + i, x: w - pad.r + 10, y: ly + 4, style: Object.assign({}, FB, { fill: col, fontSize: 10 }) }, (p.short || p.label) + ' ' + (+num(p.y.v)).toFixed(2) + '%')); kids.push(h('line', { key: 'll' + i, x1: x + 6, x2: w - pad.r + 6, y1: y, y2: ly, stroke: th.grid })); });
    return frame(w, hh, kids);
  }

  // Range strip: per metric, a peer range with the issuer's position marked
  function rangeStrip(spec, o) {
    const w = o.w || 460, rowH = o.rowH || 38, pad = { l: o.labelW || 150, r: 16, t: 6, b: 4 }; const rows = spec.rows; const hh = pad.t + rows.length * rowH + pad.b; const kids = [];
    rows.forEach((r, i) => { const y = pad.t + i * rowH + rowH / 2 + 2; const all = [num(r.issuer.v)].concat(r.peers.map(p => num(p.v))).filter(v => !isNaN(v)); const lo = Math.min(...all), hi = Math.max(...all); const span = (hi - lo) || 1; const X = v => pad.l + 24 + (w - pad.l - pad.r - 48) * (v - lo) / span;
      kids.push(h('text', { key: 'l' + i, x: pad.l - 10, y: y + 4, textAnchor: 'end', style: FB }, r.label)); kids.push(h('text', { key: 'u' + i, x: pad.l - 10, y: y + 15, textAnchor: 'end', style: Object.assign({}, F, { fontSize: 10 }) }, r.unit));
      kids.push(h('rect', { key: 'tr' + i, x: pad.l, y: y - 5, width: w - pad.l - pad.r, height: 10, fill: th.track }));
      kids.push(h('rect', { key: 'rg' + i, x: X(lo), y: y - 5, width: X(hi) - X(lo), height: 10, fill: th.grid }));
      r.peers.forEach((p, k) => { const v = num(p.v); if (isNaN(v)) return; kids.push(mark('pe' + i + k, X(v), y, `${p.label}: ${p.v} ${r.unit} (${prov(p)} ${p.ref || ''})`, h('circle', { cx: X(v), cy: y, r: 4.5, fill: th.paper, stroke: th.ink2, strokeWidth: 1.5 }))); kids.push(h('text', { key: 'pl' + i + k, x: X(v), y: y + 17, textAnchor: 'middle', style: Object.assign({}, F, { fontSize: 9.5 }) }, p.label + ' ' + p.v)); });
      const iv = num(r.issuer.v); if (!isNaN(iv)) { kids.push(mark('is' + i, X(iv), y, `${spec.issuer}: ${r.issuer.v} ${r.unit} (${prov(r.issuer)} ${r.issuer.ref || ''})`, h('circle', { cx: X(iv), cy: y, r: 6, fill: th.c1 }))); kids.push(h('text', { key: 'il' + i, x: X(iv), y: y - 10, textAnchor: 'middle', style: Object.assign({}, FB, { fill: th.c1, fontSize: 10.5 }) }, spec.issuer + ' ' + r.issuer.v)); }
    });
    return frame(w, hh, kids);
  }

  // n/a frame: the chart the data cannot draw, with its reason
  function naFrame(o) {
    const w = o.w || 300, hh = o.h || 120;
    return h('svg', { width: w, height: hh, viewBox: `0 0 ${w} ${hh}`, role: 'img', 'aria-label': `${o.title || 'Chart'}: not available. ${o.reason || ''}`, style: { display: 'block', fontFamily: th.font } },
      h('rect', { x: 0.5, y: 0.5, width: w - 1, height: hh - 1, fill: th.track, stroke: th.grid, strokeDasharray: '4 3' }),
      h('text', { x: w / 2, y: hh / 2 - 6, textAnchor: 'middle', style: Object.assign({}, FB, { fontSize: 13, fontStyle: 'italic' }) }, 'n/a' + (o.ref ? ' · ' + o.ref : '')),
      h('text', { x: w / 2, y: hh / 2 + 12, textAnchor: 'middle', style: Object.assign({}, F, { fontSize: 10.5 }) }, (o.reason || '').length > 60 ? (o.reason || '').slice(0, 58) + '…' : (o.reason || '')));
  }

  // Debt stack by rank: cumulative multiple of EBITDA with markers
  function debtStack(spec, o) {
    const w = o.w || 460, rowH = o.rowH || 17, padL = o.labelW || 140, padR = 10, padT = 6; const rows = spec.rows; const hh = padT + rows.length * rowH + 20; const max = o.max || 5; const X = x => padL + (w - padL - padR) * x / max; let acc = 0; const kids = [];
    for (let t = 1; t <= max; t++) { kids.push(h('line', { key: 'g' + t, x1: X(t), x2: X(t), y1: padT, y2: hh - 18, stroke: th.grid })); kids.push(h('text', { key: 't' + t, x: X(t), y: hh - 4, textAnchor: 'middle', style: F }, t + 'x')); }
    rows.forEach((r, i) => { const a = acc / spec.ebitda, b = (acc + r.n) / spec.ebitda; acc += r.n; const y = padT + i * rowH; const col = r.rank === 'secured' ? th.c1 : r.rank === 'unsecured' ? th.c2 : th.c5;
      kids.push(h('text', { key: 'l' + i, x: padL - 6, y: y + 12, textAnchor: 'end', style: Object.assign({}, F, { fill: th.ink, fontSize: 10 }) }, r.label));
      kids.push(mark('b' + i, (X(a) + X(b)) / 2, y + rowH / 2, `${r.label}: ${r.n.toLocaleString()} US$ m, cumulative ${b.toFixed(2)}x (cited)`, h('rect', { x: X(a), y: y + 3, width: Math.max(1.5, X(b) - X(a)), height: rowH - 6, fill: col }))); });
    (spec.markers || []).forEach((m, k) => { kids.push(h('line', { key: 'm' + k, x1: X(m.x), x2: X(m.x), y1: padT - 2, y2: hh - 18, stroke: m.muted ? th.ink2 : th.ink, strokeWidth: 1.5, strokeDasharray: m.muted ? '3 3' : undefined })); kids.push(h('text', { key: 'ml' + k, x: X(m.x) + 3, y: padT + 8 + (k === 1 ? 11 : 0), style: Object.assign({}, FB, { fontSize: 9.5, fill: m.muted ? th.ink2 : th.ink }) }, m.label)); });
    return frame(w, hh, kids);
  }

  return { lineStrip, columns, waterfall, bullet, dumbbell, scatter, rangeStrip, naFrame, debtStack, num };
};
