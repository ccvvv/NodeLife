from nodelife.probe import build_mihomo_config, _request_https


def proxy():
    return {
        "name": "test-node",
        "type": "ss",
        "server": "example.invalid",
        "port": 443,
        "cipher": "aes-128-gcm",
        "password": "not-a-real-secret",
    }


def test_mihomo_config_routes_all_traffic_to_only_the_test_proxy():
    config = build_mihomo_config(proxy(), 17890)
    assert config["proxies"] == [proxy()]
    assert config["proxy-groups"] == [
        {"name": "NODELIFE_TEST", "type": "select", "proxies": ["test-node"]}
    ]
    assert config["rules"] == ["MATCH,NODELIFE_TEST"]
    assert "DIRECT" not in str(config)


def test_probe_config_rejects_malformed_proxy():
    try:
        build_mihomo_config({"type": "ss"}, 17890)
    except ValueError:
        pass
    else:
        raise AssertionError("malformed proxy should be rejected")


def test_request_uses_local_proxy_for_http_and_https_and_disables_bypass():
    seen = {}

    class Response:
        status_code = 204
        def close(self):
            pass

    def fake_get(url, **kwargs):
        seen.update(kwargs)
        return Response()

    assert _request_https(17890, ["https://example.com"], 3, get=fake_get)
    assert seen["proxies"] == {
        "http": "http://127.0.0.1:17890",
        "https": "http://127.0.0.1:17890",
    }
    assert seen["verify"] is True
    assert seen["allow_redirects"] is True


def test_probe_rejects_non_https_targets():
    from nodelife.probe import probe_one
    try:
        probe_one(proxy(), mihomo_binary="mihomo", targets=["http://example.com"])
    except ValueError:
        pass
    else:
        raise AssertionError("HTTP target should be rejected")
