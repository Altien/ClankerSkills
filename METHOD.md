# Skills & Prompts Explorer — reusable build method

This is the tool-agnostic playbook for building a self-contained, static
**Skills & Prompts Explorer** for *any* repository: a browsable, documenter-style
site that finds every skill and prompt, gives each a detailed **assessment card**
and a generated **workflow diagram**, and lets a reader click any diagram step to
read the verbatim source for that step.

You can drive this three ways — they share the same kit:

1. **Plugin (recommended):** install this marketplace, then run `/build-explorer`
   or just ask Claude to "build a skills explorer for this repo". See
   [README.md](README.md). The skill body
   ([`skills-explorer/skills/build-explorer/SKILL.md`](skills-explorer/skills/build-explorer/SKILL.md))
   is the same playbook below.
2. **Any agent / by hand:** point your agent at this file and the kit, and follow
   the phases.
3. **Copy the kit:** lift the static components straight into a target repo's
   `docs/explorer/` and adapt.

## The kit (static, reusable components)

Everything lives under
[`skills-explorer/skills/build-explorer/`](skills-explorer/skills/build-explorer/):

| Path | Role |
|------|------|
| [`kit/assets/app.js`](skills-explorer/skills/build-explorer/kit/assets/app.js) | SPA: router, search, assessment-card renderer, programmatic-surface panel, SVG diagram generator, fence-aware click-to-source section slicer. Branding comes from `EXPLORER_CONFIG`. **Copy verbatim.** |
| [`kit/assets/marked.min.js`](skills-explorer/skills/build-explorer/kit/assets/marked.min.js) | Vendored minimal Markdown renderer. Zero deps. **Copy verbatim.** |
| [`kit/assets/styles.css`](skills-explorer/skills/build-explorer/kit/assets/styles.css) | Light/dark theming via CSS variables. **Copy verbatim.** |
| [`kit/index.html`](skills-explorer/skills/build-explorer/kit/index.html) | Shell. The **only** edit is the `EXPLORER_CONFIG` branding block + matching brand text. |
| [`kit/serve.py`](skills-explorer/skills/build-explorer/kit/serve.py) | Stdlib HTTP server (serves repo root, opens `/docs/explorer/`). **Copy verbatim.** |
| [`kit/verify.cjs`](skills-explorer/skills/build-explorer/kit/verify.cjs) | Repo-agnostic structural verifier. **Copy verbatim.** |
| [`kit/assemble_data.py`](skills-explorer/skills/build-explorer/kit/assemble_data.py) | Merges + validates `data/*.json` → `assets/explorer-data.js`. **Copy verbatim.** |
| [`reference/AUTHORING.md`](skills-explorer/skills/build-explorer/reference/AUTHORING.md) | The binding spec for authored fragments (node rules, `srcHeading`/`srcFocus`/`srcWhole`, note quality bar). **Copy verbatim.** |
| [`templates/build_explorer.skeleton.py`](skills-explorer/skills/build-explorer/templates/build_explorer.skeleton.py) | **Adapt per repo.** Generic discovery that auto-detects common conventions, with marked `ADAPT` extension points. |
| [`examples/claude-for-legal.build_explorer.py`](skills-explorer/skills/build-explorer/examples/claude-for-legal.build_explorer.py) | Worked example: a 13-plugin marketplace (skills + agents + managed-agent cookbooks + embedded prompts + TS registry parsing). |
| [`skills/update-explorer/SKILL.md`](skills-explorer/skills/update-explorer/SKILL.md) | Subsequent-update procedure: re-import tools, extract in the source repo, preserve history, verify, report, and commit. |
| [`skills/update-explorer/scripts/catalog_bundle.py`](skills-explorer/skills/update-explorer/scripts/catalog_bundle.py) | Deterministic bundle/history/checksum/verification/log publisher copied into each source repository. |

### What ships verbatim vs. what is authored per repo

- **Copy verbatim** (the engine): `assets/*`, `index.html` (one branding edit),
  `serve.py`, `verify.cjs`, `assemble_data.py`, `AUTHORING.md`.
- **Adapt** the discovery layer: `build_explorer.py` (start from the skeleton).
- **Author**: the curated `data/*.json` fragments (graphs + assessments).
- **Generated** (never hand-edit): `explorer-manifest.json` and
  `catalog/discovered.json` (from `build_explorer.py`),
  `assets/explorer-data.js` (from `assemble_data.py`), and the verified
  `catalog/{catalog.bundle.json,*.sha256,verification.json,state.json,update-log.jsonl}`.

