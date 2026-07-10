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
import hashlib
import os
import re
import subprocess
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
# By DEFAULT the scanner auto-walks text source files for in-code prompts —
# named template-literal / triple-quoted constants, prompt builder functions,
# PromptTemplate / from_template / from_messages calls, and inline role:"system"
# content. Set EMBEDDED_FILES to a non-empty list to scan ONLY those files
# instead (narrower, no walk). Set EMBEDDED_SCAN = False to disable entirely.
EMBEDDED_SCAN = True
EMBEDDED_FILES: list[str] = [
    # "src/agents/system-prompt.ts",
    # "scripts/orchestrate.py",
]
# Embedded discovery is language-profiled, with a conservative generic fallback for
# unknown text-based source extensions. No programming language is excluded merely
# because its extension is absent from this map.
LANGUAGE_PROFILES = {
    ".py": "python", ".pyw": "python",
    ".js": "ecmascript", ".jsx": "ecmascript", ".mjs": "ecmascript",
    ".cjs": "ecmascript", ".ts": "ecmascript", ".tsx": "ecmascript",
    ".go": "go", ".rs": "rust",
    ".java": "jvm", ".kt": "jvm", ".kts": "jvm", ".scala": "jvm",
    ".cs": "dotnet", ".fs": "dotnet", ".fsx": "dotnet", ".vb": "vb",
    ".c": "c-family", ".h": "c-family", ".cc": "c-family",
    ".cpp": "c-family", ".cxx": "c-family", ".hpp": "c-family",
    ".rb": "ruby", ".php": "php", ".swift": "swift", ".dart": "dart",
    ".ex": "elixir", ".exs": "elixir", ".erl": "erlang", ".hrl": "erlang",
    ".lua": "lua", ".r": "r", ".jl": "julia", ".nim": "nim", ".zig": "zig",
    ".sh": "shell", ".bash": "shell", ".zsh": "shell", ".fish": "shell",
    ".ps1": "powershell", ".psm1": "powershell",
}
NON_SOURCE_EXTS = {
    ".md", ".markdown", ".txt", ".json", ".jsonl", ".yaml", ".yml",
    ".toml", ".xml", ".html", ".htm", ".css", ".scss", ".svg", ".csv",
    ".lock", ".sum", ".mod", ".sql",
}
MAX_SOURCE_BYTES = 2_000_000
# Skip generated/minified/test files during the auto-walk (still scanned if named
# explicitly in EMBEDDED_FILES). Every skip is recorded in coverage.
SCAN_SKIP_RE = re.compile(
    r"(?i)(\.(min|bundle)\.[^.]+$|\.d\.ts$|\.(test|spec)\.[^.]+$|"
    r"(^|/)(test|tests|testdata|fixtures|generated|dist|build|vendor)/)"
)
# Structural matches (builders, from_template, role:system) with no prompt-y
# name must have a body at least this long to count — cuts false positives.
EMBEDDED_MIN_BODY = 40
# Even a prompt-y NAMED literal must clear this short floor (drops `x = "hi"`).
NAMED_MIN_BODY = 16
SCANNER_VERSION = "polyglot-literals-v1"


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


def walk_files(root=None):
    root = root or REPO
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
            "_content": text,
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
            "_content": text,
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
            "_content": text,
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
            "_content": text,
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
            "_content": text,
        })
    return out


# ── Embedded prompts in code (polyglot, conservative, coverage-audited) ───────
IDENT_ASSIGN_RE = re.compile(r"(?m)\b([A-Za-z_$][\w$]*)\s*(?::=|=>|=|:)\s*")
PROMPT_API_RE = re.compile(
    r"(?i)\b(PromptTemplate|ChatPromptTemplate|SystemMessage|DeveloperMessage|"
    r"from_template|from_messages|build\w*prompt)\b")
ROLE_SYSTEM_RE = re.compile(
    r"(?i)(?:['\"]?role['\"]?|\bRole\b)\s*[:=]\s*['\"]system['\"]|"
    r"\(\s*['\"]system['\"]\s*,")
CONTENT_KEY_RE = re.compile(r"(?i)(?:['\"]?(content|message|text)['\"]?)\s*[:=]\s*")
PROMPT_OPENER_RE = re.compile(
    r"(?i)^(?:(?:you are|you will|you must|your task|your job|your role|act as|"
    r"respond as)\b|system:|instructions?:)")
