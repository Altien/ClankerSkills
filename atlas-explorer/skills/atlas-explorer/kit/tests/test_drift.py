"""Drift detection: broken paths/symbols, inline styling, dashboard (issue 006)."""

import textwrap

import pytest
from fastapi.testclient import TestClient

import app as app_module
from engine.config import load_config
from engine.drift import build_drift
from engine.registry import build_registry


@pytest.fixture()
def drift_config(sample_repo, sample_config_path):
    src = sample_repo / "src"
    src.mkdir()
    (src / "engine.ts").write_text(
        "export function realThing(): void {\n  return;\n}\n", encoding="utf-8"
    )
    (sample_repo / "README.md").write_text(
        textwrap.dedent(
            """\
            # Sample Project

            ## Working Parts

            Real: `src/engine.ts` with `realThing()` in `src/engine.ts`.

            ## Aspirations

            Gone: `src/legacy.ts` and the removed `vanished()` from `src/engine.ts`.
            """
        ),
        encoding="utf-8",
    )
    sample_config_path.write_text(
        sample_config_path.read_text(encoding="utf-8")
        + textwrap.dedent(
            """\
            code_references:
              roots: ["src"]
            languages:
              - { extensions: [".ts"], grammar: "tree_sitter_typescript:language_typescript" }
            """
        ),
        encoding="utf-8",
    )
    return sample_config_path


def test_drift_report_contents(drift_config):
    registry = build_registry(load_config(drift_config))
    report = build_drift(registry)
    assert report.count == 2
    kinds = {(item.kind, item.raw) for item in report.items}
    assert ("path", "src/legacy.ts") in kinds
    assert ("symbol", "vanished()") in kinds
    # intact references must not be flagged
    assert all(item.raw not in ("src/engine.ts", "realThing()") for item in report.items)


def test_drift_items_deep_link_to_section(drift_config):
    registry = build_registry(load_config(drift_config))
    report = build_drift(registry)
    by_raw = {item.raw: item for item in report.items}
    assert by_raw["src/legacy.ts"].doc_url == "/doc/README.md#aspirations"
    assert by_raw["vanished()"].doc_url == "/doc/README.md#aspirations"


def test_inline_broken_styling(drift_config):
    client = TestClient(app_module.create_app(drift_config))
    page = client.get("/doc/README.md").text
    assert page.count('class="ref-broken"') == 2
    assert "not found at index time" in page
    assert "No symbol vanished" in page
    # intact refs render as chips, not broken
    assert 'hx-get="/partial/code?path=src/engine.ts"' in page


def test_drift_dashboard(drift_config):
    client = TestClient(app_module.create_app(drift_config))
    page = client.get("/drift").text
    assert "2 broken references" in page
    assert "src/legacy.ts" in page
    assert "vanished()" in page
    assert 'href="/doc/README.md#aspirations"' in page


def test_drift_clean_state(sample_config_path):
    client = TestClient(app_module.create_app(sample_config_path))
    page = client.get("/drift").text
    assert "No drift detected" in page


def test_drift_exempt_docs_skipped(drift_config, sample_repo):
    (sample_repo / "HISTORY.md").write_text(
        "# History\n\nRemoved `src/old-thing.ts` long ago.\n", encoding="utf-8"
    )
    config_path = drift_config
    text = config_path.read_text(encoding="utf-8")
    text = text.replace(
        'category_rules:', 'drift_exempt:\n  - "HISTORY.md"\ncategory_rules:\n  - { match: "HISTORY.md", category: start }'
    )
    config_path.write_text(text, encoding="utf-8")

    registry = build_registry(load_config(config_path))
    report = build_drift(registry)
    assert all(item.doc_id != "HISTORY.md" for item in report.items)
    assert report.exempted == 1


def test_drift_refreshes_on_reindex(drift_config, sample_repo):
    application = app_module.create_app(drift_config)
    client = TestClient(application)
    assert "2 broken references" in client.get("/drift").text

    (sample_repo / "src" / "legacy.ts").write_text("export const back = 1;\n", encoding="utf-8")
    client.post("/api/reindex")
    page = client.get("/drift").text
    assert "src/legacy.ts" not in page
    assert "1 broken reference" in page  # only the symbol remains
