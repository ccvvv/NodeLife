"""One-off live smoke test against the published AutoSubHub final subscription."""
from __future__ import annotations

import os
import sys

import requests
import yaml

from nodelife.identity import extract_proxies
from nodelife.probe import probe_many

UPSTREAM_URL = (
    "https://raw.githubusercontent.com/ccvvv/AutoSubHub/"
    "published-subscriptions/final/latest.yaml"
)


def main() -> int:
    limit = int(os.environ.get("NODELIFE_SMOKE_LIMIT", "10"))
    if not 1 <= limit <= 50:
        raise SystemExit("NODELIFE_SMOKE_LIMIT must be between 1 and 50")

    response = requests.get(UPSTREAM_URL, timeout=30)
    response.raise_for_status()
    document = yaml.safe_load(response.text)
    upstream = extract_proxies(document, source="AutoSubHub final/latest.yaml")
    sample = upstream[:limit]
    if not sample:
        raise SystemExit("published subscription contains no proxies")

    print(f"Published subscription parsed: {len(upstream)} nodes")
    print(f"Starting real HTTPS probe for first {len(sample)} nodes")
    passed = probe_many(
        sample,
        mihomo_binary="mihomo",
        targets=[
            "https://www.google.com/generate_204",
            "https://www.cloudflare.com/cdn-cgi/trace",
        ],
        concurrency=2,
        startup_timeout=8,
        request_timeout=10,
    )
    failed = len(sample) - len(passed)
    print(f"SMOKE_RESULT total={len(sample)} passed={len(passed)} failed={failed}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
