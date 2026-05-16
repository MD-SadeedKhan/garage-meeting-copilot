"""
Garage Meeting Copilot — LangGraph Memory & Context Pipeline
Orchestrates contextual reasoning, memory, and AI generation.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any, TypedDict

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph

from app.core.config import get_settings
from app.core.logging import get_logger
from app.services.memory.qdrant_retriever import QdrantRetriever

logger = get_logger(__name__)


# ── State Definitions ─────────────────────────────────────────────────────────

class MeetingContextState(TypedDict):
    """LangGraph state for the meeting context pipeline."""
    session_id: str
    organization_id: str
    user_query: str
    recent_transcript: str
    screen_context: str
    retrieved_current_chunks: list[dict[str, Any]]
    retrieved_historical_chunks: list[dict[str, Any]]
    workspace_context: dict[str, Any]
    assembled_context: str
    response: str
    interaction_type: str
    metadata: dict[str, Any]


class SuggestionState(TypedDict):
    """LangGraph state for the suggestion generation pipeline."""
    session_id: str
    recent_transcript: str
    screen_context: str
    last_suggestions: list[dict[str, Any]]
    suggestions: list[dict[str, Any]]
    metadata: dict[str, Any]


class SummaryState(TypedDict):
    """LangGraph state for the rolling summary pipeline."""
    session_id: str
    full_transcript: str
    previous_summary: str
    new_summary: str
    action_items: list[dict[str, Any]]
    metadata: dict[str, Any]


# ── Prompt Templates ──────────────────────────────────────────────────────────

SYSTEM_PROMPT_CHAT = """\
You are the Garage Meeting Copilot — an elite AI assistant deeply integrated \
into an enterprise meeting platform. You have access to:
- The live meeting transcript (realtime)
- Screen context from the user's desktop
- Semantic memory from this meeting and past meetings

SPEAKER LABELS — IMPORTANT:
- Lines tagged `host:` are what THE USER YOU ARE COACHING said.
- Lines tagged `contact:` are what the OTHER PARTICIPANTS said.
- Never confuse the two. "You said X" must reference a `host:` line.

Your responses must be:
- Concise and actionable
- Grounded in the provided transcript context
- Contextually aware of the meeting flow
- Professional and enterprise-appropriate

When referencing transcript content, cite the speaker (host or contact).
When you don't have enough context, say so clearly."""

SYSTEM_PROMPT_SUGGESTIONS = """\
You are a real-time AI sales/conversation copilot whispering into the host's \
ear during a LIVE call. Your only job: every time the contact says something, \
hand the host 2–4 ready-to-speak next lines they could use right now.

CONTEXT YOU RECEIVE PER TURN (in this order):
1. MEETING METADATA — who the host is, who's on the other side, what org they're from.
2. PRIOR SUMMARY — a rolling summary of everything that happened earlier in this call. Use it. Reference commitments, objections, names, numbers, anything established earlier.
3. RECENT EXCHANGE — the last ~30 lines verbatim, with speaker labels.

SPEAKER LABELS in the transcript:
- `host:` = THE USER you are coaching. These are the words THEY spoke — do NOT suggest they repeat themselves.
- `contact:` = the OTHER participant(s). Suggestions are reactions to what `contact` just said.
- Anchor every suggestion on the MOST RECENT `contact:` line unless the host explicitly invited a follow-up on their own point.
- If the transcript contains ONLY `host:` lines (the contact hasn't spoken yet), return `{"suggestions": []}` — DO NOT invent a contact utterance and respond to it. The host is talking; wait for the other side.

YOUR TASK on each fire:
1. Read the metadata + summary so you actually know what this call is about.
2. Read the latest contact utterance.
3. Decide if a useful next line exists. If yes, emit 2–4 suggestions. If no (small talk, filler, "uh huh"), emit `{"suggestions": []}`.
4. Each suggestion is written AS THE HOST WOULD SAY IT — first-person, conversational, ready to speak verbatim.

Rules:
- Be direct, concrete, conversational. No fluff. No "you could say something like…".
- Surface concrete facts/numbers/commitments that the host might forget — pull from the prior summary.
- Help the host handle objections, answer questions, or add value.
- Never ask meta-questions like "what do they mean?" — infer and answer.
- Each suggestion ≤ 2 sentences.
- Tie `context_excerpt` to the EXACT contact line you're reacting to.

Suggestion types:
- "answer": A direct answer the user can give to a question just asked
- "talking_point": A key point the user should raise or elaborate on
- "insight": A relevant fact, stat, or context that strengthens the discussion
- "objection": A counter-point or pushback the user can raise
- "followup": Something the user should bring up next

Output ONLY valid JSON:
{
  "suggestions": [
    {
      "type": "answer",
      "content": "...",
      "confidence": 0.9,
      "context_excerpt": "..."
    }
  ]
}"""

