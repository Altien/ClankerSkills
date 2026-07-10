#!/usr/bin/env python3
"""Publish or verify the Skills Explorer's downstream catalog bundle.

The repository-local build adapter owns discovery and writes
``docs/explorer/catalog/discovered.json`` while it still has exact parsed bodies.
This tool merges that active snapshot with authored data and the previous bundle,
retaining disappeared artifacts as historical records.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import quote


SCHEMA_VERSION = "1.0"
GENERATOR_VERSION = "0.3.0"


class CatalogError(RuntimeError):
    pass


def canonical_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def read_json(path: Path, required: bool = True) -> dict:
    if not path.exists():
        if required:
            raise CatalogError(f"missing required file: {path}")
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CatalogError(f"invalid JSON in {path}: {exc}") from exc


def git(repo: Path, *args: str, required: bool = True) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True
    )
    if proc.returncode and required:
        raise CatalogError(proc.stderr.strip() or f"git {' '.join(args)} failed")
    return proc.stdout.strip() if proc.returncode == 0 else ""


def git_succeeds(repo: Path, *args: str) -> bool:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True
    ).returncode == 0


def repository_url(remote: str) -> str | None:
    remote = remote.strip()
    match = re.match(r"git@([^:]+):(.+?)(?:\.git)?$", remote)
    if match:
        return f"https://{match.group(1)}/{match.group(2).removesuffix('.git')}"
    match = re.match(r"https?://([^/]+)/(.+?)(?:\.git)?$", remote)
    if match:
        return f"https://{match.group(1)}/{match.group(2).removesuffix('.git')}"
    return None


def commit_timestamp(repo: Path, commit: str) -> str:
    return git(repo, "show", "-s", "--format=%cI", commit)


def last_content_commit(repo: Path, artifact: dict, head: str) -> str:
    explicit = artifact.get("content_commit")
    if explicit:
        return explicit
    path = artifact.get("source_path")
    if not path:
        return head
    start, end = artifact.get("line_start"), artifact.get("line_end")
    if start and end:
        value = git(repo, "log", "-1", "--format=%H", "-L", f"{start},{end}:{path}",
                    required=False)
        if value:
            return value.splitlines()[0]
    value = git(repo, "log", "-1", "--format=%H", "--", path, required=False)
    return value.splitlines()[0] if value else head


def source_blob(repo: Path, commit: str, path: str) -> bytes:
    proc = subprocess.run(
        ["git", "-C", str(repo), "show", f"{commit}:{path}"], capture_output=True
    )
    if proc.returncode:
        raise CatalogError(f"source path {path} does not exist at content commit {commit}")
    return proc.stdout


def bind_content_to_source(blob: bytes, content: str, line_start: int | None,
                           line_end: int | None) -> str:
    text = blob.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")
    if line_start:
        lines = text.splitlines(keepends=True)
        end = line_end or line_start
        text = "".join(lines[line_start - 1:end])
    normalized = content.replace("\r\n", "\n").replace("\r", "\n")
    candidates = {
        "verbatim": normalized,
        "json-string": json.dumps(normalized, ensure_ascii=False)[1:-1],
        "json-string-ascii": json.dumps(normalized, ensure_ascii=True)[1:-1],
        "csharp-verbatim": normalized.replace('"', '""'),
    }
    for mode, candidate in candidates.items():
        if candidate and candidate in text:
            return mode
    raise CatalogError(
        "pre-extracted content cannot be reproduced from its pinned source region; "
        "adapt discovery to emit exact source text or a narrower line range"
    )


def immutable_url(base_url: str | None, commit: str, path: str | None,
                  line_start: int | None, line_end: int | None) -> str | None:
    if not base_url or not path:
        return None
    url = f"{base_url}/blob/{commit}/{quote(path, safe='/')}"
    if line_start:
        url += f"#L{line_start}"
        if line_end and line_end != line_start:
            url += f"-L{line_end}"
    return url


def load_curated(explorer: Path) -> dict[str, dict]:
    merged: dict[str, dict] = {}
    for path in sorted((explorer / "data").glob("*.json")):
        fragment = read_json(path)
        for artifact_id, value in (fragment.get("artifacts") or {}).items():
            if artifact_id in merged:
                raise CatalogError(f"duplicate curated artifact id {artifact_id} ({path})")
            merged[artifact_id] = value
    return merged


def source_tree_is_clean(repo: Path, explorer: Path) -> None:
    """Allow generated Explorer edits, but require the rest of the source tree at HEAD."""
    explorer_rel = explorer.relative_to(repo).as_posix().rstrip("/")
    excluded = f":(exclude,top){explorer_rel}/**"
    if (not git_succeeds(repo, "diff", "--quiet", "--", ".", excluded)
            or not git_succeeds(repo, "diff", "--cached", "--quiet", "--", ".", excluded)):
        raise CatalogError(
            "repository source has tracked changes outside the Explorer; commit them before publishing"
        )
    untracked = git(repo, "ls-files", "--others", "--exclude-standard", required=False)
    untracked_source = [
        path for path in untracked.splitlines()
        if path != explorer_rel and not path.startswith(explorer_rel + "/")
    ]
    if untracked_source:
        raise CatalogError(
            "repository source has untracked files outside the Explorer; commit them before publishing:\n"
            + "\n".join(untracked_source)
        )


def load_inputs(explorer: Path) -> tuple[dict, dict, dict[str, dict]]:
    manifest = read_json(explorer / "explorer-manifest.json")
    discovered = read_json(explorer / "catalog" / "discovered.json")
    curated = load_curated(explorer)
    return manifest, discovered, curated


def coverage_review_view(coverage: dict) -> dict:
    embedded = coverage.get("embedded_scan") or {}
    return {
        "searched_patterns": coverage.get("searched_patterns") or [],
        "embedded_scan": {
            key: copy.deepcopy(embedded.get(key))
            for key in (
                "mode", "scanner_version", "files_scanned", "bytes_scanned", "profiles",
                "extensions", "generic_fallback_files", "skipped", "warnings", "candidates",
                "rejections",
            )
        },
        "pre_extracted_missing": (coverage.get("pre_extracted") or {}).get("missing_content_ids") or [],
        "counts_by_kind": copy.deepcopy(coverage.get("counts_by_kind") or {}),
        "counts_by_category": copy.deepcopy(coverage.get("counts_by_category") or {}),
        "total": coverage.get("total"),
    }


def assemble_bundle(explorer: Path, reviewed_unchanged: set[str] | None = None,
                    *, block_stale_curation: bool = True,
                    accept_coverage_change: bool = False,
                    block_coverage_change: bool = True) -> tuple[dict, dict]:
    explorer = explorer.resolve()
    reviewed_unchanged = reviewed_unchanged or set()
    repo = explorer.parents[1]
    manifest, discovered, curated = load_inputs(explorer)
    head = git(repo, "rev-parse", "HEAD")
    scan_commit = discovered.get("scan_commit")
    if scan_commit != head:
        raise CatalogError(
            f"discovery snapshot is for {scan_commit or 'no commit'}, but repository HEAD is {head}"
        )
    missing = discovered.get("missing_content_ids") or []
    if missing:
        raise CatalogError(
            "repo-specific discovery did not pre-extract exact content for: " + ", ".join(missing)
        )

    manifest_items = {item["id"]: item for item in manifest.get("artifacts", [])}
    discovered_items = {item["id"]: item for item in discovered.get("artifacts", [])}
    if len(manifest_items) != len(manifest.get("artifacts", [])):
        raise CatalogError("duplicate artifact ids in explorer-manifest.json")
    if set(manifest_items) != set(discovered_items):
        only_manifest = sorted(set(manifest_items) - set(discovered_items))
        only_discovered = sorted(set(discovered_items) - set(manifest_items))
        raise CatalogError(
            f"manifest/discovery parity failed; missing bodies={only_manifest}, orphan bodies={only_discovered}"
        )

    source_tree_is_clean(repo, explorer)
    previous_path = explorer / "catalog" / "catalog.bundle.json"
    if previous_path.exists():
        verify_catalog(explorer, repo=repo, verify_source=True)
    previous = read_json(previous_path, required=False)
    previous_head = previous.get("observed_at_commit")
    if previous_head and not git_succeeds(repo, "merge-base", "--is-ancestor", previous_head, head):
        raise CatalogError(
            f"previous verified commit {previous_head} is not an ancestor of HEAD {head}"
        )
    previous_items = {item["id"]: item for item in previous.get("artifacts", [])}
    remote = git(repo, "remote", "get-url", "origin", required=False)
    base_url = repository_url(remote)
    if manifest_items and not base_url:
        raise CatalogError(
            "origin must be a GitHub-style HTTPS or SSH remote so immutable source URLs can be published"
        )
    observed_at = commit_timestamp(repo, head)

    current = []
    added, updated, restored, unchanged = [], [], [], 0
    stale_curated = []
    for artifact_id in sorted(manifest_items):
        mechanical = copy.deepcopy(manifest_items[artifact_id])
        extracted = discovered_items[artifact_id]
        content = str(extracted.get("content") or "")
        content_hash = sha256_bytes(content.encode("utf-8"))
        if extracted.get("content_sha256") != content_hash:
            raise CatalogError(f"pre-extracted content hash mismatch for {artifact_id}")
        prior = previous_items.get(artifact_id)
        same_content = bool(prior and prior.get("content_sha256") == content_hash)
        prior_source = prior.get("source", {}) if prior else {}
        current_path = extracted.get("source_path") or mechanical.get("source_path")
        current_start = extracted.get("line_start") or mechanical.get("line_start")
        current_end = extracted.get("line_end") or mechanical.get("line_end")
        content_commit = prior_source["content_commit"] if same_content else last_content_commit(repo, extracted, head)
        provenance_path = prior_source.get("path") if same_content else current_path
        provenance_start = prior_source.get("line_start") if same_content else current_start
        provenance_end = prior_source.get("line_end") if same_content else current_end
        source = {
            "path": provenance_path,
            "line_start": provenance_start,
            "line_end": provenance_end,
            "observed_path": current_path,
            "observed_line_start": current_start,
            "observed_line_end": current_end,
            "content_commit": content_commit,
            "first_seen_commit": (
                prior.get("source", {}).get("first_seen_commit") if prior else head
            ),
            "last_seen_commit": head,
            "observed_at_commit": head,
            "removed_at_commit": None,
        }
        source["immutable_url"] = immutable_url(
            base_url, content_commit, source["path"], source["line_start"], source["line_end"]
        )
        if not source["path"] or not source["immutable_url"]:
            raise CatalogError(f"artifact {artifact_id} has no immutable source location")
        blob = source_blob(repo, content_commit, source["path"])
        source["source_blob_sha256"] = sha256_bytes(blob)
        source["content_binding"] = bind_content_to_source(
            blob, content, source["line_start"], source["line_end"]
        )
        supplied_curated = curated.get(artifact_id)
        current_curated = copy.deepcopy(
            supplied_curated if supplied_curated is not None
            else (prior.get("curated") if prior and prior.get("lifecycle", {}).get("status") == "historical" else {})
        )
        if (prior and not same_content and prior.get("curated")
                and current_curated == prior.get("curated")
                and artifact_id not in reviewed_unchanged):
            stale_curated.append(artifact_id)
        lifecycle = {"status": "active"}
        if prior and prior.get("lifecycle", {}).get("status") == "historical":
            lifecycle["restored_at_commit"] = head
            restored.append({"id": artifact_id, "hash": content_hash})
        elif not prior:
            added.append({"id": artifact_id, "hash": content_hash})
        elif not same_content:
            updated.append({"id": artifact_id, "before": prior["content_sha256"],
                            "after": content_hash})
        else:
            unchanged += 1
        current.append({
            "id": artifact_id,
            "title": mechanical.get("title"),
            "kind": mechanical.get("kind"),
            "category": mechanical.get("category"),
            "content": content,
            "content_sha256": content_hash,
            "source": source,
            "lifecycle": lifecycle,
            "mechanical": mechanical,
            "curated": current_curated,
        })

    historical = []
    for artifact_id in sorted(set(previous_items) - set(manifest_items)):
        item = copy.deepcopy(previous_items[artifact_id])
        lifecycle = item.setdefault("lifecycle", {})
        if lifecycle.get("status") != "historical":
            lifecycle["status"] = "historical"
            item.setdefault("source", {})["removed_at_commit"] = head
            historical.append({"id": artifact_id, "last_hash": item["content_sha256"]})
        current.append(item)

    if stale_curated and block_stale_curation:
        raise CatalogError(
            "changed artifacts retain unchanged authored curation; review/update: "
            + ", ".join(stale_curated)
        )

    bundle = {
        "schema_version": SCHEMA_VERSION,
        "repository": {
            "name": manifest.get("repo") or repo.name,
            "url": base_url,
            "default_branch": git(repo, "symbolic-ref", "--short", "refs/remotes/origin/HEAD",
                                  required=False).removeprefix("origin/") or None,
        },
        "observed_at_commit": head,
        "observed_at": observed_at,
        "generator": {"name": "skills-explorer", "version": GENERATOR_VERSION},
        "coverage": copy.deepcopy(manifest.get("coverage") or {}),
        "artifacts": sorted(current, key=lambda item: item["id"]),
    }
    previous_coverage = coverage_review_view(previous.get("coverage") or {}) if previous else None
    current_coverage = coverage_review_view(bundle["coverage"])
    coverage_changed = previous_coverage is not None and previous_coverage != current_coverage
    if coverage_changed and block_coverage_change and not accept_coverage_change:
        raise CatalogError(
            "scan coverage changed; review the plan and republish with --accept-coverage-change"
        )
    previous_bundle_hash = sha256_bytes(previous_path.read_bytes()) if previous_path.exists() else None
    candidate_bundle_hash = sha256_bytes(canonical_bytes(bundle))
    changes = {
        "base_commit": previous.get("observed_at_commit") if previous else None,
        "head_commit": head,
        "added": added,
        "updated": updated,
        "restored": restored,
        "historical": historical,
        "unchanged_count": unchanged,
        "curation_reviewed_unchanged": sorted(reviewed_unchanged),
        "stale_curated": sorted(stale_curated),
        "coverage_changed": coverage_changed,
        "coverage_change_accepted": bool(coverage_changed and accept_coverage_change),
        "coverage_before_sha256": (
            sha256_bytes(canonical_bytes(previous_coverage)) if previous_coverage is not None else None
        ),
        "coverage_after_sha256": sha256_bytes(canonical_bytes(current_coverage)),
        "bundle_before_sha256": previous_bundle_hash,
        "bundle_after_sha256": candidate_bundle_hash,
    }
    return bundle, changes


def run_verification(repo: Path, command: str) -> dict:
    proc = subprocess.run(command, cwd=repo, shell=True, text=True, capture_output=True)
    if proc.returncode:
        raise CatalogError(
            f"Explorer verification failed ({command}):\n{proc.stdout}\n{proc.stderr}".strip()
        )
    return {"command": command, "exit_code": 0, "stdout_sha256": sha256_bytes(proc.stdout.encode())}


def read_log(path: Path) -> list[dict]:
    if not path.exists():
        return []
    events = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            events.append(json.loads(line))
        except ValueError as exc:
            raise CatalogError(f"invalid update log line {number}: {exc}") from exc
    return events


def event_identity(changes: dict) -> str:
    identity = {key: changes[key] for key in (
        "base_commit", "head_commit", "added", "updated", "restored", "historical",
        "curation_reviewed_unchanged", "coverage_changed", "coverage_change_accepted",
        "coverage_before_sha256", "coverage_after_sha256", "bundle_before_sha256",
        "bundle_after_sha256",
    )}
    return sha256_bytes(canonical_bytes(identity))


def append_event(path: Path, changes: dict, summary: str, verification_hash: str) -> dict:
    events = read_log(path)
    event_id = event_identity(changes)
    if events and events[-1].get("event_id") == event_id:
        return events[-1]
    event = {
        "schema_version": SCHEMA_VERSION,
        "sequence": len(events) + 1,
        "previous_event_sha256": events[-1].get("event_sha256") if events else None,
        "event_id": event_id,
        **changes,
        "generator_version": GENERATOR_VERSION,
        "summary": summary.strip(),
        "verification_sha256": verification_hash,
    }
    event["event_sha256"] = sha256_bytes(canonical_bytes(event))
    with path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
    return event


def validate_bundle_shape(bundle: dict) -> None:
    required = {"schema_version", "repository", "observed_at_commit", "generator", "coverage", "artifacts"}
    if not isinstance(bundle, dict) or not required.issubset(bundle) or bundle.get("schema_version") != SCHEMA_VERSION:
        raise CatalogError("catalog bundle does not satisfy catalog-bundle.schema.json")
    repository = bundle.get("repository")
    if not isinstance(repository, dict) or not isinstance(repository.get("name"), str):
        raise CatalogError("catalog bundle has invalid repository metadata")
    for key in ("url", "default_branch"):
        if repository.get(key) is not None and not isinstance(repository.get(key), str):
            raise CatalogError(f"catalog bundle repository has invalid {key}")
    if bundle.get("observed_at") is not None and not isinstance(bundle.get("observed_at"), str):
        raise CatalogError("catalog bundle has invalid observed_at")
    if not isinstance(bundle.get("generator"), dict) or not isinstance(bundle.get("coverage"), dict):
        raise CatalogError("catalog bundle has invalid generator or coverage metadata")
    if not re.fullmatch(r"[0-9a-f]{40,64}", str(bundle.get("observed_at_commit") or "")):
        raise CatalogError("catalog bundle has an invalid observed_at_commit")
    if not isinstance(bundle.get("artifacts"), list):
        raise CatalogError("catalog bundle artifacts must be an array")
    for item in bundle["artifacts"]:
        if not isinstance(item, dict) or not {"id", "kind", "content", "content_sha256", "source", "lifecycle", "mechanical", "curated"}.issubset(item):
            raise CatalogError("catalog artifact does not satisfy catalog-bundle.schema.json")
        if not isinstance(item["id"], str) or not item["id"] or not isinstance(item["content"], str):
            raise CatalogError("catalog artifact has an invalid id or content")
        if item["kind"] is not None and not isinstance(item["kind"], str):
            raise CatalogError(f"catalog artifact {item['id']} has invalid kind")
        if not re.fullmatch(r"[0-9a-f]{64}", str(item.get("content_sha256") or "")):
            raise CatalogError(f"catalog artifact {item['id']} has invalid content hash")
        if not isinstance(item["mechanical"], dict) or not isinstance(item["curated"], dict):
            raise CatalogError(f"catalog artifact {item.get('id')} has invalid metadata objects")
        if not isinstance(item["source"], dict) or not isinstance(item["lifecycle"], dict):
            raise CatalogError(f"catalog artifact {item['id']} has invalid source or lifecycle")
        required_source = {
            "path", "content_commit", "last_seen_commit", "observed_at_commit",
            "source_blob_sha256", "content_binding", "immutable_url",
        }
        if not required_source.issubset(item["source"]):
            raise CatalogError(f"catalog artifact {item['id']} has incomplete source provenance")
        if not isinstance(item["source"].get("immutable_url"), str):
            raise CatalogError(f"catalog artifact {item['id']} has invalid immutable_url")
        for key in ("content_commit", "last_seen_commit", "observed_at_commit"):
            if not re.fullmatch(r"[0-9a-f]{40,64}", str(item["source"].get(key) or "")):
                raise CatalogError(f"catalog artifact {item['id']} has invalid {key}")
        if item["lifecycle"].get("status") not in {"active", "historical"}:
            raise CatalogError(f"catalog artifact {item['id']} has invalid lifecycle status")


def validate_event_shape(event: dict) -> None:
    required = {
        "schema_version", "sequence", "event_id", "event_sha256", "head_commit",
        "added", "updated", "restored", "historical", "unchanged_count", "summary",
        "verification_sha256", "curation_reviewed_unchanged", "coverage_changed",
        "coverage_change_accepted", "coverage_after_sha256", "bundle_after_sha256",
        "stale_curated",
    }
    if not isinstance(event, dict) or not required.issubset(event) or event.get("schema_version") != SCHEMA_VERSION:
        raise CatalogError("update event does not satisfy update-event.schema.json")
    for key in ("event_id", "event_sha256", "verification_sha256"):
        if not re.fullmatch(r"[0-9a-f]{64}", str(event.get(key) or "")):
            raise CatalogError(f"update event has invalid {key}")
    if not isinstance(event.get("sequence"), int) or event["sequence"] < 1:
        raise CatalogError("update event has invalid sequence")
    if not isinstance(event.get("summary"), str) or not event["summary"].strip():
        raise CatalogError("update event has no summary")
    if not re.fullmatch(r"[0-9a-f]{40,64}", str(event.get("head_commit") or "")):
        raise CatalogError("update event has invalid head_commit")
    for key in ("added", "updated", "restored", "historical", "curation_reviewed_unchanged", "stale_curated"):
        if not isinstance(event.get(key), list):
            raise CatalogError(f"update event has invalid {key}")
    if any(not isinstance(value, str) for value in event["stale_curated"]):
        raise CatalogError("update event has invalid stale_curated")
    if event.get("base_commit") is not None and not isinstance(event.get("base_commit"), str):
        raise CatalogError("update event has invalid base_commit")
    if not isinstance(event.get("unchanged_count"), int) or event["unchanged_count"] < 0:
        raise CatalogError("update event has invalid unchanged_count")
    for key in ("coverage_changed", "coverage_change_accepted"):
        if not isinstance(event.get(key), bool):
            raise CatalogError(f"update event has invalid {key}")
    reviewed = event.get("curation_reviewed_unchanged")
    if any(not isinstance(value, str) for value in reviewed) or len(reviewed) != len(set(reviewed)):
        raise CatalogError("update event has invalid curation_reviewed_unchanged")
    for key in ("coverage_after_sha256", "bundle_after_sha256"):
        if not re.fullmatch(r"[0-9a-f]{64}", str(event.get(key) or "")):
            raise CatalogError(f"update event has invalid {key}")
    for key in ("coverage_before_sha256", "bundle_before_sha256", "previous_event_sha256"):
        value = event.get(key)
        if value is not None and not re.fullmatch(r"[0-9a-f]{64}", str(value)):
            raise CatalogError(f"update event has invalid {key}")


def verify_catalog(explorer: Path, *, repo: Path | None = None,
                   verify_source: bool = False) -> None:
    catalog = explorer / "catalog"
    if verify_source:
        repo = repo or explorer.resolve().parents[1]
    bundle_path = catalog / "catalog.bundle.json"
    bundle_bytes = bundle_path.read_bytes()
    bundle_hash = sha256_bytes(bundle_bytes)
    expected = (catalog / "catalog.bundle.sha256").read_text(encoding="ascii").strip()
    if bundle_hash != expected:
        raise CatalogError("catalog.bundle.sha256 does not match catalog.bundle.json")
    bundle = json.loads(bundle_bytes)
    validate_bundle_shape(bundle)
    ids = set()
    for item in bundle.get("artifacts", []):
        if item["id"] in ids:
            raise CatalogError(f"duplicate bundle artifact id {item['id']}")
        ids.add(item["id"])
        actual = sha256_bytes(str(item.get("content") or "").encode("utf-8"))
        if actual != item.get("content_sha256"):
            raise CatalogError(f"content hash mismatch for {item['id']}")
        if item.get("lifecycle", {}).get("status") not in {"active", "historical"}:
            raise CatalogError(f"invalid lifecycle status for {item['id']}")
        source = item.get("source") or {}
        url, commit = source.get("immutable_url"), source.get("content_commit")
        if not isinstance(url, str) or not url or not commit or commit not in url:
            raise CatalogError(f"immutable URL is not pinned to content commit for {item['id']}")
        path, blob_hash = source.get("path"), source.get("source_blob_sha256")
        if not path or not re.fullmatch(r"[0-9a-f]{64}", str(blob_hash or "")):
            raise CatalogError(f"source blob provenance is missing for {item['id']}")
        if source.get("content_binding") not in {
            "verbatim", "json-string", "json-string-ascii", "csharp-verbatim"
        }:
            raise CatalogError(f"source content binding is missing for {item['id']}")
        if verify_source:
            assert repo is not None
            blob = source_blob(repo, commit, path)
            if sha256_bytes(blob) != blob_hash:
                raise CatalogError(f"source blob provenance mismatch for {item['id']}")
            binding = bind_content_to_source(
                blob, item["content"], source.get("line_start"), source.get("line_end")
            )
            if binding != source["content_binding"]:
                raise CatalogError(f"source content binding mismatch for {item['id']}")

    previous_hash = None
    for expected_sequence, event in enumerate(read_log(catalog / "update-log.jsonl"), 1):
        validate_event_shape(event)
        if event.get("sequence") != expected_sequence:
            raise CatalogError("update log sequence is broken")
        if event.get("previous_event_sha256") != previous_hash:
            raise CatalogError("update log hash chain is broken")
        claimed = event.get("event_sha256")
        unsigned = dict(event)
        unsigned.pop("event_sha256", None)
        if claimed != sha256_bytes(canonical_bytes(unsigned)):
            raise CatalogError(f"update log event {expected_sequence} hash mismatch")
        previous_hash = claimed

    verification = read_json(catalog / "verification.json")
    if verification.get("status") != "verified" or verification.get("bundle_sha256") != bundle_hash:
        raise CatalogError("verification.json does not verify the current bundle")
    if verification.get("source_provenance", {}).get("status") != "verified":
        raise CatalogError("verification.json has no successful source-provenance receipt")
    verification_hash = sha256_bytes(canonical_bytes(verification))
    events = read_log(catalog / "update-log.jsonl")
    if not events or events[-1].get("verification_sha256") != verification_hash:
        raise CatalogError("latest update event does not reference current verification.json")
    state = read_json(catalog / "state.json")
    if state.get("bundle_sha256") != bundle_hash or state.get("last_event_sha256") != previous_hash:
        raise CatalogError("state.json does not match bundle/log state")


def install_staged_catalog(staged: Path, catalog: Path, names: list[str]) -> None:
    backups = {name: (catalog / name).read_bytes() if (catalog / name).exists() else None
               for name in names}
    try:
        for name in names:
            os.replace(staged / name, catalog / name)
    except BaseException:
        for name, content in backups.items():
            target = catalog / name
            if content is None:
                target.unlink(missing_ok=True)
            else:
                with tempfile.NamedTemporaryFile(dir=catalog, delete=False) as fh:
                    fh.write(content)
                    replacement = Path(fh.name)
                os.replace(replacement, target)
        raise


def publish(explorer: Path, summary: str, verification_command: str,
            reviewed_unchanged: set[str] | None = None,
            accept_coverage_change: bool = False) -> dict:
    if not summary.strip():
        raise CatalogError("--summary is required and must explain what changed and why")
    explorer = explorer.resolve()
    repo = explorer.parents[1]
    bundle, changes = assemble_bundle(
        explorer, reviewed_unchanged, accept_coverage_change=accept_coverage_change
    )
    if changes["bundle_before_sha256"] == changes["bundle_after_sha256"]:
        verify_catalog(explorer, repo=repo, verify_source=True)
        return changes
    verification_run = run_verification(repo, verification_command)
    catalog = explorer / "catalog"
    catalog.mkdir(parents=True, exist_ok=True)
    bundle_bytes = canonical_bytes(bundle)
    bundle_hash = sha256_bytes(bundle_bytes)
    verification = {
        "schema_version": SCHEMA_VERSION,
        "status": "verified",
        "verified_at": bundle["observed_at"],
        "observed_at_commit": bundle["observed_at_commit"],
        "bundle_sha256": bundle_hash,
        "source_provenance": {
            "status": "verified",
            "artifact_count": len(bundle["artifacts"]),
            "verified_at_commit": bundle["observed_at_commit"],
        },
        **verification_run,
    }
    verification_bytes = canonical_bytes(verification)
    verification_hash = sha256_bytes(verification_bytes)

    names = [
        "catalog.bundle.json", "catalog.bundle.sha256", "verification.json",
        "update-log.jsonl", "state.json",
    ]
    with tempfile.TemporaryDirectory(prefix=".catalog-stage-", dir=explorer) as temp_dir:
        stage_explorer = Path(temp_dir) / "explorer"
        staged = stage_explorer / "catalog"
        staged.mkdir(parents=True)
        (staged / "catalog.bundle.json").write_bytes(bundle_bytes)
        (staged / "catalog.bundle.sha256").write_text(bundle_hash + "\n", encoding="ascii")
        (staged / "verification.json").write_bytes(verification_bytes)
        old_log = catalog / "update-log.jsonl"
        if old_log.exists():
            (staged / "update-log.jsonl").write_bytes(old_log.read_bytes())
        event = append_event(staged / "update-log.jsonl", changes, summary, verification_hash)
        state = {
            "schema_version": SCHEMA_VERSION,
            "last_verified_head": bundle["observed_at_commit"],
            "bundle_sha256": bundle_hash,
            "last_event_sha256": event["event_sha256"],
            "sequence": event["sequence"],
            "generator_version": GENERATOR_VERSION,
        }
        (staged / "state.json").write_bytes(canonical_bytes(state))
        verify_catalog(stage_explorer, repo=repo, verify_source=True)
        install_staged_catalog(staged, catalog, names)
    verify_catalog(explorer, repo=repo, verify_source=True)
    return changes


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish/verify a pre-extracted Explorer catalog")
    parser.add_argument("action", choices=("plan", "publish", "verify"))
    parser.add_argument("--explorer", type=Path, default=Path("docs/explorer"))
    parser.add_argument("--summary", default="")
    parser.add_argument("--verification-command", default="node docs/explorer/verify.cjs")
    parser.add_argument(
        "--reviewed-unchanged", action="append", default=[], metavar="ARTIFACT_ID",
        help="record that unchanged curation was reviewed and remains accurate after content changed",
    )
    parser.add_argument(
        "--accept-coverage-change", action="store_true",
        help="record that the reported scanner coverage delta was reviewed and accepted",
    )
    args = parser.parse_args()
    try:
        if args.action == "verify":
            verify_catalog(args.explorer.resolve())
            print("catalog bundle: verified")
            return 0
        if args.action == "plan":
            _bundle, changes = assemble_bundle(
                args.explorer, set(args.reviewed_unchanged),
                block_stale_curation=False, block_coverage_change=False,
            )
            print(json.dumps(changes, indent=2, ensure_ascii=False, sort_keys=True))
            return 0
        changes = publish(
            args.explorer, args.summary, args.verification_command,
            set(args.reviewed_unchanged), args.accept_coverage_change,
        )
        print(json.dumps(changes, indent=2, ensure_ascii=False, sort_keys=True))
        return 0
    except (CatalogError, OSError, ValueError, KeyError) as exc:
        print(f"catalog bundle error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
