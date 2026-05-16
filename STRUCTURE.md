# Garage Meeting Copilot — Project Structure

```
garage-meeting-copilot/
│
├── .env.example                          # Environment variable template
├── docker-compose.yml                    # Full production stack
├── README.md                             # Architecture overview
│
├── ai-service/                           # Python FastAPI backend
│   ├── Dockerfile                        # Multi-stage production image
│   ├── requirements.txt                  # All Python dependencies
│   ├── alembic.ini                       # Alembic config
│   │
│   ├── alembic/                          # Database migrations
│   │   ├── env.py                        # Async migration runner
│   │   └── versions/
│   │       └── 001_initial.py            # Initial schema migration
│   │
│   └── app/
│       ├── __init__.py
│       ├── main.py                       # FastAPI app + all REST endpoints
│       ├── gateway.py                    # Realtime WebSocket gateway
│       │
│       ├── core/
│       │   ├── config.py                 # Pydantic settings (env-based)
│       │   ├── database.py               # AsyncSQLAlchemy engine + sessions
│       │   ├── logging.py                # Structlog configuration
│       │   └── redis.py                  # Redis client + stream state
│       │
│       ├── middleware/
│       │   ├── garage_auth.py            # Garage JWT validator + API client
│       │   └── rate_limit.py             # Redis sliding-window rate limiter
│       │
│       ├── models/
│       │   └── copilot.py                # All SQLAlchemy ORM models
│       │
│       ├── schemas/
│       │   └── copilot.py                # All Pydantic request/response schemas
│       │
│       ├── repositories/
│       │   └── copilot_repo.py           # Data access layer (repository pattern)
│       │
│       ├── api/
│       │   └── v1/
│       │       ├── router.py             # API router aggregator
│       │       └── endpoints/
│       │           ├── ocr.py            # Screenshot OCR endpoint
│       │           └── exports.py        # Transcript/summary/S3 export endpoints
│       │
│       ├── services/
│       │   ├── transcription/
│       │   │   └── deepgram_service.py   # Deepgram streaming session manager
│       │   │
│       │   ├── ai/
│       │   │   ├── langgraph_pipeline.py # LangGraph context + suggestion + summary pipelines
│       │   │   └── workspace_context.py  # Garage workspace context fetcher/cache
│       │   │
│       │   ├── memory/
│       │   │   └── qdrant_retriever.py   # Qdrant vector indexing + semantic retrieval
│       │   │
│       │   ├── ocr/
│       │   │   └── screen_ocr.py         # OpenCV + Tesseract OCR pipeline
│       │   │
│       │   └── storage/
│       │       └── s3_storage.py         # AWS S3 artifact storage
│       │
│       └── integrations/
│           └── garage/                   # Garage ecosystem integration utilities
│
├── desktop-agent/                        # Tauri v2 native desktop agent
│   ├── package.json                      # Node dependencies
│   ├── vite.config.ts                    # Vite bundler config
│   ├── tsconfig.json                     # TypeScript config
│   ├── tsconfig.node.json
│   ├── tailwind.config.js                # Tailwind CSS config
│   ├── index.html                        # HTML entry point
│   │
│   ├── src-tauri/                        # Rust native layer
│   │   ├── Cargo.toml                    # Rust dependencies
│   │   ├── tauri.conf.json               # Tauri v2 app configuration
│   │   └── src/
│   │       ├── main.rs                   # App entry point + setup
│   │       ├── audio/
│   │       │   ├── mod.rs
│   │       │   └── capture.rs            # Cross-platform audio capture (CPAL)
│   │       ├── ipc/
│   │       │   └── mod.rs                # Tauri invoke command handlers
│   │       ├── overlay/
│   │       │   ├── mod.rs
│   │       │   └── manager.rs            # Overlay window management
│   │       └── utils/
│   │           ├── mod.rs
│   │           └── crypto.rs             # AES-256-GCM secure storage
│   │
│   └── src/                              # TypeScript / React frontend
│       ├── main.tsx                      # React entry point
│       ├── App.tsx                       # Root component + Tauri event listeners
│       │
│       ├── stores/
│       │   └── index.ts                  # All Zustand stores (session, transcript, chat, ui...)
│       │
│       ├── hooks/
│       │   ├── useGatewayWebSocket.ts    # WebSocket connection + event dispatch
│       │   ├── useScreenCapture.ts       # Periodic screen capture + OCR trigger
│       │   └── useGlobalHotkeys.ts       # Tauri global shortcut registration
│       │
│       ├── components/
│       │   ├── overlay/
│       │   │   ├── CopilotOverlay.tsx    # Main overlay UI (header, tabs, panels)
│       │   │   ├── SessionSetupScreen.tsx # Initial session configuration UI
│       │   │   └── index.ts
│       │   ├── transcript/
│       │   │   └── TranscriptPanel.tsx   # Live transcript with speaker diarization
│       │   ├── suggestions/
│       │   │   └── Panels.tsx            # Suggestions, Summary, Actions, Chat panels
│       │   └── index.ts                  # Component barrel exports
│       │
│       ├── lib/
│       │   ├── utils.ts                  # cn() helper + utilities
│       │   └── garageIntegration.tsx     # Embeddable CopilotLauncher + useCopilotSession
│       │
│       └── styles/
│           └── globals.css               # Tailwind + custom overlay CSS
│
└── infrastructure/
    ├── docker/
    │   ├── postgres/
    │   │   └── init.sql                  # PostgreSQL init + optimisation
    │   └── qdrant/
    │       └── config.yaml               # Qdrant production config
    │
    ├── nginx/
    │   ├── nginx.conf                    # NGINX main config (WebSocket optimised)
    │   └── conf.d/
    │       └── copilot.conf              # Virtual host: API + WS routing
    │
    └── scripts/
        └── setup.sh                      # Automated deployment setup script
```

