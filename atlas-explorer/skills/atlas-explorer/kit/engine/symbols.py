"""AST-accurate symbol indexing via tree-sitter.

Languages are declared in config ("module:function" grammar specs), loaded
eagerly so a missing grammar wheel fails at startup, not mid-request.
Symbol extraction walks top-level declarations (plus class/interface
members one level down) and records exact line spans — these drive
jump-to-symbol, fold regions, and doc→symbol drift verification.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from pathlib import Path

from tree_sitter import Language, Parser

from .config import ConfigError, LanguageSpec

# Friendly names for common declaration node types; anything unmapped
# falls back to the raw node type with _declaration/_definition stripped.
_KIND_MAP = {
    "function_declaration": "function",
    "generator_function_declaration": "function",
    "class_declaration": "class",
    "abstract_class_declaration": "class",
    "interface_declaration": "interface",
    "type_alias_declaration": "type",
    "enum_declaration": "enum",
    "method_definition": "method",
    "abstract_method_signature": "method",
    "public_field_definition": "field",
    "internal_module": "namespace",
}

_DECL_TYPES = tuple(
    t for t in _KIND_MAP if t not in ("method_definition", "abstract_method_signature", "public_field_definition")
) + ("lexical_declaration", "variable_declaration")


@dataclass
class Symbol:
    name: str
    kind: str
    start_line: int  # 0-based, inclusive
    end_line: int    # 0-based, inclusive
    exported: bool = False
    children: list["Symbol"] = field(default_factory=list)
    qualified: str = ""

    @property
    def span_lines(self) -> int:
        return self.end_line - self.start_line + 1


@dataclass
class FileSymbols:
    path: Path
    language: str | None      # None = no grammar configured for this extension
    symbols: list[Symbol] = field(default_factory=list)

    def flat(self) -> list[Symbol]:
        out: list[Symbol] = []
        for sym in self.symbols:
            out.append(sym)
            out.extend(sym.children)
        return out

    def find(self, name: str) -> Symbol | None:
        """Match by qualified name ('Class.method') or bare name."""
        for sym in self.flat():
            if sym.qualified == name or sym.name == name:
                return sym
        return None


def _kind_for(node_type: str) -> str:
    if node_type in _KIND_MAP:
        return _KIND_MAP[node_type]
    return node_type.removesuffix("_declaration").removesuffix("_definition")


def _name_of(node) -> str | None:
    name_node = node.child_by_field_name("name")
    if name_node is not None:
        return name_node.text.decode("utf-8", errors="replace")
    return None


def _symbols_from_declaration(node, *, exported: bool) -> list[Symbol]:
    node_type = node.type
    if node_type in ("lexical_declaration", "variable_declaration"):
        out = []
        for declarator in node.children:
            if declarator.type != "variable_declarator":
                continue
            name = _name_of(declarator)
            if not name:
                continue
            value = declarator.child_by_field_name("value")
            kind = "function" if value is not None and value.type in (
                "arrow_function",
                "function_expression",
            ) else "const"
            out.append(
                Symbol(name, kind, node.start_point[0], node.end_point[0], exported=exported)
            )
        return out

    name = _name_of(node)
    if not name:
        return []
    symbol = Symbol(
        name, _kind_for(node_type), node.start_point[0], node.end_point[0], exported=exported
    )

    body = node.child_by_field_name("body")
    if body is not None and node_type in (
        "class_declaration",
        "abstract_class_declaration",
        "interface_declaration",
    ):
        for member in body.children:
            if member.type in ("method_definition", "abstract_method_signature"):
                member_name = _name_of(member)
                if member_name:
                    symbol.children.append(
                        Symbol(
                            member_name,
                            "method",
                            member.start_point[0],
                            member.end_point[0],
                        )
                    )
            elif member.type == "public_field_definition":
                member_name = _name_of(member)
                value = member.child_by_field_name("value")
                if member_name and value is not None and value.type == "arrow_function":
                    symbol.children.append(
                        Symbol(member_name, "method", member.start_point[0], member.end_point[0])
                    )
    return [symbol]


def extract_symbols(root) -> list[Symbol]:
    symbols: list[Symbol] = []
    for child in root.children:
        if child.type == "export_statement":
            for inner in child.children:
                if inner.type in _DECL_TYPES:
                    for sym in _symbols_from_declaration(inner, exported=True):
                        # span the whole export statement, not just the declaration
                        sym.start_line = child.start_point[0]
                        symbols.append(sym)
        elif child.type in _DECL_TYPES:
            symbols.extend(_symbols_from_declaration(child, exported=False))

    for sym in symbols:
        sym.qualified = sym.name
        for member in sym.children:
            member.qualified = f"{sym.name}.{member.name}"
    return symbols


class SymbolIndexer:
    """Lazy, mtime-aware symbol index over source files."""

    def __init__(self, languages: tuple[LanguageSpec, ...]):
        self._parsers: dict[str, tuple[str, Parser]] = {}  # extension -> (language name, parser)
        self._cache: dict[Path, tuple[float, FileSymbols]] = {}
        for spec in languages:
            parser = self._load_parser(spec)
            for extension in spec.extensions:
                self._parsers[extension] = (spec.grammar, parser)

    @staticmethod
    def _load_parser(spec: LanguageSpec) -> Parser:
        module_name, _, function_name = spec.grammar.partition(":")
        try:
            module = importlib.import_module(module_name)
            language_fn = getattr(module, function_name)
        except (ImportError, AttributeError) as exc:
            raise ConfigError(
                f"language grammar '{spec.grammar}' failed to load: {exc} — "
                f"is the wheel in requirements.txt?"
            ) from exc
        return Parser(Language(language_fn()))

    def supports(self, path: Path) -> bool:
        return path.suffix in self._parsers

    def index_for(self, path: Path) -> FileSymbols:
        entry = self._parsers.get(path.suffix)
        if entry is None or not path.is_file():
            return FileSymbols(path=path, language=None)

        mtime = path.stat().st_mtime
        cached = self._cache.get(path)
        if cached is not None and cached[0] == mtime:
            return cached[1]

        grammar_name, parser = entry
        tree = parser.parse(path.read_bytes())
        result = FileSymbols(path=path, language=grammar_name, symbols=extract_symbols(tree.root_node))
        self._cache[path] = (mtime, result)
        return result
