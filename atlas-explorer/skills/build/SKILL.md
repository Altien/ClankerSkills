---
name: build
description: >
  Build "The Atlas" for the current repository — a live FastAPI documentation
  navigator that binds every markdown doc to the code it describes. Doc↔code
  50/50 views (code paths in prose become chips; the panel shows tree-sitter-
  sliced, Pygments-highlighted source with collapsible fold regions and jump-to-
  symbol), SQLite FTS5 search, live drift detection (every doc→code reference
  verified against the tree, plus deterministic quantitative-claim counters),
  authored curation (per-doc summaries, sequenced journeys, clickable SVG flow
  diagrams), and anchored commenting with clipboard "agent brief" export. Use
  when the user says "build an atlas", "build a documentation navigator for this
  repo", "bind the docs to the code", "give me a doc explorer with drift
  detection", or runs /atlas-explorer:build.
argument-hint: "[--no-curation] [--no-comments] [--manifest-only] [--update] [target dir, default: docs/atlas]"
---

# Build The Atlas

Build a **live, self-contained documentation navigator** for the current
repository under `docs/atlas/`. It binds the repo's markdown docs to the code
they describe and checks, continuously, that they still agree.

Unlike the static sibling explorers in this marketplace, The Atlas is a **live
FastAPI server** with real Python dependencies (tree-sitter, Pygments, FTS5) —
that is the cost of its live doc↔code binding, drift detection, and commenting,
which a static export cannot do. It is self-contained (no external services, no
node toolchain, runs entirely locally) but **not** dependency-light. Be honest
about that in what you write.

Read real files and cite them; never invent a summary, a journey, or a diagram
note. Authored prose is written *after reading the source*, never extracted.

The engine is **repo-agnostic by contract**: nothing in the kit references a
particular repository (a test enforces this). Everything repo-specific lives in
exactly two places you create: **`atlas.config.yaml`** and **`curated/`**.

## Locate the kit

This skill bundles the engine, the authoring references, a config skeleton, and
a full worked example in its own directory. Resolve that directory robustly —
it works whether this runs as a plugin or a plain skill in `~/.claude/skills/`:
`${CLAUDE_SKILL_DIR}` is the skill's own directory in both modes (equivalently
`${CLAUDE_PLUGIN_ROOT}/skills/build` when installed as a plugin); if
neither is set, fall back to the directory that contains this `SKILL.md`. Then:

- `SELF` = this skill's directory (resolved above)
- `KIT  = SELF/kit`        — the engine, **copied verbatim**
- `REF  = SELF/reference`  — `METHOD.md` (config surface + architecture), `AUTHORING.md` (the curated-YAML binding spec + quality bar)
- `TPL  = SELF/templates`  — `atlas.config.skeleton.yaml`, the annotated config to adapt
- `EX   = SELF/examples`   — `lavernDev/`, a real, non-trivial worked instance (config + full curated/)
- `DEST = <target repo>/docs/atlas`

> **Golden rule:** the **engine** (`KIT`) is copy-verbatim and never references
> the host repo; the **mechanical index** (built live at startup from the tree)
> and the **authored curation** (`curated/*.yaml`) are separate sources merged
> at request time. Re-running the server (or the ⟳ reindex) refreshes the
> mechanical side and never touches your authored curation or the durable
> comments. **Drift is a feature** — when docs disagree with the tree it shows
> on `/drift`; only fix doc drift if the user asks.

## Modes (from `$ARGUMENTS`)

- **default** — full build: working navigator + the full authored curation.
- `--no-curation` — stop after Phase 3: a working navigator (50/50, search,
  drift, comments) with an empty `curated/`. The engine fully supports this.
- `--no-comments` — ship read-only: omit the commenting/feedback layer.
- `--manifest-only` — run Phase 1 only; report the corpus + code surface that
  *would* be indexed, build nothing.
- `--update` — incremental refresh against a prior build: re-run the mechanical
  side, re-author only the curation whose backing source changed, and prepend a
  doc-build changelog entry. See *Incremental updates* below.

Parse the args, state the mode you're running, then proceed.

## Phase 0 — Copy the kit and prove the engine runs

Copy the **entire** `KIT` into `DEST`, verbatim: `engine/`, `templates/`
(incl. `partials/`), `static/`, `app.py`, `verify.py`, `requirements.txt`,
`tests/`, `.gitignore`, `data/.gitignore`. Do **not** copy any
`atlas.config.yaml` or `curated/` — you create those fresh.

Install the engine's dependencies and prove the bare engine works before
configuring anything:

```
cd DEST
pip install -r requirements.txt
python -m pytest tests -q          # engine suite green; 2 instance tests skip until config exists
```

Use `python -m <tool>` (not bare `uvicorn`/`pytest`) — pip's script dir is
often not on PATH, especially on Windows.

