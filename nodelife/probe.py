"""Strict per-node HTTPS probing through Mihomo; no DIRECT fallback exists."""
from __future__ import annotations

import concurrent.futures
import socket
import subprocess
import tempfile
import time
from collections import Counter
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

import requests
import yaml


class ProbeError(RuntimeError):
    """Raised when the local proxy engine cannot be started safely."""


def build_mihomo_config(proxy: dict[str, Any], mixed_port: int) -> dict[str, Any]:
    if not isinstance(proxy, dict) or not isinstance(proxy.get("name"), str) or not proxy["name"]:
        raise ValueError("proxy entry is malformed")
    return {
        "mixed-port": mixed_port,
        "allow-lan": False,
        "mode": "rule",
        "log-level": "error",
        "ipv6": False,
        "proxies": [dict(proxy)],
        "proxy-groups": [{"name": "NODELIFE_TEST", "type": "select", "proxies": [proxy["name"]]}],
        "rules": ["MATCH,NODELIFE_TEST"],
    }


def _free_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_port(port: int, process: subprocess.Popen[Any], timeout: float) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return "mihomo_exit"
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.25):
                return "ready"
        except OSError:
            time.sleep(0.1)
    return "startup_timeout"


def _classify_mihomo_log(path: Path) -> str:
    """Return a safe category only; never emit raw Mihomo logs."""
    try:
        content = path.read_text(encoding="utf-8", errors="replace").lower()
    except OSError:
        return "mihomo_exit"
    if any(x in content for x in ("unsupported", "invalid config", "unmarshal", "proxy type", "unknown field")):
        return "mihomo_config_error"
    if any(x in content for x in ("error", "fatal", "failed")):
        return "mihomo_runtime_error"
    return "mihomo_exit"


