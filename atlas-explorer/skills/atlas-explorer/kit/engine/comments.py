"""Durable comments: the feedback substrate.

Comments live in the same SQLite file as the FTS index but in a durable
table that reindexes never touch. Single-user by design (DESIGN §5) —
no auth, no attribution. Anchors are a tagged union; v1 ships doc-section
and whole-doc, issue 010 adds code-symbol, issue 013 the rest.
"""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

ANCHOR_KINDS = ("doc", "doc-section", "code-symbol", "code-file", "diagram-node", "journey-stop")
COMMENT_TYPES = ("improve-doc", "question", "fix-drift", "idea")
STATUSES = ("open", "in-progress", "resolved")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS comments (
  id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  anchor_kind TEXT NOT NULL,
  doc_id TEXT,
  heading TEXT,
  path TEXT,
  symbol TEXT,
  diagram_id TEXT,
  node_id TEXT,
  journey_id TEXT,
  stop_id TEXT,
  type TEXT NOT NULL,
  body TEXT NOT NULL,
  quote TEXT,
  status TEXT NOT NULL DEFAULT 'open',
  resolution_note TEXT
)
"""

_COLUMNS = (
    "id", "created_at", "updated_at", "anchor_kind", "doc_id", "heading", "path",
    "symbol", "diagram_id", "node_id", "journey_id", "stop_id", "type", "body",
    "quote", "status", "resolution_note",
)


@dataclass
class Comment:
    id: str
    created_at: str
    updated_at: str
    anchor_kind: str
    doc_id: str | None
    heading: str | None
    path: str | None
    symbol: str | None
    diagram_id: str | None
    node_id: str | None
    journey_id: str | None
    stop_id: str | None
    type: str
    body: str
    quote: str | None
    status: str
    resolution_note: str | None
    orphaned: bool = field(default=False)  # set by anchor verification, not stored

    @property
    def anchor_label(self) -> str:
        if self.anchor_kind == "doc":
            return self.doc_id or "?"
        if self.anchor_kind == "doc-section":
            return f"{self.doc_id} § {self.heading}"
        if self.anchor_kind in ("code-symbol", "code-file"):
            return f"{self.path}::{self.symbol}" if self.symbol else (self.path or "?")
        if self.anchor_kind == "diagram-node":
            return f"diagram {self.diagram_id} · node {self.node_id}"
        if self.anchor_kind == "journey-stop":
            return f"journey {self.journey_id} · stop {self.stop_id}"
        return "?"

    @property
    def anchor_url(self) -> str:
        if self.anchor_kind == "doc-section" and self.doc_id:
            return f"/doc/{self.doc_id}#{self.heading}"
        if self.anchor_kind == "doc" and self.doc_id:
            return f"/doc/{self.doc_id}"
        if self.anchor_kind in ("code-symbol", "code-file") and self.path:
            return f"/code/{self.path}?symbol={self.symbol}" if self.symbol else f"/code/{self.path}"
        return "/feedback"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class CommentStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def create(
        self,
        *,
        anchor_kind: str,
        type: str,
        body: str,
        quote: str | None = None,
        **anchor_fields,
    ) -> Comment:
        if anchor_kind not in ANCHOR_KINDS:
            raise ValueError(f"unknown anchor kind: {anchor_kind}")
        if type not in COMMENT_TYPES:
            raise ValueError(f"unknown comment type: {type}")
        if not body.strip():
            raise ValueError("comment body is empty")
        now = _now()
        comment = Comment(
            id=uuid.uuid4().hex[:12],
            created_at=now,
            updated_at=now,
            anchor_kind=anchor_kind,
            doc_id=anchor_fields.get("doc_id"),
            heading=anchor_fields.get("heading"),
            path=anchor_fields.get("path"),
            symbol=anchor_fields.get("symbol"),
            diagram_id=anchor_fields.get("diagram_id"),
            node_id=anchor_fields.get("node_id"),
            journey_id=anchor_fields.get("journey_id"),
            stop_id=anchor_fields.get("stop_id"),
            type=type,
            body=body.strip(),
            quote=(quote or "").strip() or None,
            status="open",
            resolution_note=None,
        )
        values = [getattr(comment, col) for col in _COLUMNS]
        with self._connect() as conn:
            conn.execute(
                f"INSERT INTO comments ({','.join(_COLUMNS)}) "
                f"VALUES ({','.join('?' * len(_COLUMNS))})",
                values,
            )
        return comment

    def get(self, comment_id: str) -> Comment | None:
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT {','.join(_COLUMNS)} FROM comments WHERE id = ?", (comment_id,)
            ).fetchone()
        return Comment(*row) if row else None

    def list(
        self,
        *,
        status: str | None = None,
        type: str | None = None,
        doc_id: str | None = None,
        anchor_kind: str | None = None,
        heading: str | None = None,
        path: str | None = None,
        diagram_id: str | None = None,
        node_id: str | None = None,
        journey_id: str | None = None,
        stop_id: str | None = None,
    ) -> list[Comment]:
        clauses, params = [], []
        for column, value in (
            ("status", status),
            ("type", type),
            ("doc_id", doc_id),
            ("anchor_kind", anchor_kind),
            ("heading", heading),
            ("path", path),
            ("diagram_id", diagram_id),
            ("node_id", node_id),
            ("journey_id", journey_id),
            ("stop_id", stop_id),
        ):
            if value:
                clauses.append(f"{column} = ?")
                params.append(value)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT {','.join(_COLUMNS)} FROM comments {where} ORDER BY created_at DESC",
                params,
            ).fetchall()
        return [Comment(*row) for row in rows]

    def update_body(self, comment_id: str, body: str) -> Comment | None:
        if not body.strip():
            raise ValueError("comment body is empty")
        with self._connect() as conn:
            conn.execute(
                "UPDATE comments SET body = ?, updated_at = ? WHERE id = ?",
                (body.strip(), _now(), comment_id),
            )
        return self.get(comment_id)

    def set_status(
        self, comment_id: str, status: str, resolution_note: str | None = None
    ) -> Comment | None:
        if status not in STATUSES:
            raise ValueError(f"unknown status: {status}")
        with self._connect() as conn:
            conn.execute(
                "UPDATE comments SET status = ?, resolution_note = ?, updated_at = ? WHERE id = ?",
                (status, (resolution_note or "").strip() or None, _now(), comment_id),
            )
        return self.get(comment_id)

    def delete(self, comment_id: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM comments WHERE id = ?", (comment_id,))
        return cursor.rowcount > 0

    def counts_by_section(self, doc_id: str) -> dict[str, int]:
        """Open-comment counts per heading slug ('' = whole-doc comments)."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT COALESCE(heading, ''), COUNT(*) FROM comments "
                "WHERE doc_id = ? AND status != 'resolved' "
                "AND anchor_kind IN ('doc', 'doc-section') GROUP BY heading",
                (doc_id,),
            ).fetchall()
        return {heading: count for heading, count in rows}