Then make the **only two per-repo edits inside the kit**, both clearly marked
`ADAPT PER REPO`:
- `tests/test_reusability.py` — set `FORBIDDEN` to this repo's product/codebase
  names (and source-dir tokens). This is what enforces that the engine never
  hard-codes anything about its host.
- `tests/test_app.py` (`test_real_config_smoke`) — set `MIN_DOCS` to a sane
  floor for this repo's corpus once you know its size (do this in Phase 3).

If `--manifest-only`, do Phase 1 and stop.

## Phase 1 — Survey the repository

Inventory what the Atlas will index and bind (fan out exploration sub-agents on
a large repo):

- **Docs**: every significant `.md` (and `.html` if the repo ships rendered
  pages worth searching). Note the natural **categories** and the 5–10
  **entry-point docs** a newcomer starts with.
- **Code surface**: which top-level directories do the docs actually reference
  (`src/`, `lib/`, `pkg/`, …)? These become `code_references.roots`.
- **Languages**: what languages are in those roots? Each needs a tree-sitter
  grammar wheel + one `languages:` entry (Pygments already highlights
  everything; the grammar is only for symbol slicing/folding). TS/TSX ship in
  the kit's `requirements.txt`; add others as needed.
- **Sibling tools**: any existing explorer/catalog worth deep-linking into via
  `artifact_links` (it maps `source_path → id` through that tool's manifest).
- **Drift-exempt docs**: changelogs and history files that reference removed
  files *by design* → `drift_exempt`.

Report counts. If `--manifest-only`, this is the deliverable — stop here.

## Phase 2 — A short, repo-specific question round

The architecture is settled; do **not** re-litigate it. Ask the user only what
changes the config (use AskUserQuestion, recommended option first):

- corpus edges — what's in/out; which docs are **search-only** vs **full
  depth**; any HTML that should be **external** (linked, not rendered);
- category names and ordering;
- which languages need grammars (confirm the wheels to add);
- sibling-tool deep-links, if any;
- the port;
- and, unless `--no-curation`, **which 3–5 journeys** would serve this repo's
  audience (the sequenced reading paths authored in Phase 4).

## Phase 3 — Configure (drive to a booting navigator)

Start from `TPL/atlas.config.skeleton.yaml` and write `DEST/atlas.config.yaml`.
The full key surface is documented there and in `REF/METHOD.md`: `site`,
`repo_root`, `port`, `categories`, `corpus` (include/exclude globs ×
`depth: full|search-only` × `render: internal|external`), `category_rules`
(first-match-wins; an unassigned doc fails startup — a deliberate "no doc falls
through the cracks" guard), `code_references.roots`, `drift_exempt`,
`languages`, `artifact_links`, `db_path`, `curated_dir`.

Iterate until:

```
cd DEST
python -m uvicorn app:app --port <port>     # boots clean
python -m pytest tests -q                    # all green (set MIN_DOCS now)
```

Smoke-test against real docs: chips resolve to the code panel and slice
correctly; search returns sane hits; `/drift` shows only **genuine** drift. If
prose like "and/or" leaks in as a fake reference, tighten
`code_references.roots` — the root allowlist exists for exactly this. Every
include glob must match ≥1 file (the engine fails startup on a dead glob, so a
renamed directory can never silently shrink the corpus — don't paper over it).

If `--no-curation`, write the README (Phase 5) against the empty-curation state
and stop. Otherwise continue.

## Phase 4 — Author the curation layer

This is most of the work and the quality bar is high. The binding spec and the
standard are in `REF/AUTHORING.md`; the worked instance in `EX/lavernDev/` shows
the bar in practice. Fan out sub-agents for a large corpus.

- **`curated/atlas.yaml`** — dispatch a reader sub-agent to digest every
  full-depth doc (gist, audience, notable), then author a 2–3 sentence overview
  per category and a `summary` + `read_when` line for **every full-depth doc**.
  `verify.py` enforces 100% coverage; search-only docs are exempt.
- **`curated/journeys.yaml`** — the 3–5 agreed journeys. Each stop targets a
  doc, a doc section (use a **real heading slug** — print them from the
  registry, never guess), or a code symbol (a **real exported symbol** — print
  those too), with hand-written narration explaining why this stop and what to
  notice.
- **`curated/diagrams.yaml`** — 2–4 flow diagrams for the flow-heavy docs.
  Every node anchors to a real heading/symbol and carries a one-line summary.
  Compose each one with the **`diagram-design`** skill: earn the diagram, one
  distinct idea per node, ≤9 nodes (split overview/detail past that), edges only
  where they carry information, and run its remove test before committing the
  YAML. The engine owns the geometry and palette, so its style guide and
  connector rules don't apply — the composition discipline does. See
  `REF/AUTHORING.md`.
- **`curated/claims.yaml`** — find quantitative claims in the docs ("N modules",
  "N tests across M files"); verify each against the tree yourself first, then
  pair it with a deterministic counter. `expected` is what the **doc** says, so
  genuine drift fails visibly on `/drift`.

The standard (non-negotiable): every authored sentence is written after reading
the source. Extracted, templated, or "see the source" filler is a defect.

## Phase 5 — Verify and hand over

```
cd DEST
python verify.py                 # MUST exit 0 — curation errors are fatal; drift is not
python -m pytest tests -q        # all green
python -m uvicorn app:app --port <port>   # eyeball: home, a doc with chips, a journey, /drift, /feedback, /search
```

`verify.py` fails on curation **errors** (missing summary coverage, dangling
journey/diagram anchors, crashing claim counters, dead globs) and **reports**
content **drift** (broken refs, failing claims) without failing — that
distinction is the product. Fix every error; leave drift for the user.

Write `DEST/README.md` (run / reindex / verify / the feedback→agent loop) and
cross-link it from the repo's top-level docs (e.g. a row in `README.md` or
`CLAUDE.md`/`AGENTS.md`). Report coverage counts and the drift you surfaced.
Commit per phase on a feature branch with clear messages; open a PR only if
asked.

## Incremental updates & the doc-build changelog

After the first build, most re-runs are **updates**, not rebuilds. The Atlas is
already incremental on its mechanical side — re-running the server (or the ⟳
reindex) refreshes the tree-derived index and never touches `curated/` or the
durable comments. The `--update` mode extends that discipline to the **authored**
curation, so summaries, claims, journeys, and diagrams track the code instead of
silently going stale.

Anchor each build on the commit it was authored against. Keep a single
drift-exempt markdown doc — `docs/atlas/DOC-BUILD-LOG.md` — that the Atlas
indexes and renders like any other doc: a machine-readable `<!-- built_from:
<sha> -->` line plus a human-readable, newest-first changelog. Add it to a
`corpus` include glob and list it under `drift_exempt` (it references code by
design). Storing this as its own doc keeps the engine and the `curated/` schema
untouched and repo-agnostic — do **not** add an engine route or new curated keys
for it.

An `--update` run:

1. Read `built_from` from `DOC-BUILD-LOG.md`. If it is missing, fall back to a
   full author pass (Phase 4).
2. Compute the changed-source set — `git diff --name-only <built_from>..HEAD`
   plus untracked docs/code — and map those paths to the curation they back: the
   `summary`/`read_when` of a changed doc, the `claims` whose counted code moved,
   the `journeys`/`diagrams` whose anchored heading or symbol shifted. Print the
   mapping so the scope is auditable.
3. Re-author **only** those entries, to the full Phase-4 bar; leave the rest
   untouched. Re-run `verify.py` — anchors dangling from renamed or removed code
   surface here and must be fixed.
4. Update `built_from` to HEAD and prepend a changelog entry: the date, the
   commit range, and **what curation changed and why**, authored after reading
   the diff (e.g. "Refreshed for the Opus 4.8 migration: updated the
   provider-abstraction summary, the agent-count claim, and the delivery-view
   journey stop"). Never paste a mechanical file list — if it reads like
   `git log`, it does not belong here.

This is the **documentation's** history, distinct from the repo's own product
`CHANGELOG.md` (which stays `drift_exempt` and is never edited here).

## Phase 6 — Evolve this skill

The Atlas is meant to get better every time it meets a new repo. When a build
surfaces a genuinely **reusable** improvement, write it back into **this skill's
own directory** (`SELF`, resolved above) so the next invocation inherits it —
do not let the improvement die in the target repo:

- **Engine fix or capability** (a real bug, a robustness gap, a broadly useful
  feature) → edit `KIT/` in place. It must stay repo-agnostic: add nothing that
  names a host repo, and keep `tests/test_reusability.py` meaningful. Add or
  update a test in `KIT/tests/` to cover it. If the improvement also benefits an
  already-deployed instance you know about (e.g. the lavernDev example), apply
  it there too so they don't drift.
- **New language support** → add the grammar to `KIT/requirements.txt` and a
  `languages:` example to `TPL/atlas.config.skeleton.yaml`; note it in
  `REF/METHOD.md`.
- **Better curation pattern or a sharper authoring rule** → fold it into
  `REF/AUTHORING.md` (and the skeleton/example if it changes their shape).
- **A recurring config need** → surface it in `TPL/atlas.config.skeleton.yaml`
  with a comment, and document the key in `REF/METHOD.md`.

Guardrails: only generalize what is genuinely repo-independent (one repo's
quirk belongs in *its* config, not the kit); run `KIT` tests green before and
after; keep the kit lean — resist speculative features. Tell the user what you
changed in the skill and why, and (if the skill lives in a git repo) commit it
separately from the target-repo work so the evolution is reviewable.

## Quality bar

Effort and judgement are the standard. Every user-facing string — a summary, a
journey note, a diagram label, a category overview — must be specific to *this*
repo and earned by reading the source. The drift layer must reflect the real
tree, not the docs' self-description. No new runtime dependencies beyond the
engine's (and any tree-sitter grammar a language genuinely needs). The result
should work for a repo with a handful of docs or many hundreds.
