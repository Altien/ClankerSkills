---
name: sync
description: >
  Pull upstream changes into a dev-workspace repo set up by mirror-repo,
  fork-trunk, or adopt-repo — fast-forward the pristine main from upstream,
  land those commits on the development trunk via a reviewable PR, then
  reconcile any vendored documentation islands (Repository Explorer, Skills &
  Prompts Explorer, The Atlas) with the changed code. Use when the user says
  "update from upstream", "sync with the original repo", "pull upstream
  changes", "catch this fork up", "refresh the docs after syncing", or runs
  /sync-upstream:sync.
argument-hint: "[--no-docs]"
---

# Catch a dev-workspace repo up with upstream, then reconcile its docs

The routine follow-up to `/private-mirror:mirror`, `/fork-trunk:setup`, and `/adopt-repo:adopt`: once
a repo has been mirrored into the dev workspace, this is how you periodically
pull in what changed upstream **and** keep any vendored documentation islands
honest about the code that moved.

## This skill is a sequencer for doc reconciliation

Steps 1–3 (git sync) are this skill's own work. Step 5 (doc reconciliation) is
**owned by the component explorer skills** — `/repository-explorer:build --update`,
`/skills-explorer:update`, `/atlas-explorer:build --update`. This skill only detects which
islands exist in the repo and hands off to them; it does not reimplement their
update logic or invent a parallel diffing mechanism.

**Order matters.** Sync `main` before merging onto the trunk before
reconciling docs — the doc tools read the working tree, so they need the new
code checked out first.

## Prerequisites

- The repo has an `upstream` remote (set up by `/private-mirror:mirror`, or `/fork-trunk:setup`
  / `/adopt-repo:adopt`). If there is no `upstream` remote, stop and point the user
  at `/private-mirror:mirror`.
- `gh auth status` works. Mind the token-shadowing gotcha from mirror-repo/
  fork-trunk: a `GITHUB_TOKEN`/`GH_TOKEN` env var can shadow the keyring
  credential and make `gh api`/`gh pr` 404 on a private repo — clear them for
  the command if that happens.

## 1. Detect the repo's shape

`git remote -v` — confirm `origin` (yours) and `upstream` (canonical, push
disabled or absent). Then work out which setup this is:

- **Fork-trunk model** — `git symbolic-ref refs/remotes/origin/HEAD` names a
  branch other than `main` (the trunk, e.g. `altien-main`), and a separate
  `main` branch exists that tracks `upstream`. This is what `/fork-trunk:setup` and
  `/adopt-repo:adopt` leave behind.
- **Plain-mirror model** — the default branch *is* the branch you sync
  directly (whatever `/private-mirror:mirror` left as the default, without a
  `/fork-trunk:setup` on top). There's no separate pristine `main`.

If it's ambiguous, ask rather than guess — the two models diverge from here.

**The pristine branch isn't always called `main`.** Some forks keep upstream's
default under its own name — e.g. `Altien/DocHaus2Dev` keeps `dochaus` as the
pristine mirror of `upstream/dochaus` and develops on `altien-main`. Call that
branch `MIRROR` (the local branch whose upstream is `upstream/<upstream-default>`);
wherever this skill says `main`, read `MIRROR`.

