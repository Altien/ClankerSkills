---
name: build-explorer
description: Build the initial self-contained Skills & Prompts Explorer for a repository, including polyglot embedded-prompt discovery, exact pre-extracted bodies, authored assessments and workflows, a verified downstream catalog bundle, and immutable Git provenance. Use for the first Explorer build; use update-explorer for an existing Explorer.
---

# Build a Skills & Prompts Explorer

Build the repository's first Explorer under `docs/explorer/`. Read real files and cite
them; never invent metadata, workflow steps, or commentary. The source repository owns
discovery and publishes exact prompt/skill bodies. A downstream directory consumes only
the verified catalog bundle and must not rescan the source repository.

Let `BUILD = ${CLAUDE_PLUGIN_ROOT}/skills/build-explorer`,
`UPDATE = ${CLAUDE_PLUGIN_ROOT}/skills/update-explorer`, and
`DEST = <target repository>/docs/explorer`.

## 1. Establish the repository conventions

Inspect the tree, README, agent instructions, and registries before adapting anything.
Look for:

- `**/SKILL.md`, commands, agent definitions, and instruction files;
- prompt directories, prompt catalogs, templates, and structured JSON/YAML registries;
- embedded system/developer messages, prompt literals, prompt-builder calls, and shared
  registries in every programming language used by the repository.

The skeleton does not exclude a programming language merely because its extension is
unknown. It has literal profiles for Python, ECMAScript, Go, Rust, JVM, .NET, C-family,
Ruby, PHP, Swift, Dart, Elixir/Erlang, Lua/R/Julia/Nim/Zig, shells, and PowerShell, plus a
conservative generic text-source fallback. This is heuristic discovery, not a claim that
arbitrary syntax can be parsed perfectly. Coverage must report profiles, extensions,
fallback files, skipped files/reasons, warnings, and rejected candidates.

For a large roster, delegate bounded discovery or authoring batches to subagents. Give
each one `AUTHORING.md` plus an explicit artifact-id-to-source-path list; retain coverage,
deduplication, and publication decisions in the integrating agent.

## 2. Install and adapt the repository-local Explorer

Copy the static engine from `BUILD/kit/` into `DEST/`, preserving `assets/`. Copy:

- `BUILD/reference/AUTHORING.md` to `DEST/AUTHORING.md`;
- `BUILD/templates/build_explorer.skeleton.py` to `DEST/build_explorer.py`;
- `UPDATE/scripts/catalog_bundle.py` to `DEST/tools/catalog_bundle.py`;
- `UPDATE/schemas/*.json` to `DEST/schemas/`;
- `UPDATE/references/CATALOG_SCHEMA.md` to `DEST/CATALOG_SCHEMA.md`.

Adapt only the discovery layer of `build_explorer.py`: category mapping, explicit paths,
repository registries, stable IDs, exclusions, and structured programmatic metadata. The
generic discoverers already store an exact private `_content` value. Every repository-
specific adapter must do the same, especially when many artifacts share one JSON/YAML/code
registry and line slicing could not reconstruct them later. Such shared-registry adapters
should also supply per-artifact `content_commit` when whole-file Git history would confuse
an unrelated registry edit with a body change.

Run:

```text
python docs/explorer/build_explorer.py
```

It must write both `explorer-manifest.json` and `catalog/discovered.json`. Treat any
`missing_content_ids`, unexplained coverage regression, parse warning, or ambiguous
candidate as a blocker: explain it to the user and improve the repository adapter before
continuing. Do not make the downstream library compensate for an insufficient Explorer.

## 3. Author assessments and workflows

Read `DEST/AUTHORING.md` completely. For each artifact, author a `data/*.json` entry with
an evidence-grounded assessment and a graph of its real ordered process. Every step or
decision needs an exact source anchor and a specific 12–28 word note.

Compose each graph with the **`diagram-design`** skill: one distinct idea per node, the
5–9 step budget as a hard ceiling, edges only where they carry information, accents
(`chips`/`tag`/`stop`) kept scarce, and its remove test run before the fragment ships.
The engine owns the geometry and palette, so its style guide and connector rules don't
apply here — the composition discipline does. `AUTHORING.md` has the details.

A manifest-only pass may omit this phase only when the user explicitly requests it; label
the resulting UI fallback as mechanical rather than authored.

Edit the `EXPLORER_CONFIG` branding block and matching visible brand text in `index.html`.
Do not alter the engine for repository-specific branding.

## 4. Assemble, verify, and publish the initial bundle

The source artifact files must be committed before publication so `scan_commit` identifies
an immutable tree. Explorer outputs may still be uncommitted while they are being built.

```text
python docs/explorer/assemble_data.py
node docs/explorer/verify.cjs
python docs/explorer/tools/catalog_bundle.py plan
python docs/explorer/tools/catalog_bundle.py publish --summary "Initial verified Explorer catalog."
python docs/explorer/tools/catalog_bundle.py verify
```

Also validate JSON, compile Python, run `node --check` on JavaScript, serve the site, and
eyeball it. `verify.cjs` is structural verification, not pixel verification.

Publication creates repository-owned, check-in-ready artifacts under `catalog/`:

- `catalog.bundle.json` and its SHA-256 checksum;
- `verification.json` and `state.json`;
- append-only, hash-chained `update-log.jsonl`.

The bundle includes exact bodies and immutable GitHub links pinned to the commit where the
body last changed. Write `DEST/README.md` with serve/regenerate instructions, coverage,
maintenance rules, and a newest-first human Doc build log. Commit only the Explorer files
on a feature branch after all checks pass. Opening a PR still requires confirmation.

## 5. Hand subsequent work to update-explorer

Do not rebuild an existing Explorer from scratch and do not use a `--update` mode here.
Invoke `update-explorer`; it refreshes the current tool/schema copies, reruns repository-
owned extraction, preserves disappeared artifacts as history, reviews only changed
curation, verifies, logs, and commits the update.

## Quality bar

Discovery coverage is explicit, not aspirational. Every exported artifact has an exact
body, stable ID, source path, content hash, and immutable provenance. Every authored claim
traces to source text. Unknown manifest fields are preserved. Low-quality source material
is described honestly rather than silently promoted or rewritten.
