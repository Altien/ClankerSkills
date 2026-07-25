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

# ADAPT 0 — roots to walk for Markdown. Empty = the whole repo (default,
# repo-documentation mode). For a focused design-doc / PRD-review build, list the
# doc subtree(s) to index, e.g. {"docs"} or {"docs/prd/AI-42"}; then add the source
# files those docs cite via INCLUDE_EXTRA_GLOBS (below) so they're viewable for
# click-through. Paths are repo-relative, POSIX. INCLUDE_EXTRA_PATHS/GLOBS are
# always honored regardless of roots, so cited source outside the roots still gets in.
INCLUDE_ROOTS: set[str] = set()

# ADAPT 1 — extra non-Markdown *text* files worth browsing (rendered as code
# blocks). Add canonical specs/configs the repo treats as references. Exact
# repo-relative paths in INCLUDE_EXTRA_PATHS; globs in INCLUDE_EXTRA_GLOBS.
# These ARE read_text()'d, so never point them at binaries — use ADAPT 1b.
INCLUDE_EXTRA_PATHS: set[str] = set()
INCLUDE_EXTRA_GLOBS: list[str] = []

# ADAPT 1b — binary documents to index for BROWSING ONLY (PDFs, Office files,
# images). Empty by default. These are never read_text()'d: they appear in the
# file tree under their real folder hierarchy, and the SPA renders a document
# card (folder, type, size, a link to the original) with an inline preview for
# PDFs and images. Nothing is copied — links resolve to the file in place, and
# serve.py serves the repository root.
#
# Use this when a repo's substance IS its documents (a corpus, a data room, a
# design-asset folder) rather than its prose. e.g. ["Input Documents/**/*"].
INCLUDE_ASSET_GLOBS: list[str] = []

# Suffixes eligible for asset indexing (anything else matched by the globs above
# is skipped). Extend per repo if you have other binaries worth browsing.
ASSET_SUFFIXES = {
    ".pdf", ".docx", ".xlsx", ".pptx", ".doc", ".xls", ".ppt", ".csv",
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".zip",
}

# Extensions a browser can display inline rather than download. Drives the
# preview pane in the SPA; everything else just gets a link.
INLINE_PREVIEW = {".pdf", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"}

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
def _walk_roots() -> list[Path]:
    """Markdown search roots: the named INCLUDE_ROOTS, or the whole repo if none."""
    if not INCLUDE_ROOTS:
        return [REPO_ROOT]
    roots: list[Path] = []
    for r in sorted(INCLUDE_ROOTS):
        p = (REPO_ROOT / r).resolve()
        if p.is_dir():
            roots.append(p)
        else:
            print(f"  ! INCLUDE_ROOTS entry not a directory, skipped: {r}")
    return roots or [REPO_ROOT]


def iter_candidate_paths() -> list[Path]:
    seen: set[Path] = set()
    out: list[Path] = []

    for root in _walk_roots():
        for path in sorted(root.rglob("*")):
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


def iter_asset_paths(already: set[Path]) -> list[Path]:
    """Binary documents to list in the tree. Metadata only — never read."""
    seen: set[Path] = set()
    out: list[Path] = []
    for pattern in INCLUDE_ASSET_GLOBS:
        for p in sorted(REPO_ROOT.glob(pattern)):
            if not p.is_file() or p in seen or p in already:
                continue
            if any(part in EXCLUDE_DIRS for part in p.parts):
                continue
            rel = p.relative_to(REPO_ROOT).as_posix()
            if any(rel.startswith(x) for x in EXCLUDE_PATH_PREFIXES):
                continue
            if p.suffix.lower() not in ASSET_SUFFIXES:
                continue
            seen.add(p)
            out.append(p)
    return out


def _human(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.0f} KiB"
    return f"{n / 1024 / 1024:.1f} MiB"


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

    indexed = {REPO_ROOT / f["path"] for f in files}
    for path in iter_asset_paths(indexed):
        rel = path.relative_to(REPO_ROOT).as_posix()
        ext = path.suffix.lower()
        size = path.stat().st_size
        files.append({
            "path": rel,
            "title": rel.rsplit("/", 1)[-1],
            "summary": f"{ext.lstrip('.').upper()} document · {_human(size)}",
            "size": size,
            "lines": 0,
            "category": categorize(rel),
            "type": "asset",
            "ext": ext.lstrip("."),
            "inline": ext in INLINE_PREVIEW,
        })

    files.sort(key=lambda f: f["path"])
    docs = [f for f in files if f["type"] != "asset"]
    assets = [f for f in files if f["type"] == "asset"]
    return {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "repo": REPO_ROOT.name,
        "fileCount": len(files),
        "docCount": len(docs),
        "assetCount": len(assets),
        "totalBytes": sum(f["size"] for f in files),
        "files": files,
    }


def main() -> None:
    manifest = build()
    OUTPUT.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {OUTPUT.relative_to(REPO_ROOT)}: {manifest['fileCount']} entries "
          f"({manifest['docCount']} documents, {manifest['assetCount']} assets), "
          f"{manifest['totalBytes'] / 1024 / 1024:.1f} MiB referenced.")


if __name__ == "__main__":
    main()
