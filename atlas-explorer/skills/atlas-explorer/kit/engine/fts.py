"""SQLite FTS5 full-text search.

The FTS table is disposable — dropped and rebuilt on every reindex from
the registry snapshot. The same database file also holds durable tables
(comments); rebuilds must only ever touch fts_* tables.

Rows are heading-bounded sections (so hits land on the right anchor),
one preamble row per doc, and one row per code symbol of every file the
corpus references.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .indexer import iter_sections

_SCOPE_KINDS = {
    "all": None,
    "docs": ("doc", "section", "summary"),
    "code": ("symbol",),
    "claims": ("claim",),
}


@dataclass(frozen=True)
class SearchHit:
    kind: str       # doc | section | symbol | summary | claim
    ref: str        # doc id, "doc id#slug", or "path::symbol"
    title: str
    heading: str
    snippet: str    # body excerpt with <mark> highlights

    @property
    def url(self) -> str:
        if self.kind == "symbol":
            path, _, symbol = self.ref.partition("::")
            return f"/code/{path}?symbol={symbol}" if symbol else f"/code/{path}"
        if self.kind == "claim":
            return "/drift"
        doc_id, _, slug = self.ref.partition("#")
        return f"/doc/{doc_id}#{slug}" if slug else f"/doc/{doc_id}"


class SearchIndex:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def rebuild(self, registry) -> int:
        """Drop and repopulate the FTS table from a registry snapshot."""
        rows: list[tuple[str, str, str, str, str]] = []

        for doc in registry.docs.values():
            if doc.plain_text is not None:
                # HTML and other extracted docs index as one row.
                rows.append(("doc", doc.id, doc.title, "", doc.plain_text))
                continue
            text = doc.path.read_text(encoding="utf-8", errors="replace")
            for heading, slug, body in iter_sections(text):
                if heading is None:
                    if body:
                        rows.append(("doc", doc.id, doc.title, "", body))
                elif body or heading:
                    rows.append(("section", f"{doc.id}#{slug}", doc.title, heading, body))

        # Authored summaries (issue 011) — searchable orientation layer.
        for doc_id, curation in registry.curated.docs.items():
            doc = registry.docs.get(doc_id)
            rows.append(
                (
                    "summary",
                    doc_id,
                    doc.title if doc else doc_id,
                    "summary",
                    f"{curation.summary} {curation.read_when}".strip(),
                )
            )

        # Curated quantitative claims (issue 007).
        for result in registry.claims:
            rows.append(
                (
                    "claim",
                    result.claim.doc,
                    result.claim.doc,
                    result.claim.id,
                    f"{result.claim.quote} — {result.message}. {result.claim.note}",
                )
            )

        # Symbols of every file the corpus actually references.
        seen_files: set[str] = set()
        for doc in registry.docs.values():
            for ref in doc.code_refs:
                if not ref.resolved or ref.is_dir or ref.target in seen_files:
                    continue
                seen_files.add(ref.target)
                file_symbols = registry.symbols.index_for(registry.config.repo_root / ref.target)
                if file_symbols.language is None:
                    continue
                for sym in file_symbols.flat():
                    rows.append(
                        (
                            "symbol",
                            f"{ref.target}::{sym.qualified}",
                            ref.target,
                            sym.qualified,
                            f"{sym.kind} {sym.qualified} in {ref.target}",
                        )
                    )

        conn = self._connect()
        try:
            with conn:
                conn.execute("DROP TABLE IF EXISTS fts")
                conn.execute(
                    "CREATE VIRTUAL TABLE fts USING fts5("
                    "kind, ref, title, heading, body, tokenize='porter unicode61')"
                )
                conn.executemany("INSERT INTO fts VALUES (?, ?, ?, ?, ?)", rows)
        finally:
            conn.close()
        return len(rows)

    def search(self, query: str, scope: str = "all", limit: int = 50) -> list[SearchHit]:
        query = query.strip()
        if not query:
            return []
        kinds = _SCOPE_KINDS.get(scope, None)
        kind_clause = ""
        params: list = []
        if kinds:
            kind_clause = f"AND kind IN ({','.join('?' * len(kinds))})"
            params.extend(kinds)

        sql = (
            "SELECT kind, ref, title, heading, "
            "snippet(fts, 4, '<mark>', '</mark>', '…', 14) AS snip "
            f"FROM fts WHERE fts MATCH ? {kind_clause} "
            "ORDER BY bm25(fts) LIMIT ?"
        )
        conn = self._connect()
        try:
            try:
                cursor = conn.execute(sql, [query, *params, limit])
            except sqlite3.OperationalError:
                # FTS5 syntax error (stray quotes/operators) — retry as a phrase.
                phrase = '"' + query.replace('"', '""') + '"'
                cursor = conn.execute(sql, [phrase, *params, limit])
            return [SearchHit(*row) for row in cursor.fetchall()]
        finally:
            conn.close()
