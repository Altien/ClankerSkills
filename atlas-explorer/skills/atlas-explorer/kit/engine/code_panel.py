"""Code panel rendering: highlighted source files and directory listings.

Server-side Pygments highlighting (the browser stays thin). Theme-aware
CSS is generated once per process from two Pygments styles — the dark
variant is scoped under html[data-theme="dark"].
"""

from __future__ import annotations

import html
import re
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote

from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import TextLexer, get_lexer_for_filename
from pygments.token import STANDARD_TYPES
from pygments.util import ClassNotFound

from .symbols import FileSymbols, Symbol, SymbolIndexer

LIGHT_STYLE = "default"
DARK_STYLE = "native"
MAX_PANEL_BYTES = 512 * 1024  # refuse to highlight monsters; show a notice instead
MIN_FOLD_LINES = 3            # symbols shorter than this aren't worth a fold

_ANCHOR_SAFE_RE = re.compile(r"[^A-Za-z0-9_.-]")


def _anchor(qualified: str) -> str:
    return "sym-" + _ANCHOR_SAFE_RE.sub("-", qualified)


class PanelError(Exception):
    """Raised for invalid panel requests (bad path, outside repo, missing)."""


def safe_resolve(repo_root: Path, raw_path: str) -> Path:
    """Resolve a repo-relative request path, refusing escapes."""
    candidate = (repo_root / raw_path).resolve()
    try:
        candidate.relative_to(repo_root.resolve())
    except ValueError:
        raise PanelError(f"path escapes the repository: {raw_path}") from None
    return candidate


@lru_cache(maxsize=1)
def pygments_css() -> str:
    light = HtmlFormatter(style=LIGHT_STYLE).get_style_defs(".highlight")
    dark = HtmlFormatter(style=DARK_STYLE).get_style_defs('html[data-theme="dark"] .highlight')
    return f"{light}\n\n{dark}\n"


def _comment_btn(anchor_kind: str, path: str, symbol: str | None = None, label: str = "💬") -> str:
    params = f"anchor_kind={quote(anchor_kind)}&path={quote(path)}"
    if symbol:
        params += f"&symbol={quote(symbol)}"
    return (
        f'<button class="panel-comment-btn" type="button" title="Comment here" '
        f'hx-get="/partial/comments?{params}" hx-target="#panel-thread" '
        f'hx-swap="innerHTML">{label}</button>'
    )


def _header(title: str, subtitle: str = "", comment_path: str | None = None) -> str:
    sub = f'<span class="panel-subtitle">{html.escape(subtitle)}</span>' if subtitle else ""
    comment = _comment_btn("code-file", comment_path) if comment_path else ""
    return (
        '<div class="panel-header">'
        f'<span class="panel-path">{html.escape(title)}</span>{sub}{comment}'
        '<button class="panel-close" type="button" '
        "onclick=\"document.getElementById('code-panel').innerHTML='';"
        "document.body.classList.remove('panel-open')\">×</button>"
        "</div>"
        '<div id="panel-thread" class="comment-thread panel-thread"></div>'
    )


def render_file(
    repo_root: Path,
    raw_path: str,
    symbol_index: SymbolIndexer | None = None,
    symbol: str | None = None,
) -> str:
    path = safe_resolve(repo_root, raw_path)
    if not path.exists():
        raise PanelError(f"not found: {raw_path}")
    if path.is_dir():
        return render_dir(repo_root, raw_path)

    size = path.stat().st_size
    if size > MAX_PANEL_BYTES:
        return _header(raw_path) + (
            f'<p class="panel-notice">File is {size // 1024} KB — too large to render inline.</p>'
        )

    text = path.read_text(encoding="utf-8", errors="replace")
    try:
        lexer = get_lexer_for_filename(path.name, text)
    except ClassNotFound:
        lexer = TextLexer()

    file_symbols = symbol_index.index_for(path) if symbol_index is not None else None
    line_count = text.count("\n") + 1

    if file_symbols is not None and file_symbols.language is not None and file_symbols.symbols:
        return _render_with_folds(raw_path, text, lexer, file_symbols, symbol, line_count)

    formatter = HtmlFormatter(cssclass="highlight", linenos="table", lineanchors="L", wrapcode=True)
    body = highlight(text, lexer, formatter)
    return (
        _header(raw_path, f"{line_count} lines", comment_path=raw_path)
        + f'<div class="panel-code">{body}</div>'
    )


# ── fold-aware rendering ─────────────────────────────────────────────


def _highlighted_lines(text: str, lexer) -> list[str]:
    """Highlight to per-line HTML, splitting multi-line tokens safely."""
    lines: list[list[str]] = [[]]
    for toktype, value in lexer.get_tokens(text):
        css = STANDARD_TYPES.get(toktype)
        while css is None:
            toktype = toktype.parent
            css = STANDARD_TYPES.get(toktype)
        for i, part in enumerate(value.split("\n")):
            if i:
                lines.append([])
            if part:
                escaped = html.escape(part)
                lines[-1].append(f'<span class="{css}">{escaped}</span>' if css else escaped)
    return ["".join(parts) for parts in lines]


