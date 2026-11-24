from nodelife import publisher


def node(name="node-a", server="example.com", port=443):
    return {"name": name, "type": "ss", "server": server, "port": port,
            "cipher": "aes-128-gcm", "password": "test-only"}


def test_fetches_latest_previous_and_older_as_https_subscriptions():
    seen = []
    yaml_by_name = {
        "latest.yaml": "proxies:\n- name: latest\n  type: ss\n  server: latest.example\n  port: 443\n  cipher: aes-128-gcm\n  password: test-only\n",
        "previous.yaml": "proxies:\n- name: previous\n  type: ss\n  server: previous.example\n  port: 443\n  cipher: aes-128-gcm\n  password: test-only\n",
        "older.yaml": "proxies:\n- name: older\n  type: ss\n  server: older.example\n  port: 443\n  cipher: aes-128-gcm\n  password: test-only\n",
    }
    class Response:
        def __init__(self, text):
            self.text = text
        def raise_for_status(self):
            pass
    class Session:
        def get(self, url, **kwargs):
            seen.append(url)
            filename = url.rsplit("/", 1)[-1]
            return Response(yaml_by_name[filename])

    snapshots = publisher.fetch_upstream_subscriptions(session=Session())
    assert [item["source"] for item in snapshots] == [
        "latest.yaml", "previous.yaml", "older.yaml"
    ]
    assert [item["proxies"][0]["name"] for item in snapshots] == [
        "latest", "previous", "older"
    ]
    assert len(seen) == 3
    assert all(url.startswith("https://raw.githubusercontent.com/") for url in seen)
    assert all("/final/" in url for url in seen)


def test_cycle_pool_merges_three_subscriptions_and_previous_passes_by_fingerprint():
    latest = node("latest", "latest.example")
    previous_release = node("previous", "previous.example")
    older_release = node("older", "older.example")
    previous_passed = node("kept-from-last-cycle", "last-cycle.example")
    renamed_duplicate = dict(latest, name="same-node-different-name")
    snapshots = [
        {"source": "latest.yaml", "proxies": [latest]},
        {"source": "previous.yaml", "proxies": [previous_release, renamed_duplicate]},
        {"source": "older.yaml", "proxies": [older_release]},
    ]
    candidates = publisher.collect_cycle_candidates(
        [previous_passed, dict(latest, name="last-cycle-name")], snapshots
    )
    assert [p["name"] for p in candidates] == [
        "latest", "previous", "older", "kept-from-last-cycle"
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

    empty = publisher.fetch_upstream_subscriptions(
        session=Session("proxies: []\n")
    )
    assert all(item["proxies"] == [] for item in empty)

    class BadSession:
        def get(self, url, **kwargs):
            return Response("not: [valid")
    import pytest
    with pytest.raises(Exception):
        publisher.fetch_upstream_subscriptions(session=BadSession())
