"""FTS5 search: indexing, scoping, snippets, durability (issue 004)."""

import sqlite3
import textwrap

import pytest
from fastapi.testclient import TestClient

import app as app_module
from engine.config import load_config
from engine.fts import SearchIndex
from engine.registry import build_registry


@pytest.fixture()
def fts_config(sample_repo, sample_config_path, tmp_path):
    src = sample_repo / "src"
    src.mkdir()
    (src / "engine.ts").write_text(
        "export function dispatchWork(): void {\n  // zanzibar\n  return;\n}\n",
        encoding="utf-8",
    )
    (sample_repo / "README.md").write_text(
        textwrap.dedent(
            """\
            # Sample Project

            The flux capacitor is configured in `src/engine.ts`.

            ## Calibration

            Calibrate the flux capacitor before each run.
            """
        ),
        encoding="utf-8",
    )
    sample_config_path.write_text(
        sample_config_path.read_text(encoding="utf-8")
        + textwrap.dedent(
            f"""\
            code_references:
              roots: ["src"]
            languages:
              - {{ extensions: [".ts"], grammar: "tree_sitter_typescript:language_typescript" }}
            db_path: {(tmp_path / 'atlas-test.db').as_posix()}
            """
        ),
        encoding="utf-8",
    )
    return sample_config_path


@pytest.fixture()
def search_index(fts_config):
    config = load_config(fts_config)
    registry = build_registry(config)
    index = SearchIndex(config.db_path)
    index.rebuild(registry)
    return index


def test_section_hit_lands_on_anchor(search_index):
    hits = search_index.search("calibrate")
    assert hits, "expected a hit for body text"
    hit = hits[0]
    assert hit.kind == "section"
    assert hit.url == "/doc/README.md#calibration"
    assert "<mark>" in hit.snippet.lower()


def test_doc_preamble_hit(search_index):
    hits = search_index.search("flux capacitor")
    assert any(h.kind in ("doc", "section") for h in hits)


def test_symbol_indexed_and_scoped(search_index):
    hits = search_index.search("dispatchWork", scope="code")
    assert len(hits) == 1
    assert hits[0].kind == "symbol"
    assert hits[0].url == "/code/src/engine.ts?symbol=dispatchWork"
    # docs scope must exclude it (the only dispatchWork mention is the symbol row
    # plus the README body, which says "engine.ts" not "dispatchWork")
    assert all(h.kind != "symbol" for h in search_index.search("dispatchWork", scope="docs"))


def test_rebuild_idempotent(fts_config):
    config = load_config(fts_config)
    registry = build_registry(config)
    index = SearchIndex(config.db_path)
    first = index.rebuild(registry)
    second = index.rebuild(registry)
    assert first == second > 0


def test_rebuild_preserves_durable_tables(fts_config):
    config = load_config(fts_config)
    registry = build_registry(config)
    index = SearchIndex(config.db_path)
    index.rebuild(registry)

    conn = sqlite3.connect(config.db_path)
    with conn:
        conn.execute("CREATE TABLE IF NOT EXISTS comments (id TEXT PRIMARY KEY, body TEXT)")
        conn.execute("INSERT INTO comments VALUES ('c1', 'keep me')")
    conn.close()

    index.rebuild(registry)

    conn = sqlite3.connect(config.db_path)
    rows = conn.execute("SELECT body FROM comments").fetchall()
    conn.close()
    assert rows == [("keep me",)]


def test_bad_fts_syntax_falls_back_to_phrase(search_index):
    # unbalanced quote would raise an FTS5 syntax error without the fallback
    assert search_index.search('"flux AND (') == []


def test_empty_query_returns_nothing(search_index):
    assert search_index.search("   ") == []


# ── routes ──


def test_search_page(fts_config):
    client = TestClient(app_module.create_app(fts_config))
    response = client.get("/search", params={"q": "calibrate"})
    assert response.status_code == 200
    assert "result" in response.text
    assert 'href="/doc/README.md#calibration"' in response.text


def test_search_dropdown_partial(fts_config):
    client = TestClient(app_module.create_app(fts_config))
    response = client.get("/partial/search", params={"q": "calibrate"})
    assert response.status_code == 200
    assert "search-dropdown" in response.text
    assert client.get("/partial/search", params={"q": ""}).text == ""


def test_code_page_full_view(fts_config):
    client = TestClient(app_module.create_app(fts_config))
    response = client.get("/code/src/engine.ts", params={"symbol": "dispatchWork"})
    assert response.status_code == 200
    assert "hl-target" in response.text
