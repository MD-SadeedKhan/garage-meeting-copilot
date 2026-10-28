import asyncio
import functools
import json
import os
import re
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


# ── pipeline wiring ───────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset():
    mt._reset()
    yield
    mt._reset()


@pytest.fixture
def traced():
    calls = []
    with patch("app.services.ai.langgraph_pipeline.record", side_effect=lambda **k: calls.append(k)), \
         patch("app.services.memory.qdrant_retriever.record", side_effect=lambda **k: calls.append(k)):
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


@arun
async def test_stream_closed_early_records_aborted_partial(traced):
    from app.services.ai import langgraph_pipeline as lp
    p = lp.MeetingContextPipeline.__new__(lp.MeetingContextPipeline)
    p._settings = lp.get_settings()
    p._retriever = MagicMock(get_meeting_context_chunks=AsyncMock(return_value={"current": [], "historical": []}))

    async def gen(_m):
        for t in "abcd":
            yield AIMessageChunk(content=t)

    p._streaming_llm = MagicMock(astream=gen)
    g = p.stream("sess", "org", "q", "tx")
    assert [await g.__anext__(), await g.__anext__()] == ["a", "b"]
    await g.aclose()
    assert len(traced) == 1
    assert traced[0]["output"] == {"text": "ab", "finishReason": "aborted"}


@arun
async def test_stream_error_records_aborted_with_error(traced):
    from app.services.ai import langgraph_pipeline as lp
    p = lp.MeetingContextPipeline.__new__(lp.MeetingContextPipeline)
    p._settings = lp.get_settings()
    p._retriever = MagicMock(get_meeting_context_chunks=AsyncMock(return_value={"current": [], "historical": []}))

    async def gen(_m):
        yield AIMessageChunk(content="a")
        raise RuntimeError("drop")

    p._streaming_llm = MagicMock(astream=gen)
    with pytest.raises(RuntimeError):
        [t async for t in p.stream("sess", "org", "q", "tx")]
    assert len(traced) == 1
    assert traced[0]["output"] == {"text": "a", "finishReason": "aborted"} and traced[0]["error"]["message"] == "drop"


def test_configure_tracing_from_settings(monkeypatch):
    from app.core.config import get_settings
    from app.services.trace_setup import configure_tracing

    s = get_settings()
    monkeypatch.setattr(s, "model_trace", "1", raising=False)
    monkeypatch.setattr(s, "contacts_backend_service_secret", "sek")
    monkeypatch.setattr(s, "contacts_backend_base_url", "http://127.0.0.1:9/")
    assert not mt._cfg["enabled"]  # nothing traces until startup opts in
    configure_tracing()
    assert mt._cfg == {"enabled": True, "url": "http://127.0.0.1:9/internal/traces",
                       "headers": {"Authorization": "Bearer sek"}, "source": "meeting-copilot"}
    monkeypatch.setattr(s, "contacts_backend_service_secret", None)
    configure_tracing()
    assert not mt._cfg["enabled"]


def test_tracing_on_by_default_and_model_trace_0_turns_it_off(monkeypatch):
    from app.core.config import Settings, get_settings
    from app.services.trace_setup import configure_tracing

    assert Settings.model_fields["model_trace"].default == "1"
    s = get_settings()
    monkeypatch.setattr(s, "contacts_backend_service_secret", "sek")
    monkeypatch.setattr(s, "model_trace", "0", raising=False)
    configure_tracing()
    assert not mt._cfg["enabled"]
