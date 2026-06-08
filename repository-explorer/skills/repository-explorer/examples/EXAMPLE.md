# Worked example — the LQ.AI repository

The repository-explorer engine is the generalization of an explorer first built
by hand for the **LQ.AI** codebase (a 3-service legal-AI platform: a SvelteKit
web app, a FastAPI backend, and a FastAPI inference gateway). That build is the
reference for what "good" looks like.

## What was produced

- **The Markdown browser** (`docs/explore/`) — indexed ~250 docs (Markdown plus
  the OpenAPI specs and the gateway config), with a folder tree, search, and the
  review-commenting layer.
- **The code-verified analysis** (`docs/explore/architecture.html`) — authored
  after reading `api/`, `gateway/`, `web/package.json`, `docker-compose.yml`, and
  the Helm chart, and cross-checking the repo's own `docs/HONEST-STATE.md`. Four
  hand-authored inline-SVG diagrams: system topology (clients → backend →
  gateway → providers + data plane), the real coded gateway request pipeline (with
  the tier-floor `403` branch), the four-stage citation cascade, and the
  autonomous layer's five-phase state machine with its guard chokepoint.

## Divergences it surfaced (the honesty rule in action)

- The README/architecture docs called the gateway **"~3,000 LOC"**; the tree
  measured **12,163 LOC** (`find gateway/app -name '*.py' | xargs wc -l`).
- Gateway **rate limiting** had a config schema but **no enforcement** — the docs
  listed it as if active.
- The Word add-in was a **scaffold**; the Slack/Teams bridges **partial** (not
  live-verified) — labelled amber, not implied as shipped.

## The `EXPLORER_CONFIG` that drove it

A close equivalent of the config you'd set in `index.html` for that repo:

```js
window.EXPLORER_CONFIG = {
  brand: "LQ.AI",
  tagline: "Repository Explorer",
  brandMark: "LQ",
  accent: "#2f5bd9",
  intro: "Open-source, self-hosted AI for in-house legal teams. A read-and-review " +
         "surface over the repo's documentation — browse a file, then select text " +
         "or a heading to leave a review comment.",
  repoRoot: "../../",
  outputDir: "docs/explore",          // LQ.AI used docs/explore; the kit defaults to docs/repository-explorer
  storageNamespace: "lqai",
  commenting: true,
  keyDocs: [
    "README.md", "docs/PRD.md", "docs/architecture.md", "docs/HONEST-STATE.md",
    "CLAUDE.md", "docs/db-schema.md", "CONTRIBUTING.md"
  ],
  analysisPages: [
    { href: "architecture.html", title: "Architecture & Technology",
      badge: "✓ Code-verified",
      sub: "System topology, the gateway pipeline, the citation cascade, and the autonomous layer — read from the source." }
  ]
};
```

## Lessons baked into the skill

- The metrics strip and stack tables came from commands actually run + the
  dependency manifests read directly — not from the prose.
- Source-file links opened the raw file (`../../api/app/...`); Markdown links
  opened in the explorer (`index.html#/docs/...`). The verifier enforces that
  analysis-page assets resolve.
- The diagrams were hand-authored SVG because they were the centerpiece and
  needed labelled boundaries and branch arrows; quick structural sketches in a
  repo's existing `architecture.md` (mermaid) render in the browser as-is.
