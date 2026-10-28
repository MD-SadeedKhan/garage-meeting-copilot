"""model_trace client. Identical in all three services; local http.server on 127.0.0.1 only."""
from __future__ import annotations

import importlib
import json
import logging
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

for _p in ("app.clients.model_trace", "app.services.model_trace", "agent_manager.services.model_trace"):
    try:
        mt = importlib.import_module(_p)
        break
    except ModuleNotFoundError as _e:
        if not _p.startswith(str(_e.name)):
            raise


@pytest.fixture(autouse=True)
def reset():
    mt._reset()
    yield
    mt._reset()


@pytest.fixture
def server():
    got = type("Got", (list,), {})()
    reply = {"body": b"{}"}

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            got.append((self.headers.get("Authorization"), len(body), json.loads(body)))
            self.send_response(202)
            self.end_headers()
            self.wfile.write(reply["body"])

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    got.reply = reply
    yield f"http://127.0.0.1:{srv.server_port}/internal/traces", got
    srv.shutdown()


def on(url, enabled=True):
    mt.configure(enabled, url, {"Authorization": "Bearer s3"}, "svc")


def no_thread(monkeypatch):
    monkeypatch.setattr(mt, "_ensure_thread", lambda: None)  # flush() is the only poster


def test_unconfigured_is_a_noop():
    mt.record(site="x")
    assert mt._thread is None and len(mt._q) == 0 and mt.dropped() == 0


@pytest.mark.parametrize("v,exp", [("1", True), (" TRUE ", True), ("yes", True), (True, True),
                                   ("on", False), ("0", False), ("", False), (None, False), (False, False)])
def test_enabled_parsing(v, exp):
    mt.configure(v, "http://127.0.0.1:9/x", {"A": "b"}, "svc")
    assert mt._cfg["enabled"] is exp


def test_wire_format_and_auth(server, monkeypatch):
    url, got = server
    no_thread(monkeypatch)
    on(url)
    mt.record(site="s", kind="chat", latencyMs=3)
    mt.flush()
    auth, _, body = got[0]
    assert auth == "Bearer s3" and body["source"] == "svc"
    assert body["calls"][0]["site"] == "s" and "ts" in body["calls"][0]


def test_none_values_stripped_recursively(server, monkeypatch):
    url, got = server
    no_thread(monkeypatch)
    on(url)
    mt.record(site="s", a=None, output={"text": "t", "finishReason": None},
              messages=[{"role": "user", "content": "q", "name": None}])
    mt.flush()
    c = got[0][2]["calls"][0]
    assert "a" not in c and c["output"] == {"text": "t"} and c["messages"] == [{"role": "user", "content": "q"}]


def test_non_ascii_kept_unescaped(server, monkeypatch):
    url, got = server
    no_thread(monkeypatch)
    on(url)
    mt.record(site="s", output={"text": "héllo م"})
    mt.flush()
    assert got[0][2]["calls"][0]["output"]["text"] == "héllo م"


def test_nan_is_dropped_and_counted(server, monkeypatch):
    url, got = server
    no_thread(monkeypatch)
    on(url)
    mt.record(site="s", params={"temperature": float("nan")})
    mt.record(site="ok")
    mt.flush()
    assert mt.dropped() == 1 and [c["site"] for c in got[0][2]["calls"]] == ["ok"]


def test_embedding_texts_capped_at_whole_strings(server, monkeypatch):
    url, got = server
    no_thread(monkeypatch)
    on(url)
    mt.record(site="e", kind="embedding", embedding={"texts": ["a" * 400_000] * 3})
    mt.record(site="e2", kind="embedding", embedding={"texts": ["a", "b"]})
    mt.flush()
    c1, c2 = got[0][2]["calls"]
    assert len(c1["embedding"]["texts"]) == 2 and c1["embedding"]["truncated"] is True
    assert c2["embedding"] == {"texts": ["a", "b"]}


def test_batches_at_most_50_calls(server, monkeypatch):
    url, got = server
    no_thread(monkeypatch)
    on(url)
    for _ in range(120):
        mt.record(site="s")
    mt.flush()
    assert [len(b["calls"]) for _, _, b in got] == [50, 50, 20]


