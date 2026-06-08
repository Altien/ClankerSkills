"""Commenting core: CRUD, lifecycle, durability, orphans (issue 009)."""

import pytest
from fastapi.testclient import TestClient

import app as app_module
from engine.comments import CommentStore, mark_orphans


@pytest.fixture()
def store(tmp_path):
    return CommentStore(tmp_path / "atlas.db")


def test_create_and_get(store):
    comment = store.create(
        anchor_kind="doc-section",
        type="improve-doc",
        body="This section needs a worked example.",
        quote="the engine works",
        doc_id="README.md",
        heading="install",
    )
    loaded = store.get(comment.id)
    assert loaded.body == "This section needs a worked example."
    assert loaded.status == "open"
    assert loaded.anchor_label == "README.md § install"
    assert loaded.anchor_url == "/doc/README.md#install"


def test_validation(store):
    with pytest.raises(ValueError, match="anchor"):
        store.create(anchor_kind="bogus", type="idea", body="x")
    with pytest.raises(ValueError, match="type"):
        store.create(anchor_kind="doc", type="bogus", body="x")
    with pytest.raises(ValueError, match="empty"):
        store.create(anchor_kind="doc", type="idea", body="   ")


def test_lifecycle_transitions(store):
    comment = store.create(anchor_kind="doc", type="question", body="why?", doc_id="A.md")
    comment = store.set_status(comment.id, "in-progress")
    assert comment.status == "in-progress"
    comment = store.set_status(comment.id, "resolved", "answered in PR #7")
    assert comment.status == "resolved"
    assert comment.resolution_note == "answered in PR #7"
    with pytest.raises(ValueError):
        store.set_status(comment.id, "bogus")


def test_filters(store):
    store.create(anchor_kind="doc", type="idea", body="a", doc_id="A.md")
    store.create(anchor_kind="doc", type="question", body="b", doc_id="B.md")
    c3 = store.create(anchor_kind="doc", type="question", body="c", doc_id="B.md")
    store.set_status(c3.id, "resolved")

    assert len(store.list()) == 3
    assert len(store.list(type="question")) == 2
    assert len(store.list(doc_id="B.md", status="open")) == 1


def test_delete(store):
    comment = store.create(anchor_kind="doc", type="idea", body="bye", doc_id="A.md")
    assert store.delete(comment.id) is True
    assert store.get(comment.id) is None
    assert store.delete("nonexistent") is False


def test_counts_by_section(store):
    store.create(anchor_kind="doc-section", type="idea", body="a", doc_id="A.md", heading="x")
    store.create(anchor_kind="doc-section", type="idea", body="b", doc_id="A.md", heading="x")
    store.create(anchor_kind="doc", type="idea", body="c", doc_id="A.md")
    resolved = store.create(
        anchor_kind="doc-section", type="idea", body="d", doc_id="A.md", heading="y"
    )
    store.set_status(resolved.id, "resolved")

    counts = store.counts_by_section("A.md")
    assert counts == {"x": 2, "": 1}  # resolved comments don't count


# ── end-to-end ──


def test_comments_survive_reindex(sample_config_path):
    application = app_module.create_app(sample_config_path)
    client = TestClient(application)
    response = client.post(
        "/api/comments",
        data={
            "anchor_kind": "doc-section",
            "type": "improve-doc",
            "body": "Needs detail.",
            "doc_id": "README.md",
            "heading": "install",
            "quote": "",
        },
    )
    assert response.status_code == 200
    assert "Needs detail." in response.text

    client.post("/api/reindex")
    assert len(application.state.comments.list()) == 1  # survived


def test_thread_partial_and_composer(sample_config_path):
    client = TestClient(app_module.create_app(sample_config_path))
    response = client.get(
        "/partial/comments",
        params={
            "anchor_kind": "doc-section",
            "doc_id": "README.md",
            "heading": "install",
            "quote": "selected words",
        },
    )
    assert response.status_code == 200
    assert "comment-composer" in response.text
    assert "selected words" in response.text  # captured quote pre-filled


def test_feedback_page_filters_and_status_flow(sample_config_path):
    application = app_module.create_app(sample_config_path)
    client = TestClient(application)
    created = application.state.comments.create(
        anchor_kind="doc", type="question", body="What is this?", doc_id="README.md"
    )

    page = client.get("/feedback").text
    assert "What is this?" in page
    assert "1 open" in page

    row = client.post(
        f"/api/comments/{created.id}/status",
        data={"status": "resolved", "resolution_note": "explained"},
    ).text
    assert "resolved" in row and "explained" in row

    assert "What is this?" not in client.get("/feedback", params={"status": "open"}).text


def test_orphan_detection(sample_config_path):
    application = app_module.create_app(sample_config_path)
    store = application.state.comments
    ok = store.create(
        anchor_kind="doc-section", type="idea", body="fine", doc_id="README.md", heading="install"
    )
    gone_doc = store.create(anchor_kind="doc", type="idea", body="gone", doc_id="DELETED.md")
    gone_heading = store.create(
        anchor_kind="doc-section", type="idea", body="gone", doc_id="README.md", heading="vanished"
    )
    comments = mark_orphans(store.list(), application.state.registry)
    by_id = {c.id: c for c in comments}
    assert by_id[ok.id].orphaned is False
    assert by_id[gone_doc.id].orphaned is True
    assert by_id[gone_heading.id].orphaned is True

    page = TestClient(application).get("/feedback").text
    assert "orphaned" in page


def test_doc_view_carries_comment_machinery(sample_config_path):
    application = app_module.create_app(sample_config_path)
    application.state.comments.create(
        anchor_kind="doc-section", type="idea", body="x", doc_id="README.md", heading="install"
    )
    page = TestClient(application).get("/doc/README.md").text
    assert "comments.js" in page
    assert '"install": 1' in page or '"install":1' in page  # counts JSON embedded
    assert "doc-comment-btn" in page