NON_PROMPT_NAME_RE = re.compile(r"(?i)(sql|html|css|xml|svg|email)[_-]?template")
GENERIC_FIELD_NAMES = {"content", "message", "text", "value", "body", "template"}


def _normalise_symbol(name: str) -> str:
    name = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name)
    return re.sub(r"[^a-z0-9]+", "_", name.casefold()).strip("_")


def _strong_prompt_name(name: str) -> bool:
    norm = _normalise_symbol(name)
    tokens = set(norm.split("_"))
    if NON_PROMPT_NAME_RE.search(norm):
        return False
    return bool(
        "prompt" in tokens
        or "persona" in tokens
        or "preamble" in tokens
        or "instructions" in tokens
        or "instruction" in tokens
        or norm in {"system", "system_message", "system_content", "developer_message", "sys_msg"}
        or norm.endswith("_system_prompt")
    )


def _literal_kind(name: str, body: str) -> str:
    norm = _normalise_symbol(name)
    tokens = set(norm.split("_"))
    if tokens & {"user", "human", "query"}:
        return "prompt-template"
    if tokens & {"system", "developer", "persona", "preamble"}:
        return "system-prompt"
    return "system-prompt" if PROMPT_OPENER_RE.match(body.strip()) else "prompt-template"


def _mask_comments(text: str, profile: str, mask_long_literals: bool = False) -> str:
    """Mask comments and optionally prompt-sized literal interiors without moving offsets."""
    chars, i, n = list(text), 0, len(text)

    def mask_literal(start: int, end: int) -> None:
        if mask_long_literals and end - start >= NAMED_MIN_BODY:
            for index in range(start, end):
                if chars[index] not in "\r\n":
                    chars[index] = " "
    line_markers = {
        "python": ["#"], "ruby": ["#"], "shell": ["#"], "powershell": ["#"],
        "r": ["#"], "julia": ["#"], "nim": ["#"], "elixir": ["#"],
        "erlang": ["%"], "lua": ["--"], "vb": ["'"], "php": ["//", "#"],
    }.get(profile, ["//"])
    block_markers = {
        "powershell": [("<#", "#>")], "lua": [("--[[", "]]" )],
        "nim": [("#[", "]#")], "dotnet": [("/*", "*/"), ("(*", "*)")],
        "php": [("/*", "*/")],
    }.get(profile, [] if profile in {"python", "ruby", "shell", "r", "julia", "elixir", "erlang", "vb"}
          else [("/*", "*/")])
    while i < n:
        if text.startswith(('"""', "'''"), i):
            delimiter = text[i:i + 3]
            end = text.find(delimiter, i + 3)
            if end != -1:
                mask_literal(i + 3, end)
            i = n if end == -1 else end + 3
            continue
        block = next(((opening, closing) for opening, closing in block_markers
                      if text.startswith(opening, i)), None)
        if block:
            opening, closing = block
            end = text.find(closing, i + len(opening))
            end = n if end == -1 else end + len(closing)
            for j in range(i, end):
                if chars[j] not in "\r\n":
                    chars[j] = " "
            i = end
            continue
        marker = next((value for value in line_markers if text.startswith(value, i)), None)
        if marker:
            end = text.find("\n", i)
            end = n if end == -1 else end
            chars[i:end] = " " * (end - i)
            i = end
            continue
        if text[i] in {'"', "'", "`"}:
            quote, body_start, i = text[i], i + 1, i + 1
            while i < n:
                if text[i] == "\\":
                    i += 2
                elif text[i] == quote:
                    mask_literal(body_start, i)
                    i += 1
                    break
                else:
                    i += 1
            continue
        i += 1
    return "".join(chars)


