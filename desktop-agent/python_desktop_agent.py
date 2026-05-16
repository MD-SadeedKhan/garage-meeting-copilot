#!/usr/bin/env python3
"""
Garage Meeting Copilot — Python Desktop Agent
Replaces Rust/Tauri with PyQt6 for desktop overlay + audio/screen capture
"""

import sys
import json
import asyncio
import logging
import threading
import base64
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, List

import numpy as np
import sounddevice as sd
from PIL import ImageGrab
import websockets
import websockets.client
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWebEngineView, 
    QWidget, QVBoxLayout, QSizePolicy
)
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtCore import Qt, QUrl, QThread, pyqtSignal, QSize, QPoint
from PyQt6.QtGui import QColor
from PyQt6.QtWebChannel import QWebChannel

# ── Configuration ──────────────────────────────────────────────────────────

SAMPLE_RATE = 16000  # Deepgram Nova-3 requirement
CHANNELS = 1  # Mono
CHUNK_DURATION_MS = 100
SAMPLES_PER_CHUNK = (SAMPLE_RATE * CHUNK_DURATION_MS) // 1000

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("CopilotDesktop")

# ── Audio Capture Engine ──────────────────────────────────────────────────

class AudioCaptureEngine:
    """Cross-platform audio capture using sounddevice"""
    
    def __init__(self):
        self.is_running = False
        self.stream = None
        self.audio_queue = None
        self.config = {
            'sample_rate': SAMPLE_RATE,
            'channels': CHANNELS,
            'enable_mic': True,
            'enable_system_audio': False,
        }
    
    def get_devices(self) -> List[Dict]:
        """Get list of available audio devices"""
        devices = sd.query_devices()
        device_list = []
        
        for i, device in enumerate(devices):
            if device['max_input_channels'] > 0:
                device_list.append({
                    'id': str(i),
                    'name': device['name'],
                    'is_default': i == sd.default.device[0],
                    'device_type': 'microphone',
                    'channels': device['max_input_channels']
                })
        
        return device_list
    
    def start_capture(self, mic_device_id: Optional[str] = None) -> bool:
        """Start audio capture"""
        try:
            device_id = int(mic_device_id) if mic_device_id else None
            
            # Create audio queue for buffering
            self.audio_queue = asyncio.Queue()
            
            def audio_callback(indata, frames, time_info, status):
                if status:
                    logger.warning(f"Audio status: {status}")
                # Resample to 16kHz mono if needed
                audio_data = indata[:, 0] if indata.shape[1] > 1 else indata[:, 0]
                # Convert to base64-encoded bytes for transmission
                audio_bytes = (audio_data * 32767).astype(np.int16).tobytes()
                try:
                    asyncio.run_coroutine_threadsafe(
                        self.audio_queue.put(audio_bytes),
                        asyncio.get_event_loop()
                    )
                except:
                    pass
            
            self.stream = sd.InputStream(
                device=device_id,
                samplerate=SAMPLE_RATE,
                channels=CHANNELS,
                blocksize=SAMPLES_PER_CHUNK,
                callback=audio_callback,
                dtype=np.float32
            )
            self.stream.start()
            self.is_running = True
            logger.info(f"Audio capture started on device {device_id}")
            return True
        
        except Exception as e:
            logger.error(f"Failed to start audio capture: {e}")
            return False
    
    def stop_capture(self) -> bool:
        """Stop audio capture"""
        try:
            if self.stream:
                self.stream.stop()
                self.stream.close()
                self.stream = None
            self.is_running = False
            logger.info("Audio capture stopped")
            return True
        except Exception as e:
            logger.error(f"Failed to stop audio capture: {e}")
            return False
    
    async def get_audio_chunk(self) -> Optional[bytes]:
        """Get next audio chunk from queue"""
        if self.audio_queue:
            try:
                return await asyncio.wait_for(
                    self.audio_queue.get(),
                    timeout=0.5
                )
            except asyncio.TimeoutError:
                return None
        return None

# ── WebSocket Streaming ────────────────────────────────────────────────────

