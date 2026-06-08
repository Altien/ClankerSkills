"""Agent briefs + code anchors: export content, bundles, orphans (issue 010)."""

import textwrap

import pytest
from fastapi.testclient import TestClient

import app as app_module
from engine.comments import mark_orphans
from engine.export import brief_for, bundle_for


@pytest.fixture()
def export_app(sample_repo, sample_config_path):
    src = sample_repo / "src"
    src.mkdir()
    (src / "engine.ts").write_text(
        "export function widget(): void {\n  // gadget\n  return;\n}\n"
        "export const OTHER = 1;\n",
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
    return app_module.create_app(sample_config_path)


def test_doc_section_brief_slices_section(export_app):
    store = export_app.state.comments
    comment = store.create(
        anchor_kind="doc-section",
        type="improve-doc",
        body="Add an example.",
        quote="Some prose.",
        doc_id="docs/guide.md",
        heading="getting-around",
    )
    brief = brief_for(comment, export_app.state.registry)
    assert "# Atlas feedback brief" in brief
    assert "doc-section — `docs/guide.md § getting-around`" in brief
    assert "> Some prose." in brief
    assert "## Getting Around" in brief  # sliced section, not the whole doc
    assert "Back to the" not in brief    # preamble content excluded


def test_code_symbol_brief_slices_symbol(export_app):
    store = export_app.state.comments
    comment = store.create(
        anchor_kind="code-symbol",
        type="question",
        body="Why is this void?",
        path="src/engine.ts",
        symbol="widget",
    )
    brief = brief_for(comment, export_app.state.registry)
    assert "code-symbol — `src/engine.ts::widget`" in brief
    assert "export function widget" in brief
    assert "L1–4" in brief
    assert "OTHER" not in brief  # only the target symbol's span


def test_truncation(export_app):
    store = export_app.state.comments
    comment = store.create(
        anchor_kind="doc", type="idea", body="trim me", doc_id="README.md"
    )
    brief = brief_for(comment, export_app.state.registry, max_lines=3)
    assert "context truncated to 3 lines" in brief


def test_orphan_brief_omits_stale_context(export_app):
    store = export_app.state.comments
    comment = store.create(
        anchor_kind="doc-section",
        type="fix-drift",
        body="gone",
        doc_id="README.md",
        heading="no-such-heading",
    )
    mark_orphans([comment], export_app.state.registry)
    brief = brief_for(comment, export_app.state.registry)
    assert "Anchor no longer resolves" in brief
    assert "## Anchored context" not in brief


def test_bundle_summarizes_and_joins(export_app):
    store = export_app.state.comments
    store.create(anchor_kind="doc", type="idea", body="one", doc_id="README.md")
    store.create(anchor_kind="doc", type="question", body="two", doc_id="README.md")
    comments = mark_orphans(store.list(), export_app.state.registry)
    bundle = bundle_for(comments, export_app.state.registry)
    assert "2 comment(s): 1 idea · 1 question" in bundle
    assert bundle.count("# Atlas feedback brief") == 2
    assert "---" in bundle


def test_brief_and_bundle_routes(export_app):
    client = TestClient(export_app)
    created = export_app.state.comments.create(
        anchor_kind="code-file", type="idea", body="rename it", path="src/engine.ts"
    )
    brief = client.get(f"/api/comments/{created.id}/brief")
    assert brief.status_code == 200
    assert "text/markdown" in brief.headers["content-type"]
    assert "rename it" in brief.text

    resolved = export_app.state.comments.create(
        anchor_kind="doc", type="idea", body="done already", doc_id="README.md"
    )
    export_app.state.comments.set_status(resolved.id, "resolved")

    bundle = client.get("/api/comments/bundle")  # defaults to open only
    assert "rename it" in bundle.text
    assert "done already" not in bundle.text

    assert client.get("/api/comments/zzz/brief").status_code == 404


def test_code_panel_carries_comment_affordances(export_app):
    client = TestClient(export_app)
    panel = client.get("/partial/code", params={"path": "src/engine.ts"}).text
    assert "panel-thread" in panel
    assert "anchor_kind=code-file&path=src/engine.ts" in panel
    assert "anchor_kind=code-symbol&path=src/engine.ts&symbol=widget" in panel


def test_code_symbol_anchor_orphan_detection(export_app):
    store = export_app.state.comments
    ok = store.create(
        anchor_kind="code-symbol", type="idea", body="x", path="src/engine.ts", symbol="widget"
    )
    gone = store.create(
        anchor_kind="code-symbol", type="idea", body="y", path="src/engine.ts", symbol="ghost"
    )
    comments = mark_orphans(store.list(), export_app.state.registry)
    by_id = {c.id: c for c in comments}
    assert by_id[ok.id].orphaned is False
    assert by_id[gone.id].orphaned is True
