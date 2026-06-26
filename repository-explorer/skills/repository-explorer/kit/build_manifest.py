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

# HTML documents/templates (e.g. the invoice/report templates a skill ships) are
# browsable too — rendered in a sandboxed iframe, the way Markdown is rendered.
# HTML is a presentational markup format, not deep source, so surfacing it broadly
# is an easy, low-noise win. Set INCLUDE_HTML = False to opt a repo out.
HTML_SUFFIXES = {".html", ".htm"}
INCLUDE_HTML = True

# ADAPT 0 — roots to walk for Markdown. Empty = the whole repo (default,
# repo-documentation mode). For a focused design-doc / PRD-review build, list the
# doc subtree(s) to index, e.g. {"docs"} or {"docs/prd/AI-42"}; then add the source
# files those docs cite via INCLUDE_EXTRA_GLOBS (below) so they're viewable for
# click-through. Paths are repo-relative, POSIX. INCLUDE_EXTRA_PATHS/GLOBS are
# always honored regardless of roots, so cited source outside the roots still gets in.
INCLUDE_ROOTS: set[str] = set()

# ADAPT 1 — extra non-Markdown files worth browsing (rendered as code blocks).
# Add canonical specs/configs the repo treats as references. Exact repo-relative
# paths in INCLUDE_EXTRA_PATHS; globs in INCLUDE_EXTRA_GLOBS. Empty by default.
INCLUDE_EXTRA_PATHS: set[str] = set()
INCLUDE_EXTRA_GLOBS: list[str] = []

# ADAPT 1b — link binary documents (Word/PDF/PowerPoint/spreadsheets/etc) to their
# source instead of re-hosting them. Surfaced only when DOC_CLOUD_BASE is set. At
# runtime the app opens the local checkout when served locally, or this base on
# cloud (the same pattern the data-explorer's DOC_PIN uses). Use a RAW,
# COMMIT-PINNED base so links open the real bytes and never rot, e.g.
# "https://raw.githubusercontent.com/<org>/<repo>/<commit>/".
DOC_CLOUD_BASE = ""
# Documents only — the link-don't-rehost case. Images are intentionally excluded:
# they're usually inline-embedded and ARE re-hosted, so listing them as source
# links would both duplicate them and bury the real documents in icon noise.
BINARY_SUFFIXES = {
    ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx", ".pdf",
}

# ADAPT 1c — cloud-path remap for a dev mirror that reorganized files away from the
# upstream layout. Maps a repo-relative LOCAL path -> the repo-relative UPSTREAM path,
# used only for the cloud link (DOC_CLOUD_BASE + upstream path). Local serving still
# uses the real local path, so the file opens both places. Empty by default.
DOC_PATH_REMAP: dict[str, str] = {}

# ADAPT 2 — directories never to walk (VCS, build output, vendored trees).
EXCLUDE_DIRS = {
    ".git", "node_modules", ".svelte-kit", "dist", "build", "out",
    "__pycache__", ".venv", "venv", ".pytest_cache", ".mypy_cache",
    ".next", ".nuxt", "target", "vendor", ".terraform",
}
# Path-prefix excludes (repo-relative, POSIX). E.g. a large vendored fork:
EXCLUDE_PATH_PREFIXES: tuple[str, ...] = ()
# Sibling doc-tooling islands that live beside this one — generated sites (the
# skills/prompts explorer, atlas, data-explorer), not repo content. Their app
# shells (e.g. docs/explorer/index.html) must never be indexed as documents.
SIBLING_ISLAND_DIRS: tuple[str, ...] = ("docs/explorer/", "docs/atlas/", "docs/data-explorer/")

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


_HTML_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)


