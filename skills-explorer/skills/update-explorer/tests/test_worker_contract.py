from __future__ import annotations

import unittest
from pathlib import Path


PLUGIN = Path(__file__).resolve().parents[3]


class ExplorerWorkerContractTests(unittest.TestCase):
    def test_worker_is_haiku_and_cannot_make_judgment_or_git_publication_decisions(self) -> None:
        worker = (PLUGIN / "agents" / "explorer-update-worker.md").read_text(encoding="utf-8")
        collapsed = " ".join(worker.split())
        self.assertIn("model: haiku", worker)
        self.assertIn("Never clone, pull, fetch, push, commit", worker)
        self.assertIn("accept a coverage change", collapsed)
        self.assertIn("Return one JSON object and no prose", worker)

    def test_update_skill_keeps_approval_in_primary_model(self) -> None:
        skill = (Path(__file__).resolve().parents[1] / "SKILL.md").read_text(encoding="utf-8")
        collapsed = " ".join(skill.split())
        self.assertIn("explorer-update-worker", skill)
        self.assertIn("Keep all judgment in the primary model", skill)
        self.assertIn("If model routing is unavailable, say so", collapsed)


if __name__ == "__main__":
    unittest.main()
