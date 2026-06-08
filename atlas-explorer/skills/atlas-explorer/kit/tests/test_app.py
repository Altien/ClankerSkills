"""End-to-end app tests against the fixture repo, plus a real-config smoke test."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app as app_module

ATLAS_DIR = Path(__file__).resolve().parents[1]


@pytest.fixture()
def client(sample_config_path) -> TestClient:
    return TestClient(app_module.create_app(sample_config_path))


def test_home_lists_categories_and_docs(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Start Here" in response.text
    assert "Guides" in response.text
    assert "Sample Project" in response.text
    assert "User Guide" in response.text


def test_doc_view_renders_anchored_headings(client):
    response = client.get("/doc/README.md")
    assert response.status_code == 200
    assert 'id="install"' in response.text
    assert 'id="install-2"' in response.text  # slug dedupe matches the indexer
    # the fenced "# this is a comment" must not become a heading
    assert 'id="this-is-a-comment-not-a-heading"' not in response.text


def test_doc_links_rewritten_to_atlas_routes(client):
    response = client.get("/doc/README.md")
    assert 'href="/doc/docs/guide.md"' in response.text
    # unknown target and external links stay untouched
    assert 'href="docs/nope.md"' in response.text
    assert 'href="https://example.com/page.md"' in response.text


def test_backlinks_shown(client):
    response = client.get("/doc/docs/guide.md")
    assert "Linked from" in response.text
    assert "Sample Project" in response.text


def test_unknown_doc_404(client):
    response = client.get("/doc/docs/missing.md")
    assert response.status_code == 404
    assert "Document not found" in response.text


def test_healthz(client):
    payload = client.get("/healthz").json()
    assert payload["status"] == "ok"
    assert payload["docs"] == 2


def test_real_config_smoke():
    """The deployed atlas.config.yaml builds against the host repository.

    Skips in the bare kit (no config yet) so the engine regression suite passes
    standalone; activates once a target repo writes its atlas.config.yaml.
    ADAPT PER REPO: set MIN_DOCS to a floor for this repo's corpus so it can
    never silently shrink, and assert on a doc you know exists.
    """
    import pytest

    config_path = ATLAS_DIR / "atlas.config.yaml"
    if not config_path.is_file():
        pytest.skip("no deployed atlas.config.yaml — bare kit")

    MIN_DOCS = 1  # ADAPT: raise to this repo's expected corpus floor
    real = TestClient(app_module.create_app(config_path))
    assert real.get("/").status_code == 200
    health = real.get("/healthz").json()
    assert health["docs"] >= MIN_DOCS
