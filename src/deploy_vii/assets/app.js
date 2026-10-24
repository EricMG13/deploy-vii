/* Direction C shell (DS-03, DS-04, DS-07). Python decides every number, word and spelling; this
   script only places them. Data enters text nodes (textContent / createTextNode) and attributes
   through the DOM, never as markup. The one parsed string is the chart SVG that charts.py built
   from escaped text; it is parsed as image/svg+xml and imported as nodes, never set as markup. */
(() => {
  "use strict";
  const report = JSON.parse(document.getElementById("report-data").textContent);
  const front = report.report;
  const SVG_NS = "http://www.w3.org/2000/svg";
  const $ = (id) => document.getElementById(id);

  const node = (tag, text, className) => {
    const result = document.createElement(tag);
    if (text !== undefined && text !== null) result.textContent = String(text);
    if (className) result.className = className;
    return result;
  };
  const svgNode = (tag, attrs, kids) => {
    const result = document.createElementNS(SVG_NS, tag);
    Object.entries(attrs || {}).forEach(([key, value]) => result.setAttribute(key, String(value)));
    (kids || []).forEach(kid => result.append(kid));
    return result;
  };
  const wrap = (child, className) => { const result = node("span", null, className); result.append(child); return result; };

  // ---- icons (DS-06: 16px set, 1.6 stroke) -----------------------------------------------
  const PATHS = {
    front: "M2 2h12v12H2zM2 6h12M6 6v8", analysis: "M2 12l4-4 3 3 5-6M10 5h4v4",
    model: "M2 3h12v10H2zM2 7h12M6 3v10M10 3v10", fit: "M8 2a6 6 0 1 1-6 6h6z",
    evidence: "M4 2h6l3 3v9H4zM10 2v3h3M6 9h4M6 11.5h4", limits: "M8 2l6 11H2zM8 7v3M8 11.5v.5",
    search: "M11 11l3 3M3 7a4 4 0 1 0 8 0 4 4 0 1 0-8 0",
    help: "M8 1.5a6.5 6.5 0 1 1 0 13 6.5 6.5 0 0 1 0-13M6 6.5a2 2 0 1 1 3 1.7c-.7.4-1 .8-1 1.5M8 12v.5",
    print: "M4 6V2h8v4M4 12H2V6h12v6h-2M4 10h8v4H4z", menu: "M2 4h12M2 8h12M2 12h12",
    chevUp: "M4 10l4-4 4 4", chevDn: "M4 6l4 4 4-4", close: "M4 4l8 8M12 4l-8 8",
    pen: "M3 13l1-4 7-7 3 3-7 7z", skip: "M3 3l10 10M13 3L3 13", clock: "M8 1.5a6.5 6.5 0 1 1 0 13 6.5 6.5 0 0 1 0-13M8 4.5V8l2.5 1.5",
    arrowR: "M3 8h10M9 4l4 4-4 4", arrowU: "M8 13V3M4 7l4-4 4 4", arrowD: "M8 3v10M4 9l4 4 4-4",
    tick: "M3 8.5l3.5 3.5L13 4.5"
  };
  const iconSvg = (name, size, stroke) => svgNode("svg", {
    width: size || 14, height: size || 14, viewBox: "0 0 16 16", fill: "none", stroke: "currentColor",
    "stroke-width": stroke || 1.6, "stroke-linecap": "round", "stroke-linejoin": "round", "aria-hidden": "true"
  }, [svgNode("path", {d: PATHS[name]})]);
  const icon = (name, size, stroke) => wrap(iconSvg(name, size, stroke), "ic");
  const glyph = (kind, size) => {
    const s = size || 13;
    const circle = (r) => svgNode("circle", {cx: 8, cy: 8, r});
    const root = svgNode("svg", {
      width: s, height: s, viewBox: "0 0 16 16", fill: "none", stroke: "currentColor", "stroke-width": 1.6,
      "stroke-linecap": "round", "stroke-linejoin": "round", "aria-hidden": "true"
    });
    if (kind === "pass") root.append(circle(6.5), svgNode("path", {d: "M5 8l2 2 4-4"}));
    else if (kind === "lim") root.append(circle(6.5), svgNode("path", {d: "M8 1.5A6.5 6.5 0 0 1 8 14.5Z", fill: "currentColor"}));
    else if (kind === "blocked") root.append(circle(6.5), svgNode("path", {d: "M3.5 3.5l9 9"}));
    else if (kind === "na") root.append(circle(6), svgNode("path", {d: "M5 8h6"}));
    else if (kind === "stale") root.append(svgNode("path", {d: PATHS.clock}));
    else if (kind === "candidate") root.append(svgNode("circle", {cx: 8, cy: 8, r: 6.5, "stroke-dasharray": "2 2"}));
    else if (kind === "chevron") root.append(svgNode("path", {d: PATHS.chevDn}));
    else root.append(svgNode("path", {d: PATHS.skip}));
    return wrap(root, "ic st-" + kind);
  };
  const chip = (kind, word) => {
    const result = node("span", null, "chip st-" + kind);
    result.append(glyph(kind, 12), document.createTextNode(word));
    return result;
  };
  const PROV = {C: "cited", K: "calculated", S: "synthetic", G: "gap"};
  const provOfRef = (ref) => PROV[String(ref || "").charAt(0)] || null;
  const provGlyph = (prov) => {
    if (prov !== "cited" && prov !== "calculated" && prov !== "synthetic") return document.createTextNode("");
    const root = svgNode("svg", {width: 8, height: 9, viewBox: "0 0 8 9", class: "pg", role: "img", "aria-label": prov}, [svgNode("title", {}, [document.createTextNode(prov)])]);
    if (prov === "cited") root.append(svgNode("path", {d: "M1 .5h4l2 2v6H1z", class: "pg-cited"}));
    else if (prov === "calculated") root.append(svgNode("rect", {x: .5, y: .5, width: 7, height: 8, class: "pg-calc"}), svgNode("path", {d: "M2 3.5h4M2 5.5h4", class: "pg-calc-line"}));
    else root.append(svgNode("path", {d: "M3 .5h2v3l2.5 4.5h-7L3 3.5z", class: "pg-synth"}));
    return root;
  };

  // ---- inspector --------------------------------------------------------------------------
  const inspector = {tab: "source", source: null, table: null, trigger: null};
  const TABS = [["source", "Source"], ["table", "Table"], ["key", "Key"]];
  const keyPanel = () => {
    const list = node("div", null, "key-list");
    const row = (name, sample, rule) => {
      const item = node("div", null, "key-row");
      item.append(node("span", name, "caps"), node("span", rule));
      if (sample) item.firstChild.append(document.createTextNode(" "), node("span", sample, "num"));
      return item;
    };
    list.append(node("p", "Provenance marks", "twin-title"));
    [["cited", "Cited", "Read from a source in the Source Pack."], ["calculated", "Calculated", "Computed by Python from cited figures."],
      ["synthetic", "Synthetic", "Test data, never a fact about the issuer."]].forEach(([prov, name, rule]) => {
      const item = node("div", null, "key-row");
      const label = node("span", null, "caps"); label.append(provGlyph(prov), document.createTextNode(name));
      item.append(label, node("span", rule)); list.append(item);
    });
    list.append(node("p", "Pen mark", "twin-title"));
    const pen = node("div", null, "key-row"); const penLabel = node("span", null, "caps");
    penLabel.append(icon("pen", 10), document.createTextNode("Model-written"));
    pen.append(penLabel, node("span", "Prose written by a model; its figures keep their own marks.")); list.append(pen);
    list.append(node("p", "Cell spellings", "twin-title"));
    report.legend.forEach(entry => list.append(row(entry.name, entry.sample, entry.rule)));
    list.append(node("p", "Status words", "twin-title"));
    const seen = new Set();
    report.nav.forEach(item => {
      if (seen.has(item.word)) return; seen.add(item.word);
      const entry = node("div", null, "key-row"); entry.append(chip(item.glyph, item.word), node("span", ""));
      list.append(entry);
    });
    return list;
  };
  const renderInspector = () => {
    const tabs = $("insp-tabs"); tabs.replaceChildren();
    TABS.forEach(([key, label]) => {
      const button = node("button", label); button.type = "button"; button.id = "tab-" + key;
      button.setAttribute("role", "tab"); button.setAttribute("aria-selected", String(inspector.tab === key));
      button.setAttribute("aria-controls", "inspector-content"); button.tabIndex = inspector.tab === key ? 0 : -1;
      button.addEventListener("click", () => { inspector.tab = key; renderInspector(); });
      button.addEventListener("keydown", event => {
        const step = {ArrowRight: 1, ArrowLeft: -1}[event.key];
        if (!step) return;
        inspector.tab = TABS[(TABS.findIndex(t => t[0] === inspector.tab) + step + TABS.length) % TABS.length][0];
        renderInspector(); $("tab-" + inspector.tab).focus(); event.preventDefault();
      });
      tabs.append(button);
    });
    $("inspector-content").setAttribute("aria-labelledby", "tab-" + inspector.tab);
    const content = $("inspector-content"); content.replaceChildren();
    if (inspector.tab === "key") content.append(keyPanel());
    else if (inspector.tab === "table") content.append(inspector.table ? inspector.table() : node("p", "No table twin for this item.", "muted"));
    else content.append(inspector.source ? inspector.source() : node("p", "Select a figure or source to inspect its evidence, period, units and calculation basis.", "muted"));
  };
  const openInspector = (source, table, trigger, tab) => {
    inspector.source = source; inspector.table = table; inspector.trigger = trigger || null; inspector.tab = tab || "source";
    renderInspector();
    // Focus moves into the inspector so the keyboard path continues there; Escape returns it.
    if (trigger) $("inspector-content").focus();
    if (window.matchMedia("(max-width:900px)").matches) $("inspector").scrollIntoView({block: "start"});
  };
  const closeInspector = () => {
    const trigger = inspector.trigger;
    inspector.source = null; inspector.table = null; inspector.trigger = null; inspector.tab = "source";
    renderInspector();
    if (trigger && trigger.isConnected) trigger.focus();
  };
  const dl = (fields) => {
    const list = node("dl");
    fields.forEach(([name, value]) => list.append(node("dt", name), node("dd", value ?? "Not supplied")));
    return list;
  };
  const passportCard = (kind, ref, title, fields) => {
    const card = node("section", null, "passport " + kind);
    const head = node("div", null, "passport-head");
    if (kind === "gap") head.append(node("span", "∅ " + ref, "num"));
    else head.append(provGlyph(kind), node("span", ref, "num"));
    head.append(node("span", kind, "caps"));
    const close = node("button", null, "close"); close.type = "button"; close.setAttribute("aria-label", "Close inspector");
    close.append(icon("close", 12)); close.addEventListener("click", closeInspector); head.append(close);
    card.append(head, node("div", title, "passport-title"));
    if (kind === "synthetic") card.append(node("div", "TEST DATA: invented for testing, not a fact about the issuer.", "banner"));
    card.append(dl(fields));
    return card;
  };
  const passportOf = (ref) => front.passports.find(item => item.ref_id === ref);
  const reasonOf = (ref) => {
    const found = passportOf(ref);
    const reason = found && found.fields.find(field => field.name === "Reason");
    return reason ? reason.value : null;
  };

  // ---- tables, prose and charts -----------------------------------------------------------
  const tableFor = (block) => (block.chart ? block.chart.table_twin : block.rows.length ? block : null);
  const openRef = (ref, block, trigger) => {
    const found = passportOf(ref);
    const source = () => {
      if (!found) return node("p", `No passport for ${ref}.`, "muted");
      return passportCard(found.kind, found.ref_id, found.fields.length ? found.fields[0].value : found.ref_id,
        found.fields.map(field => [field.name, field.value]));
    };
    const twin = tableFor(block);
    openInspector(source, twin ? () => twinPanel(twin) : null, trigger);
  };
  const cellNode = (cell, block, name, interactive) => {
    const ref = cell.gap_ref || cell.ref_id;
    if (!ref) return node("span", cell.text);
    const holder = interactive ? node("button", null, "fig") : node("span", null, "fig");
    if (cell.prov === "gap") holder.classList.add("gap-fig");
    holder.append(provGlyph(cell.prov), document.createTextNode(cell.text));
    const reason = cell.prov === "gap" ? reasonOf(ref) : null;
    if (reason) holder.title = reason;
    if (interactive) {
      holder.type = "button"; holder.dataset.ref = ref;
      holder.setAttribute("aria-label", `${name}: ${cell.text} (${provOfRef(ref) || "reference"} ${ref})`);
      holder.addEventListener("click", () => openRef(ref, block, holder));
    }
    return holder;
  };
  const dataTable = (block, interactive, owner) => {
    const result = node("table", null, block.kind === "keyvalue" ? "keyvalue" : "dense");
    result.append(node("caption", block.title, "sr-only"));
    const grid = block.kind === "period_grid";
    if (grid) result.classList.add("period-grid");
    const absent = new Map((block.absent_columns || []).map(item => [item.column, item.reason]));
    const shade = (cell, index) => {
      if (grid && index === block.base_column) cell.classList.add("base");
      if (absent.has(index)) { cell.classList.add("absent"); cell.title = absent.get(index); }
    };
    if (block.kind !== "keyvalue") {
      const head = node("thead");
      if (grid && block.groups.length) {
        const groupRow = node("tr", null, "group-row"); groupRow.append(node("th", block.scale || "Item"));
        block.groups.forEach(group => { const th = node("th", group.label, "group"); th.colSpan = group.span; th.scope = "colgroup"; groupRow.append(th); });
        head.append(groupRow);
      }
      const row = node("tr");
      // Under a group row the row-label heading is spoken, not drawn twice.
      const first = node("th", grid && block.groups.length ? null : block.row_header || block.scale || "Item"); first.scope = "col";
      if (grid && block.groups.length) first.append(node("span", block.scale || block.row_header || "Item", "sr-only"));
      row.append(first);
      block.columns.forEach((label, index) => {
        const th = node("th", label, "fig-col"); th.scope = "col"; shade(th, index);
        if (absent.has(index)) th.append(node("span", ` (absent: ${absent.get(index)})`, "sr-only"));
        row.append(th);
      });
      head.append(row); result.append(head);
    }
    const body = node("tbody");
    block.rows.forEach(item => {
      const tr = node("tr", null, item.style && item.style !== "row" ? "row-" + item.style : ""); tr.dataset.rowId = item.row_id;
      const th = node("th", item.label); th.scope = "row"; tr.append(th);
      if (block.kind === "keyvalue") {
        const td = node("td");
        item.cells.forEach((cell, index) => { if (index) td.append(document.createTextNode(" ")); td.append(cellNode(cell, owner, item.label, interactive)); });
        tr.append(td);
      } else {
        item.cells.forEach((cell, index) => {
          const td = node("td", null, cell.unit_class === "text" ? "" : "fig-cell");
          shade(td, index);
          td.append(cellNode(cell, owner, `${item.label}, ${block.columns[index]}`, interactive)); tr.append(td);
        });
      }
      body.append(tr);
    });
    result.append(body);
    const scroll = node("div", null, "table-scroll"); scroll.tabIndex = 0; scroll.setAttribute("role", "region");
    scroll.setAttribute("aria-label", block.title); scroll.append(result);
    return scroll;
  };
  const twinPanel = (block) => {
    const panel = node("div"); panel.append(node("p", `Table twin · ${block.title}`, "twin-title"), dataTable(block, false, block));
    return panel;
  };
  // Runs renderer: Front Page lines join their runs with a space; claim runs (MC-2) keep the
  // spacing Python resolved, so they join with nothing.
  const runNodes = (runs, block, separator) => {
    const out = [];
    runs.forEach((run, index) => {
      if (index && separator) out.push(document.createTextNode(separator));
      if (run.kind === "text") out.push(document.createTextNode(run.text));
      else if (run.kind === "pen") { const pen = node("span", null, "pen-tag"); pen.append(icon("pen", 10), document.createTextNode(run.text)); out.push(pen); }
      else out.push(cellNode({text: run.text, prov: run.kind === "gap" ? "gap" : provOfRef(run.ref_id), ref_id: run.kind === "gap" ? null : run.ref_id, gap_ref: run.kind === "gap" ? run.ref_id : null}, block, block.title, true));
    });
    return out;
  };
  const lineNodes = (line, block) => runNodes(line.runs, block, " ");
  const sectionColumn = (block, name, lines, kind) => {
    const column = node("div", null, "sw-col " + kind);
    const head = node("div", null, "sw-head"); head.append(icon(kind === "strengths" ? "tick" : "close", 12), document.createTextNode(name));
    column.append(head);
    if (!lines.length) column.append(node("p", "No " + name.toLowerCase() + " supplied.", "muted sw-empty"));
    lines.forEach(line => { const row = node("div", null, "sw-row"); const text = node("span"); text.append(...lineNodes(line, block)); row.append(node("span", line.label, "sw-label"), text); column.append(row); });
    return column;
  };
  const proseBody = (block) => {
    const body = node("div", null, "block-body prose");
    if (block.lines.some(line => line.section)) {
      block.lines.filter(line => line.section === "thesis").forEach(line => {
        const paragraph = node("p", null, "thesis"); paragraph.append(node("b", line.label + "."), document.createTextNode(" "), ...lineNodes(line, block)); body.append(paragraph);
      });
      const columns = node("div", null, "sw-cols");
      columns.append(sectionColumn(block, "Strengths", block.lines.filter(line => line.section === "strengths"), "strengths"),
        sectionColumn(block, "Weaknesses", block.lines.filter(line => line.section === "weaknesses"), "weaknesses"));
      body.append(columns);
      return body;
    }
    const list = block.numbered ? node("ol", null, "numbered") : body;
    block.lines.forEach((line, at) => {
      if (block.numbered) { const item = node("li"), text = node("span"); text.append(...lineNodes(line, block)); item.append(node("span", at + 1, "num n"), text); list.append(item); return; }
      const paragraph = node("p"); paragraph.append(...lineNodes(line, block)); list.append(paragraph);
    });
    if (block.numbered) body.append(list);
    return body;
  };
  // Only the elements charts.py emits are allowed; anything else refuses the whole chart.
  const SVG_ALLOWED = new Set(["svg", "g", "rect", "path", "line", "circle", "text", "title", "desc", "defs", "pattern"]);
  const cleanSvg = (element) => {
    if (element.namespaceURI !== SVG_NS || !SVG_ALLOWED.has(element.localName)) return false;
    Array.from(element.attributes).forEach(attr => {
      const name = attr.name.toLowerCase();
      if (name.startsWith("on") || name === "href" || name === "xlink:href" || name === "style" || attr.localName.toLowerCase() === "href") element.removeAttribute(attr.name);
    });
    return Array.from(element.childNodes).every(child => {
      if (child.nodeType === Node.TEXT_NODE) return true;
      if (child.nodeType === Node.ELEMENT_NODE) return cleanSvg(child);
      child.remove(); return true;
    });
  };
  const parseSvg = (text) => {
    const doc = new DOMParser().parseFromString(text, "image/svg+xml");
    if (doc.getElementsByTagName("parsererror").length || !cleanSvg(doc.documentElement)) {
      return node("p", "This chart could not be drawn; its table is available.", "muted chart-refused");
    }
    return document.importNode(doc.documentElement, true);
  };
  // One figure: caption (figure id, title, unit), the chart, its legend and its table twin.
  const chartFigure = (chart, title, figId, extra) => {
    extra = extra || {};
    const figure = node("figure", null, "chart-figure"); figure.dataset.chartKind = chart.kind;
    if (figId) figure.dataset.figId = figId;
    const caption = node("figcaption");
    if (figId) caption.append(node("span", figId, "num fig-id"));
    caption.append(node("span", title));
    if (chart.unit) caption.append(node("span", chart.unit, "unit"));
    const host = node("div", null, "chart-host"); host.append(parseSvg(chart.svg));
    const twin = node("div", null, "chart-twin"); twin.hidden = true; twin.append(dataTable(chart.table_twin, true, {chart, title}));
    const toggle = node("span", null, "seg"); toggle.setAttribute("role", "group"); toggle.setAttribute("aria-label", "Chart or table");
    [["Chart", false], ["Table", true]].forEach(([label, showTable]) => {
      const button = node("button", label); button.type = "button"; button.setAttribute("aria-pressed", String(showTable === false));
      button.addEventListener("click", () => {
        host.hidden = showTable; twin.hidden = !showTable;
        toggle.querySelectorAll("button").forEach(other => other.setAttribute("aria-pressed", String(other === button)));
      });
      toggle.append(button);
    });
    caption.append(toggle); figure.append(caption);
    // A figure set beside a table keeps a slot for its summary sentence; absent, it says so.
    if (extra.placement === "beside") figure.append(extra.summary ? node("p", extra.summary, "fig-summary") : node("p", "No summary sentence is produced for this figure yet.", "fig-summary muted"));
    figure.append(host);
    const legend = node("div", null, "legend num");
    chart.series.forEach((name, index) => { const item = node("span"); item.append(node("i", null, `sw sw${index % 5 + 1}`), document.createTextNode(name)); legend.append(item); });
    if (extra.gaps_note) legend.append(node("span", extra.gaps_note, "gaps-note"));
    if (legend.children.length) figure.append(legend);
    figure.append(twin);
    const owner = {chart, title};
    const marks = () => Array.from(host.querySelectorAll("g.mark"));
    host.addEventListener("click", event => {
      const mark = event.target.closest && event.target.closest("g.mark");
      if (mark && mark.dataset.ref) openRef(mark.dataset.ref, owner, mark);
    });
    host.addEventListener("keydown", event => {
      const mark = event.target.closest && event.target.closest("g.mark");
      if (!mark) return;
      if (event.key === "Enter" || event.key === " ") { if (mark.dataset.ref) openRef(mark.dataset.ref, owner, mark); event.preventDefault(); return; }
      const step = {ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1}[event.key];
      if (!step) return;
      const all = marks(); const next = all[all.indexOf(mark) + step];
      if (next) { next.focus(); event.preventDefault(); }
    });
    return figure;
  };
  // A strip of figures (FP 01's S.1 to S.4, the debt stack, S.5): one column per figure.
  const figureStrip = (figures) => {
    const strip = node("div", null, "fig-strip"); strip.style.setProperty("--fig-count", String(figures.length));
    figures.forEach(item => strip.append(chartFigure(item.chart, item.title, item.fig_id, item)));
    return strip;
  };
  const chartBody = (block) => {
    const body = node("div", null, "block-body");
    if (block.chart) body.append(chartFigure(block.chart, block.title, block.fig_id));
    if (block.figures.length) body.append(figureStrip(block.figures));
    return body;
  };
  // Tabs (FP 01 Capital structure | EBITDA adjustments | Transaction and new debt): one register
  // shown at a time, built when selected so a large register costs nothing until it is opened.
  const tabbedParts = (block) => {
    const panels = [{label: block.tab_label, pseudo: block}, ...block.tabs.map(tab => ({label: tab.label, pseudo: Object.assign({}, block, {
      title: tab.label, scale: tab.scale, row_header: tab.row_header, columns: tab.columns, rows: tab.rows, groups: [], base_column: null, absent_columns: [], kind: "dense"}), note: tab.note}))];
    const strip = node("div", null, "block-tabs"); strip.setAttribute("role", "tablist"); strip.setAttribute("aria-label", block.title + " views");
    const panel = node("div"); panel.setAttribute("role", "tabpanel"); panel.id = "panel-" + block.block_id;
    let current = 0;
    const select = (index, focus) => {
      current = index; panel.replaceChildren();
      const item = panels[index];
      panel.append(item.note ? node("p", item.note, "muted") : dataTable(item.pseudo, true, item.pseudo));
      panel.setAttribute("aria-labelledby", `tab-${block.block_id}-${index}`);
      strip.querySelectorAll("button").forEach((button, at) => { button.setAttribute("aria-selected", String(at === index)); button.tabIndex = at === index ? 0 : -1; });
      if (focus) strip.children[index].focus();
    };
    panels.forEach((item, index) => {
      const button = node("button", item.label); button.type = "button"; button.setAttribute("role", "tab"); button.id = `tab-${block.block_id}-${index}`;
      button.setAttribute("aria-controls", panel.id);
      button.addEventListener("click", () => select(index, false));
      button.addEventListener("keydown", event => {
        const step = {ArrowRight: 1, ArrowLeft: -1}[event.key];
        if (!step) return;
        select((current + step + panels.length) % panels.length, true); event.preventDefault();
      });
      strip.append(button);
    });
    select(0, false);
    return {strip, panel};
  };

  // ---- blocks (DS-04) ----------------------------------------------------------------------
  const hasPen = (block) => block.lines.some(line => line.runs.some(run => run.kind === "pen"));
  const renderBlock = (block) => {
    const section = node("section", null, `block state-${block.state} w-${block.width}`);
    section.id = "block-" + block.block_id; section.dataset.blockId = block.block_id; section.dataset.state = block.state;
    section.dataset.outline = block.title;
    const hasContent = block.state === "populated" || block.state === "collapsed";
    const collapsedKind = block.state === "collapsed";
    const tabs = hasContent && block.tabs.length ? tabbedParts(block) : null;
    const head = node("header", null, "block-head" + (tabs ? " has-tabs" : ""));
    const right = [block.owner, block.fig_id, block.meta].filter(Boolean).join(" · ");
    if (tabs) {
      // FP 01: the tabs are the head; the right-hand text carries the owner, as-of date and scale.
      head.append(node("h3", block.title, "sr-only"), tabs.strip, node("span", null, "spacer"), node("span", right, "meta num tab-meta"));
    } else head.append(node("h3", block.title), node("span", right, "meta num"));
    block.tags.forEach(tag => head.append(node("span", tag, "tag")));
    if (hasPen(block)) { const pen = node("span", null, "pen-tag"); pen.append(icon("pen", 10), document.createTextNode("Model-written")); head.append(pen); }
    const state = report.block_states[block.state];
    if (state && !collapsedKind) { head.append(chip(state.glyph, state.word)); section.dataset.stateWord = state.word.toLowerCase(); }
    if (block.note) { const note = node("span", block.note, "block-note"); head.append(note); }
    const summary = collapsedKind && block.summary ? node("span", block.summary, "summary") : null;
    if (summary) head.append(summary);
    if (block.kind === "chart" && block.figures.some(item => item.chart.kind !== "na") && hasContent) head.append(node("span", "Select a mark: its source opens in the inspector; arrows move between marks", "hint"));
    if (!tabs) head.append(node("span", null, "spacer"));
    const end = node("span", null, "head-end");
    if (block.pinned) end.append(node("span", "pinned", "pinned"));
    if (block.full_analysis_route) { const link = node("a", (block.route_label || "Full analysis") + " →", "full"); link.href = "#" + block.full_analysis_route; end.append(link); }
    head.append(end);
    section.append(head);
    if (hasContent) {
      const tableBody = () => {
        const holder = node("div", null, "block-body");
        const at = (place) => block.figures.filter(item => item.placement === place);
        if (at("above").length) holder.append(figureStrip(at("above")));
        const main = tabs ? tabs.panel : dataTable(block, true, block);
        if (at("beside").length) {
          const row = node("div", null, "beside"); row.append(main, figureStrip(at("beside"))); holder.append(row);
        } else holder.append(main);
        if (at("below").length) holder.append(figureStrip(at("below")));
        return holder;
      };
      const body = block.kind === "prose" ? proseBody(block) : block.kind === "chart" ? chartBody(block) : tableBody();
      body.id = "body-" + block.block_id;
      const toggle = node("button", null, "collapse" + (collapsedKind ? " expand-link" : "")); toggle.type = "button";
      body.hidden = collapsedKind;
      const sync = () => {
        toggle.setAttribute("aria-expanded", String(!body.hidden)); toggle.setAttribute("aria-controls", body.id);
        toggle.setAttribute("aria-label", (body.hidden ? "Expand " : "Collapse ") + block.title);
        toggle.replaceChildren(...(collapsedKind ? [document.createTextNode(body.hidden ? "Expand" : "Collapse")] : []), icon(body.hidden ? "chevDn" : "chevUp", 12));
        if (summary) summary.hidden = !body.hidden;
        section.classList.toggle("is-collapsed", body.hidden);
      };
      toggle.addEventListener("click", () => { body.hidden = !body.hidden; sync(); });
      section.sync = (hidden) => { body.hidden = hidden; sync(); };
      sync(); end.append(toggle); section.append(body);
    }
    return section;
  };

  // ---- call band (DS-03) -------------------------------------------------------------------
  const callBand = () => {
    const band = node("section", null, "call-band"); band.setAttribute("aria-label", "The call");
    band.dataset.callState = front.call_state;
    const top = node("div", null, "call-top");
    top.append(node("h2", front.pathway.title), node("span", front.pathway.question));
    if (report.run.case_kind === "synthetic") top.append(node("span", "SYNTHETIC", "tag"));
    top.append(node("span", report.run_display.as_of));
    const collapse = node("button", "Collapse all"); collapse.type = "button"; let all = false;
    collapse.addEventListener("click", () => {
      all = !all; collapse.textContent = all ? "Expand all" : "Collapse all";
      document.querySelectorAll(".block").forEach(block => { if (block.sync) block.sync(all); });
    });
    top.append(collapse);
    const items = node("div", null, "call-items");
    front.call.filter(entry => !entry.line).forEach(entry => {
      const item = node("div", null, "call-item " + entry.kind);
      item.append(node("span", entry.label, "lab"));
      const value = node("span", null, "val");
      if (entry.kind === "scale") value.append(node("span", entry.meter, "tile"));
      if (entry.kind === "direction") { const tile = node("span", null, "tile"); tile.append(icon({up: "arrowU", down: "arrowD", flat: "arrowR"}[entry.direction], 16)); value.append(tile); }
      const words = node("span", null, "words"); words.append(node("span", entry.value_text, "word"));
      if (entry.kind === "scale") {
        const meter = node("span", null, "meter"); meter.setAttribute("role", "img"); meter.setAttribute("aria-label", `${entry.value_text}, ${entry.meter} of 5`);
        for (let i = 1; i <= 5; i++) meter.append(node("i", null, i <= entry.meter ? "on" : ""));
        words.append(meter);
      }
      value.append(words); item.append(value); items.append(item);
    });
    band.append(top, items);
    // Full-width lines (Main risk, Portfolio Fit, Instrument) follow the scale row.
    front.call.filter(entry => entry.line).forEach(entry => {
      const line = node("p", null, "call-line"); line.append(node("span", entry.label, "lab"), document.createTextNode(" " + entry.value_text)); band.append(line);
    });
    if (front.call_words) {
      const withheld = node("p", null, "call-note");
      withheld.append(chip(front.call_words.glyph, front.call_words.word), document.createTextNode(front.call_state === "blocked"
        ? " The call is withheld; the blocking reason is listed under Limitations."
        : ` ${front.pathway.title} does not make this call.`));
      band.append(withheld);
    } else if (front.call_state === "no-judgement") band.append(node("p", "No judgement is recorded. Module status and supporting evidence stay visible.", "call-note"));
    return band;
  };

  // ---- module and evidence pages -----------------------------------------------------------
  let sectionCounter = 0;
  const panel = (title, content) => {
    const section = node("section", null, "block");
    section.id = "section-" + (++sectionCounter); section.dataset.outline = title;
    const header = node("header", null, "block-head"); header.append(node("h2", title));
    const body = node("div", null, "block-body"); body.append(content);
    section.append(header, body);
    return section;
  };
  const plainTable = (headings, rows, title) => {
    const wrapper = node("div", null, "table-scroll"); wrapper.tabIndex = 0; wrapper.setAttribute("role", "region"); wrapper.setAttribute("aria-label", title);
    const result = node("table"); result.append(node("caption", title));
    const head = node("thead"), headRow = node("tr"), body = node("tbody");
    headings.forEach(label => { const cell = node("th", label); cell.scope = "col"; headRow.append(cell); });
    head.append(headRow);
    rows.forEach(row => { const tr = node("tr"); row.forEach(value => { const cell = node("td", null, value instanceof Node && value.classList && value.classList.contains("fact-value") ? "fig-cell" : ""); cell.append(value instanceof Node ? value : node("span", value)); tr.append(cell); }); body.append(tr); });
    result.append(head, body); wrapper.append(result); return wrapper;
  };
  const sourceText = (citations) => citations.map(c => `${c.source_id} · ${c.locator}\nSHA-256 ${c.source_sha256}\n${c.quote}`).join("\n\n");
  const factButton = (fact, owner, inTable) => {
    const button = node("button", inTable ? fact.table_display : fact.display, "fact-value");
    button.type = "button"; button.dataset.factId = fact.fact_id; button.dataset.moduleId = owner.module_id;
    button.setAttribute("aria-label", `Inspect ${fact.label}`);
    button.addEventListener("click", () => {
      const kind = fact.status !== "known" ? "gap" : fact.calculation_id ? "calculated" : report.run.case_kind === "synthetic" ? "synthetic" : "cited";
      const fields = [["Field", `${owner.module_id} / ${fact.table_id} / ${fact.row_id} / ${fact.field}`],
        ["Label", fact.label], ["Value class", fact.value_class], ["Source value", fact.source_amount], ["Stated comparison", fact.stated_amount],
        ["Calculation status", fact.calculation_status], ["Formula", fact.formula], ["Value", fact.display], ["Status", fact.status],
        ["Period", fact.period], ["Unit", fact.unit], ["Currency", fact.currency], ["Scale", fact.scale], ["Basis", fact.basis],
        ["Denominator", fact.denominator], ["Calculation", fact.calculation_id],
        ["Evidence", sourceText(fact.citations) || "No citation supplied"], ["Limitation", fact.limitation], ["Artifact SHA-256", owner.artifact_sha256]];
      const peers = owner.facts.filter(other => other.table_id === fact.table_id && other.row_id === fact.row_id);
      openInspector(() => passportCard(kind, fact.fact_id, fact.label, fields), () => {
        const twin = node("div"); twin.append(node("p", `Table twin · ${fact.table_id} / ${fact.row_id}`, "twin-title"),
          plainTable(["Field", "Value", "Period"], peers.map(other => [other.label, other.table_display, other.period]), fact.table_id));
        return twin;
      }, button);
    });
    return button;
  };
  const renderModule = (module) => {
    const content = node("div");
    content.append(chip(module.status_glyph, module.status_word));
    if (module.limitations.length) content.append(panel("Scope and limitations", node("p", module.limitations[0], "text-content")));
    if (module.aliases.length) content.append(node("p", "Also invoked by " + module.aliases.join(", "), "muted"));
    if (!module.facts.length && !module.claims.length) {
      const message = module.status_glyph === "na"
        ? `${module.title} is not part of the ${front.pathway.title} Pathway, so it is not run.`
        : "No validated output is available for this module. Its findings and figures will appear here after the module is run and checked.";
      content.append(panel("Analysis", node("p", message, "empty-state")));
    }
    module.claims.forEach(claim => {
      const body = node("div"), text = node("p", null, "text-content");
      text.append(...runNodes(claim.runs, {title: "Finding", rows: []}, "")); body.append(text); body.dataset.claimId = claim.claim_id;
      const evidence = node("button", "Inspect supporting evidence", "source-button"); evidence.type = "button";
      evidence.addEventListener("click", () => openInspector(() => passportCard(report.run.case_kind === "synthetic" ? "synthetic" : "cited", claim.claim_id, claim.plain, [
        ["Claim", claim.claim_id], ["Evidence", sourceText(claim.citations) || "No citation supplied"], ["Limitation", claim.limitation], ["Artifact SHA-256", module.artifact_sha256]]), null, evidence));
      body.append(evidence); content.append(panel("Finding", body));
    });
    const groups = new Map(); const laidOut = new Set(module.tables.map(layout => layout.table_id));
    const factsById = new Map(module.facts.map(fact => [fact.fact_id, fact]));
    module.tables.forEach(layout => {
      const headings = layout.columns.map(column => column.label);
      if (layout.row_header) headings.unshift(layout.row_header);
      const rows = layout.rows.map(row => {
        const cells = row.fact_ids.map(id => factButton(factsById.get(id), module, true));
        if (layout.row_header) cells.unshift(row.label);
        return cells;
      });
      const matrix = plainTable(headings, rows, layout.title); matrix.dataset.tableId = layout.table_id;
      matrix.querySelectorAll("tbody tr").forEach((tr, index) => {
        tr.dataset.rowId = layout.rows[index].row_id;
        layout.columns.forEach((column, offset) => { tr.children[offset + (layout.row_header ? 1 : 0)].dataset.field = column.field; });
      });
      if (layout.row_header) matrix.querySelectorAll("tbody tr").forEach(tr => { const th = node("th", tr.firstChild.textContent); th.scope = "row"; tr.replaceChild(th, tr.firstChild); });
      if (!rows.length) matrix.append(node("p", "No rows supplied for this register.", "muted"));
      const body = node("div");
      if (layout.limitation) body.append(node("p", layout.limitation, "text-content"));
      body.append(matrix); content.append(panel(layout.table_id + " · " + layout.title, body));
    });
    module.facts.forEach(fact => { if (laidOut.has(fact.table_id)) return; if (!groups.has(fact.table_id)) groups.set(fact.table_id, []); groups.get(fact.table_id).push(fact); });
    groups.forEach((facts, id) => content.append(panel(id, plainTable(["Record", "Field", "Value", "Period / units", "Status"], facts.map(fact => [
      fact.row_id, fact.label, factButton(fact, module, false), [fact.period, fact.unit, fact.currency, "scale " + fact.scale].filter(Boolean).join(" · "), fact.status.replace(/_/g, " ")
    ]), id + " · artifact values"))));
    module.limitations.slice(1).forEach(text => content.append(panel("Limitation", node("p", text, "text-content"))));
    return content;
  };
  // The Model destination (decision 0006 DC-5): the CP-MODEL artifact above the CP-1 register detail.
  // A published Model (task 7.1a) shows its calculation JSON link and publication provenance, read from the
  // module's own registers; a module that has not run says so and offers none.
  const renderModelArtifact = () => {
    const model = report.modules.find(item => item.module_id === "CP-MODEL");
    const body = node("div");
    if (model) body.append(chip(model.status_glyph, model.status_word));
    const fact = (table, row, field) => { const found = model && model.facts.find(item => item.table_id === table && item.row_id === row && item.field === field); return found ? found.text : null; };
    const path = fact("model-destination", "calculation-json", "path"), cp1 = fact("model-provenance", "cp1-head", "sha256"), pack = fact("model-provenance", "pack", "sha256");
    if (model && model.artifact_sha256 && path && /^[A-Za-z0-9._-]+$/.test(path) && cp1 && pack) {
      const json = node("p", "Calculation JSON: ", "text-content"), link = node("a", path); link.href = path; json.append(link);
      const page = node("p", "Its status and limitations are on the ", "text-content"), anchor = node("a", "CP-MODEL page"); anchor.href = "#CP-MODEL"; page.append(anchor, ".");
      body.append(json, node("p", `Published as head ${model.artifact_sha256.slice(0, 12)} from CP-1 head ${cp1.slice(0, 12)} · pack ${pack.slice(0, 12)}`, "muted"), node("p", "This destination shows CP-1 and CP-MODEL only; other modules appear on the Front Page.", "muted"), page);
      return panel("Model", body);
    }
    let words;
    if (!model || model.status_glyph === "unrun") words = "Model not run: CP-MODEL has not published the Model destination, so no calculation JSON has been emitted.";
    else if (model.status_glyph === "na") words = `Model is not part of the ${front.pathway.title} Pathway, so it is not run.`;
    else words = "Its status and limitations are on the CP-MODEL page.";
    const text = node("p", words, "text-content");
    if (model && model.status_glyph !== "unrun" && model.status_glyph !== "na") { const link = node("a", "CP-MODEL"); link.href = "#CP-MODEL"; text.append(" ", link); }
    body.append(text);
    return panel("Model", body);
  };
  const TABLE_KINDS = new Set(["dense", "keyvalue", "period_grid"]);
  const renderFront = () => {
    const root = node("div", null, "front-grid");
    // DS-04 section 5: a table block with nothing to show is hidden here and listed under Limitations.
    front.blocks.filter(block => !(block.state === "absent" && TABLE_KINDS.has(block.kind))).forEach(block => root.append(renderBlock(block)));
    return root;
  };
  const renderAnalysis = () => {
    const root = node("div");
    const summary = node("div", null, "summary-grid");
    summary.append(panel("Research scope", node("p", `${report.responsibilities.modules} analytical and delivery responsibilities, including ${report.responsibilities.alternates} alternate commands. Aliases run the complete owning workflow.`)),
      panel("Qualification", node("p", `Analytical: ${report.analytical_qualification}. Native Copilot: ${report.native_host_qualification}.`)));
    root.append(summary, panel("Module coverage", plainTable(["Module", "Responsibility", "Status"], report.modules.map(module => {
      const link = node("a", module.module_id); link.href = "#" + module.module_id;
      const status = node("span", null, "status-cell"); status.append(glyph(module.status_glyph, 13), document.createTextNode(module.status_word));
      return [link, module.title, status];
    }), "Current report coverage")));
    return root;
  };
  const renderSources = () => {
    const root = node("div");
    if (report.rejected_count) root.append(panel("Rejected attempts", node("p", `${report.rejected_count} rejected attempt(s) are kept in evidence and are not displayed.`, "muted")));
    if (!report.sources.length) { root.append(panel("Source inventory", node("p", "No source pack has been prepared. Readability and source readiness are unrun.", "empty-state"))); return root; }
    root.append(panel("Source inventory", plainTable(["Source", "Readiness", "Limitation"], report.sources.map(source => {
      const button = node("button", source.name, "source-button"); button.type = "button"; button.dataset.sourceId = source.source_id;
      button.addEventListener("click", () => openInspector(() => passportCard(report.run.case_kind === "synthetic" ? "synthetic" : "cited", source.source_id, source.name, [
        ["Source", source.source_id], ["SHA-256", source.sha256], ["Status", source.status], ["Extractor", source.extractor], ["Extraction", source.extraction_status],
        ["Coverage", source.coverage.map(item => `${item.locator}: ${item.status}${item.limitation ? " · " + item.limitation : ""}`).join("\n")],
        ["Content", source.spans.map(span => `${span.locator}\n${span.text}\nType: ${span.data_type ?? "text"}; format: ${span.number_format ?? "not supplied"}; hidden: ${span.hidden}\nFormula: ${span.formula ?? "none"}\nStored cache: ${span.cached_value ?? "not supplied"}\nNote: ${span.note ?? "none"}`).join("\n\n")],
        ["Limitation", source.limitation]]), null, button));
      return [button, source.status, source.limitation || "—"];
    }), "Prepared evidence")));
    return root;
  };
  const renderLimitations = () => {
    const root = node("div");
    root.append(panel("Qualification limits", node("p", "Unrun modules are not qualified. Passing structure or rendering checks does not establish analytical correctness.")));
    const open = front.blocks.filter(block => block.state !== "populated" && block.state !== "collapsed");
    if (open.length) {
      const list = node("ul", null, "text-content");
      open.forEach(block => { const item = node("li"); item.textContent = `${block.title} (${report.block_states[block.state].word}): ${block.note}`; list.append(item); });
      root.append(panel("Blocks without content", list));
    }
    if (front.unplaced.length) {
      const list = node("ul", null, "text-content");
      front.unplaced.forEach(entry => { const item = node("li"); item.textContent = `${entry.title} · ${entry.block_id} (${report.block_states[entry.state].word}): ${entry.note}`; list.append(item); });
      root.append(panel("Bound outside this Pathway", list));
    }
    report.modules.forEach(item => item.limitations.forEach(text => root.append(panel(item.module_id, node("p", text, "text-content")))));
    return root;
  };

  // ---- routing, rail, navigator ------------------------------------------------------------
  const routeOf = () => { const route = location.hash.slice(1) || "front"; return route === "overview" ? "front" : route; };
  const moduleFor = (route) => report.modules.find(item => item.module_id === route || item.aliases.includes(route));
  const DEST = [["front", "Front Page", "#front"], ["analysis", "Analysis", "#analysis"], ["model", "Model", "#CP-1"],
    ["fit", "Portfolio Fit", "#FIT"], ["evidence", "Evidence", "#evidence"], ["limits", "Limitations", "#limitations"]];
  const destOf = (route) => {
    const module = moduleFor(route);
    if (module) return module.module_id === "CP-1" ? "model" : "analysis";
    return {front: "front", analysis: "analysis", FIT: "fit", evidence: "evidence", limitations: "limits"}[route] || null;
  };
  // Bindings outside this Pathway are listed under Limitations too, so they light the rail.
  const hasLimitations = report.modules.some(item => item.limitations.length) || front.unplaced.length > 0;
  const showNavigator = (open) => {
    $("navigator").classList.toggle("open", open); $("toggle-nav").setAttribute("aria-expanded", String(open));
  };
  const railButton = (label, name, extra) => {
    const result = extra || node("button"); result.classList.add("rail-btn");
    if (result.tagName === "BUTTON") result.type = "button";
    result.title = label; result.setAttribute("aria-label", label); result.append(icon(name, 16)); return result;
  };
  const buildRail = () => {
    const dests = $("rail-dests");
    DEST.forEach(([key, label, href]) => {
      const link = railButton(label + (key === "limits" && hasLimitations ? " · with limitations" : ""), key, node("a")); link.href = href; link.dataset.dest = key;
      if (key === "limits" && hasLimitations) link.append(node("span", null, "rail-dot"));
      dests.append(link);
    });
    const foot = $("rail-foot");
    const toggle = railButton("Toggle module navigator", "menu"); toggle.id = "toggle-nav"; toggle.setAttribute("aria-expanded", "false");
    toggle.addEventListener("click", () => { const open = !$("navigator").classList.contains("open"); showNavigator(open); if (open) $("module-filter").focus(); });
    const search = railButton("Search (/)", "search"); search.addEventListener("click", focusSearch);
    const help = railButton("How to read a figure", "help"); help.addEventListener("click", () => openInspector(null, null, help, "key"));
    const print = railButton("Print", "print"); print.id = "print"; print.addEventListener("click", () => window.print());
    foot.append(toggle, search, help, print);
  };
  const syncRail = (route) => {
    const current = destOf(route);
    document.querySelectorAll("[data-dest]").forEach(link => { if (link.dataset.dest === current) link.setAttribute("aria-current", "page"); else link.removeAttribute("aria-current"); });
  };
  const focusSearch = () => {
    if (window.matchMedia("(max-width:1350px)").matches) showNavigator(true);
    $("module-filter").focus();
  };
  let tally = "all";
  let pendingScroll = null;
  const renderNavigation = (route) => {
    const filter = $("module-filter").value.trim().toLowerCase();
    const inPathway = report.nav.filter(row => row.in_pathway), outside = report.nav.filter(row => !row.in_pathway);
    const count = (kind) => inPathway.filter(row => row.glyph === kind).length;
    $("tally-label").textContent = "Analysis · " + inPathway.length;
    const chips = $("tally-chips"); chips.replaceChildren();
    [["all", "All"], ["lim", count("lim") + " lim"], ["pass", count("pass") + " pass"], ...(count("blocked") ? [["blocked", count("blocked") + " blocked"]] : [])].forEach(([key, label]) => {
      const button = node("button", label, key === "all" ? "" : "chip-" + key); button.type = "button"; button.setAttribute("aria-pressed", String(tally === key));
      button.addEventListener("click", () => { tally = key; renderNavigation(routeOf()); }); chips.append(button);
    });
    const matches = (row) => !filter || [row.module_id, row.title, row.word, ...row.aliases].join(" ").toLowerCase().includes(filter);
    const list = $("module-list"); list.replaceChildren();
    const current = moduleFor(route);
    inPathway.filter(row => matches(row) && (tally === "all" || row.glyph === tally)).forEach(row => {
      const link = node("a", null, "module-link" + (row.glyph === "unrun" ? " is-unrun" : "")); link.href = "#" + row.module_id;
      link.style.borderLeftColor = row.color;
      if (current && current.module_id === row.module_id) link.setAttribute("aria-current", "page");
      const mark = node("span", null, "mark-glyph"); const symbol = glyph(row.glyph, 13); symbol.title = row.word; mark.append(symbol);
      const title = node("span", row.title, "title"); title.append(node("span", " · " + row.word, "sr-only"));
      link.append(node("span", row.number, "n num"), mark, title, node("span", row.module_id, "code num"));
      list.append(link);
    });
    const foot = $("nav-foot"); foot.replaceChildren();
    const unrun = inPathway.filter(row => row.glyph === "unrun");
    if (unrun.length) foot.append(node("p", `${unrun[0].word} · ${unrun.length}`));
    if (outside.length) {
      const details = node("details"); details.append(node("summary", `${outside[0].word} · ${outside.length}`));
      outside.filter(matches).forEach(row => {
        const link = node("a"); link.href = "#" + row.module_id; link.append(glyph(row.glyph, 12), node("span", row.module_id, "num"), node("span", row.title));
        details.append(link);
      });
      foot.append(details);
    }
    renderSearch(filter);
  };
  const renderSearch = (filter) => {
    const box = $("search-results"); box.replaceChildren();
    if (!filter) return;
    const hit = (kind, code, label, action) => {
      const button = node("button", null, "search-hit"); button.type = "button";
      button.append(node("span", code, "num"), node("span", label)); button.setAttribute("aria-label", `${kind}: ${code} ${label}`);
      button.addEventListener("click", action); return button;
    };
    const group = (title, hits) => { if (!hits.length) return; const section = node("div", null, "search-group"); section.append(node("p", title, "caps"), ...hits); box.append(section); };
    const has = (...parts) => parts.join(" ").toLowerCase().includes(filter);
    group("Figures", front.blocks.filter(block => has(block.title, block.fig_id || "", block.owner)).slice(0, 6)
      .map(block => hit("Figure", block.fig_id || block.owner, block.title, () => {
        pendingScroll = "block-" + block.block_id;
        if (routeOf() === "front") render(); else location.hash = "#front";
      })));
    group("Sources", [
      ...front.passports.filter(item => has(item.ref_id, item.kind, ...item.fields.map(field => field.value))).slice(0, 4)
        .map(item => hit("Reference", item.ref_id, item.fields.length ? item.fields[0].value : item.kind, () => openInspector(() => passportCard(item.kind, item.ref_id, item.fields.length ? item.fields[0].value : item.ref_id, item.fields.map(field => [field.name, field.value])), null, null))),
      ...report.sources.filter(source => has(source.name, source.source_id)).slice(0, 4).map(source => hit("Source", source.source_id, source.name, () => { location.hash = "#evidence"; }))
    ]);
  };
  const renderOutline = (route) => {
    const outline = $("outline"); outline.replaceChildren();
    const targets = Array.from(document.querySelectorAll("#view-root [data-outline]"));
    if (!targets.length) return;
    outline.append(node("p", "On this page", "caps"));
    const entries = route === "front" ? [{label: "The call", target: $("call-root").firstChild}, ...targets.map(target => ({label: target.dataset.outline, target, word: target.dataset.stateWord}))]
      : targets.map(target => ({label: target.dataset.outline, target}));
    entries.forEach((entry, index) => {
      const button = node("button", entry.label); button.type = "button"; button.setAttribute("aria-current", String(index === 0));
      // A block that is not shown as content says why in the outline too (FP 01: "condition").
      if (entry.word) button.append(document.createTextNode(" "), node("i", entry.word, "state-word"));
      button.addEventListener("click", () => {
        outline.querySelectorAll("button").forEach(other => other.setAttribute("aria-current", String(other === button)));
        entry.target.scrollIntoView({block: "start"});
      });
      outline.append(button);
    });
  };
  const render = () => {
    sectionCounter = 0;
    const route = routeOf();
    const module = moduleFor(route);
    const root = $("view-root"); root.replaceChildren(); $("call-root").replaceChildren();
    const title = module ? `${module.module_id} · ${module.title}` : ({front: report.run.issuer_name, analysis: "Analysis", evidence: "Evidence", limitations: "Limitations", FIT: "Portfolio Fit"}[route] || "Unknown destination");
    const head = node("header", null, "page-head");
    head.append(node("p", "DEPLOY VII / CREDIT WORKBENCH", "eyebrow"), node("h1", title),
      node("p", `As of ${report.run_display.as_of} · ${report.run.case_kind} case · ${report.run.method_version}`, "muted"));
    if (report.mode === "candidate") head.append(node("span", "CANDIDATE PREVIEW · NOT ACCEPTED", "candidate-label"));
    if (route === "front") $("call-root").append(callBand());
    root.append(head);
    if (module) { if (module.module_id === "CP-1") root.append(renderModelArtifact()); root.append(renderModule(module)); }
    else if (route === "front") root.append(renderFront());
    else if (route === "analysis") root.append(renderAnalysis());
    else if (route === "evidence") root.append(renderSources());
    else if (route === "limitations") root.append(renderLimitations());
    else if (route === "FIT") root.append(panel("Portfolio Fit · not run", node("p", "No portfolio constraints or exposures have been evaluated.", "empty-state")));
    else root.append(panel("Destination unavailable", node("p", "Choose a module from the navigator.")));
    showNavigator(false);
    syncRail(route); renderNavigation(route); renderOutline(route);
    if (pendingScroll) { const target = $(pendingScroll); pendingScroll = null; if (target) target.scrollIntoView({block: "start"}); }
  };

  $("nav-issuer").textContent = report.run.issuer_name;
  $("nav-meta").textContent = `${report.run.issuer_id} · ${report.run_display.as_of} · ${report.run.case_kind}`;
  $("nav-pathway").textContent = front.pathway.title;
  buildRail(); renderInspector();
  $("module-filter").addEventListener("input", () => renderNavigation(routeOf()));
  document.addEventListener("keydown", event => {
    const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(event.target.tagName);
    if (event.key === "/" && !typing && !event.metaKey && !event.ctrlKey && !event.altKey) { event.preventDefault(); focusSearch(); return; }
    if (event.key !== "Escape") return;
    if (inspector.trigger && $("inspector").contains(document.activeElement)) { closeInspector(); return; }
    if ($("module-filter") === document.activeElement && $("module-filter").value) { $("module-filter").value = ""; renderNavigation(routeOf()); return; }
    if ($("navigator").classList.contains("open")) { showNavigator(false); $("toggle-nav").focus(); }
  });
  window.addEventListener("hashchange", render);
  render();
})();
