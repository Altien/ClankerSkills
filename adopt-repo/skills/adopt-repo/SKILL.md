---
name: adopt-repo
description: >
  Onboard an upstream OSS repository into the dev workspace end to end. Creates a
  private <name>-dev mirror of the upstream, gives it an altien-main development
  trunk (main stays a pristine upstream mirror), vendors the explorer skills into
  the repo and pushes them so Claude in the cloud can build the documentation
  islands, pauses for that cloud build, then pulls the islands back and registers
  them on the docs launcher. Use when the user says "onboard this OSS repo",
  "adopt <repo> into the dev workspace", "mirror and document a new upstream",
  "set up a -dev repo for <url>", or runs /adopt-repo. This is a SEQUENCER over
  mirror-repo, fork-trunk, the explorer skills, and rescan-docs — it does not
  re-implement them.
argument-hint: "<upstream-git-url> [dest-name]"
---

# Adopt an upstream OSS repo into the dev workspace

Take a public upstream repo and bring it fully into the
`C:\Data\Projects\Mike` workspace: a private development mirror, its own work
trunk, the explorer skills vendored in so the cloud can document it, and an entry
on the docs launcher dashboard once the islands are built.

## This skill is a sequencer, not a re-implementation

Each act below is **owned by a component skill**. adopt-repo's only original work
is Phase 0 (derive + confirm), Phase 2 (vendor the explorer skills), and Phase 3
(the cloud handoff). Everywhere else, **invoke the component skill and let it run
its own ordered playbook** — do not copy or paraphrase its steps here, and do not
invent parallel mechanisms for its edge cases (the component skill already handles
them, including the `GITHUB_TOKEN`/`GH_TOKEN` shadowing gotchas on Windows). If a
component skill stops and asks something, relay it to the user.

The order matters. **Do not reorder.** Mirror before trunk before vendoring before
the cloud build before registration.

## Prerequisites

- These plugins enabled at the desktop/profile level: `private-mirror`,
  `fork-trunk`, `repository-explorer`, `skills-explorer`, `atlas-explorer`. If any
  is missing, stop and ask the user to `claude plugin install <name>@clanker-skills`
  and restart.
- The `rescan-docs` workspace skill (lives in `C:\Data\Projects\Mike\.claude`).
- `gh auth status` works with `repo` + admin scope on the destination org.

## Inputs & derivation

- `UPSTREAM_URL` (required) — the public clone URL, e.g. `https://github.com/thepranky/cr_oss`.
- `DEST_NAME` (optional) — defaults to `<upstream repo name>-dev` (e.g. `cr_oss` ⇒ `cr_oss-dev`).

Derive and **confirm all of these with the user before doing anything**:

| Value | Derivation | Example |
|-------|------------|---------|
| `REPO` | basename of the upstream URL, minus `.git` | `cr_oss` |
| `DEST_NAME` | `REPO` + `-dev`, unless overridden | `cr_oss-dev` |
| `TARGET_DIR` | `C:\Data\Projects\Mike\<DEST_NAME>` | `C:\Data\Projects\Mike\cr_oss-dev` |
| `MY_REPO` | `Altien/<DEST_NAME>` | `Altien/cr_oss-dev` |
| `TRUNK` | `altien-main` | `altien-main` |

## Phase 0 — Pre-flight & resume detection

- `gh auth status` (let the component skills handle token shadowing if it bites).
- Ensure `TARGET_DIR` exists and is **empty**. Create it if missing. The
  convention is that an empty staging dir already sits in the workspace.
- **Resume detection** — if `TARGET_DIR` is *not* empty and already a git repo,
  inspect it instead of starting over:
  - origin = `MY_REPO`, `upstream` present, trunk exists, `.claude/skills/`
    vendored ⇒ Phases 1–2 are done; ask whether to jump to Phase 3 (re-print the
    handoff) or Phase 4 (islands already built in the cloud → register them).
  - Never re-mirror or force-push over an existing dev repo.
- `cd` into `TARGET_DIR` — the mirror step requires the current directory to be
  the (empty) target.

## Phase 1 — Private mirror

Invoke **`/mirror-repo`** with `<UPSTREAM_URL> <MY_REPO>`.

It will: create the private `MY_REPO` if needed, **disable GitHub Actions before
the first push**, clone, rewire remotes (`origin` = your private repo,
`upstream` = the public source with push physically disabled), push the default
branch, and verify. When it finishes you have: `origin` = `Altien/<DEST_NAME>`
(private), `upstream` = the public repo (fetch-only), Actions off.

This leaves exactly the remote shape fork-trunk expects (`origin` = your fork,
`upstream` = canonical), so the two compose cleanly.

## Phase 1b — Development trunk

Invoke **`/fork-trunk`** with `altien-main` as the trunk name.

