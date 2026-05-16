import asyncio
import redis.asyncio as r
from app.core.config import get_settings

async def main():
    s = get_settings()
    c = await r.from_url(s.redis_url)
    deleted = await c.delete(
        "rl:ws:user_test_001",
        "copilot:session:1f43a42f-3e62-4464-8376-b4639dbe3250"
    )
    print(f"Flushed {deleted} key(s)")
    await c.aclose()

asyncio.run(main())
