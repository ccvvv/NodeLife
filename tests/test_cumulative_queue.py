import json
import pytest
from nodelife import publisher


def node(name="node-a", server="example.com", port=443):
    return {"name": name, "type": "ss", "server": server, "port": port,
            "cipher": "aes-128-gcm", "password": "test-only"}


def test_queue_state_defaults_and_round_trip(tmp_path):
    path = tmp_path / "queue_state.json"
    state = publisher.load_queue_state(path)
    assert state == {"schema_version": 1, "last_processed_commit": None, "pending": {}}
    state["pending"] = {publisher.canonical_fingerprint(node()): node()}
    publisher.save_queue_state(path, state)
    assert publisher.load_queue_state(path) == state


def test_queue_state_rejects_fingerprint_mismatch(tmp_path):
    path = tmp_path / "queue_state.json"
    path.write_text(json.dumps({"schema_version": 1, "last_processed_commit": None, "pending": {"wrong": node()}}))
    with pytest.raises(ValueError):
        publisher.load_queue_state(path)


def test_snapshots_accumulate_and_deduplicate_across_releases():
    pending = {}
    added = publisher.add_snapshots_to_pending(
        [{"proxies": [node("first")]},
         {"proxies": [node("renamed"), node("second", server="second.example")]}],
        pending, set(),
    )
    assert added == 2
    assert [item["name"] for item in pending.values()] == ["first", "second"]


def test_already_published_identity_is_not_queued_again():
    existing = node("published")
    fingerprint = publisher.canonical_fingerprint(existing)
    pending = {}
    added = publisher.add_snapshots_to_pending(
        [{"proxies": [node("renamed-same-config")]}], pending, {fingerprint}
    )
    assert added == 0
    assert pending == {}


def test_fetch_upstream_snapshots_collects_all_releases_oldest_first():
    old_sha, new_sha = "1" * 40, "2" * 40
    yaml_text = ("proxies:\n- name: node\n  type: ss\n  server: example.com\n"
                 "  port: 443\n  cipher: aes-128-gcm\n  password: test-only\n")
    class Response:
        def __init__(self, payload=None, text=""):
            self.payload, self.text = payload, text
        def raise_for_status(self):
            pass
        def json(self):
            return self.payload
    class Session:
        def get(self, url, **kwargs):
            if url == publisher.UPSTREAM_COMMITS_URL:
                return Response([{"sha": new_sha}, {"sha": old_sha}])
            return Response(text=yaml_text)
    snapshots, cursor = publisher.fetch_upstream_snapshots(None, session=Session())
    assert [item["commit"] for item in snapshots] == [old_sha, new_sha]
    assert cursor == new_sha


def test_fetch_upstream_snapshots_stops_at_saved_cursor():
    cursor_sha = "2" * 40
    class Response:
        def raise_for_status(self):
            pass
        def json(self):
            return [{"sha": cursor_sha}, {"sha": "1" * 40}]
    class Session:
        def get(self, url, **kwargs):
            return Response()
    snapshots, cursor = publisher.fetch_upstream_snapshots(cursor_sha, session=Session())
    assert snapshots == []
    assert cursor == cursor_sha


def test_fetch_upstream_snapshots_fails_closed_if_cursor_disappears():
    class Response:
        def raise_for_status(self):
            pass
        def json(self):
            return [{"sha": "1" * 40}]
    class Session:
        def get(self, url, **kwargs):
            return Response()
    with pytest.raises(RuntimeError, match="cursor"):
        publisher.fetch_upstream_snapshots("2" * 40, session=Session())