def _request_https(
    port: int, targets: Iterable[str], timeout: float, get: Any = requests.get,
) -> bool:
    """Backward-compatible HTTPS request helper used by unit tests and callers."""
    proxy_url = f"http://127.0.0.1:{port}"
    proxies = {"http": proxy_url, "https": proxy_url}
    for target in targets:
        try:
            response = get(
                target, proxies=proxies, timeout=timeout,
                allow_redirects=True, verify=True,
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


def _classify_tls_error(error: requests.exceptions.SSLError) -> str:
    """Map TLS exceptions to safe categories without printing exception text."""
    message = str(error).lower()
    if "certificate verify failed" in message or "certificate has expired" in message:
        return "tls_certificate"
    if "wrong version number" in message or "unknown protocol" in message:
        return "tls_protocol"
    if any(token in message for token in ("handshake failure", "alert handshake", "tlsv1 alert")):
        return "tls_handshake"
    if any(token in message for token in ("unexpected eof", "eof occurred")):
        return "tls_unexpected_eof"
    if "connection reset" in message:
        return "tls_connection_reset"
    return "tls_other"


def _request_https_result(port: int, targets: Iterable[str], timeout: float, session: requests.Session) -> str:
    proxy_url = f"http://127.0.0.1:{port}"
    proxies = {"http": proxy_url, "https": proxy_url}
    observed: list[str] = []
    # Retry only likely transient transport failures once; permanent TLS/config
    # failures are recorded immediately. Keep the retry bounded per target.
    retryable = {"proxy_connection", "request_timeout", "tls_unexpected_eof", "tls_connection_reset", "connection_error"}
    for target in targets:
        host = urlparse(target).hostname or "unknown"
        category = "request_error"
        for attempt in range(2):
            try:
                response = session.get(
                    target, proxies=proxies, timeout=timeout,
                    allow_redirects=True, verify=True,
                )
                try:
                    status_code = int(response.status_code)
                    if 200 <= status_code < 400:
                        print(f"PROBE_TARGET host={host} attempt={attempt + 1} result=passed status={status_code}", flush=True)
                        return "passed"
                    category = "http_status"
                finally:
                    response.close()
            except requests.exceptions.ProxyError:
                category = "proxy_connection"
            except (requests.exceptions.ConnectTimeout, requests.exceptions.ReadTimeout):
                category = "request_timeout"
            except requests.exceptions.SSLError as error:
                category = _classify_tls_error(error)
            except requests.exceptions.ConnectionError:
                category = "connection_error"
            except requests.RequestException:
                category = "request_error"
            print(f"PROBE_TARGET host={host} attempt={attempt + 1} result={category}", flush=True)
            if attempt == 0 and category in retryable:
                continue
            break
        observed.append(host + ":" + category)
    if not observed:
        return "request_error"
    # Include only the fixed target hostname and safe error category, never node identity.
    return "|".join(sorted(set(observed)))


def probe_one_detailed(
    proxy: dict[str, Any], *, mihomo_binary: str, targets: list[str],
    startup_timeout: float = 8, request_timeout: float = 10,
) -> str:
    """Return a safe diagnostic category; never return or log node identity."""
    if not targets or any(not str(url).startswith("https://") for url in targets):
        raise ValueError("probe targets must be non-empty HTTPS URLs")
    try:
        port = _free_local_port()
        config = build_mihomo_config(proxy, port)
    except (ValueError, OSError):
        return "config_error"

    with tempfile.TemporaryDirectory(prefix="nodelife-probe-") as temp_dir:
        root = Path(temp_dir)
        config_path = root / "config.yaml"
        log_path = root / "mihomo.log"
        try:
            config_path.write_text(
                yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8"
            )
            with log_path.open("w", encoding="utf-8") as log_file:
                try:
                    process = subprocess.Popen(
                        [mihomo_binary, "-f", str(config_path)],
                        stdin=subprocess.DEVNULL, stdout=log_file,
                        stderr=subprocess.STDOUT, cwd=temp_dir,
                    )
                except (OSError, subprocess.SubprocessError):
                    return "mihomo_spawn_error"
                try:
                    startup = _wait_for_port(port, process, startup_timeout)
                    if startup != "ready":
                        if process.poll() is not None:
                            return _classify_mihomo_log(log_path)
                        return startup
                    session = requests.Session()
                    session.trust_env = False
                    try:
                        return _request_https_result(port, targets, request_timeout, session)
                    finally:
                        session.close()
                finally:
                    if process.poll() is None:
                        process.terminate()
                        try:
                            process.wait(timeout=2)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait(timeout=2)
        except (OSError, subprocess.SubprocessError):
            return "local_runtime_error"


def probe_one(
    proxy: dict[str, Any], *, mihomo_binary: str, targets: list[str],
    startup_timeout: float = 8, request_timeout: float = 10,
) -> bool:
    """Backward-compatible pass/fail wrapper."""
    return probe_one_detailed(
        proxy, mihomo_binary=mihomo_binary, targets=targets,
        startup_timeout=startup_timeout, request_timeout=request_timeout,
    ) == "passed"


def probe_many_detailed(
    proxies: list[dict[str, Any]], *, mihomo_binary: str, targets: list[str],
    concurrency: int = 2, startup_timeout: float = 8, request_timeout: float = 10,
) -> Counter[str]:
    """Probe concurrently and return aggregate categories only."""
    if concurrency < 1:
        raise ValueError("concurrency must be at least 1")

    def run(proxy: dict[str, Any]) -> str:
        try:
            return probe_one_detailed(
                proxy, mihomo_binary=mihomo_binary, targets=targets,
                startup_timeout=startup_timeout, request_timeout=request_timeout,
            )
        except Exception:
            return "unexpected_probe_error"

    counts: Counter[str] = Counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [executor.submit(run, proxy) for proxy in proxies]
        for future in concurrent.futures.as_completed(futures):
            counts[future.result()] += 1
    return counts


def probe_many(
    proxies: list[dict[str, Any]], *, mihomo_binary: str, targets: list[str],
    concurrency: int = 10, startup_timeout: float = 8, request_timeout: float = 10,
) -> list[dict[str, Any]]:
    """Return only passing proxies; retained for existing callers."""
    if concurrency < 1:
        raise ValueError("concurrency must be at least 1")

    def run(proxy: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        try:
            passed = probe_one(
                proxy, mihomo_binary=mihomo_binary, targets=targets,
                startup_timeout=startup_timeout, request_timeout=request_timeout,
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