def test_batches_are_byte_bounded(server, monkeypatch):
    url, got = server
    no_thread(monkeypatch)
    on(url)
    for i in range(10):
        mt.record(site="s", n=i, output={"text": "x" * 1_500_000})
    mt.flush(timeout=30)
    assert sum(len(b["calls"]) for _, _, b in got) == 10
    assert all(n <= 6_000_000 for _, n, _ in got) and len(got) >= 3
    assert [c["n"] for _, _, b in got for c in b["calls"]] == list(range(10))


def test_oversized_single_call_dropped_never_sent(server, monkeypatch):
    url, got = server
    no_thread(monkeypatch)
    on(url)
    mt.record(site="big", output={"text": "x" * 6_100_000})
    mt.record(site="ok")
    mt.flush()
    assert mt.dropped() == 1 and [c["site"] for _, _, b in got for c in b["calls"]] == ["ok"]


def test_queue_bounded_drops_oldest(monkeypatch):
    no_thread(monkeypatch)
    on("http://127.0.0.1:9/x")
    for i in range(510):
        mt.record(site="s", n=i)
    assert len(mt._q) == 500 and mt.dropped() == 10 and json.loads(mt._q[0])["n"] == 10


def test_queue_bounded_by_total_bytes_drops_oldest(monkeypatch):
    no_thread(monkeypatch)
    on("http://127.0.0.1:9/x")
    big = "x" * 5_000_000  # ~5 MB per call, under the 6 MB single-call cap
    for i in range(12):
        mt.record(site="s", n=i, system=big)
    assert sum(len(b) for b in mt._q) <= 50_000_000
    assert mt.dropped() == 12 - len(mt._q) and json.loads(mt._q[-1])["n"] == 11
    mt._drain()  # draining keeps the byte count honest
    assert mt._qbytes == 0


def test_fork_child_hook_resets_state():
    on("http://127.0.0.1:9/nope")
    mt.record(site="s")
    old = mt._thread
    assert old is not None and len(mt._q) == 1
    mt._lock.acquire()  # as if another parent thread held it at fork time
    mt._reset_state()  # == the os.register_at_fork(after_in_child=...) hook
    assert len(mt._q) == 0 and mt._thread is None and mt._lock.acquire(blocking=False)
    mt._lock.release()
    mt.record(site="s")
    assert mt._thread is not None and mt._thread is not old
    old.join(3)  # superseded flusher exits
    assert not old.is_alive()


def test_pid_change_restarts_thread(monkeypatch):
    on("http://127.0.0.1:9/nope")
    mt.record(site="s")
    first = mt._thread
    import os
    monkeypatch.setattr(os, "getpid", lambda: mt._pid + 1)
    mt.record(site="s")
    assert mt._thread is not first and len(mt._q) == 1


def test_only_one_flusher_under_concurrency(monkeypatch):
    started = []
    real = threading.Thread

    def counting(*a, **kw):
        t = real(*a, **kw)
        started.append(t)
        return t

    monkeypatch.setattr(mt.threading, "Thread", counting)
    on("http://127.0.0.1:9/nope")
    ts = [real(target=mt._ensure_thread) for _ in range(16)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert len(started) == 1


def test_flusher_posts_on_its_own(server):
    url, got = server
    on(url)
    mt.record(site="s")
    for _ in range(60):
        if got:
            break
        time.sleep(0.1)
    assert got


def test_failure_swallowed_counted_and_warned_with_count(caplog):
    on("http://127.0.0.1:9/nope")
    mt._q.append(b'{"site":"s"}')
    with caplog.at_level(logging.WARNING):
        mt.flush()
    assert mt.dropped() == 1 and "dropped so far: 1" in caplog.text


def test_rejected_in_response_is_logged(server, monkeypatch, caplog):
    url, got = server
    got.reply["body"] = b'{"accepted":0,"rejected":2}'
    no_thread(monkeypatch)
    on(url)
    mt.record(site="s")
    with caplog.at_level(logging.WARNING):
        mt.flush()
    assert "rejected 2" in caplog.text
