#!/usr/bin/env python3
"""
build_explorer.py — GENERIC discovery skeleton for the Skills & Prompts Explorer.

Copy this to <target-repo>/docs/explorer/build_explorer.py and ADAPT the discovery
layer to the repo's real conventions (found in Phase 0). It walks the repo, finds
every skill/agent/prompt artifact, extracts *mechanical* metadata, and writes
`explorer-manifest.json`.

Out of the box it auto-detects the common conventions:
  - Claude Skills folders:   **/SKILL.md  (YAML frontmatter: name, description,
                             argument-hint, user-invocable, allowed-tools, ...)
  - Slash commands:          .claude/commands/**/*.md  and  **/commands/*.md
  - Subagents:               .claude/agents/*.md  and  **/agents/*.md  (frontmatter:
                             name, description, model, tools)
  - Instruction docs:        CLAUDE.md, AGENTS.md, SOUL.md, .cursorrules,
                             .github/copilot-instructions.md
  - Prompt files:            prompts/**/*.(md|txt|yaml|yml),  *.prompt(.md|.yaml|.yml),
                             *.prompty,  *.jinja
  - Embedded prompts:        const NAME = `…` / export const *Prompt / SYSTEM_PROMPT /
                             *_TEMPLATE / build*Prompt(...) over a configurable file
                             list (see EMBEDDED_FILES) — records path AND line range.

WHERE TO ADAPT (search for "ADAPT"):
  1. EMBEDDED_FILES  — list the source files that hold named prompt literals/builders.
  2. CATEGORY_FOR    — how an artifact's category is derived (default: parent dir / "skills").
  3. parse_registry()— if the repo encodes structured metadata (model, tools, output
     schema, strengths/limitations) in a TS/JSON registry, parse it and merge by id
     (see examples/claude-for-legal.build_explorer.py for definitions.ts/profiles.ts).
  4. discover_*()    — add/adjust a discoverer for any convention unique to the repo.

Design rules:
  - Stdlib only. PyYAML used *if importable* (frontmatter + YAML), tolerant fallback otherwise.
  - The manifest is the GENERATED, mechanical index. Hand-authored workflow graphs and
    assessments live in docs/explorer/data/*.json and are merged by id at runtime.
  - Nothing is invented: descriptions, headings, tools, and line ranges come from real files.

Run:  python3 docs/explorer/build_explorer.py
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone

# ── Locate repo root (this file lives at <repo>/docs/explorer/) ──────────────
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))

try:
    import yaml  # type: ignore
    HAVE_YAML = True
except Exception:  # pragma: no cover - tolerant fallback
    HAVE_YAML = False

# Directories never worth walking.
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist",
             "build", ".next", ".cache", "vendor", "target", "docs/explorer"}

# ── ADAPT (1): source files that contain named prompt literals/builders. ──────
# Leave empty to skip embedded-prompt discovery, or list repo-relative paths.
EMBEDDED_FILES: list[str] = [
    # "src/agents/system-prompt.ts",
    # "scripts/orchestrate.py",
]


# ── Generic helpers (reuse as-is) ─────────────────────────────────────────────
def rel(path: str) -> str:
    return os.path.relpath(path, REPO).replace(os.sep, "/")


def read(path: str) -> str:
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        return fh.read()


def extract_headings(body: str, limit: int = 60):
    """Markdown headings [{level, text}], skipping fenced code blocks so `#`
    comments inside ``` fences are not mistaken for headings."""
    out, in_fence = [], False
    for line in body.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = re.match(r"^(#{1,4})\s+(.*?)\s*$", line)
        if not m:
            continue
        text = m.group(2).strip().strip("`")
        if not text:
            continue
        out.append({"level": len(m.group(1)), "text": text})
        if len(out) >= limit:
            break
    return out


def first_sentence(text: str, maxlen: int = 320) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return ""
    m = re.search(r"(.+?[.!?])(\s|$)", text)
    s = m.group(1) if m else text
    if len(s) > maxlen:
        s = s[: maxlen - 1].rstrip() + "…"
    return s


def line_of(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(s).lower()).strip("-")


