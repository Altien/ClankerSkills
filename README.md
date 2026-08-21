# ClankerSkills

Reusable Claude Code tooling for understanding — and working inside — other
repositories. Point any of these plugins at a repo and it builds you a
self-contained tool for navigating, documenting, or mirroring it.

## Install (as a Claude Code marketplace)

```bash
claude plugin marketplace add Altien/ClankerSkills
claude plugin install <plugin>@clanker-skills
```

Then, in any repository, run the plugin's slash command — or just describe what
you want and the skill auto-triggers.

## The plugins

| Plugin | Command | What it builds |
|--------|---------|----------------|
| **Adopt Repo** (`adopt-repo`) | `/adopt-repo:adopt` | The front-runner. Onboards an upstream OSS repo into the dev workspace end to end — private `<name>-dev` mirror → `altien-main` development trunk → vendors the explorer skills into the repo and pushes them → **pauses** so Claude in the cloud can build the documentation islands → pulls them back and registers them on the docs launcher. A sequencer over the four plugins below plus `rescan-docs`. |
| **Skills & Prompts Explorer** (`skills-explorer`) | `/skills-explorer:build`, `/skills-explorer:update` | A dependency-light **static** site plus a repository-owned catalog. Polyglot discovery pre-extracts exact skill/prompt bodies in the source repo; verified bundles preserve removals as history, pin provenance to immutable commits, and carry a hash-chained update log. |
| **Repository Explorer** (`repository-explorer`) | `/repository-explorer:build` | A **static** browsable Markdown documentation site (file tree, search, rendered mermaid, optional review/commenting) **plus** a code-verified "Architecture & Technology" analysis published as both Markdown and an expressive HTML page with hand-authored inline-SVG diagrams. |
| **The Atlas** (`atlas-explorer`) | `/atlas-explorer:build` | A **live FastAPI** documentation navigator that binds every markdown doc to the code it describes: doc↔code 50/50 views, tree-sitter symbol slicing with fold regions, SQLite FTS5 search, live drift detection, authored journeys + clickable SVG diagrams, and anchored feedback with clipboard agent-brief export. |
| **Private Mirror** (`private-mirror`) | `/private-mirror:mirror` | Sets up the current empty directory as a **private mirror** of a public GitHub repo — pull upstream updates, but pushes to upstream are physically disabled and Actions are turned off before the first push. |
| **Fork Trunk** (`fork-trunk`) | `/fork-trunk:setup` | Gives an **existing fork** its own default development branch (e.g. `<org>-main`) that all work lands on, while `main` stays a pristine mirror of upstream you only sync from. Sets the trunk as the GitHub + local default, routes unmerged local work onto it via PR (never onto `main`), and can disable Actions on the fork. |
| **Sync Upstream** (`sync-upstream`) | `/sync-upstream:sync` | The routine follow-up to the three above. Fast-forwards the pristine `main` from `upstream`, lands those commits on the dev trunk via a reviewable PR, then detects any vendored documentation islands and hands off to their own update modes (`/repository-explorer:build --update`, `/skills-explorer:update`, `/atlas-explorer:build --update`) so the docs stay honest about the code that just moved. |

### Static explorers vs. The Atlas

`skills-explorer` and `repository-explorer` produce **dependency-light static
sites** — vendored JS + a stdlib `serve.py`, nothing to install. They're built
once and browsed.

`atlas-explorer` is the **heavyweight, server-based** sibling: a live FastAPI
app with real Python dependencies (tree-sitter, Pygments, FTS5). That's the cost
of what static sites can't do — verify every doc→code reference against the tree
on each load, slice symbols precisely, and accept anchored feedback. It's still
self-contained and fully local; just not dependency-free. Reach for it when you
want a *living* doc↔code binding with drift detection, not a snapshot.

## Use without installing