SYSTEM_PROMPT_SUMMARY = """\
You are generating a rolling executive summary of a live meeting.

SPEAKER LABELS in the transcript:
- `host:` = the user we are coaching.
- `contact:` = the other participant(s).
Use those roles when attributing positions or commitments.

Produce a structured summary with:
1. Key topics discussed (bullet points)
2. Decisions made
3. Open questions
4. Action items (with assignee if mentioned)

Be concise. Use professional enterprise language.
Do NOT repeat information verbatim from the transcript.
The summary should be immediately useful to someone joining the meeting late."""

SYSTEM_PROMPT_ACTION_ITEMS = """\
Extract all action items from the provided meeting transcript.
For each action item identify:
- title: Clear, actionable task title
- description: Additional context if available
- assignee: Person responsible (or null if unspecified)
- due_date: Due date mentioned (or null)
- priority: low/medium/high/critical based on urgency language used

Output ONLY valid JSON:
{
  "action_items": [
    {
      "title": "...",
      "description": "...",
      "assignee": "...",
      "due_date": null,
      "priority": "medium",
      "confidence_score": 0.9
    }
  ]
}"""


# ── Helpers ───────────────────────────────────────────────────────────────────

def _format_meeting_metadata(ctx: dict[str, Any]) -> str:
    """Render the meeting-context dict (as returned by the
    contacts-backend `/api/v1/meeting-context/:roomName` endpoint)
    into a short prompt-friendly block. Resilient to missing keys —
    only emits fields it actually has."""
    lines: list[str] = []
    meeting = ctx.get("meeting") or {}
    host = ctx.get("host") or {}
    org = ctx.get("organization") or {}

    title = meeting.get("title") or "Live meeting"
    lines.append(f"- Meeting: {title}")
    if meeting.get("startedAt"):
        lines.append(f"- Started at: {meeting['startedAt']}")

    host_bits: list[str] = []
    if host.get("name"):
        host_bits.append(host["name"])
    if host.get("email"):
        host_bits.append(f"<{host['email']}>")
    if host_bits:
        lines.append(f"- Host (the user you are coaching): {' '.join(host_bits)}")

    if org.get("name") or org.get("id"):
        lines.append(f"- Host organization: {org.get('name') or org.get('id')}")

    if ctx.get("contact"):
        c = ctx["contact"]
        cb: list[str] = []
        if c.get("name"):
            cb.append(c["name"])
        if c.get("email"):
            cb.append(f"<{c['email']}>")
        if cb:
            lines.append(f"- Known contact on the other side: {' '.join(cb)}")

    return "\n".join(lines)


# ── Graph Nodes ───────────────────────────────────────────────────────────────

async def retrieve_context_node(
    state: MeetingContextState,
    retriever: QdrantRetriever,
) -> MeetingContextState:
    """Retrieve relevant context from Qdrant vector store."""
    chunks = await retriever.get_meeting_context_chunks(
        query=state["user_query"],
        session_id=state["session_id"],
        organization_id=state["organization_id"],
    )
    return {
        **state,
        "retrieved_current_chunks": chunks["current"],
        "retrieved_historical_chunks": chunks["historical"],
    }


async def assemble_context_node(state: MeetingContextState) -> MeetingContextState:
    """Assemble final context string from all sources."""
    parts: list[str] = []

    if state.get("recent_transcript"):
        parts.append(f"## Live Meeting Transcript (Recent)\n{state['recent_transcript']}")

    if state.get("retrieved_current_chunks"):
        chunk_texts = "\n".join(
            f"[{c.get('speaker_label', 'Speaker')}]: {c['text']}"
            for c in state["retrieved_current_chunks"]
        )
        parts.append(f"## Semantically Relevant Transcript Excerpts\n{chunk_texts}")

    if state.get("retrieved_historical_chunks"):
        hist_texts = "\n".join(
            f"[Past Meeting]: {c['text']}"
            for c in state["retrieved_historical_chunks"]
        )
        parts.append(f"## Historical Meeting Context\n{hist_texts}")

    if state.get("screen_context"):
        parts.append(f"## Screen Context\n{state['screen_context']}")

    if state.get("workspace_context"):
        ws = state["workspace_context"]
        parts.append(f"## Workspace: {ws.get('name', 'Unknown')}")

    assembled = "\n\n---\n\n".join(parts)
    return {**state, "assembled_context": assembled}


