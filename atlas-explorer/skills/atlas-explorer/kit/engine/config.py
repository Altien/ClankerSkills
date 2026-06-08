"""Configuration loading for the Atlas engine.

The engine is repo-agnostic: every repo-specific value (corpus globs,
categories, branding, paths) comes from atlas.config.yaml. The loader
validates structure loudly at startup so misconfiguration never degrades
silently into a half-empty site.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from pathlib import Path

import yaml

VALID_DEPTHS = ("full", "search-only")
VALID_RENDERS = ("internal", "external")


class ConfigError(Exception):
    """Raised when atlas.config.yaml is structurally invalid."""


@dataclass(frozen=True)
class SiteConfig:
    title: str
    subtitle: str = ""


@dataclass(frozen=True)
class Category:
    id: str
    title: str


@dataclass(frozen=True)
class CorpusEntry:
    include: tuple[str, ...]
    exclude: tuple[str, ...] = ()
    depth: str = "full"        # full | search-only
    render: str = "internal"   # internal | external


@dataclass(frozen=True)
class CategoryRule:
    match: str       # fnmatch pattern against the repo-relative doc id
    category: str    # must be a declared category id


@dataclass(frozen=True)
class LanguageSpec:
    extensions: tuple[str, ...]   # e.g. (".ts",)
    grammar: str                  # "module:function", e.g. "tree_sitter_typescript:language_typescript"


@dataclass(frozen=True)
class ArtifactLink:
    """Deep-link docs to a sibling tool (e.g. the explorer) via its manifest."""

    match: str          # fnmatch pattern against doc ids
    title: str          # link label shown in the doc view
    url_template: str   # "...#/a/{id}" — {id} replaced with the artifact id
    manifest: str       # repo-relative JSON manifest with [{id, source_path}, ...]


@dataclass(frozen=True)
class AtlasConfig:
    site: SiteConfig
    repo_root: Path
    corpus: tuple[CorpusEntry, ...]
    categories: tuple[Category, ...]
    category_rules: tuple[CategoryRule, ...]
    code_roots: tuple[str, ...] = ()   # first path segments eligible as code references
    drift_exempt: tuple[str, ...] = ()  # doc-id patterns whose broken refs are expected (e.g. changelogs)
    languages: tuple[LanguageSpec, ...] = ()
    artifact_links: tuple[ArtifactLink, ...] = ()
    db_path: Path = field(default_factory=Path)  # FTS index + durable comments
    curated_dir: Path = field(default_factory=Path)  # authored YAML (summaries, claims, ...)
    port: int = 8400
    base_dir: Path = field(default_factory=Path)

    def category_for(self, doc_id: str) -> str | None:
        """First matching rule wins; None means unassigned (a startup error)."""
        for rule in self.category_rules:
            if fnmatch.fnmatch(doc_id, rule.match):
                return rule.category
        return None


def _require(data: dict, key: str, where: str):
    if key not in data or data[key] in (None, "", []):
        raise ConfigError(f"missing required key '{key}' in {where}")
    return data[key]


def load_config(path: Path | str) -> AtlasConfig:
    path = Path(path)
    if not path.is_file():
        raise ConfigError(f"config file not found: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"config root must be a mapping: {path}")

    site_raw = _require(data, "site", str(path))
    site = SiteConfig(
        title=_require(site_raw, "title", "site"),
        subtitle=site_raw.get("subtitle", ""),
    )

    repo_root = (path.parent / _require(data, "repo_root", str(path))).resolve()
    if not repo_root.is_dir():
        raise ConfigError(f"repo_root does not exist: {repo_root}")

    categories = tuple(
        Category(id=_require(c, "id", "categories[]"), title=_require(c, "title", "categories[]"))
        for c in _require(data, "categories", str(path))
    )
    category_ids = {c.id for c in categories}
    if len(category_ids) != len(categories):
        raise ConfigError("duplicate category ids")

    corpus = []
    for i, entry in enumerate(_require(data, "corpus", str(path))):
        include = entry.get("include") or []
        if not include:
            raise ConfigError(f"corpus[{i}] has no include globs")
        depth = entry.get("depth", "full")
        if depth not in VALID_DEPTHS:
            raise ConfigError(f"corpus[{i}] depth '{depth}' not in {VALID_DEPTHS}")
        render = entry.get("render", "internal")
        if render not in VALID_RENDERS:
            raise ConfigError(f"corpus[{i}] render '{render}' not in {VALID_RENDERS}")
        corpus.append(
            CorpusEntry(
                include=tuple(include),
                exclude=tuple(entry.get("exclude") or ()),
                depth=depth,
                render=render,
            )
        )

    rules = []
    for i, rule in enumerate(_require(data, "category_rules", str(path))):
        category = _require(rule, "category", f"category_rules[{i}]")
        if category not in category_ids:
            raise ConfigError(f"category_rules[{i}] references unknown category '{category}'")
        rules.append(CategoryRule(match=_require(rule, "match", f"category_rules[{i}]"), category=category))

    code_refs_raw = data.get("code_references") or {}
    code_roots = tuple(code_refs_raw.get("roots") or ())
    if any(not isinstance(r, str) or "/" in r for r in code_roots):
        raise ConfigError("code_references.roots must be plain top-level directory names")

    languages = []
    for i, lang in enumerate(data.get("languages") or ()):
        extensions = tuple(lang.get("extensions") or ())
        grammar = lang.get("grammar", "")
        if not extensions or any(not e.startswith(".") for e in extensions):
            raise ConfigError(f"languages[{i}] extensions must be like ['.ts']")
        if ":" not in grammar:
            raise ConfigError(f"languages[{i}] grammar must be 'module:function'")
        languages.append(LanguageSpec(extensions=extensions, grammar=grammar))

    artifact_links = []
    for i, link in enumerate(data.get("artifact_links") or ()):
        for key in ("match", "title", "url_template", "manifest"):
            if not link.get(key):
                raise ConfigError(f"artifact_links[{i}] missing '{key}'")
        artifact_links.append(
            ArtifactLink(
                match=link["match"],
                title=link["title"],
                url_template=link["url_template"],
                manifest=link["manifest"],
            )
        )

    return AtlasConfig(
        site=site,
        repo_root=repo_root,
        corpus=tuple(corpus),
        categories=categories,
        category_rules=tuple(rules),
        code_roots=code_roots,
        drift_exempt=tuple(data.get("drift_exempt") or ()),
        languages=tuple(languages),
        artifact_links=tuple(artifact_links),
        db_path=(path.parent / data.get("db_path", "data/atlas.db")).resolve(),
        curated_dir=(path.parent / data.get("curated_dir", "curated")).resolve(),
        port=int(data.get("port", 8400)),
        base_dir=path.parent.resolve(),
    )
