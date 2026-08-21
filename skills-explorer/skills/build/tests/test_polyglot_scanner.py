from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


SKELETON = Path(__file__).resolve().parents[1] / "templates" / "build_explorer.skeleton.py"


def load_scanner(repo: Path):
    spec = importlib.util.spec_from_file_location("build_explorer_fixture", SKELETON)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    module.REPO = str(repo)
    module.EMBEDDED_SCAN = True
    module.EMBEDDED_FILES = []
    return module


class PolyglotScannerTests(unittest.TestCase):
    def test_discovers_prompt_literals_across_language_families(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            fixtures = {
                "agent.go": '''
var systemPrompt = `You are a Go legal analyst. Review the record and return grounded findings.`
msg := Message{Role: "system", Content: "You must verify every legal citation before answering the user."}
''',
                "agent.rs": 'const SYSTEM_PROMPT: &str = r#"Act as a Rust legal research agent and cite every conclusion."#;\n',
                "Agent.java": 'String SYSTEM_PROMPT = """You are a Java legal drafting assistant. Preserve defined terms exactly.""";\n',
                "Agent.cs": 'const string SystemPrompt = """You are a C sharp contract reviewer. Explain every proposed edit.""";\n',
                "agent.rb": '''SYSTEM_PROMPT = <<~PROMPT
You are a Ruby legal intake assistant. Ask only questions needed for conflicts review.
PROMPT
''',
                "agent.ps1": '''$SystemPrompt = @"
You are a PowerShell legal operations assistant. Return a concise audit log.
"@
<# $BLOCKED_SYSTEM_PROMPT = "You are inside a PowerShell block comment." #>
''',
                "commented.lua": '-- SYSTEM_PROMPT = "You are inside a Lua comment and must be ignored."\n',
                "commented.ex": '# SYSTEM_PROMPT = "You are inside an Elixir comment and must be ignored."\n',
                "commented.erl": '% SYSTEM_PROMPT = "You are inside an Erlang comment and must be ignored."\n',
                "commented.vb": '\' SYSTEM_PROMPT = "You are inside a VB comment and must be ignored."\n',
                "agent.futurelang": 'const SYSTEM_PROMPT = "You are a future-language legal agent. Return only verified propositions.";\n',
                "agent.py": '''
SYSTEM_PROMPT = """You are a Python legal analyst. Distinguish facts from assumptions."""
SQL_QUERY = """SELECT * FROM matters WHERE status = 'open' AND owner IS NOT NULL"""
''',
                "web.ts": '''
// const COMMENTED_SYSTEM_PROMPT = `You are a commented prompt and must not be discovered.`;
const HTML_TEMPLATE = `<html><body>This is layout markup, not a model prompt.</body></html>`;
const EXTRACTION_SYSTEM = `You are a TypeScript extraction agent. Return strict JSON only.`;
const USER_PROMPT = `Summarize the supplied pleading without adding facts or legal conclusions.`;
function one() { const SYSTEM_PROMPT = `You are the first scoped system prompt. Return citations.`; }
function two() { const SYSTEM_PROMPT = `You are the second scoped system prompt. Return quotations.`; }
const LOADED_SYSTEM_PROMPT = load_from_disk();
const UNRELATED = `You are text after a non-literal assignment and must not be attached to it.`;
const messages = from_messages([("system", "You are a tuple-based system prompt. Verify every authority.")]);
const EXAMPLE_PROMPT = `Explain message objects such as {"role":"system","content":"This nested example is not a separate prompt artifact."} to the user.`;
const ESCAPED_SYSTEM_PROMPT = "You are an escaped prompt.\\nReturn \\"verified\\" text with caf\\u00e9.";
''',
            }
            for name, body in fixtures.items():
                (repo / name).write_text(body, encoding="utf-8")

            scanner = load_scanner(repo)
            artifacts, report = scanner.discover_embedded()
            contents = [artifact["_content"] for artifact in artifacts]

            self.assertTrue(any("Go legal analyst" in body for body in contents))
            self.assertTrue(any("verify every legal citation" in body for body in contents))
            self.assertTrue(any("Rust legal research" in body for body in contents))
            self.assertTrue(any("Java legal drafting" in body for body in contents))
            self.assertTrue(any("C sharp contract" in body for body in contents))
            self.assertTrue(any("Ruby legal intake" in body for body in contents))
            self.assertTrue(any("PowerShell legal operations" in body for body in contents))
            self.assertTrue(any("future-language legal agent" in body for body in contents))
            self.assertTrue(any("Python legal analyst" in body for body in contents))
            self.assertTrue(any("TypeScript extraction" in body for body in contents))
            self.assertTrue(any("tuple-based system prompt" in body for body in contents))
            self.assertTrue(any('escaped prompt.\nReturn "verified" text with café.' in body for body in contents))
            self.assertFalse(any("SELECT * FROM matters" in body for body in contents))
            self.assertFalse(any("layout markup" in body for body in contents))
            self.assertFalse(any("commented prompt" in body for body in contents))
            self.assertFalse(any("inside a Lua comment" in body for body in contents))
            self.assertFalse(any("inside an Elixir comment" in body for body in contents))
            self.assertFalse(any("inside an Erlang comment" in body for body in contents))
            self.assertFalse(any("inside a VB comment" in body for body in contents))
            self.assertFalse(any("PowerShell block comment" in body for body in contents))
            nested = [artifact for artifact in artifacts if "nested example" in artifact["_content"]]
            self.assertEqual(len(nested), 1)
            loaded = [artifact for artifact in artifacts if "LOADED_SYSTEM_PROMPT" in artifact["title"]]
            self.assertEqual(loaded, [])
            scoped = [artifact for artifact in artifacts if "scoped system prompt" in artifact["_content"]]
            self.assertEqual(len(scoped), 2)
            self.assertEqual(len({artifact["id"] for artifact in scoped}), 2)
            user_prompt = next(artifact for artifact in artifacts if "supplied pleading" in artifact["_content"])
            self.assertEqual(user_prompt["kind"], "prompt-template")
            self.assertIn("go", report["profiles"])
            self.assertIn("rust", report["profiles"])
            self.assertIn("generic", report["profiles"])
            self.assertIn("agent.futurelang", report["generic_fallback_files"])
            self.assertEqual(report["scanner_version"], "polyglot-literals-v1")

    def test_records_binary_oversize_and_generated_skips(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            (repo / "binary.go").write_bytes(b"\x00SYSTEM_PROMPT")
            (repo / "large.rs").write_text("x" * 200, encoding="utf-8")
            tests = repo / "tests"
            tests.mkdir()
            (tests / "agent.go").write_text(
                "var systemPrompt = `You are a prompt hidden in a test fixture.`", encoding="utf-8"
            )
            scanner = load_scanner(repo)
            scanner.MAX_SOURCE_BYTES = 100

            artifacts, report = scanner.discover_embedded()

            self.assertEqual(artifacts, [])
            self.assertEqual(report["skipped"]["binary"], 1)
            self.assertEqual(report["skipped"]["too_large"], 1)
            self.assertEqual(report["skipped"]["generated_or_test"], 1)

    def test_opener_variants_and_missing_explicit_file_warning(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            (repo / "agent.go").write_text(
                'var prompt = `System: verify the cited authority before answering.`\n',
                encoding="utf-8",
            )
            scanner = load_scanner(repo)
            artifacts, _report = scanner.discover_embedded()
            self.assertEqual(len(artifacts), 1)
            self.assertEqual(artifacts[0]["kind"], "system-prompt")

            scanner.EMBEDDED_FILES = ["missing.go"]
            _artifacts, report = scanner.discover_embedded()
            self.assertEqual(report["warnings"], [
                {"path": "missing.go", "reason": "missing_explicit"}
            ])

    def test_main_fails_for_zero_artifacts_or_duplicate_ids(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            explorer = repo / "docs" / "explorer"
            explorer.mkdir(parents=True)
            scanner = load_scanner(repo)
            scanner.HERE = str(explorer)
            scanner.EMBEDDED_SCAN = False
            self.assertEqual(scanner.main(), 1)

            artifact = {
                "id": "duplicate", "title": "Duplicate", "kind": "skill",
                "category": "skills", "source_path": "one.md", "format": "test",
                "description": "", "headings": [], "body_chars": 20,
                "_content": "You are a duplicate prompt.",
            }
            scanner.discover_skill_folders = lambda: [artifact, {**artifact, "source_path": "two.md"}]
            scanner.discover_agents = lambda: []
            scanner.discover_commands = lambda: []
            scanner.discover_prompt_files = lambda: []
            scanner.discover_instruction_docs = lambda: []
            self.assertEqual(scanner.main(), 1)


if __name__ == "__main__":
    unittest.main()
