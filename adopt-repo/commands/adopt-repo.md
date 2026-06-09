---
description: >
  Onboard an upstream OSS repo into the dev workspace end to end: create a private
  <name>-dev mirror of it, give the mirror its own altien-main development trunk
  (main stays a pristine upstream mirror), vendor the explorer skills into the
  repo and push them so Claude in the cloud can build the documentation islands,
  pause for that cloud build, then register the new islands on the docs launcher.
  Thin alias for the adopt-repo skill — a sequencer over mirror-repo, fork-trunk,
  the explorer skills, and rescan-docs.
argument-hint: "<upstream-git-url> [dest-name]"
---

Invoke the **adopt-repo** skill to onboard a new upstream OSS repository into the
`C:\Data\Projects\Mike` dev workspace, following its ordered playbook
(derive + confirm names → private mirror → development trunk → vendor explorer
skills + push → PAUSE for the cloud island build → pull islands + register on the
launcher).

Arguments: `$ARGUMENTS`

- First argument (required): the upstream clone URL (e.g. `https://github.com/owner/repo.git`).
- Second argument (optional): the destination name. If omitted, default to the
  upstream repo name plus `-dev` (e.g. `cr_oss` ⇒ `cr_oss-dev`); confirm with the
  user before creating anything.

This skill is a **sequencer**: each act is owned by a component skill
(`/mirror-repo`, `/fork-trunk`, `/repository-explorer`, `/build-explorer`,
`/build-atlas`, `/rescan-docs`). adopt-repo derives the inputs, runs them in the
right order, and owns only the skill-vendoring step and the cloud handoff — it
does not re-implement any component skill. The order matters; do not reorder. It
pauses after pushing the vendored skills so the heavy island generation can be
offloaded to Claude in the cloud, then resumes to register the results.
