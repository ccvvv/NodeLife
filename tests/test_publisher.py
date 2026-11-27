from nodelife import publisher


def node(name):
    return {"name": name, "type": "ss", "server": f"{name}.example", "port": 443,
            "cipher": "aes-128-gcm", "password": "test-only"}


def test_filter_passing_keeps_only_successful_nodes_in_source_order(monkeypatch):
    def fake_probe(proxy, **kwargs):
        return "passed" if proxy["name"] in {"first", "third"} else "tls_peer_closed"

    monkeypatch.setattr(publisher, "probe_one_detailed", fake_probe)
    result = publisher.filter_passing(
        [node("first"), node("second"), node("third")], concurrency=2, batch_size=3,
    )
    assert [proxy["name"] for proxy in result] == ["first", "third"]


def test_render_subscription_is_valid_yaml_and_has_only_proxies():
    rendered = publisher.render_subscription([node("working")])
    assert "password: test-only" in rendered
    assert publisher.yaml.safe_load(rendered) == {"proxies": [node("working")]}


def test_render_subscription_allows_empty_result():
    rendered = publisher.render_subscription([])
    assert publisher.yaml.safe_load(rendered) == {"proxies": []}


def test_collect_candidates_merges_latest_and_previous_passes_only():
    latest = node("latest")
    previous_passed = node("previous-cycle")
    renamed_duplicate = dict(latest, name="old-name")
    candidates = publisher.collect_cycle_candidates(
        [previous_passed, renamed_duplicate],
        [{"source": "latest.yaml", "proxies": [latest]}],
    )
    assert [p["name"] for p in candidates] == ["latest", "previous-cycle"]
