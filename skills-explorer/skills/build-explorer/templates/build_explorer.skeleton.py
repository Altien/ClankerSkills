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

# ── ADAPT (1): embedded-prompt scanning. ─────────────────────────────────────
# By DEFAULT the scanner auto-walks source files (SCAN_EXTS) for in-code prompts —
# named template-literal / triple-quoted constants, prompt builder functions,
# PromptTemplate / from_template / from_messages calls, and inline role:"system"
# content. Set EMBEDDED_FILES to a non-empty list to scan ONLY those files
# instead (narrower, no walk). Set EMBEDDED_SCAN = False to disable entirely.
EMBEDDED_SCAN = True
EMBEDDED_FILES: list[str] = [
    # "src/agents/system-prompt.ts",
    # "scripts/orchestrate.py",
]
# Source extensions auto-walked when EMBEDDED_FILES is empty.
SCAN_EXTS = (".py", ".ts", ".tsx", ".js", ".jsx", ".mjs")
# Skip generated/minified/test files during the auto-walk (still scanned if you
# name them explicitly in EMBEDDED_FILES).
SCAN_SKIP_RE = re.compile(r"\.(min|bundle)\.js$|\.d\.ts$|\.(test|spec)\.[jt]sx?$")
# Structural matches (builders, from_template, role:system) with no prompt-y
# name must have a body at least this long to count — cuts false positives.
EMBEDDED_MIN_BODY = 40
# Even a prompt-y NAMED literal must clear this short floor (drops `x = "hi"`).
NAMED_MIN_BODY = 16


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


# ── Embedded prompts in code (auto-scans source by default) ───────────────────
# A "prompt-y" identifier: contains prompt / template / instruction / system /
# persona / preamble. Used to accept a literal on its NAME alone (no length gate).
PROMPTY_NAME_RE = re.compile(
    r"(?i)(prompt|template|instruction|persona|preamble|sys[_-]?msg|system[_-]?message)")
# JS/TS: const NAME = `…`   (also `let`/`var`, optional `export`)
JS_CONST_RE = re.compile(
    r"(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*`")
# JS/TS: export function buildXxxPrompt(...) { … }
JS_BUILDER_RE = re.compile(r"(?:export\s+)?function\s+(build[A-Za-z0-9_]*Prompt)\s*\(")
# Python: NAME = (r/f/rf)? '''…''' | """…"""   (top-level or indented)
PY_TRIPLE_RE = re.compile(
    r'^([ \t]*)([A-Za-z_][\w]*)\s*=\s*(?:[rRfFuUbB]{1,2})?("""|\'\'\')', re.MULTILINE)
# LangChain-style builders: PromptTemplate( | *.from_template( | *.from_messages(
PY_BUILDER_RE = re.compile(
    r"(?:(\w+)\s*=\s*)?(?:[\w.]*Prompt(?:Template)?|\w*\.from_template|\w*\.from_messages)\s*\(")
# Inline chat messages: role:"system"  /  ("system", "…")
ROLE_SYSTEM_RE = re.compile(r"""['"]?role['"]?\s*[:=]\s*['"]system['"]|\(\s*['"]system['"]\s*,""")
# Strong system/instruction-prompt OPENERS — let the scanner accept a JS/TS
# template literal on its CONTENT when the identifier isn't prompt-shaped
# (real prompts are often named EXTRACTION_SYSTEM / SYSTEM / systemContent,
# whose bodies still begin "You are …").
PROMPT_OPENER_RE = re.compile(
    r"(?i)^(you are|you will|you must|your task|your job|your role|act as)\b")