Every plugin is also usable by hand or by any agent — each ships a tool-agnostic
playbook (`METHOD.md` at the root and/or the skill's `reference/`) plus a
copy-verbatim engine you lift into a target repo. See each plugin's `SKILL.md`.

## Layout

```
.claude-plugin/marketplace.json     # marketplace manifest (lists all plugins)

adopt-repo/             skills/adopt/SKILL.md            # the orchestrator
skills-explorer/        skills/build/{SKILL.md, kit/, templates/, reference/, examples/}
                        skills/update/{SKILL.md, scripts/, schemas/, references/}
                        agents/explorer-update-worker.md
repository-explorer/    skills/build/{SKILL.md, kit/, reference/, examples/}
atlas-explorer/         skills/build/{SKILL.md, kit/, reference/, templates/, examples/}
private-mirror/         skills/mirror/SKILL.md
fork-trunk/             skills/setup/SKILL.md
prd-reviewer/           skills/review/SKILL.md
sync-upstream/          skills/sync/SKILL.md

METHOD.md                           # the Skills & Prompts Explorer's tool-agnostic playbook
```

For The Atlas specifically: the engine kit is at
`atlas-explorer/skills/build/kit/`, the config surface and curated-YAML
binding spec are in `reference/{METHOD,AUTHORING}.md`, an annotated config
skeleton is in `templates/atlas.config.skeleton.yaml`, and a real worked
instance is in `examples/lavernDev/`.

## Shared ethos

Across the explorer plugins, the same discipline holds:

- **The engine (`kit/`) is copy-verbatim and repo-agnostic.** Nothing in it
  names a host repo (a test enforces this for The Atlas).
- **Mechanical and authored content are separate sources, merged by id.**
  Regenerating the mechanical index (a manifest, or The Atlas's live reindex)
  never clobbers authored graphs, summaries, or comments.
- **Extraction belongs in the source repository.** Skills & Prompts Explorers
  publish exact bodies in a verified bundle; downstream directories consume the
  bundle and do not rediscover prompts from arbitrary source code.
- **Absence is history, not a deletion command.** A skill or prompt missing from
  a later scan remains in the catalog as historical, linked to its last content
  commit.
- **Authored prose is written after reading the source, never extracted.**
  Templated or "see the source" filler is a defect.
- **Honesty over polish.** Claims are verified against code; The Atlas goes
  further and *reports* doc↔code drift continuously rather than hiding it.

The Atlas additionally **evolves itself**: when a build surfaces a genuinely
reusable improvement (an engine fix, a new language grammar, a sharper authoring
rule), the skill writes it back into its own `kit/`/`reference/` so the next
repo inherits it.

## Status

- `adopt-repo` v0.1.0 — the orchestrator. Sequences `private-mirror` →
  `fork-trunk` → vendor explorers + push → cloud island build (paused handoff) →
  `rescan-docs`. First built to onboard `thepranky/cr_oss` as `Altien/cr_oss-dev`.
- `skills-explorer` v0.3.1 — first built for and proven on a 13-plugin legal
  marketplace (206 artifacts, 191 curated graphs, 37k+ structural checks); also
  run on a ~250-doc legal-AI platform (23 artifacts incl. 8 in-code system
  prompts). v0.3.0 adds polyglot literal discovery (including Go), exact
  repository-owned extraction, verified catalog bundles, immutable source
  provenance, historical retention, and `/skills-explorer:update` with hash-chained
  machine reports. v0.3.1 adds a bounded `model: haiku` update worker while keeping
  coverage, curation, quality, historical-retention, and publication decisions in the primary
  model. Explorer commits remain local until a PR is explicitly approved.
- `repository-explorer` v0.1.0.
- `atlas-explorer` v0.2.1 — engine proven on a ~140K-LOC repo (110 docs bound to
  its code) and a second ~250-doc repo; ships a 128-test engine suite (passes
  standalone) and a full worked instance. v0.2.1: an unresolved path token is only
  recorded as a code reference if its basename has a file extension, so REST routes
  (`api/v1/...`) and conceptual namespaces no longer pollute the drift report.
- `private-mirror` v0.1.0.
- `fork-trunk` v0.1.0 — distilled from setting up a private fork's `altien-main`
  trunk: keep `main` tracking upstream, develop on `<org>-main`, and disable CI.
- `sync-upstream` v0.1.0 — the ongoing counterpart to `adopt-repo`'s one-time
  setup: sync `main`, land it on the trunk via PR, then hand off to
  `repository-explorer`/`update-explorer`/`build-atlas`'s own update modes so
  vendored docs never silently drift from the code they describe.