It will: keep `main` a pristine mirror of `upstream/main`, branch `altien-main`
off it, set `altien-main` as both the GitHub and local default, and wire local
tracking. (Actions are already off from Phase 1, so `--disable-ci` is redundant —
omit it.) After this, a fresh clone lands on `altien-main`, and `main` is only
ever fast-forwarded from upstream.

All subsequent commits in this workflow land on **`altien-main`**, never `main`.

## Phase 2 — Vendor the explorer skills into the repo, then push

This is adopt-repo's own step. A Claude **cloud** session sees only the repo's
`.claude/` directory — not your desktop profile — so the explorer skills must
live *inside* the repo and be pushed before the cloud can run them.

1. Locate the ClankerSkills source `CS_SRC`. Prefer the local checkout at
   `C:\Data\Projects\Tools\ClankerSkills`. If it is absent, clone
   `https://github.com/Altien/ClankerSkills` to a temp dir and use that.
2. For each explorer — copy the **entire** skill subtree (SKILL.md + `kit/` +
   `reference/` + `templates/` + `examples/`) and its command alias, verbatim:

   | Plugin | Skill subtree → dest | Command → dest |
   |--------|----------------------|----------------|
   | `repository-explorer` | `…\repository-explorer\skills\repository-explorer\` → `TARGET_DIR\.claude\skills\repository-explorer\` | `…\commands\repository-explorer.md` → `TARGET_DIR\.claude\commands\repository-explorer.md` |
   | `skills-explorer` | `…\skills-explorer\skills\build-explorer\` → `TARGET_DIR\.claude\skills\build-explorer\` | `…\commands\build-explorer.md` → `TARGET_DIR\.claude\commands\build-explorer.md` |
   | `atlas-explorer` | `…\atlas-explorer\skills\atlas-explorer\` → `TARGET_DIR\.claude\skills\atlas-explorer\` | `…\commands\build-atlas.md` → `TARGET_DIR\.claude\commands\build-atlas.md` |

3. If the upstream repo already ships a same-named skill under `.claude/`, **do
   not clobber it** — warn the user and skip that one.
4. Commit on `altien-main` and push:
   ```
   git add .claude
   git commit -m "Vendor explorer skills for cloud island builds"
   git push origin altien-main
   ```

These pushes go **only** to the dev repo this skill just created — that is the
explicit intent of running `/adopt-repo`, so no extra confirmation is needed for
them (this is the one boundary the workspace's AGENTS.md caution is about).

## Phase 3 — Hand the island builds to the cloud, then PAUSE

The repository-explorer and skills-explorer (and optionally the Atlas) generation
is heavy; offload it to Claude in the cloud against the pushed repo. Print a
handoff block the user can act on, then **stop and wait** — do not proceed to
Phase 4 in this run unless the user says the islands are already built and pushed.

Handoff to print:

```
Repo:   https://github.com/Altien/<DEST_NAME>   (branch: altien-main)
Open this repo in Claude (cloud) on the altien-main branch and run:

  /repository-explorer      → docs/repository-explorer/   (always)
  /build-explorer           → docs/explorer/               (only if the repo has skills/agents/prompts; it auto-detects and will say so)
  /build-atlas              → docs/atlas/                  (optional, heavyweight — only if you want the live doc↔code Atlas)

Let the cloud session commit the generated docs/ islands to altien-main and push.
Then come back here and say "register the <DEST_NAME> islands" (or re-run /adopt-repo) to finish.
```

Note that `build-explorer` may find no skills/prompts in a plain application repo
(e.g. an Outlook add-in) — that's fine; it reports coverage and you simply skip
that island.

## Phase 4 — Pull the islands & register them on the launcher

When the cloud build is confirmed done:

1. `cd TARGET_DIR && git pull origin altien-main` — the generated `docs/` islands
   are now on disk locally, where the launcher serves them from.
2. Run the **`rescan-docs`** skill end-to-end. Per the user's standing preference,
   run the full workflow **without asking first**: dry run → `--write` → refine
   each new entry's `name`/`desc` by reading its island README → set
   `publishable: true` for the static explorers (`repository-explorer`,
   `build-explorer`) and `false` for the Atlas (it's a `uvicorn` app, not static)
   → validate ports → commit + push the launcher (`MikeForxExplorer`). Surface any
   stale-island warnings but leave stale entries in place.
3. Remind the user to restart the launcher (`Ctrl+C`, then `python app.py` from
   inside `MikeForxExplorer`) to pick up the new islands.

## Verify & report

Print a final summary:

- Dev repo: `https://github.com/Altien/<DEST_NAME>`, default branch `altien-main`,
  `main` pristine-tracking `upstream/main`, Actions disabled.
- Vendored skills committed under `.claude/`.
- Islands built in the cloud and registered: list each with its launcher port and
  `publishable` flag.
- The two sync cheat-sheets the component skills printed (upstream → main, and
  develop-on-trunk), so the user has them in one place.
