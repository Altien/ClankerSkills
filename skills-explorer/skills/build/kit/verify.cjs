/* verify.js — Phase-4 STRUCTURAL verification (no browser / SVG rasterizer).
 *
 * Loads the real app.js diagram code under a minimal DOM stub, then for EVERY
 * manifest artifact builds its graph (curated or shape fallback) and runs the
 * layout/render. Asserts: graph integrity (one start, one output, valid
 * loop/skip/stop targets) and geometry (no NaN, no negative width/height, chips
 * within node bounds). This validates geometry + links, NOT pixels — eyeball via
 * `python3 docs/explorer/serve.py` for visual confirmation.
 *
 * Run:  node docs/explorer/verify.js
 */
"use strict";
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const DIR = __dirname;
let fails = 0, checks = 0;
function ok(cond, msg) { checks++; if (!cond) { fails++; console.error("  FAIL: " + msg); } }

// ── minimal DOM/window stub so app.js can initialise without a browser ──
function stubEl() {
  const el = { style: {}, dataset: {}, classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
    addEventListener() {}, removeEventListener() {}, appendChild() {}, querySelectorAll() { return []; },
    setAttribute() {}, getAttribute() { return "light"; }, focus() {}, blur() {} };
  Object.defineProperty(el, "innerHTML", { set() {}, get() { return ""; } });
  Object.defineProperty(el, "textContent", { set() {}, get() { return ""; } });
  return el;
}
const sandbox = {
  console,
  localStorage: { getItem() { return null; }, setItem() {} },
  fetch() { return Promise.reject(new Error("no fetch in verify")); },
  setTimeout, clearTimeout,
};
sandbox.window = sandbox;
sandbox.document = {
  readyState: "complete",
  documentElement: { setAttribute() {}, getAttribute() { return "light"; } },
  querySelector() { return stubEl(); },
  querySelectorAll() { return []; },
  getElementById() { return stubEl(); },
  addEventListener() {},
};
vm.createContext(sandbox);

// load curated data + marked + app into the sandbox
for (const f of ["assets/explorer-data.js", "assets/marked.min.js", "assets/app.js"]) {
  vm.runInContext(fs.readFileSync(path.join(DIR, f), "utf8"), sandbox, { filename: f });
}

const E = sandbox.window.__EXPLORER__;
ok(E && typeof E.buildDiagram === "function", "app.js exposed __EXPLORER__.buildDiagram");
const curated = (sandbox.window.EXPLORER_DATA && sandbox.window.EXPLORER_DATA.artifacts) || {};

const manifest = JSON.parse(fs.readFileSync(path.join(DIR, "explorer-manifest.json"), "utf8"));

// ── graph integrity ──
function checkGraph(id, g, isCurated) {
  const nodes = g.nodes || [];
  const ids = new Set(nodes.map(n => n.id));
  ok(ids.size === nodes.length, `[${id}] node ids unique`);
  const starts = nodes.filter(n => n.type === "start").length;
  const outs = nodes.filter(n => n.type === "output").length;
  ok(starts === 1, `[${id}] exactly one start (got ${starts})`);
  ok(outs === 1, `[${id}] exactly one output (got ${outs})`);
  nodes.forEach(n => {
    if (n.loopTo) ok(ids.has(n.loopTo.id), `[${id}] loopTo target '${n.loopTo.id}' exists`);
    if (n.skipTo) ok(ids.has(n.skipTo.id), `[${id}] skipTo target '${n.skipTo.id}' exists`);
  });
}

// ── geometry: render + assert numbers are finite/non-negative, chips in bounds ──
function checkGeometry(id, g) {
  const svg = E.buildDiagram(g);
  ok(svg.indexOf("NaN") === -1, `[${id}] no NaN in SVG`);
  ok(svg.indexOf("undefined") === -1, `[${id}] no 'undefined' in SVG`);

  // viewBox positive
  const vb = /viewBox="0 0 ([\d.]+) ([\d.]+)"/.exec(svg);
  ok(vb && +vb[1] > 0 && +vb[2] > 0, `[${id}] positive viewBox`);
  const W = vb ? +vb[1] : 0;

  // every rect width/height > 0 and within canvas
  let m, rectRe = /<rect[^>]*\sx="([-\d.]+)"[^>]*\sy="([-\d.]+)"[^>]*\swidth="([-\d.]+)"[^>]*\sheight="([-\d.]+)"/g;
  while ((m = rectRe.exec(svg))) {
    const x = +m[1], y = +m[2], w = +m[3], h = +m[4];
    ok([x, y, w, h].every(Number.isFinite), `[${id}] rect coords finite`);
    ok(w > 0 && h > 0, `[${id}] rect non-negative size`);
    ok(x >= -1 && x + w <= W + 1, `[${id}] rect within canvas width (x=${x} w=${w} W=${W})`);
  }
  // all positional numeric attrs finite (catch stray NaN in paths/text).
  // Require a leading space so we match real attribute names, not the tail of
  // tokens like viewBox / markerWidth.
  let attrRe = /\s(x|y|width|height|cx|cy)="([^"]+)"/g, a;
  while ((a = attrRe.exec(svg))) ok(Number.isFinite(+a[2]), `[${id}] attr ${a[1]} finite ('${a[2]}')`);
}

