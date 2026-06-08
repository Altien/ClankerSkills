---
description: >
  Build a self-contained, static Repository Explorer for the current repo — a
  browsable Markdown site with a file tree, search, and review/commenting, plus a
  code-verified Architecture & Technology analysis as Markdown + expressive HTML
  with inline-SVG diagrams (and rendered mermaid). Thin alias for the
  repository-explorer skill.
argument-hint: "[--browse-only] [--no-comments] [target path, default: repo root]"
---

Invoke the **repository-explorer** skill to build a Repository Explorer for this
repository, following its phased playbook (detect doc conventions → copy the
bundled engine into `docs/repository-explorer/` → generate the Markdown manifest
→ investigate the codebase and author the code-verified Architecture &
Technology analysis as Markdown + inline-SVG HTML → verify to zero failures →
write the README).

Arguments: `$ARGUMENTS`

- Default: **browse + full analysis** — the Markdown browser AND a code-verified
  architecture analysis authored by reading the source (fanning out parallel
  sub-agents for large codebases).
- `--browse-only`: build just the Markdown documentation browser; skip the
  expensive code-investigation + analysis pages.
- `--no-comments`: ship a read-only browser (disable the review/commenting layer).
