/* verify.cjs — Phase-4 STRUCTURAL verification for the Repository Explorer.
 *
 * No browser / no SVG rasterizer. This:
 *   1. loads marked + app.js under a minimal DOM stub and asserts the app
 *      initialises without throwing and exposes window.__EXPLORER__;
 *   2. exercises the pure helpers (slugify, resolvePath, markdown→HTML, the
 *      ```mermaid fence hook);
 *   3. validates manifest.json: shape, unique paths, every path exists on disk;
 *   4. checks the kit assets are present;
 *   5. for every analysisPages entry in EXPLORER_CONFIG, asserts the HTML file
 *      exists, is tag-balanced, and its referenced local assets resolve.
 *
 * Geometry of hand-authored SVG in analysis pages is NOT pixel-checked — eyeball
 * via `python3 <thisdir>/serve.py`.
 *
 * Run:  node docs/repository-explorer/verify.cjs
 */
"use strict";
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const DIR = __dirname;
// The reviewer can live at any depth (e.g. docs/JIRA/JIRA-1855/review), so find the
// repo root by walking up to the nearest .git rather than assuming a fixed depth.
function findRepoRoot(start) {
  let p = start;
  for (let i = 0; i < 40; i++) {
    if (fs.existsSync(path.join(p, ".git"))) return p;
    const parent = path.dirname(p);
    if (parent === p) break;
    p = parent;
  }
  return path.resolve(start, "..", "..");
}
const REPO_ROOT = findRepoRoot(DIR);
let fails = 0, checks = 0;
function ok(cond, msg) { checks++; if (!cond) { fails++; console.error("  FAIL: " + msg); } }

// ── minimal DOM/window stub so app.js can initialise without a browser ──
function stubEl() {
  const el = {
    style: { setProperty() {} }, dataset: {}, value: "", hidden: false, files: [],
    classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
    addEventListener() {}, removeEventListener() {}, appendChild() {}, insertBefore() {},
    replaceChild() {}, remove() {}, setAttribute() {}, getAttribute() { return "light"; },
    focus() {}, blur() {}, querySelector() { return stubEl(); }, querySelectorAll() { return []; },
    closest() { return null; }, getBoundingClientRect() { return { top: 0, left: 0, width: 0, bottom: 0 }; },
  };
  el.parentNode = el; // so el.parentNode.querySelector(...) is safe
  Object.defineProperty(el, "innerHTML", { set() {}, get() { return ""; } });
  Object.defineProperty(el, "textContent", { set() {}, get() { return ""; } });
  return el;
}

const sandbox = {
  console,
  localStorage: { getItem() { return null; }, setItem() {}, removeItem() {} },
  fetch() { return Promise.reject(new Error("no fetch in verify")); },
  setTimeout, clearTimeout, navigator: { clipboard: null },
  addEventListener() {}, removeEventListener() {},
  getSelection() { return { isCollapsed: true, toString() { return ""; } }; },
  scrollX: 0, scrollY: 0,
};
sandbox.window = sandbox;
sandbox.document = {
  readyState: "complete", title: "",
  documentElement: { setAttribute() {}, getAttribute() { return "light"; }, style: { setProperty() {} } },
  body: stubEl(),
  querySelector() { return stubEl(); }, querySelectorAll() { return []; },
  getElementById() { return stubEl(); }, createElement() { return stubEl(); },
  addEventListener() {}, getSelection() { return { isCollapsed: true, toString() { return ""; } }; },
};
vm.createContext(sandbox);

// pull EXPLORER_CONFIG out of index.html (it's an inline <script>)
const indexHtml = fs.readFileSync(path.join(DIR, "index.html"), "utf8");
const cfgMatch = /window\.EXPLORER_CONFIG\s*=\s*([\s\S]*?);\s*<\/script>/.exec(indexHtml);
ok(!!cfgMatch, "index.html contains a window.EXPLORER_CONFIG block");
let CONFIG = {};
if (cfgMatch) {
  try { CONFIG = vm.runInContext("(" + cfgMatch[1] + ")", sandbox); }
  catch (e) { ok(false, "EXPLORER_CONFIG parses as an object: " + e.message); }
}
sandbox.window.EXPLORER_CONFIG = CONFIG;

// load marked then app.js into the sandbox; app.js self-inits on load
for (const f of ["assets/marked.min.js", "assets/app.js"]) {
  try { vm.runInContext(fs.readFileSync(path.join(DIR, f), "utf8"), sandbox, { filename: f }); }
  catch (e) { ok(false, `${f} loaded without throwing: ${e.message}`); }
}

const E = sandbox.window.__EXPLORER__;
ok(E && typeof E.slugify === "function", "app.js exposed __EXPLORER__.slugify");
ok(E && typeof E.resolvePath === "function", "app.js exposed __EXPLORER__.resolvePath");
ok(E && typeof E.renderMarkdownString === "function", "app.js exposed __EXPLORER__.renderMarkdownString");

