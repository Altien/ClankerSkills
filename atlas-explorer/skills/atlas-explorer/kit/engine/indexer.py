"""Corpus indexer: scan markdown docs into structured entries.

Extracts titles, headings (with stable slugs that the renderer reuses),
and doc-to-doc links. Fenced code blocks are skipped so a `# comment`
inside a code sample never becomes a heading.
"""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath

from .config import AtlasConfig, ConfigError, CorpusEntry

MARKDOWN_SUFFIXES = (".md", ".markdown")
HTML_SUFFIXES = (".html", ".htm")

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_FENCE_RE = re.compile(r"^(```|~~~)")
_LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
_SLUG_STRIP_RE = re.compile(r"[^\w\s-]")
_SLUG_DASH_RE = re.compile(r"[\s_]+")
# Path-like tokens: at least one slash, sane path characters.
_PATH_TOKEN_RE = re.compile(r"(?:[A-Za-z0-9_.\-]+/)+[A-Za-z0-9_.\-*]+/?")
_LINE_SUFFIX_RE = re.compile(r":[\d:,-]+$")
# Symbol mentions: `name()` tokens — paired with a code ref on the same line.
_SYMBOL_TOKEN_RE = re.compile(r"\b([A-Za-z_$][A-Za-z0-9_$]*(?:\.[A-Za-z_$][A-Za-z0-9_$]*)?)\(\)")


def slugify(text: str) -> str:
    """Heading text -> anchor slug. Must stay in lockstep with render.py."""
    text = _SLUG_STRIP_RE.sub("", text.strip().lower())
    return _SLUG_DASH_RE.sub("-", text).strip("-") or "section"


class SlugDeduper:
    """Per-document slug uniquifier: repeated headings get -2, -3, ..."""

    def __init__(self) -> None:
        self._seen: dict[str, int] = {}

    def take(self, text: str) -> str:
        base = slugify(text)
        count = self._seen.get(base, 0) + 1
        self._seen[base] = count
        return base if count == 1 else f"{base}-{count}"


@dataclass(frozen=True)
class Heading:
    level: int
    text: str
    slug: str


@dataclass(frozen=True)
class CodeRef:
    """A doc's mention of a code path, validated against the real tree."""

    raw: str          # the token as written (line suffixes stripped)
    target: str       # normalized repo-relative path
    resolved: bool    # exists on disk at index time
    is_dir: bool
    in_fence: bool    # found inside a fenced code block
    section: str | None = None  # slug of the nearest preceding heading


@dataclass
class SymbolRef:
    """A doc's mention of a symbol (`name()`) paired with a same-line code ref.

    Resolution happens at registry build time, once the symbol index exists:
    True/False = verified against the AST; None = the file's language has
    no configured grammar, so the claim is unverifiable.
    """

    raw: str                 # token as written, e.g. "dispatchSession()"
    name: str                # bare or dotted symbol name
    target: str              # repo-relative file the mention is paired with
    resolved: bool | None = None
    section: str | None = None  # slug of the nearest preceding heading


def find_code_ref_tokens(line: str, code_roots: tuple[str, ...]) -> list[tuple[str, int]]:
    """(token, position) pairs whose first segment is a configured code root.

    The root allowlist keeps prose like "and/or" or URL fragments from
    becoming (false) drift entries; existence is checked by the caller.
    Positions let symbol mentions pair with their *nearest* file reference.
    """
    tokens: list[tuple[str, int]] = []
    for match in _PATH_TOKEN_RE.finditer(line):
        token = _LINE_SUFFIX_RE.sub("", match.group(0)).rstrip(".,;:")
        first = token.split("/", 1)[0]
        if first in code_roots and "*" not in token:
            tokens.append((token, match.start()))
    return tokens


@dataclass
class DocEntry:
    id: str                  # repo-relative posix path, e.g. "docs/guide.md"
    path: Path               # absolute path on disk
    title: str
    category: str | None
    depth: str               # full | search-only
    render: str              # internal | external
    headings: list[Heading] = field(default_factory=list)
    link_targets: list[str] = field(default_factory=list)  # raw repo-relative candidates
    links: list[str] = field(default_factory=list)          # resolved ids (set by registry)
    code_refs: list[CodeRef] = field(default_factory=list)
    symbol_refs: list[SymbolRef] = field(default_factory=list)
    plain_text: str | None = None   # extracted text for non-markdown docs (HTML)
    mtime: float = 0.0

    @property
    def is_markdown(self) -> bool:
        return self.path.suffix.lower() in MARKDOWN_SUFFIXES

    @property
    def is_html(self) -> bool:
        return self.path.suffix.lower() in HTML_SUFFIXES

    def code_ref_for(self, raw: str) -> CodeRef | None:
        for ref in self.code_refs:
            if ref.raw == raw:
                return ref
        return None

    def symbol_ref_for(self, raw: str) -> SymbolRef | None:
        for ref in self.symbol_refs:
            if ref.raw == raw:
                return ref
        return None


