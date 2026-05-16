"""
Garage Meeting Copilot — End-to-End Test Script

Run from ai-service directory with venv activated:
  python test_e2e.py

Tests:
  1. Health check (DB, Redis, Qdrant)
  2. JWT generation (mimics Garage auth)
  3. Create session via API
  4. Send transcript chunk
  5. Trigger AI suggestion
  6. Get suggestions
  7. Print frontend URL with session hash
"""
from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import httpx
from jose import jwt

# ── Config ─────────────────────────────────────────────────────────────────────

API_BASE = "http://localhost:8000"
WS_GATEWAY = "ws://localhost:8000"

# Must match .env values
JWT_SECRET = "your-garage-jwt-secret-here"
JWT_ALGORITHM = "HS256"
JWT_AUDIENCE = "garage-platform"

# Test identities
TEST_USER_ID = "user_test_001"
TEST_ORG_ID = "org_test_001"
TEST_WORKSPACE_ID = "ws_test_001"
TEST_MEETING_ID = "meeting_test_" + str(int(time.time()))


# ── JWT Generator ───────────────────────────────────────────────────────────────

def make_test_token() -> str:
    """Create a JWT that matches what Garage would issue."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": TEST_USER_ID,
        "org": TEST_ORG_ID,
        "workspace": TEST_WORKSPACE_ID,
        "email": "test@garage.dev",
        "roles": ["member"],
        "aud": JWT_AUDIENCE,
        "iat": now,
        "exp": now + timedelta(hours=24),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


# ── Tests ───────────────────────────────────────────────────────────────────────

async def test_health(client: httpx.AsyncClient) -> bool:
    print("\n[1] Health Check...")
    resp = await client.get(f"{API_BASE}/health")
    data = resp.json()
    status = data.get("status")
    checks = data.get("checks", {})
    print(f"    Status  : {status}")
    print(f"    Database: {'✓' if checks.get('database') else '✗'}")
    print(f"    Redis   : {'✓' if checks.get('redis') else '✗'}")
    print(f"    Qdrant  : {'✓' if checks.get('qdrant') else '✗'}")
    if status not in ("ok", "degraded"):
        print("    FAIL: health endpoint returned unexpected status")
        return False
    print("    PASS")
    return True


async def test_create_session(client: httpx.AsyncClient, token: str) -> str | None:
    print("\n[2] Create Session...")
    resp = await client.post(
        f"{API_BASE}/api/v1/copilot/sessions",
        json={"garage_meeting_id": TEST_MEETING_ID, "workspace_id": TEST_WORKSPACE_ID},
        headers={"Authorization": f"Bearer {token}"},
    )
    if resp.status_code not in (200, 201):
        print(f"    FAIL: {resp.status_code} — {resp.text}")
        return None
    session = resp.json()
    session_id = session.get("id")
    print(f"    Session ID : {session_id}")
    print(f"    Meeting ID : {session.get('garage_meeting_id')}")
    print(f"    Status     : {session.get('status')}")
    print("    PASS")
    return session_id


async def test_ingest_transcript(client: httpx.AsyncClient, token: str, session_id: str) -> bool:
    print("\n[3] Ingest Transcript Chunk...")
    resp = await client.post(
        f"{API_BASE}/api/v1/copilot/sessions/{session_id}/transcript",
        json={
            "text": "Let's discuss the Q3 roadmap. We need to ship the new authentication module by end of July.",
            "speaker_label": "Speaker 1",
            "start_time": 0.0,
            "end_time": 6.5,
            "confidence": 0.97,
            "is_final": True,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    if resp.status_code not in (200, 201):
        print(f"    FAIL: {resp.status_code} — {resp.text}")
        return False
    print(f"    Response: {resp.json()}")
    print("    PASS")
    return True


async def test_get_transcript(client: httpx.AsyncClient, token: str, session_id: str) -> bool:
    print("\n[4] Get Transcript...")
    resp = await client.get(
        f"{API_BASE}/api/v1/copilot/sessions/{session_id}/transcript",
        headers={"Authorization": f"Bearer {token}"},
    )
    if resp.status_code != 200:
        print(f"    FAIL: {resp.status_code} — {resp.text}")
        return False
    chunks = resp.json()
    print(f"    Chunks: {len(chunks)}")
    if chunks:
        print(f"    First chunk: \"{chunks[0].get('text', '')[:60]}...\"")
    print("    PASS")
    return True


async def test_ai_suggestions(client: httpx.AsyncClient, token: str, session_id: str) -> bool:
    print("\n[5] Request AI Suggestions...")
    resp = await client.post(
        f"{API_BASE}/api/v1/copilot/sessions/{session_id}/suggest",
        json={
            "transcript_window": "Let's discuss the Q3 roadmap. We need to ship the new authentication module by end of July.",
            "context": "Engineering planning meeting",
        },
        headers={"Authorization": f"Bearer {token}"},
        timeout=30.0,
    )
    if resp.status_code not in (200, 201):
        print(f"    FAIL: {resp.status_code} — {resp.text}")
        return False
    result = resp.json()
    suggestions = result.get("suggestions", [])
    print(f"    Suggestions received: {len(suggestions)}")
    for i, s in enumerate(suggestions[:3], 1):
        print(f"    [{i}] ({s.get('type', '?')}) {s.get('content', '')[:80]}")
    print("    PASS")
    return True


async def test_ocr_endpoint(client: httpx.AsyncClient, token: str, session_id: str) -> bool:
    print("\n[6] OCR Screen Context (no image, expect 422)...")
    resp = await client.post(
        f"{API_BASE}/api/v1/copilot/sessions/{session_id}/screen",
        headers={"Authorization": f"Bearer {token}"},
        # No body - intentionally testing validation
    )
    # 422 means the endpoint exists but validation failed (expected without image data)
    if resp.status_code in (200, 201, 422):
        print(f"    Status {resp.status_code} — endpoint reachable ✓")
        print("    PASS")
        return True
    print(f"    FAIL: {resp.status_code} — {resp.text}")
    return False


async def main():
    print("=" * 60)
    print("  Garage Meeting Copilot — E2E Test Suite")
    print("=" * 60)

    token = make_test_token()
    print(f"\n  JWT Token (first 50 chars): {token[:50]}...")

    results: dict[str, bool] = {}

    async with httpx.AsyncClient(timeout=15.0) as client:
        results["health"] = await test_health(client)
        if not results["health"]:
            print("\n✗ Backend not reachable. Is uvicorn running on :8000?")
            return

        session_id = await test_create_session(client, token)
        results["create_session"] = session_id is not None

        if session_id:
            results["ingest_transcript"] = await test_ingest_transcript(client, token, session_id)
            results["get_transcript"] = await test_get_transcript(client, token, session_id)
            results["ai_suggestions"] = await test_ai_suggestions(client, token, session_id)
            results["ocr_endpoint"] = await test_ocr_endpoint(client, token, session_id)

    # ── Summary ────────────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("  Results")
    print("=" * 60)
    passed = 0
    for name, ok in results.items():
        icon = "✓" if ok else "✗"
        print(f"  {icon} {name}")
        if ok:
            passed += 1
    print(f"\n  {passed}/{len(results)} tests passed")

    if session_id:
        gateway_url = quote(f"{WS_GATEWAY}/ws/copilot", safe="")
        frontend_url = (
            f"http://localhost:1420/#"
            f"token={token}"
            f"&session_id={session_id}"
            f"&meeting_id={TEST_MEETING_ID}"
            f"&user_id={TEST_USER_ID}"
            f"&org_id={TEST_ORG_ID}"
            f"&gateway_url={gateway_url}"
        )
        print("\n" + "=" * 60)
        print("  Frontend URL (open this in your browser):")
        print("=" * 60)
        print(f"\n  {frontend_url}\n")
        print("  This will connect the UI to the session you just created.")
        print("  You should see the status change from 'Offline' to 'Live'.")


if __name__ == "__main__":
    asyncio.run(main())
