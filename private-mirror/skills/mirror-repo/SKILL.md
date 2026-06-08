---
name: mirror-repo
description: >
  Set up the current empty directory as a private mirror of a public GitHub repo
  — like a fork, but private: pull updates from upstream but never push to it.
  Disables GitHub Actions before the first push (so inherited workflows don't run,
  fail, and email the owner), rewires remotes so plain push/pull only touch your
  private copy, and physically disables pushing to upstream. Use when the user
  says "make a private mirror/fork of <repo>", "privately track an upstream repo",
  "mirror this public repo into my org", or runs /mirror-repo.
argument-hint: "<upstream-git-url> <my-org/my-repo>"
---

# Create a private mirror of a public GitHub repo

Turn the current (empty) directory into a private mirror of `UPSTREAM_URL` that
the user can pull updates from but **never push to** — like a fork, but private.

**The order of these steps matters.** Do not reorder. In particular, GitHub
Actions must be disabled *before* the first push.

## Inputs

- `UPSTREAM_URL` — the public repo's clone URL, e.g. `https://github.com/<owner>/<repo>.git`
- `MY_REPO` — the private destination as `<my-org>/<my-repo-name>`

If either is missing from the invocation, ask before starting.

## Environment gotchas (learned the hard way)

These bite on Windows / `gh` setups where a token is present in the environment:

- **`GITHUB_TOKEN` / `GH_TOKEN` env vars shadow the keyring credential.** A
  fine-grained PAT in the environment may lack access to the destination repo and
  cause `repo create`, `gh api`, and `git push` to fail with "not found" /
  "does not have the correct permissions". If that happens, clear them for the
  command: in PowerShell prefix with `$env:GITHUB_TOKEN = $null; $env:GH_TOKEN = $null;`
  so `gh`/git fall back to the keyring login. Verify scopes with `gh auth status`.
- **`gh api` booleans need `-F`, not `-f`.** `-f enabled=false` sends the *string*
  `"false"` and 422s. Use `-F enabled=false` to send a real boolean.

## 1. Pre-flight

- Confirm the current directory is empty and `gh auth status` works.
- If `MY_REPO` does not exist yet, create it: `gh repo create MY_REPO --private`
- It must be **EMPTY** (no README/license/gitignore auto-init). Check with
  `gh repo view MY_REPO --json isEmpty,defaultBranchRef`. If it already has
  commits, **stop and ask the user** — do not push over existing history.

## 2. Disable GitHub Actions BEFORE pushing anything

Workflows inherited from upstream will run (and fail, and email the owner) the
moment code is pushed. Disable Actions first:

- Try: `gh api -X PUT repos/MY_REPO/actions/permissions -F enabled=false`
  then confirm with `gh api repos/MY_REPO/actions/permissions` (expect
  `"enabled": false`).
- If that 404s (fine-grained token without Administration scope), **STOP** and
  tell the user to flip it manually: repo **Settings → Actions → General →
  Disable actions**, and wait for confirmation before pushing.
- Fallback only if the user refuses the setting: delete `.github/workflows/` in a
  commit on the default branch before the first push (note: this diverges from
  upstream and can conflict on future merges — prefer the setting).

## 3. Clone and rewire remotes

```
git clone UPSTREAM_URL .
git remote rename origin upstream
git remote add origin https://github.com/MY_REPO.git
git remote set-url --push upstream DISABLED_NO_PUSH_TO_UPSTREAM
```

Detect the default branch (don't assume `main` vs `master`):
`git branch --show-current`.

## 4. Push to the private repo

- Push the default branch with tracking: `git push -u origin <default-branch>`
- **Ask the user** whether to also mirror the other upstream branches and tags.
  (Mirroring everything is a fuller copy, but pushing many branches can trigger
  org automations — e.g. auto-PR bots — and creates noise. Default-branch-only
  is usually enough for reading/exploring the code.) Show them what exists first:
  `git branch -r` and `git tag`.
- If yes: push each `refs/remotes/upstream/<b>` to `refs/heads/<b>` on origin
  (skip `HEAD`), then `git push origin --tags`.

## 5. Verify

- `git remote -v` shows: `origin` = the private repo (fetch + push),
  `upstream` = the original (fetch only, push = `DISABLED_NO_PUSH_TO_UPSTREAM`).
- `git push upstream <default-branch> --dry-run` must **FAIL** with
  "does not appear to be a git repository" — that failure is the success signal.
- `git branch -vv` shows the default branch tracking `origin`.
- Confirm Actions are disabled (that step 2 actually took effect).

## 6. Report back

Print a short cheat-sheet for syncing from upstream later:

```
git fetch upstream
git merge upstream/<default-branch>   # while on <default-branch>
git push origin <default-branch>
```

Remind the user that plain `git push` / `git pull` go to their **private repo
only** — pushing to upstream is impossible until its push URL is deliberately
reset.
