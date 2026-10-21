// View-model builder: turns window.RBOT (the pack's data) into flat rows a template can render.
(function () {
  const num = s => { if (s == null) return NaN; const t = String(s).replace(/,/g, ''); const m = t.match(/^\((.*)\)$/); return m ? -parseFloat(m[1]) : parseFloat(t); };
  const unitText = (v, unit) => unit === 'x' ? v + 'x' : unit === '%' ? v + '%' : unit === 'pp' ? v + ' pp' : v;
  // Cell: {t, p, ref, reason, cited, calc, gap, synth, illus, model}
  const cell = (d, unit, opts) => {
    opts = opts || {};
    if (d == null || typeof d !== 'object') { const t = d == null ? '' : String(d); return { t, p: 'plain', ref: '', reason: '', cited: false, calc: false, gap: false, synth: false, illus: false, model: false, plain: true, num: !isNaN(num(t)) && t !== '' }; }
    if (d.text !== undefined) return prose(d);
    if (d.status !== undefined) return status(d.status);
    if (d.word !== undefined && d.scale !== undefined) return { t: d.word, p: d.illustrative ? 'illustrative' : 'plain', illus: !!d.illustrative, word: d.word, pos: d.pos, steps: d.steps || 5, scaleName: d.scaleName, cited: false, calc: false, gap: false, synth: false, model: false };
    const gap = d.v == null;
    const p = gap ? 'gap' : (d.prov || 'plain');
    const G = (window.RBOT && window.RBOT.gaps && window.RBOT.gaps[d.ref]) || null;
    const t = gap ? (opts.na || 'n/a') : unitText(d.v, unit || d.unit);
    return { t, p, ref: d.ref || '', reason: d.reason || (G ? G.reason : ''), field: G ? G.field : '', cited: p === 'cited', calc: p === 'calculated', gap, synth: p === 'synthetic', illus: p === 'illustrative', model: p === 'model', num: !gap, neg: !gap && /^\(/.test(String(d.v)) };
  };
  const status = w => { if (w && typeof w === 'object') w = w.word != null ? w.word : (w.status != null ? w.status : ''); const map = { Pass: 'pos', Fits: 'pos', Headroom: 'pos', Improving: 'pos', Aligned: 'pos', Low: 'pos', 'Not met': 'pos', Restricted: 'caut', 'With limitations': 'caut', Watch: 'caut', Tight: 'caut', Medium: 'caut', Unclear: 'caut', Divergent: 'caut', Stable: 'caut', Blocked: 'neg', Breaches: 'neg', Breached: 'neg', Deteriorating: 'neg', High: 'neg', Met: 'neg', Avoid: 'neg' }; const label = w === 'Restricted' ? 'With limitations' : w; const tone = map[w] || 'neu'; return { t: label, word: label, tone, pos: tone === 'pos', caut: tone === 'caut', neg: tone === 'neg', neu: tone === 'neu', p: 'status' }; };
  // Prose: "{K112|%} … [G8]" -> runs
  const prose = d => {
    const runs = []; const re = /\{([CKSG]\d+)\|?([^}]*)\}|\[([CKSG]\d+)\]/g; let last = 0, m;
    const R = window.RBOT || {};
    const txt = d.text || '';
    while ((m = re.exec(txt))) {
      if (m.index > last) runs.push({ t: txt.slice(last, m.index), isFig: false, isChip: false });
      if (m[1]) { const id = m[1]; const rec = (R.citations && R.citations[id]) || (R.calcs && R.calcs[id]); const v = rec ? rec.value : id; const p = id[0] === 'C' ? 'cited' : id[0] === 'K' ? 'calculated' : id[0] === 'S' ? 'synthetic' : 'gap'; runs.push({ t: '', isFig: true, isChip: false, fig: unitText(v, m[2] === 'US$ m' ? '' : m[2]), unit: m[2], ref: id, p, cited: p === 'cited', calc: p === 'calculated', synth: p === 'synthetic' }); }
      else { const id = m[3]; const isGap = id[0] === 'G'; const g = R.gaps && R.gaps[id]; runs.push({ t: '', isFig: false, isChip: true, chip: isGap ? 'n/a ' + id : id, ref: id, isGap, reason: g ? g.reason : '', p: isGap ? 'gap' : (id[0] === 'C' ? 'cited' : 'calculated') }); }
      last = re.lastIndex;
    }
    if (last < txt.length) runs.push({ t: txt.slice(last), isFig: false, isChip: false });
    return { runs, plain: txt.replace(/\{([CKSG]\d+)\|?([^}]*)\}/g, (_, id, u) => { const R2 = window.RBOT || {}; const rec = (R2.citations && R2.citations[id]) || (R2.calcs && R2.calcs[id]); return rec ? unitText(rec.value, u === 'US$ m' ? '' : u) : id; }).replace(/\s*\[([CKSG]\d+)\]/g, (_, id) => id[0] === 'G' ? ' (n/a ' + id + ')' : ''), p: 'model', model: true, illus: !!d.illustrative };
  };
  const refRecord = id => { const R = window.RBOT || {}; if (!id) return null; if (R.citations && R.citations[id]) return Object.assign({ kind: 'cited' }, R.citations[id]); if (R.calcs && R.calcs[id]) { const k = R.calcs[id]; return Object.assign({ kind: 'calculated', inputs: (k.inputs || []).map(i => { const c = (R.citations && R.citations[i]) || (R.calcs && R.calcs[i]); return { id: i, label: c ? c.label + (c.period ? ', ' + c.period : '') : i, value: c ? c.value : '' }; }) }, k); } if (R.gaps && R.gaps[id]) return Object.assign({ kind: 'gap' }, R.gaps[id]); return null; };

  const FAMILY = { 'CP-0': 'sources', 'CP-1': 'financials', 'CP-1A': 'business', 'CP-1B': 'earnings', 'CP-1C': 'market', 'CP-1D': 'earnings', 'CP-2': 'synthesis', 'CP-2A': 'synthesis', 'CP-2D': 'liquidity', 'CP-2E': 'synthesis', 'CP-2G': 'liquidity', 'CP-2H': 'market', 'CP-3': 'market', 'CP-3C': 'liquidity', 'CP-3D': 'market', 'CP-4': 'covenants', 'CP-4C': 'recovery', 'CP-5': 'evidence', 'CP-6': 'portfolio' };
  const FAMILY_LABEL = { sources: 'Sources', financials: 'Financials', business: 'Business', earnings: 'Earnings', synthesis: 'Credit view', liquidity: 'Liquidity and refinancing', covenants: 'Covenants and legal', market: 'Market and relative value', recovery: 'Recovery', evidence: 'Evidence', portfolio: 'Portfolio' };
  const FULL17 = ['CP-0', 'CP-1', 'CP-1A', 'CP-1B', 'CP-1D', 'CP-1C', 'CP-2', 'CP-2A', 'CP-2E', 'CP-4', 'CP-2D', 'CP-2G', 'CP-2H', 'CP-3D', 'CP-3C', 'CP-4C', 'CP-3'];
  const EXTRA = { 'CP-2E': { id: 'CP-2E', name: 'Macro and hedging', status: 'Restricted', reason: 'No rate deck or hedging disclosure in the Source Pack.', question: 'Which macro and rate exposures move the credit, and are they hedged?' } };

  function build() {
    const R = window.RBOT; if (!R) return null;
    const I = R.illustrative, T = R.tables, FP = R.fpIllustrative;
    const meter = (pos, steps, invert) => Array.from({ length: steps }, (_, i) => ({ on: i < pos, idx: i }));
    const scaleTone = (kind, pos) => kind === 'rec' ? (pos <= 2 ? 'pos' : pos === 3 ? 'caut' : 'neg') : (pos <= 2 ? 'pos' : pos === 3 ? 'caut' : 'neg');
    const scale = (kind, s, label) => { const pos = s.pos; const tone = s.word === 'Avoid' ? 'neg' : scaleTone(kind, pos); return { label, kind, pos: pos == null ? '' : (kind === 'val' ? 'V' + pos : String(pos)), word: s.word.replace(/^V\d\s*/, ''), full: (kind === 'val' ? 'V' + pos + ' ' : pos + ' - ') + s.word.replace(/^V\d\s*/, ''), tone, posT: tone === 'pos', cautT: tone === 'caut', negT: tone === 'neg', meter: meter(pos, 5), steps: 5, illus: true }; };
    const call = [scale('rec', I.recommendation.CLO, 'CLO'), scale('rec', I.recommendation['Indexed Loans'], 'Indexed Loans'), scale('rec', I.recommendation['Indexed HY'], 'Indexed HY'), scale('val', I.valuation, 'Valuation'), scale('score', I.creditScore, 'Credit Score')];
    const direction = { label: 'Credit Direction', word: I.creditDirection.word, tone: 'neg', negT: true, illus: true, arrow: 'down' };
    const honest = { note: 'Not yet produced. The live CAOS run of 6 October 2026 completed 17 modules and stopped before CP-5 and CP-6: no Recommendation per Strategy, no Valuation, no instrument call. CP-3 (confidence 44) marks no security Preferred; every module is With limitations.', items: [{ label: 'Recommendation (CLO, Indexed Loans, Indexed HY)', word: 'Not yet produced', why: 'CP-6 did not run' }, { label: 'Valuation', word: 'Not yet produced', why: 'CP-6 did not run' }, { label: 'Relative value', word: 'Unclear', why: 'CP-3: Requires More Work on both priced 2032 bonds' }, { label: 'Credit Score', word: 'Not Scorable', why: 'no factor weights supplied' }, { label: 'Credit view (CP-2)', word: 'Adequate but cyclical', why: 'liquidity Average at US$2,928m; confidence 59' }] };
    const findings = I.keyFindings.map((f, i) => ({ n: i + 1, text: f.text, refs: f.refs, chips: f.refs.map(r => ({ id: r, p: r[0] === 'C' ? 'cited' : 'calculated', cited: r[0] === 'C', calc: r[0] === 'K' })) }));
    const mainRisk = { title: 'Merger debt unknown', text: 'The committed debt financing has no stated amount; leverage after closing cannot be computed.', gap: 'G8', reason: R.gaps.G8.reason };
    const om = T.operatingModel;
    const opRows = [
      { k: 'Segments', runs: prose({ text: 'Regional {K79|%}, Las Vegas {K77|%}, Caesars Digital {K81|%} and Managed and Branded {K83|%} of FY2025 net revenues of {C51|US$ m}.' }).runs },
      { k: 'Footprint', runs: prose({ text: '54 properties in 20 jurisdictions at 30 June 2026 [C1].' }).runs },
      { k: 'Real estate', runs: prose({ text: '22 casinos owned and 25 leased: 18 from VICI, six from GLPI and Caesars Windsor from the Ontario Lottery and Gaming Corporation [C1].' }).runs },
      { k: 'Digital', runs: prose({ text: 'Sports wagering in 34 jurisdictions, 27 online; iGaming in five [C1].' }).runs }
    ];
    const cs = T.capitalStructure; const byInst = {}; (I.byInstrument || []).forEach(b => byInst[b.facility] = b);
    const capRows = cs.rows.map(r => ({ facility: r.facility, rank: r.rank, secured: r.rank === 'secured', unsecured: r.rank === 'unsecured', other: r.rank === 'other', coupon: cell(r.coupon, '%'), maturity: cell(r.maturity), outstanding: cell(r.outstanding), mult: cell(r.structuring_multiple, 'x'), pctEV: cell(r.pct_ev, '%'), n: num(r.outstanding && r.outstanding.v), rec: byInst[r.facility] ? byInst[r.facility].word : '', recPos: byInst[r.facility] && byInst[r.facility].pos != null ? byInst[r.facility].pos : '', recTone: byInst[r.facility] ? (byInst[r.facility].pos == null ? 'neu' : byInst[r.facility].pos <= 2 ? 'pos' : byInst[r.facility].pos === 3 ? 'caut' : 'neg') : 'neu' }));
    const ST = cs.subtotals || {}; const M = R.calcs || {};
    const multOf = id => M[id] ? cell({ v: M[id].value, prov: 'calculated', ref: id }, 'x') : { t: '', plain: true }; const pctOf = id => M[id] ? cell({ v: M[id].value, prov: 'calculated', ref: id }, '%') : { t: '', plain: true };
    const subs = [
      { label: 'Senior secured debt (7 facilities)', outstanding: cell(ST.senior_secured), mult: cell(T.creditMetrics.rows[0].cells[3], 'x'), pctEV: pctOf('K98'), total: false, italic: true },
      { label: 'Unsecured debt (2 facilities)', outstanding: cell(ST.unsecured), mult: multOf('K58b'), pctEV: pctOf('K102'), total: false, italic: true },
      { label: 'Other debt (2 facilities)', outstanding: cell(ST.other), mult: multOf('K59b'), pctEV: pctOf('K106'), total: false, italic: true },
      { label: 'Total debt', outstanding: cell(ST.total_debt), mult: cell(T.creditMetrics.rows[1].cells[3], 'x'), pctEV: pctOf('K106'), total: true },
      { label: 'Cash', outstanding: cell(ST.cash), mult: { t: '', plain: true }, pctEV: { t: '', plain: true }, total: false, italic: true },
      { label: 'Net debt', outstanding: cell(ST.net_debt), mult: cell(T.creditMetrics.rows[2].cells[3], 'x'), pctEV: { t: '', plain: true }, total: true },
      { label: 'EV (merger transaction value) and EV multiple', outstanding: cell(ST.ev), mult: cell(ST.ev_multiple, 'x'), pctEV: { t: '', plain: true }, total: true }
    ];
    const ebitdaRows = T.ebitdaAdjustments.rows.map(r => ({ label: r.label, kind: r.kind || '', total: r.kind === 'total', indent: r.kind === 'indent', sub: r.kind === 'sub', cells: r.cells.map(c => cell(c)) }));
    const finRows = T.financials.rows.map(r => ({ label: r.label, kind: r.kind || '', total: r.kind === 'total', head: r.kind === 'head', sub: r.kind === 'sub', cells: r.cells.map(c => cell(c)) }));
    const finCols = T.financials.columns;
    const metricRows = T.creditMetrics.rows.map(r => ({ label: r.label, total: r.kind === 'total', cells: r.cells.map(c => cell(c, 'x')) }));
    const metricCols = T.creditMetrics.columns;
    const sw = { thesis: prose(I.thesis), strengths: I.strengths.map(s => ({ label: s.label, runs: prose({ text: s.text, refs: s.refs }).runs })), weaknesses: I.weaknesses.map(s => ({ label: s.label, runs: prose({ text: s.text, refs: s.refs }).runs })) };
    const B = R.blocks;
    const covRows = B.covenantTests.rows.map(r => ({ test: r.test, type: r.type, direction: r.direction, ceiling: r.direction === 'Ceiling', threshold: cell(r.threshold, 'x'), current: cell(r.current, 'x'), headroom: cell(r.headroom, 'x'), status: status(r.status.status), pct: Math.min(100, Math.round(num(r.current.v) / Math.max(num(r.threshold.v), num(r.current.v)) * 100)), thrPct: Math.round(num(r.threshold.v) / Math.max(num(r.threshold.v), num(r.current.v)) * 100) }));
    const runwayRows = B.runway.rows.map(r => ({ item: r.item, value: r.value && r.value.text !== undefined ? prose(r.value) : cell(r.value), isProse: !!(r.value && r.value.text !== undefined) }));
    const pressureRows = B.maturityPressure.rows.map(r => ({ year: r.year, maturing: cell(r.maturing), left: cell(r.liquidityLeft), gap: r.gap && r.gap !== 'None' ? cell(r.gap) : { t: 'None', plain: true }, pressure: status(r.pressure), negLeft: /^\(/.test(String(r.liquidityLeft.v)) }));
    const redFlags = B.redFlags.rows.map(r => { const sv = status(r.severity); return { flag: r.flag, runs: prose(r.provision).runs, sev: sv, protective: r.kind === 'protective', bars: sv.t === 'High' ? 3 : sv.t === 'Medium' ? 2 : 1 }; });
    const protection = B.protectionScore.rows.map(r => { const sc = typeof r.score === 'object' ? (r.score.pos || parseInt(r.score.word)) : parseInt(r.score); const scoreText = typeof r.score === 'object' ? r.score.word : r.score; return { area: r.area, score: sc, scoreText, meter: meter(sc, 5), runs: prose(r.evidence).runs, tone: sc >= 4 ? 'pos' : sc === 3 ? 'caut' : 'neg' }; });
    const refiPaths = B.refinancingPaths.rows.map(r => { const dir = r.direction && typeof r.direction === 'object' ? r.direction.word : r.direction; return { path: r.path, feas: status(r.feasibility), dir, up: dir === 'Up', down: dir === 'Down', forRuns: prose(r.evidenceFor).runs, againstRuns: prose(r.evidenceAgainst).runs, impactRuns: prose(r.impact).runs }; });
    const capacity = B.capacity.rows.map(r => ({ type: r.type, basket: r.basket, used: cell(r.used), remaining: cell(r.remaining), status: r.status, sev: (typeof r.severity === 'string' || (r.severity && r.severity.word)) ? status(r.severity) : { t: 'n/a', neu: true }, runs: prose(r.implication).runs }));
    const covCall = [{ label: 'Credit Score', pos: '3', word: 'Fair', tone: 'caut', cautT: true, illus: true, meter: meter(3, 5) }, { label: 'Covenant tests', word: 'Headroom', sub: 'Maintenance, 2 tests', tone: 'pos', posT: true, calc: true }, { label: 'Lender protection', pos: '2', word: 'of 5', tone: 'neg', negT: true, illus: true, meter: meter(2, 5) }, { label: 'Refinancing pressure', word: 'High', tone: 'neg', negT: true, illus: true, meter: meter(3, 3), steps: 3 }, { label: 'Credit Direction', word: 'Deteriorating', tone: 'neg', negT: true, illus: true, arrow: 'down' }];
    const covLines = [{ k: 'Covenants', runs: prose({ text: 'Total Leverage {K56|x} against a {C338|x} ceiling; FCCR {K52|x} against a {C339|x} floor; tested for the revolver and Term A only, Term B-1 has no maintenance test [C343]. Ratios are on RBOT\'s basis [G34].' }).runs }, { k: 'Liquidity', runs: prose({ text: '{C177|US$ m} against mandatory uses of {K160|US$ m} over 12 months from 30 June 2026, lease payments included: {K165} months; the revolver matures 31 January 2028 [C162].' }).runs }, { k: 'New tranches', runs: prose({ text: 'Merger debt unstated; CR Score n/a [G39] [G8].' }).runs }, { k: 'Not in this Pathway', runs: [{ t: 'No Recommendation, no Valuation and no Portfolio Fit: this Pathway runs no CP-3, CP-6 or Fit.', isFig: false, isChip: false }] }];
    // CP-1B
    const m1b = R.modules['CP-1B'];
    const segRows = B.segmentChanges.rows.map(r => ({ segment: r.segment, sub: r.kind === 'sub', rev25: cell(r.rev25), rev26: cell(r.rev26), revPct: cell(r.revPct, '%'), e25: cell(r.ebitda25), e26: cell(r.ebitda26), ePct: cell(r.ebitdaPct, '%'), m26: cell(r.margin26, '%'), mChg: cell(r.marginChg, 'pp'), down: num(r.ebitda26.v) < num(r.ebitda25.v), up: num(r.ebitda26.v) > num(r.ebitda25.v) }));
    const drivers = B.varianceDrivers.rows.map(r => ({ metric: r.metric, mgmt: prose(r.mgmt).runs, analyst: prose(r.analyst).runs, impl: prose(r.implication).runs }));
    const gaps1b = ['G3', 'G1', 'G2'].map(g => ({ id: g, field: ({ G3: 'Cash from operations, Q2 2026 and Q2 2025', G1: 'Cash interest paid, Q2 2026 and Q2 2025', G2: 'Income taxes paid, Q2 2026 and Q2 2025' })[g], reason: R.gaps[g].reason }));
    const popC94 = refRecord('C94');
    const headline1b = prose(m1b.headline);
    const srcs1b = [refRecord('C94'), refRecord('C95'), refRecord('C96'), refRecord('C97')];
    // nav 17
    const nav17 = FULL17.map(id => { const m = R.modules[id] || EXTRA[id]; const st = status(m.status); return { id, name: m.name, status: st, fam: FAMILY[id], famLabel: FAMILY_LABEL[FAMILY[id]], pass: st.pos, lim: st.caut, blocked: st.neg, question: m.question }; });
    const famGroups = []; nav17.forEach(m => { let g = famGroups.find(x => x.fam === m.fam); if (!g) { g = { fam: m.fam, label: m.famLabel, items: [] }; famGroups.push(g); } g.items.push(m); });
    const tally = { total: 17, lim: nav17.filter(m => m.lim).length, pass: nav17.filter(m => m.pass).length, text: `17 modules: ${nav17.filter(m => m.lim).length} with limitations, ${nav17.filter(m => m.pass).length} pass` };
    const nav6 = ['CP-0', 'CP-1', 'CP-1B', 'CP-2', 'CP-3', 'CP-4'].map(id => { const m = R.baseModules.find(x => x.id === id); const st = status(m.status); return { id, name: m.name, status: st, pass: st.pos, lim: st.caut, current: id === 'CP-1B' }; });
    // Model: house view
    const house = [{ label: 'Reported EBITDA, Q2 2026', v: cell(T.ebitdaAdjustments.rows[0].cells[0]) }, { label: '+ Transaction costs and other, net', v: cell(T.ebitdaAdjustments.rows[1].cells[0]) }, { label: '+ Stock-based compensation', v: cell(T.ebitdaAdjustments.rows[2].cells[0]) }, { label: 'Structuring EBITDA, Q2 2026', v: cell(T.ebitdaAdjustments.rows[3].cells[0]), total: true }, { label: '− Unrealized add-backs', v: cell(T.ebitdaAdjustments.rows[4].cells[0]) }, { label: 'SSIM EBITDA, Q2 2026', v: cell(T.ebitdaAdjustments.rows[5].cells[0]), total: true }];
    const houseLTM = { structuring: cell(T.ebitdaAdjustments.rows[3].cells[1]), ssim: cell(T.ebitdaAdjustments.rows[5].cells[1]), pf: cell(T.ebitdaAdjustments.rows[5].cells[2]) };
    const mults = [{ label: 'Senior secured leverage', v: cell(T.creditMetrics.rows[0].cells[3], 'x') }, { label: 'Total leverage', v: cell(T.creditMetrics.rows[1].cells[3], 'x') }, { label: 'Net leverage', v: cell(T.creditMetrics.rows[2].cells[3], 'x') }, { label: 'Interest cover', v: cell(T.creditMetrics.rows[3].cells[3], 'x') }, { label: 'Cash interest cover, debt only', v: cell(T.creditMetrics.rows[4].cells[3], 'x') }];
    const evSub = subs[6];
    const modelCols = [{ g: 'Annual', cols: ['FY2023', 'FY2024', 'FY2025'] }, { g: 'Interim, six months', cols: ['H1 2025', 'H1 2026'] }, { g: 'Trailing', cols: ['LTM Q2 2026'], base: true }, { g: 'Pro forma', cols: ['PF-LTM'], na: true, why: 'merger debt unstated (G8, G21)' }];
    const bands = ['Operating KPIs', 'Revenue by business unit', 'Gross profit', 'Operating expenses to EBITDA', 'Adjusted EBITDA and add-backs', 'Adjusted EBITDA to free cash flow', 'Net cash flow, cash and liquidity', 'Debt stack by rank', 'Debt roll-forward', 'Interest by facility', 'Working capital', 'Credit metrics'].map((b, i) => ({ n: i + 1, label: b, rows: [3, 5, 1, 6, 6, 9, 5, 11, 4, 11, 4, 5][i], na: i === 2 || i === 10 }));
    const fit = R.fit;
    const fitLine = { portfolio: fit.portfolio.name, text: FP.callBand.fitSummary.text, instruments: fit.instruments.map(x => ({ instrument: x.instrument, verdict: status(x.verdict), maxSize: cell(x.maxSize), binding: x.bindingLimit, final: x.final ? x.final.word : '' })) };
    const trace = T.trace.rows.map(r => ({ issuer: r.issuer, seniority: r.seniority, coupon: cell(r.coupon), couponT: parseFloat(r.coupon.v).toString() + '%', maturity: cell(r.maturity), price: cell(r.price), yield: cell(r.yield), yieldT: parseFloat(r.yield.v).toFixed(2) + '%', moodys: cell(r.moodys), sp: cell(r.sp) }));
    return { meta: R.meta, call, direction, honest, findings, mainRisk, opRows, opIntro: prose({ text: 'Caesars is a geographically diversified gaming and hospitality company [C1], founded in 1973 [C1]; its primary source of revenue is gaming operations [C1].' }).runs, capRows, subs, evSub, ebitdaRows, ebitdaCols: T.ebitdaAdjustments.columns, finRows, finCols, metricRows, metricCols, sw, covRows, runwayRows, pressureRows, redFlags, protection, refiPaths, capacity, covCall, covLines, m1b: { name: m1b.name, id: m1b.id, question: m1b.question, reason: m1b.reason, status: status(m1b.status), headline: headline1b, refs: m1b.refs }, segRows, drivers, gaps1b, popC94, srcs1b, nav17, famGroups, tally, nav6, house, houseLTM, mults, modelCols, bands, fitLine, trace, charts: { leverage: R.charts.leverage, coverage: R.charts.coverage, liquidity: R.charts.liquidity, maturityWall: R.charts.maturityWall, revenueEbitda: R.charts.revenueEbitda, bridge: R.fpCharts['fig-liquidity-bridge'], fundingGap: R.fpCharts['fig-funding-gap'], covenant: R.fpCharts['fig-covenant-headroom'], segments: R.charts.segments }, cell, prose, status, refRecord, num };
  }
  window.RBOTVM = { build, cell, prose, status, refRecord, num };
})();
