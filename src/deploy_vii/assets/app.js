/* Direction C DOM/navigation patterns adapted from the reviewed report app.
   Data enters text nodes only; financial values are formatted by Python. */
(() => {
  "use strict";
  const report = JSON.parse(document.getElementById("report-data").textContent);
  const node = (tag, text, className) => {
    const result = document.createElement(tag);
    if (text !== undefined && text !== null) result.textContent = String(text);
    if (className) result.className = className;
    return result;
  };
  const status = (value) => {
    const badge = node("span", value, "status");
    badge.dataset.status = value;
    return badge;
  };
  const panel = (title, content) => {
    const section = node("section", null, "panel");
    const header = node("header", null, "panel-head");
    header.append(node("h2", title));
    const body = node("div", null, "panel-body");
    body.append(content);
    section.append(header, body);
    return section;
  };
  const inspect = (details) => {
    const content = document.getElementById("inspector-content");
    content.replaceChildren();
    Object.entries(details).forEach(([key, value]) => {
      const pair = node("dl");
      pair.append(node("dt", key), node("dd", value ?? "Not supplied"));
      content.append(pair);
    });
    if (window.matchMedia("(max-width:900px)").matches) {
      document.getElementById("inspector").scrollIntoView({block:"start"});
    }
  };
  const table = (headings, rows, title, rowHeaders = false) => {
    const wrapper = node("div", null, "table-scroll");
    wrapper.tabIndex = 0;
    wrapper.setAttribute("role", "region");
    wrapper.setAttribute("aria-label", title);
    const result = node("table");
    result.append(node("caption", title));
    const head = node("thead"), headRow = node("tr"), body = node("tbody");
    headings.forEach(label => {
      const cell = node("th", label); cell.scope = "col"; headRow.append(cell);
    });
    head.append(headRow);
    rows.forEach(row => {
      const tr = node("tr");
      row.forEach((value, index) => {
        const cell = node(rowHeaders && index === 0 ? "th" : "td");
        if (rowHeaders && index === 0) cell.scope = "row";
        cell.append(value instanceof Node ? value : node("span", value)); tr.append(cell);
      });
      body.append(tr);
    });
    result.append(head, body); wrapper.append(result); return wrapper;
  };
  const sourceText = (citations) => citations.map(c =>
    `${c.source_id} · ${c.locator}\nSHA-256 ${c.source_sha256}\n${c.quote}`).join("\n\n");
  const factButton = (fact, owner, inTable = false) => {
    const button = node("button", inTable ? fact.table_display : fact.display, "fact-value");
    button.type = "button";
    button.dataset.factId = fact.fact_id;
    button.dataset.moduleId = owner.module_id;
    button.setAttribute("aria-label", `Inspect ${fact.label}`);
    button.addEventListener("click", () => inspect({
      "Field": `${owner.module_id} / ${fact.table_id} / ${fact.row_id} / ${fact.field}`,
      "Label": fact.label, "Value class": fact.value_class,
      "Source value": fact.source_amount, "Formula": fact.formula,
      "Value": fact.display, "Status": fact.status, "Period": fact.period,
      "Unit": fact.unit, "Currency": fact.currency, "Scale": fact.scale,
      "Basis": fact.basis, "Denominator": fact.denominator,
      "Calculation": fact.calculation_id,
      "Evidence": sourceText(fact.citations) || "No citation supplied",
      "Limitation": fact.limitation, "Artifact SHA-256": owner.artifact_sha256
    }));
    return button;
  };
  const renderModule = (module) => {
    const content = node("div");
    content.append(status(module.status));
    if (module.limitations.length) content.append(panel("Scope and limitations", node("p", module.limitations[0], "text-content")));
    if (module.aliases.length) content.append(node("p", "Also invoked by " + module.aliases.join(", "), "muted"));
    if (!module.facts.length && !module.claims.length) {
      content.append(panel("Analysis", node("p", "No validated output is available for this module. Its findings and figures will appear here after the module is run and checked.", "empty-state")));
    }
    module.claims.forEach(claim => {
      const body = node("div"); body.append(node("p", claim.text, "text-content"));
      const evidence = node("button", "Inspect supporting evidence", "source-button");
      evidence.type = "button"; evidence.addEventListener("click", () => inspect({
        "Claim": claim.claim_id, "Evidence": sourceText(claim.citations) || "No citation supplied",
        "Limitation": claim.limitation
      }));
      body.append(evidence); content.append(panel("Finding", body));
    });
    const groups = new Map();
    const laidOut = new Set(module.tables.map(layout => layout.table_id));
    const factsById = new Map(module.facts.map(fact => [fact.fact_id, fact]));
    module.tables.forEach(layout => {
      const headings = layout.columns.map(column => column.label);
      if (layout.row_header) headings.unshift(layout.row_header);
      const rows = layout.rows.map(row => {
        const cells = row.fact_ids.map(id => factButton(factsById.get(id), module, true));
        if (layout.row_header) cells.unshift(row.label);
        return cells;
      });
      const matrix = table(headings, rows, layout.title, Boolean(layout.row_header));
      matrix.dataset.tableId = layout.table_id;
      matrix.querySelectorAll("tbody tr").forEach((tr, index) => {
        tr.dataset.rowId = layout.rows[index].row_id;
        layout.columns.forEach((column, offset) => {
          tr.children[offset + (layout.row_header ? 1 : 0)].dataset.field = column.field;
        });
      });
      if (!rows.length) matrix.append(node("p", "No rows supplied for this register.", "muted"));
      if (layout.limitation) matrix.prepend(node("p", layout.limitation, "text-content"));
      content.append(panel(layout.table_id + " · " + layout.title, matrix));
    });
    module.facts.forEach(fact => {
      if (laidOut.has(fact.table_id)) return;
      if (!groups.has(fact.table_id)) groups.set(fact.table_id, []);
      groups.get(fact.table_id).push(fact);
    });
    groups.forEach((facts, id) => content.append(panel(id, table(
      ["Record", "Field", "Value", "Period / units", "Status"], facts.map(fact => [
        fact.row_id, fact.label, factButton(fact, module),
        [fact.period, fact.unit, fact.currency, "scale " + fact.scale].filter(Boolean).join(" · "),
        status(fact.status)
      ]), id + " · artifact values"
    ))));
    module.limitations.slice(1).forEach(text => content.append(panel("Limitation", node("p", text, "text-content"))));
    return content;
  };
  const renderOverview = () => {
    const root = node("div");
    const call = node("section", null, "call-band");
    call.append(node("p", "CREDIT ASSESSMENT", "eyebrow"), node("h2", "Assessment pending"),
      node("p", "No final credit recommendation has been qualified. Module status and supporting evidence remain visible throughout the research process."));
    root.append(call);
    const summary = node("div", null, "summary-grid");
    summary.append(panel("Research scope", node("p", "25 analytical and delivery responsibilities, including 16 alternate commands. Aliases run the complete owning workflow.")),
      panel("Qualification", node("p", `Analytical: ${report.analytical_qualification}. Native Copilot: ${report.native_host_qualification}.`)));
    root.append(summary, panel("Module coverage", table(["Module", "Responsibility", "Status"], report.modules.map(module => {
      const link = node("a", module.module_id); link.href = "#" + module.module_id;
      return [link, module.title, status(module.status)];
    }), "Current report coverage")));
    return root;
  };
  const renderSources = () => {
    if (!report.sources.length) return panel("Source inventory", node("p", "No source pack has been prepared. Readability and source readiness are unrun.", "empty-state"));
    return panel("Source inventory", table(["Source", "Readiness", "Limitation"], report.sources.map(source => {
      const button = node("button", source.name, "source-button"); button.type = "button";
      button.dataset.sourceId = source.source_id;
      button.addEventListener("click", () => inspect({"Source": source.source_id, "SHA-256": source.sha256,
        "Status": source.status, "Extractor": source.extractor, "Extraction": source.extraction_status,
        "Coverage": source.coverage.map(item => `${item.locator}: ${item.status}${item.limitation ? ' · ' + item.limitation : ''}`).join("\n"),
        "Content": source.spans.map(span => `${span.locator}\n${span.text}\nType: ${span.data_type ?? 'text'}; format: ${span.number_format ?? 'not supplied'}; hidden: ${span.hidden}\nFormula: ${span.formula ?? 'none'}\nStored cache: ${span.cached_value ?? 'not supplied'}\nNote: ${span.note ?? 'none'}`).join("\n\n"),
        "Limitation": source.limitation}));
      return [button, status(source.status), source.limitation || "—"];
    }), "Prepared evidence"));
  };
  const renderNavigation = () => {
    const filter = document.getElementById("module-filter").value.toLowerCase();
    const list = document.getElementById("module-list"); list.replaceChildren();
    report.modules.filter(module => [module.module_id,module.title,module.status,...module.aliases].join(" ").toLowerCase().includes(filter)).forEach(module => {
      const link = node("a", null, "module-link"); link.href = "#" + module.module_id;
      if (location.hash === link.hash) link.setAttribute("aria-current", "page");
      link.append(status(module.status), node("strong", module.module_id), node("small", module.title));
      list.append(link);
    });
  };
  const render = () => {
    const route = location.hash.slice(1) || "overview";
    const module = report.modules.find(item => item.module_id === route || item.aliases.includes(route));
    const root = document.getElementById("view-root"); root.replaceChildren();
    const title = module ? `${module.module_id} · ${module.title}` : ({overview:report.run.issuer_name,evidence:"Evidence",limitations:"Limitations",FIT:"Portfolio Fit"}[route] || "Unknown destination");
    const head = node("header", null, "page-head");
    head.append(node("p", "DEPLOY VII / CREDIT WORKBENCH", "eyebrow"), node("h1", title),
      node("p", `As of ${report.run.as_of} · ${report.run.case_kind} case · ${report.run.method_version}`, "muted"));
    if (report.mode === "candidate") head.append(node("span", "CANDIDATE PREVIEW · NOT ACCEPTED", "candidate-label"));
    root.append(head);
    if (module) root.append(renderModule(module));
    else if (route === "overview") root.append(renderOverview());
    else if (route === "evidence") root.append(renderSources());
    else if (route === "limitations") {
      root.append(panel("Qualification limits", node("p", "Unrun modules are not qualified. Passing structure or rendering checks does not establish analytical correctness.")));
      report.modules.forEach(item => item.limitations.forEach(text => root.append(panel(item.module_id, node("p", text, "text-content")))));
    } else if (route === "FIT") root.append(panel("Portfolio Fit · unrun", node("p", "No portfolio constraints or exposures have been evaluated.", "empty-state")));
    else root.append(panel("Destination unavailable", node("p", "Choose a module from the navigator.")));
    document.getElementById("breadcrumb").textContent = "Credit research / " + title;
    document.getElementById("navigator").classList.remove("open");
    document.getElementById("toggle-nav").setAttribute("aria-expanded", "false");
    renderNavigation();
  };
  document.getElementById("nav-issuer").textContent = report.run.issuer_name;
  document.getElementById("nav-date").textContent = report.run.as_of + " · " + report.run.case_kind;
  document.getElementById("module-filter").addEventListener("input", renderNavigation);
  document.getElementById("toggle-nav").addEventListener("click", () => {
    const open = document.getElementById("navigator").classList.toggle("open");
    document.getElementById("toggle-nav").setAttribute("aria-expanded", String(open));
    if (open) document.getElementById("module-filter").focus();
  });
  document.getElementById("inspect-button").addEventListener("click", () => {
    const inspector = document.getElementById("inspector"); inspector.tabIndex = -1; inspector.focus();
  });
  document.getElementById("print").addEventListener("click", () => window.print());
  document.addEventListener("keydown", event => {
    if (event.key === "Escape") {
      document.getElementById("navigator").classList.remove("open");
      document.getElementById("toggle-nav").setAttribute("aria-expanded", "false");
      document.getElementById("toggle-nav").focus();
    }
  });
  window.addEventListener("hashchange", render);
  render();
})();
