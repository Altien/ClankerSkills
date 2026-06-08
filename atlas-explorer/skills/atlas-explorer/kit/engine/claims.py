"""Curated quantitative claims, checked deterministically.

claims.yaml pairs a quoted documentation claim with a counter expression.
No NLP: every claim is hand-curated, every counter is a deterministic
measurement of the tree. Three outcomes:

  pass  — the doc and the tree agree
  fail  — drift: the doc claims a number the tree contradicts
  error — the counter itself is broken (bad glob/path): a curation bug,
          surfaced loudly and treated as fatal by verify.py (DESIGN §7)
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from .config import AtlasConfig, ConfigError


@dataclass(frozen=True)
class Claim:
    id: str
    doc: str            # doc id making the claim
    quote: str          # the claim as written, for inline marking
    counter_type: str
    counter_args: dict
    expected: int       # what the doc claims
    note: str = ""


@dataclass(frozen=True)
class ClaimResult:
    claim: Claim
    actual: int | None
    status: str         # pass | fail | error
    message: str

    @property
    def doc_url(self) -> str:
        return f"/doc/{self.claim.doc}"


def _count_files(config: AtlasConfig, symbols, args: dict) -> int:
    glob = args.get("glob")
    if not glob:
        raise ValueError("file_count requires a 'glob' arg")
    return sum(1 for p in config.repo_root.glob(glob) if p.is_file())


def _count_symbols(config: AtlasConfig, symbols, args: dict) -> int:
    path = args.get("path")
    if not path:
        raise ValueError("symbol_count requires a 'path' arg")
    file_symbols = symbols.index_for(config.repo_root / path)
    if file_symbols.language is None:
        raise ValueError(f"no grammar configured for {path}")
    if args.get("exported_only"):
        return sum(1 for s in file_symbols.flat() if s.exported)
    return len(file_symbols.flat())


def _count_lines(config: AtlasConfig, symbols, args: dict) -> int:
    path = args.get("path")
    if not path:
        raise ValueError("line_count requires a 'path' arg")
    target = config.repo_root / path
    if not target.is_file():
        raise ValueError(f"no such file: {path}")
    return target.read_text(encoding="utf-8", errors="replace").count("\n") + 1


COUNTERS = {
    "file_count": _count_files,
    "symbol_count": _count_symbols,
    "line_count": _count_lines,
}


def load_claims(path: Path) -> list[Claim]:
    if not path.is_file():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    claims: list[Claim] = []
    seen_ids: set[str] = set()
    for i, raw in enumerate(data):
        counter = raw.get("counter") or {}
        counter_type = counter.get("type", "")
        if counter_type not in COUNTERS:
            raise ConfigError(
                f"claims[{i}] counter type '{counter_type}' unknown "
                f"(have: {', '.join(COUNTERS)})"
            )
        claim_id = raw.get("id") or f"claim-{i}"
        if claim_id in seen_ids:
            raise ConfigError(f"duplicate claim id '{claim_id}'")
        seen_ids.add(claim_id)
        for key in ("doc", "quote", "expected"):
            if key not in raw:
                raise ConfigError(f"claims[{i}] ('{claim_id}') missing '{key}'")
        claims.append(
            Claim(
                id=claim_id,
                doc=raw["doc"],
                quote=str(raw["quote"]),
                counter_type=counter_type,
                counter_args={k: v for k, v in counter.items() if k != "type"},
                expected=int(raw["expected"]),
                note=raw.get("note", ""),
            )
        )
    return claims


def run_claims(config: AtlasConfig, symbols, claims: list[Claim]) -> list[ClaimResult]:
    results: list[ClaimResult] = []
    for claim in claims:
        try:
            actual = COUNTERS[claim.counter_type](config, symbols, claim.counter_args)
        except Exception as exc:  # counter bug = curation error, not drift
            results.append(ClaimResult(claim, None, "error", f"counter failed: {exc}"))
            continue
        if actual == claim.expected:
            results.append(ClaimResult(claim, actual, "pass", "doc and tree agree"))
        else:
            results.append(
                ClaimResult(
                    claim,
                    actual,
                    "fail",
                    f"doc claims {claim.expected}, tree has {actual}",
                )
            )
    return results
