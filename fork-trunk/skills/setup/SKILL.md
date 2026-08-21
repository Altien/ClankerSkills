---
name: setup
description: >
  Turn an existing GitHub fork into a clean two-branch setup: a fork-specific
  default development branch (e.g. <org>-main) that all your work lands on, while
  `main` stays a pristine mirror of upstream you only ever sync from. Creates the
  trunk off the upstream-synced main, sets it as the GitHub default AND the local
  default, routes unmerged local work onto it via PR (never onto main), and can
  disable GitHub Actions on the fork. Use when the user says "make the repo
  default to <branch>", "give this fork its own main", "keep main tracking
  upstream and develop on a separate branch", "make sure our work goes on
  <branch> not main", or runs /fork-trunk:setup.
argument-hint: "[trunk-branch-name] [--disable-ci]"
---

# Give a fork its own default development branch

Take a repo that is already a **fork** (`origin` = your fork, `upstream` = the
canonical repo) and split its two roles onto two branches:

- **`main`** stays a **pristine mirror of `upstream/main`** — you only ever
  fast-forward it from upstream, never commit to it. This keeps merges from
  upstream conflict-free.
- **`TRUNK`** (the fork-specific default development branch, e.g. `altien-main`)
  is where **all** your fork's work lands, and it becomes both the GitHub default
  branch and the local default.

The result: clone the fork and you land on `TRUNK`; sync from upstream by
fast-forwarding `main`; your customizations never fight an upstream rebase.

**The order of these steps matters. Do not reorder.** In particular, never reset
or force-update `main` without first proving it carries no unmerged work, and
verify a branch is a strict ancestor before fast-forwarding it.

## Inputs

- `TRUNK` — the fork-specific default branch name. If not given, default to
  `<origin-owner>-main` (derive the owner from the `origin` URL — e.g. an
  `Altien/...` fork ⇒ `altien-main`) and **confirm with the user** before creating.
- `--disable-ci` (optional) — also disable GitHub Actions on the fork (§6).

## Environment gotchas (learned the hard way)

These bite on Windows / `gh` setups where a token is present in the environment:

- **`GITHUB_TOKEN` / `GH_TOKEN` env vars shadow the keyring credential.** A
  fine-grained PAT in the environment may lack access to a private fork and make
  `gh api` / `gh pr` / `gh repo view` fail with "Not Found" / 404. If that
  happens, clear it for the command so `gh` falls back to the keyring login:
  Bash `unset GITHUB_TOKEN GH_TOKEN`; PowerShell `$env:GITHUB_TOKEN=$null; $env:GH_TOKEN=$null`.
  Verify scopes with `gh auth status` (you want a token with `repo` + admin on
  the fork to change the default branch and Actions).
- **`gh api` booleans need `-F`, not `-f`.** `-f enabled=false` sends the *string*
  `"false"`; use `-F enabled=false` for a real boolean.
- **PR bodies with backticks/parens break bash `-b "..."`.** Write the body to a
  file with a quoted heredoc (`cat > /tmp/body.md <<'EOF' … EOF`) and pass
  `--body-file`, or use a PowerShell single-quoted here-string (`@'…'@`).
- **`git branch -f <b> origin/<b>` only fast-forwards safely when the local `<b>`
  is a strict ancestor** of `origin/<b>`. If it isn't, don't force — `git switch <b>`
  and `git pull` (or investigate the divergence).

## 1. Pre-flight — confirm it's a fork

- `git remote -v` — expect `origin` (your fork) **and** `upstream` (canonical).
  If there is **no `upstream`**, stop and ask: this skill assumes an existing
  fork. (To set up a fresh *private* mirror of a public repo, use `/private-mirror:mirror`.)
- Derive `OWNER/REPO` from the `origin` URL; default `TRUNK = <OWNER lowercased>-main`.
- `gh auth status` works (mind the token-shadowing gotcha above).
- Working tree is clean (`git status --short` empty) and note the current branch
  so you can return to it.

