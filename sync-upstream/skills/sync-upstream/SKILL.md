---
name: sync-upstream
description: >
  Pull upstream changes into a dev-workspace repo set up by mirror-repo,
  fork-trunk, or adopt-repo — fast-forward the pristine main from upstream,
  land those commits on the development trunk via a reviewable PR, then
  reconcile any vendored documentation islands (Repository Explorer, Skills &
  Prompts Explorer, The Atlas) with the changed code. Use when the user says
  "update from upstream", "sync with the original repo", "pull upstream
  changes", "catch this fork up", "refresh the docs after syncing", or runs
  /sync-upstream.
argument-hint: "[--no-docs]"
---

# Catch a dev-workspace repo up with upstream, then reconcile its docs

The routine follow-up to `/mirror-repo`, `/fork-trunk`, and `/adopt-repo`: once
a repo has been mirrored into the dev workspace, this is how you periodically
pull in what changed upstream **and** keep any vendored documentation islands
honest about the code that moved.

## This skill is a sequencer for doc reconciliation

Steps 1–3 (git sync) are this skill's own work. Step 5 (doc reconciliation) is
**owned by the component explorer skills** — `/repository-explorer --update`,
`/update-explorer`, `/build-atlas --update`. This skill only detects which
islands exist in the repo and hands off to them; it does not reimplement their
update logic or invent a parallel diffing mechanism.

**Order matters.** Sync `main` before merging onto the trunk before
reconciling docs — the doc tools read the working tree, so they need the new
code checked out first.

## Prerequisites

- The repo has an `upstream` remote (set up by `/mirror-repo`, or `/fork-trunk`
  / `/adopt-repo`). If there is no `upstream` remote, stop and point the user
  at `/mirror-repo`.
- `gh auth status` works. Mind the token-shadowing gotcha from mirror-repo/
  fork-trunk: a `GITHUB_TOKEN`/`GH_TOKEN` env var can shadow the keyring
  credential and make `gh api`/`gh pr` 404 on a private repo — clear them for
  the command if that happens.

## 1. Detect the repo's shape

`git remote -v` — confirm `origin` (yours) and `upstream` (canonical, push
disabled or absent). Then work out which setup this is:

- **Fork-trunk model** — `git symbolic-ref refs/remotes/origin/HEAD` names a
  branch other than `main` (the trunk, e.g. `altien-main`), and a separate
  `main` branch exists that tracks `upstream`. This is what `/fork-trunk` and
  `/adopt-repo` leave behind.
- **Plain-mirror model** — the default branch *is* the branch you sync
  directly (whatever `/mirror-repo` left as the default, without a
  `/fork-trunk` on top). There's no separate pristine `main`.

If it's ambiguous, ask rather than guess — the two models diverge from here.

## 2. Fast-forward `main` (or the default branch) from upstream

```
git fetch upstream
```

Find upstream's default branch name (don't assume `main`): `git remote show
upstream` or `git symbolic-ref refs/remotes/upstream/HEAD`.

- **Fork-trunk model:**
  ```
  git switch main
  git merge --ff-only upstream/<upstream-default>
  ```
  If the fast-forward fails, `main` has local-only commits, which violates the
  fork-trunk invariant — **STOP**, surface it, do not force. That work
  belongs on the trunk; help the user move it there and reset `main`
  deliberately, the same way `/fork-trunk` §2 handles it.
- **Plain-mirror model:**
  ```
  git switch <default-branch>
  git merge upstream/<upstream-default>
  ```
  This can produce real conflicts since it's the working branch — resolve
  them with the user, never discard local changes to force the merge through.

Push the result: `git push origin main` (or the default branch).

## 3. Fork-trunk model only: land the new commits on the trunk

```
git fetch origin
git log TRUNK..main --oneline
```

- Nothing to bring over → report "trunk already up to date with main" and
  skip to step 4.
- Something to bring over → branch off the trunk, merge `main` in, resolve any
  conflicts (real conflicts should only turn up in files upstream and the
  trunk both touched — vendored `.claude/` skills and generated `docs/`
  islands are dev-only additions upstream doesn't have, so they merge
  cleanly):
  ```
  git switch -c sync/upstream-<yyyy-mm-dd> TRUNK
  git merge main
  git push -u origin sync/upstream-<yyyy-mm-dd>
  gh pr create --base TRUNK --title "Sync upstream" --body-file <heredoc file>
  ```
  Open a PR rather than pushing straight to the trunk — unlike the vendoring
  push in `/adopt-repo` (which only ever adds files upstream can't touch),
  this merge can carry arbitrary upstream code changes and deserves a normal
  review pass. Tell the user the PR is ready and **wait** for them to merge it
  before continuing — the doc tools in step 5 need the merged code on disk.

## 4. Detect vendored documentation islands

Check for what `/adopt-repo` Phase 2 vendors, using the same mapping:

| Island | Skill dir | Docs dir |
|--------|-----------|----------|
| Repository Explorer | `.claude/skills/repository-explorer/` | `docs/repository-explorer/` |
| Skills & Prompts Explorer | `.claude/skills/build-explorer/` | `docs/explorer/` |
| The Atlas | `.claude/skills/atlas-explorer/` | `docs/atlas/` |

List which are present. If none are present, report "no vendored explorer
skills found — nothing to reconcile" and stop; this repo predates
`/adopt-repo` or its docs live elsewhere. If `--no-docs` was passed, skip this
section and step 5 entirely — the user only wanted the git sync.

## 5. Hand off doc reconciliation to the cloud, then PAUSE

Generation is heavy, same as `/adopt-repo` Phase 3 — offload it to Claude in
the cloud against the now-synced trunk. Print a handoff block covering only
the islands actually present, then **stop and wait**:

```
Repo:   <origin URL>   (branch: <TRUNK or default>, now synced with upstream)
Open this repo in Claude (cloud) on that branch and run, for each island present:

  /repository-explorer --update   → refreshes docs/repository-explorer/
  /update-explorer                 → refreshes docs/explorer/ (never /build-explorer again — that's a fresh build, not a refresh)

The Atlas (docs/atlas/) is self-updating: its mechanical index rebuilds live
on server start / reindex, so ordinary code drift needs no rebuild. Only run
  /build-atlas --update
if curated journeys or diagrams need a refresh for genuinely new authored
content.

Let the cloud session commit and push the refreshed docs/ islands.
Then come back here and say "pull the synced docs" to finish.
```

## 6. Resume — pull the refreshed docs back

When told the cloud session pushed:

```
git pull origin <TRUNK or default>
git log --stat -1   # see what the doc commit touched
```

Remind the user to restart any locally-running Atlas server so it picks up
the fresh index.

## Verify & report

- `main` still equals `upstream/<upstream-default>` (fork-trunk model only —
  confirms it stayed pristine).
- The sync PR's status (open, awaiting review, or merged).
- Which islands were reconciled, which were skipped, and why (absent, or
  `--no-docs`).
- A short cheat-sheet so this becomes routine:
  ```
  # next time:
  /sync-upstream
  ```
