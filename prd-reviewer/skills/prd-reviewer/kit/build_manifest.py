#!/usr/bin/env python3
"""Generate the manifest the PRD Reviewer reads.

Unlike a whole-repo explorer, a PRD Reviewer is scoped to **one** document set: a
single PRD / design / epic folder, plus the source files that PRD references (so a
reviewer can click from the design straight to the real code). The reviewer's home
is that folder; nothing else in the repo is indexed.

Two inputs, both repo-relative:
  * PRD_DIR            — the PRD folder to review (set below, per build).
  * <PRD_DIR>/referenced-files.txt — a simple list of source files/globs to make
    navigable. One entry per line; blank lines and ``#`` comments ignored; an
    optional ``| Label`` groups the entry in the sidebar. Example:

        # Client transport
        ADMClient/Integration/Integration.Library/Core/Net/*.cs | Client · transport
        ADM/Integration.Net/Net/IntegrationNetRequest.cs        | Server · handler

Run it whenever the PRD docs or the referenced list change:

    python prd-reviewer/.../build_manifest.py     # (path to THIS file)

Stdlib-only. The one block marked ``ADAPT`` (PRD_DIR) is all you normally set.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# ADAPT — the PRD folder this reviewer is scoped to (repo-relative, POSIX).
# ---------------------------------------------------------------------------
PRD_DIR = "docs/prd/EXAMPLE"

# The list-of-referenced-files filename, looked up inside PRD_DIR.
REFERENCES_FILE = "referenced-files.txt"

INCLUDE_SUFFIXES = {".md", ".markdown"}
EXCLUDE_DIRS = {".git", "node_modules", "__pycache__", "bin", "obj"}

HERE = Path(__file__).resolve()
OUTPUT = HERE.parent / "manifest.json"


def find_repo_root(start: Path) -> Path:
    """Walk up until a .git is found; fall back to the start dir."""
    p = start
    for _ in range(40):
        if (p / ".git").exists():
            return p
        if p.parent == p:
            break
        p = p.parent
    return start


REPO_ROOT = find_repo_root(HERE.parent)
PRD_ROOT = (REPO_ROOT / PRD_DIR).resolve()
OUTPUT_REL = OUTPUT.parent.relative_to(REPO_ROOT).as_posix()


# ---------------------------------------------------------------------------
# Title + summary extraction
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
# Collect: PRD docs + referenced source
# ---------------------------------------------------------------------------
def read_references() -> list[tuple[str, str]]:
    """Return [(repo_rel_path, label), …] from PRD_DIR/referenced-files.txt."""
    out: list[tuple[str, str]] = []
    ref_file = PRD_ROOT / REFERENCES_FILE
    if not ref_file.is_file():
        return out
    for raw in ref_file.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        label = "Referenced source"
        if "|" in line:
            spec, label = line.split("|", 1)
            spec, label = spec.strip(), label.strip()
        else:
            spec = line
        matches = sorted(REPO_ROOT.glob(spec)) if any(c in spec for c in "*?[") else [REPO_ROOT / spec]
        hit = False
        for p in matches:
            if p.is_file():
                out.append((p.relative_to(REPO_ROOT).as_posix(), label))
                hit = True
        if not hit:
            print(f"  ! referenced path not found, skipped: {spec}")
    return out


def iter_prd_docs() -> list[Path]:
    out: list[Path] = []
    if not PRD_ROOT.is_dir():
        print(f"  ! PRD_DIR not found: {PRD_DIR}")
        return out
    for path in sorted(PRD_ROOT.rglob("*")):
        if not path.is_file():
            continue
        if any(part in EXCLUDE_DIRS for part in path.parts):
            continue
        rel = path.relative_to(REPO_ROOT).as_posix()
        if rel.startswith(OUTPUT_REL + "/"):  # never index our own output
            continue
        if path.suffix.lower() in INCLUDE_SUFFIXES:
            out.append(path)
    return out


def build() -> dict:
    files = []
    seen: set[str] = set()

    for path in iter_prd_docs():
        rel = path.relative_to(REPO_ROOT).as_posix()
        seen.add(rel)
        text = path.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        files.append({
            "path": rel,
            "title": extract_title(rel, lines),
            "summary": extract_summary(lines),
            "size": path.stat().st_size,
            "lines": len(lines),
            "category": "PRD document",
            "group": "prd",
            "type": "markdown",
        })

    for rel, label in read_references():
        if rel in seen:
            continue
        seen.add(rel)
        p = REPO_ROOT / rel
        text = p.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        is_md = p.suffix.lower() in INCLUDE_SUFFIXES
        files.append({
            "path": rel,
            "title": rel.rsplit("/", 1)[-1],
            "summary": label,
            "size": p.stat().st_size,
            "lines": len(lines),
            "category": label,
            "group": "reference",
            "type": "markdown" if is_md else (p.suffix.lstrip(".") or p.name.lower()),
        })

    files.sort(key=lambda f: (f["group"] != "prd", f["path"]))
    return {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "repo": REPO_ROOT.name,
        "prdDir": PRD_DIR,
        "fileCount": len(files),
        "prdCount": sum(1 for f in files if f["group"] == "prd"),
        "refCount": sum(1 for f in files if f["group"] == "reference"),
        "totalBytes": sum(f["size"] for f in files),
        "files": files,
    }


def main() -> None:
    manifest = build()
    OUTPUT.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {OUTPUT.relative_to(REPO_ROOT)}: {manifest['fileCount']} files "
          f"({manifest['prdCount']} PRD docs + {manifest['refCount']} referenced), "
          f"{manifest['totalBytes'] / 1024:.0f} KiB.")


if __name__ == "__main__":
    main()