def _ordinary_quoted(text: str, start: int, quote: str):
    i, n, out = start + 1, len(text), []
    escapes = {
        "n": "\n", "r": "\r", "t": "\t", "b": "\b", "f": "\f",
        "v": "\v", "a": "\a", "\\": "\\", "\"": "\"",
        "'": "'", "/": "/",
    }
    while i < n:
        if text[i] == "\\" and i + 1 < n:
            escaped = text[i + 1]
            if escaped in "01234567":
                octal = re.match(r"[0-7]{1,3}", text[i + 1:])
                assert octal is not None
                out.append(chr(int(octal.group(0), 8)))
                i += 1 + len(octal.group(0))
            elif escaped in escapes:
                out.append(escapes[escaped])
                i += 2
            elif escaped in {"x", "u", "U"}:
                width = {"x": 2, "u": 4, "U": 8}[escaped]
                digits = text[i + 2:i + 2 + width]
                if len(digits) == width and re.fullmatch(r"[0-9A-Fa-f]+", digits):
                    codepoint = int(digits, 16)
                    consumed = 2 + width
                    if (escaped == "u" and 0xD800 <= codepoint <= 0xDBFF
                            and text[i + consumed:i + consumed + 2] == "\\u"):
                        low_digits = text[i + consumed + 2:i + consumed + 6]
                        if re.fullmatch(r"[0-9A-Fa-f]{4}", low_digits or ""):
                            low = int(low_digits, 16)
                            if 0xDC00 <= low <= 0xDFFF:
                                codepoint = 0x10000 + ((codepoint - 0xD800) << 10) + low - 0xDC00
                                consumed += 6
                    if codepoint > 0x10FFFF or 0xD800 <= codepoint <= 0xDFFF:
                        out.append(text[i:i + consumed])
                    else:
                        out.append(chr(codepoint))
                    i += consumed
                else:
                    out.extend(("\\", escaped))
                    i += 2
            elif escaped in "\r\n":
                i += 2
                if escaped == "\r" and i < n and text[i] == "\n":
                    i += 1
            else:
                out.extend(("\\", escaped))
                i += 2
            continue
        if text[i] == quote:
            return "".join(out), i
        if text[i] == "\n":
            return None
        out.append(text[i])
        i += 1
    return None


def _read_literal(text: str, start: int, search_limit: int = 240,
                  allow_leading_newline: bool = True):
    """Return (body, end_index, syntax) for common polyglot string forms."""
    n, limit, i = len(text), min(len(text), start + search_limit), start
    while i < limit:
        # Rust raw string: r"..." / r#"..."# / br##"..."##
        m = re.match(r"(?:b)?r(#{0,8})\"", text[i:])
        if m:
            hashes = m.group(1)
            body_start = i + m.end()
            close = '"' + hashes
            end = text.find(close, body_start)
            if end != -1:
                return text[body_start:end], end + len(close) - 1, "rust-raw"
        # C++ raw string: R"tag(... )tag"
        m = re.match(r'R"([A-Za-z0-9_]*)\(', text[i:])
        if m:
            tag, body_start = m.group(1), i + m.end()
            close = ")" + tag + '"'
            end = text.find(close, body_start)
            if end != -1:
                return text[body_start:end], end + len(close) - 1, "cpp-raw"
        # PowerShell here-strings.
        if text[i:i + 2] in {'@"', "@'"}:
            quote, body_start = text[i + 1], i + 2
            close_re = re.compile(r"(?m)^" + re.escape(quote + "@") + r"\s*$")
            close = close_re.search(text, body_start)
            if close:
                return text[body_start:close.start()], close.end() - 1, "powershell-here"
        # Python/Java/C# triple-quoted strings.
        if text[i:i + 3] in {'"""', "'''"}:
            delimiter, body_start = text[i:i + 3], i + 3
            end = text.find(delimiter, body_start)
            if end != -1:
                return text[body_start:end], end + 2, "triple-quoted"
        # Go/JS template or raw literal.
        if text[i] == "`":
            end = i + 1
            while end < n:
                if text[end] == "\\":
                    end += 2
                    continue
                if text[end] == "`":
                    return text[i + 1:end], end, "backtick"
                end += 1
            return None
        # Ruby/shell-style heredoc.
        m = re.match(r"<<[-~]?\s*['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?", text[i:])
        if m:
            token, body_start = m.group(1), i + m.end()
            if body_start < n and text[body_start] == "\r":
                body_start += 1
            if body_start < n and text[body_start] == "\n":
                body_start += 1
            close = re.search(r"(?m)^\s*" + re.escape(token) + r"\s*$", text[body_start:])
            if close:
                end = body_start + close.start()
                return text[body_start:end], body_start + close.end() - 1, "heredoc"
        # C# verbatim string.
        if text[i:i + 2] == '@"':
            j, out = i + 2, []
            while j < n:
                if text[j:j + 2] == '""':
                    out.append('"')
                    j += 2
                elif text[j] == '"':
                    return "".join(out), j, "csharp-verbatim"
                else:
                    out.append(text[j])
                    j += 1
            return None
        if text[i] in "\"'":
            ordinary = _ordinary_quoted(text, i, text[i])
            if ordinary:
                return ordinary[0], ordinary[1], "quoted"
        if text[i] == ";" or (text[i] in "\r\n" and not allow_leading_newline) \
                or text[i:i + 2] == "\n\n":
            return None
        i += 1
    return None


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


