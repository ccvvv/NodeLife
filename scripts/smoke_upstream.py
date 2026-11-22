"""Run a diagnostic HTTPS recheck without publishing node data."""
from __future__ import annotations

import concurrent.futures
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import requests
import yaml

from nodelife.identity import extract_proxies
from nodelife.probe import probe_one_detailed

UPSTREAM_URL = (
    "https://raw.githubusercontent.com/ccvvv/AutoSubHub/"
    "published-subscriptions/final/latest.yaml"
)
TARGETS = [
    "https://www.google.com/generate_204",
    "https://www.cloudflare.com/cdn-cgi/trace",
]


def main() -> int:
    concurrency = int(os.environ.get("NODELIFE_PROBE_CONCURRENCY", "2"))
    batch_size = int(os.environ.get("NODELIFE_PROBE_BATCH_SIZE", "30"))
    if not 1 <= concurrency <= 20:
        raise SystemExit("NODELIFE_PROBE_CONCURRENCY must be between 1 and 20")
    if not 1 <= batch_size <= 100:
        raise SystemExit("NODELIFE_PROBE_BATCH_SIZE must be between 1 and 100")

    response = requests.get(UPSTREAM_URL, timeout=30)
    response.raise_for_status()
    upstream = extract_proxies(yaml.safe_load(response.text), source="AutoSubHub final/latest.yaml")
    total = len(upstream)
    if not total:
        raise SystemExit("published subscription contains no proxies")

    if os.environ.get("NODELIFE_PROBE_FIND_FAILED", "0") == "1":
        print("Searching sequentially for one failed node; node identity will not be printed", flush=True)
        for index, proxy in enumerate(upstream, start=1):
            category = probe_one_detailed(
                proxy, mihomo_binary="mihomo", targets=TARGETS,
                startup_timeout=8, request_timeout=10,
            )
            if category != "passed":
                print(f"FIRST_FAILED_NODE index={index} category={category}", flush=True)
                return 0
            if index % 10 == 0:
                print(f"SEARCH_PROGRESS checked={index}/{total}", flush=True)
        print("FIRST_FAILED_NODE none", flush=True)
        return 0

    only_index = int(os.environ.get("NODELIFE_PROBE_ONLY_INDEX", "0"))
    if only_index < 0 or only_index > total:
        raise SystemExit(f"NODELIFE_PROBE_ONLY_INDEX must be 0 or between 1 and {total}")
    selected = upstream[only_index - 1 : only_index] if only_index else upstream
    target_total = len(selected)

    print(f"Published subscription parsed: {total} nodes", flush=True)
    print(
        f"Starting DIAGNOSTIC HTTPS recheck: concurrency={concurrency}, "
        f"batch_size={batch_size}, targets=2, selected_index={only_index or 'all'}; "
        "no node identities will be printed",
        flush=True,
    )

    totals: dict[str, int] = {}
    failed_indices: list[int] = []
    for start in range(0, target_total, batch_size):
        batch = selected[start : start + batch_size]
        indexed_batch = list(enumerate(batch, start=only_index or start + 1))
        with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = {
                executor.submit(
                    probe_one_detailed,
                    proxy,
                    mihomo_binary="mihomo",
                    targets=TARGETS,
                    startup_timeout=8,
                    request_timeout=10,
                ): index
                for index, proxy in indexed_batch
            }
            results = [(index, future.result()) for future, index in futures.items()]
        for index, category in sorted(results):
            totals[category] = totals.get(category, 0) + 1
            if category != "passed":
                failed_indices.append(index)
            print(f"NODE_RESULT index={index} category={category}", flush=True)
        done = min(start + len(batch), target_total)
        passed = totals.get("passed", 0)
        print(
            f"PROGRESS done={done}/{target_total} passed={passed} "
            f"not_passed={done - passed} categories={dict(sorted(totals.items()))}",
            flush=True,
        )

    passed = totals.get("passed", 0)
    print(
        f"DIAGNOSTIC_RESULT total={target_total} upstream_total={total} passed={passed} "
        f"not_passed={target_total - passed} concurrency={concurrency} "
        f"failed_indices={failed_indices} categories={dict(sorted(totals.items()))}",
        flush=True,
    )
    # Diagnostic only: no subscription is generated and no plaintext nodes are published.
    return 0


if __name__ == "__main__":
    sys.exit(main())