def extract_html_title(text: str) -> str:
    # Strip tags/whitespace only — NOT the markdown cleaner, which would eat
    # underscores etc. that are legitimate in an HTML <title> (e.g. {{ client_name }}).
    m = _HTML_TITLE_RE.search(text)
    return re.sub(r"\s+", " ", _HTML_TAG_RE.sub("", m.group(1))).strip() if m else ""


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
            # Never index the explorer's own output directory or sibling islands.
            if rel.startswith(OUTPUT.parent.relative_to(REPO_ROOT).as_posix() + "/"):
                continue
            if rel.startswith(SIBLING_ISLAND_DIRS):
                continue
            viewable = INCLUDE_SUFFIXES | (HTML_SUFFIXES if INCLUDE_HTML else set())
            suf = path.suffix.lower()
            # An index.html is a site/app shell (Vite/SPA entry), not a prose
            # document — skip it. A genuine HTML doc named index.html can still be
            # forced in via INCLUDE_EXTRA_PATHS.
            if suf in HTML_SUFFIXES and path.name.lower() == "index.html":
                continue
            if suf in viewable and path not in seen:
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


def iter_binary_paths() -> list[Path]:
    """Binary documents to surface as source links (only when DOC_CLOUD_BASE set)."""
    if not DOC_CLOUD_BASE:
        return []
    out_dir = OUTPUT.parent.relative_to(REPO_ROOT).as_posix() + "/"
    out: list[Path] = []
    for path in sorted(REPO_ROOT.rglob("*")):
        if not path.is_file():
            continue
        if any(part in EXCLUDE_DIRS for part in path.parts):
            continue
        rel = path.relative_to(REPO_ROOT).as_posix()
        if (any(rel.startswith(p) for p in EXCLUDE_PATH_PREFIXES)
                or rel.startswith(out_dir) or rel.startswith(SIBLING_ISLAND_DIRS)):
            continue
        if path.suffix.lower() in BINARY_SUFFIXES:
            out.append(path)
    return out


def build() -> dict:
    files = []
    for path in iter_candidate_paths():
        rel = path.relative_to(REPO_ROOT).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        suf = path.suffix.lower()
        is_markdown = suf in INCLUDE_SUFFIXES
        is_html = suf in HTML_SUFFIXES
        if is_markdown:
            title = extract_title(rel, lines)
            summary = extract_summary(lines)
        elif is_html:
            title = extract_html_title(text) or rel.rsplit("/", 1)[-1]
            summary = "HTML document — rendered preview."
        else:
            title = rel.rsplit("/", 1)[-1]
            summary = f"{(path.suffix.lstrip('.') or 'config')} reference."
        entry = {
            "path": rel,
            "title": title,
            "summary": summary,
            "size": path.stat().st_size,
            "lines": len(lines),
            "category": categorize(rel),
            "type": "markdown" if is_markdown else ("html" if is_html else (path.suffix.lstrip(".") or path.name.lower())),
        }
        if rel in DOC_PATH_REMAP:
            entry["cloudPath"] = DOC_PATH_REMAP[rel]
        files.append(entry)

    for path in iter_binary_paths():
        rel = path.relative_to(REPO_ROOT).as_posix()
        ext = (path.suffix.lstrip(".") or "file").lower()
        entry = {
            "path": rel,
            "title": rel.rsplit("/", 1)[-1],
            "summary": f"{ext.upper()} document — opens the source file.",
            "size": path.stat().st_size,
            "lines": 0,
            "category": categorize(rel),
            "type": "binary",
        }
        if rel in DOC_PATH_REMAP:
            entry["cloudPath"] = DOC_PATH_REMAP[rel]
        files.append(entry)

    files.sort(key=lambda f: f["path"])
    return {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "repo": REPO_ROOT.name,
        "fileCount": len(files),
        "totalBytes": sum(f["size"] for f in files),
        # Resolved at runtime by app.js: local checkout when served locally, this
        # commit-pinned base on cloud. Binary docs + HTML "view source" use it.
        "docCloudBase": DOC_CLOUD_BASE,
        "files": files,
    }


def main() -> None:
    manifest = build()
    OUTPUT.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {OUTPUT.relative_to(REPO_ROOT)}: {manifest['fileCount']} files, "
          f"{manifest['totalBytes'] / 1024:.0f} KiB indexed.")


if __name__ == "__main__":
    main()