def _candidate_paths():
    if not EMBEDDED_FILES:
        return [(rel(path), False) for path in walk_files()]
    candidates = []
    for configured in EMBEDDED_FILES:
        full = os.path.join(REPO, configured)
        if os.path.isdir(full):
            candidates.extend((rel(path), True) for path in walk_files(full))
        else:
            candidates.append((configured.replace(os.sep, "/"), True))
    return candidates


def classify_sources():
    report = {
        "mode": "explicit" if EMBEDDED_FILES else "auto",
        "scanner_version": SCANNER_VERSION,
        "files_scanned": 0,
        "bytes_scanned": 0,
        "profiles": {},
        "extensions": {},
        "generic_fallback_files": [],
        "skipped": {},
        "warnings": [],
        "candidates": {"accepted": 0, "rejected": 0},
        "rejections": [],
    }
    targets = []

    def skip(reason, path):
        report["skipped"][reason] = report["skipped"].get(reason, 0) + 1
        if reason in {"missing_explicit", "read_error"}:
            report["warnings"].append({"path": path, "reason": reason})

    for rp, explicit in sorted(set(_candidate_paths())):
        path = os.path.join(REPO, rp)
        if not os.path.isfile(path):
            skip("missing_explicit" if explicit else "missing", rp)
            continue
        if not explicit and SCAN_SKIP_RE.search(rp):
            skip("generated_or_test", rp)
            continue
        try:
            size = os.path.getsize(path)
            if size > MAX_SOURCE_BYTES:
                skip("too_large", rp)
                continue
            with open(path, "rb") as fh:
                raw = fh.read()
        except OSError:
            skip("read_error", rp)
            continue
        if b"\0" in raw:
            skip("binary", rp)
            continue
        ext = os.path.splitext(rp)[1].casefold()
        profile = LANGUAGE_PROFILES.get(ext)
        if not profile:
            if not explicit and ext in NON_SOURCE_EXTS:
                skip("non_source_text", rp)
                continue
            profile = "generic"
            report["generic_fallback_files"].append(rp)
        targets.append((rp, profile))
        report["files_scanned"] += 1
        report["bytes_scanned"] += len(raw)
        report["profiles"][profile] = report["profiles"].get(profile, 0) + 1
        report["extensions"][ext or "<none>"] = report["extensions"].get(ext or "<none>", 0) + 1
    return targets, report


