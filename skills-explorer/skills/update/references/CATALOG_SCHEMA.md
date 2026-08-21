# Explorer catalog contract

The source repository publishes `docs/explorer/catalog/catalog.bundle.json`. Downstream
directories consume only a bundle whose checksum and `verification.json` pass
`catalog_bundle.py verify`; they do not rediscover artifacts from source code.

## Artifact lifecycle

- `active`: present in the current verified Explorer discovery payload.
- `historical`: absent from current discovery but retained verbatim from the last verified
  bundle. Historical artifacts remain available to downstream libraries.

`source.content_commit` identifies the immutable commit containing the exported content.
`source.source_blob_sha256` proves that the linked source path exists with the recorded blob
at that commit. `source.content_binding` records the reproducible verbatim/JSON/C# transform
that located the exact exported body in that blob or line slice. If an unchanged artifact moves, its immutable provenance tuple remains at
the earlier path/commit while `source.observed_path` and the mechanical manifest record its
current location.
`source.last_seen_commit` records the latest repository commit where discovery still found it.
`source.removed_at_commit` records when it first became historical. Never replace
`content_commit` merely because the repository was scanned at a newer HEAD.

## Repository-owned extraction

`docs/explorer/build_explorer.py` must write `catalog/discovered.json` while its discovery
adapter has the exact parsed body. This is mandatory for shared registries where a manifest
path cannot reconstruct one artifact's body. The generic skeleton sets `_content` on every
artifact and removes that private field from the browser manifest.

Authored assessment and graph fragments remain under `data/*.json`; the bundle merges them
opaquely by artifact ID. Unknown mechanical fields are preserved.

## Update log

`catalog/update-log.jsonl` is append-only and hash-chained. An event records added, updated,
restored, and newly historical artifacts plus the verified bundle state. Repeating the same
base/head/delta does not append another event. Human `summary` text explains what changed and
why; it is not used as event identity.

If an artifact body changes but its authored assessment/graph remains accurate, publication
normally stops for stale-curation review. `--reviewed-unchanged <artifact-id>` records the
explicit decision in `curation_reviewed_unchanged`; it is an audit receipt, not a bypass for
unread content.

Planning reports coverage and stale-curation changes without publishing. Publication blocks
changed scanner coverage unless `--accept-coverage-change` records that its profiles, skips,
warnings, fallbacks, and candidate totals were reviewed. Bundle and event shapes are enforced
with stdlib validation equivalent to the checked-in JSON schemas.

Source-side publication verifies Git commits, blob hashes, and content bindings and records
the result in `verification.json`. The normal `verify` action is deliberately bundle-only:
downstream consumers need the catalog files, not a checkout or Git history.
