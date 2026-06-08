# The Atlas — engine reference (config surface + architecture)

This is the binding reference for the Atlas engine that ships in this skill's
`kit/`. The SKILL.md playbook drives the build; this file is the detail you
consult while configuring. The engine is repo-agnostic by contract: nothing
under `kit/engine/`, `kit/templates/`, `kit/static/`, `kit/app.py`, or
`kit/verify.py` may reference a particular repository (enforced by
`kit/tests/test_reusability.py`). Everything repo-specific lives in exactly two
places you author in the target repo: **`atlas.config.yaml`** and **`curated/`**.

## `atlas.config.yaml` — the full key surface

| Key | What it controls |
|---|---|
| `site.title` / `site.subtitle` | Branding strings |
| `repo_root` | Relative path from the config file to the repo root |
| `port` | Default uvicorn port |
| `categories` | Ordered category list (id + title) for the sidebar/home |
| `corpus` | Entries of include/exclude globs with `depth: full \| search-only` and `render: internal \| external`. Every individual glob must match ≥1 file — dead globs fail startup so a renamed directory can never silently shrink the corpus |
| `category_rules` | Ordered fnmatch rules mapping doc ids to categories (first match wins; an unassigned doc fails startup — no doc falls through the cracks) |
| `code_references.roots` | First path segments eligible to become code chips (the allowlist that keeps prose like "and/or" out of drift) |
| `drift_exempt` | Doc-id patterns whose broken refs are expected (changelogs reference removed files by design) |
| `languages` | Extension → tree-sitter grammar (`"module:function"`). **TypeScript and Python grammars ship in the kit's `requirements.txt`** (`.py`, `.ts`, `.tsx` slice out of the box); adding another language = `pip install` its grammar wheel + one entry. Pygments handles highlighting for every language already; the grammar is only for symbol slicing + fold regions. The extractor understands JS/TS declarations (functions, classes + methods, interfaces, enums, exported consts) and Python (`def`/`class`, decorated defs incl. routes, and class methods) |
| `artifact_links` | Deep-links into sibling tools via a JSON manifest (`source_path` → `id` mapping + URL template) |
| `db_path` / `curated_dir` | Storage locations (FTS index + durable comments; the authored YAML dir) |

`templates/atlas.config.skeleton.yaml` in this skill is an annotated starting
point; `examples/lavernDev/atlas.config.yaml` is a real, non-trivial instance.

## `curated/` — four authored YAML files

All optional to *run*, but `atlas.yaml` is required to *verify*:

- `atlas.yaml` — category overviews + per-doc `summary` and `read_when`.
  **Coverage rule:** every `depth: full` doc needs an entry (search-only docs
  are exempt).
- `journeys.yaml` — sequenced stops (`doc` / `doc`+`heading` / `path`+`symbol`)
  with hand-written narration per stop.
- `diagrams.yaml` — flow graphs; every node needs an anchor (real heading or
  symbol) AND a one-line summary.
- `claims.yaml` — quoted quantitative doc claims paired with deterministic
  counters (`file_count`, `symbol_count`, `line_count`).

The binding spec (exact fields, node rules, what fails verification) and the
quality bar are in `AUTHORING.md`.

## Verify and serve

- `python verify.py` — fails on curation *errors* (missing coverage, dangling
  anchors, crashing counters, dead globs) and *reports* content *drift* (broken
  refs, failing claims) without failing. Drift is the system working.
- `python -m uvicorn app:app --port <port>` — serve (module form; pip's script
  dir is often not on PATH). Reindex from the UI (⟳) after editing docs, or
  `POST /api/reindex`.

## Architecture in one paragraph

A `Registry` is an immutable-in-spirit snapshot built at startup: corpus scan
(markdown + HTML extraction), doc→code reference detection validated against the
tree, tree-sitter symbol index, claims evaluation, curation load, journey/diagram
anchor verification. `POST /api/reindex` builds a new snapshot and swaps one
attribute — in-flight requests never see a partial index. SQLite holds the
disposable FTS5 index and the durable comments table side by side; rebuilds only
ever touch `fts`. Rendering is fully server-side (markdown-it-py, Pygments +
tree-sitter fold regions, SVG diagrams); the browser runs htmx plus ~100 lines of
vanilla JS. `app.py` exposes `app` lazily via module `__getattr__`, so importing
the module (tests, tooling) never requires a deployed config; `uvicorn app:app`
builds it on demand.

## What the comments system expects

Comments anchor to docs, sections, files, symbols, diagram nodes, or journey
stops; orphan detection re-verifies anchors against every new index instead of
deleting anything. The clipboard is the agent handoff: per-comment briefs and
filtered bundles embed the anchored source slice so an agent can act without
re-deriving context. `--no-comments` ships a read-only navigator (the engine
runs fine with the feature unused).
