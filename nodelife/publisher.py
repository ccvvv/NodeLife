"""Re-probe the complete NodeLife pool every scheduled cycle."""
from __future__ import annotations

import concurrent.futures
import sys
from pathlib import Path
from typing import Any

import requests
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nodelife.identity import extract_proxies, merge_proxies
from nodelife.probe import probe_one_detailed

UPSTREAM_REPOSITORY = "ccvvv/AutoSubHub"
UPSTREAM_BRANCH = "published-subscriptions"
UPSTREAM_RAW_URL = f"https://raw.githubusercontent.com/{UPSTREAM_REPOSITORY}"
TARGETS = ["https://www.google.com/generate_204", "https://www.cloudflare.com/cdn-cgi/trace"]
ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = ROOT / "data" / "latest.yaml"
USER_AGENT = "NodeLife/0.4 (+https://github.com/ccvvv/NodeLife)"


def filter_passing(
    proxies: list[dict[str, Any]], *, mihomo_binary: str = "mihomo",
    concurrency: int = 2, startup_timeout: float = 8,
    request_timeout: float = 10, batch_size: int = 30,
) -> list[dict[str, Any]]:
    """Return this cycle's passing proxies in source order."""
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
    """Load the previous passing pool; an intentionally empty pool is valid."""
    if not path.exists():
        return []
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or not isinstance(document.get("proxies"), list):
        raise ValueError("previous NodeLife output must contain a proxies list")
    if not document["proxies"]:
        return []
    return extract_proxies(document, source="previous NodeLife output")


def render_subscription(proxies: list[dict[str, Any]]) -> str:
    """Render exactly this cycle's passing nodes; an empty result is valid."""
    return yaml.safe_dump(
        {"proxies": proxies}, allow_unicode=True, sort_keys=False, default_flow_style=False
    )


def fetch_upstream_subscriptions(*, session: Any = requests) -> list[dict[str, Any]]:
    """Fetch only AutoSubHub's latest published subscription over HTTPS."""
    filename = "latest.yaml"
    url = f"{UPSTREAM_RAW_URL}/{UPSTREAM_BRANCH}/final/{filename}"
    response = session.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
    response.raise_for_status()
    proxies = extract_proxies(
        yaml.safe_load(response.text),
        source=f"AutoSubHub final/{filename}",
        allow_empty=True,
    )
    return [{"source": filename, "proxies": proxies}]


def collect_cycle_candidates(
    previous: list[dict[str, Any]], snapshots: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Union latest subscription snapshot and last cycle's passing pool."""
    upstream: list[dict[str, Any]] = []
    for snapshot in snapshots:
        upstream.extend(snapshot["proxies"])
    return merge_proxies(upstream, previous)


def atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    previous = load_previous_output(OUTPUT_PATH)

    # Candidate input is subscription-only: no Git history/API calls to AutoSubHub.
    snapshots = fetch_upstream_subscriptions()
    candidates = collect_cycle_candidates(previous, snapshots)
    counts = " ".join(
        f"{item['source'].replace('.yaml', '')}={len(item['proxies'])}"
        for item in snapshots
    )
    print(
        f"CYCLE_POOL {counts} previous_passed={len(previous)} "
        f"candidates_deduplicated={len(candidates)}",
        flush=True,
    )

    # Re-test the complete merged pool every cycle; publish only this cycle's passes.
    passing = filter_passing(candidates, concurrency=2, batch_size=30) if candidates else []
    atomic_write_text(OUTPUT_PATH, render_subscription(passing))
    print(
        f"PUBLISH_READY tested={len(candidates)} passed={len(passing)} "
        f"discarded={len(candidates)-len(passing)} output=data/latest.yaml",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        detail = f" status={error.response.status_code} url={error.response.url}" if isinstance(error, requests.HTTPError) and error.response is not None else ""
        print(f"NODELIFE_CYCLE_FAILED error_type={type(error).__name__}{detail}", file=sys.stderr, flush=True)
        raise SystemExit(1)
