"""Config loading: valid configs load; structural problems fail loudly."""

import pytest

from engine.config import ConfigError, load_config


def test_valid_config_loads(sample_config_path, sample_repo):
    config = load_config(sample_config_path)
    assert config.site.title == "Test Atlas"
    assert config.repo_root == sample_repo.resolve()
    assert [c.id for c in config.categories] == ["start", "guides"]
    assert config.corpus[0].depth == "full"


def test_missing_site_title_fails(sample_config_path):
    text = sample_config_path.read_text(encoding="utf-8").replace('title: "Test Atlas"', "")
    sample_config_path.write_text(text, encoding="utf-8")
    with pytest.raises(ConfigError, match="title"):
        load_config(sample_config_path)


def test_unknown_category_in_rule_fails(sample_config_path):
    text = sample_config_path.read_text(encoding="utf-8").replace(
        "category: guides", "category: nonexistent"
    )
    sample_config_path.write_text(text, encoding="utf-8")
    with pytest.raises(ConfigError, match="nonexistent"):
        load_config(sample_config_path)


def test_bad_depth_fails(sample_config_path):
    text = sample_config_path.read_text(encoding="utf-8").replace("depth: full", "depth: bogus")
    sample_config_path.write_text(text, encoding="utf-8")
    with pytest.raises(ConfigError, match="depth"):
        load_config(sample_config_path)


def test_missing_repo_root_fails(sample_config_path):
    text = sample_config_path.read_text(encoding="utf-8").replace(
        "repo_root: repo", "repo_root: does-not-exist"
    )
    sample_config_path.write_text(text, encoding="utf-8")
    with pytest.raises(ConfigError, match="repo_root"):
        load_config(sample_config_path)


def test_category_for_first_match_wins(sample_config_path):
    config = load_config(sample_config_path)
    assert config.category_for("README.md") == "start"
    assert config.category_for("docs/guide.md") == "guides"
    assert config.category_for("unmatched/thing.md") is None
