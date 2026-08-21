---
description: >
  Pull upstream changes into a dev-workspace repo set up by mirror-repo,
  fork-trunk, or adopt-repo, land them on the development trunk via a
  reviewable PR, and reconcile any vendored documentation islands
  (Repository Explorer, Skills & Prompts Explorer, The Atlas) with the
  changed code. Thin alias for the sync-upstream skill.
argument-hint: "[--no-docs]"
---

Invoke the **sync-upstream** skill to catch the current repository up with its
`upstream` remote, following its ordered playbook (detect fork-trunk vs
plain-mirror shape → fast-forward `main` from upstream → land those commits on
the development trunk via PR → detect vendored explorer-skill islands →
PAUSE and hand off doc reconciliation to Claude in the cloud → resume once
pushed and pull the refreshed docs back).

Arguments: `$ARGUMENTS`

- `--no-docs` (optional): only perform the git sync (steps 1–3); skip
  detecting and reconciling documentation islands entirely.

This skill assumes the repo already has an `upstream` remote, i.e. it was set
up by `/mirror-repo`, `/fork-trunk`, or `/adopt-repo`. If there is no
`upstream` remote, stop and point the user at `/mirror-repo`. It is a
**sequencer** for the doc-reconciliation step — it detects which islands are
present and hands off to their own update modes (`/repository-explorer
--update`, `/update-explorer`, `/build-atlas --update`) rather than
reimplementing them. The order matters; do not reorder, and never push a
merge of upstream code straight to the trunk without a reviewable PR.
