# Garage Meeting Copilot

**Enterprise-grade realtime AI meeting copilot subsystem for the Garage ecosystem.**

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                    GARAGE ECOSYSTEM                             │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐       │
│  │   Auth   │  │  Users   │  │   Orgs   │  │Workspaces│       │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘       │
└────────────────────────────┬────────────────────────────────────┘
                             │ JWT / API Integration
┌────────────────────────────▼────────────────────────────────────┐
│              GARAGE MEETING COPILOT SUBSYSTEM                   │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │              DESKTOP AGENT (Tauri v2 / Rust)            │   │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐  │   │
│  │  │  Audio   │ │ Overlay  │ │  Screen  │ │Websocket │  │   │
│  │  │ Capture  │ │ Engine   │ │   OCR    │ │ Streaming│  │   │
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────┘  │   │
│  └─────────────────────────────────────────────────────────┘   │
│                          │ WSS / HTTPS                          │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │              AI SERVICE LAYER (FastAPI / Python)         │   │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐  │   │
│  │  │Realtime  │ │Deepgram  │ │LangGraph │ │ Qdrant   │  │   │
│  │  │ Gateway  │ │ Service  │ │ Pipeline │ │Retrieval │  │   │
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────┘  │   │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐  │   │
│  │  │  Redis   │ │Postgres  │ │   S3     │ │  NGINX   │  │   │
│  │  │  State   │ │ Storage  │ │Artifacts │ │  Proxy   │  │   │
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────┘  │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

## Tech Stack

### Desktop Agent
- **Framework**: Tauri v2
- **Languages**: Rust + TypeScript
- **Frontend**: React 19, Vite, Tailwind CSS, ShadCN UI, Framer Motion, Zustand, TanStack Query
- **Audio**: WASAPI (Windows), CoreAudio (macOS), PipeWire/PulseAudio (Linux)

### AI Service Layer
- **Framework**: FastAPI + Python 3.12
- **LLM**: OpenAI GPT-4.1
- **Orchestration**: LangGraph
- **Transcription**: Deepgram Streaming API
- **OCR**: OpenCV + Tesseract
- **Vector DB**: Qdrant + OpenAI text-embedding-3-large
- **Cache**: Redis
- **Database**: PostgreSQL
- **Storage**: AWS S3

### Infrastructure
- Docker + Docker Compose
- NGINX reverse proxy

## Quick Start

```bash
# 1. Configure environment
cp .env.example .env
# Edit .env with your credentials

# 2. Start infrastructure
docker-compose up -d

# 3. Run database migrations
docker-compose exec meeting-ai-service alembic upgrade head

# 4. Build desktop agent
cd desktop-agent
npm install
npm run tauri build
```

## Integration with Garage

The copilot subsystem integrates via:
- **JWT Middleware**: Validates Garage-issued JWTs on all endpoints
- **Garage API Client**: Fetches workspace/meeting context from Garage APIs
- **WebSocket Gateway**: Extends Garage's existing WS infrastructure
- **Embeddable Modules**: React components embeddable in Garage frontend

## Module Documentation

- [Desktop Agent](./desktop-agent/README.md)
- [AI Service](./ai-service/README.md)
- [Infrastructure](./infrastructure/README.md)
