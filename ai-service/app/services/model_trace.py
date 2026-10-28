"""
Model-trace client: queues model calls in memory and POSTs them in batches to
contacts-backend `POST /internal/traces`.

Identical in every service. A service opts in by calling `configure(...)` from
its API/worker startup; until then `record()` is a no-op, so offline scripts
never trace. Never blocks, never raises into a caller. Stdlib only.
"""
from __future__ import annotations

import atexit
import collections
import json
import logging
import os
import threading
import time
import urllib.request
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_MAX_QUEUE, _BATCH, _TIMEOUT, _WAKE_EVERY, _WAKE_AT = 500, 50, 5, 2, 20
_MAX_BATCH_BYTES = 6_000_000  # per POST (backend limit is 8mb); also the cap for one call
_MAX_EMBED_CHARS = 1_000_000
_MAX_QUEUE_BYTES = 50_000_000  # total queued; oldest dropped first, so a backend outage can't grow memory

_cfg: dict = {"enabled": False, "url": "", "headers": {}, "source": ""}
_q: collections.deque = collections.deque()  # encoded calls (bytes); bounded by count AND bytes in record()
_qbytes = 0
_dropped = 0
_lock = threading.Lock()
_wake = threading.Event()
_thread: threading.Thread | None = None
_pid = 0
_last_warn = 0.0


def truthy(value) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes"}


def configure(enabled, url: str, headers: dict, source: str) -> None:
    global _cfg
    _cfg = {"enabled": bool(truthy(enabled) and url and headers), "url": url,
            "headers": headers, "source": source}


def dropped() -> int:
    return _dropped


def _reset_state() -> None:
    global _q, _qbytes, _lock, _wake, _thread, _pid
    _q, _qbytes = collections.deque(), 0
    _lock, _wake = threading.Lock(), threading.Event()
    _thread, _pid = None, 0


def _reset() -> None:
    """Test helper: back to the pristine, off state."""
    global _dropped, _last_warn
    _reset_state()
    _dropped, _last_warn = 0, 0.0
    configure(False, "", {}, "")


# A forked child inherits the parent's queue, a possibly-held lock and no flusher thread.
os.register_at_fork(after_in_child=_reset_state)


def _warn(msg: str) -> None:
    global _last_warn
    now = time.monotonic()
    if now - _last_warn >= 60:
        _last_warn = now
        logger.warning("model_trace: %s (dropped so far: %d)", msg, _dropped)


def _ensure_thread() -> None:
    global _thread, _pid
    if _pid and _pid != os.getpid():  # fork without the hook (belt and braces)
        _reset_state()
    with _lock:
        if _thread is not None and _thread.is_alive():
            return
        _pid = os.getpid()
        _thread = threading.Thread(target=_loop, args=(_wake,), name="model-trace", daemon=True)
        _thread.start()


def _loop(wake: threading.Event) -> None:
    me = threading.current_thread()
    while _thread is me:  # superseded (reset / restarted) -> exit
        wake.wait(_WAKE_EVERY)
        wake.clear()
        if _thread is not me:
            return
        _drain()


def _drain(deadline: float | None = None) -> None:
    global _qbytes
    while deadline is None or time.monotonic() < deadline:
        batch, size = [], 0
        with _lock:
            while _q and len(batch) < _BATCH and (not batch or size + len(_q[0]) + 1 <= _MAX_BATCH_BYTES):
                b = _q.popleft()
                _qbytes -= len(b)
                batch.append(b)
                size += len(b) + 1
        if not batch:
            return
        _post(batch)


def _post(calls: list) -> None:
    global _dropped
    try:
        body = b'{"source":' + json.dumps(_cfg["source"]).encode() + b',"calls":[' + b",".join(calls) + b"]}"
        req = urllib.request.Request(
            _cfg["url"], data=body,
            headers={"Content-Type": "application/json", **_cfg["headers"]}, method="POST",
        )
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
            raw = r.read(65536)
        try:
            rejected = json.loads(raw).get("rejected", 0)
        except Exception:  # noqa: BLE001
            rejected = 0
        if isinstance(rejected, int) and rejected > 0:
            _warn(f"backend rejected {rejected} of {len(calls)} calls")
    except Exception as e:  # noqa: BLE001 — tracing must never surface
        _dropped += len(calls)
        _warn(f"post failed ({len(calls)} calls dropped): {e}")


def _strip_none(v):
    if isinstance(v, dict):
        return {k: _strip_none(x) for k, x in v.items() if x is not None}
    if isinstance(v, list):
        return [_strip_none(x) for x in v]
    return v


def _cap_embedding(call: dict) -> None:
    emb = call.get("embedding")
    if not isinstance(emb, dict) or not isinstance(emb.get("texts"), list):
        return
    kept, total = [], 0
    for t in emb["texts"]:
        s = t if isinstance(t, str) else str(t)
        if total + len(s) > _MAX_EMBED_CHARS:
            call["embedding"] = {**emb, "texts": kept, "truncated": True}
            return
        kept.append(s)
        total += len(s)


def record(**call_fields) -> None:
    """Queue one call (wire-format field names). Never raises."""
    global _dropped, _qbytes
    try:
        if not _cfg["enabled"]:
            return
        call = _strip_none(call_fields)
        _cap_embedding(call)
        call.setdefault("ts", datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))
        try:
            b = json.dumps(call, ensure_ascii=False, allow_nan=False, default=str).encode()
        except Exception:  # noqa: BLE001 — unencodable (NaN, cycles, ...)
            b = None
        if b is None or len(b) > _MAX_BATCH_BYTES:
            _dropped += 1
            _warn("call not sent: " + ("could not be encoded" if b is None else "too large"))
            return
        _ensure_thread()
        with _lock:
            while _q and (len(_q) >= _MAX_QUEUE or _qbytes + len(b) > _MAX_QUEUE_BYTES):
                _qbytes -= len(_q.popleft())
                _dropped += 1
            _q.append(b)
            _qbytes += len(b)
            full = len(_q) >= _WAKE_AT
        if full:
            _wake.set()
    except Exception as e:  # noqa: BLE001
        _warn(f"record failed: {e}")


def flush(timeout: float = 5) -> None:
    try:
        if _cfg["enabled"]:
            _drain(time.monotonic() + timeout)
    except Exception as e:  # noqa: BLE001
        _warn(f"flush failed: {e}")


atexit.register(flush)
