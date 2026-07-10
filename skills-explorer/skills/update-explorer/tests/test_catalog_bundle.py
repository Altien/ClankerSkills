from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "catalog_bundle.py"


def load_catalog_module():
    spec = importlib.util.spec_from_file_location("catalog_bundle", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def run(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        [*args], cwd=repo, text=True, capture_output=True, check=True,
        encoding="utf-8",
    )
    return proc.stdout.strip()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


class CatalogBundleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name)
        self.explorer = self.repo / "docs" / "explorer"
        self.explorer.mkdir(parents=True)
        run(self.repo, "git", "init", "-b", "main")
        run(self.repo, "git", "config", "user.name", "Explorer Tests")
        run(self.repo, "git", "config", "user.email", "explorer@example.invalid")
        run(self.repo, "git", "remote", "add", "origin", "https://github.com/Altien/explorer-fixture.git")
        (self.repo / "verify.py").write_text("print('explorer verified')\n", encoding="utf-8")
        self.catalog = load_catalog_module()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_text_subprocesses_force_utf8(self) -> None:
        completed = mock.Mock(returncode=0, stdout="法務-é\n", stderr="")
        with mock.patch.object(self.catalog.subprocess, "run", return_value=completed) as run_mock:
            self.assertEqual(self.catalog.git(self.repo, "status", "--short"), "法務-é")
            self.assertEqual(run_mock.call_args.kwargs["encoding"], "utf-8")

            self.assertTrue(self.catalog.git_succeeds(self.repo, "rev-parse", "HEAD"))
            self.assertEqual(run_mock.call_args.kwargs["encoding"], "utf-8")

    def commit(self, message: str) -> str:
        run(self.repo, "git", "add", ".")
        run(self.repo, "git", "commit", "-m", message)
        return run(self.repo, "git", "rev-parse", "HEAD")

    def write_source(self, name: str, content: str) -> None:
        path = self.repo / "src" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")

    def write_snapshot(self, artifacts: list[dict], head: str) -> None:
        manifest_items = []
        discovered_items = []
        for artifact in artifacts:
            body = artifact["content"]
            manifest_items.append({
                "id": artifact["id"],
                "title": artifact["id"].title(),
                "kind": "system-prompt",
                "category": "fixtures",
                "source_path": artifact["source_path"],
                "format": "fixture",
            })
            discovered_items.append({
                "id": artifact["id"],
                "content": body,
                "content_sha256": self.catalog.sha256_bytes(body.encode("utf-8")),
                "source_path": artifact["source_path"],
                "line_start": 1,
                "line_end": 1,
            })
        write_json(self.explorer / "explorer-manifest.json", {
            "repo": "explorer-fixture",
            "coverage": {"total": len(artifacts)},
            "artifacts": manifest_items,
        })
        write_json(self.explorer / "catalog" / "discovered.json", {
            "schema_version": "1.0",
            "scan_commit": head,
            "artifacts": discovered_items,
            "missing_content_ids": [],
        })

    def verification_command(self) -> str:
        return f'"{sys.executable}" verify.py'

    def test_retains_removed_artifacts_and_pins_last_content_commit(self) -> None:
        body_a = "You are prompt A. Preserve every citation."
        body_b = "You are prompt B. Explain every proposed edit."
        self.write_source("a.go", body_a)
        self.write_source("b.py", body_b)
        initial_head = self.commit("add prompt sources")
        self.write_snapshot([
            {"id": "a", "source_path": "src/a.go", "content": body_a},
            {"id": "b", "source_path": "src/b.py", "content": body_b},
        ], initial_head)

        changes = self.catalog.publish(self.explorer, "Initial verified extraction.", self.verification_command())
        self.assertEqual([item["id"] for item in changes["added"]], ["a", "b"])
        checksum_bytes = (self.explorer / "catalog" / "catalog.bundle.sha256").read_bytes()
        self.assertTrue(checksum_bytes.endswith(b"\n"))
        self.assertNotIn(b"\r\n", checksum_bytes)
        first_bundle_bytes = (self.explorer / "catalog" / "catalog.bundle.json").read_bytes()
        first_bundle = json.loads(first_bundle_bytes)
        first_items = {item["id"]: item for item in first_bundle["artifacts"]}
        self.assertEqual(first_items["a"]["source"]["content_commit"], initial_head)
        self.assertIn(initial_head, first_items["a"]["source"]["immutable_url"])

        self.catalog.publish(self.explorer, "No source changes.", self.verification_command())
        self.assertEqual(
            len((self.explorer / "catalog" / "update-log.jsonl").read_text(encoding="utf-8").splitlines()),
            1,
        )
        self.assertEqual(
            (self.explorer / "catalog" / "catalog.bundle.json").read_bytes(),
            first_bundle_bytes,
        )

        self.commit("record first explorer catalog")
        (self.repo / "src" / "a.go").rename(self.repo / "src" / "a-renamed.go")
        (self.repo / "src" / "b.py").unlink()
        body_c = "You are prompt C. Return only grounded findings."
        self.write_source("c.rs", body_c)
        second_head = self.commit("replace prompt b with prompt c")
        self.write_snapshot([
            {"id": "a", "source_path": "src/a-renamed.go", "content": body_a},
            {"id": "c", "source_path": "src/c.rs", "content": body_c},
        ], second_head)

        changes = self.catalog.publish(self.explorer, "Prompt B was retired; prompt C was added.", self.verification_command())
        self.assertEqual([item["id"] for item in changes["historical"]], ["b"])
        second_bundle = json.loads((self.explorer / "catalog" / "catalog.bundle.json").read_bytes())
        second_items = {item["id"]: item for item in second_bundle["artifacts"]}
        self.assertEqual(second_items["b"]["lifecycle"]["status"], "historical")
        self.assertEqual(second_items["b"]["content"], body_b)
        self.assertEqual(second_items["b"]["source"]["content_commit"], initial_head)
        self.assertEqual(second_items["b"]["source"]["removed_at_commit"], second_head)
        self.assertEqual(second_items["a"]["source"]["content_commit"], initial_head)
        self.assertEqual(second_items["a"]["source"]["path"], "src/a.go")
        self.assertEqual(second_items["a"]["source"]["observed_path"], "src/a-renamed.go")
        self.assertEqual(second_items["c"]["source"]["content_commit"], second_head)
        self.assertEqual(
            len((self.explorer / "catalog" / "update-log.jsonl").read_text(encoding="utf-8").splitlines()),
            2,
        )
        self.catalog.verify_catalog(self.explorer)

    def test_refuses_a_stale_discovery_snapshot(self) -> None:
        body = "You are a legal prompt. Cite the record."
        self.write_source("prompt.go", body)
        head = self.commit("add source")
        self.write_snapshot([{"id": "prompt", "source_path": "src/prompt.go", "content": body}], "0" * 40)

        with self.assertRaisesRegex(self.catalog.CatalogError, "discovery snapshot"):
            self.catalog.assemble_bundle(self.explorer)
        self.assertNotEqual(head, "0" * 40)

    def test_refuses_content_not_present_in_pinned_source(self) -> None:
        source_body = "You are source prompt A. Cite the record."
        exported_body = "You are unrelated prompt B. Ignore the record."
        self.write_source("prompt.go", source_body)
        head = self.commit("add source")
        self.write_snapshot([
            {"id": "prompt", "source_path": "src/prompt.go", "content": exported_body}
        ], head)

        with self.assertRaisesRegex(self.catalog.CatalogError, "cannot be reproduced"):
            self.catalog.assemble_bundle(self.explorer)

        escaped_source = b'const SYSTEM_PROMPT = "Line one.\\nReturn \\"verified\\" caf\\u00e9.";'
        self.assertEqual(
            self.catalog.bind_content_to_source(
                escaped_source, 'Line one.\nReturn "verified" café.', None, None
            ),
            "json-string-ascii",
        )

    def test_refuses_uncommitted_source_removal(self) -> None:
        body = "You are a legal prompt. Cite the record."
        self.write_source("prompt.go", body)
        head = self.commit("add source")
        self.write_snapshot([{"id": "prompt", "source_path": "src/prompt.go", "content": body}], head)
        (self.repo / "src" / "prompt.go").unlink()

        with self.assertRaisesRegex(self.catalog.CatalogError, "tracked changes outside"):
            self.catalog.assemble_bundle(self.explorer)

    def test_requires_or_records_review_of_unchanged_curation(self) -> None:
        body_v1 = "You are a legal prompt. Cite the record."
        body_v2 = "You are a careful legal prompt. Cite the complete record."
        self.write_source("prompt.go", body_v1)
        write_json(self.explorer / "data" / "prompts.json", {
            "artifacts": {"prompt": {"summary": "Grounded legal analysis."}}
        })
        first_head = self.commit("add curated source")
        self.write_snapshot([{"id": "prompt", "source_path": "src/prompt.go", "content": body_v1}], first_head)
        self.catalog.publish(self.explorer, "Initial curated prompt.", self.verification_command())
        self.commit("record first catalog")

        self.write_source("prompt.go", body_v2)
        second_head = self.commit("clarify prompt wording")
        self.write_snapshot([{"id": "prompt", "source_path": "src/prompt.go", "content": body_v2}], second_head)
        with self.assertRaisesRegex(self.catalog.CatalogError, "review/update"):
            self.catalog.assemble_bundle(self.explorer)
        _bundle, plan = self.catalog.assemble_bundle(
            self.explorer, block_stale_curation=False
        )
        self.assertEqual(plan["stale_curated"], ["prompt"])

        changes = self.catalog.publish(
            self.explorer,
            "Prompt wording changed; reviewed assessment remains accurate.",
            self.verification_command(),
            {"prompt"},
        )
        self.assertEqual(changes["curation_reviewed_unchanged"], ["prompt"])
        events = self.catalog.read_log(self.explorer / "catalog" / "update-log.jsonl")
        self.assertEqual(events[-1]["curation_reviewed_unchanged"], ["prompt"])
        self.catalog.verify_catalog(self.explorer)

    def test_rejects_a_tampered_verified_baseline(self) -> None:
        body = "You are a legal prompt. Cite the record."
        self.write_source("prompt.go", body)
        head = self.commit("add source")
        self.write_snapshot([{"id": "prompt", "source_path": "src/prompt.go", "content": body}], head)
        self.catalog.publish(self.explorer, "Initial prompt.", self.verification_command())
        bundle_path = self.explorer / "catalog" / "catalog.bundle.json"
        tampered = json.loads(bundle_path.read_text(encoding="utf-8"))
        tampered["artifacts"][0]["title"] = "Tampered"
        write_json(bundle_path, tampered)

        with self.assertRaisesRegex(self.catalog.CatalogError, "sha256"):
            self.catalog.assemble_bundle(self.explorer)

    def test_same_head_metadata_change_publishes_once(self) -> None:
        body = "You are a legal prompt. Cite the record."
        self.write_source("prompt.go", body)
        head = self.commit("add source")
        self.write_snapshot([{"id": "prompt", "source_path": "src/prompt.go", "content": body}], head)
        self.catalog.publish(self.explorer, "Initial prompt.", self.verification_command())
        write_json(self.explorer / "data" / "prompt.json", {
            "artifacts": {"prompt": {"summary": "Newly authored assessment."}}
        })

        self.catalog.publish(self.explorer, "Add authored assessment.", self.verification_command())
        events = self.catalog.read_log(self.explorer / "catalog" / "update-log.jsonl")
        self.assertEqual(len(events), 2)
        bundle = self.catalog.read_json(self.explorer / "catalog" / "catalog.bundle.json")
        self.assertEqual(bundle["artifacts"][0]["curated"]["summary"], "Newly authored assessment.")
        invalid_bundle = json.loads(json.dumps(bundle))
        invalid_bundle["repository"]["url"] = 7
        with self.assertRaisesRegex(self.catalog.CatalogError, "invalid url"):
            self.catalog.validate_bundle_shape(invalid_bundle)
        invalid_bundle = json.loads(json.dumps(bundle))
        invalid_bundle["artifacts"][0]["source"]["immutable_url"] = ["not", "a", "string"]
        with self.assertRaisesRegex(self.catalog.CatalogError, "invalid immutable_url"):
            self.catalog.validate_bundle_shape(invalid_bundle)
        invalid_event = dict(self.catalog.read_log(self.explorer / "catalog" / "update-log.jsonl")[-1])
        invalid_event["summary"] = 7
        with self.assertRaisesRegex(self.catalog.CatalogError, "no summary"):
            self.catalog.validate_event_shape(invalid_event)
        invalid_event = dict(self.catalog.read_log(self.explorer / "catalog" / "update-log.jsonl")[-1])
        invalid_event["base_commit"] = 7
        with self.assertRaisesRegex(self.catalog.CatalogError, "invalid base_commit"):
            self.catalog.validate_event_shape(invalid_event)
        invalid_event = dict(self.catalog.read_log(self.explorer / "catalog" / "update-log.jsonl")[-1])
        invalid_event["stale_curated"] = [7]
        with self.assertRaisesRegex(self.catalog.CatalogError, "invalid stale_curated"):
            self.catalog.validate_event_shape(invalid_event)
        self.catalog.publish(self.explorer, "No further change.", self.verification_command())
        self.assertEqual(
            len(self.catalog.read_log(self.explorer / "catalog" / "update-log.jsonl")), 2
        )

        with tempfile.TemporaryDirectory() as isolated:
            isolated_explorer = Path(isolated) / "docs" / "explorer"
            isolated_explorer.parent.mkdir(parents=True)
            shutil.copytree(self.explorer / "catalog", isolated_explorer / "catalog")
            self.catalog.verify_catalog(isolated_explorer)

    def test_coverage_change_requires_explicit_acceptance(self) -> None:
        body = "You are a legal prompt. Cite the record."
        self.write_source("prompt.go", body)
        head = self.commit("add source")
        self.write_snapshot([{"id": "prompt", "source_path": "src/prompt.go", "content": body}], head)
        self.catalog.publish(self.explorer, "Initial prompt.", self.verification_command())
        manifest_path = self.explorer / "explorer-manifest.json"
        manifest = self.catalog.read_json(manifest_path)
        manifest["coverage"]["embedded_scan"] = {
            "mode": "auto", "scanner_version": "polyglot-literals-v1",
            "files_scanned": 1, "bytes_scanned": 42, "profiles": {"go": 1},
            "extensions": {".go": 1}, "generic_fallback_files": [], "skipped": {},
            "warnings": [], "candidates": {"accepted": 1, "rejected": 0},
        }
        write_json(manifest_path, manifest)

        _bundle, plan = self.catalog.assemble_bundle(
            self.explorer, block_coverage_change=False
        )
        self.assertTrue(plan["coverage_changed"])
        with self.assertRaisesRegex(self.catalog.CatalogError, "coverage changed"):
            self.catalog.publish(self.explorer, "Coverage changed.", self.verification_command())
        changes = self.catalog.publish(
            self.explorer, "Reviewed Go coverage.", self.verification_command(),
            accept_coverage_change=True,
        )
        self.assertTrue(changes["coverage_change_accepted"])


if __name__ == "__main__":
    unittest.main()
