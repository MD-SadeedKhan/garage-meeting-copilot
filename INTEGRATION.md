# Garage Meeting Copilot — Integration Guide

## Overview

This subsystem integrates into the existing Garage platform as a **pluggable AI module**.
It does NOT own authentication, users, organizations, workspaces, or meetings.
It reads from Garage APIs and extends meeting capabilities.

---

## 1. Backend Integration

### JWT Authentication

The copilot validates **Garage-issued JWTs** on every request.
Configure your Garage JWT secret in `.env`:

```env
GARAGE_JWT_SECRET=your-existing-garage-jwt-secret
GARAGE_JWT_ALGORITHM=HS256
GARAGE_JWT_AUDIENCE=garage-platform
```

Your existing Garage JWT payload must contain:
```json
{
  "sub": "user_id",
  "org_id": "organization_id",
  "workspace_id": "optional_workspace_id",
  "email": "user@company.com",
  "roles": ["member"],
  "exp": 1234567890
}
```

### Network Access

The copilot service needs access to the Garage internal API:
```env
GARAGE_API_BASE_URL=https://api.garage.internal
```

It calls these Garage endpoints:
- `GET /api/v1/meetings/{meeting_id}` — meeting context
- `GET /api/v1/workspaces/{workspace_id}` — workspace context
- `GET /api/v1/users/{user_id}` — user profile

### Docker Network

Add the copilot containers to your existing Garage Docker network:

```yaml
# In your existing Garage docker-compose.yml, the network must exist:
networks:
  garage_default:
    driver: bridge

# The copilot docker-compose.yml will attach to it:
networks:
  garage-network:
    external: true
    name: garage_default
```

---

## 2. Frontend Integration

### Option A: Embedded Launch Button (Recommended)

Import and use `CopilotLauncher` in your Garage meeting view:

```tsx
import { CopilotLauncher } from '@/lib/garageIntegration';

// In your MeetingRoom component:
function MeetingRoom({ meeting, user }) {
  return (
    <div>
      {/* ... existing meeting UI ... */}

      <CopilotLauncher
        meetingId={meeting.id}
        token={user.accessToken}
        workspaceId={meeting.workspaceId}
        apiBaseUrl="https://copilot.garage.internal"
        gatewayUrl="wss://copilot.garage.internal/ws/copilot"
        onSessionCreated={(sessionId) => {
          console.log('Copilot session:', sessionId);
        }}
      />
    </div>
  );
}
```

### Option B: Read Copilot Data in Garage UI

Display transcripts and action items within the Garage meeting panel:

```tsx
import { useCopilotSession } from '@/lib/garageIntegration';

function MeetingIntelligencePanel({ sessionId, token }) {
  const { transcript, actionItems, summary, fetchTranscript } =
    useCopilotSession(sessionId, token);

  useEffect(() => {
    const interval = setInterval(fetchTranscript, 5000);
    return () => clearInterval(interval);
  }, [fetchTranscript]);

  return (
    <div>
      <h3>Live Transcript</h3>
      {transcript.map((chunk) => (
        <p key={chunk.id}><strong>{chunk.speaker_label}:</strong> {chunk.text}</p>
      ))}

      <h3>Action Items</h3>
      {actionItems.map((item) => (
        <div key={item.id}>
          <strong>{item.title}</strong> — {item.assignee}
        </div>
      ))}
    </div>
  );
}
```

### Option C: Tauri Deep Link (Desktop-First)

The desktop agent registers a custom URL scheme `garage-copilot://`.
Garage web frontend can trigger it with:

```javascript
// Launches the desktop agent and injects session config
const url = new URL('garage-copilot://init');
url.searchParams.set('session_id', sessionId);
url.searchParams.set('meeting_id', meeting.id);
url.searchParams.set('token', user.accessToken);
url.searchParams.set('gateway_url', 'wss://copilot.garage.internal/ws/copilot');

// Open the deep link
window.location.href = url.toString();
// or: document.createElement('iframe').src = url.toString()
```

---

## 3. REST API Reference

All endpoints require: `Authorization: Bearer <garage_jwt>`

### Sessions

```
POST /api/v1/copilot/sessions
  Body: { "garage_meeting_id": "...", "workspace_id": "..." }
  → Creates session, returns { id, status, started_at, ... }

GET  /api/v1/copilot/sessions/{session_id}
  → Session status

POST /api/v1/copilot/sessions/{session_id}/end
  → Gracefully ends session
```

