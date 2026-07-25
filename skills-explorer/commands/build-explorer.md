---
description: >
  Build a self-contained, static Skills & Prompts Explorer for the current
  repository — discovers every skill, agent, prompt, and instruction doc and
  generates a browsable site with assessment cards and clickable, source-linked
  workflow diagrams. Thin alias for the build-explorer skill.
argument-hint: "[--manifest-only] [target path, default: repo root]"
---

Invoke the **build-explorer** skill to build a Skills & Prompts Explorer for
this repository, following its phased playbook (detect conventions → copy the
bundled engine into `docs/explorer/` → adapt the discovery layer → author the
per-artifact assessment cards and workflow graphs → assemble + verify to zero
failures → write the README).

Arguments: `$ARGUMENTS`

- Default: full authoring (read every artifact; author curated graphs +
  assessments, fanning out parallel sub-agents for large rosters).
- `--manifest-only`: discovery + auto-derived shape diagrams and mechanical
  assessment fallbacks only; skip the expensive curated authoring.

This command is for the initial build. If `docs/explorer/` already exists, invoke
`/update-explorer` so removals remain historical and the verified update log is preserved.
