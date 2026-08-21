"""Shared fixtures: a tiny synthetic repo + config for engine tests."""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

# Make the atlas package importable when pytest runs from anywhere.
ATLAS_DIR = Path(__file__).resolve().parents[1]
if str(ATLAS_DIR) not in sys.path:
    sys.path.insert(0, str(ATLAS_DIR))


@pytest.fixture()
def sample_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "docs").mkdir(parents=True)

    (repo / "README.md").write_text(
        textwrap.dedent(
            """\
            # Sample Project

            Start with the [guide](docs/guide.md) or the [missing one](docs/nope.md).
            External [link](https://example.com/page.md) stays untouched.

            ## Install

            ```bash
            # this is a comment, not a heading
            echo "[fake](docs/fake.md)"
            ```

            ## Install

            Duplicate heading to test slug dedupe.
            """
        ),
        encoding="utf-8",
    )

    (repo / "docs" / "guide.md").write_text(
        textwrap.dedent(
            """\
            # User Guide

            Back to the [readme](../README.md).

            ## Getting Around

            Some prose.
            """
        ),
        encoding="utf-8",
    )

    return repo


@pytest.fixture()
def sample_config_path(tmp_path: Path, sample_repo: Path) -> Path:
    config = tmp_path / "atlas.config.yaml"
    config.write_text(
        textwrap.dedent(
            """\
            site:
              title: "Test Atlas"
              subtitle: "fixture"
            repo_root: repo
            categories:
              - { id: start, title: "Start Here" }
              - { id: guides, title: "Guides" }
            corpus:
              - include: ["*.md", "docs/*.md"]
                depth: full
                render: internal
            category_rules:
              - { match: "README.md", category: start }
              - { match: "docs/*", category: guides }
            """
        ),
        encoding="utf-8",
    )
    return config
