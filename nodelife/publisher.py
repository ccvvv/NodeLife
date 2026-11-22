"""Accumulate immutable AutoSubHub final releases and probe each unique proxy once per queue pass."""
from __future__ import annotations

import concurrent.futures
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nodelife.identity import canonical_fingerprint, extract_proxies, merge_proxies
from nodelife.probe import probe_one_detailed

UPSTREAM_REPOSITORY = "ccvvv/AutoSubHub"
UPSTREAM_BRANCH = "published-subscriptions"
UPSTREAM_COMMITS_URL = f"https://api.github.com/repos/{UPSTREAM_REPOSITORY}/commits"
UPSTREAM_RAW_URL = f"https://raw.githubusercontent.com/{UPSTREAM_REPOSITORY}"
TARGETS = ["https://www.google.com/generate_204", "https://www.cloudflare.com/cdn-cgi/trace"]
ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = ROOT / "data" / "latest.yaml"
QUEUE_STATE_PATH = ROOT / "data" / "queue_state.json"
USER_AGENT = "NodeLife/0.2 (+https://github.com/ccvvv/NodeLife)"


def filter_passing(
    proxies: list[dict[str, Any]], *, mihomo_binary: str = "mihomo",
    concurrency: int = 2, startup_timeout: float = 8,
    request_timeout: float = 10, batch_size: int = 30,
) -> list[dict[str, Any]]:
    """Return passing proxies in source order; never log proxy identity."""
    if concurrency < 1 or concurrency > 20:
        raise ValueError("concurrency must be between 1 and 20")
    if batch_size < 1 or batch_size > 100:
        raise ValueError("batch_size must be between 1 and 100")
    passed_by_index: dict[int, bool] = {}
    categories: dict[str, int] = {}
    total = len(proxies)
    for start in range(0, total, batch_size):
        batch = list(enumerate(proxies[start:start + batch_size], start=start))
        with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = {
                executor.submit(
                    probe_one_detailed, proxy, mihomo_binary=mihomo_binary,
                    targets=TARGETS, startup_timeout=startup_timeout,
                    request_timeout=request_timeout,
                ): index for index, proxy in batch
            }
            for future in concurrent.futures.as_completed(futures):
                index = futures[future]
                try:
                    category = future.result()
                except Exception:
                    category = "unexpected_probe_error"
                passed_by_index[index] = category == "passed"
                categories[category] = categories.get(category, 0) + 1
        done = min(start + len(batch), total)
        passed_count = sum(passed_by_index.values())
        print(f"PROGRESS done={done}/{total} passed={passed_count} not_passed={done-passed_count}", flush=True)
    print(f"PROBE_SUMMARY total={total} categories={dict(sorted(categories.items()))}", flush=True)
    return [proxy for index, proxy in enumerate(proxies) if passed_by_index.get(index, False)]