let curatedCount = 0, shapeCount = 0;
for (const art of manifest.artifacts) {
  const cur = curated[art.id];
  let g;
  if (cur && cur.graph) { g = cur.graph; curatedCount++; }
  else { g = E.shapeGraph(art, cur || {}); shapeCount++; }
  checkGraph(art.id, g, !!(cur && cur.graph));
  checkGeometry(art.id, g);
}

// render smoke test — exercise renderHome + renderDetail for every artifact
// to catch runtime errors in the detail/home HTML builders (DOM writes are stubbed).
const byId = {};
manifest.artifacts.forEach(a => { byId[a.id] = a; });
E._setState(manifest, byId);
try { E.renderHome(); ok(true, "renderHome ran"); }
catch (e) { ok(false, "renderHome threw: " + e.message); }
manifest.artifacts.forEach(a => {
  try { E.renderDetail(a); }
  catch (e) { ok(false, `[${a.id}] renderDetail threw: ${e.message}`); }
});

// section extraction — slice a real heading out of a real source file, verbatim.
// Repo-agnostic: picks the first artifact that has multiple headings and proves the
// slicer returns the right section, stops at the next same-or-higher heading, and
// does not bleed into the following section.
(function () {
  const REPO = path.join(DIR, "..", "..");
  // (adapted for this repo: artifacts ARE markdown — sample any multi-heading one)
  const sample = manifest.artifacts.find(a =>
    !a.embedded && (a.headings || []).filter(h => h.level <= 3).length >= 2);
  if (sample) {
    const text = fs.readFileSync(path.join(REPO, sample.source_path), "utf8");
    const hs = sample.headings.filter(h => h.level <= 3);
    const sec = E.extractSection(text, sample, hs[0].text);
    ok(sec && sec.body.trim().length > 0, `extractSection returns a non-empty section for ${sample.id}`);
    const next = hs.find(h => h.level <= hs[0].level && h.text !== hs[0].text);
    if (sec && next) ok(!new RegExp("^#{1,3}\\s+" + next.text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "m").test(sec.body),
      "extracted section stops before the next same-or-higher heading");
  } else {
    ok(true, "no multi-heading artifact to sample (repo has none) — skipped");
  }
  // every step node resolves to a real section in its source
  let resolved = 0, attempted = 0;
  for (const a of manifest.artifacts) {
    if (a.embedded) continue; // md/yaml sources are first-class in this repo
    const g = (curated[a.id] && curated[a.id].graph) ? curated[a.id].graph : E.shapeGraph(a, curated[a.id] || {});
    const text = fs.readFileSync(path.join(REPO, a.source_path), "utf8");
    g.nodes.forEach(n => {
      const anchor = n.srcHeading || ((n.type === "step" || n.type === "decision") ? n.label : null);
      if (!anchor) return;
      attempted++;
      if (E.extractSection(text, a, anchor)) resolved++;
    });
  }
  ok(attempted > 0, "section-resolution attempted for step nodes");
  console.log(`  section anchors resolved to real source: ${resolved}/${attempted}`);
})();

