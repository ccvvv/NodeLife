"""Strict per-node HTTPS probing through Mihomo; no DIRECT fallback exists."""
from __future__ import annotations

import concurrent.futures
import socket
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Iterable

import requests
import yaml


class ProbeError(RuntimeError):
    """Raised when the local proxy engine cannot be started safely."""


def build_mihomo_config(proxy: dict[str, Any], mixed_port: int) -> dict[str, Any]:
    if not isinstance(proxy, dict) or not isinstance(proxy.get("name"), str) or not proxy["name"]:
        raise ValueError("proxy entry is malformed")
    # MATCH is forced to the one-node proxy group. No DIRECT rule or fallback is added.
    return {
        "mixed-port": mixed_port,
        "allow-lan": False,
        "mode": "rule",
        "log-level": "error",
        "ipv6": False,
        "proxies": [dict(proxy)],
        "proxy-groups": [
            {
                "name": "NODELIFE_TEST",
                "type": "select",
                "proxies": [proxy["name"]],
            }
        ],
        "rules": ["MATCH,NODELIFE_TEST"],
    }


def _free_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_port(port: int, process: subprocess.Popen[Any], timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise ProbeError("Mihomo exited before its local proxy became ready")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.25):
                return
        except OSError:
            time.sleep(0.1)
    raise ProbeError("Mihomo local proxy startup timed out")


def _request_https(
    port: int,
    targets: Iterable[str],
    timeout: float,
    get: Callable[..., Any] = requests.get,
) -> bool:
    proxy_url = f"http://127.0.0.1:{port}"
    proxies = {"http": proxy_url, "https": proxy_url}
    for target in targets:
        try:
            response = get(
                target,
                proxies=proxies,
                timeout=timeout,
                allow_redirects=True,
                verify=True,
            )
            try:
                if 200 <= int(response.status_code) < 400:
                    return True
            finally:
                close = getattr(response, "close", None)
                if callable(close):
                    close()
        except requests.RequestException:
            continue
    return False


def probe_one(
    proxy: dict[str, Any],
    *,
    mihomo_binary: str,
    targets: list[str],
    startup_timeout: float = 8,
    request_timeout: float = 10,
) -> bool:
    """Return True only if an HTTPS target responds through this proxy."""
    if not targets or any(not str(url).startswith("https://") for url in targets):
        raise ValueError("probe targets must be non-empty HTTPS URLs")

    port = _free_local_port()
    config = build_mihomo_config(proxy, port)
    with tempfile.TemporaryDirectory(prefix="nodelife-probe-") as temp_dir:
        config_path = Path(temp_dir) / "config.yaml"
        config_path.write_text(
            yaml.safe_dump(config, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        with open(Path(temp_dir) / "mihomo.log", "w", encoding="utf-8") as log_file:
            process = subprocess.Popen(
                [mihomo_binary, "-f", str(config_path)],
                stdin=subprocess.DEVNULL,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                cwd=temp_dir,
            )
            try:
                _wait_for_port(port, process, startup_timeout)
                session = requests.Session()
                session.trust_env = False
                try:
                    return _request_https(
                        port,
                        targets,
                        request_timeout,
                        get=session.get,
                    )
                finally:
                    session.close()
            except (ProbeError, OSError, subprocess.SubprocessError):
                return False
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=2)


def probe_many(
    proxies: list[dict[str, Any]],
    *,
    mihomo_binary: str,
    targets: list[str],
    concurrency: int = 10,
    startup_timeout: float = 8,
    request_timeout: float = 10,
) -> list[dict[str, Any]]:
    """Probe concurrently and return only aggregate pass/fail per proxy identity."""
    if concurrency < 1:
        raise ValueError("concurrency must be at least 1")

    def run(proxy: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        try:
            passed = probe_one(
                proxy,
                mihomo_binary=mihomo_binary,
                targets=targets,
                startup_timeout=startup_timeout,
                request_timeout=request_timeout,
            )
        except (ValueError, ProbeError):
            passed = False
        return proxy, passed

    results: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [executor.submit(run, proxy) for proxy in proxies]
        for future in concurrent.futures.as_completed(futures):
            proxy, passed = future.result()
            if passed:
                results.append(proxy)
    return results
