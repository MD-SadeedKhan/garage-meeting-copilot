# 🚀 Garage Meeting Copilot — Complete Setup & Launch Guide

## ✅ System Status

| Component | Status | Port | Notes |
|-----------|--------|------|-------|
| **Backend (FastAPI)** | ✅ Running | 8000 | `app.main:app` |
| **Frontend (React/Vite)** | ⏸️ Ready | 1420 | Use `npm run dev` |
| **Desktop Agent (PyQt6)** | ✅ Ready | - | Python replacement for Rust |
| **Database (PostgreSQL)** | ✅ Running | 5432 | Migrations applied ✓ |
| **Redis** | ✅ Running | 6379 | Session state |
| **Qdrant (Vector DB)** | ⚠️ Unhealthy | 6333 | May need restart |

---

## 📋 Prerequisites

✅ All dependencies installed:
- Backend venv: `/ai-service/venv/`
- Frontend node_modules: `/desktop-agent/node_modules/`
- Desktop dependencies: PyQt6, sounddevice, websockets, cryptography

---

## 🏃 Quick Start (3 Terminals)

### Terminal 1: Start Backend
```bash
cd c:\Users\sadid\garage-meeting-copilot\ai-service

# Run backend (already running on :8000)
venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

**Expected output:**
```
Uvicorn running on http://0.0.0.0:8000
Application startup complete
```

**Test:**
```bash
curl http://localhost:8000/health
```

---

### Terminal 2: Start Frontend
```bash
cd c:\Users\sadid\garage-meeting-copilot\desktop-agent

# Start Vite dev server on :1420
npm run dev
```

**Expected output:**
```
  VITE v6.4.2  ready in XXX ms

  ➜  Local:   http://localhost:1420/
  ➜  Network: use --host to expose
```

**Access:** Open browser → `http://localhost:1420/`

---

### Terminal 3: Start Desktop Agent (Optional)

```bash
cd c:\Users\sadid\garage-meeting-copilot\ai-service

# Method 1: Using PowerShell launcher (recommended)
.\launch_desktop_agent.ps1 -SessionID "test_session_123" -Token "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."

# Method 2: Using Python directly
venv\Scripts\python.exe desktop_agent.py "http://localhost:1420/#token=YOUR_JWT&session_id=YOUR_SESSION_ID&gateway_url=ws://localhost:8000/ws/copilot"
```

---

## 🧪 Testing the System

### Health Check
```bash
cd c:\Users\sadid\garage-meeting-copilot\ai-service
venv\Scripts\python.exe -c "import httpx; print(httpx.get('http://localhost:8000/health').json())"
```

### Run E2E Tests
```bash
cd c:\Users\sadid\garage-meeting-copilot\ai-service

# Set encoding for Unicode output (Windows fix)
$env:PYTHONIOENCODING = "utf-8"

# Run all tests
venv\Scripts\python.exe test_e2e.py
```

**Expected:** ✅ All 6 tests passing (health, session, transcript, suggest, etc.)

---

## 📁 File Structure

### Backend (`/ai-service`)
```
app/
├── main.py              # FastAPI app entry point ✅
├── gateway.py           # WebSocket handler ✅
├── api/v1/
│   ├── endpoints/
│   │   ├── sessions.py  # POST /api/v1/copilot/sessions ✅
│   │   ├── ocr.py       # POST /api/v1/copilot/screen ✅
│   │   └── exports.py   # Other endpoints ✅
│   └── router.py        # Route aggregation ✅
├── services/
│   ├── ai/
│   │   └── langgraph_pipeline.py  # AI suggestions ✅
│   ├── ocr/
│   │   └── screen_ocr.py          # Screen capture ✅
│   └── memory/
│       └── qdrant_retriever.py    # Vector search ✅
└── repositories/
    └── copilot_repo.py  # DB queries ✅

venv/                   # Python virtual environment ✅
requirements.txt        # All deps installed ✅
desktop_agent.py        # Python desktop agent ✅
launch_desktop_agent.ps1 # PowerShell launcher ✅
launch_desktop_agent.bat # Windows batch launcher ✅
```

### Frontend (`/desktop-agent`)
```
src/
├── App.tsx              # Main React component
├── hooks/
│   ├── useGatewayWebSocket.ts  # WS connection
│   ├── useGlobalHotkeys.ts     # Keyboard shortcuts
│   └── useScreenCapture.ts     # Screen grab
├── components/
│   ├── overlay/
│   │   └── CopilotOverlay.tsx  # Main overlay UI
│   └── ...
├── stores/              # Zustand state
└── lib/
    ├── garageIntegration.tsx  # Garage auth
    └── utils.ts

node_modules/           # All npm deps installed ✅
package.json            # Scripts ✅
vite.config.ts          # Dev server config ✅
.env                    # API URLs ✅
```