def _read_string_literal(text: str, i: int):
    """From the next quote at/after i, return (body, end_index) for a JS/Python
    string literal: backtick, triple-quote, or single/double quote. None if none."""
    n = len(text)
    while i < n and text[i] not in "`\"'":
        if text[i] == ")" or text[i] == "\n" and text[i - 1:i] == "\n":
            pass
        i += 1
        if i - 0 > n:
            return None
    if i >= n:
        return None
    q = text[i]
    if q == "`":
        body, end = _template_body(text, i)
        return body, end
    if text[i:i + 3] in ('"""', "'''"):
        triple = text[i:i + 3]
        end = text.find(triple, i + 3)
        end = end if end != -1 else n
        return text[i + 3:end], end + 2
    j = i + 1
    while j < n:
        if text[j] == "\\":
            j += 2
            continue
        if text[j] == q:
            return text[i + 1:j], j
        if text[j] == "\n":
            break
        j += 1
    return text[i + 1:j], j


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


def _brace_body(text: str, start: int):
    """From the opening brace at `start`, return (inner_body, end_index) of its
    matching close brace. Naive depth counter — adequate for prompt-builder fns."""
    depth, i, n = 0, start, len(text)
    while i < n:
        c = text[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[start + 1:i], i
        i += 1
    return text[start + 1:], n


def humanize(name: str) -> str:
    if not name:
        return "Embedded prompt"
    if "_" in name:
        return name.replace("_", " ").title()
    words = re.findall(r"[A-Z]?[a-z0-9]+|[A-Z]+(?![a-z])", name)
    return " ".join(w.capitalize() for w in words) or name


def _embedded_targets():
    """The files to scan: EMBEDDED_FILES verbatim if set, else an auto-walk of
    SCAN_EXTS. Returns (relpaths, scanned_mode_str)."""
    if EMBEDDED_FILES:
        return [p for p in EMBEDDED_FILES
                if os.path.exists(os.path.join(REPO, p))], "explicit list"
    rels = []
    for path in walk_files():
        rp = rel(path)
        if rp.endswith(SCAN_EXTS) and not SCAN_SKIP_RE.search(rp):
            rels.append(rp)
    return rels, "auto-walk"


def discover_embedded():
    out, seen = [], set()
    if not EMBEDDED_SCAN:
        return out, 0
    targets, _mode = _embedded_targets()

    def emit(name, relpath, start_line, end_line, body, kind, fmt):
        if name and len(name) <= 2:      # 1–2 char vars (p, x) → treat as unnamed
            name = ""
        slug = slugify(name) if name else (slugify(relpath) + "-l" + str(start_line))
        aid = "embedded-" + slug
        if aid in seen:
            aid = aid + "-l" + str(start_line)
            if aid in seen:
                return
        seen.add(aid)
        out.append({
            "id": aid,
            "title": humanize(name) or (os.path.basename(relpath) + f" :{start_line}"),
            "kind": kind,
            "category": "embedded prompts",
            "source_path": relpath,
            "line_start": start_line,
            "line_end": max(end_line, start_line),
            "format": fmt,
            "description": first_sentence(re.sub(r"\s+", " ", body)[:400]) if body else "",
            "headings": extract_headings(body) if body else [],
            "body_chars": len(body or ""),
            "embedded": True,
        })

    for relpath in targets:
        path = os.path.join(REPO, relpath)
        try:
            text = read(path)
        except Exception:
            continue
        is_py = relpath.endswith(".py")

        if not is_py:
            # JS/TS: named template-literal consts
            for m in JS_CONST_RE.finditer(text):
                name = m.group(1)
                tick = text.index("`", m.end() - 1)
                body, end_idx = _template_body(text, tick)
                stripped = body.strip()
                # Accept on a prompt-y NAME or a strong system-prompt OPENER in the
                # body. Drop assembly fragments that start with an interpolation
                # (`${columnPrompt}…`) — those are wrappers, not authored prompts.
                if not (PROMPTY_NAME_RE.search(name) or PROMPT_OPENER_RE.match(stripped)):
                    continue
                if stripped.startswith("${"):
                    continue
                if len(stripped) < NAMED_MIN_BODY:
                    continue
                emit(name, relpath, line_of(text, m.start()), line_of(text, end_idx),
                     body, "system-prompt", "embedded literal (TS/JS template)")
            # JS/TS: prompt builder functions — capture the whole fn body so the
            # artifact carries a real line range and rendered excerpt.
            for m in JS_BUILDER_RE.finditer(text):
                name = m.group(1)
                brace = text.find("{", m.end())
                body, end_idx = "", m.end()
                if brace != -1:
                    body, end_idx = _brace_body(text, brace)
                emit(name, relpath, line_of(text, m.start()), line_of(text, end_idx),
                     body, "prompt-template", "embedded prompt builder (fn)")
        else:
            # Python: named triple-quoted assignments
            for m in PY_TRIPLE_RE.finditer(text):
                name = m.group(2)
                lit = _read_string_literal(text, m.start(len(m.groups())))
                quote_at = text.index(m.group(3), m.start())
                lit = _read_string_literal(text, quote_at)
                body = lit[0] if lit else ""
                end_line = line_of(text, lit[1]) if lit else line_of(text, m.start())
                prompty = bool(PROMPTY_NAME_RE.search(name))
                if prompty and len(body.strip()) < NAMED_MIN_BODY:
                    continue
                if not prompty and len(body) < EMBEDDED_MIN_BODY:
                    continue
                emit(name, relpath, line_of(text, m.start()), end_line,
                     body, "system-prompt", "embedded literal (python)")
            # Python: PromptTemplate / from_template / from_messages
            for m in PY_BUILDER_RE.finditer(text):
                name = m.group(1) or ""
                lit = _read_string_literal(text, m.end())
                body = lit[0] if lit else ""
                if len(body) < EMBEDDED_MIN_BODY and not PROMPTY_NAME_RE.search(name):
                    continue
                end_line = line_of(text, lit[1]) if lit else line_of(text, m.end())
                emit(name, relpath, line_of(text, m.start()), end_line,
                     body, "prompt-template", "embedded prompt (PromptTemplate)")

        # Any language: inline role:"system" message content
        for m in ROLE_SYSTEM_RE.finditer(text):
            lit = _read_string_literal(text, m.end())
            body = lit[0] if lit else ""
            if len(body) < EMBEDDED_MIN_BODY:
                continue
            emit("", relpath, line_of(text, m.start()),
                 line_of(text, lit[1]) if lit else line_of(text, m.end()),
                 body, "system-prompt", "embedded system message (role:system)")

    return out, len(targets)


# ── ADAPT (3): structured registry metadata (model/tools/output schema/etc). ──
def parse_registry():
    """Return {artifact_id: {extra mechanical fields}} from a repo registry, or {}.
    See examples/claude-for-legal.build_explorer.py for a TS-registry parser that
    merges model/maxTurns/tools/outputFormat and editorial strengths/limitations."""
    return {}


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    embedded, scanned_files = discover_embedded()
    artifacts = (
        discover_skill_folders()
        + discover_agents()
        + discover_commands()
        + discover_prompt_files()
        + embedded
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
                ("embedded prompts in code: " + (
                    "DISABLED" if not EMBEDDED_SCAN else
                    ("explicit list (" + ", ".join(EMBEDDED_FILES) + ")") if EMBEDDED_FILES else
                    f"auto-scanned {scanned_files} source files ({', '.join(SCAN_EXTS)}) "
                    "for named prompt/template literals, builder fns, "
                    "PromptTemplate/from_template/from_messages, and role:system content")),
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
    if EMBEDDED_SCAN:
        mode = "explicit list" if EMBEDDED_FILES else f"auto-walk of {scanned_files} source files"
        print(f"  embedded-prompt scan: {mode} ({counts.get('system-prompt', 0)} system-prompt + "
              f"{counts.get('prompt-template', 0)} prompt-template found)")
    else:
        print("  embedded-prompt scan: DISABLED (set EMBEDDED_SCAN = True to scan in-code prompts)")
    if not deduped:
        print("  NOTE: nothing found — adapt the discover_*() functions to this repo's conventions.")


if __name__ == "__main__":
    sys.exit(main())
