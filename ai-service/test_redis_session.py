#!/usr/bin/env python3
"""Test if session exists in Redis."""

import asyncio
import os
from app.core.redis import RedisStreamState, get_redis
from app.core.config import get_settings

async def main():
    settings = get_settings()
    redis = get_redis()
    redis_state = RedisStreamState(redis)
    
    session_id = "1f43a42f-3e62-4464-8376-b4639dbe3250"
    
    print(f"\n🔍 Checking session: {session_id}")
    print(f"   Expected key: copilot:session:{session_id}\n")
    
    try:
        session_data = await redis_state.get_session(session_id)
        print(f"✓ Session data found: {session_data}\n")
        
        if session_data:
            for k, v in session_data.items():
                print(f"   {k}: {v}")
    except Exception as e:
        print(f"✗ Error getting session: {e}\n")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
