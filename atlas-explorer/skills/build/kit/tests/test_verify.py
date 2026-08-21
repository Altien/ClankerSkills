"""verify.py: each curation error class fails; drift alone passes (issue 014)."""

import textwrap

import pytest

from verify import verify


@pytest.fixture()
def verified_config(sample_repo, sample_config_path, tmp_path):
    """A config whose curation layer is complete and sound."""
    curated = tmp_path / "curated"
    curated.mkdir()
    (curated / "atlas.yaml").write_text(
        textwrap.dedent(
            """\
            categories:
              start: "Begin here."
              guides: "How-tos."
            docs:
              README.md: { summary: "The front door.", read_when: "First." }
              docs/guide.md: { summary: "The guide.", read_when: "Second." }
            """
        ),
        encoding="utf-8",
    )
    sample_config_path.write_text(
        sample_config_path.read_text(encoding="utf-8") + f"curated_dir: {curated.as_posix()}\n",
        encoding="utf-8",
    )
    return sample_config_path


def test_sound_curation_passes(verified_config):
    errors, notes = verify(verified_config)
    assert errors == []
    assert any("2 docs" in n for n in notes)


def test_missing_curation_file_fails(sample_config_path):
    errors, _ = verify(sample_config_path)
    assert any("atlas.yaml is missing" in e for e in errors)
    assert any("lack an authored summary" in e for e in errors)


def test_unknown_doc_in_curation_fails(verified_config, tmp_path):
    atlas_yaml = tmp_path / "curated" / "atlas.yaml"
    atlas_yaml.write_text(
        atlas_yaml.read_text(encoding="utf-8").replace("README.md:", "GHOST.md:"),
        encoding="utf-8",
    )
    errors, _ = verify(verified_config)
    assert any("GHOST.md" in e for e in errors)


def test_dangling_journey_stop_fails(verified_config, tmp_path):
    (tmp_path / "curated" / "journeys.yaml").write_text(
        textwrap.dedent(
            """\
            - id: walk
              title: W
              intro: I
              stops:
                - { doc: MISSING.md, narration: "n" }
            """
        ),
        encoding="utf-8",
    )
    errors, _ = verify(verified_config)
    assert any("journey 'walk'" in e and "MISSING.md" in e for e in errors)


def test_dangling_diagram_node_fails(verified_config, tmp_path):
    (tmp_path / "curated" / "diagrams.yaml").write_text(
        textwrap.dedent(
            """\
            - id: flow
              title: F
              doc: README.md
              nodes:
                - { id: a, type: start, label: A, summary: s, doc: README.md, heading: install }
                - { id: b, type: output, label: B, summary: s, doc: README.md, heading: vanished }
            """
        ),
        encoding="utf-8",
    )
    errors, _ = verify(verified_config)
    assert any("diagram 'flow'" in e and "vanished" in e for e in errors)


def test_claim_counter_error_fails_but_claim_drift_does_not(verified_config, tmp_path):
    (tmp_path / "curated" / "claims.yaml").write_text(
        textwrap.dedent(
            """\
            - id: broken
              doc: README.md
              quote: "ghost"
              counter: { type: line_count, path: "missing.txt" }
              expected: 1
            - id: drifting
              doc: README.md
              quote: "two docs"
              counter: { type: file_count, glob: "*.md" }
              expected: 99
            """
        ),
        encoding="utf-8",
    )
    errors, notes = verify(verified_config)
    assert any("claim 'broken'" in e for e in errors)          # error: fatal
    assert not any("drifting" in e for e in errors)             # drift: not fatal
    assert any("failing claim" in n for n in notes)


def test_dead_glob_fails(verified_config):
    text = verified_config.read_text(encoding="utf-8").replace(
        '- include: ["*.md", "docs/*.md"]', '- include: ["*.md", "phantom/*.md"]'
    )
    verified_config.write_text(text, encoding="utf-8")
    errors, _ = verify(verified_config)
    assert any("build failed" in e and "phantom" in e for e in errors)


def test_shipped_tree_verifies_clean():
    """The deployed instance must pass its own harness.

    Skips in the bare kit (no config). Once a target repo writes its
    atlas.config.yaml + curated/, this asserts the curation layer is sound.
    """
    from pathlib import Path

    import pytest

    config_path = Path(__file__).resolve().parents[1] / "atlas.config.yaml"
    if not config_path.is_file():
        pytest.skip("no deployed atlas.config.yaml — bare kit")

    errors, _ = verify(config_path)
    assert errors == [], f"shipped curation has errors: {errors}"
