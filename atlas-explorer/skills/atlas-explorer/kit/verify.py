"""The Atlas integrity harness (DESIGN.md §7).

Fails loudly (exit 1) on curation ERRORS — things only a maintainer can
break: summaries that don't cover the corpus or point at missing docs,
journey stops and diagram nodes with dangling anchors, claim counters
that crash, config globs matching nothing.

Content DRIFT (claim value mismatches, broken doc→code references) is
the system working as designed: it reports on /drift and does NOT fail
verification.

Run:  python verify.py [path/to/atlas.config.yaml]
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from engine.config import ConfigError, load_config  # noqa: E402
from engine.drift import build_drift  # noqa: E402
from engine.registry import build_registry  # noqa: E402


def verify(config_path: Path | str) -> tuple[list[str], list[str]]:
    """Returns (errors, notes). Non-empty errors = verification failure."""
    errors: list[str] = []
    notes: list[str] = []

    try:
        config = load_config(config_path)
        registry = build_registry(config)
    except ConfigError as exc:
        # covers: bad config structure, dead corpus globs, curation entries
        # referencing unknown docs/categories, broken claims/journeys/diagrams schema
        return [f"build failed: {exc}"], notes

    if not registry.curated.source_exists:
        errors.append("curated/atlas.yaml is missing — the orientation layer is required")
    if registry.uncurated:
        errors.append(
            f"{len(registry.uncurated)} full-depth doc(s) lack an authored summary: "
            + ", ".join(registry.uncurated[:10])
            + ("…" if len(registry.uncurated) > 10 else "")
        )

    for dangling in registry.dangling_stops:
        errors.append(
            f"journey '{dangling.journey_id}' stop {dangling.stop_index + 1} "
            f"({dangling.label}): {dangling.reason}"
        )
    for dangling in registry.dangling_nodes:
        errors.append(
            f"diagram '{dangling.diagram_id}' node '{dangling.node_id}' "
            f"({dangling.label}): {dangling.reason}"
        )

    for result in registry.claims:
        if result.status == "error":
            errors.append(f"claim '{result.claim.id}': {result.message}")

    # Drift is reported, never fatal.
    drift = build_drift(registry)
    failing_claims = sum(1 for r in registry.claims if r.status == "fail")
    notes.append(
        f"{registry.doc_count} docs · {len(registry.journeys)} journeys · "
        f"{len(registry.diagrams)} diagrams · {len(registry.claims)} claims"
    )
    if drift.count or failing_claims:
        notes.append(
            f"drift (reported on /drift, not fatal): {drift.count} broken reference(s), "
            f"{failing_claims} failing claim(s)"
        )

    return errors, notes


def main() -> int:
    config_path = sys.argv[1] if len(sys.argv) > 1 else Path(__file__).parent / "atlas.config.yaml"
    errors, notes = verify(config_path)
    for note in notes:
        print(f"  {note}")
    if errors:
        print(f"\nVERIFY FAILED — {len(errors)} curation error(s):", file=sys.stderr)
        for error in errors:
            print(f"  ✗ {error}", file=sys.stderr)
        return 1
    print("\nVERIFY OK — curation layer is sound.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
