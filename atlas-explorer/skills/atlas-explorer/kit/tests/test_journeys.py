"""Journeys: schema, stop resolution, navigation, dangling handling (issue 012)."""

import textwrap

import pytest
from fastapi.testclient import TestClient

import app as app_module
from engine.config import ConfigError, load_config
from engine.journeys import load_journeys
from engine.registry import build_registry


@pytest.fixture()
def journey_config(sample_repo, sample_config_path, tmp_path):
    src = sample_repo / "src"
    src.mkdir()
    (src / "engine.ts").write_text(
        "export function ignite(): void {\n  return;\n}\n", encoding="utf-8"
    )
    curated = tmp_path / "curated"
    curated.mkdir()
    (curated / "journeys.yaml").write_text(
        textwrap.dedent(
            """\
            - id: tour
              title: "The Tour"
              intro: "A short walk."
              stops:
                - doc: README.md
                  title: "Start"
                  narration: "Read the front door."
                - doc: docs/guide.md
                  heading: getting-around
                  narration: "The guide's key section."
                - path: src/engine.ts
                  symbol: ignite
                  narration: "Where it starts."
                - doc: docs/guide.md
                  heading: no-such-heading
                  narration: "This one dangles."
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


def test_schema_validation(tmp_path):
    bad = tmp_path / "journeys.yaml"
    bad.write_text("- id: x\n  title: T\n  intro: I\n  stops: []\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="no stops"):
        load_journeys(bad)

    bad.write_text(
        "- id: x\n  title: T\n  intro: I\n  stops:\n"
        "    - doc: a.md\n      path: b.ts\n      narration: both\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="exactly one"):
        load_journeys(bad)

    bad.write_text(
        "- id: x\n  title: T\n  intro: I\n  stops:\n    - doc: a.md\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="narration"):
        load_journeys(bad)


def test_dangling_detection(journey_config):
    registry = build_registry(load_config(journey_config))
    assert len(registry.journeys) == 1
    assert len(registry.dangling_stops) == 1
    dangling = registry.dangling_stops[0]
    assert dangling.stop_index == 3
    assert "no-such-heading" in dangling.reason


def test_journey_navigation_and_content(journey_config):
    client = TestClient(app_module.create_app(journey_config))

    stop1 = client.get("/journey/tour/1").text
    assert "stop 1 of 4" in stop1
    assert "Read the front door." in stop1
    assert "Sample Project" in stop1  # live doc content rendered

    stop2 = client.get("/journey/tour/2").text
    assert "Getting Around" in stop2          # sliced section, live
    assert "Back to the" not in stop2          # preamble not included

    stop3 = client.get("/journey/tour/3").text
    assert "hl-target" in stop3                # code stop renders the symbol slice
    assert "ignite" in stop3


def test_dangling_stop_renders_notice_not_500(journey_config):
    client = TestClient(app_module.create_app(journey_config))
    response = client.get("/journey/tour/4")
    assert response.status_code == 200
    assert "no longer resolves" in response.text


def test_stop_number_clamped(journey_config):
    client = TestClient(app_module.create_app(journey_config))
    assert "stop 4 of 4" in client.get("/journey/tour/99").text
    assert "stop 1 of 4" in client.get("/journey/tour/0").text


def test_unknown_journey_404(journey_config):
    client = TestClient(app_module.create_app(journey_config))
    assert client.get("/journey/nope").status_code == 404


def test_home_lists_journeys(journey_config):
    client = TestClient(app_module.create_app(journey_config))
    home = client.get("/").text
    assert "The Tour" in home
    assert "4 stops" in home


def test_dangling_on_drift_page(journey_config):
    client = TestClient(app_module.create_app(journey_config))
    page = client.get("/drift").text
    assert "Dangling journey stops" in page
    assert "no-such-heading" in page