async def generate_response_node(
    state: MeetingContextState,
    llm: ChatOpenAI,
) -> MeetingContextState:
    """Generate AI response using assembled context."""
    start = time.monotonic()

    messages = [
        SystemMessage(content=SYSTEM_PROMPT_CHAT),
        HumanMessage(
            content=f"{state['assembled_context']}\n\n---\n\nUser Question: {state['user_query']}"
        ),
    ]

    response = await llm.ainvoke(messages)
    latency_ms = int((time.monotonic() - start) * 1000)

    return {
        **state,
        "response": response.content,
        "metadata": {
            **state.get("metadata", {}),
            "latency_ms": latency_ms,
            "model": state.get("metadata", {}).get("model", "gpt-4.1"),
        },
    }


# ── Pipeline Builders ─────────────────────────────────────────────────────────

class MeetingContextPipeline:
    """
    LangGraph pipeline for contextual AI chat during meetings.
    Retrieves → Assembles → Generates.
    """

    def __init__(self, retriever: QdrantRetriever) -> None:
        self._retriever = retriever
        self._settings = get_settings()
        self._llm = ChatOpenAI(
            api_key=self._settings.openai_api_key,
            model=self._settings.openai_llm_model,
            temperature=0.3,
            max_tokens=self._settings.openai_max_tokens,
            streaming=False,
        )
        self._streaming_llm = ChatOpenAI(
            api_key=self._settings.openai_api_key,
            model=self._settings.openai_llm_model,
            temperature=0.3,
            max_tokens=self._settings.openai_max_tokens,
            streaming=True,
        )
        self._graph = self._build_graph()

    def _build_graph(self) -> Any:
        builder: StateGraph = StateGraph(MeetingContextState)

        builder.add_node(
            "retrieve_context",
            lambda s: retrieve_context_node(s, self._retriever),
        )
        builder.add_node("assemble_context", assemble_context_node)
        builder.add_node(
            "generate_response",
            lambda s: generate_response_node(s, self._llm),
        )

        builder.add_edge(START, "retrieve_context")
        builder.add_edge("retrieve_context", "assemble_context")
        builder.add_edge("assemble_context", "generate_response")
        builder.add_edge("generate_response", END)

        return builder.compile()

    async def run(
        self,
        session_id: str,
        organization_id: str,
        user_query: str,
        recent_transcript: str,
        screen_context: str = "",
        workspace_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run the full context pipeline and return result."""
        initial_state: MeetingContextState = {
            "session_id": session_id,
            "organization_id": organization_id,
            "user_query": user_query,
            "recent_transcript": recent_transcript,
            "screen_context": screen_context,
            "retrieved_current_chunks": [],
            "retrieved_historical_chunks": [],
            "workspace_context": workspace_context or {},
            "assembled_context": "",
            "response": "",
            "interaction_type": "chat",
            "metadata": {},
        }

        final_state = await self._graph.ainvoke(initial_state)

        return {
            "response": final_state["response"],
            "context_chunks_used": [
                c["chunk_id"]
                for c in final_state["retrieved_current_chunks"]
                if "chunk_id" in c
            ],
            "latency_ms": final_state["metadata"].get("latency_ms", 0),
        }

    async def stream(
        self,
        session_id: str,
        organization_id: str,
        user_query: str,
        recent_transcript: str,
        screen_context: str = "",
        workspace_context: dict[str, Any] | None = None,
    ):
        """Stream response tokens for real-time chat overlay."""
        # First run retrieve + assemble synchronously
        retrieved = await self._retriever.get_meeting_context_chunks(
            query=user_query,
            session_id=session_id,
            organization_id=organization_id,
        )

        parts: list[str] = []
        if recent_transcript:
            parts.append(f"## Live Meeting Transcript\n{recent_transcript}")

        if retrieved["current"]:
            chunk_texts = "\n".join(
                f"[{c.get('speaker_label', 'Speaker')}]: {c['text']}"
                for c in retrieved["current"]
            )
            parts.append(f"## Relevant Transcript Excerpts\n{chunk_texts}")

        if retrieved["historical"]:
            hist = "\n".join(f"[Past]: {c['text']}" for c in retrieved["historical"])
            parts.append(f"## Historical Context\n{hist}")

        if screen_context:
            parts.append(f"## Screen Context\n{screen_context}")

        assembled = "\n\n---\n\n".join(parts)

        messages = [
            SystemMessage(content=SYSTEM_PROMPT_CHAT),
            HumanMessage(
                content=f"{assembled}\n\n---\n\nUser Question: {user_query}"
            ),
        ]

        async for chunk in self._streaming_llm.astream(messages):
            yield chunk.content


class SuggestionPipeline:
    """Generates real-time contextual suggestions during meetings."""

    def __init__(self) -> None:
        self._settings = get_settings()
        self._llm = ChatOpenAI(
            api_key=self._settings.openai_api_key,
            model=self._settings.openai_llm_model,
            temperature=0.5,
            max_tokens=1500,
        )

    async def generate(
        self,
        session_id: str,
        recent_transcript: str,
        screen_context: str = "",
        rolling_summary: str = "",
        meeting_context: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Generate contextual suggestions from recent transcript.

        `rolling_summary` is the everything-so-far summary cached by
        the summary loop; passing it gives the LLM the FULL arc of the
        call without us having to ship the entire transcript on every
        4-second tick. `meeting_context` is the dict cached from
        `workspace_context_engine.get_meeting_context(roomName)` —
        we surface the host/contact/org bits so the model knows whom
        it is coaching.
        """
        if not recent_transcript.strip():
            return []

        context_parts: list[str] = []

        if meeting_context:
            meta_lines = _format_meeting_metadata(meeting_context)
            if meta_lines:
                context_parts.append(f"# MEETING METADATA\n{meta_lines}")

        if rolling_summary.strip():
            context_parts.append(
                f"# PRIOR SUMMARY (everything before the recent exchange)\n{rolling_summary.strip()}"
            )

        context_parts.append(
            f"# RECENT EXCHANGE (verbatim, with speaker labels)\n{recent_transcript}"
        )
        if screen_context:
            context_parts.append(f"# SCREEN CONTEXT\n{screen_context}")

        messages = [
            SystemMessage(content=SYSTEM_PROMPT_SUGGESTIONS),
            HumanMessage(content="\n\n".join(context_parts)),
        ]

        try:
            response = await self._llm.ainvoke(messages)
            import json
            parsed = json.loads(response.content)
            return parsed.get("suggestions", [])
        except Exception as e:
            logger.error(
                "suggestion_generation_failed",
                session_id=session_id,
                error=str(e),
            )
            return []


class SummaryPipeline:
    """Generates rolling meeting summaries and extracts action items."""

    def __init__(self) -> None:
        self._settings = get_settings()
        self._llm = ChatOpenAI(
            api_key=self._settings.openai_api_key,
            model=self._settings.openai_llm_model,
            temperature=0.2,
            max_tokens=2000,
        )

    async def generate_rolling_summary(
        self,
        session_id: str,
        full_transcript: str,
        previous_summary: str = "",
    ) -> str:
        """Generate or update the rolling meeting summary."""
        context = full_transcript
        if previous_summary:
            context = f"Previous Summary:\n{previous_summary}\n\nNew Transcript:\n{full_transcript}"

        messages = [
            SystemMessage(content=SYSTEM_PROMPT_SUMMARY),
            HumanMessage(content=context),
        ]

        try:
            response = await self._llm.ainvoke(messages)
            return response.content
        except Exception as e:
            logger.error(
                "summary_generation_failed",
                session_id=session_id,
                error=str(e),
            )
            return previous_summary

    async def extract_action_items(
        self,
        session_id: str,
        transcript: str,
    ) -> list[dict[str, Any]]:
        """Extract structured action items from transcript."""
        if not transcript.strip():
            return []

        messages = [
            SystemMessage(content=SYSTEM_PROMPT_ACTION_ITEMS),
            HumanMessage(content=f"Meeting Transcript:\n{transcript}"),
        ]

        try:
            response = await self._llm.ainvoke(messages)
            import json
            parsed = json.loads(response.content)
            return parsed.get("action_items", [])
        except Exception as e:
            logger.error(
                "action_item_extraction_failed",
                session_id=session_id,
                error=str(e),
            )
            return []