class WebSocketStreamer:
    """WebSocket connection for audio/screen streaming to backend"""
    
    def __init__(self, gateway_url: str, session_id: str, token: str):
        self.gateway_url = gateway_url
        self.session_id = session_id
        self.token = token
        self.websocket = None
        self.is_connected = False
        self.sequence_number = 0
    
    async def connect(self) -> bool:
        """Connect to WebSocket gateway"""
        try:
            url = f"{self.gateway_url}?token={self.token}&session_id={self.session_id}"
            self.websocket = await websockets.client.connect(url)
            self.is_connected = True
            logger.info(f"WebSocket connected: {self.session_id}")
            return True
        except Exception as e:
            logger.error(f"WebSocket connection failed: {e}")
            self.is_connected = False
            return False
    
    async def send_audio(self, audio_bytes: bytes) -> bool:
        """Send audio chunk via WebSocket"""
        if not self.is_connected or not self.websocket:
            return False
        
        try:
            message = {
                "type": "audio",
                "session_id": self.session_id,
                "data": base64.b64encode(audio_bytes).decode(),
                "sequence": self.sequence_number,
                "source": "microphone"
            }
            await self.websocket.send(json.dumps(message))
            self.sequence_number += 1
            return True
        except Exception as e:
            logger.error(f"Failed to send audio: {e}")
            self.is_connected = False
            return False
    
    async def send_screen(self, image_base64: str, width: int, height: int) -> bool:
        """Send screen capture via WebSocket"""
        if not self.is_connected or not self.websocket:
            return False
        
        try:
            message = {
                "type": "screen",
                "session_id": self.session_id,
                "image": image_base64,
                "width": width,
                "height": height,
                "sequence": self.sequence_number
            }
            await self.websocket.send(json.dumps(message))
            self.sequence_number += 1
            return True
        except Exception as e:
            logger.error(f"Failed to send screen: {e}")
            self.is_connected = False
            return False
    
    async def disconnect(self):
        """Disconnect from WebSocket"""
        if self.websocket:
            await self.websocket.close()
            self.is_connected = False

# ── Screen Capture ─────────────────────────────────────────────────────────

class ScreenCapture:
    """Cross-platform screen capture"""
    
    @staticmethod
    def capture_primary_monitor() -> Optional[Dict]:
        """Capture primary monitor and return as base64 PNG"""
        try:
            screenshot = ImageGrab.grab()
            width, height = screenshot.size
            
            # Convert to base64
            import io
            buffer = io.BytesIO()
            screenshot.save(buffer, format='PNG')
            image_base64 = base64.b64encode(buffer.getvalue()).decode()
            
            return {
                'image': image_base64,
                'width': width,
                'height': height
            }
        except Exception as e:
            logger.error(f"Screen capture failed: {e}")
            return None

# ── Bridge for Frontend ────────────────────────────────────────────────────

class DesktopBridge:
    """Bridge between React frontend and Python backend"""
    
    def __init__(self, audio_engine: AudioCaptureEngine, streamer: WebSocketStreamer):
        self.audio_engine = audio_engine
        self.streamer = streamer
    
    def get_audio_devices(self) -> Dict:
        """Get available audio devices"""
        devices = self.audio_engine.get_devices()
        return {'success': True, 'devices': devices}
    
    def start_audio_capture(self, device_id: Optional[str] = None) -> Dict:
        """Start audio capture"""
        success = self.audio_engine.start_capture(device_id)
        return {
            'success': success,
            'is_running': self.audio_engine.is_running
        }
    
    def stop_audio_capture(self) -> Dict:
        """Stop audio capture"""
        success = self.audio_engine.stop_capture()
        return {
            'success': success,
            'is_running': self.audio_engine.is_running
        }
    
    def capture_screen(self) -> Dict:
        """Capture screen"""
        result = ScreenCapture.capture_primary_monitor()
        if result:
            return {'success': True, **result}
        return {'success': False, 'error': 'Screen capture failed'}
    
    def get_status(self) -> Dict:
        """Get current status"""
        return {
            'is_audio_running': self.audio_engine.is_running,
            'websocket_connected': self.streamer.is_connected,
            'session_id': self.streamer.session_id
        }

# ── Audio Streaming Thread ──────────────────────────────────────────────────

