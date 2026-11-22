"""Run a diagnostic HTTPS recheck without publishing node data."""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import requests
import yaml

from nodelife.identity import extract_proxies
from nodelife.probe import probe_many_detailed

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

    print(f"Published subscription parsed: {total} nodes", flush=True)
    print(
        f"Starting DIAGNOSTIC HTTPS recheck: concurrency={concurrency}, "
        f"batch_size={batch_size}, targets=2; no node identities will be printed",
        flush=True,
    )

    totals: dict[str, int] = {}
    for start in range(0, total, batch_size):
        batch = upstream[start : start + batch_size]
        counts = probe_many_detailed(
            batch, mihomo_binary="mihomo", targets=TARGETS,
            concurrency=concurrency, startup_timeout=8, request_timeout=10,
        )
        for category, count in counts.items():
            totals[category] = totals.get(category, 0) + count
        done = min(start + len(batch), total)
        passed = totals.get("passed", 0)
        print(
            f"PROGRESS done={done}/{total} passed={passed} "
            f"not_passed={done - passed} categories={dict(sorted(totals.items()))}",
            flush=True,
        )

    passed = totals.get("passed", 0)
    print(
        f"DIAGNOSTIC_RESULT total={total} passed={passed} "
        f"not_passed={total - passed} concurrency={concurrency} "
        f"categories={dict(sorted(totals.items()))}",
        flush=True,
    )
    # Diagnostic only: no subscription is generated and no plaintext nodes are published.
    return 0


if __name__ == "__main__":
    sys.exit(main())
