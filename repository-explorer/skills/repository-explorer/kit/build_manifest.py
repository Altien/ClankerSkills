#!/usr/bin/env python3
"""Generate the manifest the Repository Explorer reads.

The Explorer (``index.html``) is a static, dependency-light single-page app. It
does not crawl the repository at runtime — instead it loads ``manifest.json``, a
small index of every browsable document (path, title, one-line summary, size,
and a category derived from the path). Document *bodies* are fetched lazily over
HTTP when a file is opened, so this manifest stays tiny even for large corpora.

Run from anywhere; paths resolve relative to the repository root (two levels up
from this file). Re-run whenever docs are added, removed, or retitled:

    python3 docs/repository-explorer/build_manifest.py

Stdlib-only — no dependencies. The three blocks marked ``ADAPT`` are the only
ones you normally touch per repo: what extra non-Markdown files to include,
which directories to skip, and how paths map to sidebar/home categories.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# What to include
# ---------------------------------------------------------------------------
# Markdown is the primary surface.
INCLUDE_SUFFIXES = {".md", ".markdown"}

# ADAPT 1 — extra non-Markdown files worth browsing (rendered as code blocks).
# Add canonical specs/configs the repo treats as references. Exact repo-relative
# paths in INCLUDE_EXTRA_PATHS; globs in INCLUDE_EXTRA_GLOBS. Empty by default.
INCLUDE_EXTRA_PATHS: set[str] = set()
INCLUDE_EXTRA_GLOBS: list[str] = []

# ADAPT 2 — directories never to walk (VCS, build output, vendored trees).
EXCLUDE_DIRS = {
    ".git", "node_modules", ".svelte-kit", "dist", "build", "out",
    "__pycache__", ".venv", "venv", ".pytest_cache", ".mypy_cache",
    ".next", ".nuxt", "target", "vendor", ".terraform",
}
# Path-prefix excludes (repo-relative, POSIX). E.g. a large vendored fork:
EXCLUDE_PATH_PREFIXES: tuple[str, ...] = ()

REPO_ROOT = Path(__file__).resolve().parents[2]
OUTPUT = Path(__file__).resolve().parent / "manifest.json"


# ---------------------------------------------------------------------------
# ADAPT 3 — Category routing. Groups the file tree + the "Browse by area" home
# grid. First matching prefix wins; tune the labels to the repo's vocabulary.
# ---------------------------------------------------------------------------
CATEGORY_RULES: list[tuple[str, str]] = [
    ("docs/adr/", "Architecture Decisions"),
    ("docs/api/", "API Contracts"),
    ("docs/security/", "Security"),
    ("docs/", "Documentation"),
    (".github/", "GitHub & CI"),
    ("skills/", "Skills"),
    ("packages/", "Packages"),
    ("apps/", "Apps"),
    ("src/", "Source"),
    ("tests/", "Tests"),
    ("test/", "Tests"),
    ("examples/", "Examples"),
    ("deploy/", "Deployment"),
    ("scripts/", "Scripts"),
]


def categorize(rel_path: str) -> str:
    if "/" not in rel_path:
        return "Project Root"
    for prefix, label in CATEGORY_RULES:
        if rel_path.startswith(prefix):
            return label
    top = rel_path.split("/", 1)[0]
    return top.replace("-", " ").replace("_", " ").title()


# ---------------------------------------------------------------------------
# Title + summary extraction (no need to touch)
# ---------------------------------------------------------------------------
_BADGE_RE = re.compile(r"^\s*(\[!\[|\!\[|\[.*\]:)")
_HEADING_RE = re.compile(r"^#{1,6}\s+(.*)$")
_INLINE_MD_RE = re.compile(r"[*_`>#]+")
_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_IMG_RE = re.compile(r"!\[[^\]]*\]\([^)]+\)")
_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _clean_inline(text: str) -> str:
    text = _IMG_RE.sub("", text)
    text = _LINK_RE.sub(r"\1", text)
    text = _HTML_TAG_RE.sub("", text)
    text = _INLINE_MD_RE.sub("", text)
    return re.sub(r"\s+", " ", text).strip()


def extract_title(rel_path: str, lines: list[str]) -> str:
    for line in lines[:40]:
        m = _HEADING_RE.match(line)
        if m:
            return _clean_inline(m.group(1)) or rel_path
    return rel_path.rsplit("/", 1)[-1]


def extract_summary(lines: list[str], max_len: int = 220) -> str:
    in_code = False
    started = False
    buf: list[str] = []
    for raw in lines:
        stripped = raw.rstrip("\n").strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_code = not in_code
            continue
        if in_code:
            continue
        if not started:
            if not stripped or stripped.startswith("#") or _BADGE_RE.match(stripped):
                continue
            if stripped.startswith("---") or stripped.startswith("===") or stripped.startswith("<!--"):
                continue
            started = True
        if started:
            if not stripped:
                break
            buf.append(stripped.lstrip("> "))
    summary = _clean_inline(" ".join(buf))
    if len(summary) > max_len:
        summary = summary[: max_len - 1].rsplit(" ", 1)[0] + "…"
    return summary


# ---------------------------------------------------------------------------
# Walk
# ---------------------------------------------------------------------------
def iter_candidate_paths() -> list[Path]:
    seen: set[Path] = set()
    out: list[Path] = []

    for path in sorted(REPO_ROOT.rglob("*")):
        if not path.is_file():
            continue
        if any(part in EXCLUDE_DIRS for part in path.parts):
            continue
        rel = path.relative_to(REPO_ROOT).as_posix()
        if any(rel.startswith(p) for p in EXCLUDE_PATH_PREFIXES):
            continue
        # Never index the explorer's own output directory.
        if rel.startswith(OUTPUT.parent.relative_to(REPO_ROOT).as_posix() + "/"):
            continue
        if path.suffix.lower() in INCLUDE_SUFFIXES and path not in seen:
            seen.add(path)
            out.append(path)

    for extra in INCLUDE_EXTRA_PATHS:
        p = REPO_ROOT / extra
        if p.is_file() and p not in seen:
            seen.add(p)
            out.append(p)
    for glob in INCLUDE_EXTRA_GLOBS:
        for p in sorted(REPO_ROOT.glob(glob)):
            if p.is_file() and p not in seen:
                seen.add(p)
                out.append(p)

    return out


def build() -> dict:
    files = []
    for path in iter_candidate_paths():
        rel = path.relative_to(REPO_ROOT).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        is_markdown = path.suffix.lower() in INCLUDE_SUFFIXES
        if is_markdown:
            title = extract_title(rel, lines)
            summary = extract_summary(lines)
        else:
            title = rel.rsplit("/", 1)[-1]
            summary = f"{(path.suffix.lstrip('.') or 'config')} reference."
        files.append({
            "path": rel,
            "title": title,
            "summary": summary,
            "size": path.stat().st_size,
            "lines": len(lines),
            "category": categorize(rel),
            "type": "markdown" if is_markdown else (path.suffix.lstrip(".") or path.name.lower()),
        })

    files.sort(key=lambda f: f["path"])
    return {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "repo": REPO_ROOT.name,
        "fileCount": len(files),
        "totalBytes": sum(f["size"] for f in files),
        "files": files,
    }


def main() -> None:
    manifest = build()
    OUTPUT.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {OUTPUT.relative_to(REPO_ROOT)}: {manifest['fileCount']} files, "
          f"{manifest['totalBytes'] / 1024:.0f} KiB indexed.")


if __name__ == "__main__":
    main()
