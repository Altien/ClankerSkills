# Authoring the code-verified analysis

This is the binding spec for Phase 2–3 of the repository-explorer skill: how to
investigate a codebase and turn it into an honest Architecture & Technology
analysis, published as **Markdown** (mermaid diagrams) and **expressive HTML**
(hand-authored inline SVG). The bar is *verified against code, not paraphrased
from the docs*.

## 1. Investigate (Phase 2)

**Read before writing.** The deliverable's credibility is that every claim traces
to a file. Build a small evidence ledger as you go: `claim → path[:line]`.

**Fan out, then verify yourself.**
- Spawn one read-only sub-agent per subsystem (a service, a package, a major
  directory). Give each a tight brief: *report the tech stack, the request/data
  flow, the key modules, and explicitly what is implemented vs stubbed, with
  file:line evidence. Read the code, not the docs.*
- **Read the dependency manifests yourself** (`package.json`, `pyproject.toml`,
  `go.mod`, `Cargo.toml`, lockfiles, `docker-compose.yml`, Helm, CI). They are
  authoritative for the stack tables and the runtime topology — never take an
  agent's word for a version or a service list.
- Spot-check at least one surprising agent claim against the actual file before
  you print it.

**Find the repo's own status doc.** Many mature repos keep an honest
shipped-vs-deferred doc (a `HONEST-STATE.md`, `STATUS.md`, roadmap, or release
notes). Treat it as the canonical status source — but when it disagrees with the
code, **the code wins**, and you record the divergence.

**Measure, don't guess.** Counts that go in the metrics strip (LOC, services,
endpoints, migrations, providers) must come from a command you actually ran
(`wc -l`, a file count, a route count), not from prose. A stale figure in the
repo's own docs is exactly the kind of divergence worth flagging.

**The honesty rule.** If the docs claim something the code doesn't back up, say
so in a `callout-warn`. If a capability is scaffolded/stubbed, label it
(amber/partial) rather than implying it ships. Don't overclaim; under-claiming a
verified fact is also a defect.

## 2. Choose the medium per diagram (Phase 3)

You ship diagrams two ways. Pick deliberately:

| Use **mermaid** (in the Markdown doc) when… | Use **hand-authored inline SVG** (in the HTML) when… |
|---|---|
| a quick structural sketch communicates it (a flowchart, a sequence, an ER sketch) | you want exact layout, labelled boundaries, and branch/error arrows |
| the diagram should stay trivially editable by future contributors | precision and theme-following vectors matter (the "expressive" set) |
| it's one of several supporting views | it's a centerpiece (system topology, the real coded pipeline, a state machine, a verification cascade) |

The browser renders ```mermaid fences (mermaid is vendored, `securityLevel:
strict`). The HTML SVGs are styled by `architecture.css` classes so they follow
light/dark automatically.

## 3. Inline-SVG authoring (the HTML pages)

Start from `kit/analysis/architecture.template.html`. The diagram classes live in
`architecture.css`; use them instead of hard-coded colors so the SVG themes
itself:

**Node boxes:** `nb` (neutral), `nb-accent` (highlight), `nb-data` (data store),
`nb-boundary` (dashed accent — a security/trust boundary), `nb-green` /
`nb-red` (verified / failure states).
**Bands & labels:** `band`, `band-strong` (grouping rectangles behind a tier);
`band-label` (small caps tier label), `band-label.accent`.
**Text:** `nt` (bold title), `nt2` (semibold), `ns` (muted subtitle), `pn`/`ps`
(pipeline node title/sub), `dnote` (in/out note), `edge-cap` (mono edge caption).
Add `.red`/`.green` to a text class to tint it.
**Edges:** `ed` (neutral), `ed-accent`, `ed-red`, `ed-green`, `ed-dash`. Pair
each with an arrowhead `<marker>` whose `<path>` uses the matching
`ed-head` / `ed-head-accent` / `ed-head-red` / `ed-head-green` class. Define the
markers once per `<svg>` in `<defs>`.
**Chips:** `chip` + `ct`/`ct2` for small inline tags (pipeline stages, brakes).

Conventions:
- One `start`/entry and one terminal per flow; arrows show the **real coded
  order**, including the branch arrows (errors, short-circuits, refusals) — those
  are what make it honest rather than idealized.
- Give every `<svg>` a `viewBox` and `role="img"` + `aria-label`. Keep numbers
  finite and boxes inside the canvas (verify.cjs tag-balances the page; eyeball
  geometry via `serve.py`).
- **Links:** a source-code file opens raw via `../../<path>` (`target="_blank"`);
  a Markdown doc that the explorer indexes opens in-app via
  `index.html#/<path>`. Never link a code file through `index.html#/` — the
  router only resolves indexed docs.

## 4. Markdown analysis (the doc form)

Write `docs/ARCHITECTURE-ANALYSIS.md` (or the repo's docs convention) as a normal
Markdown doc — prose, tables, and ```mermaid blocks. It is indexed by the
manifest automatically; add it to `keyDocs` so it surfaces under "Start here".
Keep it consistent with the HTML page (same facts, same divergence flags); the
two are different renderings of one investigation, not two investigations.

## 5. Wire-up & verification

- Add each HTML page to `EXPLORER_CONFIG.analysisPages` as
  `{ href, title, badge, sub }` — it becomes a feature card on the home view.
- Copy `kit/analysis/architecture.css` → `DEST/assets/architecture.css`.
- `node verify.cjs` checks the page exists, is tag-balanced, and that its local
  `.css`/`.js` references resolve. It does **not** pixel-check SVG — say so, and
  eyeball via `serve.py`.

## Quality bar

Every label, row, and number is specific to this repo and traceable to a file.
The analysis is verified against code and flags doc↔code divergences. Diagrams
are split sensibly between mermaid (quick/maintainable) and SVG (expressive/
precise), and both follow the theme. No fabrication; flag present-vs-inferred.
