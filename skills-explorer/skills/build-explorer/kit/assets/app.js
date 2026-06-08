/* Skills & Prompts Explorer — SPA
 * No framework, no build step. Merges the generated manifest (mechanical) with
 * the curated data (authored graphs/editorial) by id. Renders a sidebar tree,
 * search, a home grid, and per-artifact detail pages with an inline SVG
 * workflow diagram. Source bodies are lazy-loaded over HTTP.
 *
 * Diagrams trace to real files: curated graphs are hand-authored from reading the
 * artifact; when none exists, a faithful "shape" diagram is derived from the
 * artifact's actual section headings (or its input→model→output shape). Steps are
 * never invented — if the source has no process, the diagram says so and stays minimal.
 */
(function () {
  "use strict";

  // Path back to repo root from /docs/explorer/index.html
  var ROOT = "../../";
  // Per-repo branding (set in index.html via window.EXPLORER_CONFIG). All optional.
  var CONFIG = (window.EXPLORER_CONFIG) || {};
  var state = { manifest: null, curated: {}, byId: {}, kindFilter: "all", query: "" };

  // Apply branding from EXPLORER_CONFIG so the engine files stay repo-agnostic.
  function applyConfig() {
    var brand = CONFIG.brand || "Skills & Prompts";
    var tagline = CONFIG.tagline || "Explorer";
    try { document.title = brand + " — " + tagline; } catch (e) {}
    var logo = document.getElementById("brand-logo");
    if (logo) logo.innerHTML = esc(brand) + '<span class="dot">.</span>';
    var sub = document.getElementById("brand-sub");
    if (sub) sub.textContent = tagline;
    if (CONFIG.accent) document.documentElement.style.setProperty("--accent", CONFIG.accent);
  }

  // ───────────────────────────── boot ─────────────────────────────
  function init() {
    applyConfig();
    state.curated = (window.EXPLORER_DATA && window.EXPLORER_DATA.artifacts) || {};
    fetch("explorer-manifest.json", { cache: "no-cache" })
      .then(function (r) { if (!r.ok) throw new Error("manifest " + r.status); return r.json(); })
      .then(function (m) {
        state.manifest = m;
        m.artifacts.forEach(function (a) { state.byId[a.id] = a; });
        buildSidebar();
        window.addEventListener("hashchange", route);
        route();
      })
      .catch(function (e) {
        document.querySelector(".content").innerHTML =
          '<div class="errbox">Could not load explorer-manifest.json (' + esc(e.message) +
          ').<br/>Serve the repo over HTTP — e.g. <code>python3 docs/explorer/serve.py</code> — then open /docs/explorer/.</div>';
      });
    wireChrome();
  }

  function wireChrome() {
    var theme = localStorage.getItem("explorer-theme") || "light";
    setTheme(theme);
    document.getElementById("theme-btn").addEventListener("click", function () {
      setTheme(document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark");
    });
    var search = document.getElementById("search");
    search.addEventListener("input", function () { state.query = search.value.trim().toLowerCase(); buildSidebar(); });
    document.addEventListener("keydown", function (e) {
      if (e.key === "/" && document.activeElement !== search) { e.preventDefault(); search.focus(); }
      if (e.key === "Escape" && document.activeElement === search) { search.value = ""; state.query = ""; buildSidebar(); search.blur(); }
    });
    var menu = document.getElementById("menu-btn");
    if (menu) menu.addEventListener("click", function () {
      document.querySelector(".sidebar").classList.toggle("open");
      document.querySelector(".scrim").classList.toggle("show");
    });
    var scrim = document.querySelector(".scrim");
    if (scrim) scrim.addEventListener("click", function () {
      document.querySelector(".sidebar").classList.remove("open");
      scrim.classList.remove("show");
    });
  }

  function setTheme(t) {
    document.documentElement.setAttribute("data-theme", t);
    localStorage.setItem("explorer-theme", t);
    document.getElementById("theme-btn").textContent = t === "dark" ? "☾ Dark" : "☀ Light";
  }

  // ───────────────────────────── sidebar ─────────────────────────────
  var KIND_LABEL = {
    "skill": "Skill", "agent": "Agent", "system-prompt": "System prompt",
    "prompt-template": "Prompt template", "instruction-doc": "Instruction doc",
    "managed-agent": "Managed agent", "subagent": "Subagent"
  };

  function matchQuery(a) {
    if (state.kindFilter !== "all" && a.kind !== state.kindFilter) return false;
    if (!state.query) return true;
    var hay = (a.title + " " + a.id + " " + a.category + " " + (a.description || "") + " " + (a.source_path || "")).toLowerCase();
    return hay.indexOf(state.query) !== -1;
  }

  function buildSidebar() {
    var arts = state.manifest.artifacts.filter(matchQuery);
    var groups = {};
    arts.forEach(function (a) { (groups[a.category] = groups[a.category] || []).push(a); });

    var order = Object.keys(groups).sort(function (x, y) { return groups[y].length - groups[x].length || x.localeCompare(y); });
    var tree = document.getElementById("tree");
    tree.innerHTML = "";

    // kind filter buttons
    var kf = document.getElementById("kind-filter");
    if (!kf.dataset.built) {
      var kinds = ["all"].concat(Array.from(new Set(state.manifest.artifacts.map(function (a) { return a.kind; }))));
      kf.innerHTML = kinds.map(function (k) {
        return '<button data-k="' + k + '">' + (k === "all" ? "All" : (KIND_LABEL[k] || k)) + "</button>";
      }).join("");
      kf.querySelectorAll("button").forEach(function (b) {
        b.addEventListener("click", function () {
          state.kindFilter = b.dataset.k;
          kf.querySelectorAll("button").forEach(function (x) { x.classList.toggle("active", x.dataset.k === state.kindFilter); });
          buildSidebar();
        });
      });
      kf.dataset.built = "1";
    }
    kf.querySelectorAll("button").forEach(function (x) { x.classList.toggle("active", x.dataset.k === state.kindFilter); });

    var active = currentId();
    order.forEach(function (cat) {
      var items = groups[cat].sort(function (a, b) { return a.title.localeCompare(b.title); });
      var g = document.createElement("div");
      g.className = "tree-group";
      var head = document.createElement("div");
      head.className = "grp-head";
      head.innerHTML = '<span><span class="caret">▾</span>' + esc(cat) + '</span><span class="count">' + items.length + "</span>";
      head.addEventListener("click", function () { g.classList.toggle("collapsed"); });
      g.appendChild(head);
      var box = document.createElement("div");
      box.className = "grp-items";
      items.forEach(function (a) {
        var el = document.createElement("a");
        el.className = "tree-item" + (a.id === active ? " active" : "");
        el.href = "#/a/" + encodeURIComponent(a.id);
        el.innerHTML = esc(a.title) + ' <span class="ki">· ' + (KIND_LABEL[a.kind] || a.kind) + "</span>";
        box.appendChild(el);
      });
      g.appendChild(box);
      tree.appendChild(g);
    });
    if (arts.length === 0) tree.innerHTML = '<div class="loading" style="padding:10px 16px">No artifacts match.</div>';
  }

  // ───────────────────────────── router ─────────────────────────────
  function currentId() {
    var m = /^#\/a\/(.+)$/.exec(location.hash);
    return m ? decodeURIComponent(m[1]) : null;
  }
  function route() {
    var id = currentId();
    document.querySelector(".sidebar").classList.remove("open");
    var scrim = document.querySelector(".scrim"); if (scrim) scrim.classList.remove("show");
    if (id && state.byId[id]) renderDetail(state.byId[id]);
    else renderHome();
    buildSidebar();
    window.scrollTo(0, 0);
  }

  // ───────────────────────────── home ─────────────────────────────
  function renderHome() {
    var m = state.manifest, c = m.coverage;
    var cv = state.byId, curatedCount = Object.keys(state.curated).length;
    var html = "";
    html += '<div class="crumbs">Explorer</div>';
    html += '<h1 class="title">Skills &amp; Prompts Explorer</h1>';
    html += '<p class="lede">Every agent, system prompt, prompt template and instruction doc in this repository — each with a generated workflow diagram traced to its source file. ' +
      'Built from <code>explorer-manifest.json</code> (mechanical) merged with curated graphs in <code>assets/explorer-data.js</code>.</p>';

    html += '<div class="statgrid">';
    html += stat(c.total, "artifacts");
    Object.keys(c.counts_by_kind).sort().forEach(function (k) { html += stat(c.counts_by_kind[k], KIND_LABEL[k] || k); });
    html += stat(curatedCount, "curated graphs");
    html += "</div>";

    // coverage block
    html += '<section class="block"><h2>Coverage — where we looked</h2><ul class="clean">';
    c.searched_patterns.forEach(function (p) { html += "<li>" + esc(p) + "</li>"; });
    html += "</ul><p class=\"note\">Generated " + esc(m.generatedAt) + " · PyYAML " + (m.pyyaml ? "available" : "fallback parser") + "</p></section>";

    // category card grid
    var cats = {};
    m.artifacts.forEach(function (a) { (cats[a.category] = cats[a.category] || []).push(a); });
    html += '<section class="block"><h2>Browse by category</h2><div class="cards">';
    Object.keys(cats).sort(function (x, y) { return cats[y].length - cats[x].length; }).forEach(function (cat) {
      var first = cats[cat][0];
      html += '<div class="card" data-go="' + esc(first.id) + '">' +
        '<div class="ck">' + esc(cat) + "</div>" +
        "<h3>" + cats[cat].length + " artifact" + (cats[cat].length === 1 ? "" : "s") + "</h3>" +
        '<p>' + esc(cats[cat].slice(0, 6).map(function (a) { return a.title; }).join(" · ")) + "</p>" +
        "</div>";
    });
    html += "</div></section>";

    setContent(html);
    document.querySelectorAll(".card[data-go]").forEach(function (el) {
      el.addEventListener("click", function () { location.hash = "#/a/" + encodeURIComponent(el.dataset.go); });
    });
  }
  function stat(n, l) { return '<div class="stat"><div class="n">' + n + '</div><div class="l">' + esc(l) + "</div></div>"; }

  // ───────────────────────────── detail ─────────────────────────────
  function renderDetail(a) {
    var cur = state.curated[a.id] || {};
    var html = "";
    html += '<div class="crumbs"><a href="#/">Explorer</a> › ' + esc(a.category) + " › " + esc(a.title) + "</div>";
    html += '<h1 class="title">' + esc(a.title) + "</h1>";
    var lede = cur.summary || a.description || a.jsdoc || "";
    if (lede) html += '<p class="lede">' + esc(lede) + "</p>";

    // pills
    html += '<div class="pills">';
    html += pill("kind", KIND_LABEL[a.kind] || a.kind, true);
    html += pill("category", a.category);
    if (a.model) html += pill("model", a.model);
    if (a.maxTurns) html += pill("max turns", a.maxTurns);
    if (a.costTier) html += pill("cost tier", a.costTier);
    if (a.seniority) html += pill("seniority", a.seniority);
    if (a.billingRateUsd) html += pill("rate", "$" + a.billingRateUsd + "/hr");
    if (a.archetype) html += pill("archetype", a.archetype);
    if (a.outputFormat) html += pill("output schema", a.outputFormat);
    if (a.format) html += pill("format", a.format);
    html += "</div>";

    // ── assessment card (structured; authored fields override grounded fallback) ──
    html += buildAssessment(a, cur);

    // ── programmatic surface (repo extension: claude-for-legal skills carry
    //    tool grants, MCP connections, bundled resources and invocation modes) ──
    html += buildProgrammatic(a);

    if (a.practiceAreas && a.practiceAreas.length) {
      html += block("Practice areas", '<div class="pills">' + a.practiceAreas.map(function (p) { return pill("", p); }).join("") + "</div>");
    }

    // workflow diagram
    var graph = cur.graph || shapeGraph(a, cur);
    state.current = { a: a, graph: graph };
    var provNote = cur.graph
      ? "Curated graph — hand-authored from reading <code>" + esc(a.source_path) + "</code>."
      : (graph._shape === "headings"
          ? "Diagram derived from the section headings in <code>" + esc(a.source_path) + "</code> (steps are real headings, not invented)."
          : "Shape diagram — this prompt has no explicit multi-step process in the source, so it shows input → model → output only.");
    html += '<section class="block diagram-block"><h2>Workflow diagram</h2>' +
      '<p class="note">Click any step to read its summary and reveal the verbatim source section.</p>' +
      '<div class="diagram-layout">' +
        '<div class="diagram-wrap" id="diagram-wrap">' + buildDiagram(graph) + "</div>" +
        '<div class="node-panel" id="node-panel"><div class="np-placeholder">Click a step in the diagram to see what it does and read its exact source.</div></div>' +
      "</div>" +
      diagramLegend(graph) +
      '<p class="note">' + provNote + "</p></section>";

    // inputs / template variables
    if (cur.inputs && cur.inputs.length) {
      html += block(cur.inputs_label || "Inputs", ioTable(cur.inputs));
    }
    // outputs
    if (cur.outputs && cur.outputs.length) {
      html += block("Outputs", ioTable(cur.outputs));
    } else if (a.outputFormat) {
      var schemaNote = CONFIG.outputSchemaPath
        ? " (schema defined in <code>" + esc(CONFIG.outputSchemaPath) + "</code>)"
        : "";
      html += block("Outputs", '<p>Returns a validated <code>' + esc(a.outputFormat) +
        '</code> structured output' + schemaNote + "." + pres(true) + "</p>");
    }

    // does not do
    if (cur.does_not_do && cur.does_not_do.length) {
      html += block("What it does <em>not</em> do", '<ul class="clean donot">' +
        cur.does_not_do.map(function (d) { return "<li>" + esc(d) + "</li>"; }).join("") + "</ul>");
    }

    // references & examples
    if (cur.references && cur.references.length) {
      html += block("References", '<ul class="reflist">' + cur.references.map(refLink).join("") + "</ul>");
    }
    if (cur.examples && cur.examples.length) {
      html += block("Examples", '<ul class="clean">' + cur.examples.map(function (e) { return "<li>" + esc(e) + "</li>"; }).join("") + "</ul>");
    }

    // headings list from manifest (always accurate)
    if (a.headings && a.headings.length) {
      html += block("Sections in source",
        '<ul class="clean" style="columns:2;font-size:13px">' +
        a.headings.map(function (h) { return '<li style="margin-left:' + ((h.level - 1) * 10) + 'px">' + esc(h.text) + "</li>"; }).join("") +
        "</ul>");
    }

    // full source (lazy)
    var meta = a.source_path + (a.line_start ? ":" + a.line_start + "-" + a.line_end : "");
    html += '<section class="block"><h2>Source</h2>' +
      '<p class="note">Full body lazy-loaded from the served repo. ' +
      '<a href="' + esc(ROOT + a.source_path) + '" target="_blank" rel="noopener">Open raw file ↗</a></p>' +
      '<details class="source" id="src-details"><summary><span>' +
      (a.embedded ? "Show code excerpt" : "Show full source") +
      '</span><span class="meta">' + esc(meta) + "</span></summary>" +
      '<div class="source-body" id="src-body"><div class="loading">Click to load…</div></div></details></section>';

    setContent(html);

    var det = document.getElementById("src-details");
    det.addEventListener("toggle", function once() {
      if (det.open) { det.removeEventListener("toggle", once); loadSource(a); }
    });

    // wire diagram node clicks (event delegation; click/tap only, no hover)
    var dwrap = document.getElementById("diagram-wrap");
    if (dwrap) {
      dwrap.addEventListener("click", function (e) {
        var g = e.target.closest ? e.target.closest(".dnode") : null;
        if (g) openNode(g.getAttribute("data-node"));
      });
      dwrap.addEventListener("keydown", function (e) {
        if (e.key !== "Enter" && e.key !== " ") return;
        var g = e.target.closest ? e.target.closest(".dnode") : null;
        if (g) { e.preventDefault(); openNode(g.getAttribute("data-node")); }
      });
    }
  }

  // ── assessment card ───────────────────────────────────────────────────────
  // Structured quality/applicability card. Authored cur.assessment fields override
  // a grounded fallback derived from the manifest (profile strengths/limitations/
  // criticalRules + definition model/turns/schema). Fallback fields are labelled.
  function buildAssessment(a, cur) {
    var asm = cur.assessment || {};
    var rows = [];

    var purpose = asm.purpose || cur.summary || a.description || a.jsdoc;
    if (purpose) rows.push(field("Purpose", "<p>" + esc(purpose) + "</p>" + src(asm.purpose ? "authored" : srcKind(a))));

    var goodAt = asm.good_at || a.strengths;
    if (goodAt && goodAt.length) rows.push(field("Good at", listOf(goodAt) + src(asm.good_at ? "authored" : "from profile")));

    var useWhen = asm.use_when || cur.when_to_use || a.description;
    if (useWhen) rows.push(field("Use when", "<p>" + esc(useWhen) + "</p>" + src(asm.use_when || cur.when_to_use ? "authored" : srcKind(a))));

    var avoid = asm.avoid || cur.does_not_do;
    if (avoid && avoid.length) rows.push(field("Avoid / out of scope", listOf(avoid, "donot") + src(asm.avoid ? "authored" : "from curated does-not-do")));
    else if (a.limitations && a.limitations.length) rows.push(field("Avoid / out of scope", listOf(a.limitations, "donot") + src("from profile limitations")));

    var signals = asm.signals || deriveSignals(a);
    if (signals && signals.length) rows.push(field("Quality signals", '<div class="pills">' + signals.map(function (s) { return pill("", s); }).join("") + "</div>" + src(asm.signals ? "authored" : "from definition + source")));

    var limits = asm.limits || a.criticalRules;
    if (limits && limits.length) rows.push(field(asm.limits ? "Limitations & caveats" : "Hard guardrails", listOf(limits) + src(asm.limits ? "authored" : "from profile criticalRules")));

    if (!rows.length) return "";
    return '<section class="block assess"><h2>Assessment</h2><div class="assess-grid">' + rows.join("") + "</div></section>";
  }
  // ── Programmatic surface (repo extension for claude-for-legal) ─────────────
  // Skills/agents in this marketplace are not prose-only: they declare tool
  // grants, MCP server connections, invocation modes (user- vs model-invoked,
  // argument hints) and ship bundled data files (state registers, jurisdiction
  // refs, output templates). All fields below come from the mechanical manifest
  // — explicitly present in frontmatter / agent.yaml / .mcp.json, never inferred.
  function buildProgrammatic(a) {
    var rows = [];
    if (a.invocation) {
      var inv = [];
      if (a.invocation.user_invocable === false) inv.push(pill("", "model-invoked only (user-invocable: false)"));
      else inv.push(pill("", "user-invocable slash command"));
      if (a.invocation.argument_hint) inv.push(pill("args", a.invocation.argument_hint));
      rows.push(field("Invocation", '<div class="pills">' + inv.join("") + "</div>" + src("from frontmatter")));
    }
    if (a.tools && a.tools.length) {
      rows.push(field("Tool access", '<div class="pills">' + a.tools.map(function (t) { return pill("", t); }).join("") + "</div>" +
        src(a.kind === "skill" ? "from frontmatter allowed-tools" : "from " + (a.kind === "agent" ? "agent frontmatter" : "agent.yaml tool scoping"))));
    }
    var mcp = a.mcp_servers || a.plugin_mcp_servers;
    if (mcp && mcp.length) {
      rows.push(field(a.mcp_servers ? "MCP servers" : "Plugin MCP servers",
        '<div class="pills">' + mcp.map(function (s) { return pill("", s); }).join("") + "</div>" +
        src(a.mcp_servers ? "declared in source" : "from plugin .mcp.json (available, not necessarily used)")));
    } else if (a.kind === "managed-agent") {
      rows.push(field("MCP servers", "<p>None — the orchestrator is scoped to local-only tools; MCP toolsets are held by subagent leaves.</p>" + src("from agent.yaml")));
    }
    if (a.callable_agents && a.callable_agents.length) {
      rows.push(field("Callable subagents", '<div class="pills">' + a.callable_agents.map(function (c) { return pill("", c); }).join("") + "</div>" + src("from agent.yaml callable_agents")));
    }
    if (a.skills_from_plugins && a.skills_from_plugins.length) {
      rows.push(field("Skills loaded from", '<div class="pills">' + a.skills_from_plugins.map(function (s) { return pill("", s); }).join("") + "</div>" + src("from agent.yaml skills")));
    }
    if (a.system_file) {
      rows.push(field("System prompt source", '<p><code>' + esc(a.system_file) + '</code> — inlined at deploy time by <code>scripts/deploy-managed-agent.sh</code>' +
        (a.system_append_chars ? ", plus a headless-mode append block in agent.yaml" : "") + ".</p>" + src("from agent.yaml system")));
    }
    if (a.template_intents && a.template_intents.length) {
      rows.push(field("Steering intents", '<div class="pills">' + a.template_intents.map(function (t) { return pill("", t); }).join("") + "</div>" + src("from HANDOFF_TEMPLATES keys")));
    }
    if (a.resources && a.resources.length) {
      rows.push(field("Bundled resources", '<ul class="reflist">' + a.resources.map(function (p) {
        return '<li><a href="' + esc(ROOT + p) + '" target="_blank" rel="noopener">' + esc(p) + "</a></li>";
      }).join("") + "</ul>" + src("files shipped in the artifact's directory")));
    }
    if (!rows.length) return "";
    return '<section class="block assess"><h2>Programmatic surface</h2><div class="assess-grid">' + rows.join("") + "</div></section>";
  }

  function field(label, inner) { return '<div class="assess-row"><div class="assess-k">' + esc(label) + '</div><div class="assess-v">' + inner + "</div></div>"; }
  function listOf(arr, cls) { return '<ul class="clean ' + (cls || "") + '">' + arr.map(function (x) { return "<li>" + esc(x) + "</li>"; }).join("") + "</ul>"; }
  function src(label) { return ' <span class="srctag">' + esc(label) + "</span>"; }
  function srcKind(a) { return a.in_definitions ? "from agent definition" : (a.embedded ? "from source comment" : "from source"); }
  function deriveSignals(a) {
    var s = [];
    if (a.model) s.push("model: " + a.model);
    if (a.maxTurns) s.push("≤ " + a.maxTurns + " turns");
    if (a.costTier && a.costTier !== a.model) s.push("cost tier: " + a.costTier);
    if (a.outputFormat) s.push("validated output (" + a.outputFormat + ")");
    var H = (a.headings || []).map(function (h) { return h.text.toLowerCase(); }).join(" | ");
    if (/self-check/.test(H)) s.push("pre-submission self-check");
    if (/debate board/.test(H)) s.push("posts to debate board");
    if (/false-positive/.test(H)) s.push("false-positive exclusions");
    if (/confidence calculation/.test(H)) s.push("calibrated confidence");
    if (/memory protocol/.test(H)) s.push("institutional memory");
    if (a.criticalRules && a.criticalRules.length) s.push(a.criticalRules.length + " hard guardrails");
    if (a.billingRateUsd) s.push("$" + a.billingRateUsd + "/hr tier");
    // repo extension: programmatic-surface signals (mechanical, from the manifest)
    if (a.tools && a.tools.length) s.push(a.tools.length + " scoped tool grant" + (a.tools.length > 1 ? "s" : ""));
    if (a.invocation && a.invocation.user_invocable === false) s.push("model-invoked reference skill");
    if (a.resources && a.resources.length) s.push("ships bundled resources");
    if (/destination check/.test(H)) s.push("privilege destination check");
    if (/matter context/.test(H)) s.push("matter-workspace aware");
    if (/what this skill does not do/.test(H)) s.push("explicit non-goals section");
    if (/guardrails/.test(H)) s.push("guardrails section");
    return s;
  }

  // ── node section panel (click a diagram step) ─────────────────────────────
  function openNode(id) {
    var cur = state.current;
    if (!cur) return;
    var n = cur.graph.nodes.filter(function (x) { return x.id === id; })[0];
    if (!n) return;
    var panel = document.getElementById("node-panel");
    var typeLabel = { start: "Start", step: "Step", decision: "Decision", output: "Output" }[n.type] || "Step";
    var authored = n.note || n.desc;  // hand-authored summary, if any
    var html = '<button class="np-close" aria-label="Close">×</button>';
    html += '<div class="np-kind n-' + n.type + '">' + (n.num != null ? n.num + " · " : "") + esc(typeLabel) + "</div>";
    html += "<h3>" + esc(n.label || "") + "</h3>";
    if (n.tag) html += '<p class="np-tag">⚑ conditional: ' + esc(n.tag) + "</p>";
    html += '<p class="np-summary" id="np-summary">' + (authored ? esc(authored) : '<span class="np-loading">Reading the source for this step…</span>') + "</p>";
    if (n.chips && n.chips.length) html += '<div class="pills">' + n.chips.map(function (c) { return pill("", c); }).join("") + "</div>";
    if (n.stop) html += '<p class="np-route"><b>Route-out:</b> ' + esc(n.stop) + "</p>";
    if (n.loopTo) html += '<p class="np-route"><b>Loops to step:</b> ' + esc(loopLabel(cur.graph, n.loopTo)) + "</p>";
    if (n.skipTo) html += '<p class="np-route"><b>Skips to step:</b> ' + esc(loopLabel(cur.graph, n.skipTo)) + "</p>";
    // Source snippet is shown by default; the triangle button just collapses it.
    html += '<div class="np-source"><button class="np-srcbtn" aria-expanded="true" aria-label="Hide source for this step" title="Hide source">▾</button>' +
      '<div class="np-srcbody"><div class="np-loading">Loading source…</div></div></div>';

    panel.innerHTML = html;
    panel.classList.add("active");
    panel.dataset.node = id;
    panel.querySelector(".np-close").addEventListener("click", closeNode);
    var btn = panel.querySelector(".np-srcbtn"), body = panel.querySelector(".np-srcbody");

    // Resolve the real source section ONCE; reuse it for the summary and the snippet.
    resolveSection(cur.a, n).then(function (res) {
      if (panel.dataset.node !== id) return;       // a different node was clicked meanwhile
      panel._sec = res;
      if (!authored) {
        var basis = res.sec ? res.sec.body : (res.whole && res.text ? sourceMarkdown(res.text, cur.a) : "");
        var lede = basis ? sectionLede(basis) : "";
        var sEl = panel.querySelector("#np-summary");
        if (sEl) sEl.innerHTML = esc(lede || nodeMinimalSummary(cur.a, n));
      }
      // expanded by default — render the section as soon as it resolves
      if (!body.dataset.loaded) { body.dataset.loaded = "1"; renderSection(cur.a, n, body, res); }
    });

    btn.addEventListener("click", function () {
      var open = btn.getAttribute("aria-expanded") === "true";
      btn.setAttribute("aria-expanded", String(!open));
      body.hidden = open;
      btn.textContent = open ? "▸" : "▾";
      btn.setAttribute("aria-label", (open ? "Show" : "Hide") + " source for this step");
      btn.setAttribute("title", open ? "Show source" : "Hide source");
      if (!open && !body.dataset.loaded) { body.dataset.loaded = "1"; renderSection(cur.a, n, body, panel._sec); }
    });
  }
  function closeNode() {
    var p = document.getElementById("node-panel");
    if (!p) return;
    p.classList.remove("active");
    p.dataset.node = "";
    p.innerHTML = '<div class="np-placeholder">Click a step in the diagram to see what it does and read its exact source.</div>';
  }
  function loopLabel(graph, ref) {
    var t = graph.nodes.filter(function (x) { return x.id === ref.id; })[0];
    return (t ? (t.num != null ? t.num + ". " : "") + t.label : ref.id) + (ref.when ? " — " + ref.when : "");
  }
  // Minimal, honest fallback — never the lazy "Step in <workflow>" placeholder.
  function nodeMinimalSummary(a, n) {
    if (n.type === "start") return "Entry point — the request and its context enter the workflow here.";
    if (n.type === "output") return a.outputFormat ? "Final output: a validated " + a.outputFormat + " structured result." : "Final output of this workflow.";
    return n.label || "";
  }
  // Distil a real one/two-sentence summary from a section's own opening prose.
  function sectionLede(md) {
    var lines = String(md || "").split("\n"), out = [], started = false, inFence = false;
    for (var i = 0; i < lines.length; i++) {
      var ln = lines[i].trim();
      if (/^```/.test(ln)) { inFence = !inFence; continue; }
      if (inFence) continue;
      if (/^#{1,6}\s/.test(ln)) continue;                 // skip heading lines
      if (!ln) { if (started) break; else continue; }      // blank ends the lede once started
      out.push(ln.replace(/^[-*+]\s+/, "").replace(/^\d+[.)]\s+/, ""));
      started = true;
      if (out.join(" ").length > 130) break;
    }
    var text = out.join(" ")
      .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")             // links → text
      .replace(/[`*_>#]/g, "").replace(/\s+/g, " ").trim();
    if (!text) return "";
    var m = text.match(/^(.{40,220}?[.!?:])(\s|$)/);
    var s = m ? m[1] : text.slice(0, 200);
    if (s.length < text.length && !/[.!?:]$/.test(s)) s = s.replace(/\s+\S*$/, "") + "…";
    return s.trim();
  }
  function fetchFileText(a) {
    var cur = state.current;
    if (cur._textCache && cur._textPath === a.source_path) return cur._textCache;
    cur._textPath = a.source_path;
    cur._textCache = fetch(ROOT + a.source_path, { cache: "no-cache" })
      .then(function (r) { if (!r.ok) throw new Error(r.status + ""); return r.text(); });
    return cur._textCache;
  }
  function resolveSection(a, n) {
    // srcWhole nodes deliberately map to the entire (short, section-less) prompt.
    var anchor = n.srcWhole ? null : (n.srcHeading || ((n.type === "step" || n.type === "decision") ? n.label : null));
    return fetchFileText(a)
      .then(function (text) { return { text: text, sec: (anchor ? extractSection(text, a, anchor) : null), anchor: anchor, whole: !!n.srcWhole }; })
      .catch(function (e) { return { text: null, sec: null, anchor: anchor, err: e }; });
  }
  function renderSection(a, n, body, res) {
    if (!res) { body.innerHTML = '<div class="loading">Loading source…</div>'; resolveSection(a, n).then(function (r) { renderSection(a, n, body, r); }); return; }
    if (res.err) { body.innerHTML = '<div class="errbox">Could not load source (' + esc(res.err.message) + ").</div>"; return; }
    var focus = n && n.srcFocus;
    if (res.sec && res.sec.body.trim()) {
      // srcFocus narrows a SHARED section to this node's own item (e.g. one
      // numbered step out of a single "Instructions" list) so sibling nodes
      // don't all show an identical snippet.
      var secBody = res.sec.body, fmeta = "";
      if (focus) {
        var narrowed = focusSlice(secBody, focus);
        if (narrowed) { secBody = narrowed; fmeta = " · this step's excerpt"; }
      }
      body.innerHTML = '<p class="np-srcmeta">' + esc(a.source_path) + (res.sec.lines && !fmeta ? " · lines " + res.sec.lines : "") +
        (res.anchor ? ' · section “' + esc(res.anchor) + "”" : "") + fmeta + '</p><div class="md-body">' + window.marked(secBody) + "</div>";
    } else {
      var label = res.whole
        ? "This prompt has no sub-sections — showing the full prompt."
        : "No distinct heading for this step — showing the full source.";
      var inner;
      // Code sources (python / yaml / ts) must NOT go through the markdown
      // renderer — underscores become italics and # comments become headings.
      if (isCodeSource(a)) {
        var fc = focus ? codeFocusExcerpt(res.text, a, focus) : null;
        if (fc) { inner = fc; label = "This step's excerpt from the prompt."; }
        else { inner = codeExcerpt(res.text, a); }
      } else {
        var md = sourceMarkdown(res.text, a);
        if (focus) { var nr = focusSlice(md, focus); if (nr) { md = nr; label = "This step's excerpt from the source."; } }
        inner = '<div class="md-body">' + window.marked(md) + "</div>";
      }
      body.innerHTML = '<p class="np-srcmeta">' + esc(a.source_path) + " · " + label + '</p>' + inner;
    }
  }
  // Narrow a section/body to the item that starts at the line containing `focus`
  // (verbatim substring). For list items: run until the next sibling item at the
  // same-or-lower indent, a heading, or end; for paragraphs: until a blank line.
  function focusSlice(bodyText, focus) {
    var lines = bodyText.split("\n");
    var fenced = fenceMap(lines);
    var idx = -1;
    for (var i = 0; i < lines.length; i++) if (lines[i].indexOf(focus) !== -1) { idx = i; break; }
    if (idx === -1) return null;
    // focus on a (template) heading line → slice until the next same-or-higher
    // heading, fenced or not, so a whole template sub-block is shown.
    var fh = /^(#{1,6})\s/.exec(lines[idx].trim());
    if (fh) {
      var fend = lines.length;
      for (var q = idx + 1; q < lines.length; q++) {
        var qm = /^(#{1,6})\s/.exec(lines[q].trim());
        if (qm && qm[1].length <= fh[1].length) { fend = q; break; }
      }
      return lines.slice(idx, fend).join("\n");
    }
    var item = /^(\s*)(\d+[.)]|[-*])\s/.exec(lines[idx]);
    var end = lines.length;
    for (var j = idx + 1; j < lines.length; j++) {
      var t = lines[j];
      if (!fenced[j] && /^#{1,6}\s/.test(t.trim())) { end = j; break; }
      if (item) {
        var sib = /^(\s*)(\d+[.)]|[-*])\s/.exec(t);
        if (sib && sib[1].length <= item[1].length) { end = j; break; }
        if (!t.trim() && j + 1 < lines.length && !/^\s/.test(lines[j + 1] || "") && !/^(\d+[.)]|[-*])\s/.test((lines[j + 1] || "").trim())) { end = j; break; }
      } else if (!t.trim()) { end = j; break; }
    }
    return lines.slice(idx, end).join("\n");
  }
  // Code variant: focused, line-numbered excerpt bounded by the next blank line.
  function codeFocusExcerpt(text, a, focus) {
    var sliced = a.embedded && a.line_start;
    var lines = sliced ? text.split("\n").slice(a.line_start - 1, a.line_end) : text.split("\n");
    var start = sliced ? a.line_start : 1;
    var idx = -1;
    for (var i = 0; i < lines.length; i++) if (lines[i].indexOf(focus) !== -1) { idx = i; break; }
    if (idx === -1) return null;
    var end = lines.length;
    for (var j = idx + 1; j < lines.length; j++) if (!lines[j].trim()) { end = j; break; }
    return '<pre class="excerpt">' + lines.slice(idx, end).map(function (ln, k) {
      return '<span class="ln">' + (start + idx + k) + "</span>" + esc(ln);
    }).join("\n") + "</pre>";
  }
  // Non-markdown sources are rendered as pretty-printed code, never as markdown.
  function isCodeSource(a) { return !/\.md$/.test(a.source_path || ""); }
  function codeExcerpt(text, a) {
    var sliced = a.embedded && a.line_start;
    var lines = sliced ? text.split("\n").slice(a.line_start - 1, a.line_end) : text.split("\n");
    var start = sliced ? a.line_start : 1;
    return '<pre class="excerpt">' + lines.map(function (ln, i) {
      return '<span class="ln">' + (start + i) + "</span>" + esc(ln);
    }).join("\n") + "</pre>";
  }
  // Resolve the markdown body of an artifact's source (template literal / md / embedded slice).
  function sourceMarkdown(text, a) {
    if (a.embedded && a.line_start) return text.split("\n").slice(a.line_start - 1, a.line_end).join("\n");
    if (/\.md$/.test(a.source_path)) return text;
    return extractTemplateBody(text);
  }
  // Slice a single section (by heading) out of an artifact's body, verbatim.
  // Fence-aware: `#` lines inside ``` fenced blocks (output templates) are NOT
  // headings — they must neither match an anchor nor terminate a section.
  function fenceMap(lines) {
    var inFence = false, map = new Array(lines.length);
    for (var i = 0; i < lines.length; i++) {
      if (/^\s*(```|~~~)/.test(lines[i])) { inFence = !inFence; map[i] = true; continue; }
      map[i] = inFence;
    }
    return map;
  }
  function extractSection(text, a, heading) {
    var md = sourceMarkdown(text, a);
    if (!heading) return null;
    var lines = md.split("\n");
    var fenced = fenceMap(lines);
    var esc2 = heading.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    var hre = new RegExp("^(#{1,6})\\s+" + esc2 + "\\s*$");
    var start = -1, level = 0;
    for (var i = 0; i < lines.length; i++) {
      if (fenced[i]) continue;
      var m = hre.exec(lines[i].trim());
      if (m) { start = i; level = m[1].length; break; }
    }
    if (start === -1) {
      // fuzzy: match heading text ignoring numbering/weight
      var norm = heading.toLowerCase().replace(/\s*\(weight:[^)]*\)/, "").replace(/^\d+[.)]\s*/, "").replace(/^phase\s*\d+:?\s*/, "").trim();
      for (var j = 0; j < lines.length; j++) {
        if (fenced[j]) continue;
        var hm = /^(#{1,6})\s+(.*)$/.exec(lines[j].trim());
        if (hm && hm[2].toLowerCase().replace(/\s*\(weight:[^)]*\)/, "").replace(/^\d+[.)]\s*/, "").replace(/^phase\s*\d+:?\s*/, "").trim() === norm) { start = j; level = hm[1].length; break; }
      }
    }
    if (start === -1) return null;
    var end = lines.length;
    for (var k = start + 1; k < lines.length; k++) {
      if (fenced[k]) continue;
      var hm2 = /^(#{1,6})\s+/.exec(lines[k].trim());
      if (hm2 && hm2[1].length <= level) { end = k; break; }
    }
    return { body: lines.slice(start, end).join("\n"), lines: (start + 1) + "–" + end };
  }

  function pill(k, v, accent) {
    return '<span class="pill' + (accent ? " accent" : "") + '">' + (k ? "<span>" + esc(k) + "</span> <b>" + esc(String(v)) + "</b>" : "<b>" + esc(String(v)) + "</b>") + "</span>";
  }
  function block(title, inner) { return '<section class="block"><h2>' + title + "</h2>" + inner + "</section>"; }
  function pres(present) { return ' <span class="inferred">' + (present ? "present" : "inferred") + "</span>"; }
  function ioTable(rows) {
    var html = '<table class="io"><thead><tr><th>Name</th><th>Type</th><th>Description</th></tr></thead><tbody>';
    rows.forEach(function (r) {
      html += "<tr><td><code>" + esc(r.name) + "</code>" + (r.required ? "" : ' <span class="note">optional</span>') +
        "</td><td>" + esc(r.type || "") + "</td><td>" + esc(r.desc || "") + "</td></tr>";
    });
    return html + "</tbody></table>";
  }
  function refLink(r) {
    if (typeof r === "string") return "<li>" + esc(r) + "</li>";
    var href = r.path ? (/^https?:/.test(r.path) ? r.path : ROOT + r.path) : (r.href || "#");
    var target = /^https?:/.test(href) || /^\.\.\//.test(href) ? ' target="_blank" rel="noopener"' : "";
    return '<li><a href="' + esc(href) + '"' + target + ">" + esc(r.label || r.path || r.href) + "</a>" +
      (r.note ? ' — <span class="note">' + esc(r.note) + "</span>" : "") + "</li>";
  }

  // ───────────────────────────── lazy source ─────────────────────────────
  function loadSource(a) {
    var body = document.getElementById("src-body");
    fetch(ROOT + a.source_path, { cache: "no-cache" })
      .then(function (r) { if (!r.ok) throw new Error(r.status + ""); return r.text(); })
      .then(function (text) {
        if (/\.md$/.test(a.source_path)) {
          body.innerHTML = '<div class="md-body">' + window.marked(text) + "</div>";
        } else {
          // code source (python / yaml / ts) — pretty-print the excerpt with
          // line numbers; codeExcerpt slices embedded line ranges itself.
          body.innerHTML = codeExcerpt(text, a);
        }
      })
      .catch(function (e) { body.innerHTML = '<div class="errbox">Could not load source (' + esc(e.message) + ").</div>"; });
  }
  function extractTemplateBody(text) {
    var m = /export const \w+\s*=\s*`/.exec(text);
    if (!m) return text;
    var start = text.indexOf("`", m.index + m[0].length - 1);
    var i = start + 1, out = "";
    while (i < text.length) {
      var ch = text[i];
      if (ch === "\\") { out += text[i + 1]; i += 2; continue; }
      if (ch === "`") break;
      out += ch; i++;
    }
    // un-escape the doubled \` and \${ used in TS template literals
    return out.replace(/\\`/g, "`").replace(/\\\$\{/g, "${");
  }

  // ───────────────────────── shape-graph fallback ─────────────────────────
  // Build a faithful diagram when no curated graph exists. Steps come from REAL
  // section headings; if there are none we fall back to input→model→output.
  var STEP_RE = /^(phase\s*\d|step\s*\d|\d+[.)]\s|intake|parallel|analysis|debate|synthesis|deliver|verification|review|decomposition|workstream|execution)/i;

  function shapeGraph(a, cur) {
    var nodes = [];
    var start = { id: "start", type: "start", label: "Invoke " + a.title };
    if (a.model) start.desc = "model: " + a.model + (a.maxTurns ? " · ≤" + a.maxTurns + " turns" : "");
    nodes.push(start);

    var steps = (a.headings || []).filter(function (h) { return h.level <= 3 && STEP_RE.test(h.text); });
    // de-dup & cap
    var seen = {}, picked = [];
    steps.forEach(function (h) { var k = h.text.toLowerCase(); if (!seen[k]) { seen[k] = 1; picked.push(h); } });
    picked = picked.slice(0, 8);

    if (picked.length >= 2) {
      var notes = (window.EXPLORER_NOTES && window.EXPLORER_NOTES[a.id]) || {};
      picked.forEach(function (h, i) {
        var node = { id: "s" + i, type: "step", num: i + 1, label: cleanHead(h.text), srcHeading: h.text };
        var note = notes[h.text] || notes[node.label];
        if (note) node.note = note;
        nodes.push(node);
      });
      nodes.push(outputNode(a));
      var g = { nodes: nodes, _shape: "headings" };
      return g;
    }

    // no process — input/model/output shape
    var ioNotes = (window.EXPLORER_NOTES && window.EXPLORER_NOTES[a.id]) || {};
    var io = [];
    io.push(start);
    var model = { id: "model", type: "decision", label: a.model ? "Model · " + a.model : "Language model", desc: a.maxTurns ? "≤ " + a.maxTurns + " turns" : (a.kind === "prompt-template" ? "fills template variables" : "single completion") };
    if (ioNotes.model) model.note = ioNotes.model;
    io.push(model);
    io.push(outputNode(a));
    return { nodes: io, _shape: "io" };
  }
  function outputNode(a) {
    var oh = (a.headings || []).filter(function (h) { return /output|deliver|format/i.test(h.text); })[0];
    if (a.outputFormat) return { id: "out", type: "output", label: "Structured output", desc: a.outputFormat + " schema", srcHeading: oh ? oh.text : undefined };
    return { id: "out", type: "output", label: oh ? cleanHead(oh.text) : "Output", desc: oh ? "" : "free-form response", srcHeading: oh ? oh.text : undefined };
  }
  function cleanHead(t) { return t.replace(/\s*\(weight:[^)]*\)/i, "").replace(/^\d+[.)]\s*/, "").replace(/^phase\s*\d+:?\s*/i, "").trim(); }

  // ───────────────────────── SVG diagram generator ─────────────────────────
  function buildDiagram(graph) {
    var nodes = graph.nodes || [];
    var W = 360, INNER = W - 28, PADX = 14;
    var GAP = 34, TOP = 18;
    var STOPW = 150, STOP_GUTTER = 46;
    var charLbl = 7.3, charDesc = 5.8, charChip = 5.6;

    // any node with a stop branch needs right gutter for the stop terminal
    var hasStop = nodes.some(function (n) { return n.stop; });
    var hasArc = nodes.some(function (n) { return n.loopTo || n.skipTo; });
    var leftPad = hasArc ? 40 : 16;
    var spineX = leftPad + W / 2;

    // ── measure & place vertically ──
    var y = TOP, idIndex = {};
    nodes.forEach(function (n, i) { idIndex[n.id] = i; });
    nodes.forEach(function (n) {
      n._lbl = wrap(n.label || "", INNER, charLbl);
      n._desc = n.desc ? wrap(n.desc, INNER, charDesc) : [];
      var chipsH = 0;
      if (n.chips && n.chips.length) {
        n._chipRows = packChips(n.chips, INNER, charChip);
        chipsH = n._chipRows.length * 20 + 6;
      }
      var tagH = n.tag ? 20 : 0;
      var h = 14 /*top*/ + n._lbl.length * 17 + (n._desc.length ? 4 + n._desc.length * 14 : 0) + chipsH + tagH + 12 /*bottom*/;
      n._h = Math.max(46, h);
      n._y = y;
      n._cx = spineX;
      y += n._h + GAP;
    });
    var contentH = Math.max(y - GAP + TOP, TOP + 60);

    var rightExtent = spineX + W / 2 + (hasStop ? STOP_GUTTER + STOPW : 16);
    var totalW = Math.max(rightExtent, spineX + W / 2 + 16);
    var totalH = contentH;

    var svg = [];
    svg.push('<svg viewBox="0 0 ' + totalW + " " + totalH + '" width="' + totalW + '" preserveAspectRatio="xMinYMin meet" role="img" aria-label="workflow diagram">');
    svg.push(defs());

    // ── spine edges (sequential step/start/output nodes) ──
    var spine = nodes.filter(function (n) { return n.type !== "_stopterm"; });
    for (var k = 0; k < spine.length - 1; k++) {
      var aN = spine[k], bN = spine[k + 1];
      var y1 = aN._y + aN._h, y2 = bN._y;
      svg.push(line(aN._cx, y1, bN._cx, y2, "edge", true));
    }

    // ── stop terminals + arcs ──
    nodes.forEach(function (n) {
      if (n.stop) {
        var sx = spineX + W / 2 + STOP_GUTTER;
        var sy = n._y + n._h / 2;
        var sh = 40, sw = STOPW;
        svg.push('<path class="edge-stop" marker-end="url(#arrow-stop)" d="M' + (n._cx + W / 2) + " " + sy + " H" + (sx) + '"/>');
        if (n.stop) svg.push('<text class="edge-lbl" x="' + (n._cx + W / 2 + 6) + '" y="' + (sy - 5) + '">' + esc(short(n.stop, 22)) + "</text>");
        svg.push(roundRect(sx, sy - sh / 2, sw, sh, "n-stop"));
        svg.push('<text class="lbl" x="' + (sx + sw / 2) + '" y="' + (sy + 4) + '" text-anchor="middle">STOP / route out</text>');
      }
    });

    // ── loop / skip arcs (drawn in left gutter) ──
    nodes.forEach(function (n) {
      var arc = n.loopTo || n.skipTo;
      if (!arc) return;
      var target = nodes[idIndex[arc.id]];
      if (!target) return;
      var fromY = n._y + n._h / 2, toY = target._y + target._h / 2;
      var x = n._cx - W / 2;
      var bow = leftPad - 8;
      var midX = Math.max(8, x - 26);
      var d = "M" + x + " " + fromY + " C" + midX + " " + fromY + " " + midX + " " + toY + " " + (target._cx - W / 2) + " " + toY;
      svg.push('<path class="edge-loop" marker-end="url(#arrow-loop)" d="' + d + '"/>');
      var lblY = (fromY + toY) / 2;
      svg.push('<text class="edge-lbl" x="' + (midX - 2) + '" y="' + lblY + '" text-anchor="end" transform="rotate(-90 ' + (midX - 2) + " " + lblY + ')">' + esc(short(arc.when || (n.loopTo ? "loop" : "skip"), 18)) + "</text>");
    });

    // ── nodes (each wrapped in a clickable group → opens the section panel) ──
    nodes.forEach(function (n) {
      if (n.type === "_stopterm") return;
      var cls = "n-" + (({ start: "start", step: "step", decision: "decision", output: "output", stop: "stop" })[n.type] || "step");
      var x = n._cx - W / 2;
      svg.push('<g class="dnode" data-node="' + esc(n.id) + '" tabindex="0" role="button" aria-label="' +
        esc((n.num != null ? n.num + ". " : "") + (n.label || "step") + " — open details") + '"><title>Click for step details &amp; source</title>');
      svg.push(roundRect(x, n._y, W, n._h, cls));
      // small affordance: a "+" disc at the node's top-right corner
      svg.push('<circle class="dnode-dot" cx="' + (x + W - 15) + '" cy="' + (n._y + 15) + '" r="7"/>');
      svg.push('<text class="dnode-plus" x="' + (x + W - 15) + '" y="' + (n._y + 19) + '" text-anchor="middle">+</text>');
      var ty = n._y + 22;
      if (n.num != null) svg.push('<text class="num" x="' + (x + PADX) + '" y="' + ty + '">' + n.num + ".</text>");
      var lblX = x + PADX + (n.num != null ? 20 : 0);
      n._lbl.forEach(function (ln, i) { svg.push('<text class="lbl" x="' + lblX + '" y="' + (ty + i * 17) + '">' + esc(ln) + "</text>"); });
      var dy = ty + n._lbl.length * 17;
      n._desc.forEach(function (ln, i) { svg.push('<text class="desc" x="' + (x + PADX) + '" y="' + (dy + 4 + i * 14) + '">' + esc(ln) + "</text>"); });
      var cy = dy + (n._desc.length ? n._desc.length * 14 + 8 : 6);
      // chips
      if (n._chipRows) {
        n._chipRows.forEach(function (row, ri) {
          var cx = x + PADX;
          row.forEach(function (ch) {
            var w = ch.length * charChip + 14;
            svg.push('<rect class="chip" x="' + cx + '" y="' + (cy + ri * 20) + '" width="' + w + '" height="15" rx="7"/>');
            svg.push('<text class="chip-txt" x="' + (cx + w / 2) + '" y="' + (cy + ri * 20 + 11) + '" text-anchor="middle">' + esc(ch) + "</text>");
            cx += w + 5;
          });
        });
        cy += n._chipRows.length * 20;
      }
      // tag pill
      if (n.tag) {
        var w2 = n.tag.length * 5.6 + 18;
        svg.push('<rect class="tag-pill" x="' + (x + PADX) + '" y="' + cy + '" width="' + w2 + '" height="15" rx="7"/>');
        svg.push('<text class="tag-txt" x="' + (x + PADX + w2 / 2) + '" y="' + (cy + 11) + '" text-anchor="middle">⚑ ' + esc(n.tag) + "</text>");
      }
      svg.push("</g>");
    });

    svg.push("</svg>");
    return svg.join("");
  }

  function diagramLegend(graph) {
    var used = {};
    (graph.nodes || []).forEach(function (n) { used[n.type] = 1; if (n.stop) used.stop = 1; if (n.loopTo) used.loop = 1; if (n.skipTo) used.skip = 1; if (n.tag) used.tag = 1; });
    var items = [];
    if (used.start) items.push(leg("n-start", "start"));
    if (used.step) items.push(leg("n-step", "step"));
    if (used.decision) items.push(leg("n-decision", "decision"));
    if (used.output) items.push(leg("n-output", "output"));
    if (used.stop) items.push(leg("n-stop", "stop / route-out"));
    if (used.tag) items.push('<span><b style="color:var(--node-decision-stroke)">⚑</b> conditional</span>');
    if (used.loop) items.push('<span><b style="color:var(--edge-loop)">⤺</b> loop-back</span>');
    if (used.skip) items.push('<span><b style="color:var(--edge-loop)">⤳</b> skip-ahead</span>');
    return '<div class="diagram-legend">' + items.join("") + "</div>";
  }
  function leg(cls, label) {
    var map = { "n-start": ["--node-start", "--node-start-stroke"], "n-step": ["--node-step", "--node-step-stroke"],
      "n-decision": ["--node-decision", "--node-decision-stroke"], "n-output": ["--node-output", "--node-output-stroke"],
      "n-stop": ["--node-stop", "--node-stop-stroke"] };
    var c = map[cls];
    return '<span><i style="background:var(' + c[0] + ');border-color:var(' + c[1] + ')"></i>' + esc(label) + "</span>";
  }

  // svg helpers
  function defs() {
    return '<defs>' +
      marker("arrow", "var(--edge)") +
      marker("arrow-loop", "var(--edge-loop)") +
      marker("arrow-stop", "var(--node-stop-stroke)") +
      "</defs>";
  }
  function marker(id, color) {
    return '<marker id="' + id + '" markerWidth="9" markerHeight="9" refX="7" refY="4" orient="auto"><path d="M0 0 L8 4 L0 8 z" fill="' + color + '"/></marker>';
  }
  function roundRect(x, y, w, h, cls) {
    return '<rect class="node-box ' + cls + '" x="' + r(x) + '" y="' + r(y) + '" width="' + r(w) + '" height="' + r(h) + '" rx="10" ry="10"/>';
  }
  function line(x1, y1, x2, y2, cls, arrow) {
    var mk = arrow ? ' marker-end="url(#arrow)"' : "";
    if (x1 === x2) return '<path class="' + cls + '"' + mk + ' d="M' + r(x1) + " " + r(y1) + " V" + r(y2) + '"/>';
    return '<path class="' + cls + '"' + mk + ' d="M' + r(x1) + " " + r(y1) + " C" + r(x1) + " " + r((y1 + y2) / 2) + " " + r(x2) + " " + r((y1 + y2) / 2) + " " + r(x2) + " " + r(y2) + '"/>';
  }
  function r(n) { return Math.round(n * 100) / 100; }

  // text wrapping by approximate width
  function wrap(text, maxW, charW) {
    text = String(text);
    var words = text.split(/\s+/), lines = [], cur = "";
    var max = Math.max(4, Math.floor(maxW / charW));
    words.forEach(function (w) {
      if (w.length > max) { // hard-break very long tokens
        if (cur) { lines.push(cur); cur = ""; }
        while (w.length > max) { lines.push(w.slice(0, max - 1) + "-"); w = w.slice(max - 1); }
        cur = w; return;
      }
      var t = cur ? cur + " " + w : w;
      if (t.length > max) { lines.push(cur); cur = w; } else cur = t;
    });
    if (cur) lines.push(cur);
    return lines.length ? lines.slice(0, 3) : [""];
  }
  function packChips(chips, maxW, charW) {
    var rows = [], cur = [], width = 0;
    chips.forEach(function (c) {
      c = short(c, 24);
      var w = c.length * charW + 19;
      if (width + w > maxW && cur.length) { rows.push(cur); cur = []; width = 0; }
      cur.push(c); width += w;
    });
    if (cur.length) rows.push(cur);
    return rows.slice(0, 4);
  }
  function short(s, n) { s = String(s); return s.length > n ? s.slice(0, n - 1) + "…" : s; }

  // misc
  function setContent(html) { document.querySelector(".content").innerHTML = html; }
  function esc(s) {
    return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  // expose for headless structural verification (Phase 4)
  window.__EXPLORER__ = {
    buildDiagram: buildDiagram, shapeGraph: shapeGraph, wrap: wrap, packChips: packChips,
    renderDetail: renderDetail, renderHome: renderHome, buildAssessment: buildAssessment,
    extractSection: extractSection, sourceMarkdown: sourceMarkdown, deriveSignals: deriveSignals,
    sectionLede: sectionLede, nodeMinimalSummary: nodeMinimalSummary, focusSlice: focusSlice,
    _setState: function (m, byId) { state.manifest = m; state.byId = byId; }
  };

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
