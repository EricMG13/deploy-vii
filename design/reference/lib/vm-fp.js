// Front Page view-models for Earnings Update, Relative Value, Distressed & Restructuring and Portfolio Decision.
(function () {
  const TONE = { pos: ['Pass', 'Fits', 'Headroom', 'Improving', 'Aligned', 'Low', 'Not met', 'Preferred', 'Attractive', 'Very attractive', 'Available', 'Strong OW', 'Modest OW', 'Up', 'Held'],
    caut: ['Restricted', 'With limitations', 'Watch', 'Tight', 'Medium', 'Unclear', 'Divergent', 'Stable', 'Neutral', 'Fair', 'MW', 'Partial', 'Requires more work', 'Requires More Work', 'Not resolved', 'Limited'],
    neg: ['Blocked', 'Breaches', 'Breached', 'Deteriorating', 'High', 'Met', 'Avoid', 'Inadequate', 'Unattractive', 'Very unattractive', 'Modest UW', 'Strong UW', 'Down'] };
  const tone = w => { w = w && typeof w === 'object' ? (w.word || w.status || '') : (w || ''); for (const k in TONE) if (TONE[k].includes(w)) return k; return 'neu'; };
  const word = w => w && typeof w === 'object' ? (w.word != null ? w.word : (w.status != null ? w.status : (w.v != null ? w.v : ''))) : (w == null ? '' : String(w));
  const sig = (w) => { const t = word(w); const tn = tone(t); const illus = !!(w && typeof w === 'object' && w.illustrative); return { t, tone: tn, pos: tn === 'pos', caut: tn === 'caut', neg: tn === 'neg', neu: tn === 'neu', illus, isNA: /^(N\/A|n\/a|Not computable|Not evaluated)/.test(t) }; };
  const scalePos = (kind, s) => { if (!s || s.pos == null) return ''; return kind === 'val' ? 'V' + s.pos : String(s.pos); };
  const cleanWord = s => (s && s.word ? s.word : '').replace(/^V\d\s*/, '');

  function build(v) {
    const R = window.RBOT; const cell = v.cell, prose = v.prose; const B = R.blocks, I = R.illustrative, FP = R.fpIllustrative;
    const meterOf = (pos, steps) => Array.from({ length: steps || 5 }, (_, i) => ({ on: i < pos }));
    const scaleItem = (label, kind, s) => { const t = s.word === 'Avoid' || (s.pos != null && s.pos >= 4) ? 'neg' : s.pos == null ? 'neu' : s.pos <= 2 ? 'pos' : 'caut'; return { label, kind, pos: scalePos(kind, s), word: cleanWord(s), full: (kind === 'val' ? 'V' + s.pos + ' ' : s.pos + ' - ') + cleanWord(s), tone: t, meter: meterOf(s.pos, 5), illus: true, hasPos: s.pos != null, hasMeter: true }; };
    const dirItem = (label, w, illus) => ({ label, word: w, tone: w === 'Deteriorating' || w === 'Down' ? 'neg' : w === 'Improving' || w === 'Up' ? 'pos' : 'caut', arrow: w === 'Deteriorating' || w === 'Down' ? 'down' : w === 'Improving' || w === 'Up' ? 'up' : 'flat', illus: illus !== false, hasPos: false, hasMeter: false });
    const wordItem = (label, s, sub, steps) => { const sg = sig(s); return { label, word: sg.t, sub, tone: sg.tone, illus: !!(s && s.illustrative), hasPos: false, hasMeter: s && s.pos != null, meter: meterOf(s.pos, steps || s.steps || 3), steps: steps || (s && s.steps) || 3 }; };
    const naItem = (label, w, sub) => ({ label, word: w, sub, tone: 'neu', na: true, hasPos: false, hasMeter: false });
    const rec = I.recommendation;
    const recItems = [scaleItem('CLO', 'rec', rec.CLO), scaleItem('Indexed Loans', 'rec', rec['Indexed Loans']), scaleItem('Indexed HY', 'rec', rec['Indexed HY'])];
    const valItem = scaleItem('Valuation', 'val', I.valuation), scoreItem = scaleItem('Credit Score', 'score', I.creditScore);
    const dirI = dirItem('Credit Direction', I.creditDirection.word);

    // ---------- Earnings Update ----------
    const pc = B.periodComparison.rows.map(r => ({ metric: r.metric, reference: cell(r.reference), current: cell(r.current), change: cell(r.change), changePct: cell(r.changePct, '%'), perimeter: r.perimeter && r.perimeter.text !== undefined ? prose(r.perimeter).plain : (r.perimeter || ''), isX: /\(x\)/.test(r.metric), isPct: /\(%\)/.test(r.metric), worse: (() => { const c = v.num(r.change && r.change.v); if (isNaN(c)) return false; const bad = /leverage|Net debt|Interest|loss/i.test(r.metric) ? c > 0 : c < 0; return bad; })(), better: (() => { const c = v.num(r.change && r.change.v); if (isNaN(c) || c === 0) return false; return !(/leverage|Net debt|Interest|loss/i.test(r.metric) ? c > 0 : c < 0); })() }));
    const kpi = B.kpiChanges.rows.map(r => ({ kpi: r.kpi.replace(' Adjusted EBITDA margin', ''), reference: cell(r.reference, '%'), current: cell(r.current, '%'), change: cell(r.change, 'pp'), trend: sig(r.trend) }));
    const guidance = B.guidance.rows.map(r => ({ metric: r.metric, benchmark: cell(r.benchmark), actual: cell(r.actual), variance: cell(r.variance), note: prose(r.note).runs }));
    const signals = B.signals.rows.map(r => ({ signal: r.signal, evidence: prose(r.evidence).runs, severity: sig(r.severity), implication: prose(r.implication).runs }));
    const watch = B.watchItems.rows.map(r => ({ trigger: r.trigger, signal: prose(r.signal).runs, why: prose(r.why).runs }));
    const cv = B.creditView.rows; const cvMap = {}; cv.forEach(r => cvMap[r.item] = r.value);
    const eu = {
      call: [scoreItem, dirI, dirItem('Sector Outlook', cvMap['Sector Outlook'].word), naItem('Since last Report', 'No Prior Case', 'first RBOT Report on Caesars'), wordItem('Sponsor Quality', { word: I.sponsorQuality.word || I.sponsorQuality, illustrative: true, pos: 2, steps: 3 }, null, 3)],
      lines: [{ k: 'The quarter', runs: prose({ text: 'Net revenues {C19|US$ m}, up {K74|%}; Adjusted EBITDA {C23|US$ m}, {K112|%}; margin {K71|%}, {K114|pp}. Regional includes Caesars Windsor from 3 March 2026 [C365].' }).runs },
        { k: 'Watch', runs: prose({ text: 'Merger debt terms [G8]; Las Vegas margin {K134|%}, down {K136|pp}.' }).runs },
        { k: 'Recommendation', runs: prose({ text: 'None in this Pathway: no CP-3, CP-6 or Portfolio Fit ran, so the page answers whether the credit view moves, not whether to own the issuer.' }).runs }],
      pc, kpi, guidance, signals, watch, confidence: cvMap['Confidence'] ? sig(cvMap['Confidence']) : null,
      nav: R.pathways.EARNINGS_UPDATE.nav, notRun: R.pathways.EARNINGS_UPDATE.notRun, histPerf: prose(I.historicalPerformance).plain
    };

    // ---------- Relative Value ----------
    const levels = B.instrumentLevels.rows.map(r => ({ instrument: r.instrument.replace('CEI ', '').replace('Senior Secured Notes', 'SSN').replace('Senior Notes', 'SN').replace('Special Improvement District Bonds 4.30%', 'SID bonds 4.30%').replace('Long-term notes and other payables', 'Other payables').replace('Revolving Credit Facility', 'Revolver').replace('CVA Delayed Draw Term Loan', 'CVA DDTL'), basis: r.basis, hasLevel: r.basis !== 'None', date: cell(r.date), price: cell(r.price), yield: cell(r.yield, '%'), spread: cell(r.spread), valuation: r.valuation && r.valuation.word ? { t: cleanWord(r.valuation), pos: scalePos('val', r.valuation), tone: tone(cleanWord(r.valuation)), has: true } : { t: 'n/a', ref: r.valuation && r.valuation.ref, reason: r.valuation && r.valuation.reason, has: false }, rec: r.recommendation.pos != null ? { t: r.recommendation.word, pos: String(r.recommendation.pos), tone: tone(r.recommendation.word), has: true } : { t: 'N/A', has: false }, secured: /SSN|Term Loan|Revolver|DDTL/.test(r.instrument.replace('CEI ', '')) }));
    const secPref = B.securityPreference.rows.map(r => ({ instrument: r.instrument, preference: sig(r.preference), reason: prose(r.reason).runs, trigger: prose(r.trigger).runs }));
    const comp = B.compensation.rows.map(r => ({ instrument: r.instrument, rank: r.rank, sensitivity: sig(r.sensitivity), compensation: sig(r.compensation), comparables: prose(r.comparables).runs }));
    const mvf = B.marketVsFundamental.rows.map(r => ({ implication: prose(r.implication).runs, fundamental: prose(r.fundamental).runs, alignment: sig(r.alignment), basis: prose(r.basis).runs }));
    const K = R.calcs, C = R.citations; const kv = id => ({ v: K[id].value, prov: 'calculated', ref: id }); const cvv = id => ({ v: C[id].value, prov: 'cited', ref: id });
    const yc = R.charts.yieldCurve;
    const peerStrip = { issuer: 'CZR', rows: [
      { label: 'Adj. EBITDA margin, Q2', unit: '%', issuer: kv('K71'), peers: [{ label: 'MGM', v: K.K69.value, prov: 'calculated', ref: 'K69' }, { label: 'PENN', v: K.K70.value, prov: 'calculated', ref: 'K70' }] },
      { label: 'Last-trade yield', unit: '%', issuer: { v: (+yc.points[0].y.v).toFixed(2), prov: 'cited', ref: 'C233' }, peers: [{ label: 'CZR unsec.', v: (+yc.points[1].y.v).toFixed(2), prov: 'cited', ref: 'C242' }, { label: 'MGM', v: (+yc.points[2].y.v).toFixed(2), prov: 'cited', ref: yc.points[2].y.ref }, { label: 'PENN', v: (+yc.points[3].y.v).toFixed(2), prov: 'cited', ref: yc.points[3].y.ref }] } ] };
    const peerSet = B.peerSet.rows.map(r => ({ peer: r.peer, basis: prose(r.basis).plain, comparability: sig(r.comparability), data: prose(r.data).runs }));
    const byInst = {}; I.byInstrument.forEach(b => byInst[b.facility] = b);
    const fitByKey = {}; R.fit.instruments.forEach(f => fitByKey[f.instrument] = f);
    const fitRows = R.fit.instruments.map(f => ({ instrument: f.instrument, verdict: sig(f.verdict), maxSize: cell(f.maxSize), binding: f.bindingLimit, uncapped: { t: f.uncapped.word, pos: String(f.uncapped.pos), tone: tone(f.uncapped.word) }, cap: f.cap || 'No cap', hasCap: !!f.cap, final: { t: f.final.word, pos: String(f.final.pos), tone: tone(f.final.word) }, secured: f.secured, rated: !!(f.issueRating && f.issueRating.rated), changed: f.cap && f.final.word !== f.uncapped.word }));
    const notEval = R.fit.notEvaluated.map(n => ({ instrument: n.facility.replace('CEI ', '').replace('Revolving Credit Facility', 'Revolver').replace('CVA Delayed Draw Term Loan', 'CVA DDTL').replace('Special Improvement District Bonds 4.30%', 'SID bonds 4.30%').replace('Long-term notes and other payables', 'Other payables'), text: n.text }));
    const rv = {
      call: recItems.concat([valItem, scoreItem, dirI]),
      lines: [{ k: 'Preferred', runs: prose({ text: 'The 6.50% secured 2032s at {C232}, yield {C233|%}: Preferred. The 6.00% unsecured 2032s at {C241}: Avoid, {K146|pp} more yield for a claim behind {K57|US$ m} of secured debt. Prices and yields are TRACE last trades of 1 October 2026, not bids.' }).runs },
        { k: 'Portfolio Fit', runs: prose({ text: 'Test CLO I (synthetic): proposed US${S47|US$} of the secured 2032s Fits, max US${K221|US$} under C-01; loans and unrated notes Watch, max US${K222|US$} under C-04 [G35].' }).runs }],
      honest: { note: 'Honest state: the live CAOS Relative Value run of 12 October 2026 concluded Requires More Work for both priced 2032 bonds; relative value Unclear; fundamental score Not Scorable (no factor weights). No preference is established yet.', items: [{ label: 'Relative value', word: 'Unclear', why: 'CP-3 confidence 44' }, { label: '6.50% secured 2032s', word: 'Requires More Work', why: '93.28 · 8.06%' }, { label: '6.00% unsecured 2032s', word: 'Requires More Work', why: '84.94 · 9.32%' }, { label: 'Fundamental score', word: 'Not Scorable', why: 'no factor weights' }, { label: 'Recommendation · Valuation', word: 'Not yet produced', why: 'CP-6 did not run' }] },
      levels, secPref, comp, mvf, peerStrip, peerSet, fitRows, notEval, byInst, yc, nav: R.pathways.RELATIVE_VALUE.nav, notRun: R.pathways.RELATIVE_VALUE.notRun
    };

    // ---------- Distressed & Restructuring ----------
    const gate = B.distressGate.rows.map(r => ({ trigger: r.trigger, evidence: prose(r.evidence).runs, status: sig(r.status), overall: /overall/i.test(r.trigger) }));
    const gateOverall = gate.find(g => g.overall) || { status: sig(FP.callBand.distressGate) };
    const ev = B.evScenarios.rows.map(r => ({ scenario: r.scenario, basis: r.basis, metric: cell(r.metric), multiple: cell(r.multiple, 'x'), ev: cell(r.ev), illus: r.ev.prov === 'illustrative' }));
    const recov = B.recoveries.rows.map(r => ({ scenario: r.scenario, cls: r.class, claim: cell(r.claim), allocation: cell(r.allocation), recovery: cell(r.recovery, '%'), fulcrum: word(r.fulcrum) === 'Yes', illus: r.recovery.prov === 'illustrative', pct: Math.max(0, Math.min(100, v.num(r.recovery.v))) }));
    const recovByScenario = []; recov.forEach(r => { let g = recovByScenario.find(x => x.scenario === r.scenario); if (!g) { g = { scenario: r.scenario, rows: [], illus: r.illus }; recovByScenario.push(g); } g.rows.push(r); });
    const claims = B.claims.rows.map(r => ({ cls: r.class, claim: r.claim, obligor: r.obligor, amount: cell(r.amount), security: r.security, rank: typeof r.rank === 'object' ? (r.rank.word || 'n/a') : r.rank, excluded: /lease/i.test(r.class), note: r.note ? prose(r.note).plain : '' }));
    const restr = B.restructuringPaths.rows.map(r => ({ path: r.path, process: r.process, consent: prose(r.consent).runs, newMoney: prose(r.newMoney).runs, treatment: prose(r.treatment).runs, blockers: prose(r.blockers || { text: '' }).runs, likelihood: sig(r.likelihood) }));
    const ratingRows = B.ratingTriggers.rows.map(r => ({ agency: r.agency, type: r.type.replace('Issue rating, ', ''), threshold: cell(r.threshold), current: cell(r.current), status: sig(r.status) }));
    const migration = B.migrationView.rows.map(r => ({ agency: r.agency, cs: r.case, transition: prose(r.transition).plain, timing: r.timing, catalyst: prose(r.catalyst).runs, confidence: sig(r.confidence) }));
    const dr = {
      call: [wordItem('Distress gate', FP.callBand.distressGate, 'Not met · Unclear · Met', 3)].concat(recItems, [scoreItem]),
      callNotMet: [wordItem('Distress gate', { word: 'Not met', illustrative: false, pos: 1, steps: 3 }, 'no named distress trigger', 3)].concat(recItems, [scoreItem]),
      lines: [{ k: 'Fulcrum', runs: prose({ text: 'Senior unsecured in the 5.0x downside ({K205|%} recovery); senior secured in the 4.0x stress ({K211|%}); none at the merger value.' }).runs },
        { k: 'Instrument', runs: prose({ text: 'Prefer the 6.50% secured 2032s; avoid the unsecured notes.' }).runs },
        { k: 'Portfolio Fit', runs: prose({ text: 'Test CLO I (synthetic): US${S47|US$} of the secured 2032s Fits, max US${K221|US$} under C-01; loans and unrated notes Watch, max US${K222|US$} under C-04.' }).runs }],
      linesNotMet: [{ k: 'Gate', runs: prose({ text: 'The real CAOS CP-4C output: Not Applicable, no named distress trigger. Covenant compliance reported at 30 June 2026; no paths, valuation, waterfall or fulcrum were produced.' }).runs },
        { k: 'Lead with', runs: prose({ text: 'Liquidity runway {K165} months on mandatory uses of {K160|US$ m}; liquidity left turns negative in 2028 when the CEI revolver matures [C162].' }).runs }],
      gate, gateOverall, ev, recov, recovByScenario, claims, restr, ratingRows, migration, nav: R.pathways.DISTRESSED_RESTRUCTURING.nav, notRun: R.pathways.DISTRESSED_RESTRUCTURING.notRun, m4c: R.modules['CP-4C']
    };

    // ---------- Portfolio Decision ----------
    const limits = R.fit.limits.map(l => ({ id: l.id, label: l.label, kind: l.kind, limit: cell(l.limit), current: cell(l.current), headroom: cell(l.headroomPct), room: cell(l.room), binds: l.id === 'C-04' || l.id === 'C-01', tight: v.num(l.headroomPct.v) < 0.5 }));
    const proposed = R.fit.proposed; const pf = R.fit.portfolio;
    const pd = {
      call: recItems.concat([{ label: 'Test CLO I · final', pos: '2', word: 'Modest OW', sub: 'Secured 2032s · Fits · no cap', tone: 'pos', illus: true, hasPos: true, hasMeter: true, meter: meterOf(2, 5), synthetic: true }, valItem, scoreItem]),
      lines: [{ k: 'Test CLO I', runs: prose({ text: 'Synthetic. Proposed US${S47|US$} par of the 6.50% secured 2032s ({S48|% NAV}% of NAV): Fits, max US${K221|US$} under C-01. Loans and unrated notes: Watch, max US${K222|US$} under C-04, because no issue rating is in the sources [G35].' }).runs },
        { k: 'Other books', runs: prose({ text: 'Indexed Loans and Indexed HY have no portfolio attached: Fit not run.' }).runs }],
      fitRows, notEval, limits, proposed: { par: cell(proposed.par), weight: cell(proposed.weightOnPar, '%'), mv: cell(proposed.marketValue), price: cell(proposed.price) }, portfolio: { name: pf.name, asOf: pf.asOf, nav: cell(pf.nav), onePct: cell(pf.onePctNav) }, rule: R.fit.rule,
      caveats: [{ id: 'S50', text: 'Workbook NAV and compliance check dated 29 May 2026; price 1 October 2026.' }, { id: 'S51', text: 'The CLO indenture 7.11 is the CLO\'s own indenture, not the Caesars notes indenture.' }, { id: 'G40', text: 'Eligibility of a senior secured bond for this CLO is unconfirmed.' }],
      catalysts: I.catalysts.map(c => prose(c).runs), challenge: B.challenge.rows.map(r => ({ claim: prose(r.claim).plain, counter: prose(r.counter).runs, resolution: prose(r.resolution).runs, change: prose(r.change).plain, held: /^Held/.test(prose(r.resolution).plain) })),
      bindLim: B.bindingLimitations.rows.map(r => ({ module: r.module, limitation: prose(r.limitation).runs, effect: r.effect, lift: r.lift })),
      nav: R.pathways.PORTFOLIO_DECISION.nav, notRun: R.pathways.PORTFOLIO_DECISION.notRun
    };
    return { eu, rv, dr, pd, sig, tone, recItems, valItem, scoreItem, dirI };
  }
  window.RBOTFP = { build, sig, tone };
})();
