"""Re-probe the complete NodeLife pool every scheduled cycle."""
from __future__ import annotations

import concurrent.futures
import json
import os
import sys
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
USER_AGENT = "NodeLife/0.3 (+https://github.com/ccvvv/NodeLife)"


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
    """Load last passing pool; an intentionally empty published pool is valid."""
    if not path.exists():
        return []
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or not isinstance(document.get("proxies"), list):
        raise ValueError("previous NodeLife output must contain a proxies list")
    proxies = document["proxies"]
    if not proxies:
        return []
    return extract_proxies(document, source="previous NodeLife output")


def render_subscription(proxies: list[dict[str, Any]]) -> str:
    """Render exactly this cycle's passing nodes, including a valid empty result."""
    return yaml.safe_dump({"proxies": proxies}, allow_unicode=True, sort_keys=False, default_flow_style=False)


def load_queue_state(path: Path) -> dict[str, Any]:
    """Load only the historical-release cursor; failed candidates are never persisted."""
    if not path.exists():
        return {"schema_version": 2, "last_processed_commit": None}
    state = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(state, dict) or state.get("schema_version") not in (1, 2):
        raise ValueError("queue state has an unsupported schema")
    cursor = state.get("last_processed_commit")
    if cursor is not None and (
        not isinstance(cursor, str) or len(cursor) != 40
        or any(char not in "0123456789abcdef" for char in cursor.lower())
    ):
        raise ValueError("queue state commit cursor is invalid")
    # Migrate v1 by deliberately discarding its old pending/failure queue.
    return {"schema_version": 2, "last_processed_commit": cursor}


def save_queue_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    clean = {"schema_version": 2, "last_processed_commit": state.get("last_processed_commit")}
    temporary.write_text(json.dumps(clean, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def fetch_upstream_snapshots(
    last_processed_commit: str | None, *, session: Any = requests,
) -> tuple[list[dict[str, Any]], str | None]:
    """Read every final/latest.yaml revision after the saved cursor, oldest first."""
    commit_shas: list[str] = []
    cursor_found = last_processed_commit is None
    page = 1
    while True:
        headers = {"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"}
        token = os.environ.get("NODELIFE_GITHUB_TOKEN")
        if token:
            headers["Authorization"] = "Bearer " + token
        response = session.get(
            UPSTREAM_COMMITS_URL,
            params={"path": "final/latest.yaml", "sha": UPSTREAM_BRANCH, "per_page": 100, "page": page},
            headers=headers, timeout=30,
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
        raise RuntimeError("saved history cursor was not found; refusing to skip releases")

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


def collect_cycle_candidates(
    previous: list[dict[str, Any]], snapshots: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Union previous passing nodes and every newly discovered historical snapshot."""
    historical: list[dict[str, Any]] = []
    for snapshot in snapshots:
        historical.extend(snapshot["proxies"])
    return merge_proxies(previous, historical)


def atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    queue = load_queue_state(QUEUE_STATE_PATH)
    previous = load_previous_output(OUTPUT_PATH)

    # Fetch and validate upstream history before probing or changing published data.
    snapshots, newest_cursor = fetch_upstream_snapshots(queue.get("last_processed_commit"))
    candidates = collect_cycle_candidates(previous, snapshots)
    print(
        f"CYCLE_POOL previous_passed={len(previous)} historical_releases={len(snapshots)} "
        f"candidates_deduplicated={len(candidates)}",
        flush=True,
    )

    # Every candidate is tested again on every cycle. Failed nodes are not retained.
    passing = filter_passing(candidates, concurrency=2, batch_size=30) if candidates else []
    atomic_write_text(OUTPUT_PATH, render_subscription(passing))
    print(
        f"PUBLISH_READY tested={len(candidates)} passed={len(passing)} "
        f"discarded={len(candidates)-len(passing)} output=data/latest.yaml",
        flush=True,
    )

    # Advance history cursor only after the complete cycle output was safely written.
    if newest_cursor != queue.get("last_processed_commit") or not QUEUE_STATE_PATH.exists():
        save_queue_state(QUEUE_STATE_PATH, {"last_processed_commit": newest_cursor})
        print(f"HISTORY_CURSOR_SAVED cursor={(newest_cursor or 'none')[:12]}", flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        detail = f" status={error.response.status_code} url={error.response.url}" if isinstance(error, requests.HTTPError) and error.response is not None else ""
        print(f"NODELIFE_CYCLE_FAILED error_type={type(error).__name__}{detail}", file=sys.stderr, flush=True)
        raise SystemExit(1)
