"""
Quick debug script to test API endpoints with detailed output.
"""
import asyncio
import json
import traceback
from datetime import datetime, timedelta, timezone

import httpx
from jose import jwt

# Config
API_BASE = "http://localhost:8000"
JWT_SECRET = "your-garage-jwt-secret-here"
JWT_ALGORITHM = "HS256"
JWT_AUDIENCE = "garage-platform"

TEST_USER_ID = "user_test_001"
TEST_ORG_ID = "org_test_001"
TEST_WORKSPACE_ID = "ws_test_001"
TEST_MEETING_ID = "meeting_test_debug"


def make_token():
    """Create test JWT."""
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


async def test_session_create():
    """Test session creation with full error details."""
    token = make_token()
    print(f"\n=== Testing Session Creation ===")
    print(f"Token: {token[:50]}...")
    print(f"User ID: {TEST_USER_ID}")
    print(f"Org ID: {TEST_ORG_ID}")
    print(f"Workspace ID: {TEST_WORKSPACE_ID}")
    print(f"Meeting ID: {TEST_MEETING_ID}\n")

    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(
                f"{API_BASE}/api/v1/copilot/sessions",
                json={
                    "garage_meeting_id": TEST_MEETING_ID,
                    "workspace_id": TEST_WORKSPACE_ID,
                },
                headers={"Authorization": f"Bearer {token}"},
                timeout=10,
            )

            print(f"Status Code: {resp.status_code}")
            print(f"Headers: {dict(resp.headers)}")

            if resp.status_code == 200 or resp.status_code == 201:
                print(f"Response: {json.dumps(resp.json(), indent=2)}")
            else:
                print(f"Error Response: {resp.text}")

        except Exception as e:
            print(f"Exception: {e}")
            traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(test_session_create())
