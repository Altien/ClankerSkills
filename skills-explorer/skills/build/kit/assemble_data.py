#!/usr/bin/env python3
"""
assemble_data.py — merge the authored fragments in docs/explorer/data/*.json
into assets/explorer-data.js (the curated layer the app merges by id).

The fragments are the AUTHORED source of truth; this script only validates and
concatenates them. Run after editing any fragment:

    python3 docs/explorer/assemble_data.py
    node docs/explorer/verify.cjs
"""

from __future__ import annotations

import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def fail(msg: str):
    print("ERROR: " + msg)
    sys.exit(1)


def validate_graph(aid: str, g: dict):
    nodes = g.get("nodes") or []
    ids = [n.get("id") for n in nodes]
    if len(set(ids)) != len(ids):
        fail(f"{aid}: duplicate node ids")
    starts = [n for n in nodes if n.get("type") == "start"]
    outs = [n for n in nodes if n.get("type") == "output"]
    if len(starts) != 1 or len(outs) != 1:
        fail(f"{aid}: needs exactly one start and one output "
             f"(got {len(starts)}/{len(outs)})")
    idset = set(ids)
    # nodes sharing one srcHeading must each carry srcFocus (panel slices per item)
    head_counts: dict = {}
    for n in nodes:
        if n.get("type") in ("step", "decision") and n.get("srcHeading"):
            head_counts[n["srcHeading"]] = head_counts.get(n["srcHeading"], 0) + 1
    for n in nodes:
        for arc in ("loopTo", "skipTo"):
            if n.get(arc) and n[arc].get("id") not in idset:
                fail(f"{aid}: {arc} target '{n[arc].get('id')}' missing")
        if not (n.get("label") or "").strip():
            fail(f"{aid}/{n.get('id')}: every node needs a non-empty label")
        if n.get("type") in ("step", "decision"):
            if not n.get("srcHeading") and not n.get("srcWhole"):
                fail(f"{aid}/{n.get('id')}: step node needs srcHeading or srcWhole")
            if n.get("srcHeading") and head_counts.get(n["srcHeading"], 0) > 1 \
                    and not (n.get("srcFocus") or "").strip():
                fail(f"{aid}/{n.get('id')}: shares srcHeading "
                     f"'{n['srcHeading']}' with another node — needs srcFocus")
            note = (n.get("note") or n.get("desc") or "").strip()
            if len(note) < 20:
                fail(f"{aid}/{n.get('id')}: step node needs an authored note (>=20 chars)")


def main():
    artifacts: dict = {}
    notes: dict = {}
    sources: dict = {}
    for path in sorted(glob.glob(os.path.join(HERE, "data", "*.json"))):
        with open(path, "r", encoding="utf-8") as fh:
            try:
                frag = json.load(fh)
            except json.JSONDecodeError as e:
                fail(f"{os.path.basename(path)}: invalid JSON — {e}")
        for aid, entry in (frag.get("artifacts") or {}).items():
            if aid in artifacts:
                fail(f"duplicate artifact id '{aid}' "
                     f"({sources[aid]} and {os.path.basename(path)})")
            if entry.get("graph"):
                validate_graph(aid, entry["graph"])
            artifacts[aid] = entry
            sources[aid] = os.path.basename(path)
        for aid, nmap in (frag.get("notes") or {}).items():
            notes.setdefault(aid, {}).update(nmap)

    header = (
        "/* explorer-data.js — CURATED workflow graphs + editorial detail.\n"
        " *\n"
        " * GENERATED from the hand-authored fragments in docs/explorer/data/*.json by\n"
        " * assemble_data.py — edit the fragments, not this file. Merged with the\n"
        " * mechanical explorer-manifest.json (by id) at runtime; regenerating the\n"
        " * manifest never clobbers these graphs.\n"
        " *\n"
        " * RULE: when an artifact's workflow changes, update its graph fragment.\n"
        " *       when its behaviour changes, update its assessment fragment.\n"
        " */\n"
    )
    out_path = os.path.join(HERE, "assets", "explorer-data.js")
    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(header)
        fh.write("window.EXPLORER_DATA = { artifacts: ")
        fh.write(json.dumps(artifacts, indent=1, ensure_ascii=False, sort_keys=True))
        fh.write(" };\n")
        fh.write("// Per-heading authored notes for shape-derived graphs (merged in shapeGraph).\n")
        fh.write("window.EXPLORER_NOTES = ")
        fh.write(json.dumps(notes, indent=1, ensure_ascii=False, sort_keys=True))
        fh.write(";\n")

    print(f"Wrote assets/explorer-data.js — {len(artifacts)} curated artifacts, "
          f"{len(notes)} note maps, from {len(set(sources.values()))} fragments")


if __name__ == "__main__":
    main()
