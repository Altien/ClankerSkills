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
| **Skills & Prompts Explorer** (`skills-explorer`) | `/build-explorer` | A dependency-light **static** site documenting every skill, agent, prompt-template, system-prompt, and instruction doc in the repo — each with an assessment card, a programmatic-surface panel (tool grants, MCP servers, invocation mode, bundled resources), and a workflow diagram whose steps slice their verbatim source. |
| **Repository Explorer** (`repository-explorer`) | `/repository-explorer` | A **static** browsable Markdown documentation site (file tree, search, rendered mermaid, optional review/commenting) **plus** a code-verified "Architecture & Technology" analysis published as both Markdown and an expressive HTML page with hand-authored inline-SVG diagrams. |
| **The Atlas** (`atlas-explorer`) | `/build-atlas` | A **live FastAPI** documentation navigator that binds every markdown doc to the code it describes: doc↔code 50/50 views, tree-sitter symbol slicing with fold regions, SQLite FTS5 search, live drift detection, authored journeys + clickable SVG diagrams, and anchored feedback with clipboard agent-brief export. |
| **Private Mirror** (`private-mirror`) | `/mirror-repo` | Sets up the current empty directory as a **private mirror** of a public GitHub repo — pull upstream updates, but pushes to upstream are physically disabled and Actions are turned off before the first push. |
| **Fork Trunk** (`fork-trunk`) | `/fork-trunk` | Gives an **existing fork** its own default development branch (e.g. `<org>-main`) that all work lands on, while `main` stays a pristine mirror of upstream you only sync from. Sets the trunk as the GitHub + local default, routes unmerged local work onto it via PR (never onto `main`), and can disable Actions on the fork. |

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

skills-explorer/        commands/build-explorer.md       skills/build-explorer/{SKILL.md, kit/, templates/, reference/, examples/}
repository-explorer/    commands/repository-explorer.md  skills/repository-explorer/{SKILL.md, kit/, reference/, examples/}
atlas-explorer/         commands/build-atlas.md          skills/atlas-explorer/{SKILL.md, kit/, reference/, templates/, examples/}
private-mirror/         commands/mirror-repo.md          skills/...

METHOD.md                           # the Skills & Prompts Explorer's tool-agnostic playbook
```

For The Atlas specifically: the engine kit is at
`atlas-explorer/skills/atlas-explorer/kit/`, the config surface and curated-YAML
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
- **Authored prose is written after reading the source, never extracted.**
  Templated or "see the source" filler is a defect.
- **Honesty over polish.** Claims are verified against code; The Atlas goes
  further and *reports* doc↔code drift continuously rather than hiding it.

The Atlas additionally **evolves itself**: when a build surfaces a genuinely
reusable improvement (an engine fix, a new language grammar, a sharper authoring
rule), the skill writes it back into its own `kit/`/`reference/` so the next
repo inherits it.

## Status

- `skills-explorer` v0.1.0 — first built for and proven on a 13-plugin legal
  marketplace (206 artifacts, 191 curated graphs, 37k+ structural checks).
- `repository-explorer` v0.1.0.
- `atlas-explorer` v0.1.0 — engine proven on a ~140K-LOC repo (110 docs bound to
  its code); ships a 127-test engine suite (passes standalone) and a full worked
  instance.
- `private-mirror` v0.1.0.
- `fork-trunk` v0.1.0 — distilled from setting up a private fork's `altien-main`
  trunk: keep `main` tracking upstream, develop on `<org>-main`, and disable CI.