def iter_sections(text: str):
    """Split a doc into (heading_text|None, slug|None, body) sections.

    Heading slugs use the same SlugDeduper walk as parse_doc/render_doc,
    so a search hit's anchor always matches the rendered page. The chunk
    before the first heading is yielded with (None, None).
    """
    deduper = SlugDeduper()
    heading_text: str | None = None
    slug: str | None = None
    body: list[str] = []
    for line, in_fence in _iter_content_lines(text):
        match = None if in_fence else _HEADING_RE.match(line)
        if match:
            if body or heading_text is not None:
                yield heading_text, slug, "\n".join(body).strip()
            heading_text = match.group(2).strip()
            slug = deduper.take(heading_text)
            body = []
        else:
            body.append(line)
    yield heading_text, slug, "\n".join(body).strip()


def _iter_content_lines(text: str):
    """Yield (line, in_fence) tracking fenced code blocks."""
    fence: str | None = None
    for line in text.splitlines():
        match = _FENCE_RE.match(line.strip())
        if match:
            marker = match.group(1)
            if fence is None:
                fence = marker
            elif marker == fence:
                fence = None
            yield line, True
            continue
        yield line, fence is not None


class _HTMLTextExtractor(HTMLParser):
    """Pull title, heading outline, and visible text out of an HTML page."""

    _SKIP = {"script", "style", "noscript", "template"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.headings: list[tuple[int, str]] = []
        self._chunks: list[str] = []
        self._stack: list[str] = []
        self._heading_level: int | None = None
        self._heading_parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        self._stack.append(tag)
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._heading_level = int(tag[1])
            self._heading_parts = []

    def handle_endtag(self, tag):
        while self._stack and self._stack.pop() != tag:
            pass
        if self._heading_level is not None and tag == f"h{self._heading_level}":
            text = " ".join("".join(self._heading_parts).split())
            if text:
                self.headings.append((self._heading_level, text))
            self._heading_level = None

    def handle_data(self, data):
        if any(tag in self._SKIP for tag in self._stack):
            return
        if self._stack and self._stack[-1] == "title" and not self.title:
            self.title = " ".join(data.split())
        if self._heading_level is not None:
            self._heading_parts.append(data)
        stripped = " ".join(data.split())
        if stripped:
            self._chunks.append(stripped)

    @property
    def text(self) -> str:
        return " ".join(self._chunks)


def _parse_html_doc(
    doc_id: str, path: Path, *, category: str | None, depth: str, render: str
) -> DocEntry:
    extractor = _HTMLTextExtractor()
    extractor.feed(path.read_text(encoding="utf-8", errors="replace"))
    deduper = SlugDeduper()
    headings = [Heading(level, text, deduper.take(text)) for level, text in extractor.headings]
    title = extractor.title or next((t for _, t in extractor.headings), PurePosixPath(doc_id).stem)
    return DocEntry(
        id=doc_id,
        path=path,
        title=title,
        category=category,
        depth=depth,
        render=render,
        headings=headings,
        plain_text=extractor.text,
        mtime=path.stat().st_mtime,
    )


def parse_doc(
    doc_id: str,
    path: Path,
    *,
    category: str | None,
    depth: str,
    render: str,
    repo_root: Path | None = None,
    code_roots: tuple[str, ...] = (),
) -> DocEntry:
    if path.suffix.lower() in HTML_SUFFIXES:
        return _parse_html_doc(
            doc_id, path, category=category, depth=depth, render=render
        )
    if depth == "search-only":
        # Search-only docs are indexed for FTS and readable, but never feed
        # chips or drift — their references are not the doc's claims.
        repo_root = None
        code_roots = ()

    text = path.read_text(encoding="utf-8", errors="replace")
    headings: list[Heading] = []
    link_targets: list[str] = []
    code_refs: list[CodeRef] = []
    symbol_refs: list[SymbolRef] = []
    seen_refs: set[str] = set()
    seen_symbols: set[str] = set()
    deduper = SlugDeduper()
    doc_dir = PurePosixPath(doc_id).parent

    current_slug: str | None = None

    for line, in_fence in _iter_content_lines(text):
        heading = None if in_fence else _HEADING_RE.match(line)
        if heading:
            text_part = heading.group(2).strip()
            current_slug = deduper.take(text_part)
            headings.append(Heading(len(heading.group(1)), text_part, current_slug))

        line_file_refs: list[tuple[int, CodeRef]] = []
        if repo_root is not None and code_roots:
            for token, position in find_code_ref_tokens(line, code_roots):
                target = str(PurePosixPath(token))
                on_disk = repo_root / target
                ref = CodeRef(
                    raw=token,
                    target=target,
                    resolved=on_disk.exists(),
                    is_dir=on_disk.is_dir(),
                    in_fence=in_fence,
                    section=current_slug,
                )
                if ref.resolved and not ref.is_dir:
                    line_file_refs.append((position, ref))
                if token in seen_refs:
                    continue
                seen_refs.add(token)
                code_refs.append(ref)
            # `name()` mentions pair with the NEAREST resolved file ref on their line
            if line_file_refs and not in_fence:
                for match in _SYMBOL_TOKEN_RE.finditer(line):
                    raw = match.group(0)
                    if raw in seen_symbols:
                        continue
                    seen_symbols.add(raw)
                    _, paired = min(
                        line_file_refs, key=lambda pair: abs(pair[0] - match.start())
                    )
                    symbol_refs.append(
                        SymbolRef(
                            raw=raw,
                            name=match.group(1),
                            target=paired.target,
                            section=current_slug,
                        )
                    )
        if in_fence or heading:
            continue
        for match in _LINK_RE.finditer(line):
            target = match.group(2).split("#", 1)[0]
            if not target or "://" in target or target.startswith(("mailto:", "#", "/")):
                continue
            if not target.lower().endswith((".md", ".markdown")):
                continue
            resolved = resolve_relative(doc_dir, target)
            if resolved is not None:
                link_targets.append(resolved)

    title = next((h.text for h in headings if h.level == 1), PurePosixPath(doc_id).stem)
    return DocEntry(
        id=doc_id,
        path=path,
        title=title,
        category=category,
        depth=depth,
        render=render,
        headings=headings,
        link_targets=link_targets,
        code_refs=code_refs,
        symbol_refs=symbol_refs,
        mtime=path.stat().st_mtime,
    )


def resolve_relative(doc_dir: PurePosixPath, target: str) -> str | None:
    """Resolve a relative link against a doc's directory to a repo-relative id."""
    parts: list[str] = list(doc_dir.parts)
    for piece in PurePosixPath(target).parts:
        if piece == ".":
            continue
        if piece == "..":
            if not parts:
                return None  # escapes the repo
            parts.pop()
        else:
            parts.append(piece)
    return str(PurePosixPath(*parts)) if parts else None


def _matched_files(entry: CorpusEntry, repo_root: Path) -> list[tuple[str, Path]]:
    """Match include globs; a pattern that hits nothing is a loud error.

    Dead globs silently shrink the corpus (a renamed directory would just
    drop its docs), so every pattern must justify its existence.
    """
    found: list[tuple[str, Path]] = []
    for pattern in entry.include:
        matched_any = False
        for path in sorted(repo_root.glob(pattern)):
            if not path.is_file():
                continue
            matched_any = True
            doc_id = path.relative_to(repo_root).as_posix()
            if any(fnmatch.fnmatch(doc_id, ex) for ex in entry.exclude):
                continue
            found.append((doc_id, path))
        if not matched_any:
            raise ConfigError(
                f"corpus include glob matched no files: '{pattern}' — "
                "fix the glob or remove it"
            )
    return found


def scan_corpus(config: AtlasConfig) -> dict[str, DocEntry]:
    """Scan every corpus entry; first entry to claim a doc id wins."""
    docs: dict[str, DocEntry] = {}
    for i, entry in enumerate(config.corpus):
        matches = _matched_files(entry, config.repo_root)
        if not matches:
            raise ConfigError(
                f"corpus[{i}] matched no files (include={list(entry.include)}) — "
                "fix the glob or remove the entry"
            )
        for doc_id, path in matches:
            if doc_id in docs:
                continue
            docs[doc_id] = parse_doc(
                doc_id,
                path,
                category=config.category_for(doc_id),
                depth=entry.depth,
                render=entry.render,
                repo_root=config.repo_root,
                code_roots=config.code_roots,
            )
    return docs
