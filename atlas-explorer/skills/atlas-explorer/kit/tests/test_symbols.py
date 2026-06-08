"""tree-sitter symbol index, fold rendering, jump-to-symbol (issue 003)."""

import textwrap

import pytest
from fastapi.testclient import TestClient

import app as app_module
from engine.config import ConfigError, LanguageSpec, load_config
from engine.registry import build_registry
from engine.symbols import SymbolIndexer

TS_SPECS = (
    LanguageSpec(extensions=(".ts",), grammar="tree_sitter_typescript:language_typescript"),
)

TS_SAMPLE = textwrap.dedent(
    """\
    import { x } from "./other";

    export interface Options {
      name: string;
      depth: number;
    }

    export function dispatch(opts: Options): void {
      const inner = () => {
        console.log(opts.name);
      };
      inner();
    }

    export const helper = (n: number): number => {
      return n * 2;
    };

    class Engine {
      start(): void {
        console.log("start");
        console.log("more");
      }
      stop(): void {
        console.log("stop");
        console.log("more");
      }
    }

    const SHORT = 1;
    """
)


@pytest.fixture()
def ts_repo(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "engine.ts").write_text(TS_SAMPLE, encoding="utf-8")
    return tmp_path


def test_extraction_kinds_and_spans(ts_repo):
    indexer = SymbolIndexer(TS_SPECS)
    fs = indexer.index_for(ts_repo / "src" / "engine.ts")
    by_name = {s.qualified: s for s in fs.flat()}

    assert by_name["Options"].kind == "interface" and by_name["Options"].exported
    assert by_name["dispatch"].kind == "function" and by_name["dispatch"].exported
    assert by_name["helper"].kind == "function"  # exported arrow const
    assert by_name["Engine"].kind == "class" and not by_name["Engine"].exported
    assert by_name["Engine.start"].kind == "method"
    assert by_name["SHORT"].kind == "const"
    # spans: dispatch starts at its export line
    assert by_name["dispatch"].start_line < by_name["dispatch"].end_line


def test_find_supports_bare_and_qualified(ts_repo):
    fs = SymbolIndexer(TS_SPECS).index_for(ts_repo / "src" / "engine.ts")
    assert fs.find("Engine.stop") is not None
    assert fs.find("stop") is not None
    assert fs.find("nonexistent") is None


def test_unsupported_extension_has_no_language(ts_repo):
    (ts_repo / "src" / "notes.txt").write_text("hello", encoding="utf-8")
    fs = SymbolIndexer(TS_SPECS).index_for(ts_repo / "src" / "notes.txt")
    assert fs.language is None and fs.symbols == []


def test_bad_grammar_fails_loudly():
    with pytest.raises(ConfigError, match="failed to load"):
        SymbolIndexer((LanguageSpec(extensions=(".zz",), grammar="no_such_module:nope"),))


def test_mtime_cache_invalidation(ts_repo):
    indexer = SymbolIndexer(TS_SPECS)
    path = ts_repo / "src" / "engine.ts"
    first = indexer.index_for(path)
    assert indexer.index_for(path) is first  # cached
    import os, time

    os.utime(path, (time.time() + 5, time.time() + 5))
    assert indexer.index_for(path) is not first  # invalidated


# ── end-to-end: docs that mention symbols ──


@pytest.fixture()
def symbol_config(sample_repo, sample_config_path):
    src = sample_repo / "src"
    src.mkdir()
    (src / "engine.ts").write_text(TS_SAMPLE, encoding="utf-8")
    (sample_repo / "README.md").write_text(
        textwrap.dedent(
            """\
            # Sample Project

            Call `dispatch()` in `src/engine.ts` to start. The removed
            `vanished()` in `src/engine.ts` is history.
            """
        ),
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
    return sample_config_path


def test_symbol_refs_verified_at_build(symbol_config):
    registry = build_registry(load_config(symbol_config))
    readme = registry.docs["README.md"]
    by_raw = {r.raw: r for r in readme.symbol_refs}
    assert by_raw["dispatch()"].resolved is True
    assert by_raw["vanished()"].resolved is False  # drift fodder for 006


def test_symbol_chip_rendered(symbol_config):
    client = TestClient(app_module.create_app(symbol_config))
    page = client.get("/doc/README.md").text
    assert "symbol=dispatch" in page
    assert 'class="code-chip sym-chip"' in page
    # unresolved symbol mention renders with broken-reference styling (006)
    assert "No symbol vanished" in page
    assert page.count('class="ref-broken"') == 1


def test_jump_to_symbol_partial(symbol_config):
    client = TestClient(app_module.create_app(symbol_config))
    response = client.get(
        "/partial/code", params={"path": "src/engine.ts", "symbol": "dispatch"}
    )
    assert response.status_code == 200
    assert "hl-target" in response.text
    assert "dispatch L" in response.text  # header subtitle shows the span
    # non-target folds arrive closed, target open
    assert '<details class="fold" open id="sym-dispatch">' in response.text
    assert '<details class="fold" id="sym-Engine">' in response.text


def test_whole_file_view_all_folds_open(symbol_config):
    client = TestClient(app_module.create_app(symbol_config))
    response = client.get("/partial/code", params={"path": "src/engine.ts"})
    assert response.status_code == 200
    assert response.text.count("<details class=\"fold\" open") >= 3
    assert 'class="outline"' in response.text


def test_unknown_symbol_falls_back_to_whole_file(symbol_config):
    client = TestClient(app_module.create_app(symbol_config))
    response = client.get(
        "/partial/code", params={"path": "src/engine.ts", "symbol": "ghost"}
    )
    assert response.status_code == 200
    assert "not found" in response.text