if (E) {
  // helper behaviour
  ok(E.slugify("Hello, World!") === "hello-world", "slugify normalises headings");
  const r = E.resolvePath("docs/adr", "../db-schema.md#x");
  ok(r && r.path === "docs/db-schema.md" && r.hash === "#x", "resolvePath resolves .. and hash");
  ok(E.resolvePath("docs", "https://example.com") === null, "resolvePath ignores absolute URLs");

  // markdown renderer + mermaid fence hook
  const md = E.renderMarkdownString("# H1\n\n- a\n- b\n\n**b** `c` [x](https://e.com)\n\n| a | b |\n|---|---|\n| 1 | 2 |");
  ok(/<h1>/.test(md) && /<ul>/.test(md) && /<strong>/.test(md) && /<table/.test(md), "marked renders h1/list/bold/table");
  const mmd = E.renderMarkdownString("```mermaid\ngraph TD; A-->B\n```");
  ok(/class="language-mermaid"/.test(mmd), "mermaid fences become code.language-mermaid (browser then renders them)");
}

// ── manifest.json ──
const manifestPath = path.join(DIR, "manifest.json");
ok(fs.existsSync(manifestPath), "manifest.json exists (run build_manifest.py first)");
if (fs.existsSync(manifestPath)) {
  let m;
  try { m = JSON.parse(fs.readFileSync(manifestPath, "utf8")); }
  catch (e) { ok(false, "manifest.json is valid JSON: " + e.message); m = null; }
  if (m) {
    ok(Array.isArray(m.files), "manifest.files is an array");
    ok(typeof m.fileCount === "number" && m.fileCount === (m.files || []).length, "fileCount matches files length");
    const seen = new Set();
    let missing = 0, mdCount = 0;
    (m.files || []).forEach(f => {
      ok(f.path && f.title && f.category && f.type, `entry has path/title/category/type (${f.path})`);
      ok(!seen.has(f.path), `path is unique (${f.path})`);
      seen.add(f.path);
      if (f.type === "markdown") mdCount++;
      if (!fs.existsSync(path.join(REPO_ROOT, f.path))) { missing++; ok(false, `indexed file exists on disk: ${f.path}`); }
    });
    console.log(`  manifest: ${(m.files || []).length} files (${mdCount} markdown), ${missing} missing on disk`);
  }
}

// ── kit assets present ──
["assets/app.js", "assets/styles.css", "assets/marked.min.js", "index.html", "serve.py", "build_manifest.py"]
  .forEach(rel => ok(fs.existsSync(path.join(DIR, rel)), `kit asset present: ${rel}`));
const mermaidPresent = fs.existsSync(path.join(DIR, "assets/mermaid.min.js"));
const indexLoadsMermaid = /assets\/mermaid\.min\.js/.test(indexHtml);
ok(mermaidPresent === indexLoadsMermaid,
  `mermaid asset and its <script> agree (asset=${mermaidPresent}, script=${indexLoadsMermaid})`);

// ── analysis pages (hand-authored HTML, e.g. architecture.html) ──
const VOID = new Set(["area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
  "param", "source", "track", "wbr", "path", "rect", "line", "circle", "polygon", "polyline",
  "ellipse", "use", "stop", "tspan"]);
function tagBalance(html) {
  // Strip what a real parser does not scan for tags: comments, and the raw-text
  // content of <script>/<style> (which legitimately contains < and pseudo-tags).
  html = html
    .replace(/<!--[\s\S]*?-->/g, "")
    .replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, "")
    .replace(/<style\b[^>]*>[\s\S]*?<\/style>/gi, "");
  const stack = [];
  let stray = 0;
  const re = /<\/?([a-zA-Z][a-zA-Z0-9]*)\b[^>]*?(\/?)>/g;
  let m;
  while ((m = re.exec(html))) {
    const tag = m[1].toLowerCase();
    const selfClose = m[2] === "/" || VOID.has(tag);
    if (m[0][1] === "/") {
      if (stack[stack.length - 1] === tag) stack.pop();
      else if (stack.includes(tag)) { while (stack.length && stack.pop() !== tag) {} }
      else stray++;
    } else if (!selfClose) {
      stack.push(tag);
    }
  }
  return { unclosed: stack.length, stray };
}
(CONFIG.analysisPages || []).forEach(p => {
  const href = p.href || "";
  if (!href || /^[a-z]+:\/\//i.test(href)) return;
  const file = path.join(DIR, href);
  ok(fs.existsSync(file), `analysis page exists: ${href}`);
  if (!fs.existsSync(file)) return;
  const html = fs.readFileSync(file, "utf8");
  const tb = tagBalance(html);
  ok(tb.unclosed === 0 && tb.stray === 0, `analysis page tag-balanced: ${href} (unclosed=${tb.unclosed}, stray=${tb.stray})`);
  // local stylesheet/script references resolve
  let lm, refRe = /(?:href|src)="([^"#?][^":]*?)"/g;
  while ((lm = refRe.exec(html))) {
    const ref = lm[1];
    if (/^[a-z]+:\/\//i.test(ref) || ref.startsWith("#") || ref.startsWith("//")) continue;
    if (!/\.(css|js)$/.test(ref)) continue; // only assert local css/js, not doc links
    const resolved = path.resolve(path.dirname(file), ref);
    ok(fs.existsSync(resolved), `${href} references existing asset: ${ref}`);
  }
});

console.log(`\nChecks: ${checks}   Failures: ${fails}`);
process.exit(fails ? 1 : 0);
