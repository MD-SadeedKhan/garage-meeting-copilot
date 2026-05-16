# Python Desktop Agent Setup

## Overview
The Rust/Tauri code has been replaced with pure Python using PyQt6 for the desktop overlay and WebSocket streaming.

## Requirements
- Python 3.11+
- pip

## Installation

### 1. Create Python Virtual Environment
```bash
cd C:\Users\sadid\garage-meeting-copilot\desktop-agent
python -m venv venv
.\venv\Scripts\activate
```

### 2. Install Dependencies
```bash
pip install -r requirements-desktop.txt
```

## Running the Application

### Option A: Quick Start (Windows)
```bash
launch.bat
```

### Option B: Manual Start

**Terminal 1 - Start Vite Frontend Dev Server:**
```bash
cd C:\Users\sadid\garage-meeting-copilot\desktop-agent
npm run dev
```
The frontend will be available at `http://localhost:1420/`

**Terminal 2 - Start Backend (if not already running):**
```bash
cd C:\Users\sadid\garage-meeting-copilot\ai-service
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

**Terminal 3 - Start Python Desktop Agent:**
```bash
cd C:\Users\sadid\garage-meeting-copilot\desktop-agent
.\venv\Scripts\activate
python python_desktop_agent.py "http://localhost:1420/#token=YOUR_TOKEN&session_id=YOUR_SESSION&gateway_url=ws://localhost:8000/ws/copilot"
```

## What Changed

### From Rust/Tauri:
- ❌ `src-tauri/src/main.rs` - Tauri app entry
- ❌ `src-tauri/src/ipc/mod.rs` - IPC handlers
- ❌ `src-tauri/src/audio/capture.rs` - CPAL audio capture
- ❌ `src-tauri/src/overlay/manager.rs` - Tauri overlay

### To Python:
- ✅ `python_desktop_agent.py` - Complete desktop agent
- ✅ Audio capture: `sounddevice` library
- ✅ Desktop overlay: PyQt6 WebEngineView
- ✅ Screenshot: PIL/Pillow
- ✅ WebSocket: `websockets` library

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│ Garage Meeting Copilot - Python Desktop Agent               │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ PyQt6 Overlay Window (Always-on-Top, Transparent)      │ │
│  │ ├─ WebEngineView: React Frontend (http://localhost:1420)
│  │ └─ WebChannel: Python ↔ JS Communication               │ │
│  └─────────────────────────────────────────────────────────┘ │
│                                                               │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ Audio Capture (sounddevice)                             │ │
│  │ ├─ Microphone (WASAPI/CoreAudio/ALSA)                 │ │
│  │ ├─ Sample Rate: 16kHz Mono (Deepgram requirement)      │ │
│  │ └─ Audio Streaming Thread                              │ │
│  └─────────────────────────────────────────────────────────┘ │
│                                                               │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ WebSocket Connection to Backend                         │ │
│  │ ├─ URL: ws://localhost:8000/ws/copilot                │ │
│  │ ├─ Audio streaming (base64 encoded)                    │ │
│  │ ├─ Screen capture transmission                         │ │
│  │ └─ Session management                                  │ │
│  └─────────────────────────────────────────────────────────┘ │
│                                                               │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ Desktop Services                                         │ │
│  │ ├─ Screen Capture (PIL/Pillow)                         │ │
│  │ ├─ Device Management                                   │ │
│  │ └─ Status Monitoring                                   │ │
│  └─────────────────────────────────────────────────────────┘ │
│                                                               │
└─────────────────────────────────────────────────────────────┘
             │
             │ WebSocket
             ▼
    ┌──────────────────────┐
    │ Backend (FastAPI)    │
    │ ├─ Sessions API      │
    │ ├─ WebSocket /ws/*   │
    │ ├─ Transcript Ingest │
    │ ├─ AI Suggestions    │
    │ └─ OCR Screen        │
    └──────────────────────┘
```

## Features

✅ **Cross-Platform Audio Capture**
- Windows: WASAPI
- macOS: CoreAudio
- Linux: PipeWire/ALSA

✅ **Always-On-Top Overlay**
- Transparent background
- Frameless window
- Desktop integration

✅ **Real-time Streaming**
- WebSocket connection to backend
- Audio chunks at 100ms intervals
- Base64 encoding for JSON transmission

✅ **Screen Capture**
- Primary monitor capture
- PNG compression
- On-demand transmission

✅ **Desktop Bridge**
- Python ↔ JavaScript communication
- Device enumeration
- Status monitoring

## Troubleshooting

### "No module named 'PyQt6'"
```bash
pip install PyQt6 PyQt6-WebEngine
```

### "No module named 'sounddevice'"
```bash
pip install sounddevice numpy
```

### "WebSocket connection refused"
- Ensure backend is running: `python -m uvicorn app.main:app --port 8000`
- Check gateway URL in launch command

### "Screen capture not working"
- Ensure PIL/Pillow is installed: `pip install Pillow`
- On Linux, may need: `pip install pyautogui`

### Audio not captured
- Check available devices: `python -c "import sounddevice; print(sounddevice.query_devices())"`
- Verify microphone is connected and enabled

## Future Improvements

1. **Persistent Configuration**: Store session/token in encrypted local storage
2. **Hotkey Support**: Global hotkey registration (Ctrl+Shift+G)
3. **Notification Integration**: Desktop notifications for suggestions
4. **Advanced Audio**: Multi-channel capture, noise suppression
5. **Logging**: Detailed logging to file for debugging
6. **Auto-Update**: Version checking and self-update mechanism