def load_previous_output(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return extract_proxies(yaml.safe_load(path.read_text(encoding="utf-8")), source="previous NodeLife output")


def render_subscription(proxies: list[dict[str, Any]]) -> str:
    if not proxies:
        raise ValueError("refusing to render an empty subscription")
    return yaml.safe_dump({"proxies": proxies}, allow_unicode=True, sort_keys=False, default_flow_style=False)


def load_queue_state(path: Path) -> dict[str, Any]:
    """Load the durable upstream cursor and pending unique proxy configurations."""
    if not path.exists():
        return {"schema_version": 1, "last_processed_commit": None, "pending": {}}
    state = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(state, dict) or state.get("schema_version") != 1 or not isinstance(state.get("pending"), dict):
        raise ValueError("queue state has an unsupported schema")
    cursor = state.get("last_processed_commit")
    if cursor is not None and (
        not isinstance(cursor, str) or len(cursor) != 40
        or any(char not in "0123456789abcdef" for char in cursor.lower())
    ):
        raise ValueError("queue state commit cursor is invalid")
    for fingerprint, proxy in state["pending"].items():
        if not isinstance(proxy, dict) or canonical_fingerprint(proxy) != fingerprint:
            raise ValueError("queue state contains an invalid pending proxy")
    return state


def save_queue_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def fetch_upstream_snapshots(
    last_processed_commit: str | None, *, session: Any = requests,
) -> tuple[list[dict[str, Any]], str | None]:
    """Read every final/latest.yaml revision after the saved cursor, oldest first."""
    commit_shas: list[str] = []
    cursor_found = last_processed_commit is None
    page = 1
    while True:
        response = session.get(
            UPSTREAM_COMMITS_URL,
            params={"path": "final/latest.yaml", "sha": UPSTREAM_BRANCH, "per_page": 100, "page": page},
            headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"},
            timeout=30,
        )
        response.raise_for_status()
        entries = response.json()
        if not isinstance(entries, list):
            raise RuntimeError("upstream commit history response is malformed")
        stop = False
        for entry in entries:
            sha = entry.get("sha") if isinstance(entry, dict) else None
            if not isinstance(sha, str) or len(sha) != 40:
                raise RuntimeError("upstream commit history contains an invalid SHA")
            if last_processed_commit and sha == last_processed_commit:
                cursor_found, stop = True, True
                break
            commit_shas.append(sha)
        if stop or len(entries) < 100:
            break
        page += 1
        if page > 50:
            raise RuntimeError("upstream history exceeded the safe pagination limit")
    if not cursor_found:
        raise RuntimeError("saved queue cursor was not found in upstream history; refusing to skip releases")

    commit_shas.reverse()
    snapshots: list[dict[str, Any]] = []
    for sha in commit_shas:
        response = session.get(
            f"{UPSTREAM_RAW_URL}/{sha}/final/latest.yaml",
            headers={"User-Agent": USER_AGENT}, timeout=30,
        )
        response.raise_for_status()
        proxies = extract_proxies(yaml.safe_load(response.text), source=f"AutoSubHub final snapshot {sha[:12]}")
        snapshots.append({"commit": sha, "proxies": proxies})
    newest_cursor = commit_shas[-1] if commit_shas else last_processed_commit
    return snapshots, newest_cursor


def add_snapshots_to_pending(
    snapshots: list[dict[str, Any]],
    pending: dict[str, dict[str, Any]],
    already_published: set[str],
) -> int:
    """Merge release batches into one fingerprint-deduplicated queue."""
    added = 0
    for snapshot in snapshots:
        for proxy in snapshot["proxies"]:
            fingerprint = canonical_fingerprint(proxy)
            if fingerprint in already_published or fingerprint in pending:
                continue
            pending[fingerprint] = proxy
            added += 1
    return added


def atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    queue = load_queue_state(QUEUE_STATE_PATH)
    previous = load_previous_output(OUTPUT_PATH)
    previous_fingerprints = {canonical_fingerprint(proxy) for proxy in previous}
    snapshots, newest_cursor = fetch_upstream_snapshots(queue.get("last_processed_commit"))

    pending = dict(queue["pending"])
    added = add_snapshots_to_pending(snapshots, pending, previous_fingerprints)
    print(
        f"QUEUE_SUMMARY new_releases={len(snapshots)} new_unique_nodes={added} "
        f"pending_before_probe={len(pending)} already_published={len(previous)}",
        flush=True,
    )

    passing: list[dict[str, Any]] = []
    if pending:
        passing = filter_passing(list(pending.values()), concurrency=2, batch_size=30)
        for proxy in passing:
            pending.pop(canonical_fingerprint(proxy), None)

    if passing:
        published = merge_proxies(passing, previous)
        atomic_write_text(OUTPUT_PATH, render_subscription(published))
        print(f"PUBLISH_READY new_passed={len(passing)} total_published={len(published)} output=data/latest.yaml", flush=True)
    elif previous:
        print(f"NO_NEW_PASSES retained_existing={len(previous)} pending_for_retry={len(pending)}", flush=True)
    elif pending:
        print(f"NO_PASSES_YET pending_for_retry={len(pending)}; no empty subscription was published", flush=True)

    # Save the subscription first. If the cursor write fails, a retry safely
    # re-collects releases and skips identities already present in latest.yaml.
    changed = newest_cursor != queue.get("last_processed_commit") or pending != queue["pending"]
    if changed:
        queue["last_processed_commit"] = newest_cursor
        queue["pending"] = pending
        queue["updated_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        queue["last_discovered_release_count"] = len(snapshots)
        save_queue_state(QUEUE_STATE_PATH, queue)
        print(f"QUEUE_SAVED cursor={(newest_cursor or 'none')[:12]} pending={len(pending)}", flush=True)
    else:
        print(f"QUEUE_UNCHANGED pending={len(pending)}", flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"NODELIFE_QUEUE_FAILED error_type={type(error).__name__}", file=sys.stderr, flush=True)
        raise SystemExit(1)