def parse_frontmatter(text: str):
    m = re.match(r"---\s*\n(.*?)\n---\s*\n?", text, re.DOTALL)
    if not m:
        return {}, text
    fm_raw, rest = m.group(1), text[m.end():]
    if HAVE_YAML:
        try:
            return (yaml.safe_load(fm_raw) or {}), rest
        except Exception:
            pass
    data = {}
    for ln in fm_raw.splitlines():
        if ":" in ln and not ln.startswith((" ", "\t")):
            k, v = ln.split(":", 1)
            data[k.strip()] = v.strip()
    return data, rest


def first_h1(body: str):
    m = re.search(r"^#\s+(.+?)\s*$", body, re.MULTILINE)
    return m.group(1).strip() if m else None


def listify_tools(tools):
    if isinstance(tools, str):
        return [t.strip() for t in re.split(r"[,\n]", tools) if t.strip()]
    return tools or []


def walk_files(root=REPO):
    for dirpath, dirs, files in os.walk(root):
        rp = rel(dirpath)
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and rel(os.path.join(dirpath, d)) not in SKIP_DIRS]
        if any(seg in SKIP_DIRS for seg in rp.split("/")):
            continue
        for f in files:
            yield os.path.join(dirpath, f)


# ── ADAPT (2): category derivation. Default: nearest meaningful parent dir. ───
def category_for(path: str, default: str) -> str:
    parts = rel(path).split("/")
    # e.g. <plugin>/skills/<name>/SKILL.md -> "<plugin>";  skills/<name>/SKILL.md -> "skills"
    if "skills" in parts:
        i = parts.index("skills")
        return parts[i - 1] if i > 0 else "skills"
    if "commands" in parts:
        return "commands"
    if "agents" in parts:
        return "agents"
    return default


def bundled_resources(skill_dir: str, exclude: str):
    res = []
    for dp, _dirs, files in os.walk(skill_dir):
        for f in sorted(files):
            p = os.path.join(dp, f)
            if os.path.abspath(p) == os.path.abspath(exclude):
                continue
            res.append(rel(p))
    return res


# ── Discoverers (adjust as needed) ────────────────────────────────────────────
def discover_skill_folders():
    out = []
    for path in walk_files():
        if os.path.basename(path) != "SKILL.md":
            continue
        skill_dir = os.path.dirname(path)
        text = read(path)
        fm, body = parse_frontmatter(text)
        name = str(fm.get("name") or os.path.basename(skill_dir))
        art = {
            "id": "skill-" + slugify(rel(skill_dir)),
            "title": first_h1(body) or name,
            "kind": "skill",
            "category": category_for(path, "skills"),
            "source_path": rel(path),
            "format": "SKILL.md (YAML frontmatter)",
            "description": first_sentence(str(fm.get("description", ""))),
            "description_full": str(fm.get("description", "")).strip(),
            "headings": extract_headings(body),
            "body_chars": len(text),
            "frontmatter_keys": sorted(fm.keys()),
        }
        inv = {}
        if "user-invocable" in fm:
            v = fm["user-invocable"]
            inv["user_invocable"] = (v.lower() != "false") if isinstance(v, str) else bool(v)
        if "argument-hint" in fm:
            inv["argument_hint"] = str(fm["argument-hint"])
        if inv:
            art["invocation"] = inv
        if "allowed-tools" in fm:
            art["tools"] = listify_tools(fm["allowed-tools"])
        if "version" in fm:
            art["version"] = str(fm["version"])
        res = bundled_resources(skill_dir, path)
        if res:
            art["resources"] = res
        out.append(art)
    return out


def discover_commands():
    out = []
    for path in walk_files():
        rp = rel(path)
        if not rp.endswith(".md"):
            continue
        if "/commands/" not in ("/" + rp) and not rp.startswith("commands/"):
            continue
        if ".claude/commands/" not in ("/" + rp) and "/commands/" not in ("/" + rp):
            continue
        text = read(path)
        fm, body = parse_frontmatter(text)
        name = os.path.basename(path)[:-3]
        out.append({
            "id": "command-" + slugify(rp),
            "title": first_h1(body) or ("/" + name),
            "kind": "slash-command",
            "category": "commands",
            "source_path": rp,
            "format": "slash command (markdown)",
            "description": first_sentence(str(fm.get("description", "")) or body),
            "headings": extract_headings(body),
            "body_chars": len(text),
            "invocation": {"user_invocable": True,
                           **({"argument_hint": str(fm["argument-hint"])} if fm.get("argument-hint") else {})},
            **({"tools": listify_tools(fm["allowed-tools"])} if fm.get("allowed-tools") else {}),
        })
    return out