## 2. Keep `main` pristine; branch `TRUNK` off the upstream-synced `main`

- `git fetch origin && git fetch upstream`
- Confirm `main` is clean: `git rev-parse main origin/main upstream/main` should
  agree (or `git log upstream/main..main` is empty). **If `main` carries
  local-only commits, STOP** — that work belongs on `TRUNK`. Surface it and offer
  to move it (branch/cherry-pick onto `TRUNK`) and then reset `main` to
  `upstream/main`. Never silently discard or force-push `main`.
- If `TRUNK` does not exist yet, create it off `main` and push it:
  ```
  git branch TRUNK main
  git push origin TRUNK:TRUNK
  ```
  If it already exists on origin, just make sure local tracks it (§5).

## 3. Set the GitHub default branch to `TRUNK`

```
gh api -X PATCH repos/OWNER/REPO -f default_branch=TRUNK
gh repo view OWNER/REPO --json defaultBranchRef -q .defaultBranchRef.name   # expect TRUNK
```

## 4. Land local work on `TRUNK`, not `main`

The user's intent is usually "make sure our work is on `TRUNK`, not `main`."

- Find unmerged work: `git branch --no-merged TRUNK`, and for each candidate
  `git log --oneline origin/TRUNK..<branch>`.
- For each feature branch with real work: push it (`git push -u origin <branch>`)
  and open a PR **based on `TRUNK`**, then merge it:
  ```
  gh pr create --repo OWNER/REPO --base TRUNK --head <branch> --title "…" --body-file /tmp/body.md
  gh pr merge <#> --repo OWNER/REPO --merge
  ```
  (Prefer a PR over a direct push so the merge is reviewable; use the heredoc /
  `--body-file` trick for bodies with backticks.)
- Re-confirm `main` still carries nothing of yours: `git log --oneline upstream/main..main`
  should be empty.

## 5. Wire the local default to `TRUNK`

```
git fetch origin
git branch -f TRUNK origin/TRUNK              # FF only — see the gotcha; else: git switch TRUNK && git pull
git branch --set-upstream-to=origin/TRUNK TRUNK
git remote set-head origin TRUNK              # sets refs/remotes/origin/HEAD -> origin/TRUNK (the LOCAL default pointer)
```

`git remote set-head` is the step people miss: changing the default on GitHub
(§3) does **not** update your local `origin/HEAD`. Without it, `git`'s notion of
the default branch still points at the old one.

## 6. (Optional, `--disable-ci`) Disable GitHub Actions on the fork

A fork inherits upstream's workflows, which can run and fail noisily. To turn
**all** Actions off at the repo level (reversible, no commit, files untouched):

```
gh api -X PUT repos/OWNER/REPO/actions/permissions -F enabled=false
gh api repos/OWNER/REPO/actions/permissions          # expect "enabled": false
```

Tell the user this disables **every** workflow (CI, Release, Dependabot, etc.),
not just the build, and how to reverse it: repo **Settings → Actions → General**,
or `gh api -X PUT repos/OWNER/REPO/actions/permissions -F enabled=true`. If the
PATCH/PUT 404s (a fine-grained token without Administration scope), have the user
flip it in Settings instead. To disable only one workflow, use
`gh workflow disable "<name>" --repo OWNER/REPO`.

## 7. Verify and report

- `git remote -v` — `origin` = fork, `upstream` = canonical.
- `git symbolic-ref refs/remotes/origin/HEAD` → `refs/remotes/origin/TRUNK`.
- `gh repo view OWNER/REPO --json defaultBranchRef -q .defaultBranchRef.name` → `TRUNK`.
- `git branch -vv` — `TRUNK` tracks `origin/TRUNK`; the local checkout is wherever
  the user wants (often still a feature branch).
- `main` == `upstream/main` (still pristine).

Print a short cheat-sheet:

```
# sync main from upstream (never commit to main):
git fetch upstream && git switch main && git merge --ff-only upstream/main && git push origin main

# do work on the trunk:
git switch TRUNK            # the default; all PRs target this branch
```
