"""Satisfy `Settings` so the app package can be imported without a deployment.

`app.core.config` requires six settings at import time, and every module
reaches it through `app.core.logging`. Without these the suite cannot even be
collected, let alone run on a laptop or in CI.

The values are deliberately obvious placeholders. Nothing here connects to
anything — the tests under test never open a socket, and a test that needed a
real database or key would belong with the connectivity scripts in the repo
root instead.
"""
from __future__ import annotations

import os

# Settings enforces a 32-character minimum on the secrets.
os.environ.setdefault("SECRET_KEY", "test-not-a-real-secret-000000000000")
os.environ.setdefault("GARAGE_JWT_SECRET", "test-not-a-real-secret-000000000000")
os.environ.setdefault("OPENAI_API_KEY", "test-not-a-real-key")
os.environ.setdefault("DEEPGRAM_API_KEY", "test-not-a-real-key")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test/test")
os.environ.setdefault("REDIS_URL", "redis://test")