def discover_agents():
    out = []
    for path in walk_files():
        rp = rel(path)
        if not rp.endswith(".md"):
            continue
        segs = rp.split("/")
        if "agents" not in segs:
            continue
        if os.path.basename(path) in ("README.md",):
            continue
        text = read(path)
        fm, body = parse_frontmatter(text)
        if not (fm.get("name") or fm.get("description")):
            continue  # not an agent definition
        name = str(fm.get("name") or os.path.basename(path)[:-3])
        art = {
            "id": "agent-" + slugify(rp),
            "title": first_h1(body) or name,
            "kind": "agent",
            "category": category_for(path, "agents"),
            "source_path": rp,
            "format": "agent markdown (YAML frontmatter)",
            "description": first_sentence(str(fm.get("description", ""))),
            "description_full": str(fm.get("description", "")).strip(),
            "headings": extract_headings(body),
            "body_chars": len(text),
        }
        if fm.get("model"):
            art["model"] = str(fm["model"])
        if fm.get("tools"):
            art["tools"] = listify_tools(fm["tools"])
        out.append(art)
    return out


INSTRUCTION_DOCS = ["CLAUDE.md", "AGENTS.md", "SOUL.md", ".cursorrules",
                    ".github/copilot-instructions.md"]


def discover_instruction_docs():
    out = []
    for relpath in INSTRUCTION_DOCS:
        path = os.path.join(REPO, relpath)
        if not os.path.exists(path):
            continue
        text = read(path)
        title = first_h1(text) or os.path.basename(relpath)
        out.append({
            "id": "doc-" + slugify(relpath),
            "title": title,
            "kind": "instruction-doc",
            "category": "instruction docs",
            "source_path": relpath,
            "format": "markdown",
            "description": first_sentence(re.sub(r"^#.*$", "", text, count=1, flags=re.MULTILINE)),
            "headings": extract_headings(text, limit=80),
            "body_chars": len(text),
        })
    return out


PROMPT_FILE_RE = re.compile(r"\.(prompt\.(md|ya?ml)|prompty|jinja2?)$", re.IGNORECASE)


def discover_prompt_files():
    out = []
    for path in walk_files():
        rp = rel(path)
        in_prompts_dir = rp.startswith("prompts/") or "/prompts/" in ("/" + rp)
        is_prompt_file = bool(PROMPT_FILE_RE.search(rp))
        if not (is_prompt_file or (in_prompts_dir and rp.endswith((".md", ".txt", ".yaml", ".yml")))):
            continue
        text = read(path)
        fm, body = parse_frontmatter(text) if rp.endswith((".md", ".yaml", ".yml")) else ({}, text)
        out.append({
            "id": "prompt-" + slugify(rp),
            "title": first_h1(body) or os.path.basename(path),
            "kind": "prompt-template",
            "category": "prompts",
            "source_path": rp,
            "format": "prompt file",
            "description": first_sentence(str(fm.get("description", "")) or body),
            "headings": extract_headings(body),
            "body_chars": len(text),
        })
    return out


# ── Embedded prompts in code (over EMBEDDED_FILES) ────────────────────────────
CONST_PROMPT_RE = re.compile(
    r"(?:export\s+)?const\s+([A-Za-z_][A-Za-z0-9_]*(?:_PROMPT|Prompt|_TEMPLATE|Template)[A-Za-z0-9_]*)\s*=\s*`")
PY_PROMPT_RE = re.compile(
    r'^([A-Z][A-Z0-9_]*(?:_PROMPT|_TEMPLATE))\s*[:=]', re.MULTILINE)


def _template_body(text: str, start: int):
    i, n = start + 1, len(text)
    while i < n:
        if text[i] == "\\":
            i += 2
            continue
        if text[i] == "`":
            return text[start + 1:i], i
        i += 1
    return text[start + 1:], n


