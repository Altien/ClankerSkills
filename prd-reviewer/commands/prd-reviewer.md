---
description: >
  Build a self-contained, static review harness for ONE PRD / design / epic: a
  Markdown browser scoped to a single PRD folder plus the source it references
  (driven by a referenced-files.txt list in the PRD folder), with a quiet
  commenting layer — panel closed by default, right-click a selection to comment,
  inline marker on commented text. Thin alias for the prd-reviewer skill.
argument-hint: "[--no-comments] <PRD folder, e.g. docs/JIRA/JIRA-1855>"
---

Invoke the **prd-reviewer** skill to build a PRD Reviewer for the given PRD folder,
following its phased playbook (identify the PRD folder + its referenced source →
write/refresh `<PRD_DIR>/referenced-files.txt` → copy the kit into `<PRD_DIR>/review/`
→ set `PRD_DIR`, branding, `keyDocs`, and `repoRoot` depth → generate the manifest →
verify to zero failures → write the README → commit in place on the current branch).

Arguments: `$ARGUMENTS`

- The argument is the **PRD folder** to review (e.g. `docs/JIRA/JIRA-1855`). Only that
  folder's Markdown plus the source listed in `<PRD_DIR>/referenced-files.txt` is
  indexed — never the whole repo.
- `--no-comments`: ship a read-only browser (disable the review/commenting layer).
- Commenting is quiet by design: the panel stays closed until opened; select text and
  right-click to comment; commented passages get an inline 💬 marker.
