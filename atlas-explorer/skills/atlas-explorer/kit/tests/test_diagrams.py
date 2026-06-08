"""Diagrams: schema, SVG, node clicks, new comment anchors (issue 013)."""

import textwrap

import pytest
from fastapi.testclient import TestClient

import app as app_module
from engine.comments import mark_orphans
from engine.config import ConfigError, load_config
from engine.diagrams import load_diagrams, render_svg
from engine.export import brief_for
from engine.registry import build_registry


@pytest.fixture()
def diagram_config(sample_repo, sample_config_path, tmp_path):
    src = sample_repo / "src"
    src.mkdir()
    (src / "engine.ts").write_text(
        "export function ignite(): void {\n  return;\n}\n", encoding="utf-8"
    )
    curated = tmp_path / "curated"
    curated.mkdir()
    (curated / "diagrams.yaml").write_text(
        textwrap.dedent(
            """\
            - id: flow
              title: "The Flow"
              doc: README.md
              nodes:
                - id: go
                  type: start
                  label: "Start"
                  summary: "Where it begins."
                  doc: README.md
                  heading: install
                - id: work
                  type: step
                  label: "Work"
                  summary: "The code runs."
                  path: src/engine.ts
                  symbol: ignite
                - id: check
                  type: decision
                  label: "Check"
                  summary: "Quality gate."
                  doc: docs/guide.md
                  heading: getting-around
                  loop_to: work
                  when: "fail"
                - id: done
                  type: output
                  label: "Done"
                  summary: "Shipped."
                  doc: README.md
                  heading: install-2
            """
        ),
        encoding="utf-8",
    )
    (curated / "journeys.yaml").write_text(
        textwrap.dedent(
            """\
            - id: walk
              title: "Walk"
              intro: "Short."
              stops:
                - doc: README.md
                  narration: "Step one."
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


def test_schema_requires_summary_and_anchor(tmp_path):
    bad = tmp_path / "diagrams.yaml"
    bad.write_text(
        "- id: x\n  title: T\n  doc: a.md\n  nodes:\n"
        "    - { id: a, type: step, label: A, doc: a.md }\n"
        "    - { id: b, type: step, label: B, summary: s, doc: a.md }\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="summary"):
        load_diagrams(bad)

    bad.write_text(
        "- id: x\n  title: T\n  doc: a.md\n  nodes:\n"
        "    - { id: a, type: step, label: A, summary: s }\n"
        "    - { id: b, type: step, label: B, summary: s, doc: a.md }\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="exactly one"):
        load_diagrams(bad)

    bad.write_text(
        "- id: x\n  title: T\n  doc: a.md\n  nodes:\n"
        "    - { id: a, type: step, label: A, summary: s, doc: a.md, loop_to: ghost }\n"
        "    - { id: b, type: step, label: B, summary: s, doc: a.md }\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="ghost"):
        load_diagrams(bad)


def test_svg_geometry_sane(diagram_config):
    registry = build_registry(load_config(diagram_config))
    svg = render_svg(registry.diagrams[0])
    assert svg.count("<g class=") == 4          # one group per node
    assert 'class="d-loop"' in svg               # loop edge drawn
    assert "fail" in svg                          # when-label rendered
    assert "NaN" not in svg and "-1" not in svg.split("viewBox")[0]
    assert 'hx-get="/partial/diagram-node?diagram=flow&amp;node=work"' in svg


def test_dangling_node_detection(diagram_config, tmp_path):
    diagrams_yaml = tmp_path / "curated" / "diagrams.yaml"
    diagrams_yaml.write_text(
        diagrams_yaml.read_text(encoding="utf-8").replace(
            "heading: install-2", "heading: vanished-heading"
        ),
        encoding="utf-8",
    )
    registry = build_registry(load_config(diagram_config))
    assert len(registry.dangling_nodes) == 1
    assert registry.dangling_nodes[0].node_id == "done"

    client = TestClient(app_module.create_app(diagram_config))
    page = client.get("/drift").text
    assert "Dangling diagram nodes" in page


def test_doc_view_embeds_diagram(diagram_config):
    client = TestClient(app_module.create_app(diagram_config))
    page = client.get("/doc/README.md").text
    assert "The Flow" in page
    assert "flow-diagram" in page
    assert 'id="diagram-panel-flow"' in page


def test_node_click_partial(diagram_config):
    client = TestClient(app_module.create_app(diagram_config))
    # code-anchored node renders the symbol slice
    code_node = client.get("/partial/diagram-node", params={"diagram": "flow", "node": "work"})
    assert code_node.status_code == 200
    assert "The code runs." in code_node.text
    assert "hl-target" in code_node.text
    # doc-anchored node renders the sliced section
    doc_node = client.get("/partial/diagram-node", params={"diagram": "flow", "node": "go"})
    assert "Where it begins." in doc_node.text
    assert client.get(
        "/partial/diagram-node", params={"diagram": "flow", "node": "zzz"}
    ).status_code == 404


def test_diagram_node_and_journey_stop_comments(diagram_config):
    application = app_module.create_app(diagram_config)
    client = TestClient(application)
    store = application.state.comments

    ok_node = store.create(
        anchor_kind="diagram-node", type="idea", body="n", diagram_id="flow", node_id="work"
    )
    bad_node = store.create(
        anchor_kind="diagram-node", type="idea", body="n", diagram_id="flow", node_id="ghost"
    )
    ok_stop = store.create(
        anchor_kind="journey-stop", type="idea", body="s", journey_id="walk", stop_id="1"
    )
    bad_stop = store.create(
        anchor_kind="journey-stop", type="idea", body="s", journey_id="walk", stop_id="9"
    )
    by_id = {c.id: c for c in mark_orphans(store.list(), application.state.registry)}
    assert by_id[ok_node.id].orphaned is False
    assert by_id[bad_node.id].orphaned is True
    assert by_id[ok_stop.id].orphaned is False
    assert by_id[bad_stop.id].orphaned is True

    # node panel and journey view carry comment affordances
    panel = client.get("/partial/diagram-node", params={"diagram": "flow", "node": "work"}).text
    assert "anchor_kind=diagram-node" in panel
    journey_page = client.get("/journey/walk/1").text
    assert "anchor_kind=journey-stop" in journey_page


def test_export_briefs_for_new_anchors(diagram_config):
    application = app_module.create_app(diagram_config)
    registry = application.state.registry
    store = application.state.comments

    node_comment = store.create(
        anchor_kind="diagram-node",
        type="improve-doc",
        body="Clarify this node.",
        diagram_id="flow",
        node_id="work",
    )
    brief = brief_for(node_comment, registry)
    assert "Node summary: The code runs." in brief
    assert "export function ignite" in brief  # anchored code slice included

    stop_comment = store.create(
        anchor_kind="journey-stop",
        type="question",
        body="Why first?",
        journey_id="walk",
        stop_id="1",
    )
    brief = brief_for(stop_comment, registry)
    assert "Stop narration: Step one." in brief
    assert "Sample Project" in brief  # anchored doc text included
