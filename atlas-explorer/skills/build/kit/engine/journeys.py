"""Journeys: authored, sequenced reading paths through docs and code.

curated/journeys.yaml defines ordered stops; each stop targets a doc, a
doc section, or a code symbol, and carries hand-written narration. The
journey view shows narration beside the LIVE target content — never a
copy — so journeys can't silently go stale: a dangling target surfaces
as curation drift, not a 500.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .config import ConfigError


@dataclass(frozen=True)
class Stop:
    narration: str
    title: str = ""
    doc: str | None = None       # corpus doc id
    heading: str | None = None   # heading slug within the doc
    path: str | None = None      # repo-relative code path
    symbol: str | None = None    # symbol within the code file

    @property
    def kind(self) -> str:
        if self.path:
            return "code"
        if self.heading:
            return "doc-section"
        return "doc"

    @property
    def label(self) -> str:
        if self.title:
            return self.title
        if self.path:
            return f"{self.path}::{self.symbol}" if self.symbol else self.path
        return f"{self.doc} § {self.heading}" if self.heading else (self.doc or "?")


@dataclass(frozen=True)
class Journey:
    id: str
    title: str
    intro: str
    stops: tuple[Stop, ...]


@dataclass(frozen=True)
class DanglingStop:
    journey_id: str
    stop_index: int   # 0-based
    label: str
    reason: str


def load_journeys(path: Path) -> list[Journey]:
    if not path.is_file():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    journeys: list[Journey] = []
    seen: set[str] = set()
    for i, raw in enumerate(data):
        journey_id = raw.get("id", "")
        if not journey_id or journey_id in seen:
            raise ConfigError(f"journeys[{i}] needs a unique id")
        seen.add(journey_id)
        for key in ("title", "intro"):
            if not str(raw.get(key, "")).strip():
                raise ConfigError(f"journey '{journey_id}' missing '{key}'")
        stops_raw = raw.get("stops") or []
        if not stops_raw:
            raise ConfigError(f"journey '{journey_id}' has no stops")
        stops = []
        for j, stop in enumerate(stops_raw):
            if not str(stop.get("narration", "")).strip():
                raise ConfigError(f"journey '{journey_id}' stop {j + 1} missing narration")
            has_doc = bool(stop.get("doc"))
            has_path = bool(stop.get("path"))
            if has_doc == has_path:  # neither, or both
                raise ConfigError(
                    f"journey '{journey_id}' stop {j + 1} must target exactly one of doc/path"
                )
            stops.append(
                Stop(
                    narration=str(stop["narration"]).strip(),
                    title=str(stop.get("title", "")).strip(),
                    doc=stop.get("doc"),
                    heading=stop.get("heading"),
                    path=stop.get("path"),
                    symbol=stop.get("symbol"),
                )
            )
        journeys.append(
            Journey(
                id=journey_id,
                title=str(raw["title"]).strip(),
                intro=str(raw["intro"]).strip(),
                stops=tuple(stops),
            )
        )
    return journeys


def resolve_stop(stop: Stop, registry) -> str | None:
    """None if the stop resolves; otherwise a human-readable reason."""
    if stop.doc is not None:
        doc = registry.docs.get(stop.doc)
        if doc is None:
            return f"doc '{stop.doc}' is not in the corpus"
        if stop.heading and not any(h.slug == stop.heading for h in doc.headings):
            return f"heading '{stop.heading}' not found in {stop.doc}"
        return None
    target = registry.config.repo_root / (stop.path or "")
    if not target.is_file():
        return f"file '{stop.path}' does not exist"
    if stop.symbol:
        file_symbols = registry.symbols.index_for(target)
        if file_symbols.language is None:
            return f"no grammar configured for {stop.path}"
        if file_symbols.find(stop.symbol) is None:
            return f"symbol '{stop.symbol}' not found in {stop.path}"
    return None


def find_dangling(journeys: list[Journey], registry) -> list[DanglingStop]:
    dangling: list[DanglingStop] = []
    for journey in journeys:
        for index, stop in enumerate(journey.stops):
            reason = resolve_stop(stop, registry)
            if reason is not None:
                dangling.append(DanglingStop(journey.id, index, stop.label, reason))
    return dangling
