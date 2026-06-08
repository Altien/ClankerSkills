"""The curated layer: authored summaries and category overviews.

curated/atlas.yaml is hand-written — every summary is authored after
reading the doc, never extracted (DESIGN §4). The loader validates
hard: an entry pointing at a doc that doesn't exist is a curation bug.
Coverage of the full-depth corpus is accounted (and enforced later by
verify.py); search-only docs are exempt by design.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .config import ConfigError


@dataclass(frozen=True)
class DocCuration:
    summary: str
    read_when: str = ""


@dataclass
class Curated:
    category_overviews: dict[str, str] = field(default_factory=dict)
    docs: dict[str, DocCuration] = field(default_factory=dict)
    source_exists: bool = False

    def for_doc(self, doc_id: str) -> DocCuration | None:
        return self.docs.get(doc_id)


def load_curated(path: Path) -> Curated:
    if not path.is_file():
        return Curated()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ConfigError(f"curated atlas file must be a mapping: {path}")

    overviews = data.get("categories") or {}
    if not isinstance(overviews, dict) or any(
        not isinstance(v, str) or not v.strip() for v in overviews.values()
    ):
        raise ConfigError("curated categories must map category id -> overview text")

    docs: dict[str, DocCuration] = {}
    for doc_id, entry in (data.get("docs") or {}).items():
        if not isinstance(entry, dict) or not str(entry.get("summary", "")).strip():
            raise ConfigError(f"curated doc '{doc_id}' needs a non-empty summary")
        docs[doc_id] = DocCuration(
            summary=str(entry["summary"]).strip(),
            read_when=str(entry.get("read_when", "")).strip(),
        )

    return Curated(category_overviews=dict(overviews), docs=docs, source_exists=True)


def validate_against_registry(curated: Curated, registry) -> None:
    """Curation referencing missing docs/categories is a loud startup error."""
    known_categories = {c.id for c in registry.config.categories}
    unknown_cats = set(curated.category_overviews) - known_categories
    if unknown_cats:
        raise ConfigError(f"curated overviews for unknown categories: {sorted(unknown_cats)}")
    unknown_docs = set(curated.docs) - set(registry.docs)
    if unknown_docs:
        raise ConfigError(f"curated summaries for unknown docs: {sorted(unknown_docs)}")


def needs_curation(curated: Curated, registry) -> list[str]:
    """Full-depth docs without an authored summary (search-only docs exempt)."""
    return sorted(
        doc.id
        for doc in registry.docs.values()
        if doc.depth == "full" and doc.id not in curated.docs
    )
