---
name: update-explorer
description: Update an existing repository-owned Skills & Prompts Explorer from current source, re-import current Explorer tooling, pre-extract exact bodies, review changed curation, preserve removed artifacts as history, publish a verified bundle, and append an auditable update log. Use for every refresh after build-explorer.
---

# Update a Skills & Prompts Explorer

Refresh an existing `docs/explorer/` in the source repository. The source repository owns
extraction; downstream catalogs consume only its verified `catalog.bundle.json`.

If no Explorer exists, stop and use `build-explorer`. If the existing Explorer cannot
extract an artifact exactly or its coverage is ambiguous, stop and discuss that gap with
the user rather than shifting discovery into the downstream library.

Let `SELF = ${CLAUDE_PLUGIN_ROOT}/skills/update-explorer`,
`BUILD = ${CLAUDE_PLUGIN_ROOT}/skills/build-explorer`, and
`DEST = <target repository>/docs/explorer`.

## Model delegation boundary

Delegate bounded command execution to `explorer-update-worker`, which is configured with
`model: haiku`. Use it for mechanical preflight, build/assemble/verify/plan commands, an exact
parent-approved publish command, and deterministic import execution. Give it one repository,
one phase, exact arguments, and an exact changed-file allowlist; require its structured JSON result.

Keep all judgment in the primary model: discovery-adapter changes, dirty-tree handling, coverage
acceptance, curation, quality assessment, historical/removal review, publish summaries, commit
scope, and import approval. The worker may not choose `--accept-coverage-change` or
`--reviewed-unchanged`; the primary must supply those exact flags after review. If model routing is
unavailable, say so rather than claiming that an ordinary subagent is the smaller worker.

## 1. Preflight and baseline

Work from the source repository, on a feature branch. For a v0.3+ Explorer, read:

- `DEST/catalog/state.json`, `catalog.bundle.json`, and the last log event;
- `DEST/explorer-manifest.json`, `README.md`, and repository agent instructions;
- current `DEST/build_explorer.py` adapters and current source conventions.

For a legacy Explorer that has a manifest/data but no catalog state, treat this as its
catalog bootstrap: install the current tools, add exact `_content` extraction to every
adapter, run a full coverage review, and publish sequence 1. Existing Git history may be
used to derive `content_commit`, but artifacts removed before this first snapshot cannot be
reconstructed automatically; report that limit and discuss any desired backfill.

Do not publish while artifact source files are dirty. Confirm that the last verified commit
is an ancestor of HEAD. Never delete a previously exported record merely because current
discovery no longer finds it.

## 2. Re-import improvements from the installed skill

Refresh `SELF/scripts/catalog_bundle.py`, `SELF/schemas/*.json`, and
`SELF/references/CATALOG_SCHEMA.md` into `DEST/tools/`, `DEST/schemas/`, and
`DEST/CATALOG_SCHEMA.md` before each update. These files are copied verbatim and checked
into the source repository, so tool/schema upgrades are explicit in its diff.

Compare `DEST/build_explorer.py` with the current
`BUILD/templates/build_explorer.skeleton.py`. Port reusable scanner improvements while
preserving repository-specific adapters; never overwrite the adapted builder wholesale.
Record the scanner version and the tool/schema changes in the update summary. If the
installed skill adds a new relevant convention or artifact kind, extend the repository
adapter and tests during this update.

## 3. Re-extract in the source repository

Run the repository's own Explorer programs:

```text
python docs/explorer/build_explorer.py
python docs/explorer/assemble_data.py
node docs/explorer/verify.cjs
python docs/explorer/tools/catalog_bundle.py plan
```

The builder must emit exact bodies to `catalog/discovered.json` at current HEAD. Shared-
registry adapters should also emit a per-artifact `content_commit` when whole-file Git
history cannot identify the body-changing commit. Review the
coverage diff as carefully as the artifact diff: languages/profiles, generic fallback,
skips, warnings, candidate counts, and missing bodies. A newly unsupported/skipped source,
unexplained count drop, duplicate ID, or `missing_content_ids` is a blocking Explorer defect.

## 4. Review the delta

Use the plan's `added`, `updated`, `restored`, and `historical` sets.
The plan also reports `stale_curated` and coverage hashes; planning reports these review
requirements but publication enforces them.

- Author assessments and workflow graphs for additions and restorations.
- Re-read updated bodies. Change an assessment when behavior changed and a graph when the
  process changed.
- If existing curation remains accurate after a wording-only body change, pass
  `--reviewed-unchanged <artifact-id>` and explain the judgment in the summary. This audit
  acknowledgment is logged; do not make a meaningless edit merely to satisfy a timestamp.
- Leave removals in the bundle as `historical`. Preserve their last exact body, curation,
  content hash, and immutable URL pinned to their last content commit.
- Describe questionable source quality honestly. Do not silently improve, endorse, or
  discard a weak skill (for example, one with shallow or unsafe instructions).

For large deltas, delegate bounded artifact reviews separately and integrate their JSON fragments
only after source-grounding and validation checks pass. Do not use the mechanical Haiku worker for
authored quality judgments.

After editing any `data/*.json`, rerun:

```text
python docs/explorer/assemble_data.py
node docs/explorer/verify.cjs
python docs/explorer/tools/catalog_bundle.py plan
```

## 5. Publish and log

Publish only after the Explorer and authored fragments verify:

```text
python docs/explorer/tools/catalog_bundle.py publish \
  --summary "What changed and why; coverage/tool changes; review decisions." \
  --accept-coverage-change
python docs/explorer/tools/catalog_bundle.py verify
```

Add one newest-first entry to `DEST/README.md` under `## Doc build log`, including the
commit range, artifact delta, coverage changes, tool/scanner version, and concise rationale.
The machine report is `catalog/update-log.jsonl`: append-only, hash-chained, content-addressed,
and checked into the source repository with the bundle/checksum/verification/state files.
A repeated run at the same HEAD must not append a duplicate event.
Omit `--accept-coverage-change` when the plan says coverage is unchanged. When it is changed,
use the flag only after explaining the profiles/skips/warnings/candidate delta in the summary.

Run JSON validation, Python compilation/tests, `node --check`, `verify.cjs`, catalog verify,
and a browser smoke test proportionate to UI changes. Commit only `docs/explorer/` files on
the feature branch after all checks pass. Do not open a PR without confirmation.

## Downstream boundary

Downstream importers may accept only a bundle whose checksum, source-provenance receipt,
content hashes, immutable URLs, schema shape, and update-log chain verify. The normal
`catalog_bundle.py verify` action is bundle-only. Importers must not crawl source code,
manifests, or Git history. `active` records describe current discovery; `historical` records
remain in the library and are not automatic removal instructions.
