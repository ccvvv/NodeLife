import pytest

from nodelife.identity import (
    SubscriptionError,
    canonical_fingerprint,
    extract_proxies,
    merge_proxies,
)


def node(name="node-a", server="example.com", port=443):
    return {"name": name, "type": "ss", "server": server, "port": port, "cipher": "aes-128-gcm", "password": "test-only"}


def test_fingerprint_ignores_display_name():
    assert canonical_fingerprint(node("first")) == canonical_fingerprint(node("second"))


def test_fingerprint_changes_when_config_changes():
    assert canonical_fingerprint(node(port=443)) != canonical_fingerprint(node(port=8443))


def test_merge_deduplicates_and_prefers_upstream_name():
    upstream = node("upstream-label")
    previous_duplicate = node("old-label")
    previous_only = node("previous-only", server="other.example")
    result = merge_proxies([upstream], [previous_duplicate, previous_only])
    assert [item["name"] for item in result] == ["upstream-label", "previous-only"]


def test_extract_rejects_empty_or_malformed_subscription():
    with pytest.raises(SubscriptionError):
        extract_proxies({"proxies": []}, source="test")
    with pytest.raises(SubscriptionError):
        extract_proxies({"proxies": ["not-a-proxy"]}, source="test")


def test_extract_returns_independent_copy():
    original = node()
    result = extract_proxies({"proxies": [original]}, source="test")
    result[0]["name"] = "changed"
    assert original["name"] == "node-a"
