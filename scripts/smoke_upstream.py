"""Run a full live HTTPS recheck of the published AutoSubHub subscription."""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import requests
import yaml

from nodelife.identity import extract_proxies
from nodelife.probe import probe_many

UPSTREAM_URL = (
    "https://raw.githubusercontent.com/ccvvv/AutoSubHub/"
    "published-subscriptions/final/latest.yaml"
)
TARGETS = [
    "https://www.google.com/generate_204",
    "https://www.cloudflare.com/cdn-cgi/trace",
]


def main() -> int:
    concurrency = int(os.environ.get("NODELIFE_PROBE_CONCURRENCY", "10"))
    batch_size = int(os.environ.get("NODELIFE_PROBE_BATCH_SIZE", "30"))
    if not 1 <= concurrency <= 20:
        raise SystemExit("NODELIFE_PROBE_CONCURRENCY must be between 1 and 20")
    if not 1 <= batch_size <= 100:
        raise SystemExit("NODELIFE_PROBE_BATCH_SIZE must be between 1 and 100")

    response = requests.get(UPSTREAM_URL, timeout=30)
    response.raise_for_status()
    document = yaml.safe_load(response.text)
    upstream = extract_proxies(document, source="AutoSubHub final/latest.yaml")
    total = len(upstream)
    if not total:
        raise SystemExit("published subscription contains no proxies")

    print(f"Published subscription parsed: {total} nodes", flush=True)
    print(
        f"Starting FULL HTTPS recheck: concurrency={concurrency}, "
        f"batch_size={batch_size}, targets=2",
        flush=True,
    )

    passed = []
    for start in range(0, total, batch_size):
        batch = upstream[start : start + batch_size]
        batch_passed = probe_many(
            batch,
            mihomo_binary="mihomo",
            targets=TARGETS,
            concurrency=concurrency,
            startup_timeout=8,
            request_timeout=10,
        )
        passed.extend(batch_passed)
        done = min(start + len(batch), total)
        print(
            f"PROGRESS done={done}/{total} "
            f"passed={len(passed)} failed={done - len(passed)}",
            flush=True,
        )

    failed = total - len(passed)
    rate = (len(passed) / total) * 100
    print(
        f"FULL_RECHECK_RESULT total={total} passed={len(passed)} "
        f"failed={failed} pass_rate={rate:.1f}% "
        f"concurrency={concurrency}",
        flush=True,
    )
    # This is a diagnostic run only: never publish plaintext node data.
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
