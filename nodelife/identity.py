"""Stable proxy identity and safe merge helpers for NodeLife."""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any, Iterable


class SubscriptionError(ValueError):
    """Raised when a subscription contains malformed proxy data."""


def canonical_fingerprint(proxy: dict[str, Any]) -> str:
    if not isinstance(proxy, dict):
        raise SubscriptionError("proxy entry must be a mapping")
    identity = {key: value for key, value in proxy.items() if key != "name"}
    try:
        encoded = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise SubscriptionError("proxy configuration is not JSON-serializable") from exc
    return hashlib.sha256(encoded).hexdigest()


def extract_proxies(document: Any, *, source: str, allow_empty: bool = False) -> list[dict[str, Any]]:
    if not isinstance(document, dict):
        raise SubscriptionError(f"{source} must be a YAML mapping")
    proxies = document.get("proxies")
    if not isinstance(proxies, list) or (not proxies and not allow_empty):
        qualifier = "a proxies list" if allow_empty else "a non-empty proxies list"
        raise SubscriptionError(f"{source} must contain {qualifier}")
    result: list[dict[str, Any]] = []
    for index, proxy in enumerate(proxies):
        if not isinstance(proxy, dict) or not isinstance(proxy.get("name"), str) or not proxy["name"]:
            raise SubscriptionError(f"{source} proxy #{index + 1} is malformed")
        canonical_fingerprint(proxy)
        result.append(deepcopy(proxy))
    return result


def merge_proxies(
    upstream_proxies: Iterable[dict[str, Any]],
    previous_proxies: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge in priority order; the first occurrence supplies the display name."""
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for proxy in (*list(upstream_proxies), *list(previous_proxies)):
        fingerprint = canonical_fingerprint(proxy)
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        merged.append(deepcopy(proxy))
    return merged