### Desktop Agent (`/ai-service/desktop_agent.py`)
**Full Python replacement for Rust/Tauri:**
- ✅ `CopilotApp` — Window manager, system tray, overlay lifecycle
- ✅ `AudioCaptureEngine` — WASAPI audio capture, chunking
- ✅ `WebSocketStreamer` — Real-time audio streaming to backend
- ✅ `OverlayManager` — Always-on-top window positioning
- ✅ `IPCBridge` — All 9 IPC commands (mirrors Tauri invoke handlers)
- ✅ `SecureStorage` — AES-256-GCM encryption

---

## 🔧 Environment Configuration

### Frontend (`.env`)
```env
VITE_API_BASE_URL=http://localhost:8000
VITE_GATEWAY_WS_URL=ws://localhost:8000/ws/copilot
```
✅ Configured

### Backend (`.env` in `ai-service/`)
```env
DATABASE_URL=postgresql://copilot:copilot@localhost:5432/copilot
REDIS_URL=redis://localhost:6379
QDRANT_URL=http://localhost:6333
DEEPGRAM_API_KEY=your_key_here
OPENAI_API_KEY=your_key_here
JWT_SECRET=your-garage-jwt-secret-here
```
⚠️ Check that `.env` has valid API keys

### Desktop Agent
No config needed — uses environment variables or CLI args:
```bash
SESSION_ID=<id> GARAGE_TOKEN=<jwt> GATEWAY_URL=ws://localhost:8000/ws/copilot python desktop_agent.py
```

---

## 🐳 Docker Services

All services running in Docker:
```bash
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
```

**If services crashed, restart:**
```bash
docker-compose up -d
```

---

## ✅ Verification Checklist

Before running the app:

- [ ] **Backend running** → `netstat -ano | findstr 8000`
- [ ] **Database healthy** → Health check returns `"database": true`
- [ ] **Redis working** → Health check returns `"redis": true`
- [ ] **Frontend .env configured** → `.env` points to `http://localhost:8000`
- [ ] **Desktop dependencies installed** → `pip list | grep -E "PyQt6|sounddevice|websockets"`
- [ ] **E2E tests pass** → `python test_e2e.py` shows 6/6 ✓
- [ ] **Migrations applied** → `alembic upgrade head` completed

---

## 🚨 Troubleshooting

### Backend won't start
```bash
# Check if port 8000 is in use
netstat -ano | findstr :8000

# Kill existing process
taskkill /pid <PID> /f

# Restart backend
cd ai-service
venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### Frontend won't start
```bash
# Clear node_modules cache
rm -Recurse node_modules
npm install

# Restart Vite
npm run dev
```

### Desktop agent won't launch
```bash
# Check PyQt6 installation
python -c "import PyQt6; print('OK')"

# Check required packages
pip list | grep -E "PyQt6|sounddevice|websockets|numpy|cryptography"

# If missing, reinstall
pip install PyQt6==6.7.1 PyQt6-WebEngine==6.7.0 sounddevice numpy websockets cryptography
```

### Connection refused on localhost:8000
```bash
# Backend might have crashed
docker logs copilot-postgres  # Check DB
docker logs copilot-redis     # Check Redis

# Restart containers
docker-compose down
docker-compose up -d
```

---

## 📊 Expected Flow

1. **User opens** `http://localhost:1420/` in browser
2. **Frontend connects** to backend WebSocket at `ws://localhost:8000/ws/copilot`
3. **Status shows "Live"** (not "Reconnecting")
4. **User clicks "Start Session"** → POST `/api/v1/copilot/sessions`
5. **Backend returns** `session_id` + `gateway_url`
6. **Frontend receives** hash params: `?token=...&session_id=...`
7. **Desktop agent launches** with those params (optional)
8. **Desktop app connects** to WebSocket, streams audio/screen in real-time
9. **Backend processes** via LangGraph → OpenAI → Qdrant → UI suggestions

---

## 🎯 Next Steps

1. ✅ **Verify all services running** → Follow "Quick Start" above
2. ✅ **Run E2E tests** → `python test_e2e.py` (should be 6/6 passing)
3. ✅ **Test in browser** → `http://localhost:1420/`
4. ✅ **Launch desktop agent** (optional) → See Terminal 3 above

---

## 📞 Support

If you encounter issues:
1. Check this guide's Troubleshooting section
2. Review `test_e2e.py` for expected API behavior
3. Check backend logs: `docker logs copilot-postgres` / `docker logs copilot-redis`
4. Verify environment variables are set correctly

---

**Ready to launch! 🚀**