### Transcripts

```
GET /api/v1/copilot/sessions/{session_id}/transcript
  Params: only_final=true, limit=500
  → [ { text, speaker_label, start_time, end_time, is_final, ... } ]
```

### AI Outputs

```
GET /api/v1/copilot/sessions/{session_id}/summaries
  → [ { content, summary_type, created_at } ]

GET /api/v1/copilot/sessions/{session_id}/action-items
  Params: status_filter=open
  → [ { title, description, assignee, priority, status } ]

GET /api/v1/copilot/sessions/{session_id}/search?q=<query>
  → { results: [ { text, speaker_label, score } ] }
```

### Exports

```
GET  /api/v1/copilot/sessions/{session_id}/export/transcript  → plaintext
GET  /api/v1/copilot/sessions/{session_id}/export/summary     → markdown
GET  /api/v1/copilot/sessions/{session_id}/export/action-items → JSON
POST /api/v1/copilot/sessions/{session_id}/export/s3           → queues S3 export
```

### OCR

```
POST /api/v1/copilot/ocr
  Body: { "session_id": "...", "image_data": "<base64 PNG>" }
  → { cleaned_text, word_count, confidence, application_hint }
```

---

## 4. WebSocket Protocol

Connect: `wss://copilot.garage.internal/ws/copilot?token=<jwt>&session_id=<id>`

### Client → Server Messages

```jsonc
// Stream audio
{ "type": "audio", "session_id": "...", "data": "<base64 PCM>", "sequence": 1, "source": "microphone" }

// Send chat message
{ "type": "chat", "session_id": "...", "message": "What did John say about the budget?" }

// Send screen context
{ "type": "screen_context", "session_id": "...", "extracted_text": "...", "application_name": "Figma" }

// Keepalive
{ "type": "ping" }
```

### Server → Client Events

```jsonc
// Live transcript chunk
{ "event": "transcript", "text": "...", "speaker_label": "Speaker 1", "is_final": true, ... }

// AI suggestions (every ~8s)
{ "event": "suggestions", "suggestions": [ { "type": "question", "content": "...", "confidence": 0.9 } ] }

// Rolling summary (every ~60s)
{ "event": "summary", "content": "## Key Topics\n...", "summary_type": "rolling" }

// Action items (every ~30s)
{ "event": "action_items", "items": [ { "title": "...", "assignee": "...", "priority": "high" } ] }

// Chat streaming
{ "event": "chat_token", "token": "Based", "is_final": false }
{ "event": "chat_complete", "full_response": "Based on the transcript...", "latency_ms": 890 }

// Errors
{ "event": "error", "code": "SESSION_NOT_FOUND", "message": "...", "recoverable": false }
```

---

## 5. Desktop Agent Distribution

The desktop agent is built with Tauri v2 and distributed as:
- **Windows**: `.msi` / `.exe` installer
- **macOS**: `.dmg` / `.app` bundle
- **Linux**: `.AppImage` / `.deb` / `.rpm`

Build for all platforms:
```bash
cd desktop-agent
npm install
npm run tauri build
# Output: src-tauri/target/release/bundle/
```

---

## 6. Environment Variables for Garage DevOps

Add to your Garage infrastructure secrets:

```bash
# Required for copilot subsystem
GARAGE_COPILOT_JWT_SECRET=<same as GARAGE_JWT_SECRET>
OPENAI_API_KEY=sk-...
DEEPGRAM_API_KEY=...
POSTGRES_PASSWORD=<generate: openssl rand -base64 32>
REDIS_PASSWORD=<generate: openssl rand -base64 32>
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
```

---

## 7. Scaling Considerations

The current architecture supports:
- **Horizontal scaling**: Multiple `meeting-ai-service` + `realtime-gateway` replicas
- **Redis pub/sub**: Enables WebSocket messages to reach clients across replicas
- **Qdrant clustering**: Supported in Qdrant Cloud or self-hosted cluster mode
- **Future Kafka**: The Redis pub/sub layer can be replaced with Kafka for higher throughput
- **GPU inference**: The AI service is designed to swap GPT-4.1 for a local model endpoint
- **Multi-region**: Stateless services with Redis + Qdrant + PostgreSQL distributed backends
