"""Drift detection: where the docs and the tree disagree.

Built live from the current registry snapshot (so a reindex refreshes it
for free). Issue 007 adds curated quantitative claims on top.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field


@dataclass(frozen=True)
class DriftItem:
    doc_id: str
    kind: str            # "path" | "symbol"
    raw: str             # the reference as written in the doc
    detail: str          # human explanation
    section: str | None  # heading slug near the claim, for deep-linking

    @property
    def doc_url(self) -> str:
        return f"/doc/{self.doc_id}#{self.section}" if self.section else f"/doc/{self.doc_id}"


@dataclass
class DriftReport:
    items: list[DriftItem] = field(default_factory=list)
    unverifiable: int = 0   # symbol mentions in files with no configured grammar
    exempted: int = 0       # broken refs in drift-exempt docs (changelogs etc.)

    @property
    def count(self) -> int:
        return len(self.items)

    def by_doc(self) -> list[tuple[str, list[DriftItem]]]:
        grouped: dict[str, list[DriftItem]] = {}
        for item in self.items:
            grouped.setdefault(item.doc_id, []).append(item)
        return sorted(grouped.items(), key=lambda pair: (-len(pair[1]), pair[0]))


def build_drift(registry) -> DriftReport:
    report = DriftReport()
    exempt = registry.config.drift_exempt
    for doc in registry.docs.values():
        if doc.depth != "full":
            continue  # search-only docs don't make claims about the tree
        if any(fnmatch.fnmatch(doc.id, pattern) for pattern in exempt):
            report.exempted += sum(1 for r in doc.code_refs if not r.resolved)
            report.exempted += sum(1 for r in doc.symbol_refs if r.resolved is False)
            continue
        for ref in doc.code_refs:
            if not ref.resolved:
                where = " (inside a code block)" if ref.in_fence else ""
                report.items.append(
                    DriftItem(
                        doc_id=doc.id,
                        kind="path",
                        raw=ref.raw,
                        detail=f"references {ref.target}, which does not exist{where}",
                        section=ref.section,
                    )
                )
        for ref in doc.symbol_refs:
            if ref.resolved is False:
                report.items.append(
                    DriftItem(
                        doc_id=doc.id,
                        kind="symbol",
                        raw=ref.raw,
                        detail=f"mentions {ref.name}() paired with {ref.target}, "
                        "but no such symbol exists there",
                        section=ref.section,
                    )
                )
            elif ref.resolved is None:
                report.unverifiable += 1
    return report
