"""Corpus completion: prompts, HTML extraction, artifact links, raw serving (issue 008)."""

import json
import textwrap

import pytest
from fastapi.testclient import TestClient

import app as app_module
from engine.config import load_config
from engine.drift import build_drift
from engine.registry import build_registry


@pytest.fixture()
def extras_config(sample_repo, sample_config_path):
    # an "agent prompt" TS file containing markdown-ish prompt text
    prompts = sample_repo / "src" / "agents" / "prompts"
    prompts.mkdir(parents=True)
    (prompts / "negotiator.ts").write_text(
        textwrap.dedent(
            """\
            export const negotiatorPrompt = `
            # Negotiator

            ## Quibble Phase

            Always quibble about the kumquat clause. See src/ghost.ts for history.
            `;
            """
        ),
        encoding="utf-8",
    )

    # a marketing-style HTML page
    site = sample_repo / "site"
    site.mkdir()
    (site / "index.html").write_text(
        textwrap.dedent(
            """\
            <html><head><title>Shiny Product</title>
            <script>var hidden = "do-not-index-zzz";</script></head>
            <body><h1>Shiny Product</h1>
            <p>Excellence in marsupial logistics.</p></body></html>
            """
        ),
        encoding="utf-8",
    )

    # a sibling-tool manifest mapping the prompt file to an artifact id
    (sample_repo / "manifest.json").write_text(
        json.dumps(
            {"artifacts": [{"id": "negotiator", "source_path": "src/agents/prompts/negotiator.ts"}]}
        ),
        encoding="utf-8",
    )

    sample_config_path.write_text(
        sample_config_path.read_text(encoding="utf-8").replace(
            "corpus:",
            textwrap.dedent(
                """\
                artifact_links:
                  - match: "src/agents/prompts/*"
                    title: "Open in Explorer"
                    url_template: "http://localhost:9999/#/a/{id}"
                    manifest: "manifest.json"
                corpus:
                  - include: ["src/agents/prompts/*.ts"]
                    depth: search-only
                    render: internal
                  - include: ["site/index.html"]
                    depth: search-only
                    render: external
                """
            ),
        ).replace(
            "category_rules:",
            'category_rules:\n  - { match: "src/agents/prompts/*", category: guides }\n'
            '  - { match: "site/*", category: guides }',
        )
        + 'code_references:\n  roots: ["src"]\n',
        encoding="utf-8",
    )
    return sample_config_path


def test_prompt_searchable_with_section_anchor(extras_config):
    application = app_module.create_app(extras_config)
    hits = application.state.search.search("kumquat")
    assert hits
    assert hits[0].ref.startswith("src/agents/prompts/negotiator.ts")


def test_prompt_doc_view_renders_code_with_artifact_link(extras_config):
    client = TestClient(app_module.create_app(extras_config))
    page = client.get("/doc/src/agents/prompts/negotiator.ts").text
    assert "artifact-banner" in page
    assert "http://localhost:9999/#/a/negotiator" in page
    assert 'class="highlight"' in page or "panel-code" in page  # rendered as code


def test_html_page_text_extracted_scripts_skipped(extras_config):
    application = app_module.create_app(extras_config)
    assert application.state.search.search("marsupial logistics")
    assert application.state.search.search("do-not-index-zzz") == []
    doc = application.state.registry.docs["site/index.html"]
    assert doc.title == "Shiny Product"


def test_external_doc_links_out(extras_config):
    client = TestClient(app_module.create_app(extras_config))
    page = client.get("/doc/site/index.html").text
    assert 'href="/raw/site/index.html"' in page
    raw = client.get("/raw/site/index.html")
    assert raw.status_code == 200
    assert "marsupial" in raw.text
    assert raw.headers["content-type"].startswith("text/html")


def test_raw_rejects_escape(extras_config):
    client = TestClient(app_module.create_app(extras_config))
    assert client.get("/raw/../secrets.txt").status_code in (400, 404)


def test_search_only_docs_excluded_from_drift(extras_config):
    registry = build_registry(load_config(extras_config))
    report = build_drift(registry)
    # the prompt mentions src/ghost.ts which doesn't exist — but search-only
    # docs make no claims, so it must NOT appear as drift
    assert all("ghost" not in item.raw for item in report.items)


def test_changelog_style_version_sections(sample_repo, sample_config_path):
    (sample_repo / "CHANGES.md").write_text(
        textwrap.dedent(
            """\
            # Changelog

            ## v2.0.0

            Added the wombat reactor.

            ## v1.0.0

            Initial xylophone support.
            """
        ),
        encoding="utf-8",
    )
    text = sample_config_path.read_text(encoding="utf-8").replace(
        'category_rules:', 'category_rules:\n  - { match: "CHANGES.md", category: start }'
    )
    sample_config_path.write_text(text, encoding="utf-8")
    application = app_module.create_app(sample_config_path)
    hits = application.state.search.search("wombat reactor")
    assert hits and hits[0].url == "/doc/CHANGES.md#v200"