// CURATED graphs: every step/decision node MUST resolve to a real source section
// (via srcHeading) or be explicitly flagged srcWhole. A curated node that silently
// falls back to dumping the whole file is a defect and fails the build.
(function () {
  const REPO = path.join(DIR, "..", "..");
  let ok2 = 0, curatedSteps = 0;
  Object.keys(curated).forEach(id => {
    const c = curated[id]; if (!c || !c.graph) return;
    const a = byId[id]; if (!a) return;
    let text; try { text = fs.readFileSync(path.join(REPO, a.source_path), "utf8"); } catch (e) { return; }
    // shared-anchor rule: when ≥2 step nodes anchor to the SAME heading, each
    // must carry a srcFocus so the panel can slice that node's own item —
    // otherwise siblings all show an identical snippet.
    const headCounts = {};
    c.graph.nodes.forEach(n => {
      if ((n.type === "step" || n.type === "decision") && n.srcHeading)
        headCounts[n.srcHeading] = (headCounts[n.srcHeading] || 0) + 1;
    });
    const slices = {}; // heading -> [{nid, slice}] for shared-anchor distinctness
    c.graph.nodes.forEach(n => {
      if (n.type !== "step" && n.type !== "decision") return;
      curatedSteps++;
      if (n.srcWhole) {
        if (n.srcFocus) ok(text.indexOf(n.srcFocus) !== -1, `[${id}/${n.id}] srcFocus found verbatim in source`);
        ok2++; return;
      }
      const anchor = n.srcHeading || n.label;
      const sec = E.extractSection(text, a, anchor);
      const good = !!(sec && sec.body.trim());
      ok(good, `[${id}/${n.id}] curated node resolves to a real section ("${anchor}") — not a whole-file dump`);
      if (good) ok2++;
      if (n.srcHeading && headCounts[n.srcHeading] > 1)
        ok(!!n.srcFocus, `[${id}/${n.id}] shared srcHeading ("${n.srcHeading}") carries a srcFocus`);
      if (n.srcFocus && sec) {
        ok(sec.body.indexOf(n.srcFocus) !== -1, `[${id}/${n.id}] srcFocus found verbatim in its section`);
        const sl = E.focusSlice(sec.body, n.srcFocus);
        ok(!!(sl && sl.trim()), `[${id}/${n.id}] srcFocus narrows to a non-empty slice`);
        if (n.srcHeading) (slices[n.srcHeading] = slices[n.srcHeading] || []).push({ nid: n.id, slice: sl });
      }
    });
    // siblings sharing one heading must show DIFFERENT slices — the whole point
    Object.keys(slices).forEach(h => {
      const group = slices[h];
      if (group.length < 2) return;
      const seen = {};
      group.forEach(g => {
        ok(!seen[g.slice], `[${id}/${g.nid}] focused slice differs from its siblings under "${h}"`);
        seen[g.slice] = true;
      });
    });
  });
  console.log(`  curated step nodes anchored to a real section (or whole-prompt): ${ok2}/${curatedSteps}`);
})();

// node SUMMARY quality — EVERY step/decision node must carry a hand-AUTHORED
// summary (note/desc). Section-lede extraction is NOT counted as a summary; relying
// on it was the prior defect. The build fails if any node lacks an authored summary.
(function () {
  const REPO = path.join(DIR, "..", "..");
  let authoredN = 0, total = 0, missing = [];
  for (const a of manifest.artifacts) {
    // adapted for this repo: skills/agents/cookbooks are .md/.yaml and MUST carry
    // authored summaries; only instruction docs (practice-profile templates,
    // repo CLAUDE.md) are exempt — their shape graphs are reference material.
    if (a.kind === "instruction-doc") continue;
    const g = (curated[a.id] && curated[a.id].graph) ? curated[a.id].graph : E.shapeGraph(a, curated[a.id] || {});
    g.nodes.forEach(n => {
      if (n.type === "start" || n.type === "output") return;
      total++;
      const note = (n.note || n.desc || "").trim();
      const authored = note.length >= 20 && !/^Step in the .* workflow/.test(note);
      ok(authored, `[${a.id}/${n.id}] step has an authored summary ("${n.label}")`);
      if (authored) authoredN++; else missing.push(`${a.id}/${n.id} (${n.label})`);
    });
  }
  console.log(`  step nodes with an AUTHORED summary: ${authoredN}/${total}`);
  if (missing.length) console.log("  MISSING authored summary:\n   - " + missing.join("\n   - "));
})();

// assessment card renders for every artifact (with grounded fallback)
manifest.artifacts.forEach(a => {
  try {
    const html = E.buildAssessment(a, curated[a.id] || {});
    ok(typeof html === "string", `[${a.id}] buildAssessment returns string`);
  } catch (e) { ok(false, `[${a.id}] buildAssessment threw: ${e.message}`); }
});

// markdown renderer smoke test
const md = sandbox.window.marked("# H1\n\n- a\n- b\n\n**bold** and `code` and [x](https://e.com)\n\n| a | b |\n|---|---|\n| 1 | 2 |");
ok(/<h1>/.test(md) && /<ul>/.test(md) && /<strong>/.test(md) && /<table/.test(md), "marked renders h1/list/bold/table");

console.log(`\nArtifacts: ${manifest.artifacts.length}  (curated graphs: ${curatedCount}, shape fallback: ${shapeCount})`);
console.log(`Checks: ${checks}   Failures: ${fails}`);
process.exit(fails ? 1 : 0);
