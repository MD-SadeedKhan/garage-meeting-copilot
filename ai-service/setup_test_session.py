#!/usr/bin/env python
"""Setup test session in Redis for desktop agent testing."""
import asyncio
import sys
from app.core.config import get_settings
import redis.asyncio as aioredis
import json

async def setup_session(session_id: str):
    """Create a test session in Redis."""
    settings = get_settings()
    
    # Connect to Redis
    redis_url = settings.redis_url
    redis = await aioredis.from_url(redis_url, decode_responses=True)
    
    try:
        # Create session key — must match backend prefix copilot:session:<id>
        session_key = f"copilot:session:{session_id}"
        session_data = {
            "session_id": session_id,
            "meeting_id": "test_meeting_001",
            "user_id": "user_test_001",
            "workspace_id": "ws_test_001",
            "created_at": "2026-05-15T09:00:00Z",
        }
        
        # Store in Redis with 4-hour expiration (matches SESSION_TTL)
        await redis.setex(
            session_key,
            14400,  # 4 hours
            json.dumps(session_data)
        )
        
        print(f"[OK] Session created successfully!")
        print(f"  Key: {session_key}")
        print(f"  Session ID: {session_id}")
        print(f"  Meeting ID: test_meeting_001")
        print(f"  User ID: user_test_001")
        
        # Verify
        stored = await redis.get(session_key)
        if stored:
            print(f"[OK] Session verified in Redis")
        else:
            print(f"[FAIL] Session NOT found after creation -- check Redis connection")
        
    finally:
        await redis.close()

if __name__ == "__main__":
    session_id = sys.argv[1] if len(sys.argv) > 1 else "test-session-001"
    asyncio.run(setup_session(session_id))
