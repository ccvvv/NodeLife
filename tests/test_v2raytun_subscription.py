import base64
import json
from pathlib import Path

import yaml

from scripts.v2raytun_subscription import convert_file, proxy_to_link


def test_vless_reality_link_contains_required_parameters():
    link = proxy_to_link({
        "name": "reality node", "type": "vless", "server": "example.com",
        "port": 443, "uuid": "00000000-0000-0000-0000-000000000000",
        "tls": True, "network": "tcp", "servername": "www.example.com",
        "flow": "xtls-rprx-vision",
        "reality-opts": {"public-key": "public", "short-id": "abcd"},
    })
    assert link.startswith("vless://")
    assert "security=reality" in link
    assert "pbk=public" in link
    assert "sid=abcd" in link
    assert "flow=xtls-rprx-vision" in link


def test_vmess_link_is_decodable_json():
    link = proxy_to_link({
        "name": "vmess node", "type": "vmess", "server": "example.com",
        "port": 443, "uuid": "00000000-0000-0000-0000-000000000000",
        "alterId": 0, "cipher": "auto", "network": "tcp", "tls": True,
    })
    payload = link.removeprefix("vmess://")
    decoded = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
    assert json.loads(decoded)["add"] == "example.com"


def test_convert_file_writes_base64_subscription(tmp_path: Path):
    source, output = tmp_path / "in.yaml", tmp_path / "out.txt"
    source.write_text(yaml.safe_dump({"proxies": [
        {"name": "ss node", "type": "ss", "server": "example.com",
         "port": 443, "cipher": "aes-128-gcm", "password": "secret"},
        {"name": "wireguard", "type": "wireguard", "server": "example.com", "port": 443},
    ]}), encoding="utf-8")
    included, skipped = convert_file(source, output)
    decoded = base64.b64decode(output.read_text().strip()).decode()
    assert included == 1 and skipped == 1
    assert decoded.startswith("ss://")


def test_convert_empty_passing_pool_writes_empty_subscription(tmp_path: Path):
    source, output = tmp_path / "empty.yaml", tmp_path / "empty.txt"
    source.write_text("proxies: []\n", encoding="utf-8")
    included, skipped = convert_file(source, output)
    assert (included, skipped) == (0, 0)
    assert output.read_text(encoding="ascii") == ""
