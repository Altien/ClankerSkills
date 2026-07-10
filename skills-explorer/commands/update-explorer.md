---
description: Refresh an existing repository-owned Skills & Prompts Explorer, preserving historical artifacts and publishing a verified, logged catalog bundle.
argument-hint: "[--dry-run] [target path, default: repo root]"
---

Invoke the **update-explorer** skill for the existing `docs/explorer/` in this repository.

Arguments: `$ARGUMENTS`

- Re-import the current updater, schemas, and reusable scanner improvements.
- Run discovery and exact body extraction here in the source repository.
- Stop and discuss missing bodies, ambiguous coverage, or unexplained regressions.
- Review only added/updated/restored curation; retain removals as historical records.
- Publish and verify the catalog bundle, checksum, state, verification report, and
  hash-chained update log; then update the human Doc build log.
- `--dry-run`: stop after coverage review and `catalog_bundle.py plan`; do not publish or
  commit. Repository-local generators may leave preview changes under `docs/explorer/` for
  inspection.
