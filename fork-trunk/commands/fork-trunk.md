---
description: >
  Turn an existing GitHub fork into a clean two-branch setup: a fork-specific
  default development branch (e.g. <org>-main) that all your work lands on, while
  main stays a pristine mirror of upstream you only sync from. Sets the new branch
  as the GitHub + local default, routes unmerged local work onto it via PR (never
  onto main), and can disable GitHub Actions on the fork. Thin alias for the
  fork-trunk skill.
argument-hint: "[trunk-branch-name] [--disable-ci]"
---

Invoke the **fork-trunk** skill to establish a fork-specific default development
branch on the current repository's `origin` fork, following its ordered playbook
(pre-flight: confirm it's a fork → keep `main` pristine and branch the trunk off
the upstream-synced `main` → set it as the GitHub default → land unmerged local
work on it via PR, never on `main` → wire the local default + tracking →
optionally disable CI → verify and print a sync cheat-sheet).

Arguments: `$ARGUMENTS`

- First argument (optional): the trunk branch name. If omitted, default to
  `<origin-owner>-main` (e.g. an `Altien/...` fork ⇒ `altien-main`); confirm the
  name with the user before creating it.
- `--disable-ci` (optional): also turn off GitHub Actions on the fork.

This skill assumes the repo is already a **fork** — `origin` is your fork and
`upstream` is the canonical repo. If there is no `upstream` remote, stop and ask;
to set up a fresh private mirror of a public repo instead, use `/mirror-repo`.
The order of steps matters — in particular, never reset or force-update `main`
without first checking it carries no unmerged work.