def discover_embedded():
    out, seen, used_ids = [], set(), set()
    if not EMBEDDED_SCAN:
        return out, {"mode": "disabled", "scanner_version": SCANNER_VERSION,
                     "files_scanned": 0, "skipped": {},
                     "candidates": {"accepted": 0, "rejected": 0}}
    targets, report = classify_sources()

    def reject(reason, relpath, line, name=""):
        report["candidates"]["rejected"] += 1
        if len(report.setdefault("rejections", [])) < 200:
            report["rejections"].append({
                "path": relpath, "line": line, "symbol": name, "reason": reason,
            })

    def emit(name, relpath, start_line, end_line, body, kind, fmt):
        stripped = (body or "").strip()
        if len(stripped) < NAMED_MIN_BODY:
            reject("too_short", relpath, start_line, name)
            return
        if name and len(name) <= 2:      # 1–2 char vars (p, x) → treat as unnamed
            name = ""
        slug = slugify(relpath + "-" + name) if name else (slugify(relpath) + "-l" + str(start_line))
        aid = "embedded-" + slug
        if aid in used_ids:
            aid += "-l" + str(start_line)
        used_ids.add(aid)
        identity = (relpath, start_line, hashlib.sha256(stripped.encode("utf-8")).hexdigest())
        if identity in seen:
            return
        seen.add(identity)
        report["candidates"]["accepted"] += 1
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
            "_content": body,
        })

    for relpath, profile in targets:
        path = os.path.join(REPO, relpath)
        try:
            text = read(path)
        except Exception as exc:
            report["warnings"].append({"path": relpath, "reason": "read_error",
                                       "detail": str(exc)})
            continue
        searchable = _mask_comments(text, profile, mask_long_literals=True)
        # Polyglot named literals and struct/object fields.
        for m in IDENT_ASSIGN_RE.finditer(searchable):
            name = m.group(1)
            lit = _read_literal(text, m.end(), allow_leading_newline=False)
            if not lit:
                continue
            body, end_idx, syntax = lit
            stripped = body.strip()
            strong_name = _strong_prompt_name(name)
            opener = bool(PROMPT_OPENER_RE.match(stripped))
            if _normalise_symbol(name) in GENERIC_FIELD_NAMES and not strong_name:
                reject("generic_field_without_prompt_evidence", relpath, line_of(text, m.start()), name)
                continue
            if not strong_name and not opener:
                reject("weak_name_and_body", relpath, line_of(text, m.start()), name)
                continue
            if stripped.startswith("${"):
                reject("assembly_fragment", relpath, line_of(text, m.start()), name)
                continue
            emit(name, relpath, line_of(text, m.start()), line_of(text, end_idx), body,
                 _literal_kind(name, body), f"embedded literal ({profile}; {syntax})")

        # Prompt-framework calls in any language profile.
        for m in PROMPT_API_RE.finditer(searchable):
            lit = _read_literal(text, m.end())
            if not lit:
                continue
            if len(lit[0].strip()) < EMBEDDED_MIN_BODY:
                reject("prompt_api_literal_too_short", relpath, line_of(text, m.start()), m.group(1))
                continue
            body, end_idx, syntax = lit
            emit(m.group(1), relpath, line_of(text, m.start()), line_of(text, end_idx), body,
                 "prompt-template", f"embedded prompt API ({profile}; {syntax})")

        # Paired role=system + content/message/text within the same nearby object.
        for m in ROLE_SYSTEM_RE.finditer(searchable):
            matched = text[m.start():m.end()]
            if matched.lstrip().startswith("("):
                lit = _read_literal(text, m.end())
                if lit and len(lit[0].strip()) >= NAMED_MIN_BODY:
                    body, end_idx, syntax = lit
                    emit("", relpath, line_of(text, m.start()), line_of(text, end_idx), body,
                         "system-prompt", f"embedded system tuple ({profile}; {syntax})")
                continue
            region_start = max(text.rfind("{", max(0, m.start() - 500), m.start()),
                               text.rfind("(", max(0, m.start() - 500), m.start()))
            region_start = m.start() if region_start == -1 else region_start
            close_brace = text.find("}", m.end(), min(len(text), m.end() + 2000))
            close_paren = text.find(")", m.end(), min(len(text), m.end() + 2000))
            ends = [value for value in (close_brace, close_paren) if value != -1]
            region_end = min(ends) if ends else min(len(text), m.end() + 1200)
            region = searchable[region_start:region_end]
            content_match = CONTENT_KEY_RE.search(region)
            if not content_match:
                continue
            absolute = region_start + content_match.end()
            lit = _read_literal(text, absolute)
            if not lit or len(lit[0].strip()) < NAMED_MIN_BODY:
                continue
            body, end_idx, syntax = lit
            emit("", relpath, line_of(text, m.start()), line_of(text, end_idx), body,
                 "system-prompt", f"embedded system message ({profile}; {syntax})")

    return out, report


# ── ADAPT (3): structured registry metadata (model/tools/output schema/etc). ──
def parse_registry():
    """Return {artifact_id: {extra mechanical fields}} from a repo registry, or {}.
    See examples/claude-for-legal.build_explorer.py for a TS-registry parser that
    merges model/maxTurns/tools/outputFormat and editorial strengths/limitations."""
    return {}


def git_output(*args):
    try:
        return subprocess.check_output(
            ["git", "-C", REPO, *args], text=True, encoding="utf-8",
            stderr=subprocess.DEVNULL
        ).strip()
    except Exception:
        return ""


