"""
Model-trace client: queues model calls in memory and POSTs them in batches to
contacts-backend `POST /internal/traces`.

Off unless MODEL_TRACE=1 and a URL and key are configured. Never blocks,
never raises into a caller. Stdlib only.
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

_cfg: dict = {"enabled": False, "url": "", "headers": {}, "source": ""}
_q: collections.deque = collections.deque(maxlen=_MAX_QUEUE)
_dropped = 0
_lock = threading.Lock()
_wake = threading.Event()
_thread: threading.Thread | None = None
_pid = 0
_last_warn = 0.0
_configured = False


def configure(enabled: bool, url: str, headers: dict, source: str) -> None:
    global _cfg
    _cfg = {"enabled": bool(enabled and url and headers), "url": url, "headers": headers, "source": source}


def _reset() -> None:
    """Test helper: back to the pristine, off state."""
    global _q, _dropped, _thread, _pid, _last_warn, _configured, _lock, _wake
    _q = collections.deque(maxlen=_MAX_QUEUE)
    _dropped, _thread, _pid, _last_warn, _configured = 0, None, 0, 0.0, False
    _lock, _wake = threading.Lock(), threading.Event()
    configure(False, "", {}, "")


def _warn(msg: str) -> None:
    global _last_warn
    now = time.monotonic()
    if now - _last_warn >= 60:
        _last_warn = now
        logger.warning("model_trace: %s", msg)


def _ensure_thread() -> None:
    global _thread, _pid, _q, _lock, _wake
    pid = os.getpid()
    if _thread is not None and _pid == pid and _thread.is_alive():
        return
    if _pid and _pid != pid:
        # Forked child: the parent's queue/lock/event are not ours.
        _q = collections.deque(maxlen=_MAX_QUEUE)
        _lock, _wake = threading.Lock(), threading.Event()
    _pid = pid
    _thread = threading.Thread(target=_loop, name="model-trace", daemon=True)
    _thread.start()


def _loop() -> None:
    wake = _wake
    while True:
        wake.wait(_WAKE_EVERY)
        wake.clear()
        _drain()


def _drain(deadline: float | None = None) -> None:
    while deadline is None or time.monotonic() < deadline:
        with _lock:
            batch = [_q.popleft() for _ in range(min(_BATCH, len(_q)))]
        if not batch:
            return
        _post(batch)


def _post(calls: list) -> None:
    try:
        req = urllib.request.Request(
            _cfg["url"],
            data=json.dumps({"source": _cfg["source"], "calls": calls}).encode(),
            headers={"Content-Type": "application/json", **_cfg["headers"]},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=_TIMEOUT).close()
    except Exception as e:  # noqa: BLE001 — tracing must never surface
        _warn(f"post failed ({len(calls)} calls dropped): {e}")


def record(**call_fields) -> None:
    """Queue one call (Wire-format field names). Never raises."""
    global _dropped
    try:
        if not _cfg["enabled"]:
            return
        call = {k: v for k, v in call_fields.items() if v is not None}
        call.setdefault("ts", datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))
        _ensure_thread()
        with _lock:
            if len(_q) == _q.maxlen:
                _dropped += 1
            _q.append(call)
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


# ── meeting-copilot config wiring ─────────────────────────────────────────────

def trace(**call_fields) -> None:
    """record() after lazily configuring from settings (reuses the usage-ledger URL + secret)."""
    global _configured
    try:
        if not _configured:
            from app.core.config import get_settings

            s = get_settings()
            secret = s.contacts_backend_service_secret
            configure(
                bool(s.model_trace and secret),
                str(s.contacts_backend_base_url).rstrip("/") + "/internal/traces",
                {"Authorization": f"Bearer {secret}"} if secret else {},
                "meeting-copilot",
            )
            _configured = True
    except Exception as e:  # noqa: BLE001
        _warn(f"configure failed: {e}")
        return
    record(**call_fields)