def _foldable(symbols: list[Symbol]) -> list[Symbol]:
    return [s for s in symbols if s.span_lines >= MIN_FOLD_LINES]


def _open_ids(file_symbols: FileSymbols, target: Symbol | None) -> set[str] | None:
    """None = everything open (whole-file view); else only target + ancestors."""
    if target is None:
        return None
    open_ids = {target.qualified}
    for sym in file_symbols.symbols:
        if sym.start_line <= target.start_line and target.end_line <= sym.end_line:
            open_ids.add(sym.qualified)
    return open_ids


def _emit_line(out: list[str], lines: list[str], n: int, target: Symbol | None):
    in_target = target is not None and target.start_line <= n <= target.end_line
    css = "line hl-target" if in_target else "line"
    content = lines[n] if n < len(lines) else ""
    out.append(
        f'<div class="{css}"><span class="ln">{n + 1}</span><span class="lc">{content}</span></div>'
    )


def _emit_range(
    out: list[str],
    lines: list[str],
    start: int,
    end: int,
    folds: list[Symbol],
    open_ids: set[str] | None,
    target: Symbol | None,
):
    n = start
    for fold in folds:
        while n < fold.start_line and n <= end:
            _emit_line(out, lines, n, target)
            n += 1
        if n > fold.end_line:
            continue
        is_open = open_ids is None or fold.qualified in open_ids
        out.append(
            f'<details class="fold"{" open" if is_open else ""} id="{_anchor(fold.qualified)}">'
            "<summary>"
        )
        _emit_line(out, lines, fold.start_line, target)
        out.append("</summary>")
        _emit_range(
            out,
            lines,
            fold.start_line + 1,
            fold.end_line,
            _foldable(fold.children),
            open_ids,
            target,
        )
        out.append("</details>")
        n = fold.end_line + 1
    while n <= end:
        _emit_line(out, lines, n, target)
        n += 1


def _outline(raw_path: str, file_symbols: FileSymbols) -> str:
    def entry(sym: Symbol) -> str:
        href = f"/partial/code?path={quote(raw_path)}&symbol={quote(sym.qualified)}"
        children = ""
        if sym.children:
            children = "<ul>" + "".join(entry(c) for c in sym.children) + "</ul>"
        exported = ' <span class="sym-exported">export</span>' if sym.exported else ""
        comment = _comment_btn("code-symbol", raw_path, sym.qualified)
        return (
            f'<li><a href="#code-panel" hx-get="{href}" hx-target="#code-panel" '
            f'hx-swap="innerHTML">{html.escape(sym.name)}</a> '
            f'<span class="sym-kind">{sym.kind}</span>{exported}{comment}{children}</li>'
        )

    items = "".join(entry(s) for s in file_symbols.symbols)
    return (
        '<details class="outline"><summary>Outline '
        f'<span class="sym-kind">{len(file_symbols.flat())} symbols</span></summary>'
        f"<ul>{items}</ul></details>"
    )


def _render_with_folds(
    raw_path: str,
    text: str,
    lexer,
    file_symbols: FileSymbols,
    symbol: str | None,
    line_count: int,
) -> str:
    target = file_symbols.find(symbol) if symbol else None
    notice = ""
    if symbol and target is None:
        notice = (
            f'<p class="panel-notice">Symbol <code>{html.escape(symbol)}</code> '
            "not found — showing the whole file.</p>"
        )

    lines = _highlighted_lines(text, lexer)
    out: list[str] = []
    _emit_range(
        out,
        lines,
        0,
        line_count - 1,
        _foldable(file_symbols.symbols),
        _open_ids(file_symbols, target),
        target,
    )
    subtitle = f"{line_count} lines"
    if target is not None:
        subtitle += f" · {target.qualified} L{target.start_line + 1}–{target.end_line + 1}"
    return (
        _header(raw_path, subtitle, comment_path=raw_path)
        + notice
        + _outline(raw_path, file_symbols)
        + f'<div class="panel-code src">{"".join(out)}</div>'
    )


def render_dir(repo_root: Path, raw_path: str) -> str:
    path = safe_resolve(repo_root, raw_path)
    if not path.is_dir():
        raise PanelError(f"not a directory: {raw_path}")

    entries = sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
    items = []
    for entry in entries:
        rel = entry.relative_to(repo_root.resolve()).as_posix()
        name = entry.name + ("/" if entry.is_dir() else "")
        items.append(
            f'<li><a class="panel-dir-entry" href="#code-panel" '
            f'hx-get="/partial/code?path={quote(rel)}" '
            f'hx-target="#code-panel" hx-swap="innerHTML">{html.escape(name)}</a></li>'
        )
    listing = "".join(items) or "<li><em>empty directory</em></li>"
    return _header(raw_path.rstrip("/") + "/", f"{len(entries)} entries") + (
        f'<ul class="panel-dir">{listing}</ul>'
    )
