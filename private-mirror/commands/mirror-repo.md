---
description: >
  Set up the current empty directory as a private mirror of a public GitHub repo
  that you can pull updates from but never push to — like a fork, but private.
  Disables GitHub Actions before the first push, rewires remotes so pushes go to
  your private repo only, and physically disables pushing to upstream. Thin alias
  for the mirror-repo skill.
argument-hint: "<upstream-git-url> <my-org/my-repo>"
---

Invoke the **mirror-repo** skill to turn the current (empty) directory into a
private mirror of a public GitHub repository, following its ordered playbook
(pre-flight → disable Actions BEFORE pushing → clone & rewire remotes → push to
the private repo → verify → print a sync cheat-sheet).

Arguments: `$ARGUMENTS`

- First argument: the upstream clone URL (e.g. `https://github.com/owner/repo.git`).
- Second argument: your private destination as `owner/repo` (e.g. `my-org/my-repo`).

If either argument is missing, ask for it before starting. The order of the
skill's steps matters — in particular, Actions must be disabled before the first
push, or inherited workflows will run, fail, and email the owner.
