# Authoring the curated layer

The four files under `curated/` are the only authored content in an Atlas
instance. The engine validates them hard at startup and `verify.py` gates them.
This is the binding spec; `examples/lavernDev/curated/` is a full worked set
that meets the bar.

> **The standard, above all else:** every sentence is written *after reading the
> source it describes*. Extracted first-paragraphs, templated phrasing, and
> "see the source for details" filler are defects, not shortcuts. If you
> wouldn't put your name on the sentence, don't ship it.

## `atlas.yaml` — summaries + category overviews

```yaml
categories:
  <category-id>: >-          # must match a category id in atlas.config.yaml
    2–3 sentence overview of what lives in this category and why.
docs:
  <doc-id>:                  # repo-relative path, must be a corpus doc
    summary: >-              # required; one paragraph, authored
      What this doc actually says — specific: names, numbers, structure.
    read_when: >-            # optional but expected; one line
      Who should read it, in what situation.
```

**Coverage rule (enforced by verify.py):** every `depth: full` doc needs an
entry. Search-only docs are exempt. An entry pointing at a doc that isn't in the
corpus, an overview for an unknown category, or an empty summary fails startup.

## `journeys.yaml` — sequenced reading paths

```yaml
- id: <journey-id>           # unique
  title: "Human title"
  intro: >-                  # one or two sentences for the home card + header
    What this path is for.
  stops:
    - title: "Optional stop label"
      narration: >-          # required; why THIS stop, what to notice
        Hand-written, source-aware.
      # target — exactly ONE of doc / path per stop:
      doc: <doc-id>          # a corpus doc
      heading: <slug>        # optional: a real heading slug within that doc
      # …or…
      path: <repo/rel/file>  # a source file
      symbol: <Name>         # optional: a real exported symbol in that file
```

Targets are verified at index time. A stop pointing at a missing doc, heading,
or symbol is **dangling**: it surfaces on `/drift` and fails `verify.py`. Print
real heading slugs and exported symbols from the running registry — never guess
them. Narration sits *beside the live target content*, so it must not duplicate
the source; it frames it.

## `diagrams.yaml` — clickable flow diagrams

```yaml
- id: <diagram-id>           # unique
  title: "Human title"
  doc: <doc-id>              # the corpus doc this diagram attaches to
  nodes:
    - id: <node-id>          # unique within the diagram
      type: start|step|decision|output|stop
      label: "Box label"
      summary: >-            # required; one authored line
        What this node is.
      # anchor — exactly ONE of doc / path per node:
      doc: <doc-id>
      heading: <slug>
      # …or…
      path: <repo/rel/file>
      symbol: <Name>
      # optional flow edges:
      loop_to: <node-id>     # draws a dashed back-edge to an earlier node
      when: "fail → revise"  # optional label on that loop edge
```

At least two nodes per diagram; every node needs an anchor **and** a summary.
A node whose anchor doesn't resolve is dangling (drift + verify failure). Node
types map to the editorial palette (start/step/decision/output/stop). Clicking a
node swaps the panel to the anchored doc section or code slice.

**Compose each diagram with the `diagram-design` skill.** The Atlas engine draws
the SVG for you — fixed geometry, fixed palette, fixed vertical flow — so its
style guide, connector geometry, and output contract are all out of scope here.
What transfers is the part you actually control, the composition, and it is worth
invoking the skill for:

- **Earn the diagram.** Its opening test: would the reader learn more from this
  than from the doc's own prose? Only flow-heavy docs qualify — hence 2–4
  diagrams, not one per doc.
- **Hold its complexity budget: 9 nodes max.** Past that, split into an overview
  diagram plus a detail diagram on the deeper doc, rather than one wall of boxes.
- **Every node is one distinct idea.** Two steps that always travel together are
  one node. Two nodes that anchor to the same heading probably are too.
- **Every edge carries information.** The engine chains steps in order for free;
  add `loop_to` only for a real revision loop, and give it a `when` label that
  says what makes it fire.
- **Run its remove test before you commit the YAML** — can a node be merged, an
  edge dropped, a label shortened? The diagram is done when nothing can come out.

Its universal anti-patterns are the failure mode to watch here: identical nodes
with no hierarchy, and a `decision` node used for something that doesn't actually
branch.

## `claims.yaml` — deterministic quantitative checks

```yaml
- id: <claim-id>             # unique
  doc: <doc-id>              # the doc making the claim
  quote: "26 route modules"  # the claim as written, for inline marking
  counter: { type: file_count, glob: "src/api/routes/*.ts" }
  expected: 26               # what the DOC says
  note: "optional provenance"
```

Counter types: `file_count` (`glob:`), `symbol_count` (`path:`, optional
`exported_only: true`), `line_count` (`path:`). No NLP — every claim is
hand-curated and every counter is a deterministic measurement.

Three outcomes: **pass** (doc and tree agree), **fail** (drift — reported on
`/drift`, *not* fatal), **error** (the counter itself crashes: a bad glob/path —
a curation bug that *is* fatal to `verify.py`). Always verify the real count
yourself before setting `expected`, and set `expected` to what the doc claims so
genuine drift shows up rather than being silently "corrected".

## What `verify.py` fails on (curation errors — fatal)

- a `depth: full` doc with no `atlas.yaml` summary, or a summary for an unknown doc;
- an overview for an unknown category;
- a journey stop or diagram node whose anchor doesn't resolve;
- a claim counter that errors (bad glob/path);
- a config include-glob that matches no files.

Content **drift** (claim mismatches, broken doc→code references) is reported on
`/drift` and never fails verification — that is the Atlas doing its job.
