"""Markdown rendering for the doc view.

Server-side rendering via markdown-it-py with two passes over the token
stream before rendering:
  1. headings get id= anchors using the same slug rules as the indexer,
     so heading slugs in the index always match rendered anchors;
  2. relative links to other corpus docs are rewritten to Atlas routes.
"""

from __future__ import annotations

import html as html_mod
from pathlib import PurePosixPath
from typing import Mapping
from urllib.parse import quote

from markdown_it import MarkdownIt

from .indexer import DocEntry, SlugDeduper, resolve_relative


def _render_code_inline(self, tokens, idx, options, env):
    """Inline code spans that name a real code path become clickable chips.

    Corpus docs chip to their Atlas page; resolved code paths chip to the
    htmx code panel. Everything else falls through to plain <code>.
    """
    content = tokens[idx].content
    doc: DocEntry | None = env.get("doc")
    docs: Mapping[str, DocEntry] = env.get("docs", {})
    escaped = html_mod.escape(content)

    if doc is not None:
        stripped = content.strip().rstrip(".,;:")
        if stripped in docs:
            return f'<a class="code-chip doc-chip" href="/doc/{quote(stripped)}">{escaped}</a>'
        sym = doc.symbol_ref_for(stripped)
        if sym is not None:
            if sym.resolved:
                return (
                    f'<a class="code-chip sym-chip" href="#code-panel" '
                    f'hx-get="/partial/code?path={quote(sym.target)}&symbol={quote(sym.name)}" '
                    f'hx-target="#code-panel" hx-swap="innerHTML">{escaped}</a>'
                )
            if sym.resolved is False:
                return (
                    f'<code class="ref-broken" title="No symbol {html_mod.escape(sym.name)} '
                    f'in {html_mod.escape(sym.target)} at index time">{escaped}</code>'
                )
        ref = doc.code_ref_for(stripped)
        if ref is not None:
            if ref.resolved:
                if ref.target in docs:
                    return (
                        f'<a class="code-chip doc-chip" href="/doc/{quote(ref.target)}">'
                        f"{escaped}</a>"
                    )
                return (
                    f'<a class="code-chip" href="#code-panel" '
                    f'hx-get="/partial/code?path={quote(ref.target)}" '
                    f'hx-target="#code-panel" hx-swap="innerHTML">{escaped}</a>'
                )
            return (
                f'<code class="ref-broken" title="{html_mod.escape(ref.target)} '
                f'not found at index time">{escaped}</code>'
            )
    return f"<code>{escaped}</code>"


def _make_md() -> MarkdownIt:
    md = MarkdownIt("commonmark", {"html": True, "linkify": False}).enable("table").enable(
        "strikethrough"
    )
    md.add_render_rule("code_inline", _render_code_inline)
    return md


def render_doc(doc: DocEntry, docs: Mapping[str, DocEntry]) -> str:
    """Render a corpus doc to HTML with anchored headings and rewritten links."""
    text = doc.path.read_text(encoding="utf-8", errors="replace")
    md = _make_md()
    tokens = md.parse(text)
    deduper = SlugDeduper()
    doc_dir = PurePosixPath(doc.id).parent

    for i, token in enumerate(tokens):
        if token.type == "heading_open":
            inline = tokens[i + 1] if i + 1 < len(tokens) else None
            heading_text = inline.content if inline is not None else ""
            token.attrSet("id", deduper.take(heading_text))
        elif token.type == "inline" and token.children:
            for child in token.children:
                if child.type != "link_open":
                    continue
                href = child.attrGet("href") or ""
                new_href = _rewrite_href(href, doc_dir, docs)
                if new_href is not None:
                    child.attrSet("href", new_href)

    return md.renderer.render(tokens, md.options, {"doc": doc, "docs": docs})


def render_markdown_text(text: str) -> str:
    """Render standalone markdown (journey narration, section slices)."""
    md = _make_md()
    tokens = md.parse(text)
    return md.renderer.render(tokens, md.options, {})


def _rewrite_href(href: str, doc_dir: PurePosixPath, docs: Mapping[str, DocEntry]) -> str | None:
    """Rewrite a relative .md link to /doc/{id} when the target is in the corpus."""
    if not href or "://" in href or href.startswith(("mailto:", "#", "/")):
        return None
    target, _, anchor = href.partition("#")
    if not target.lower().endswith((".md", ".markdown")):
        return None
    resolved = resolve_relative(doc_dir, target)
    if resolved is None or resolved not in docs:
        return None
    suffix = f"#{anchor}" if anchor else ""
    return f"/doc/{resolved}{suffix}"