**Worktrees.** `MIRROR` and the trunk may be checked out in different
worktrees (`git worktree list`). `git switch` fails on a branch checked out
elsewhere — run that step from the worktree that holds it, or update it
without a checkout: `git fetch upstream <upstream-default>:MIRROR` (fast-forward
only).

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
  deliberately, the same way `/fork-trunk:setup` §2 handles it.
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
  push in `/adopt-repo:adopt` (which only ever adds files upstream can't touch),
  this merge can carry arbitrary upstream code changes and deserves a normal
  review pass. Tell the user the PR is ready and **wait** for them to merge it
  before continuing — the doc tools in step 5 need the merged code on disk.

## 4. Detect documentation islands

Detect islands by their **docs dir on the trunk**, not by vendored skills —
islands can exist without `.claude/skills/` (built from locally installed
plugins):

| Island | Docs dir | Update command |
|--------|----------|----------------|
| Repository Explorer | `docs/repository-explorer/` | `/repository-explorer:build --update` |
| Skills & Prompts Explorer | `docs/explorer/` | `/skills-explorer:update` |
| The Atlas | `docs/atlas/` | `/atlas-explorer:build --update` |

List which are present. If none are present, report "no documentation islands
found — nothing to reconcile" and stop. If `--no-docs` was passed, skip this
section and step 5 entirely — the user only wanted the git sync.

**Where the update runs:** if the explorer plugins are installed locally (they
appear as `repository-explorer:*`, `skills-explorer:*`, `atlas-explorer:*` in
the skill list), run the updates locally in a **fresh session** on the trunk —
no vendoring or cloud needed. Otherwise use the cloud handoff in step 5, which
needs the skills vendored under `.claude/` (see `/adopt-repo:adopt` Phase 2).

**The Atlas refuses to start after doc churn.** Its config has no catch-all
category and validates curation, so an upstream merge that adds or deletes
`.md` files breaks it ("docs matched no category rule" / "curated summaries
for unknown docs"). Fix it right after the merge, before anything else: add a
`category_rules` entry per new doc in `docs/atlas/atlas.config.yaml`, and
drop entries for deleted docs from `docs/atlas/curated/*.yaml` (check
`git log -1 -- <deleted doc>` — if upstream dropped a pipeline step, drop its
diagram node too). Confirm with a start-up: `python docs/atlas/app.py` or the
launcher build.

**Mermaid.** All three islands render mermaid at current plugin versions
(repository-explorer ≥0.4.0, skills-explorer ≥0.4.1, atlas-explorer ≥0.3.2).
An island built by an older plugin version doesn't pick it up from a sync —
run its update command to re-import the tooling. After an update, the static
explorers must ship `assets/mermaid.min.js`.

## 5. Hand off doc reconciliation to the cloud, then PAUSE

(Skip to the local route from step 4 when the plugins are installed here.)
Generation is heavy, same as `/adopt-repo:adopt` Phase 3 — offload it to Claude in
the cloud against the now-synced trunk. Print a handoff block covering only
the islands actually present, then **stop and wait**:

```
Repo:   <origin URL>   (branch: <TRUNK or default>, now synced with upstream)
Open this repo in Claude (cloud) on that branch and run, for each island present:

  /repository-explorer:build --update   → refreshes docs/repository-explorer/
  /skills-explorer:update                 → refreshes docs/explorer/ (never /skills-explorer:build again — that's a fresh build, not a refresh)

The Atlas (docs/atlas/) is self-updating: its mechanical index rebuilds live
on server start / reindex, so ordinary code drift needs no rebuild. Only run
  /atlas-explorer:build --update
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

## 7. Republish to the web

If the repo's islands are registered in the docs launcher
(`C:\Data\Projects\Mike\MikeForxExplorer\registry.json`, matched by the
first segment of each entry's `dir` — the checkout folder name), republish
from `MikeForxExplorer/`:

```
python -m build --repo <checkout-folder> --publish
python -m build --hub --publish        # only if registry names/entries changed
```

This is the launcher's `/publish-docs` skill — follow it for prerequisites
(wrangler login, Atlas deps) and the Cloudflare Access reminder: a hostname
deployed for the first time is **public** until added to the Access app.

## Verify & report

- `main` still equals `upstream/<upstream-default>` (fork-trunk model only —
  confirms it stayed pristine).
- The sync PR's status (open, awaiting review, or merged).
- Which islands were reconciled, which were skipped, and why (absent, or
  `--no-docs`).
- The live `https://<project>.pages.dev` URL if republished (step 7).
- A short cheat-sheet so this becomes routine:
  ```
  # next time:
  /sync-upstream:sync
  ```
