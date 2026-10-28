import asyncio
import functools
import json
import os
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, SystemMessage

from app.services import model_trace as mt


def arun(f):
    # The repo has no pytest-asyncio; drive coroutines with asyncio.run.
    @functools.wraps(f)
    def w(*a, **k):
        return asyncio.run(f(*a, **k))
    return w


class _Sink:
    def __init__(self, status=202):
        self.bodies, self.headers, sink = [], [], self

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                n = int(self.headers["Content-Length"])
                sink.bodies.append(json.loads(self.rfile.read(n)))
                sink.headers.append(dict(self.headers))
                self.send_response(status)
                self.end_headers()
                self.wfile.write(b"{}")

            def log_message(self, *a):
                pass

        self.srv = HTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.srv.server_port}/internal/traces"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def close(self):
        self.srv.shutdown()


@pytest.fixture
def sink():
    s = _Sink()
    yield s
    s.close()


@pytest.fixture(autouse=True)
def reset():
    mt._reset()
    yield
    mt._reset()


def _call(**kw):
    return dict(site="copilot.summary", kind="chat", provider="openai", model="m", latencyMs=5, **kw)


def test_off_means_no_thread_no_queue():
    mt.configure(False, "http://127.0.0.1:1/x", {}, "meeting-copilot")
    mt.record(**_call())
    assert mt._thread is None and len(mt._q) == 0


def test_queue_bounded_drops_oldest():
    mt.configure(True, "http://127.0.0.1:1/x", {"Authorization": "Bearer k"}, "meeting-copilot")
    with patch.object(mt, "_ensure_thread"):
        for i in range(510):
            mt.record(**_call(refId=str(i)))
    assert len(mt._q) == 500 and mt._dropped == 10
    assert mt._q[0]["refId"] == "10"


def test_post_matches_wire_format(sink):
    mt.configure(True, sink.url, {"Authorization": "Bearer k"}, "meeting-copilot")
    mt.record(**_call(userId=None, turnId="t1", usage={"inTok": 1, "outTok": 2}))
    mt.flush()
    body = sink.bodies[0]
    assert body["source"] == "meeting-copilot"
    c = body["calls"][0]
    assert c["turnId"] == "t1" and c["site"] == "copilot.summary" and "userId" not in c
    assert re.match(r"\d{4}-\d\d-\d\dT", c["ts"])
    assert sink.headers[0]["Authorization"] == "Bearer k"


def test_batches_of_50(sink):
    mt.configure(True, sink.url, {"Authorization": "Bearer k"}, "meeting-copilot")
    with patch.object(mt, "_ensure_thread"):
        for _ in range(120):
            mt.record(**_call())
    mt.flush()
    assert [len(b["calls"]) for b in sink.bodies] == [50, 50, 20]


def test_background_thread_flushes(sink):
    mt.configure(True, sink.url, {"Authorization": "Bearer k"}, "meeting-copilot")
    for _ in range(20):
        mt.record(**_call())
    for _ in range(50):
        if sink.bodies:
            break
        time.sleep(0.1)
    assert sink.bodies and mt._thread.daemon


def test_failure_swallowed():
    mt.configure(True, "http://127.0.0.1:1/x", {"Authorization": "Bearer k"}, "meeting-copilot")
    mt.record(**_call())
    mt.flush(timeout=1)  # must not raise


def test_record_never_raises():
    mt.configure(True, "http://127.0.0.1:1/x", {"Authorization": "Bearer k"}, "meeting-copilot")
    with patch.object(mt, "_ensure_thread", side_effect=RuntimeError):
        mt.record(**_call())


def test_pid_change_restarts_thread(sink):
    mt.configure(True, sink.url, {"Authorization": "Bearer k"}, "meeting-copilot")
    mt.record(**_call())
    first = mt._thread
    with patch.object(mt.os, "getpid", return_value=os.getpid() + 1):
        mt.record(**_call())
    assert mt._thread is not first and mt._thread.is_alive()


def test_trace_enabled_from_settings(monkeypatch):
    from app.core.config import get_settings

    s = get_settings()
    monkeypatch.setattr(s, "model_trace", True, raising=False)
    monkeypatch.setattr(s, "contacts_backend_service_secret", "sek")
    monkeypatch.setattr(s, "contacts_backend_base_url", "http://127.0.0.1:9/")
    mt._configured = False
    mt.trace(**_call())
    assert mt._cfg == {
        "enabled": True,
        "url": "http://127.0.0.1:9/internal/traces",
        "headers": {"Authorization": "Bearer sek"},
        "source": "meeting-copilot",
    }


def test_trace_off_without_secret(monkeypatch):
    from app.core.config import get_settings

    s = get_settings()
    monkeypatch.setattr(s, "model_trace", True, raising=False)
    monkeypatch.setattr(s, "contacts_backend_service_secret", None)
    mt._configured = False
    mt.trace(**_call())
    assert not mt._cfg["enabled"] and mt._thread is None


# ── pipeline wiring ───────────────────────────────────────────────────────────