def write_discovery_payload(artifacts, scan_commit, generated_at):
    """Write exact bodies while repo-specific adapters still have parsed values.

    The downstream catalog builder consumes this file; it never rediscovers bodies from
    arbitrary source. Adapters for shared registries must set ``_content`` explicitly.
    """
    catalog_dir = os.path.join(HERE, "catalog")
    os.makedirs(catalog_dir, exist_ok=True)
    extracted, missing = [], []
    for artifact in artifacts:
        content = artifact.get("_content")
        if content is None:
            missing.append(artifact["id"])
            continue
        normalized = str(content).replace("\r\n", "\n").replace("\r", "\n")
        extracted.append({
            "id": artifact["id"],
            "content": normalized,
            "content_sha256": hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
            "source_path": artifact.get("source_path"),
            "line_start": artifact.get("line_start"),
            "line_end": artifact.get("line_end"),
            "content_commit": artifact.get("content_commit"),
        })
    payload = {
        "schema_version": "1.0",
        "scan_commit": scan_commit or None,
        "generated_at": generated_at,
        "artifacts": sorted(extracted, key=lambda item: item["id"]),
        "missing_content_ids": sorted(missing),
    }
    out_path = os.path.join(catalog_dir, "discovered.json")
    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False, sort_keys=True)
        fh.write("\n")
    return len(extracted), missing


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    embedded, embedded_report = discover_embedded()
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
    seen, deduped, duplicate_ids = set(), [], []
    for a in artifacts:
        if a["id"] in seen:
            print(f"  WARNING: duplicate id {a['id']} ({a['source_path']}) — skipped")
            duplicate_ids.append(a["id"])
            continue
        seen.add(a["id"])
        deduped.append(a)

    counts, cat_counts = {}, {}
    for a in deduped:
        counts[a["kind"]] = counts.get(a["kind"], 0) + 1
        cat_counts[a["category"]] = cat_counts.get(a["category"], 0) + 1

    scan_commit = git_output("rev-parse", "HEAD")
    generated_at = git_output("show", "-s", "--format=%cI", "HEAD") or datetime.now(timezone.utc).isoformat()
    extracted_count, missing_content = write_discovery_payload(deduped, scan_commit, generated_at)
    public_artifacts = [
        {key: value for key, value in artifact.items() if not key.startswith("_")}
        for artifact in deduped
    ]
    manifest = {
        "generatedAt": generated_at,
        "repo": os.path.basename(REPO),
        "generator": "docs/explorer/build_explorer.py",
        "pyyaml": HAVE_YAML,
        "coverage": {
            "scan_commit": scan_commit or None,
            "searched_patterns": [
                "**/SKILL.md (Claude Skills folders; YAML frontmatter)",
                ".claude/commands/**/*.md and **/commands/*.md (slash commands)",
                ".claude/agents/*.md and **/agents/*.md (subagent definitions)",
                "instruction docs: " + ", ".join(INSTRUCTION_DOCS),
                "prompt files: prompts/**, *.prompt(.md|.yaml), *.prompty, *.jinja",
                ("embedded prompts in code: " + (
                    "DISABLED" if not EMBEDDED_SCAN else
                    ("explicit list (" + ", ".join(EMBEDDED_FILES) + ")") if EMBEDDED_FILES else
                    f"polyglot text scan ({embedded_report.get('files_scanned', 0)} files; "
                    f"heuristic {SCANNER_VERSION}) for named literals, prompt APIs, "
                    "and paired role:system content")),
            ],
            "embedded_scan": embedded_report,
            "pre_extracted": {
                "artifact_count": extracted_count,
                "missing_content_ids": missing_content,
                "path": "docs/explorer/catalog/discovered.json",
            },
            "counts_by_kind": counts,
            "counts_by_category": cat_counts,
            "total": len(deduped),
        },
        "artifacts": public_artifacts,
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
        mode = "explicit list" if EMBEDDED_FILES else f"polyglot scan of {embedded_report.get('files_scanned', 0)} source files"
        print(f"  embedded-prompt scan: {mode} ({counts.get('system-prompt', 0)} system-prompt + "
              f"{counts.get('prompt-template', 0)} prompt-template found)")
    else:
        print("  embedded-prompt scan: DISABLED (set EMBEDDED_SCAN = True to scan in-code prompts)")
    if not deduped:
        print("  ERROR: nothing found — adapt the discover_*() functions to this repo's conventions.")
    if duplicate_ids:
        print("  ERROR: duplicate artifact ids must be resolved: " + ", ".join(sorted(set(duplicate_ids))))
    if missing_content:
        print("  ERROR: pre-extracted content missing for " + ", ".join(missing_content[:10]))
        print("  Adapt repo-specific discoverers to set _content before publishing a catalog bundle.")
    if embedded_report.get("warnings"):
        print("  ERROR: embedded scan coverage warnings:")
        for warning in embedded_report["warnings"][:10]:
            print(f"    {warning.get('path')}: {warning.get('reason')}")
    return 1 if (missing_content or embedded_report.get("warnings")
                 or duplicate_ids or not deduped) else 0


if __name__ == "__main__":
    sys.exit(main())
