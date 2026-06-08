# Authoring spec — curated explorer data fragments

Each batch author writes ONE JSON file at `docs/explorer/data/<batch>.json`.
Fragments are merged by `python3 docs/explorer/assemble_data.py` into
`assets/explorer-data.js`. The mechanical manifest (`explorer-manifest.json`)
is a separate, generated source — never copy mechanical fields (headings,
tools, mcp servers) into your fragment; author only editorial content.

## Fragment shape

```json
{
  "artifacts": {
    "<artifact-id>": {
      "summary": "1-2 sentence lede, plain language, specific to THIS artifact.",
      "when_to_use": "the situation to reach for it.",
      "assessment": {
        "purpose": "1-2 sentences: what it actually does.",
        "good_at": ["2-4 concrete strengths grounded in the real sections"],
        "use_when": "the situation to reach for it.",
        "avoid": ["2-4 real out-of-scope / anti-pattern items from the source"],
        "signals": ["optional; 3-6 quality signals you observed (self-checks, gates, tool scoping, state files)"],
        "limits": ["2-4 real caveats / hard guardrails / disclaimers quoted-in-spirit from the source"]
      },
      "graph": { "nodes": [ ... ] },
      "does_not_do": ["2-5 items, from the skill's 'What this skill does not do' section when present"],
      "references": [{ "path": "repo/relative/path.md", "label": "human label", "note": "optional" }],
      "inputs":  [{ "name": "...", "type": "...", "desc": "...", "required": true }],
      "outputs": [{ "name": "...", "type": "...", "desc": "..." }]
    }
  }
}
```

`inputs`/`outputs` are OPTIONAL — use them for the programmatic aspects: state
files the skill reads/writes (registers, trackers, matter workspaces, config
CLAUDE.md paths), required arguments, and produced files/reports. Name real
paths/formats from the source; never invent.

## Graph rules (the verifier enforces these)

Node shape:

```json
{ "id": "s1", "type": "start|step|decision|output",
  "label": "short", "desc": "optional 1-line", "num": 1,
  "chips": ["fan-out", "pills"],
  "tag": "amber conditional label",
  "stop": "when this branches to STOP / route out",
  "loopTo": { "id": "s0", "when": "label" },
  "skipTo": { "id": "out", "when": "label" },
  "srcHeading": "EXACT heading text from the source file",
  "srcFocus": "verbatim substring of the line where THIS node's item starts",
  "note": "authored 12-28 word summary (REQUIRED on every step/decision node)" }
```

1. Exactly ONE `start` and ONE `output` node per graph.
2. Every `loopTo`/`skipTo` target id must exist in the graph.
3. **Every `step`/`decision` node MUST set `srcHeading` to the EXACT text of a
   real heading in the source file** (copy it verbatim — the text after the
   `#`s, including numbering). If the source has NO markdown headings at all
   (cookbook YAML system prompts, embedded python prompts), set
   `"srcWhole": true` on the step nodes instead. A node with neither will dump
   the whole file into the panel and FAIL the build.
4. **When two or more nodes anchor to the SAME `srcHeading`** (a thin skill
   whose whole process lives under one `## Instructions` list), each of those
   nodes MUST also set `srcFocus`: a short verbatim substring (copied exactly)
   of the line inside that section where this node's own item begins —
   typically the start of its numbered list item. The panel then slices that
   one item instead of showing siblings an identical snippet. `srcFocus` also
   works on `srcWhole` nodes to focus a heading-less prompt. The assembler and
   verifier both fail on shared headings without focus, and on a focus string
   that does not occur verbatim.
5. **Every `step`/`decision` node MUST carry an authored `note`**: one
   sentence, 12-28 words, specific to that step in that artifact, naming the
   concrete things it checks/produces. NOT the section's opening line, NOT a
   placeholder ("Step in the X workflow"), NOT "see the source". ≥ 20 chars.
   `start`/`output` terminals are exempt.
6. 5-9 step nodes is the sweet spot. Model the REAL process order; use
   `decision`+`stop` for gates that halt or route out (unconfigured playbook →
   stop; scope check fails → stop), `loopTo` for real revision loops, `chips`
   for real fan-outs (categories, modes, columns).
7. Don't make a node for every heading — boilerplate sections shared by all
   skills (Matter context, Destination check) can be ONE combined "context &
   guardrails" step anchored to one of those headings.
8. Plain text everywhere. No markdown in labels/notes/assessment strings.

## Grounding rules

- Read the WHOLE source file before writing its entry.
- `good_at` ← the skill's real capabilities/modes/frameworks.
- `avoid`/`limits`/`does_not_do` ← "What this skill does not do", "Guardrails",
  scope checks, disclaimers ("screening call, not legal advice"), config gates.
- `signals` ← real quality machinery: cold-start config gate, playbook-driven
  positions, privilege destination check, schema-validated JSON output,
  read-only tool scoping, register/tracker state files, human-review gates.
- Mark nothing as authored that you copied mechanically; never present a
  guess — if the source doesn't say it, leave the field out.
