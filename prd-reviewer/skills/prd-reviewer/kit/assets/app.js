/* PRD Reviewer — prd-reviewer plugin (ClankerSkills)
 * Static, dependency-light Markdown browser scoped to ONE PRD/design folder plus
 * the source it references, with a quiet review/commenting layer.
 * - Manifest (manifest.json) lists files; bodies are fetched lazily over HTTP.
 * - Comments persist in localStorage. The panel stays closed until asked for.
 *   Select text → right-click → "Comment"; commented passages get an inline 💬
 *   marker you can click to open that comment. Heading markers are hover-only.
 * - Export / import comments as JSON, or copy as Markdown for a PR/issue.
 * - ```mermaid fences render as diagrams when mermaid.min.js is present.
 *
 * Everything PRD-specific lives in window.EXPLORER_CONFIG (set in index.html):
 * brand, tagline, intro, repoRoot, outputDir, storageNamespace, commenting,
 * keyDocs[], analysisPages[]. The engine itself is copied verbatim.
 */
(function () {
  "use strict";

  // ---------------------------------------------------------------------------
  // Config & state
  // ---------------------------------------------------------------------------
  var CONFIG = (window.EXPLORER_CONFIG || {});
  var REPO_ROOT = CONFIG.repoRoot || "../../"; // index.html lives at <outputDir>/
  var OUTPUT_DIR = CONFIG.outputDir || "docs/repository-explorer";
  var COMMENTING = CONFIG.commenting !== false; // on unless explicitly disabled
  var KEY_DOCS = CONFIG.keyDocs || []; // curated "Start here" paths
  var ANALYSIS_PAGES = CONFIG.analysisPages || []; // [{href,title,badge,sub}]
  var NS = CONFIG.storageNamespace || "repoexp";

  // Theme + reviewer name are global prefs (shared across repos); comments and
  // tree-collapse state are namespaced per repo so two explorers don't collide.
  var LS_COMMENTS = NS + "-comments-v1";
  var LS_COLLAPSED = NS + "-collapsed";
  var LS_AUTHOR = "repoexp-author";
  var LS_THEME = "repoexp-theme";

  var state = {
    manifest: null,
    byPath: {},
    current: null, // current file path
    comments: loadComments(),
    pending: null, // { anchor, anchorText, quote }
  };

  var el = {
    tree: document.getElementById("tree"),
    search: document.getElementById("search"),
    doc: document.getElementById("doc"),
    crumbs: document.getElementById("crumbs"),
    comments: document.getElementById("comments"),
    commentsList: document.getElementById("comments-list"),
    commentsMeta: document.getElementById("comments-meta"),
    commentForm: document.getElementById("comment-form"),
    commentBody: document.getElementById("comment-body"),
    commentQuote: document.getElementById("comment-quote"),
    reviewCount: document.getElementById("review-count"),
    selectionBtn: document.getElementById("selection-comment"),
    reviewMenu: document.getElementById("review-menu"),
    importFile: document.getElementById("import-file"),
    toast: document.getElementById("toast"),
    sidebar: document.getElementById("sidebar"),
  };

  // ---------------------------------------------------------------------------
  // Utilities
  // ---------------------------------------------------------------------------
  function loadComments() {
    try {
      return JSON.parse(localStorage.getItem(LS_COMMENTS) || "[]");
    } catch (e) {
      return [];
    }
  }
  function saveComments() {
    localStorage.setItem(LS_COMMENTS, JSON.stringify(state.comments));
    renderReviewCount();
  }
  function uid() {
    return Date.now().toString(36) + Math.random().toString(36).slice(2, 7);
  }
  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function slugify(s) {
    return String(s)
      .toLowerCase()
      .replace(/[^\w\s-]/g, "")
      .trim()
      .replace(/\s+/g, "-")
      .slice(0, 80) || "section";
  }
  function fmtBytes(n) {
    if (n < 1024) return n + " B";
    if (n < 1024 * 1024) return (n / 1024).toFixed(0) + " KiB";
    return (n / 1024 / 1024).toFixed(1) + " MiB";
  }
  function fmtTime(ts) {
    var d = new Date(ts);
    return d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
  }
  function toast(msg) {
    el.toast.textContent = msg;
    el.toast.hidden = false;
    clearTimeout(toast._t);
    toast._t = setTimeout(function () {
      el.toast.hidden = true;
    }, 2200);
  }
  function getAuthor(promptIfMissing) {
    var a = localStorage.getItem(LS_AUTHOR);
    if (!a && promptIfMissing) {
      a = (prompt("Your name (shown on review comments):", "") || "").trim();
      if (a) localStorage.setItem(LS_AUTHOR, a);
    }
    return a || "Anonymous";
  }

  // Resolve a relative link href against the directory of the current file.
  function resolvePath(baseDir, href) {
    if (/^[a-z]+:/i.test(href) || href.startsWith("//") || href.startsWith("#")) return null;
    var hash = "";
    var hi = href.indexOf("#");
    if (hi >= 0) {
      hash = href.slice(hi);
      href = href.slice(0, hi);
    }
    if (!href) return null;
    var parts = (baseDir ? baseDir.split("/") : []).concat(href.split("/"));
    var out = [];
    for (var i = 0; i < parts.length; i++) {
      var p = parts[i];
      if (p === "" || p === ".") continue;
      if (p === "..") out.pop();
      else out.push(p);
    }
    return { path: out.join("/"), hash: hash };
  }

  // ---------------------------------------------------------------------------
  // Branding (single source of truth = EXPLORER_CONFIG)
  // ---------------------------------------------------------------------------
  function applyBranding() {
    var brand = CONFIG.brand || "Repository";
    var tagline = CONFIG.tagline || "Repository Explorer";
    var mark = CONFIG.brandMark || brand.replace(/[^A-Za-z0-9]/g, "").slice(0, 2).toUpperCase() || "RX";
    setText("brand-mark", mark);
    setText("brand-name", brand);
    setText("brand-tagline", tagline);
    document.title = brand + " · " + tagline;
    if (CONFIG.accent) document.documentElement.style.setProperty("--accent", CONFIG.accent);
  }
  function setText(id, text) {
    var n = document.getElementById(id);
    if (n) n.textContent = text;
  }

  // ---------------------------------------------------------------------------
  // Boot
  // ---------------------------------------------------------------------------
  function init() {
    document.documentElement.setAttribute(
      "data-theme",
      localStorage.getItem(LS_THEME) || "light"
    );
    applyBranding();
    wireChrome();
    fetch("manifest.json", { cache: "no-cache" })
      .then(function (r) {
        if (!r.ok) throw new Error("manifest " + r.status);
        return r.json();
      })
      .then(function (m) {
        state.manifest = m;
        m.files.forEach(function (f) {
          state.byPath[f.path] = f;
        });
        buildTree();
        renderReviewCount();
        route();
      })
      .catch(function (e) {
        el.doc.innerHTML =
          '<div class="doc-inner"><div class="banner">Could not load <code>manifest.json</code> (' +
          esc(e.message) +
          "). Run <code>python3 " + OUTPUT_DIR + "/build_manifest.py</code> and serve over HTTP (see README).</div></div>";
      });
    window.addEventListener("hashchange", route);
  }

  // ---------------------------------------------------------------------------
  // File tree
  // ---------------------------------------------------------------------------
  function getCollapsed() {
    try {
      return JSON.parse(localStorage.getItem(LS_COLLAPSED) || "{}");
    } catch (e) {
      return {};
    }
  }
  function setCollapsed(map) {
    localStorage.setItem(LS_COLLAPSED, JSON.stringify(map));
  }

  function buildTree(filter) {
    var collapsed = getCollapsed();
    var root = { dirs: {}, files: [] };
    var f = (filter || "").toLowerCase();

    state.manifest.files.forEach(function (file) {
      if (f) {
        var hay = (file.path + " " + file.title).toLowerCase();
        if (hay.indexOf(f) === -1) return;
      }
      var parts = file.path.split("/");
      var node = root;
      for (var i = 0; i < parts.length - 1; i++) {
        var d = parts[i];
        if (!node.dirs[d]) node.dirs[d] = { dirs: {}, files: [], _path: parts.slice(0, i + 1).join("/") };
        node = node.dirs[d];
      }
      node.files.push(file);
    });

    el.tree.innerHTML = "";
    el.tree.appendChild(renderTreeNode(root, "", collapsed, !!f));
    highlightActive();
  }

  function commentCountFor(path) {
    var n = 0;
    for (var i = 0; i < state.comments.length; i++) if (state.comments[i].path === path) n++;
    return n;
  }

  function renderTreeNode(node, dirPath, collapsed, forceOpen) {
    var frag = document.createDocumentFragment();

    // root-level files first (e.g. README, CLAUDE)
    if (!dirPath) {
      node.files.forEach(function (file) {
        frag.appendChild(renderTreeFile(file));
      });
    }

    Object.keys(node.dirs)
      .sort()
      .forEach(function (name) {
        var child = node.dirs[name];
        var path = child._path;
        var wrap = document.createElement("div");
        wrap.className = "tree-node";
        var isCollapsed = forceOpen ? false : collapsed[path];
        if (isCollapsed) wrap.classList.add("collapsed");

        var label = document.createElement("div");
        label.className = "tree-label";
        label.innerHTML =
          '<span class="twisty">▾</span>📁 <span>' +
          esc(name) +
          '</span><span class="tree-count">' +
          countFiles(child) +
          "</span>";
        label.addEventListener("click", function () {
          wrap.classList.toggle("collapsed");
          var c = getCollapsed();
          if (wrap.classList.contains("collapsed")) c[path] = 1;
          else delete c[path];
          setCollapsed(c);
        });
        wrap.appendChild(label);

        var children = document.createElement("div");
        children.className = "tree-children";
        children.appendChild(renderTreeNode(child, path, collapsed, forceOpen));
        // files in this dir
        child.files.forEach(function (file) {
          children.appendChild(renderTreeFile(file));
        });
        wrap.appendChild(children);
        frag.appendChild(wrap);
      });

    return frag;
  }

  function countFiles(node) {
    var n = node.files.length;
    Object.keys(node.dirs).forEach(function (k) {
      n += countFiles(node.dirs[k]);
    });
    return n;
  }

  function renderTreeFile(file) {
    var a = document.createElement("a");
    a.className = "tree-file";
    a.href = "#/" + file.path;
    a.dataset.path = file.path;
    var name = file.path.split("/").pop();
    var cc = commentCountFor(file.path);
    a.innerHTML =
      '<span class="doticon">' +
      (file.type === "markdown" ? "📄" : "⚙") +
      '</span><span class="fname">' +
      esc(name) +
      "</span>" +
      (cc ? '<span class="cbadge">' + cc + "</span>" : "");
    a.title = file.path;
    return a;
  }

  function highlightActive() {
    var nodes = el.tree.querySelectorAll(".tree-file");
    for (var i = 0; i < nodes.length; i++) {
      nodes[i].classList.toggle("active", nodes[i].dataset.path === state.current);
    }
  }

  // ---------------------------------------------------------------------------
  // Routing
  // ---------------------------------------------------------------------------
  function route() {
    var h = location.hash.replace(/^#/, "");
    if (!h || h === "home" || h === "/") {
      renderHome();
      return;
    }
    var path = h.replace(/^\//, "");
    var inHash = "";
    var hi = path.indexOf("#");
    if (hi >= 0) {
      inHash = path.slice(hi + 1);
      path = path.slice(0, hi);
    }
    if (state.byPath[path]) openFile(path, inHash);
    else renderHome();
  }

  function navigate(path, hash) {
    location.hash = "/" + path + (hash ? "#" + hash : "");
  }

  // ---------------------------------------------------------------------------
  // Home / overview
  // ---------------------------------------------------------------------------
  function renderHome() {
    state.current = null;
    highlightActive();
    el.crumbs.innerHTML = '<span class="cur">Overview</span>';
    el.comments.hidden = true;

    var m = state.manifest;
    var cats = {};
    m.files.forEach(function (f) {
      cats[f.category] = (cats[f.category] || 0) + 1;
    });

    var keyPaths = KEY_DOCS.filter(function (p) {
      return state.byPath[p];
    });
    if (!keyPaths.length) {
      // No curated list — auto-pick: README first, then other root-level docs.
      var roots = m.files.filter(function (f) {
        return f.path.indexOf("/") === -1 && f.type === "markdown";
      });
      roots.sort(function (a, b) {
        var ar = /^readme/i.test(a.path) ? 0 : 1;
        var br = /^readme/i.test(b.path) ? 0 : 1;
        return ar - br || b.size - a.size;
      });
      keyPaths = roots.slice(0, 8).map(function (f) {
        return f.path;
      });
    }
    var startCards = keyPaths
      .map(function (p) {
        var f = state.byPath[p];
        return (
          '<a class="card" href="#/' +
          f.path +
          '"><div class="card-title">' +
          esc(f.title) +
          '</div><div class="card-sum">' +
          esc(f.summary || f.path) +
          "</div></a>"
        );
      })
      .join("");

    var catOrder = Object.keys(cats).sort(function (a, b) {
      return cats[b] - cats[a];
    });
    var catCards = catOrder
      .map(function (c) {
        return (
          '<div class="cat-card" data-cat="' +
          esc(c) +
          '"><div class="cc-name">' +
          esc(c) +
          "<span>" +
          cats[c] +
          "</span></div></div>"
        );
      })
      .join("");

    var bannerHtml = location.protocol === "file:"
      ? '<div class="banner"><strong>Heads up:</strong> you opened this over <code>file://</code>. Document bodies are fetched over HTTP, so most browsers will block them here. Serve the repo instead — from the repo root run <code>python3 ' + OUTPUT_DIR + '/serve.py</code> (or <code>python3 -m http.server</code>, then open <code>/' + OUTPUT_DIR + '/</code>).</div>'
      : "";

    var featureCards = ANALYSIS_PAGES.map(function (p) {
      return (
        '<a class="feature-card" href="' + esc(p.href) + '">' +
        (p.badge ? '<div class="feature-badge">' + esc(p.badge) + "</div>" : "") +
        '<div class="feature-title">' + esc(p.title || p.href) + " →</div>" +
        (p.sub ? '<div class="feature-sub">' + esc(p.sub) + "</div>" : "") +
        "</a>"
      );
    }).join("");
    var featureRow = featureCards ? '<div class="feature-row">' + featureCards + "</div>" : "";

    var brand = CONFIG.brand || (m.repo || "Repository");
    var tagline = CONFIG.tagline || "Repository Explorer";
    var intro =
      CONFIG.intro ||
      "A read-and-review surface over this repository's documentation. Browse a file, then" +
        (COMMENTING ? " select text or a heading to leave a review comment." : " navigate the tree to explore.");

    var commentStat = COMMENTING
      ? '<div class="stat"><b>' + state.comments.length + "</b><span>review comments</span></div>"
      : "";

    el.doc.innerHTML =
      '<div class="home">' +
      bannerHtml +
      featureRow +
      '<div class="hero"><h1>' + esc(brand) + " · " + esc(tagline) + "</h1>" +
      "<p>" + esc(intro) + "</p>" +
      '<div class="stat-row">' +
      '<div class="stat"><b>' + m.fileCount + "</b><span>documents indexed</span></div>" +
      '<div class="stat"><b>' + fmtBytes(m.totalBytes) + "</b><span>total content</span></div>" +
      '<div class="stat"><b>' + catOrder.length + "</b><span>areas</span></div>" +
      commentStat +
      "</div></div>" +
      '<div class="section-title">Start here</div>' +
      '<div class="card-grid">' + startCards + "</div>" +
      '<div class="section-title">Browse by area</div>' +
      '<div class="cat-grid">' + catCards + "</div>" +
      "</div>";

    // category cards -> expand that area in the tree + filter
    var ccards = el.doc.querySelectorAll(".cat-card");
    for (var i = 0; i < ccards.length; i++) {
      ccards[i].addEventListener("click", function () {
        showCategory(this.dataset.cat);
      });
    }
    el.doc.scrollTop = 0;
  }

  function showCategory(cat) {
    // Render a simple list view of all files in a category.
    var files = state.manifest.files.filter(function (f) {
      return f.category === cat;
    });
    var cards = files
      .map(function (f) {
        return (
          '<a class="card" href="#/' +
          f.path +
          '"><div class="card-title"><span class="card-cat">' +
          esc(f.path.split("/").slice(0, -1).join("/") || ".") +
          "</span> " +
          esc(f.title) +
          '</div><div class="card-sum">' +
          esc(f.summary || "") +
          "</div></a>"
        );
      })
      .join("");
    el.crumbs.innerHTML =
      '<a href="#home" data-nav="home">Overview</a><span class="sep">/</span><span class="cur">' +
      esc(cat) +
      "</span>";
    el.comments.hidden = true;
    el.doc.innerHTML =
      '<div class="home"><div class="hero"><h1>' +
      esc(cat) +
      "</h1><p>" +
      files.length +
      ' document' + (files.length === 1 ? "" : "s") + ' in this area.</p></div><div class="card-grid">' +
      cards +
      "</div></div>";
    el.doc.scrollTop = 0;
  }

  // ---------------------------------------------------------------------------
  // File view
  // ---------------------------------------------------------------------------
  function openFile(path, inHash) {
    state.current = path;
    highlightActive();
    var file = state.byPath[path];
    renderCrumbs(path);
    el.doc.innerHTML = '<div class="doc-inner"><div class="loading">Loading…</div></div>';

    fetch(REPO_ROOT + path, { cache: "no-cache" })
      .then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.text();
      })
      .then(function (text) {
        renderMarkdown(path, file, text);
        if (inHash) {
          var target = document.getElementById(inHash);
          if (target) target.scrollIntoView();
        } else {
          el.doc.scrollTop = 0;
        }
      })
      .catch(function (e) {
        var hint =
          location.protocol === "file:"
            ? " You are on <code>file://</code> — serve over HTTP (see the Overview banner)."
            : "";
        el.doc.innerHTML =
          '<div class="doc-inner"><div class="banner">Could not load <code>' +
          esc(path) +
          "</code> (" +
          esc(e.message) +
          ")." +
          hint +
          "</div></div>";
      });
  }

  function renderCrumbs(path) {
    var parts = path.split("/");
    var html = '<a href="#home" data-nav="home">Overview</a>';
    parts.forEach(function (p, i) {
      html += '<span class="sep">/</span>';
      if (i === parts.length - 1) html += '<span class="cur">' + esc(p) + "</span>";
      else html += esc(p);
    });
    el.crumbs.innerHTML = html;
  }

  function renderMarkdown(path, file, text) {
    var baseDir = path.split("/").slice(0, -1).join("/");
    var html;

    if (file.type === "markdown") {
      marked.setOptions({ gfm: true, breaks: false, headerIds: false, mangle: false });
      html = marked.parse(text);
    } else {
      // Non-markdown (yaml etc): render as a single code block.
      html = "<pre><code>" + esc(text) + "</code></pre>";
    }

    var wrap = document.createElement("div");
    wrap.className = "doc-inner";
    wrap.innerHTML = html;

    enhanceHeadings(wrap);
    rewriteLinks(wrap, baseDir);
    renderMermaid(wrap); // replaces ```mermaid fences before code-block styling
    enhanceCodeBlocks(wrap);

    el.doc.innerHTML = "";
    el.doc.appendChild(wrap);

    // PRD-reviewer: the comments panel stays CLOSED until the reviewer asks for it
    // (the toggle, a marker click, or starting a comment). We only decorate the
    // document — inline highlights on commented passages + subtle heading markers.
    el.comments.hidden = true;
    if (COMMENTING) decorateComments(path);
  }

  // ---------------------------------------------------------------------------
  // Mermaid diagrams (rendered only if mermaid.min.js is present)
  // ---------------------------------------------------------------------------
  var _mmInit = false;
  var _mmCounter = 0;
  function ensureMermaidInit() {
    if (_mmInit || typeof mermaid === "undefined") return;
    var dark = document.documentElement.getAttribute("data-theme") === "dark";
    try {
      mermaid.initialize({
        startOnLoad: false,
        securityLevel: "strict", // never execute markup from browsed repos
        theme: dark ? "dark" : "default",
        flowchart: { useMaxWidth: true },
      });
      _mmInit = true;
    } catch (e) {
      /* mermaid present but failed to init — leave fences as code */
    }
  }

  function renderMermaid(wrap) {
    if (typeof mermaid === "undefined") return;
    var blocks = wrap.querySelectorAll("code.language-mermaid");
    if (!blocks.length) return;
    ensureMermaidInit();
    if (!_mmInit) return;
    for (var i = 0; i < blocks.length; i++) {
      (function (code) {
        var src = code.textContent;
        var pre = code.parentNode && code.parentNode.tagName === "PRE" ? code.parentNode : code;
        var fig = document.createElement("div");
        fig.className = "mermaid-fig";
        fig.innerHTML = '<div class="mermaid-loading">Rendering diagram…</div>';
        if (pre.parentNode) pre.parentNode.replaceChild(fig, pre);
        var id = "mmd-" + _mmCounter++;
        try {
          var out = mermaid.render(id, src);
          // mermaid v10+ returns a Promise; older returns a string.
          if (out && typeof out.then === "function") {
            out.then(function (r) { fig.innerHTML = r.svg; }).catch(function () { mermaidFail(fig, src); });
          } else if (typeof out === "string") {
            fig.innerHTML = out;
          } else {
            mermaidFail(fig, src);
          }
        } catch (e) {
          mermaidFail(fig, src);
        }
      })(blocks[i]);
    }
  }

  function mermaidFail(fig, src) {
    fig.className = "mermaid-fig mermaid-error";
    fig.innerHTML =
      '<div class="mermaid-error-msg">Diagram could not be rendered — showing source.</div>' +
      "<pre><code>" + esc(src) + "</code></pre>";
  }

  function enhanceHeadings(wrap) {
    var used = {};
    var hs = wrap.querySelectorAll("h1, h2, h3, h4");
    for (var i = 0; i < hs.length; i++) {
      var h = hs[i];
      var base = slugify(h.textContent);
      var id = base;
      var n = 1;
      while (used[id]) id = base + "-" + ++n;
      used[id] = true;
      h.id = id;

      var anchor = document.createElement("a");
      anchor.className = "anchor";
      anchor.href = "#/" + state.current + "#" + id;
      anchor.textContent = "#";
      h.appendChild(anchor);

      if (!COMMENTING) continue;
      var mark = document.createElement("span");
      mark.className = "cmark";
      mark.dataset.anchor = id;
      mark.dataset.anchorText = h.textContent.replace(/#$/, "").trim();
      mark.title = "Comment on this section";
      h.appendChild(mark);
      mark.addEventListener("click", function (ev) {
        ev.preventDefault();
        startComment({ anchor: this.dataset.anchor, anchorText: this.dataset.anchorText, quote: "" });
      });
    }
  }

  function rewriteLinks(wrap, baseDir) {
    var links = wrap.querySelectorAll("a[href]");
    for (var i = 0; i < links.length; i++) {
      var a = links[i];
      if (a.classList.contains("anchor")) continue;
      var href = a.getAttribute("href");
      if (href.startsWith("#")) continue; // in-page anchor; leave (handled by browser/relative)
      var res = resolvePath(baseDir, href);
      if (res && state.byPath[res.path]) {
        // Another indexed document — navigate inside the Explorer.
        a.setAttribute("href", "#/" + res.path + (res.hash || ""));
      } else if (res && res.path) {
        // A repo file we don't index (e.g. source code) — open the raw file
        // from the served repo root in a new tab.
        a.setAttribute("href", REPO_ROOT + res.path + (res.hash || ""));
        a.setAttribute("target", "_blank");
        a.setAttribute("rel", "noopener");
      } else if (/^[a-z]+:\/\//i.test(href)) {
        a.setAttribute("target", "_blank");
        a.setAttribute("rel", "noopener");
      }
    }
  }

  function enhanceCodeBlocks(wrap) {
    var pres = wrap.querySelectorAll("pre");
    for (var i = 0; i < pres.length; i++) {
      var pre = pres[i];
      var holder = document.createElement("div");
      holder.className = "codeblock-wrap";
      pre.parentNode.insertBefore(holder, pre);
      holder.appendChild(pre);
      var btn = document.createElement("button");
      btn.className = "copy-btn";
      btn.textContent = "Copy";
      (function (pre, btn) {
        btn.addEventListener("click", function () {
          copyText(pre.innerText);
          btn.textContent = "Copied";
          setTimeout(function () {
            btn.textContent = "Copy";
          }, 1200);
        });
      })(pre, btn);
      holder.appendChild(btn);
    }
  }

  function copyText(t) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(t).catch(function () {});
    } else {
      var ta = document.createElement("textarea");
      ta.value = t;
      document.body.appendChild(ta);
      ta.select();
      try {
        document.execCommand("copy");
      } catch (e) {}
      document.body.removeChild(ta);
    }
  }

  // ---------------------------------------------------------------------------
  // Comments / review
  // ---------------------------------------------------------------------------
  function commentsFor(path) {
    return state.comments
      .filter(function (c) {
        return c.path === path;
      })
      .sort(function (a, b) {
        return a.created - b.created;
      });
  }

  // Open the panel on demand (toggle / marker click). Optionally scroll to and
  // flash a specific comment card.
  function openComments(path, focusId) {
    el.comments.hidden = false;
    renderComments(path);
    refreshHeadingMarkers();
    if (focusId) {
      var card = el.commentsList.querySelector('.comment[data-id="' + cssEscape(focusId) + '"]');
      if (card) {
        card.scrollIntoView({ behavior: "smooth", block: "center" });
        card.classList.add("flash");
        setTimeout(function () { card.classList.remove("flash"); }, 1400);
      }
    }
  }

  // Decorate the rendered document without opening the panel: subtle heading
  // markers + inline highlights on every commented passage.
  function decorateComments(path) {
    refreshHeadingMarkers();
    clearHighlights();
    applyInlineHighlights(path);
  }

  function refreshHeadingMarkers() {
    var counts = {};
    commentsFor(state.current).forEach(function (c) {
      counts[c.anchor] = (counts[c.anchor] || 0) + 1;
    });
    var marks = el.doc.querySelectorAll(".cmark");
    for (var i = 0; i < marks.length; i++) {
      var a = marks[i].dataset.anchor;
      var n = counts[a] || 0;
      marks[i].textContent = n ? "💬 " + n : "💬";
      marks[i].classList.toggle("has-comments", n > 0);
    }
  }

  // --- Inline highlighting of commented selections ---------------------------
  // Each comment with a stored quote is re-located in the live document and
  // wrapped in <mark class="cmt-hl"> with a small 💬 marker the reviewer can click.
  function clearHighlights() {
    var marks = el.doc.querySelectorAll("mark.cmt-hl");
    for (var i = 0; i < marks.length; i++) {
      var m = marks[i];
      var icon = m.querySelector(".cmt-marker");
      if (icon) icon.remove();
      var parent = m.parentNode;
      while (m.firstChild) parent.insertBefore(m.firstChild, m);
      parent.removeChild(m);
      parent.normalize();
    }
  }

  function applyInlineHighlights(path) {
    commentsFor(path).forEach(function (c) {
      if (c.quote) highlightQuote(c);
    });
  }

  // Find the (first, not-yet-wrapped) occurrence of a comment's quote within a
  // single text node and wrap it. Quotes that span inline elements (e.g. inline
  // code) won't single-node-match — those simply stay un-highlighted but remain
  // listed in the panel. Truncated quotes (stored with a trailing …) match on
  // their prefix.
  function highlightQuote(c) {
    var quote = String(c.quote || "").replace(/[…]$/, "").trim();
    if (quote.length < 4) return;
    var walker = document.createTreeWalker(el.doc, NodeFilter.SHOW_TEXT, null);
    var node;
    while ((node = walker.nextNode())) {
      if (node.parentNode && node.parentNode.closest && node.parentNode.closest("mark.cmt-hl")) continue;
      var idx = node.nodeValue.indexOf(quote);
      if (idx >= 0) {
        wrapTextRange(node, idx, quote.length, c.id);
        return;
      }
    }
  }

  function wrapTextRange(textNode, start, len, id) {
    try {
      var range = document.createRange();
      range.setStart(textNode, start);
      range.setEnd(textNode, start + len);
      var mark = document.createElement("mark");
      mark.className = "cmt-hl";
      mark.dataset.commentId = id;
      range.surroundContents(mark);
      var icon = document.createElement("button");
      icon.type = "button";
      icon.className = "cmt-marker";
      icon.dataset.commentId = id;
      icon.title = "View comment";
      icon.textContent = "💬";
      mark.appendChild(icon);
    } catch (e) {
      /* range could not be surrounded (crosses element boundary) — skip */
    }
  }

  function renderComments(path) {
    var list = commentsFor(path);
    var file = state.byPath[path];
    el.commentsMeta.textContent =
      list.length + " comment" + (list.length === 1 ? "" : "s") + " · " + (file ? file.path : "");
    if (!list.length) {
      el.commentsList.innerHTML =
        '<div class="empty-note">No comments yet. Select text in the document, or use the button below, to start a review.</div>';
      return;
    }
    el.commentsList.innerHTML = list
      .map(function (c) {
        return (
          '<div class="comment' +
          (c.resolved ? " resolved" : "") +
          '" data-id="' +
          c.id +
          '">' +
          (c.anchor && c.anchor !== "doc"
            ? '<div class="comment-anchor" data-jump="' +
              esc(c.anchor) +
              '" title="Jump to section">§ ' +
              esc(c.anchorText || c.anchor) +
              "</div>"
            : "") +
          (c.quote ? '<div class="comment-blockquote">“' + esc(c.quote) + "”</div>" : "") +
          '<div class="comment-top"><span class="comment-author">' +
          esc(c.author) +
          '</span><span class="comment-time">' +
          fmtTime(c.created) +
          "</span></div>" +
          '<div class="comment-body">' +
          esc(c.body) +
          "</div>" +
          '<div class="comment-actions">' +
          '<button data-act="resolve">' +
          (c.resolved ? "Reopen" : "Resolve") +
          "</button>" +
          '<button data-act="edit">Edit</button>' +
          '<button data-act="delete" class="danger">Delete</button>' +
          "</div></div>"
        );
      })
      .join("");
  }

  function startComment(pending) {
    state.pending = pending;
    el.comments.hidden = false;
    el.commentForm.hidden = false;
    if (pending.quote) {
      el.commentQuote.hidden = false;
      el.commentQuote.textContent = "“" + pending.quote + "”";
    } else if (pending.anchorText) {
      el.commentQuote.hidden = false;
      el.commentQuote.textContent = "§ " + pending.anchorText;
    } else {
      el.commentQuote.hidden = true;
    }
    el.commentBody.value = "";
    el.commentBody.focus();
  }

  function submitComment(ev) {
    ev.preventDefault();
    var body = el.commentBody.value.trim();
    if (!body) return;
    var p = state.pending || { anchor: "doc", anchorText: "", quote: "" };
    state.comments.push({
      id: uid(),
      path: state.current,
      anchor: p.anchor || "doc",
      anchorText: p.anchorText || "",
      quote: p.quote || "",
      body: body,
      author: getAuthor(true),
      created: Date.now(),
      resolved: false,
    });
    saveComments();
    el.commentForm.hidden = true;
    state.pending = null;
    renderComments(state.current);
    decorateComments(state.current);
    updateTreeBadge(state.current);
  }

  function updateTreeBadge(path) {
    var node = el.tree.querySelector('.tree-file[data-path="' + cssEscape(path) + '"]');
    if (!node) return;
    var existing = node.querySelector(".cbadge");
    var n = commentCountFor(path);
    if (existing) existing.remove();
    if (n) {
      var b = document.createElement("span");
      b.className = "cbadge";
      b.textContent = n;
      node.appendChild(b);
    }
  }

  function cssEscape(s) {
    return s.replace(/["\\]/g, "\\$&");
  }

  function onCommentsClick(ev) {
    var jump = ev.target.closest("[data-jump]");
    if (jump) {
      var t = document.getElementById(jump.dataset.jump);
      if (t) t.scrollIntoView({ behavior: "smooth", block: "start" });
      return;
    }
    var btn = ev.target.closest("[data-act]");
    if (!btn) return;
    var card = ev.target.closest(".comment");
    var id = card && card.dataset.id;
    var c = state.comments.find(function (x) {
      return x.id === id;
    });
    if (!c) return;
    var act = btn.dataset.act;
    if (act === "resolve") {
      c.resolved = !c.resolved;
      saveComments();
      renderComments(state.current);
    } else if (act === "delete") {
      if (confirm("Delete this comment?")) {
        state.comments = state.comments.filter(function (x) {
          return x.id !== id;
        });
        saveComments();
        renderComments(state.current);
        decorateComments(state.current);
        updateTreeBadge(state.current);
      }
    } else if (act === "edit") {
      var nb = prompt("Edit comment:", c.body);
      if (nb !== null && nb.trim()) {
        c.body = nb.trim();
        c.edited = Date.now();
        saveComments();
        renderComments(state.current);
      }
    }
  }

  // Right-click within the document, over a non-empty selection, shows a small
  // floating "Comment" action at the cursor — instead of an always-present panel.
  // With no selection we let the browser's native context menu through.
  function onDocContextMenu(ev) {
    var sel = window.getSelection();
    if (!sel || sel.isCollapsed || !state.current) return;
    var text = sel.toString().trim();
    if (!text || !el.doc.contains(sel.anchorNode)) return;
    ev.preventDefault();
    var h = nearestHeading(sel.anchorNode);
    el.selectionBtn.hidden = false;
    el.selectionBtn.style.top = window.scrollY + ev.clientY + 8 + "px";
    el.selectionBtn.style.left = window.scrollX + ev.clientX + 2 + "px";
    el.selectionBtn._payload = {
      quote: text.length > 280 ? text.slice(0, 277) + "…" : text,
      anchor: h.anchor,
      anchorText: h.anchorText,
    };
  }

  function nearestHeading(node) {
    var anchor = { anchor: "doc", anchorText: "" };
    var node0 = node && node.nodeType === 3 ? node.parentNode : node;
    if (!node0) return anchor;
    var hs = el.doc.querySelectorAll("h1, h2, h3, h4");
    var best = null;
    for (var i = 0; i < hs.length; i++) {
      var pos = node0.compareDocumentPosition(hs[i]);
      // heading precedes the node
      if (pos & Node.DOCUMENT_POSITION_PRECEDING || hs[i] === node0 || hs[i].contains(node0)) {
        best = hs[i];
      } else {
        break;
      }
    }
    if (best) {
      anchor.anchor = best.id;
      anchor.anchorText = best.textContent.replace(/#$/, "").replace("💬", "").trim();
    }
    return anchor;
  }

  // ---------------------------------------------------------------------------
  // Export / import
  // ---------------------------------------------------------------------------
  function exportJson() {
    var data = {
      exported: new Date().toISOString(),
      repo: (state.manifest && state.manifest.repo) || CONFIG.brand || "repository",
      comments: state.comments,
    };
    download(NS + "-review-comments.json", JSON.stringify(data, null, 2), "application/json");
    toast("Exported " + state.comments.length + " comments");
  }

  function exportMarkdown() {
    if (!state.comments.length) {
      toast("No comments to export");
      return;
    }
    var byPath = {};
    state.comments.forEach(function (c) {
      (byPath[c.path] = byPath[c.path] || []).push(c);
    });
    var lines = ["# " + (CONFIG.brand || "Repository") + " — Review Comments", "", "_" + new Date().toLocaleString() + "_", ""];
    Object.keys(byPath)
      .sort()
      .forEach(function (p) {
        lines.push("## `" + p + "`", "");
        byPath[p]
          .sort(function (a, b) {
            return a.created - b.created;
          })
          .forEach(function (c) {
            var loc = c.anchor && c.anchor !== "doc" ? " · §" + (c.anchorText || c.anchor) : "";
            lines.push("- **" + c.author + "**" + loc + (c.resolved ? " _(resolved)_" : ""));
            if (c.quote) lines.push("  > " + c.quote);
            lines.push("  " + c.body.replace(/\n/g, "\n  "));
            lines.push("");
          });
      });
    var md = lines.join("\n");
    copyText(md);
    toast("Markdown copied to clipboard");
  }

  function download(name, content, type) {
    var blob = new Blob([content], { type: type });
    var url = URL.createObjectURL(blob);
    var a = document.createElement("a");
    a.href = url;
    a.download = name;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(function () {
      URL.revokeObjectURL(url);
    }, 1000);
  }

  function importJson(file) {
    var reader = new FileReader();
    reader.onload = function () {
      try {
        var data = JSON.parse(reader.result);
        var incoming = Array.isArray(data) ? data : data.comments;
        if (!Array.isArray(incoming)) throw new Error("no comments array");
        var existing = {};
        state.comments.forEach(function (c) {
          existing[c.id] = true;
        });
        var added = 0;
        incoming.forEach(function (c) {
          if (c && c.id && !existing[c.id]) {
            state.comments.push(c);
            added++;
          }
        });
        saveComments();
        if (state.current) {
          renderComments(state.current);
          decorateComments(state.current);
        }
        buildTree(el.search.value);
        toast("Imported " + added + " new comments");
      } catch (e) {
        toast("Import failed: " + e.message);
      }
    };
    reader.readAsText(file);
  }

  function renderReviewCount() {
    var n = state.comments.length;
    el.reviewCount.textContent = n + " comment" + (n === 1 ? "" : "s");
  }

  // ---------------------------------------------------------------------------
  // Chrome wiring
  // ---------------------------------------------------------------------------
  function wireChrome() {
    // theme
    document.getElementById("theme-toggle").addEventListener("click", function () {
      var cur = document.documentElement.getAttribute("data-theme");
      var next = cur === "dark" ? "light" : "dark";
      document.documentElement.setAttribute("data-theme", next);
      localStorage.setItem(LS_THEME, next);
    });

    // search
    var t;
    el.search.addEventListener("input", function () {
      clearTimeout(t);
      var v = el.search.value;
      t = setTimeout(function () {
        buildTree(v);
      }, 120);
    });

    // expand/collapse all
    el.tree.parentNode.querySelector('[data-action="expand-all"]').addEventListener("click", function () {
      setCollapsed({});
      buildTree(el.search.value);
    });
    el.tree.parentNode.querySelector('[data-action="collapse-all"]').addEventListener("click", function () {
      var c = {};
      state.manifest.files.forEach(function (f) {
        var parts = f.path.split("/");
        for (var i = 0; i < parts.length - 1; i++) c[parts.slice(0, i + 1).join("/")] = 1;
      });
      setCollapsed(c);
      buildTree(el.search.value);
    });

    // Comment / review wiring — only when the review layer is enabled.
    if (COMMENTING) {
    // comments panel
    document.getElementById("comments-toggle").addEventListener("click", function () {
      if (!state.current) return;
      el.comments.hidden = !el.comments.hidden;
    });
    document.getElementById("comments-close").addEventListener("click", function () {
      el.comments.hidden = true;
    });
    document.getElementById("comment-add-doc").addEventListener("click", function () {
      if (!state.current) {
        toast("Open a document first");
        return;
      }
      startComment({ anchor: "doc", anchorText: "", quote: "" });
    });
    document.getElementById("comment-cancel").addEventListener("click", function () {
      el.commentForm.hidden = true;
      state.pending = null;
    });
    el.commentForm.addEventListener("submit", submitComment);
    el.commentsList.addEventListener("click", onCommentsClick);

    // selection commenting — right-click a selection to get the Comment action
    el.doc.addEventListener("contextmenu", onDocContextMenu);
    el.selectionBtn.addEventListener("mousedown", function (ev) {
      ev.preventDefault();
    });
    el.selectionBtn.addEventListener("click", function () {
      var p = el.selectionBtn._payload;
      el.selectionBtn.hidden = true;
      if (p) startComment(p);
    });
    // Click an inline 💬 marker → open the panel focused on that comment.
    el.doc.addEventListener("click", function (ev) {
      var marker = ev.target.closest && ev.target.closest(".cmt-marker");
      if (!marker) return;
      ev.preventDefault();
      ev.stopPropagation();
      openComments(state.current, marker.dataset.commentId);
    });
    // Dismiss the floating action on any click that isn't on it.
    document.addEventListener("mousedown", function (ev) {
      if (!el.selectionBtn.hidden && !el.selectionBtn.contains(ev.target)) el.selectionBtn.hidden = true;
    });

    // review menu
    var menuBtn = document.getElementById("review-menu-btn");
    menuBtn.addEventListener("click", function (ev) {
      ev.stopPropagation();
      var open = !el.reviewMenu.hidden;
      el.reviewMenu.hidden = open;
      if (!open) {
        var r = menuBtn.getBoundingClientRect();
        el.reviewMenu.style.top = r.bottom + 6 + "px";
        el.reviewMenu.style.left = Math.max(8, r.right - 224) + "px";
      }
    });
    document.addEventListener("click", function () {
      el.reviewMenu.hidden = true;
    });
    el.reviewMenu.addEventListener("click", function (ev) {
      ev.stopPropagation();
      var b = ev.target.closest("[data-review]");
      if (!b) return;
      el.reviewMenu.hidden = true;
      var act = b.dataset.review;
      if (act === "set-author") {
        var a = prompt("Reviewer name:", getAuthor(false));
        if (a !== null) localStorage.setItem(LS_AUTHOR, a.trim());
      } else if (act === "export-json") exportJson();
      else if (act === "export-md") exportMarkdown();
      else if (act === "import-json") el.importFile.click();
      else if (act === "clear") {
        if (confirm("Delete ALL " + state.comments.length + " review comments? This cannot be undone.")) {
          state.comments = [];
          saveComments();
          if (state.current) {
            renderComments(state.current);
            refreshHeadingMarkers();
          }
          buildTree(el.search.value);
          toast("All comments cleared");
        }
      }
    });
    el.importFile.addEventListener("change", function () {
      if (el.importFile.files[0]) importJson(el.importFile.files[0]);
      el.importFile.value = "";
    });
    } else {
      // Review layer disabled — hide its chrome so the explorer is read-only.
      ["review-count", "comments-toggle", "review-menu-btn"].forEach(function (id) {
        var n = document.getElementById(id);
        if (n) n.hidden = true;
      });
      el.comments.hidden = true;
    }

    // crumbs / brand navigation to home
    document.addEventListener("click", function (ev) {
      var nav = ev.target.closest('[data-nav="home"]');
      if (nav) {
        ev.preventDefault();
        location.hash = "home";
      }
    });

    // mobile sidebar
    document.getElementById("menu-toggle").addEventListener("click", function () {
      el.sidebar.classList.toggle("open");
    });
    el.tree.addEventListener("click", function (ev) {
      if (ev.target.closest(".tree-file")) el.sidebar.classList.remove("open");
    });

    // keyboard: "/" focuses search
    document.addEventListener("keydown", function (ev) {
      if (ev.key === "/" && document.activeElement !== el.search && !/^(INPUT|TEXTAREA)$/.test(document.activeElement.tagName)) {
        ev.preventDefault();
        el.search.focus();
      } else if (ev.key === "Escape") {
        el.selectionBtn.hidden = true;
        el.reviewMenu.hidden = true;
      }
    });

    window.addEventListener("scroll", function () {
      el.selectionBtn.hidden = true;
    }, true);
  }

  // Test/verify hook — used by verify.cjs under a DOM stub; inert in a browser.
  window.__EXPLORER__ = {
    config: CONFIG,
    slugify: slugify,
    resolvePath: resolvePath,
    renderMarkdownString: function (text) {
      if (typeof marked === "undefined") return "";
      marked.setOptions({ gfm: true, breaks: false, headerIds: false, mangle: false });
      return marked.parse(text);
    },
  };

  init();
})();
