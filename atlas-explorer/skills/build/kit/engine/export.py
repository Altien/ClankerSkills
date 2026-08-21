"""Agent briefs: comments exported as paste-ready markdown.

The clipboard is the handoff mechanism (DESIGN §5): each brief carries
the comment, its anchor, and the sliced doc/code context so an agent in
any session can act on it without re-deriving where it points.
"""

from __future__ import annotations

from .comments import Comment
from .indexer import iter_sections

DEFAULT_CONTEXT_LINES = 200


def _bound(text: str, max_lines: int) -> tuple[str, bool]:
    lines = text.splitlines()
    if len(lines) <= max_lines:
        return text, False
    return "\n".join(lines[:max_lines]), True


def _context_for(comment: Comment, registry, max_lines: int) -> tuple[str, str]:
    """Return (language hint, context text) for the comment's anchor."""
    repo_root = registry.config.repo_root

    if comment.anchor_kind in ("doc", "doc-section"):
        doc = registry.docs.get(comment.doc_id or "")
        if doc is None:
            return "", ""
        text = doc.path.read_text(encoding="utf-8", errors="replace")
        if comment.anchor_kind == "doc":
            return "markdown", text
        for heading, slug, body in iter_sections(text):
            if slug == comment.heading:
                return "markdown", f"## {heading}\n\n{body}"
        return "", ""

    if comment.anchor_kind in ("code-symbol", "code-file"):
        path = repo_root / (comment.path or "")
        if not path.is_file():
            return "", ""
        text = path.read_text(encoding="utf-8", errors="replace")
        if comment.anchor_kind == "code-symbol" and comment.symbol:
            file_symbols = registry.symbols.index_for(path)
            target = file_symbols.find(comment.symbol) if file_symbols.language else None
            if target is not None:
                lines = text.splitlines()[target.start_line : target.end_line + 1]
                snippet = "\n".join(lines)
                return (
                    f"{path.suffix.lstrip('.')} · {comment.path} "
                    f"L{target.start_line + 1}–{target.end_line + 1}",
                    snippet,
                )
        return path.suffix.lstrip("."), text

    if comment.anchor_kind == "diagram-node":
        diagram = registry.diagram(comment.diagram_id or "")
        node = diagram.node(comment.node_id or "") if diagram else None
        if node is None:
            return "", ""
        anchored = _anchored_text(node, registry)
        return (
            f"diagram '{diagram.title}' · node '{node.label}'",
            f"Node summary: {node.summary}\n\n{anchored}".strip(),
        )

    if comment.anchor_kind == "journey-stop":
        journey = registry.journey(comment.journey_id or "")
        if journey is None:
            return "", ""
        try:
            stop = journey.stops[int(comment.stop_id or 0) - 1]
        except (ValueError, IndexError):
            return "", ""
        anchored = _anchored_text(stop, registry)
        return (
            f"journey '{journey.title}' · stop {comment.stop_id} ({stop.label})",
            f"Stop narration: {stop.narration}\n\n{anchored}".strip(),
        )

    return "", ""


def _anchored_text(target, registry) -> str:
    """Raw source text behind a journey stop or diagram node anchor."""
    if getattr(target, "path", None):
        path = registry.config.repo_root / target.path
        if not path.is_file():
            return ""
        text = path.read_text(encoding="utf-8", errors="replace")
        symbol = getattr(target, "symbol", None)
        if symbol:
            file_symbols = registry.symbols.index_for(path)
            found = file_symbols.find(symbol) if file_symbols.language else None
            if found is not None:
                return "\n".join(text.splitlines()[found.start_line : found.end_line + 1])
        return text
    doc = registry.docs.get(getattr(target, "doc", "") or "")
    if doc is None:
        return ""
    text = doc.path.read_text(encoding="utf-8", errors="replace")
    heading_slug = getattr(target, "heading", None)
    if heading_slug:
        for heading, slug, body in iter_sections(text):
            if slug == heading_slug:
                return f"## {heading}\n\n{body}"
    return text


def brief_for(comment: Comment, registry, max_lines: int = DEFAULT_CONTEXT_LINES) -> str:
    out: list[str] = [
        "# Atlas feedback brief",
        "",
        "Act on the feedback below. The anchor and source context identify exactly "
        "what it refers to inside this repository.",
        "",
        f"- **Type:** {comment.type}",
        f"- **Status:** {comment.status}",
        f"- **Anchor:** {comment.anchor_kind} — `{comment.anchor_label}`",
        f"- **Created:** {comment.created_at}",
    ]
    if comment.orphaned:
        out += [
            "",
            "> ⚠ **Anchor no longer resolves** — the referenced doc/heading/symbol is "
            "missing at index time. Context below is omitted; verify against the tree first.",
        ]
    if comment.quote:
        out += ["", "## Quoted text", "", f"> {comment.quote}"]
    out += ["", "## Feedback", "", comment.body]
    if comment.resolution_note:
        out += ["", f"_Resolution note so far: {comment.resolution_note}_"]

    if not comment.orphaned:
        hint, context = _context_for(comment, registry, max_lines)
        if context:
            bounded, truncated = _bound(context, max_lines)
            out += ["", f"## Anchored context ({hint})" if hint else "## Anchored context", ""]
            out += ["```", bounded, "```"]
            if truncated:
                out += ["", f"_(context truncated to {max_lines} lines)_"]
    return "\n".join(out) + "\n"


def bundle_for(comments: list[Comment], registry, max_lines: int = DEFAULT_CONTEXT_LINES) -> str:
    by_type: dict[str, int] = {}
    for comment in comments:
        by_type[comment.type] = by_type.get(comment.type, 0) + 1
    summary = " · ".join(f"{count} {kind}" for kind, count in sorted(by_type.items()))
    header = [
        "# Atlas feedback bundle",
        "",
        f"{len(comments)} comment(s): {summary or 'none'}.",
        "Work through each brief; they are independent unless they share an anchor.",
        "",
    ]
    briefs = [brief_for(comment, registry, max_lines) for comment in comments]
    return "\n".join(header) + "\n---\n\n".join(briefs)