> Golden rule: the **mechanical manifest** and the **authored data** are separate
> sources, merged by `id` in the app. Regenerating the manifest never clobbers
> graphs or assessments.

## The phases

### Phase 0 — Detect conventions
Determine what skill/prompt conventions the repo actually uses before assuming
any. Probe for: Claude Skills folders (`**/SKILL.md` + frontmatter),
`.claude/commands/*.md`, `.claude/agents/*.md`,
`CLAUDE.md`/`AGENTS.md`/`.cursorrules`/`.github/copilot-instructions.md`,
`prompts/` dirs and `*.prompt(.md|.yaml)`/`*.prompty`/`*.jinja`, prompt catalogs
(promptfoo/langfuse/dspy), structured registries, and **embedded prompts in
code** (`*_PROMPT`/`SYSTEM_PROMPT`/`*_TEMPLATE`, `role:"system"`,
`PromptTemplate`/`.from_template`, triple-quoted/template-literal blocks — record
path AND line range). Record what you find.

The skeleton's embedded scanner **auto-walks text source files by default** and
handles language-specific literal forms for Python, ECMAScript, Go, Rust, JVM,
.NET, C-family, Ruby, PHP, Swift, Dart, Elixir/Erlang, Lua/R/Julia/Nim/Zig,
shells, and PowerShell. Unknown source extensions use a conservative generic
fallback rather than being excluded. Named literals, prompt-builder calls, and
paired `role: system` content are name/content gated to reduce noise. The
manifest reports profiles, extensions, generic fallbacks, skips, warnings, and
candidate counts; unexplained gaps must be resolved in the repository adapter.

### Phase 1 — Discover everything
Copy the kit into `docs/explorer/`, plus the updater's `catalog_bundle.py`, schemas,
and catalog contract into `docs/explorer/{tools,schemas}/`. Start
`build_explorer.py` from the skeleton
and adapt its discovery to the Phase-0 conventions. Run it; iterate until
discovery is exhaustive and deduplicated, reporting counts + the coverage list.
Use a **UTF-8-safe unescaper** for quoted strings from source (not Python's
`unicode_escape`). Every generic and repository-specific discoverer must retain
the exact body as `_content`; the builder writes it to
`catalog/discovered.json` while structured-registry parsing context still exists.

### Phase 2 — Author the per-artifact data
Read `AUTHORING.md`. For every artifact author an assessment card and a workflow
graph of its REAL ordered process — every step/decision node anchored to an exact
source heading (`srcHeading`, or `srcWhole` for heading-less prompts; `srcFocus`
when siblings share a heading) and carrying a hand-authored 12–28-word `note`.
For large rosters, fan out parallel sub-agents (one fragment per area). Every card
and node must trace to real text. *(Skip for a manifest-only pass — the app falls
back to faithful heading-derived shape diagrams and mechanical assessment
fields.)*

### Phase 3 — Brand
Set `EXPLORER_CONFIG` (`brand`, `tagline`, optional `accent`, `outputSchemaPath`)
in `index.html`; replace the `YOUR_REPO` placeholders.

### Phase 4 — Verify (drive to zero)
```
python3 docs/explorer/build_explorer.py    # -> explorer-manifest.json
python3 docs/explorer/assemble_data.py     # data/*.json -> assets/explorer-data.js
node docs/explorer/verify.cjs              # MUST exit 0
python3 docs/explorer/tools/catalog_bundle.py publish --summary "Initial verified catalog."
python3 docs/explorer/tools/catalog_bundle.py verify
python3 docs/explorer/serve.py             # eyeball in a browser
```
Verification is **structural** (graph integrity, geometry, section resolution,
authored-summary coverage, distinct sibling slices), not pixel-level — eyeball via
`serve.py`.

### Phase 5 — Wrap up
Write `docs/explorer/README.md` (serve, regenerate, maintenance rules, Doc build
log). Commit the verified Explorer on a feature branch; opening a PR still needs
confirmation. Use `/update-explorer` for later refreshes. Its checked-in bundle
retains disappeared artifacts as historical records and its JSONL report is
append-only and hash-chained.

## Quality bar
Effort and judgement are the standard. Every user-facing string must be specific
to *this* artifact and traceable to a file; templated or "see the source" filler
is a defect. Exhaustive discovery with a reported coverage list. Deduplicate.
Works for repos with 1 or 100+ artifacts. No new runtime dependencies.
