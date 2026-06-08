"""Reindex endpoint + atomic registry swap (issue 005)."""

import threading

from fastapi.testclient import TestClient

import app as app_module


def test_reindex_returns_counts(sample_config_path):
    client = TestClient(app_module.create_app(sample_config_path))
    payload = client.post("/api/reindex").json()
    assert payload["status"] == "ok"
    assert payload["docs"] == 2
    assert payload["build_seconds"] >= 0


def test_disk_edit_indexed_after_reindex(sample_config_path, sample_repo):
    """Doc bodies render live from disk; reindex refreshes the *index* —
    headings registry, FTS rows, link graph — via an atomic swap."""
    application = app_module.create_app(sample_config_path)
    client = TestClient(application)

    guide = sample_repo / "docs" / "guide.md"
    guide.write_text(
        guide.read_text(encoding="utf-8") + "\n## Brand New Section\n\nZephyr quokka.\n",
        encoding="utf-8",
    )
    # indexed surfaces are stale until reindex
    assert application.state.search.search("zephyr quokka") == []
    headings = [h.text for h in application.state.registry.docs["docs/guide.md"].headings]
    assert "Brand New Section" not in headings

    old_registry = application.state.registry
    client.post("/api/reindex")
    assert application.state.registry is not old_registry  # swapped, not mutated

    hits = application.state.search.search("zephyr quokka")
    assert hits and hits[0].url == "/doc/docs/guide.md#brand-new-section"
    headings = [h.text for h in application.state.registry.docs["docs/guide.md"].headings]
    assert "Brand New Section" in headings


def test_concurrent_reindexes_serialize(sample_config_path):
    application = app_module.create_app(sample_config_path)
    client = TestClient(application)
    results = []

    def trigger():
        results.append(client.post("/api/reindex").status_code)

    threads = [threading.Thread(target=trigger) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert results == [200, 200, 200, 200]
    assert application.state.registry.doc_count == 2  # consistent end state


def test_htmx_request_gets_html(sample_config_path):
    client = TestClient(app_module.create_app(sample_config_path))
    response = client.post("/api/reindex", headers={"HX-Request": "true"})
    assert "reindex-done" in response.text
