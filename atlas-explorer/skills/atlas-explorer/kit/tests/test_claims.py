"""Curated claims engine: counters, trichotomy, inline marking (issue 007)."""

import textwrap

import pytest
from fastapi.testclient import TestClient

import app as app_module
from engine.claims import Claim, load_claims, run_claims
from engine.config import ConfigError, load_config
from engine.registry import build_registry
from engine.symbols import SymbolIndexer


@pytest.fixture()
def claims_config(sample_repo, sample_config_path, tmp_path):
    src = sample_repo / "src"
    src.mkdir()
    (src / "a.ts").write_text("export const A = 1;\n", encoding="utf-8")
    (src / "b.ts").write_text("export const B = 2;\nexport const C = 3;\n", encoding="utf-8")

    (sample_repo / "README.md").write_text(
        textwrap.dedent(
            """\
            # Sample Project

            There are exactly 3 source modules in this project.
            The helpers file holds 2 exported symbols.
            """
        ),
        encoding="utf-8",
    )

    curated = tmp_path / "curated"
    curated.mkdir()
    (curated / "claims.yaml").write_text(
        textwrap.dedent(
            """\
            - id: module-count
              doc: README.md
              quote: "exactly 3 source modules"
              counter: { type: file_count, glob: "src/*.ts" }
              expected: 3

            - id: helper-symbols
              doc: README.md
              quote: "holds 2 exported symbols"
              counter: { type: symbol_count, path: "src/b.ts" }
              expected: 2

            - id: broken-counter
              doc: README.md
              quote: "ghost claim"
              counter: { type: line_count, path: "src/missing.ts" }
              expected: 1
            """
        ),
        encoding="utf-8",
    )

    sample_config_path.write_text(
        sample_config_path.read_text(encoding="utf-8")
        + textwrap.dedent(
            f"""\
            curated_dir: {curated.as_posix()}
            languages:
              - {{ extensions: [".ts"], grammar: "tree_sitter_typescript:language_typescript" }}
            """
        ),
        encoding="utf-8",
    )
    return sample_config_path


def test_claim_trichotomy(claims_config):
    registry = build_registry(load_config(claims_config))
    by_id = {r.claim.id: r for r in registry.claims}
    assert by_id["helper-symbols"].status == "pass" and by_id["helper-symbols"].actual == 2
    assert by_id["module-count"].status == "fail"  # claims 3, tree has 2
    assert "doc claims 3, tree has 2" in by_id["module-count"].message
    assert by_id["broken-counter"].status == "error"
    assert "counter failed" in by_id["broken-counter"].message


def test_unknown_counter_type_rejected(tmp_path):
    bad = tmp_path / "claims.yaml"
    bad.write_text(
        "- id: x\n  doc: README.md\n  quote: q\n  counter: {type: magic}\n  expected: 1\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="magic"):
        load_claims(bad)


def test_duplicate_claim_id_rejected(tmp_path):
    bad = tmp_path / "claims.yaml"
    bad.write_text(
        textwrap.dedent(
            """\
            - { id: x, doc: a.md, quote: q, counter: {type: file_count, glob: "*"}, expected: 1 }
            - { id: x, doc: a.md, quote: q, counter: {type: file_count, glob: "*"}, expected: 1 }
            """
        ),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="duplicate"):
        load_claims(bad)


def test_missing_claims_file_is_fine(tmp_path):
    assert load_claims(tmp_path / "nope.yaml") == []


def test_inline_marking_and_banner(claims_config):
    client = TestClient(app_module.create_app(claims_config))
    page = client.get("/doc/README.md").text
    # failing claim quote wrapped in a mark at the quoted sentence
    assert '<mark class="claim-drift"' in page
    assert "exactly 3 source modules</mark>" in page
    # banner lists all failing claims, including the error one whose quote isn't in the doc
    assert "claim-banner" in page
    assert "ghost claim" in page
    # passing claim is NOT marked
    assert "holds 2 exported symbols</mark>" not in page


def test_drift_page_shows_claims(claims_config):
    client = TestClient(app_module.create_app(claims_config))
    page = client.get("/drift").text
    assert "Quantitative claims" in page
    assert "module-count" not in page  # ids are internal; quotes are shown
    assert "exactly 3 source modules" in page
    assert "claimed 3 · actual 2" in page


def test_claims_searchable(claims_config):
    application = app_module.create_app(claims_config)
    hits = application.state.search.search("ghost", scope="claims")
    assert hits and hits[0].kind == "claim" and hits[0].url == "/drift"