def humanize(name: str) -> str:
    if "_" in name:
        return name.replace("_", " ").title()
    words = re.findall(r"[A-Z]?[a-z0-9]+|[A-Z]+(?![a-z])", name)
    return " ".join(w.capitalize() for w in words)


def discover_embedded():
    out = []
    for relpath in EMBEDDED_FILES:
        path = os.path.join(REPO, relpath)
        if not os.path.exists(path):
            continue
        text = read(path)
        # JS/TS template-literal prompts
        for m in CONST_PROMPT_RE.finditer(text):
            name = m.group(1)
            tick = text.index("`", m.end() - 1)
            body, end_idx = _template_body(text, tick)
            out.append({
                "id": "embedded-" + slugify(name),
                "title": humanize(name),
                "kind": "system-prompt",
                "category": "embedded prompts",
                "source_path": relpath,
                "line_start": line_of(text, m.start()),
                "line_end": line_of(text, end_idx),
                "format": "embedded literal (template)",
                "description": "",
                "headings": extract_headings(body),
                "body_chars": len(body),
                "embedded": True,
            })
        # Python prompt constants (assigned a string/triple-quoted block)
        for m in PY_PROMPT_RE.finditer(text):
            name = m.group(1)
            out.append({
                "id": "embedded-" + slugify(name),
                "title": humanize(name),
                "kind": "system-prompt",
                "category": "embedded prompts",
                "source_path": relpath,
                "line_start": line_of(text, m.start()),
                "line_end": line_of(text, m.start()),  # ADAPT: widen to the literal's end
                "format": "embedded literal (python)",
                "description": "",
                "headings": [],
                "body_chars": 0,
                "embedded": True,
            })
    return out


# ── ADAPT (3): structured registry metadata (model/tools/output schema/etc). ──
def parse_registry():
    """Return {artifact_id: {extra mechanical fields}} from a repo registry, or {}.
    See examples/claude-for-legal.build_explorer.py for a TS-registry parser that
    merges model/maxTurns/tools/outputFormat and editorial strengths/limitations."""
    return {}


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    artifacts = (
        discover_skill_folders()
        + discover_agents()
        + discover_commands()
        + discover_prompt_files()
        + discover_embedded()
        + discover_instruction_docs()
    )

    registry = parse_registry()
    for a in artifacts:
        if a["id"] in registry:
            a.update(registry[a["id"]])

    # dedupe by id (and by source_path for safety)
    seen, deduped = set(), []
    for a in artifacts:
        if a["id"] in seen:
            print(f"  WARNING: duplicate id {a['id']} ({a['source_path']}) — skipped")
            continue
        seen.add(a["id"])
        deduped.append(a)

    counts, cat_counts = {}, {}
    for a in deduped:
        counts[a["kind"]] = counts.get(a["kind"], 0) + 1
        cat_counts[a["category"]] = cat_counts.get(a["category"], 0) + 1

    manifest = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "repo": os.path.basename(REPO),
        "generator": "docs/explorer/build_explorer.py",
        "pyyaml": HAVE_YAML,
        "coverage": {
            "searched_patterns": [
                "**/SKILL.md (Claude Skills folders; YAML frontmatter)",
                ".claude/commands/**/*.md and **/commands/*.md (slash commands)",
                ".claude/agents/*.md and **/agents/*.md (subagent definitions)",
                "instruction docs: " + ", ".join(INSTRUCTION_DOCS),
                "prompt files: prompts/**, *.prompt(.md|.yaml), *.prompty, *.jinja",
                "embedded prompts scanned in: " + (", ".join(EMBEDDED_FILES) or "(none configured)"),
            ],
            "counts_by_kind": counts,
            "counts_by_category": cat_counts,
            "total": len(deduped),
        },
        "artifacts": deduped,
    }

    out_path = os.path.join(HERE, "explorer-manifest.json")
    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(manifest, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    print(f"Wrote {rel(out_path)}")
    print(f"  total artifacts: {len(deduped)}")
    for k, v in sorted(counts.items()):
        print(f"    {k}: {v}")
    print(f"  PyYAML available: {HAVE_YAML}")
    if not deduped:
        print("  NOTE: nothing found — adapt the discover_*() functions to this repo's conventions.")


if __name__ == "__main__":
    sys.exit(main())
