#!/usr/bin/env python3
"""
build_explorer.py — regenerate the mechanical manifest for the Skills & Prompts Explorer.

This walks THIS repository (the claude-for-legal plugin marketplace), discovers every
skill/agent/prompt artifact, and extracts *mechanical* metadata: YAML frontmatter,
markdown section headings, tool grants, MCP server lists, bundled skill resources,
cookbook registry metadata, and line ranges for prompts embedded in code. It writes
`explorer-manifest.json`.

What it discovers (the repo's actual conventions, found in Phase 0):
  - Claude Skills folders:        <plugin>/skills/<name>/SKILL.md (+ external_plugins/)
  - Plugin subagent definitions:  <plugin>/agents/<name>.md (frontmatter: model, tools)
  - Managed-agent cookbooks:      managed-agent-cookbooks/<name>/agent.yaml + subagents/*.yaml
  - Practice-profile templates:   <plugin>/CLAUDE.md (copied to user config by cold-start-interview)
  - Repo instruction docs:        CLAUDE.md, references/*-template.md
  - Embedded prompts in code:     scripts/orchestrate.py (HANDOFF_TEMPLATES, frame_handoff)
  - Programmatic surface:         .mcp.json servers, frontmatter allowed-tools /
                                  argument-hint / user-invocable, cookbook tool scoping,
                                  bundled references/ files inside skill directories

Design rules:
  - Stdlib only; PyYAML is used *if importable* (frontmatter + cookbook YAML), with a
    tolerant line-based fallback otherwise.
  - The manifest is the GENERATED, mechanical index. It never contains hand-authored
    workflow graphs — those live in docs/explorer/data/*.json (assembled into
    assets/explorer-data.js) and are merged by id in the app.
  - Nothing is invented: descriptions, headings, tools and line ranges all come from
    real files.

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


# ── Small helpers ────────────────────────────────────────────────────────────
def rel(path: str) -> str:
    return os.path.relpath(path, REPO).replace(os.sep, "/")


def read(path: str) -> str:
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        return fh.read()


HEADING_RE = re.compile(r"^(#{1,4})\s+(.*?)\s*$", re.MULTILINE)


def extract_headings(body: str, limit: int = 60):
    """Return markdown headings found in a body: [{level, text}].
    Fenced code blocks are skipped so `# comments` inside ``` fences are not
    mistaken for headings."""
    out = []
    in_fence = False
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


# ── Frontmatter ──────────────────────────────────────────────────────────────
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


# ── Marketplace / plugin inventory ───────────────────────────────────────────
def load_marketplace():
    """plugin name -> {source dir, description} from the marketplace manifest."""
    path = os.path.join(REPO, ".claude-plugin", "marketplace.json")
    plugins = {}
    if os.path.exists(path):
        m = json.loads(read(path))
        for p in m.get("plugins", []):
            src = p.get("source", "").lstrip("./")
            plugins[p["name"]] = {
                "dir": src,
                "description": p.get("description", ""),
            }
    return plugins


def load_mcp_servers(plugin_dir: str):
    """Server titles declared in a plugin's .mcp.json (programmatic surface)."""
    path = os.path.join(REPO, plugin_dir, ".mcp.json")
    if not os.path.exists(path):
        return []
    try:
        data = json.loads(read(path))
    except Exception:
        return []
    return sorted((data.get("mcpServers") or {}).keys())


# ── Skills (<plugin>/skills/<name>/SKILL.md) ─────────────────────────────────
def discover_skills(plugins):
    out = []
    for pname, meta in plugins.items():
        sdir = os.path.join(REPO, meta["dir"], "skills")
        if not os.path.isdir(sdir):
            continue
        mcp = load_mcp_servers(meta["dir"])
        for skill in sorted(os.listdir(sdir)):
            path = os.path.join(sdir, skill, "SKILL.md")
            if not os.path.exists(path):
                continue
            text = read(path)
            fm, body = parse_frontmatter(text)
            name = str(fm.get("name") or skill)
            art = {
                "id": pname + "--" + slugify(name),
                "title": first_h1(body) or name,
                "kind": "skill",
                "category": pname,
                "source_path": rel(path),
                "format": "SKILL.md (YAML frontmatter)",
                "description": first_sentence(str(fm.get("description", ""))),
                "description_full": str(fm.get("description", "")).strip(),
                "headings": extract_headings(body),
                "body_chars": len(text),
                "frontmatter_keys": sorted(fm.keys()),
            }
            # ── programmatic surface (explicitly present in the source) ──
            inv = {}
            if "user-invocable" in fm:
                inv["user_invocable"] = bool(fm["user-invocable"]) if not isinstance(
                    fm["user-invocable"], str) else fm["user-invocable"].lower() != "false"
            if "argument-hint" in fm:
                inv["argument_hint"] = str(fm["argument-hint"])
            if inv:
                art["invocation"] = inv
            if "allowed-tools" in fm:
                tools = fm["allowed-tools"]
                if isinstance(tools, str):
                    tools = [t.strip() for t in re.split(r"[,\n]", tools) if t.strip()]
                art["tools"] = tools
            if "version" in fm:
                art["version"] = str(fm["version"])
            # bundled resources shipped inside the skill directory
            res = []
            for root, _dirs, files in os.walk(os.path.join(sdir, skill)):
                for f in sorted(files):
                    if f == "SKILL.md":
                        continue
                    res.append(rel(os.path.join(root, f)))
            if res:
                art["resources"] = res
            if mcp:
                art["plugin_mcp_servers"] = mcp
            out.append(art)
    return out


# ── Plugin agents (<plugin>/agents/<name>.md) ────────────────────────────────
def discover_plugin_agents(plugins):
    out = []
    for pname, meta in plugins.items():
        adir = os.path.join(REPO, meta["dir"], "agents")
        if not os.path.isdir(adir):
            continue
        for fname in sorted(os.listdir(adir)):
            if not fname.endswith(".md"):
                continue
            path = os.path.join(adir, fname)
            text = read(path)
            fm, body = parse_frontmatter(text)
            name = str(fm.get("name") or fname[:-3])
            art = {
                "id": pname + "--agent-" + slugify(name),
                "title": first_h1(body) or name,
                "kind": "agent",
                "category": pname,
                "source_path": rel(path),
                "format": "agent markdown (YAML frontmatter)",
                "description": first_sentence(str(fm.get("description", ""))),
                "description_full": str(fm.get("description", "")).strip(),
                "headings": extract_headings(body),
                "body_chars": len(text),
            }
            if fm.get("model"):
                art["model"] = str(fm["model"])
            tools = fm.get("tools")
            if isinstance(tools, str):
                tools = [t.strip() for t in re.split(r"[,\n]", tools) if t.strip()]
            if tools:
                art["tools"] = tools
            out.append(art)
    return out


# ── Managed-agent cookbooks (agent.yaml + subagents/*.yaml) ──────────────────
def toolset_names(tools_list):
    """Enabled tool names from an agent_toolset_20260401 block."""
    names = []
    for t in tools_list or []:
        if not isinstance(t, dict):
            continue
        for cfg in t.get("configs", []) or []:
            if isinstance(cfg, dict) and cfg.get("enabled"):
                names.append(str(cfg.get("name")))
        if t.get("type") and "toolset" not in str(t.get("type", "")):
            names.append(str(t["type"]))
    return names


def mcp_server_names(mcp_list):
    out = []
    for s in mcp_list or []:
        if isinstance(s, dict):
            out.append(str(s.get("name") or s.get("url") or "mcp"))
        else:
            out.append(str(s))
    return out


def discover_cookbooks():
    out = []
    base = os.path.join(REPO, "managed-agent-cookbooks")
    if not os.path.isdir(base):
        return out
    for cb in sorted(os.listdir(base)):
        apath = os.path.join(base, cb, "agent.yaml")
        if not os.path.exists(apath):
            continue
        cat = "cookbook: " + cb
        text = read(apath)
        data = yaml.safe_load(text) if HAVE_YAML else {}
        system = (data or {}).get("system") or {}
        sys_file = system.get("file")
        sys_text = system.get("text") or ""
        sys_append = system.get("append") or ""
        headings = extract_headings(sys_text) if sys_text else []
        # description: first sentence of the system text or of the referenced file
        desc_src = sys_text
        system_file_rel = None
        if sys_file:
            ref = os.path.normpath(os.path.join(base, cb, sys_file))
            if os.path.exists(ref):
                system_file_rel = rel(ref)
                ref_fm, ref_body = parse_frontmatter(read(ref))
                desc_src = str(ref_fm.get("description", "")) or ref_body
        art = {
            "id": "cookbook-" + slugify(cb),
            "title": (data or {}).get("name", cb) + " (orchestrator)",
            "kind": "managed-agent",
            "category": cat,
            "source_path": rel(apath),
            "format": "managed-agent cookbook (agent.yaml)",
            "description": first_sentence(desc_src),
            "headings": headings,
            "body_chars": len(text),
        }
        if (data or {}).get("model"):
            art["model"] = str(data["model"])
        tools = toolset_names((data or {}).get("tools"))
        if tools:
            art["tools"] = tools
        art["mcp_servers"] = mcp_server_names((data or {}).get("mcp_servers"))
        if system_file_rel:
            art["system_file"] = system_file_rel
        if sys_append:
            art["system_append_chars"] = len(sys_append)
        leaves = [str(c.get("manifest")) for c in (data or {}).get("callable_agents", [])
                  if isinstance(c, dict)]
        if leaves:
            art["callable_agents"] = [os.path.basename(l).replace(".yaml", "") for l in leaves]
        skills_from = [str(s.get("from_plugin")) for s in (data or {}).get("skills", [])
                       if isinstance(s, dict) and s.get("from_plugin")]
        if skills_from:
            art["skills_from_plugins"] = [os.path.basename(s) for s in skills_from]
        steering = os.path.join(base, cb, "steering-examples.json")
        if os.path.exists(steering):
            art["resources"] = [rel(steering)]
        out.append(art)

        # ── subagent leaves ──
        subdir = os.path.join(base, cb, "subagents")
        if os.path.isdir(subdir):
            for fname in sorted(os.listdir(subdir)):
                if not fname.endswith(".yaml"):
                    continue
                spath = os.path.join(subdir, fname)
                stext = read(spath)
                sdata = yaml.safe_load(stext) if HAVE_YAML else {}
                ssys = ((sdata or {}).get("system") or {}).get("text") or ""
                sart = {
                    "id": "cookbook-" + slugify(cb) + "--" + slugify(fname[:-5]),
                    "title": (sdata or {}).get("name", fname[:-5]),
                    "kind": "subagent",
                    "category": cat,
                    "source_path": rel(spath),
                    "format": "managed-agent subagent (YAML system prompt)",
                    "description": first_sentence(ssys),
                    "headings": extract_headings(ssys),
                    "body_chars": len(stext),
                }
                if (sdata or {}).get("model"):
                    sart["model"] = str(sdata["model"])
                stools = toolset_names((sdata or {}).get("tools"))
                if stools:
                    sart["tools"] = stools
                smcp = mcp_server_names((sdata or {}).get("mcp_servers"))
                if smcp:
                    sart["mcp_servers"] = smcp
                if (sdata or {}).get("output_schema") or (sdata or {}).get("output_format"):
                    sart["outputFormat"] = "structured JSON"
                out.append(sart)
    return out


# ── Practice-profile templates (<plugin>/CLAUDE.md) ──────────────────────────
def discover_practice_profiles(plugins):
    out = []
    for pname, meta in plugins.items():
        path = os.path.join(REPO, meta["dir"], "CLAUDE.md")
        if not os.path.exists(path):
            continue
        text = read(path)
        body = re.sub(r"<!--.*?-->", "", text, count=1, flags=re.DOTALL)
        title = first_h1(body) or (pname + " practice profile")
        art = {
            "id": "profile-" + pname,
            "title": title + " (template)",
            "kind": "instruction-doc",
            "category": pname,
            "source_path": rel(path),
            "format": "practice-profile CLAUDE.md template",
            "description": first_sentence(meta.get("description", "")) or first_sentence(body),
            "headings": extract_headings(text, limit=80),
            "body_chars": len(text),
        }
        mcp = load_mcp_servers(meta["dir"])
        if mcp:
            art["mcp_servers"] = mcp
        # plugin-level data files (referenced by skills/agents)
        res = []
        for cand in ("references", "deadlines.yaml"):
            p = os.path.join(REPO, meta["dir"], cand)
            if os.path.isfile(p):
                res.append(rel(p))
            elif os.path.isdir(p):
                for root, _d, files in os.walk(p):
                    for f in sorted(files):
                        res.append(rel(os.path.join(root, f)))
        if res:
            art["resources"] = res
        out.append(art)
    return out


# ── Repo instruction docs & shared templates ─────────────────────────────────
def discover_repo_docs():
    out = []
    docs = [
        ("CLAUDE.md", "instruction-doc", "repo docs", "markdown"),
        ("references/company-profile-template.md", "prompt-template", "shared templates",
         "markdown template (copied to user config)"),
        ("references/dashboard-template.md", "prompt-template", "shared templates",
         "markdown template (copied to user config)"),
    ]
    for relpath, kind, cat, fmt in docs:
        path = os.path.join(REPO, relpath)
        if not os.path.exists(path):
            continue
        text = read(path)
        title = first_h1(text) or os.path.basename(relpath)
        out.append({
            "id": "doc-" + slugify(relpath.replace("/", "-").replace(".md", "")),
            "title": title,
            "kind": kind,
            "category": cat,
            "source_path": relpath,
            "format": fmt,
            "description": first_sentence(re.sub(r"^#.*$", "", text, count=1, flags=re.MULTILINE)),
            "headings": extract_headings(text, limit=80),
            "body_chars": len(text),
        })
    return out


# ── Embedded prompts in code (scripts/orchestrate.py) ────────────────────────
def discover_embedded():
    out = []
    relpath = "scripts/orchestrate.py"
    path = os.path.join(REPO, relpath)
    if not os.path.exists(path):
        return out
    text = read(path)

    # HANDOFF_TEMPLATES: dict[str, str] = { ... }  — the steering-prompt templates
    m = re.search(r"^HANDOFF_TEMPLATES\s*:.*?=\s*\{", text, re.MULTILINE)
    if m:
        depth, i = 0, text.index("{", m.start())
        start_idx = i
        while i < len(text):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        intents = re.findall(r'^\s{4}"([a-z_]+)":', text[start_idx:i], re.MULTILINE)
        out.append({
            "id": "embedded-handoff-templates",
            "title": "Handoff steering templates",
            "kind": "prompt-template",
            "category": "orchestration scripts",
            "source_path": relpath,
            "line_start": line_of(text, m.start()),
            "line_end": line_of(text, i),
            "format": "python (dict of per-intent steering templates)",
            "description": "Per-intent steering-prompt templates the orchestrator renders locally; "
                           "untrusted free text never becomes the prompt.",
            "headings": [],
            "body_chars": i - m.start(),
            "embedded": True,
            "template_intents": intents,
        })

    # frame_handoff() — the <agent-handoff> data-frame wrapper prompt
    fm = re.search(r"^def frame_handoff\(.*?\n(?=\ndef |\nclass )", text, re.MULTILINE | re.DOTALL)
    if fm:
        out.append({
            "id": "embedded-agent-handoff-frame",
            "title": "Agent-handoff data frame",
            "kind": "system-prompt",
            "category": "orchestration scripts",
            "source_path": relpath,
            "line_start": line_of(text, fm.start()),
            "line_end": line_of(text, fm.end()),
            "format": "python (f-string prompt wrapper)",
            "description": "Wraps agent-produced text in an explicit <agent-handoff> data block "
                           "telling the receiving agent the content is data, not instructions.",
            "headings": [],
            "body_chars": fm.end() - fm.start(),
            "embedded": True,
        })
    return out


# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    plugins = load_marketplace()

    skills = discover_skills(plugins)
    agents = discover_plugin_agents(plugins)
    cookbooks = discover_cookbooks()
    profiles = discover_practice_profiles(plugins)
    repo_docs = discover_repo_docs()
    embedded = discover_embedded()

    artifacts = skills + agents + cookbooks + profiles + repo_docs + embedded

    # dedupe by id (defensive — ids are namespaced by plugin/cookbook)
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
        "repo": "claude-for-legal",
        "generator": "docs/explorer/build_explorer.py",
        "pyyaml": HAVE_YAML,
        "coverage": {
            "searched_patterns": [
                "<plugin>/skills/*/SKILL.md for all 13 marketplace plugins incl. external_plugins/ "
                "(YAML frontmatter: name, description, argument-hint, user-invocable, allowed-tools, version)",
                "<plugin>/skills/*/** bundled resources (references/*.md, *.yaml templates shipped inside skill dirs)",
                "<plugin>/agents/*.md (frontmatter: name, description, model, tools)",
                "managed-agent-cookbooks/*/agent.yaml (model, tool scoping, mcp_servers, skills, callable_agents, system.file+append)",
                "managed-agent-cookbooks/*/subagents/*.yaml (system.text, tool grants, mcp_servers, output schema)",
                "managed-agent-cookbooks/*/steering-examples.json (attached as orchestrator resources)",
                "<plugin>/CLAUDE.md practice-profile templates (NOT project context — copied to user config by cold-start-interview)",
                "<plugin>/.mcp.json (MCP server connections, recorded per plugin)",
                "repo CLAUDE.md + references/company-profile-template.md + references/dashboard-template.md",
                "embedded prompts in code: scripts/orchestrate.py HANDOFF_TEMPLATES dict + frame_handoff() "
                "(scripts/validate.py, lint-tool-scope.py, check-guardrail-sync.py, deploy-managed-agent.sh, "
                "test-cookbooks.sh scanned — no prompt literals)",
                "<plugin>/hooks/hooks.json — present in 10 plugins, all empty stubs ({\"hooks\": {}}); no hook prompts exist",
                ".claude/commands/*.md, prompts/ dirs, *.prompt(.md|.yaml), *.prompty, *.jinja, "
                ".cursorrules, .github/copilot-instructions.md — none present in this repo",
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


if __name__ == "__main__":
    sys.exit(main())
