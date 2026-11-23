"""Render NodeLife's passing Mihomo nodes as a V2RayTun-compatible share-link subscription.

The output is a base64-encoded list of standard share links (one per line).
Unsupported Mihomo-only protocols are skipped rather than emitted as broken links.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode

import yaml

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data" / "latest.yaml"
OUTPUT = ROOT / "data" / "v2raytun.txt"


def _b64(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode("utf-8")).decode("ascii").rstrip("=")


def _name(proxy: dict[str, Any]) -> str:
    return str(proxy.get("name") or "NodeLife").replace("\r", " ").replace("\n", " ")


def _host_port(proxy: dict[str, Any]) -> tuple[str, int]:
    host = proxy.get("server")
    port = proxy.get("port")
    if not isinstance(host, str) or not host.strip() or not isinstance(port, int):
        raise ValueError("proxy requires server and integer port")
    return host.strip(), port


def proxy_to_link(proxy: dict[str, Any]) -> str | None:
    kind = str(proxy.get("type", "")).lower()
    host, port = _host_port(proxy)
    name = quote(_name(proxy), safe="")
    if kind == "ss":
        method, password = proxy.get("cipher"), proxy.get("password")
        if not method or not isinstance(password, str) or not password or password.lower() == "none":
            return None
        userinfo = _b64(f"{method}:{password}")
        return f"ss://{userinfo}@{host}:{port}#{name}"

    if kind == "vmess":
        uuid = proxy.get("uuid")
        if not uuid:
            return None
        network = str(proxy.get("network") or "tcp")
        tls = "tls" if proxy.get("tls") else ""
        obj = {
            "v": "2", "ps": _name(proxy), "add": host, "port": str(port),
            "id": str(uuid), "aid": str(proxy.get("alterId", 0)),
            "scy": str(proxy.get("cipher") or "auto"), "net": network,
            "type": "none", "host": str(proxy.get("servername") or ""),
            "path": "", "tls": tls, "sni": str(proxy.get("servername") or ""),
        }
        if network == "ws":
            ws = proxy.get("ws-opts") or {}
            obj["path"] = str(ws.get("path") or "")
            obj["host"] = str((ws.get("headers") or {}).get("Host") or obj["host"])
        elif network == "grpc":
            grpc = proxy.get("grpc-opts") or {}
            obj["path"] = str(grpc.get("grpc-service-name") or "")
        return "vmess://" + _b64(json.dumps(obj, ensure_ascii=False, separators=(",", ":")))

    if kind == "vless":
        uuid = proxy.get("uuid")
        if not uuid:
            return None
        network = str(proxy.get("network") or "tcp")
        reality = proxy.get("reality-opts") or {}
        security = "reality" if reality else ("tls" if proxy.get("tls") else "none")
        params: dict[str, str] = {
            "encryption": str(proxy.get("encryption") or "none"),
            "security": security,
            "type": network,
        }
        sni = proxy.get("servername") or proxy.get("sni")
        if sni:
            params["sni"] = str(sni)
        fingerprint = proxy.get("client-fingerprint")
        if fingerprint:
            params["fp"] = str(fingerprint)
        if proxy.get("flow"):
            params["flow"] = str(proxy["flow"])
        if reality.get("public-key"):
            params["pbk"] = str(reality["public-key"])
        if reality.get("short-id"):
            params["sid"] = str(reality["short-id"])
        if network == "ws":
            ws = proxy.get("ws-opts") or {}
            if ws.get("path"):
                params["path"] = str(ws["path"])
            ws_host = (ws.get("headers") or {}).get("Host")
            if ws_host:
                params["host"] = str(ws_host)
        elif network == "grpc":
            grpc = proxy.get("grpc-opts") or {}
            if grpc.get("grpc-service-name"):
                params["serviceName"] = str(grpc["grpc-service-name"])
        elif network == "xhttp":
            xhttp = proxy.get("xhttp-opts") or {}
            if xhttp.get("path"):
                params["path"] = str(xhttp["path"])
            if xhttp.get("host"):
                params["host"] = str(xhttp["host"])
        return f"vless://{quote(str(uuid), safe='')}@{host}:{port}?{urlencode(params)}#{name}"

    if kind == "trojan":
        password = proxy.get("password")
        if not isinstance(password, str) or not password or password.lower() == "none":
            return None
        params = {}
        sni = proxy.get("sni") or proxy.get("servername")
        if sni:
            params["sni"] = str(sni)
        if proxy.get("skip-cert-verify"):
            params["allowInsecure"] = "1"
        return f"trojan://{quote(password, safe='')}@{host}:{port}?{urlencode(params)}#{name}"

    if kind == "hysteria2":
        password = proxy.get("password")
        if not isinstance(password, str) or not password or password.lower() == "none":
            return None
        params = {}
        sni = proxy.get("sni") or proxy.get("servername")
        if sni:
            params["sni"] = str(sni)
        if proxy.get("obfs"):
            params["obfs"] = str(proxy["obfs"])
        if proxy.get("obfs-password"):
            params["obfs-password"] = str(proxy["obfs-password"])
        if proxy.get("skip-cert-verify"):
            params["insecure"] = "1"
        return f"hysteria2://{quote(password, safe='')}@{host}:{port}?{urlencode(params)}#{name}"

    return None


def convert_file(source: Path = SOURCE, output: Path = OUTPUT) -> tuple[int, int]:
    document = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
    proxies = document.get("proxies", []) if isinstance(document, dict) else []
    if not isinstance(proxies, list):
        raise ValueError("latest.yaml must contain a proxies list")
    links = [link for proxy in proxies if isinstance(proxy, dict)
             if (link := proxy_to_link(proxy)) is not None]
    if not links:
        raise ValueError("no V2RayTun-compatible proxy links could be generated")
    # V2Ray-style subscription: base64 of newline-separated share links.
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(base64.b64encode(("\n".join(links) + "\n").encode("utf-8")).decode("ascii") + "\n", encoding="ascii")
    return len(links), len(proxies) - len(links)


if __name__ == "__main__":
    included, skipped = convert_file()
    print(f"V2RAYTUN_SUBSCRIPTION included={included} skipped_unsupported_or_invalid={skipped} output=data/v2raytun.txt")
