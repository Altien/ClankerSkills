"""Indexer: discovery, titles, headings (fence-aware), link resolution."""

import pytest

from engine.config import ConfigError, load_config
from engine.indexer import scan_corpus, slugify
from engine.registry import build_registry


def test_scan_finds_docs(sample_config_path):
    docs = scan_corpus(load_config(sample_config_path))
    assert set(docs) == {"README.md", "docs/guide.md"}


def test_title_from_h1(sample_config_path):
    docs = scan_corpus(load_config(sample_config_path))
    assert docs["README.md"].title == "Sample Project"
    assert docs["docs/guide.md"].title == "User Guide"


def test_headings_skip_code_fences_and_dedupe_slugs(sample_config_path):
    docs = scan_corpus(load_config(sample_config_path))
    readme = docs["README.md"]
    texts = [h.text for h in readme.headings]
    assert texts == ["Sample Project", "Install", "Install"]
    slugs = [h.slug for h in readme.headings]
    assert slugs == ["sample-project", "install", "install-2"]


def test_links_resolved_to_known_docs_only(sample_config_path):
    registry = build_registry(load_config(sample_config_path))
    readme = registry.docs["README.md"]
    # docs/nope.md doesn't exist; the fenced fake link is skipped; external untouched.
    assert readme.links == ["docs/guide.md"]
    guide = registry.docs["docs/guide.md"]
    assert guide.links == ["README.md"]


def test_zero_match_corpus_entry_fails(sample_config_path):
    text = sample_config_path.read_text(encoding="utf-8").replace(
        '- include: ["*.md", "docs/*.md"]', '- include: ["nothing/**/*.md"]'
    )
    sample_config_path.write_text(text, encoding="utf-8")
    with pytest.raises(ConfigError, match="matched no files"):
        scan_corpus(load_config(sample_config_path))


def test_unassigned_doc_fails_registry(sample_config_path, sample_repo):
    (sample_repo / "ORPHAN.md").write_text("# Orphan\n", encoding="utf-8")
    text = sample_config_path.read_text(encoding="utf-8").replace(
        '- { match: "README.md", category: start }',
        '- { match: "README.md", category: start }\n  - { match: "ORPHAN-NOT.md", category: start }',
    )
    sample_config_path.write_text(text, encoding="utf-8")
    with pytest.raises(ConfigError, match="ORPHAN.md"):
        build_registry(load_config(sample_config_path))


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Hello World", "hello-world"),
        ("API & Tools (v2)", "api-tools-v2"),
        ("  spaced   out  ", "spaced-out"),
        ("___", "section"),
    ],
)
def test_slugify(text, expected):
    assert slugify(text) == expected