## Module Responsibilities

### AI Service Layer

| Module | Responsibility |
|--------|----------------|
| `app/main.py` | REST API: sessions, transcripts, summaries, action items, search |
| `app/gateway.py` | WebSocket: audio stream ingestion, AI event broadcasting, chat |
| `app/core/config.py` | Centralised Pydantic settings from environment |
| `app/core/database.py` | Async SQLAlchemy engine, session factory |
| `app/core/redis.py` | Redis client, transcript buffering, pub/sub, session state |
| `app/middleware/garage_auth.py` | Garage JWT validation, auth context injection |
| `app/middleware/rate_limit.py` | Sliding window rate limiting per user/IP |
| `app/services/transcription/deepgram_service.py` | Deepgram WebSocket sessions, transcript streaming |
| `app/services/ai/langgraph_pipeline.py` | LangGraph: context chat, suggestions, summaries, action items |
| `app/services/memory/qdrant_retriever.py` | Vector embeddings, semantic search, cross-meeting retrieval |
| `app/services/ocr/screen_ocr.py` | OpenCV preprocessing + Tesseract OCR pipeline |
| `app/services/storage/s3_storage.py` | AWS S3 artifact uploads and presigned URLs |
| `app/repositories/copilot_repo.py` | Database CRUD for all entities |

### Desktop Agent

| Module | Responsibility |
|--------|----------------|
| `src-tauri/src/main.rs` | Tauri app bootstrap, window creation, tray |
| `src-tauri/src/audio/capture.rs` | WASAPI/CoreAudio/PipeWire audio capture via CPAL |
| `src-tauri/src/ipc/mod.rs` | Tauri command handlers (audio, screen, overlay, config) |
| `src-tauri/src/overlay/manager.rs` | Overlay window position, opacity, stealth mode |
| `src-tauri/src/utils/crypto.rs` | AES-256-GCM encryption for token storage |
| `src/stores/index.ts` | All Zustand state stores |
| `src/hooks/useGatewayWebSocket.ts` | Gateway WS connection, auto-reconnect, event routing |
| `src/hooks/useScreenCapture.ts` | Periodic screen capture + OCR API calls |
| `src/hooks/useGlobalHotkeys.ts` | Tauri global shortcut registration |
| `src/components/overlay/CopilotOverlay.tsx` | Full overlay UI with all panels |
| `src/lib/garageIntegration.tsx` | Embeddable launcher component for Garage frontend |

## Data Flow Diagrams

### Realtime Audio → Transcript Flow
```
User speaks
    ↓
CPAL audio capture (Rust)
    ↓ base64 PCM chunks
Tauri IPC → WebSocket stream
    ↓ ws://gateway/ws/copilot
FastAPI WebSocket Handler
    ↓ raw audio bytes
Deepgram Streaming API
    ↓ partial / final transcripts
Redis RPUSH (transcript buffer)
Redis PUBLISH (broadcast channel)
    ↓ JSON event
WebSocket → Frontend overlay
    ↓ Zustand store
TranscriptPanel renders live
    ↓ (final chunks only)
PostgreSQL persist (background)
Qdrant embed + index (background)
```

### AI Chat Flow
```
User types question in ChatPanel
    ↓ WS {"type":"chat", "message":"..."}
FastAPI gateway _handle_chat()
    ↓ Redis: fetch recent transcript
    ↓ Redis: fetch cached screen context
MeetingContextPipeline.stream()
    ↓ Qdrant: semantic search (current session)
    ↓ Qdrant: cross-meeting historical search
    ↓ Assemble context string
    ↓ GPT-4.1 streaming
Per-token: WS {"event":"chat_token", "token":"..."}
    ↓ ChatStore.appendStreamToken()
    ↓ ChatPanel renders streaming bubble
Final: WS {"event":"chat_complete", "full_response":"..."}
    ↓ ChatStore.finalizeStreamingMessage()
PostgreSQL AIInteraction persist (background)
```

### Background AI Orchestration
```
SessionAIOrchestrator (per session, background tasks)
    │
    ├── Suggestion loop (every 8s)
    │     Redis: last 30 transcript chunks
    │     → SuggestionPipeline.generate()
    │     → GPT-4.1 JSON output
    │     → WS broadcast {"event":"suggestions"}
    │
    ├── Summary loop (every 60s)
    │     Redis: last 100 transcript chunks
    │     → SummaryPipeline.generate_rolling_summary()
    │     → GPT-4.1 structured summary
    │     → WS broadcast {"event":"summary"}
    │     → PostgreSQL persist (background)
    │
    └── Action item loop (every 30s)
          Redis: last 50 transcript chunks
          → SummaryPipeline.extract_action_items()
          → GPT-4.1 JSON extraction
          → WS broadcast {"event":"action_items"}
          → PostgreSQL persist (background)
```
