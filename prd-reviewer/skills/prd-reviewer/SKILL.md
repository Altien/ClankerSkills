---
name: prd-reviewer
description: >
  Build a self-contained, static review harness for ONE PRD / design / epic — not
  the whole repo. Scopes a Markdown browser to a single PRD folder plus the source
  files that PRD references (driven by a simple referenced-files.txt list in the PRD
  folder), so a reviewer reads the design and clicks straight through to the real
  code. Quiet review/commenting layer: the comments panel stays closed until asked
  for; select text and right-click to comment; commented passages get an inline
  marker. Use when the user says "build a PRD browser/reviewer", "make a review
  harness for this PRD / design doc / epic", "let me review and comment on <doc>",
  or runs /prd-reviewer.
argument-hint: "[--no-comments] <PRD folder, e.g. docs/JIRA/JIRA-1855>"
---

# Build a PRD Reviewer

Build a self-contained, dependency-light static **review harness for a single PRD /
design / epic** under `<PRD_DIR>/review/`. Unlike the repository-explorer (which
documents a whole repo), this is scoped to **one document set**:

1. **The PRD folder** — every Markdown doc inside `<PRD_DIR>` (the design, decisions,
   diagrams), browsable with a tree, search, faithful GFM rendering and rendered
   ```mermaid fences.
2. **The source it references** — the files listed in `<PRD_DIR>/referenced-files.txt`
   are made navigable and viewable, so the reviewer clicks from a claim in the design
   straight to the actual code.

**Quiet commenting** (the point of this skill vs the repo explorer): the comments
panel is **closed by default**. To comment, **select text and right-click** → a small
"Comment" action appears. Saved comments **highlight the passage inline with a 💬
marker**; clicking the marker opens that comment. Heading markers are hover-only.
Comments persist in `localStorage` and export to JSON / copy-as-Markdown.

The engine is bundled in this skill's own directory (the folder containing this
`SKILL.md`), under `kit/`. Locate it via `${CLAUDE_SKILL_DIR}` (equivalently
`${CLAUDE_PLUGIN_ROOT}/skills/prd-reviewer`); if unset, use the directory containing
this `SKILL.md`. Then let `KIT = SELF/kit` and `DEST = <repo>/<PRD_DIR>/review`.

> **Golden rule:** the **mechanical manifest** (`manifest.json`, from
> `build_manifest.py`) is regenerable and never holds authored content. Treat
> `assets/*`, `serve.py`, `verify.cjs` as **copy-verbatim**; `build_manifest.py`'s
> `PRD_DIR` and `index.html`'s `EXPLORER_CONFIG` as **adapt**.

## Phase 0 — Identify the PRD and its references

- **PRD folder** — the `<PRD_DIR>` from the argument (e.g. `docs/JIRA/JIRA-1855`).
  All Markdown inside it is the review surface; pick the 1–3 entry docs for the
  "Start here" cards (`keyDocs`).
- **Referenced source** — discover the files the PRD cites: grep the PRD's Markdown
  for repo paths / code links (e.g. `\.cs|\.ts|/src/|ADM/`), and ask the user if a
  project/area should be navigable. Write them to **`<PRD_DIR>/referenced-files.txt`**
  — one path-or-glob per line, optional `| Label` to group them in the sidebar:

  ```
  # Client transport
  ADMClient/Integration/Integration.Library/Core/Net/*.cs | Client · transport
  ADM/Integration.Net/Net/IntegrationNetRequest.cs        | Server · handler
  ```

  This file is the single source of truth for what extra code is browsable; it lives
  with the PRD so it is reviewed and version-controlled alongside it.
- **Decide the review layer.** Default on. `--no-comments` ships a read-only browser.

## Phase 1 — Build

1. **Copy the kit verbatim** into `DEST/`: `index.html`, `serve.py`, `verify.cjs`,
   `build_manifest.py`, and `assets/*` (`app.js`, `styles.css`, `marked.min.js`,
   `mermaid.min.js`), preserving `assets/`.
2. **Set the scope** — in `DEST/build_manifest.py`, set `PRD_DIR` to the repo-relative
   PRD folder. (Repo root is auto-detected by walking up to `.git`, so `DEST` may be
   nested at any depth.)
3. **Brand** — edit only `window.EXPLORER_CONFIG` in `DEST/index.html`:
   `brand` (e.g. the ticket id), `tagline`, optional `intro`/`accent`, `commenting`,
   `keyDocs` (the entry docs from Phase 0), and a **unique** `storageNamespace` per
   PRD (so two reviewers don't share comments). Set `outputDir` to `DEST`'s
   repo-relative path. Leave `analysisPages: []` unless you author a proposal HTML.
   **`repoRoot` must be the relative path from `DEST` back to the repo root** — count
   the depth (e.g. `docs/JIRA/JIRA-1855/review` → `"../../../../"`).
4. **Generate + verify + serve**:
   ```
   python <DEST>/build_manifest.py     # check the PRD + referenced counts
   node   <DEST>/verify.cjs            # MUST exit 0
   python <DEST>/serve.py              # eyeball; right-click a selection to comment
   ```

## Phase 2 — Wrap up

Write `DEST/README.md` (how to serve, how to regenerate, that the referenced list
lives in `<PRD_DIR>/referenced-files.txt`). Then **commit in place on the current
branch** alongside the PRD — this reviews work in your own repo, so there is no
fork/PR ceremony. Match the repo's commit conventions. Report the PRD + referenced
counts.

## Phase 3 — Evolve this skill

When a build surfaces a reusable improvement (an engine fix, a sharper discovery
rule), write it back into this skill's own directory (`SELF`) so the next invocation
inherits it. Keep `kit/` repo-agnostic. Run the kit's checks green
(`node assets/app.js --check`-style `node --check`, `python -m py_compile`) before and
after, and commit skill changes separately from the target-repo work.

## Quality bar

Scope tight: index the PRD folder and *only* the source it actually references — never
the whole repo. Every "Start here" doc and referenced label must be specific to this
PRD. The commenting must stay quiet (no panel until asked; right-click to comment;
inline marker on commented text). No new runtime dependencies.
