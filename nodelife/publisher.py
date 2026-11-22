"""Recheck upstream and publish only passing proxies as a public YAML subscription."""
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

UPSTREAM_URL = (
    "https://raw.githubusercontent.com/ccvvv/AutoSubHub/"
    "published-subscriptions/final/latest.yaml"
)
TARGETS = [
    "https://www.google.com/generate_204",
    "https://www.cloudflare.com/cdn-cgi/trace",
]
OUTPUT_PATH = Path(__file__).resolve().parents[1] / "data" / "latest.yaml"


def filter_passing(
    proxies: list[dict[str, Any]],
    *,
    mihomo_binary: str = "mihomo",
    concurrency: int = 2,
    startup_timeout: float = 8,
    request_timeout: float = 10,
    batch_size: int = 30,
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
        batch = list(enumerate(proxies[start : start + batch_size], start=start))
        with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = {
                executor.submit(
                    probe_one_detailed,
                    proxy,
                    mihomo_binary=mihomo_binary,
                    targets=TARGETS,
                    startup_timeout=startup_timeout,
                    request_timeout=request_timeout,
                ): index
                for index, proxy in batch
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
        print(
            f"PROGRESS done={done}/{total} passed={passed_count} "
            f"not_passed={done - passed_count}",
            flush=True,
        )

    print(f"PROBE_SUMMARY total={total} categories={dict(sorted(categories.items()))}", flush=True)
    return [proxy for index, proxy in enumerate(proxies) if passed_by_index.get(index, False)]


def load_previous_output(path: Path) -> list[dict[str, Any]]:
    """Load the previous successful output, if one exists."""
    if not path.exists():
        return []
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    return extract_proxies(document, source="previous NodeLife output")


def render_subscription(proxies: list[dict[str, Any]]) -> str:
    if not proxies:
        raise ValueError("refusing to render an empty subscription")
    return yaml.safe_dump(
        {"proxies": proxies},
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    )


def main() -> int:
    stage = "fetch_upstream"
    response = requests.get(UPSTREAM_URL, timeout=30)
    response.raise_for_status()
    print(f"UPSTREAM_FETCHED bytes={len(response.content)}", flush=True)

    stage = "parse_upstream"
    upstream = extract_proxies(
        yaml.safe_load(response.text),
        source="AutoSubHub final subscription",
    )
    stage = "load_previous_output"
    previous = load_previous_output(OUTPUT_PATH)
    candidates = merge_proxies(upstream, previous)

    print(
        f"INPUT_SUMMARY upstream={len(upstream)} previous_output={len(previous)} "
        f"deduplicated_candidates={len(candidates)}",
        flush=True,
    )

    stage = "probe_nodes"
    passing = filter_passing(candidates, concurrency=2, batch_size=30)
    if not passing:
        raise RuntimeError(
            "No nodes passed the HTTPS checks; previous published subscription was preserved"
        )

    stage = "write_output"
    content = render_subscription(passing)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = OUTPUT_PATH.with_suffix(".yaml.tmp")
    temporary_path.write_text(content, encoding="utf-8")
    temporary_path.replace(OUTPUT_PATH)

    print(
        f"PUBLISH_READY passed={len(passing)} output={OUTPUT_PATH.relative_to(OUTPUT_PATH.parents[1])}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    stage = "startup"
    try:
        raise SystemExit(main())
    except Exception as error:
        # Exception messages from upstream/proxy libraries may contain sensitive data.
        print(
            f"NODELIFE_PUBLISH_FAILED stage={locals().get('stage', 'unknown')} "
            f"error_type={type(error).__name__}",
            file=sys.stderr,
            flush=True,
        )
        raise SystemExit(1)
