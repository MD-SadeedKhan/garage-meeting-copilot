"""Simple DB connectivity test."""
import asyncio
from sqlalchemy import text
from app.core.database import AsyncSessionLocal

async def test_db():
    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(text('SELECT 1'))
            print(f"✓ Database connection successful: {result.scalar()}")
            
            # Check if tables exist
            result = await db.execute(text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"))
            tables = result.fetchall()
            print(f"✓ Tables in database: {len(tables)}")
            for (table,) in tables:
                print(f"  - {table}")
    except Exception as e:
        print(f"✗ Database error: {e}")

asyncio.run(test_db())
