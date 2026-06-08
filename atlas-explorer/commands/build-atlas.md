---
description: >
  Build The Atlas for the current repository — a live FastAPI documentation
  navigator that binds markdown docs to the code they describe: doc↔code 50/50
  views, FTS5 search, live drift detection, authored journeys + diagrams, and
  anchored feedback with clipboard agent briefs. Thin alias for the
  atlas-explorer skill.
argument-hint: "[--no-curation] [--no-comments] [--manifest-only] [target dir, default: docs/atlas]"
---

Invoke the **atlas-explorer** skill to build The Atlas for this repository,
following its phased playbook (copy the bundled engine kit into `docs/atlas/`
verbatim → survey the corpus and code surface → configure `atlas.config.yaml`
until the server boots and tests pass → author the curation layer to the
quality bar → verify to zero curation errors → write the README).

Arguments: `$ARGUMENTS`

- Default: **full build** — working navigator (50/50, search, drift,
  commenting) PLUS the full authored curation (summaries for every full-depth
  doc, journeys, flow diagrams, claims). Fan out parallel sub-agents for large
  corpora.
- `--no-curation`: stop after a working navigator + search + drift + comments
  with an empty `curated/`; skip the expensive authoring phase.
- `--no-comments`: ship a read-only navigator (feedback layer disabled).
- `--manifest-only`: discovery + counts only — report the corpus and code
  surface it would index, build nothing. A fast dry-run to scope a repo.