class AudioStreamingThread(QThread):
    """Background thread for audio streaming"""
    
    status_changed = pyqtSignal(dict)
    
    def __init__(self, audio_engine: AudioCaptureEngine, streamer: WebSocketStreamer):
        super().__init__()
        self.audio_engine = audio_engine
        self.streamer = streamer
        self.running = False
    
    def run(self):
        """Run audio streaming loop"""
        self.running = True
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        async def stream_audio():
            while self.running:
                if self.audio_engine.is_running:
                    audio_chunk = await self.audio_engine.get_audio_chunk()
                    if audio_chunk:
                        await self.streamer.send_audio(audio_chunk)
                await asyncio.sleep(0.01)
        
        try:
            loop.run_until_complete(stream_audio())
        except Exception as e:
            logger.error(f"Audio streaming error: {e}")
        finally:
            loop.close()
    
    def stop(self):
        """Stop streaming"""
        self.running = False

# ── Desktop Overlay Window ──────────────────────────────────────────────────

class CopilotOverlay(QMainWindow):
    """Always-on-top desktop overlay window"""
    
    def __init__(self, frontend_url: str, session_id: str, token: str, gateway_url: str):
        super().__init__()
        self.frontend_url = frontend_url
        self.session_id = session_id
        self.token = token
        self.gateway_url = gateway_url
        
        # Initialize backend services
        self.audio_engine = AudioCaptureEngine()
        self.streamer = WebSocketStreamer(gateway_url, session_id, token)
        self.bridge = DesktopBridge(self.audio_engine, self.streamer)
        
        # Setup UI
        self.setup_ui()
        
        # Connect WebSocket
        asyncio.create_task(self.streamer.connect())
        
        # Start audio streaming thread
        self.audio_thread = AudioStreamingThread(self.audio_engine, self.streamer)
        self.audio_thread.start()
        
        logger.info("CopilotOverlay initialized")
    
    def setup_ui(self):
        """Setup overlay window UI"""
        # Window properties
        self.setWindowTitle("Garage Meeting Copilot")
        self.setGeometry(1920 - 420 - 20, 1080 - 700 - 60, 420, 700)
        
        # Always on top
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.BypassWindowManagerHint
        )
        
        # Transparent background
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        # Web engine view
        browser = QWebEngineView()
        browser.load(QUrl(self.frontend_url))
        
        # Setup web channel for Python ↔ JS communication
        channel = QWebChannel()
        channel.registerObject("desktopBridge", self.bridge)
        browser.page().setWebChannel(channel)
        
        # Layout
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(browser)
        
        widget = QWidget()
        widget.setLayout(layout)
        self.setCentralWidget(widget)
        
        self.show()
    
    def closeEvent(self, event):
        """Cleanup on close"""
        self.audio_engine.stop_capture()
        asyncio.create_task(self.streamer.disconnect())
        self.audio_thread.stop()
        self.audio_thread.wait()
        event.accept()

# ── Main Application ──────────────────────────────────────────────────────

def main():
    """Launch desktop overlay"""
    import sys
    from urllib.parse import parse_qs, urlparse
    
    app = QApplication(sys.argv)
    
    # Parse command line or use defaults
    args = sys.argv[1:]
    session_id = None
    token = None
    gateway_url = "ws://localhost:8000/ws/copilot"
    frontend_url = "http://localhost:1420"
    
    if args and args[0].startswith("http"):
        # Format: python_desktop_agent.py "http://localhost:1420/#token=...&session_id=...&gateway_url=..."
        parsed = urlparse(args[0])
        if parsed.fragment:
            params = parse_qs(parsed.fragment)
            token = params.get('token', [None])[0]
            session_id = params.get('session_id', [None])[0]
            gateway_url = params.get('gateway_url', [gateway_url])[0]
            # Remove fragment for frontend URL
            frontend_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    
    if not token or not session_id:
        logger.error("Missing token or session_id. Usage: python_desktop_agent.py 'http://localhost:1420/#token=...&session_id=...&gateway_url=...'")
        sys.exit(1)
    
    # Create and show overlay
    overlay = CopilotOverlay(frontend_url, session_id, token, gateway_url)
    
    sys.exit(app.exec())

if __name__ == '__main__':
    main()
