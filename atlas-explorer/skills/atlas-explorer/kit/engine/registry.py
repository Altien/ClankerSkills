"""The in-memory index registry.

A Registry is a complete, immutable-in-spirit snapshot of everything the
server knows: config, scanned docs, category grouping. Rebuilds construct
a brand-new Registry and swap it in atomically (one attribute assignment),
so in-flight requests always see a consistent index.
"""

from __future__ import annotations

import fnmatch
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .claims import ClaimResult, load_claims, run_claims
from .config import AtlasConfig, Category, ConfigError
from .curated import Curated, load_curated, needs_curation, validate_against_registry
from .diagrams import DanglingNode, Diagram, find_dangling_nodes, load_diagrams
from .indexer import DocEntry, scan_corpus
from .journeys import DanglingStop, Journey, find_dangling, load_journeys
from .symbols import SymbolIndexer


@dataclass
class Registry:
    config: AtlasConfig
    docs: dict[str, DocEntry]
    grouped: list[tuple[Category, list[DocEntry]]]
    symbols: SymbolIndexer
    claims: list[ClaimResult]
    artifact_links: dict[str, tuple[str, str]]  # doc id -> (label, url)
    curated: Curated
    uncurated: list[str]   # full-depth docs missing an authored summary
    journeys: list[Journey] = field(default_factory=list)
    dangling_stops: list[DanglingStop] = field(default_factory=list)
    diagrams: list[Diagram] = field(default_factory=list)
    dangling_nodes: list[DanglingNode] = field(default_factory=list)
    built_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    build_seconds: float = 0.0

    def journey(self, journey_id: str) -> Journey | None:
        return next((j for j in self.journeys if j.id == journey_id), None)

    def diagram(self, diagram_id: str) -> Diagram | None:
        return next((d for d in self.diagrams if d.id == diagram_id), None)

    def diagrams_for(self, doc_id: str) -> list[Diagram]:
        return [d for d in self.diagrams if d.doc == doc_id]

    def failing_claims_for(self, doc_id: str) -> list[ClaimResult]:
        return [r for r in self.claims if r.claim.doc == doc_id and r.status != "pass"]

    @property
    def doc_count(self) -> int:
        return len(self.docs)


def build_registry(config: AtlasConfig) -> Registry:
    start = time.perf_counter()
    docs = scan_corpus(config)
    symbols = SymbolIndexer(config.languages)  # eager grammar load: missing wheels fail here

    # Verify doc→symbol mentions against the AST of the paired file.
    for doc in docs.values():
        for ref in doc.symbol_refs:
            file_symbols = symbols.index_for(config.repo_root / ref.target)
            ref.resolved = (
                None if file_symbols.language is None else file_symbols.find(ref.name) is not None
            )

    unassigned = sorted(d.id for d in docs.values() if d.category is None)
    if unassigned:
        raise ConfigError(
            "docs matched no category rule (add rules or excludes): " + ", ".join(unassigned)
        )

    # Resolve raw link targets to known doc ids.
    for doc in docs.values():
        doc.links = [t for t in dict.fromkeys(doc.link_targets) if t in docs and t != doc.id]

    grouped: list[tuple[Category, list[DocEntry]]] = []
    for category in config.categories:
        members = sorted(
            (d for d in docs.values() if d.category == category.id),
            key=lambda d: d.title.lower(),
        )
        if members:
            grouped.append((category, members))

    claims = run_claims(config, symbols, load_claims(config.curated_dir / "claims.yaml"))
    artifact_links = _build_artifact_links(config, docs)
    curated = load_curated(config.curated_dir / "atlas.yaml")

    registry = Registry(
        config=config,
        docs=docs,
        grouped=grouped,
        symbols=symbols,
        claims=claims,
        artifact_links=artifact_links,
        curated=curated,
        uncurated=[],
        built_at=datetime.now(timezone.utc),
        build_seconds=round(time.perf_counter() - start, 3),
    )
    validate_against_registry(curated, registry)
    registry.uncurated = needs_curation(curated, registry)
    registry.journeys = load_journeys(config.curated_dir / "journeys.yaml")
    registry.dangling_stops = find_dangling(registry.journeys, registry)
    registry.diagrams = load_diagrams(config.curated_dir / "diagrams.yaml")
    registry.dangling_nodes = find_dangling_nodes(registry.diagrams, registry)
    return registry


def _build_artifact_links(config: AtlasConfig, docs: dict[str, DocEntry]) -> dict[str, tuple[str, str]]:
    """Map docs to sibling-tool deep links via each link's manifest."""
    links: dict[str, tuple[str, str]] = {}
    for link in config.artifact_links:
        manifest_path = config.repo_root / link.manifest
        if not manifest_path.is_file():
            raise ConfigError(f"artifact_links manifest not found: {link.manifest}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        artifacts = manifest.get("artifacts", manifest) if isinstance(manifest, dict) else manifest
        by_source = {
            a["source_path"]: a["id"]
            for a in artifacts
            if isinstance(a, dict) and a.get("source_path") and a.get("id")
        }
        for doc_id in docs:
            if fnmatch.fnmatch(doc_id, link.match) and doc_id in by_source:
                links[doc_id] = (link.title, link.url_template.format(id=by_source[doc_id]))
    return links
