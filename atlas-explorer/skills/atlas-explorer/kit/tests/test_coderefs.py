"""Code reference detection + the htmx code panel (issue 002)."""

import textwrap

import pytest
from fastapi.testclient import TestClient

import app as app_module
from engine.config import load_config
from engine.indexer import find_code_ref_tokens, scan_corpus


@pytest.fixture()
def code_repo(sample_repo, sample_config_path):
    """Extend the fixture repo with code + code_references config."""
    src = sample_repo / "src"
    src.mkdir()
    (src / "main.ts").write_text(
        'export function main(): void {\n  console.log("hi");\n}\n', encoding="utf-8"
    )
    (src / "util").mkdir()
    (src / "util" / "helpers.ts").write_text("export const X = 1;\n", encoding="utf-8")

    (sample_repo / "README.md").write_text(
        textwrap.dedent(
            """\
            # Sample Project

            Entry point is `src/main.ts` (see `src/main.ts:12` too) and the
            helpers live in `src/util/`. The ghost module `src/missing.ts`
            was removed. Prose like and/or must not match. The REST route
            `src/v1/users` is an endpoint, not a file. See also the
            [guide](docs/guide.md) and the doc `docs/guide.md`.
            """
        ),
        encoding="utf-8",
    )

    config_text = sample_config_path.read_text(encoding="utf-8") + textwrap.dedent(
        """\
        code_references:
          roots: ["src"]
        """
    )
    sample_config_path.write_text(config_text, encoding="utf-8")
    return sample_config_path


def _tokens(line, roots):
    return [token for token, _ in find_code_ref_tokens(line, roots)]


def test_token_detection_rules():
    roots = ("src",)
    assert _tokens("see `src/main.ts` here", roots) == ["src/main.ts"]
    assert _tokens("at src/main.ts:12 line ref", roots) == ["src/main.ts"]
    assert _tokens("dirs like src/util/ too", roots) == ["src/util/"]
    assert _tokens("and/or is prose", roots) == []
    assert _tokens("https://example.com/src/x.ts", roots) == []
    assert _tokens("globs src/**/*.ts are skipped", roots) == []


def test_scan_records_refs_resolution(code_repo):
    docs = scan_corpus(load_config(code_repo))
    readme = docs["README.md"]
    by_raw = {r.raw: r for r in readme.code_refs}
    assert by_raw["src/main.ts"].resolved is True
    assert by_raw["src/util/"].resolved is True and by_raw["src/util/"].is_dir is True
    assert by_raw["src/missing.ts"].resolved is False
    assert "and/or" not in by_raw
    # An unresolved, extensionless token under a code root is a route/namespace,
    # not a file claim — it must not be recorded as a (drifting) code reference.
    assert "src/v1/users" not in by_raw


def test_doc_view_renders_chips(code_repo):
    client = TestClient(app_module.create_app(code_repo))
    page = client.get("/doc/README.md").text
    assert 'hx-get="/partial/code?path=src/main.ts"' in page
    assert 'hx-get="/partial/code?path=src/util"' in page
    # corpus doc mentioned in backticks chips to its Atlas page, not the code panel
    assert '<a class="code-chip doc-chip" href="/doc/docs/guide.md">docs/guide.md</a>' in page
    # unresolved ref renders with broken-reference styling (006)
    assert '<code class="ref-broken" title="src/missing.ts not found at index time">' in page


def test_code_partial_highlights_file(code_repo):
    client = TestClient(app_module.create_app(code_repo))
    response = client.get("/partial/code", params={"path": "src/main.ts"})
    assert response.status_code == 200
    assert 'class="highlight"' in response.text
    assert "panel-header" in response.text
    assert "2 lines" not in response.text  # 3-line file: header shows real count


def test_code_partial_directory_listing(code_repo):
    client = TestClient(app_module.create_app(code_repo))
    response = client.get("/partial/code", params={"path": "src"})
    assert response.status_code == 200
    assert "main.ts" in response.text
    assert "util/" in response.text


def test_code_partial_rejects_traversal(code_repo):
    client = TestClient(app_module.create_app(code_repo))
    response = client.get("/partial/code", params={"path": "../outside.txt"})
    assert response.status_code == 400
    assert "escapes" in response.text


def test_code_partial_missing_file_404(code_repo):
    client = TestClient(app_module.create_app(code_repo))
    response = client.get("/partial/code", params={"path": "src/nope.ts"})
    assert response.status_code == 404


def test_pygments_css_served(code_repo):
    client = TestClient(app_module.create_app(code_repo))
    response = client.get("/pygments.css")
    assert response.status_code == 200
    assert ".highlight" in response.text
    assert 'html[data-theme="dark"] .highlight' in response.text
