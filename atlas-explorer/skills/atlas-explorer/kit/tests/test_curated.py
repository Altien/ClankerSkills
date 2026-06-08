"""Curated layer plumbing: schema, coverage, rendering, FTS (issue 011)."""

import textwrap

import pytest
from fastapi.testclient import TestClient

import app as app_module
from engine.config import ConfigError, load_config
from engine.registry import build_registry


@pytest.fixture()
def curated_config(sample_config_path, tmp_path):
    curated = tmp_path / "curated"
    curated.mkdir()
    (curated / "atlas.yaml").write_text(
        textwrap.dedent(
            """\
            categories:
              start: "Where newcomers begin."
            docs:
              README.md:
                summary: "The front door: what the sample project is and why."
                read_when: "Read this first, before anything else."
            """
        ),
        encoding="utf-8",
    )
    sample_config_path.write_text(
        sample_config_path.read_text(encoding="utf-8") + f"curated_dir: {curated.as_posix()}\n",
        encoding="utf-8",
    )
    return sample_config_path


def test_curated_loaded_and_coverage_accounted(curated_config):
    registry = build_registry(load_config(curated_config))
    assert registry.curated.for_doc("README.md").summary.startswith("The front door")
    # docs/guide.md is full-depth but uncurated → needs curation
    assert registry.uncurated == ["docs/guide.md"]


def test_unknown_doc_in_curation_fails(curated_config, tmp_path):
    atlas_yaml = tmp_path / "curated" / "atlas.yaml"
    atlas_yaml.write_text(
        atlas_yaml.read_text(encoding="utf-8").replace("README.md:", "GHOST.md:"),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="GHOST.md"):
        build_registry(load_config(curated_config))


def test_unknown_category_overview_fails(curated_config, tmp_path):
    atlas_yaml = tmp_path / "curated" / "atlas.yaml"
    atlas_yaml.write_text(
        atlas_yaml.read_text(encoding="utf-8").replace("start:", "bogus-category:"),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="bogus-category"):
        build_registry(load_config(curated_config))


def test_empty_summary_fails(curated_config, tmp_path):
    atlas_yaml = tmp_path / "curated" / "atlas.yaml"
    atlas_yaml.write_text(
        "docs:\n  README.md:\n    summary: \"\"\n", encoding="utf-8"
    )
    with pytest.raises(ConfigError, match="summary"):
        build_registry(load_config(curated_config))


def test_home_and_doc_render_curation(curated_config):
    client = TestClient(app_module.create_app(curated_config))
    home = client.get("/").text
    assert "Where newcomers begin." in home
    assert "Read this first, before anything else." in home

    doc = client.get("/doc/README.md").text
    assert "The front door" in doc


def test_summary_searchable(curated_config):
    application = app_module.create_app(curated_config)
    hits = application.state.search.search("front door", scope="docs")
    assert any(h.kind == "summary" and h.url == "/doc/README.md" for h in hits)


def test_needs_curation_on_drift_page(curated_config):
    client = TestClient(app_module.create_app(curated_config))
    page = client.get("/drift").text
    assert "Needs curation" in page
    assert "docs/guide.md" in page


def test_no_curation_file_runs_fine(sample_config_path):
    registry = build_registry(load_config(sample_config_path))
    assert registry.curated.source_exists is False
    assert set(registry.uncurated) == {"README.md", "docs/guide.md"}
