"""Reusability contract (DESIGN.md §6): engine code never references this repo.

Repo-specific strings may live only in atlas.config.yaml and curated/.
"""

from pathlib import Path

ATLAS_DIR = Path(__file__).resolve().parents[1]

# Names that identify the HOST repository/product. ADAPT PER REPO: replace these
# with this repo's product/codebase names (and any source-dir tokens) so the test
# enforces that the engine never hard-codes anything about its host. The list
# below is the canonical-kit placeholder; leaving it unedited still passes (the
# engine genuinely contains none of these), but it won't be checking YOUR names.
FORBIDDEN = ("__HOST_PRODUCT_NAME__", "__HOST_CODENAME__")

# Engine surface that must stay repo-agnostic.
SURFACES = ("engine", "templates", "static")
FILES = ("app.py",)


def _engine_files():
    for surface in SURFACES:
        yield from (ATLAS_DIR / surface).rglob("*.*")
    for name in FILES:
        yield ATLAS_DIR / name


def test_engine_is_repo_agnostic():
    offenders = []
    for path in _engine_files():
        if path.suffix in (".pyc",) or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace").lower()
        for word in FORBIDDEN:
            if word in text:
                offenders.append(f"{path.relative_to(ATLAS_DIR)}: '{word}'")
    assert not offenders, "repo-specific strings in engine surface:\n" + "\n".join(offenders)
