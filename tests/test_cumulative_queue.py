from nodelife import publisher


def node(name="node-a", server="example.com", port=443):
    return {"name": name, "type": "ss", "server": server, "port": port,
            "cipher": "aes-128-gcm", "password": "test-only"}


def test_fetches_only_latest_as_https_subscription():
    seen = []
    class Response:
        def __init__(self, text):
            self.text = text
        def raise_for_status(self):
            pass
    class Session:
        def get(self, url, **kwargs):
            seen.append(url)
            return Response(
                "proxies:\n- name: latest\n  type: ss\n  server: latest.example\n"
                "  port: 443\n  cipher: aes-128-gcm\n  password: test-only\n"
            )

    snapshots = publisher.fetch_upstream_subscriptions(session=Session())
    assert [item["source"] for item in snapshots] == ["latest.yaml"]
    assert [item["proxies"][0]["name"] for item in snapshots] == ["latest"]
    assert len(seen) == 1
    assert seen[0].endswith("/final/latest.yaml")
    assert seen[0].startswith("https://raw.githubusercontent.com/")


def test_cycle_pool_merges_latest_and_previous_passes_by_fingerprint():
    latest = node("latest", "latest.example")
    previous_passed = node("kept-from-last-cycle", "last-cycle.example")
    renamed_duplicate = dict(latest, name="same-node-different-name")
    snapshots = [{"source": "latest.yaml", "proxies": [latest, renamed_duplicate]}]
    candidates = publisher.collect_cycle_candidates([previous_passed], snapshots)
    assert [p["name"] for p in candidates] == [
        "latest", "kept-from-last-cycle"
    ]


def test_empty_subscription_is_valid_but_malformed_subscription_fails_closed():
    class Response:
        def __init__(self, text):
            self.text = text
        def raise_for_status(self):
            pass
    class Session:
        def __init__(self, text):
            self.text = text
        def get(self, url, **kwargs):
            return Response(self.text)

    empty = publisher.fetch_upstream_subscriptions(session=Session("proxies: []\n"))
    assert empty == [{"source": "latest.yaml", "proxies": []}]

    import pytest
    with pytest.raises(Exception):
        publisher.fetch_upstream_subscriptions(session=Session("not: [valid"))