def verify_anchor(comment: Comment, registry) -> bool:
    """Does this comment's anchor still resolve against the current index?"""
    if comment.anchor_kind == "doc":
        return comment.doc_id in registry.docs
    if comment.anchor_kind == "doc-section":
        doc = registry.docs.get(comment.doc_id or "")
        if doc is None:
            return False
        return any(h.slug == comment.heading for h in doc.headings)
    if comment.anchor_kind in ("code-symbol", "code-file"):
        target = registry.config.repo_root / (comment.path or "")
        if not target.is_file():
            return False
        if comment.anchor_kind == "code-file" or not comment.symbol:
            return True
        file_symbols = registry.symbols.index_for(target)
        return file_symbols.language is not None and file_symbols.find(comment.symbol) is not None
    if comment.anchor_kind == "diagram-node":
        diagram = registry.diagram(comment.diagram_id or "")
        return diagram is not None and diagram.node(comment.node_id or "") is not None
    if comment.anchor_kind == "journey-stop":
        journey = registry.journey(comment.journey_id or "")
        if journey is None:
            return False
        try:
            return 1 <= int(comment.stop_id or 0) <= len(journey.stops)
        except ValueError:
            return False
    return True


def mark_orphans(comments: list[Comment], registry) -> list[Comment]:
    for comment in comments:
        comment.orphaned = not verify_anchor(comment, registry)
    return comments
