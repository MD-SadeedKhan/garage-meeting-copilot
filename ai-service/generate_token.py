"""Generate a fresh JWT token for testing."""
import time
from app.core.config import get_settings
from jose import jwt

settings = get_settings()

now = int(time.time())
payload = {
    "sub": "user_test_001",
    "org": "org_test_001",
    "workspace": "ws_test_001",
    "email": "test@garage.dev",
    "roles": ["member"],
    "aud": settings.garage_jwt_audience,
    "iat": now,
    "exp": now + 86400,  # 24 hours from now
}

token = jwt.encode(payload, settings.garage_jwt_secret, algorithm=settings.garage_jwt_algorithm)
print(f"\nFresh JWT Token (valid 24h):\n{token}\n")
print(f"Use this URL to run the desktop agent:")
print(f'python desktop_agent.py "http://localhost:1420/#token={token}&session_id=1f43a42f-3e62-4464-8376-b4639dbe3250&gateway_url=ws%3A%2F%2Flocalhost%3A8000%2Fws%2Fcopilot"')