@pytest.fixture
def traced():
    calls = []
    with patch("app.services.model_trace.trace", side_effect=lambda **k: calls.append(k)), \
         patch("app.services.ai.langgraph_pipeline.trace", side_effect=lambda **k: calls.append(k)), \
         patch("app.services.memory.qdrant_retriever.trace", side_effect=lambda **k: calls.append(k)):
        yield calls


def _ai(text="hi"):
    m = AIMessage(content=text)
    m.usage_metadata = {"input_tokens": 3, "output_tokens": 4, "total_tokens": 7}
    return m


def test_openai_messages_mapping():
    from app.services.ai.langgraph_pipeline import _to_openai
    out = _to_openai([SystemMessage(content="s"), HumanMessage(content="u")])
    assert out == [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]


@arun
async def test_summary_traced(traced):
    from app.services.ai import langgraph_pipeline as lp
    p = lp.SummaryPipeline()
    p._llm = MagicMock(ainvoke=AsyncMock(return_value=_ai("sum")))
    await p.generate_rolling_summary("sess", "tx", user_id="u1")
    c = traced[0]
    assert c["site"] == "copilot.summary" and c["kind"] == "chat" and c["provider"] == "openai"
    assert c["output"] == {"text": "sum"} and c["usage"] == {"inTok": 3, "outTok": 4}
    assert c["userId"] == "u1" and c["turnId"] == "sess"
    assert c["messages"][0]["role"] == "system" or c["system"]


@arun
async def test_summary_error_traced_and_swallowed(traced):
    from app.services.ai import langgraph_pipeline as lp
    p = lp.SummaryPipeline()
    p._llm = MagicMock(ainvoke=AsyncMock(side_effect=RuntimeError("boom")))
    assert await p.generate_rolling_summary("sess", "tx", previous_summary="prev") == "prev"
    assert traced[0]["error"]["message"] == "boom"


@arun
async def test_action_items_and_suggestion_traced(traced):
    from app.services.ai import langgraph_pipeline as lp
    s = lp.SummaryPipeline()
    s._llm = MagicMock(ainvoke=AsyncMock(return_value=_ai('{"action_items": []}')))
    await s.extract_action_items("sess", "tx")
    g = lp.SuggestionPipeline()
    g._llm = MagicMock(ainvoke=AsyncMock(return_value=_ai('{"suggestions": []}')))
    await g.generate("sess", "hello")
    assert [c["site"] for c in traced] == ["copilot.action_items", "copilot.suggestion"]


@arun
async def test_graph_node_traced(traced):
    from app.services.ai import langgraph_pipeline as lp
    llm = MagicMock(ainvoke=AsyncMock(return_value=_ai("ans")))
    state = {"assembled_context": "ctx", "user_query": "q", "session_id": "sess", "metadata": {}}
    await lp.generate_response_node(state, llm)
    assert traced[0]["site"] == "copilot.context" and traced[0]["turnId"] == "sess"


@arun
async def test_stream_traced_once_with_ttft(traced):
    from app.services.ai import langgraph_pipeline as lp
    p = lp.MeetingContextPipeline.__new__(lp.MeetingContextPipeline)
    p._settings = lp.get_settings()
    p._retriever = MagicMock(get_meeting_context_chunks=AsyncMock(return_value={"current": [], "historical": []}))

    async def gen(_m):
        yield AIMessageChunk(content="a")
        yield AIMessageChunk(content="b", usage_metadata={"input_tokens": 1, "output_tokens": 2, "total_tokens": 3})

    p._streaming_llm = MagicMock(astream=gen)
    out = [t async for t in p.stream("sess", "org", "q", "tx")]
    assert out == ["a", "b"]
    assert len(traced) == 1
    c = traced[0]
    assert c["site"] == "copilot.context_stream" and c["kind"] == "stream"
    assert c["output"]["text"] == "ab" and c["ttftMs"] >= 0 and c["usage"] == {"inTok": 1, "outTok": 2}


@arun
async def test_embed_traced(traced):
    from app.services.memory.qdrant_retriever import QdrantRetriever
    r = QdrantRetriever()
    resp = SimpleNamespace(data=[SimpleNamespace(embedding=[0.1])], usage=SimpleNamespace(total_tokens=9))
    r._openai = MagicMock(embeddings=MagicMock(create=AsyncMock(return_value=resp)))
    await r.embed_text(" hi ", user_id="u1", session_id="sess")
    await r.embed_texts(["a", "b"])
    c = traced[0]
    assert c["site"] == "copilot.embed" and c["kind"] == "embedding"
    assert c["embedding"] == {"texts": ["hi"]} and c["usage"]["inTok"] == 9 and c["userId"] == "u1"
    assert traced[1]["embedding"] == {"texts": ["a", "b"]}


def test_coverage_guard_no_other_model_clients():
    root = Path(__file__).resolve().parents[1] / "app"
    allowed = {"services/ai/langgraph_pipeline.py", "services/memory/qdrant_retriever.py"}
    bad = [str(p) for p in root.rglob("*.py")
           if p.relative_to(root).as_posix() not in allowed
           and re.search(r"\b(ChatOpenAI|AsyncOpenAI|OpenAI)\(", p.read_text())]
    assert bad == []
