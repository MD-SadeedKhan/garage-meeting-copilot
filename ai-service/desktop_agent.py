#!/usr/bin/env python3
"""
Garage Meeting Copilot — Python Desktop Agent
Full Python replacement for the Rust/Tauri implementation.

Covers:
  main.rs          → CopilotApp  (system tray, overlay window lifecycle)
  ipc/mod.rs       → IPCBridge   (all Tauri invoke handlers as Qt slots)
  audio/capture.rs → AudioCaptureEngine (sounddevice/WASAPI, chunking, WS streaming)
  overlay/manager  → OverlayManager (always-on-top window, stealth, positioning)
  utils/crypto.rs  → SecureStorage (AES-256-GCM at-rest encryption)
"""

import asyncio
import base64
import io
import json
import logging
import os
import queue
import sys
import threading
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, urlparse

import numpy as np
import sounddevice as sd
from PIL import ImageGrab

# ── Optional PyQt6 imports (GUI mode) ─────────────────────────────────────────
try:
    from PyQt6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout,
        QSystemTrayIcon, QMenu,
    )
    from PyQt6.QtWebEngineWidgets import QWebEngineView
    from PyQt6.QtWebChannel import QWebChannel
    from PyQt6.QtCore import Qt, QUrl, QObject, pyqtSignal, pyqtSlot
    from PyQt6.QtGui import QIcon, QAction
    HAS_QT = True
except ImportError:
    HAS_QT = False

# ── Optional cryptography import ──────────────────────────────────────────────
try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    import secrets as _secrets
    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False

import websockets
import websockets.client
import websockets.exceptions

# ─────────────────────────────────────────────────────────────────────────────
# Constants  (mirrors audio/capture.rs)
# ─────────────────────────────────────────────────────────────────────────────

TARGET_SAMPLE_RATE = 16_000
TARGET_CHANNELS    = 1
CHUNK_DURATION_MS  = 100
SAMPLES_PER_CHUNK  = (TARGET_SAMPLE_RATE * CHUNK_DURATION_MS) // 1000

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
)
logger = logging.getLogger("CopilotDesktop")


# ─────────────────────────────────────────────────────────────────────────────
# utils/crypto.rs → SecureStorage
# ─────────────────────────────────────────────────────────────────────────────

class SecureStorage:
    """
    AES-256-GCM encryption for sensitive credentials at rest.
    Mirrors Rust SecureStorage in utils/crypto.rs.
    """

    def __init__(self, key_bytes: bytes):
        if not HAS_CRYPTO:
            raise RuntimeError("Install 'cryptography' package for SecureStorage")
        assert len(key_bytes) == 32, "Key must be 32 bytes (AES-256)"
        self._aesgcm = AESGCM(key_bytes)

    @staticmethod
    def generate_key() -> bytes:
        """Generate a random 32-byte key. Mirrors SecureStorage::generate_key."""
        return _secrets.token_bytes(32)

    def encrypt(self, plaintext: str) -> str:
        """Encrypt plaintext; returns base64(nonce + ciphertext)."""
        nonce = _secrets.token_bytes(12)
        ct = self._aesgcm.encrypt(nonce, plaintext.encode(), None)
        return base64.b64encode(nonce + ct).decode()

    def decrypt(self, encoded: str) -> str:
        """Decrypt base64(nonce + ciphertext); returns plaintext."""
        raw = base64.b64decode(encoded)
        nonce, ct = raw[:12], raw[12:]
        return self._aesgcm.decrypt(nonce, ct, None).decode()


# ─────────────────────────────────────────────────────────────────────────────
# audio/capture.rs → AudioDevice, CaptureConfig, AudioChunk, AudioCaptureEngine
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class AudioDevice:
    id: str
    name: str
    is_default: bool
    device_type: str   # "microphone" | "loopback"


@dataclass
class CaptureConfig:
    microphone_device_id: Optional[str] = None
    system_audio_device_id: Optional[str] = None
    sample_rate: int = TARGET_SAMPLE_RATE
    channels: int = TARGET_CHANNELS
    enable_mic: bool = True
    enable_system_audio: bool = False


@dataclass
class AudioChunk:
    data: str          # base64-encoded linear16 PCM
    sequence: int
    source: str        # "microphone" | "system"
    sample_rate: int = TARGET_SAMPLE_RATE
    channels: int = TARGET_CHANNELS
    duration_ms: int = CHUNK_DURATION_MS


class AudioCaptureEngine:
    """
    Cross-platform audio capture using sounddevice (WASAPI on Windows).
    Mirrors Rust AudioCaptureEngine in audio/capture.rs.
    """

    def __init__(self):
        self._stream: Optional[sd.InputStream] = None
        self._running = False
        self._sequence = 0
        self._chunk_queue: queue.Queue[AudioChunk] = queue.Queue()
        self._buffer: list = []
        self._buffer_samples = 0

    # ── Device enumeration ─────────────────────────────────────────────────

    def enumerate_devices(self) -> list:
        """List available audio input devices. Mirrors enumerate_devices()."""
        result = []
        devices = sd.query_devices()
        try:
            default_idx = sd.default.device[0]
        except Exception:
            default_idx = -1

        for i, dev in enumerate(devices):
            if dev["max_input_channels"] < 1:
                continue
            result.append(AudioDevice(
                id=f"input:{dev['name']}",
                name=dev["name"],
                is_default=(i == default_idx),
                device_type="microphone",
            ))

        # Windows loopback: also list output devices (mirrors #[cfg(target_os = "windows")])
        if sys.platform == "win32":
            for dev in devices:
                if dev["max_output_channels"] < 1:
                    continue
                result.append(AudioDevice(
                    id=f"loopback:{dev['name']}",
                    name=f"{dev['name']} (System Audio)",
                    is_default=False,
                    device_type="loopback",
                ))

        logger.info("Enumerated %d audio devices", len(result))
        return result

    # ── Capture control ────────────────────────────────────────────────────

    def start_microphone(self, device_id: Optional[str] = None) -> bool:
        """
        Start microphone capture. device_id can be:
        - None: use system default
        - "1": numeric device index
        - "input:Device Name": device name lookup
        
        Works with: Headsets, Earphones, USB Mics, Webcam Mics, Built-in Mics, etc.
        Mirrors start_microphone() in audio/capture.rs.
        """
        if self._running:
            return True
        try:
            sd_device = self._resolve_input_device(device_id)
            if sd_device is not None:
                dev_info = sd.query_devices(sd_device)
                logger.info("🎙️ Using audio device [%d]: %s (%d channels, %.0f Hz)", 
                           sd_device, dev_info["name"], dev_info["max_input_channels"], 
                           dev_info["default_samplerate"])
            else:
                logger.info("🎙️ Using system default audio device")

            chunk_log_counter = [0]  # Use list to allow mutation in nested function

            def _callback(indata: np.ndarray, frames: int, time_info, status):
                if status:
                    logger.warning("Audio status: %s", status)
                if not self._running:
                    return
                
                # Convert f32 → int16 PCM  (mirrors f32 → i16::MAX cast in Rust)
                samples = (indata[:, 0].clip(-1.0, 1.0) * 32767).astype(np.int16)
                self._buffer.append(samples)
                self._buffer_samples += len(samples)
                
                # Log first chunk to verify audio is being captured
                if chunk_log_counter[0] == 0:
                    logger.info("✓ First audio frame captured: %d samples, max amplitude: %.2f", 
                               len(samples), np.max(np.abs(samples)))
                    chunk_log_counter[0] += 1

                while self._buffer_samples >= SAMPLES_PER_CHUNK:
                    all_samples = np.concatenate(self._buffer)
                    chunk_s   = all_samples[:SAMPLES_PER_CHUNK]
                    remaining = all_samples[SAMPLES_PER_CHUNK:]
                    self._buffer = [remaining] if len(remaining) else []
                    self._buffer_samples = len(remaining)

                    pcm_bytes = chunk_s.tobytes()
                    encoded   = base64.b64encode(pcm_bytes).decode()
                    self._sequence += 1
                    self._chunk_queue.put(AudioChunk(
                        data=encoded,
                        sequence=self._sequence,
                        source="microphone",
                    ))
                    
                    # Log every 10 chunks created
                    if self._sequence % 10 == 0:
                        logger.info("📦 Created %d audio chunks", self._sequence)

            self._stream = sd.InputStream(
                device=sd_device,
                samplerate=TARGET_SAMPLE_RATE,
                channels=TARGET_CHANNELS,
                blocksize=SAMPLES_PER_CHUNK,
                callback=_callback,
                dtype=np.float32,
            )
            self._stream.start()
            self._running = True
            logger.info("Microphone capture started (device=%s)", sd_device)
            return True
        except Exception as exc:
            logger.error("Failed to start microphone: %s", exc)
            return False

    def stop_all(self):
        """Stop all capture streams. Mirrors stop_all() in audio/capture.rs."""
        self._running = False
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception as exc:
                logger.warning("Error stopping stream: %s", exc)
            self._stream = None
        self._buffer.clear()
        self._buffer_samples = 0
        logger.info("Audio capture stopped")

    def is_running(self) -> bool:
        return self._running

    def get_chunk_nowait(self) -> Optional[AudioChunk]:
        try:
            return self._chunk_queue.get_nowait()
        except queue.Empty:
            return None

    # ── Helpers ────────────────────────────────────────────────────────────

    def _resolve_input_device(self, device_id: Optional[str]):
        """Resolve device_id → sounddevice index.
        - If device_id is numeric (e.g., "1"), use it directly
        - If device_id starts with 'input:', extract name and find index
        - Otherwise return None for default
        """
        if not device_id:
            return None
        
        # Try to parse as integer (direct device index)
        try:
            idx = int(device_id)
            devices = sd.query_devices()
            if 0 <= idx < len(devices) and devices[idx]["max_input_channels"] > 0:
                return idx
            logger.warning("Device index %d not found or not an input device — using default", idx)
            return None
        except ValueError:
            pass
        
        # Try device name (input:<name>)
        if device_id.startswith("input:"):
            name = device_id[len("input:"):]
            for i, dev in enumerate(sd.query_devices()):
                if dev["name"] == name and dev["max_input_channels"] > 0:
                    return i
            logger.warning("Device '%s' not found — using default", name)
            return None
        
        return None


# ─────────────────────────────────────────────────────────────────────────────
# ipc/mod.rs → capture_screen command → ScreenCaptureResult + capture_screen()
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ScreenCaptureResult:
    image_data: str   # base64 PNG
    width: int
    height: int


def do_capture_screen() -> Optional[ScreenCaptureResult]:
    """Capture primary monitor. Mirrors Rust capture_screen command in ipc/mod.rs."""
    try:
        screenshot = ImageGrab.grab()
        width, height = screenshot.size
        buf = io.BytesIO()
        screenshot.save(buf, format="PNG")
        encoded = base64.b64encode(buf.getvalue()).decode()
        return ScreenCaptureResult(image_data=encoded, width=width, height=height)
    except Exception as exc:
        logger.error("Screen capture failed: %s", exc)
        return None


# ─────────────────────────────────────────────────────────────────────────────
# ipc/mod.rs → stream_audio_to_gateway → WebSocketStreamer
# ─────────────────────────────────────────────────────────────────────────────

class WebSocketStreamer:
    """
    Async WebSocket streamer with automatic reconnection.
    Sends AudioChunks and screen frames to the backend gateway.
    """

    def __init__(self, gateway_url: str, session_id: str, token: str):
        self.gateway_url = gateway_url
        self.session_id  = session_id
        self.token       = token
        self._ws         = None
        self.is_connected = False
        self._reconnect_attempts = 0
        self._max_reconnect_attempts = 5

    async def connect(self) -> bool:
        url = f"{self.gateway_url}?token={self.token}&session_id={self.session_id}"
        try:
            self._ws = await websockets.client.connect(
                url,
                ping_interval=30,  # Send ping every 30 seconds
                ping_timeout=10,   # Wait 10 seconds for pong
                close_timeout=10,
                compression=None
            )
            self.is_connected = True
            self._reconnect_attempts = 0
            logger.info("WebSocket connected → %s", self.session_id)
            return True
        except Exception as exc:
            logger.error("WebSocket connection failed: %s", exc)
            self.is_connected = False
            return False

    async def send_audio(self, chunk: AudioChunk) -> bool:
        # Try to reconnect if not connected
        if not self.is_connected or not self._ws:
            if self._reconnect_attempts < self._max_reconnect_attempts:
                self._reconnect_attempts += 1
                logger.warning("Attempting reconnection (%d/%d)...", self._reconnect_attempts, self._max_reconnect_attempts)
                if not await self.connect():
                    return False
            else:
                logger.error("Max reconnection attempts reached")
                return False
        
        try:
            payload = {
                "type":       "audio",
                "session_id": self.session_id,
                "data":       chunk.data,
                "sequence":   chunk.sequence,
                "source":     chunk.source,
            }
            await asyncio.wait_for(
                self._ws.send(json.dumps(payload)),
                timeout=5.0
            )
            return True
        except asyncio.TimeoutError:
            logger.error("WebSocket send timeout - connection may be dead")
            self.is_connected = False
            return False
        except websockets.exceptions.ConnectionClosed:
            logger.error("WebSocket connection closed")
            self.is_connected = False
            return False
        except Exception as exc:
            logger.error("WebSocket send error: %s", exc)
            self.is_connected = False
            return False

    async def send_screen(self, result: ScreenCaptureResult) -> bool:
        if not self.is_connected or not self._ws:
            return False
        try:
            payload = {
                "type":       "screen",
                "session_id": self.session_id,
                "image":      result.image_data,
                "width":      result.width,
                "height":     result.height,
            }
            await asyncio.wait_for(
                self._ws.send(json.dumps(payload)),
                timeout=5.0
            )
            return True
        except Exception as exc:
            logger.error("Screen send error: %s", exc)
            self.is_connected = False
            return False

    async def disconnect(self):
        if self._ws:
            await self._ws.close()
            self.is_connected = False


# ─────────────────────────────────────────────────────────────────────────────
# overlay/manager.rs → OverlayManager
# ─────────────────────────────────────────────────────────────────────────────

if HAS_QT:
    class OverlayManager:
        """
        Manages the always-on-top PyQt6 overlay window.
        Mirrors Rust OverlayManager in overlay/manager.rs.
        """

        def __init__(self, window: QMainWindow):
            self._window = window

        def show(self):
            self._window.show()
            self._window.raise_()
            self._window.activateWindow()
            logger.info("Overlay shown")

        def hide(self):
            self._window.hide()
            logger.info("Overlay hidden")

        def toggle(self) -> bool:
            """Toggle visibility. Mirrors OverlayManager::toggle()."""
            if self._window.isVisible():
                self.hide()
                return False
            self.show()
            return True

        def set_stealth_mode(self, enabled: bool):
            """
            Stealth = click-through (passthrough mouse events).
            Mirrors set_stealth_mode / set_ignore_cursor_events.
            """
            flags = self._window.windowFlags()
            if enabled:
                flags |= Qt.WindowType.WindowTransparentForInput
            else:
                flags &= ~Qt.WindowType.WindowTransparentForInput
            self._window.setWindowFlags(flags)
            self._window.show()
            logger.info("Stealth mode: %s", enabled)

        def set_position(self, x: float, y: float):
            """Mirrors set_position / tauri::LogicalPosition."""
            self._window.move(int(x), int(y))

        def set_size(self, width: float, height: float):
            """Mirrors set_size / tauri::LogicalSize."""
            self._window.resize(int(width), int(height))

        def set_opacity(self, opacity: float):
            self._window.setWindowOpacity(opacity)


# ─────────────────────────────────────────────────────────────────────────────
# ipc/mod.rs → IPCBridge  (all #[tauri::command] handlers as Qt slots)
# ─────────────────────────────────────────────────────────────────────────────

if HAS_QT:
    class IPCBridge(QObject):
        """
        Exposed to the React frontend via QWebChannel.
        Each method is the Python equivalent of one #[tauri::command] in ipc/mod.rs.
        Signals mirror app.emit() calls in the Rust code.
        """

        # Signals  (mirrors Tauri app.emit events)
        audioStarted = pyqtSignal(bool)    # copilot:audio-started
        audioStopped = pyqtSignal(bool)    # copilot:audio-stopped
        wsConnected  = pyqtSignal(bool)    # copilot:ws-connected
        streamError  = pyqtSignal(str)     # copilot:stream-error

        def __init__(
            self,
            audio_engine: AudioCaptureEngine,
            overlay_manager: "OverlayManager",
            config: dict,
        ):
            super().__init__()
            self._audio   = audio_engine
            self._overlay = overlay_manager
            self._config  = config
            self._streaming_thread: Optional[threading.Thread] = None
            self._stop_streaming = threading.Event()

        # ── get_audio_devices ──────────────────────────────────────────────

        @pyqtSlot(result=str)
        def get_audio_devices(self) -> str:
            devices = self._audio.enumerate_devices()
            return json.dumps({
                "success": True,
                "data": [asdict(d) for d in devices],
            })

        # ── start_audio_capture ────────────────────────────────────────────

        @pyqtSlot(str, str, str, bool, bool, str, result=str)
        def start_audio_capture(
            self,
            gateway_url: str,
            session_id: str,
            token: str,
            enable_mic: bool,
            enable_system_audio: bool,
            mic_device_id: str,
        ) -> str:
            """Mirrors start_audio_capture command in ipc/mod.rs."""
            device_id = mic_device_id if mic_device_id else None
            if enable_mic:
                ok = self._audio.start_microphone(device_id)
                if not ok:
                    return json.dumps({"success": False, "error": "Mic capture failed"})

            # Background thread: connect WS + forward chunks (mirrors tokio::spawn)
            self._stop_streaming.clear()
            self._streaming_thread = threading.Thread(
                target=self._run_streaming_loop,
                args=(gateway_url, session_id, token),
                daemon=True,
            )
            self._streaming_thread.start()
            self.audioStarted.emit(True)
            return json.dumps({"success": True, "data": True})

        def _run_streaming_loop(self, gateway_url: str, session_id: str, token: str):
            """Mirrors stream_audio_to_gateway async fn in ipc/mod.rs."""
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            async def _run():
                streamer = WebSocketStreamer(gateway_url, session_id, token)
                if await streamer.connect():
                    self.wsConnected.emit(True)
                    logger.info("✓ WebSocket connected, ready to stream audio")
                else:
                    self.streamError.emit("WebSocket connection failed")
                    logger.error("✗ WebSocket connection failed")
                    return

                # Background task: send keep-alive pings every 20 seconds
                async def keepalive():
                    while not self._stop_streaming.is_set() and streamer.is_connected:
                        try:
                            await asyncio.sleep(20)
                            if streamer.is_connected and streamer._ws:
                                payload = {"type": "ping"}
                                await asyncio.wait_for(
                                    streamer._ws.send(json.dumps(payload)),
                                    timeout=5.0
                                )
                        except Exception as e:
                            logger.debug("Keepalive ping error (recoverable): %s", e)

                keepalive_task = asyncio.create_task(keepalive())

                chunk_count = 0
                send_count = 0
                try:
                    while not self._stop_streaming.is_set():
                        chunk = self._audio.get_chunk_nowait()
                        if chunk:
                            chunk_count += 1
                            result = await streamer.send_audio(chunk)
                            if result:
                                send_count += 1
                                if send_count % 20 == 0:  # Log every 20 chunks sent
                                    logger.info("📡 Sent %d audio chunks (%d ms of audio)", send_count, send_count * CHUNK_DURATION_MS)
                            else:
                                logger.debug("Failed to send chunk %d (will retry on reconnect)", chunk_count)
                        else:
                            await asyncio.sleep(0.01)
                finally:
                    keepalive_task.cancel()
                    try:
                        await keepalive_task
                    except asyncio.CancelledError:
                        pass

                logger.info("Streaming stopped. Captured: %d chunks, Sent: %d chunks", chunk_count, send_count)
                await streamer.disconnect()

            try:
                loop.run_until_complete(_run())
            except Exception as exc:
                logger.error("Streaming loop error: %s", exc)
                self.streamError.emit(str(exc))
            finally:
                loop.close()

        # ── stop_audio_capture ─────────────────────────────────────────────

        @pyqtSlot(result=str)
        def stop_audio_capture(self) -> str:
            """Mirrors stop_audio_capture command in ipc/mod.rs."""
            self._stop_streaming.set()
            self._audio.stop_all()
            self.audioStopped.emit(True)
            return json.dumps({"success": True, "data": True})

        # ── get_audio_capture_status ───────────────────────────────────────

        @pyqtSlot(result=str)
        def get_audio_capture_status(self) -> str:
            """Mirrors get_audio_capture_status command in ipc/mod.rs."""
            return json.dumps({
                "success": True,
                "data": {
                    "is_running":             self._audio.is_running(),
                    "mic_enabled":            True,
                    "system_audio_enabled":   False,
                },
            })

        # ── capture_screen ─────────────────────────────────────────────────

        @pyqtSlot(result=str)
        def capture_screen(self) -> str:
            """Mirrors capture_screen command in ipc/mod.rs."""
            result = do_capture_screen()
            if result:
                return json.dumps({"success": True, "data": asdict(result)})
            return json.dumps({"success": False, "error": "Screen capture failed"})

        # ── toggle_overlay_visibility ──────────────────────────────────────

        @pyqtSlot(result=str)
        def toggle_overlay_visibility(self) -> str:
            """Mirrors toggle_overlay_visibility command in ipc/mod.rs."""
            visible = self._overlay.toggle()
            return json.dumps({"success": True, "data": visible})

        # ── set_overlay_stealth_mode ───────────────────────────────────────

        @pyqtSlot(bool, result=str)
        def set_overlay_stealth_mode(self, enabled: bool) -> str:
            """Mirrors set_overlay_stealth_mode command in ipc/mod.rs."""
            self._overlay.set_stealth_mode(enabled)
            return json.dumps({"success": True, "data": enabled})

        # ── get_copilot_config ─────────────────────────────────────────────

        @pyqtSlot(result=str)
        def get_copilot_config(self) -> str:
            """Mirrors get_copilot_config command in ipc/mod.rs."""
            return json.dumps({"success": True, "data": self._config})

        # ── save_copilot_config ────────────────────────────────────────────

        @pyqtSlot(str, result=str)
        def save_copilot_config(self, config_json: str) -> str:
            """Mirrors save_copilot_config command in ipc/mod.rs."""
            try:
                updates = json.loads(config_json)
                self._config.update(updates)
                cfg_path = Path(__file__).parent / "copilot_config.json"
                cfg_path.write_text(json.dumps(self._config, indent=2))
                return json.dumps({"success": True, "data": True})
            except Exception as exc:
                return json.dumps({"success": False, "error": str(exc)})


# ─────────────────────────────────────────────────────────────────────────────
# main.rs → CopilotApp  (replaces Tauri Builder + setup closure)
# ─────────────────────────────────────────────────────────────────────────────

def _load_config() -> dict:
    """
    Load or create default config.
    Mirrors CopilotConfig::default() in ipc/mod.rs.
    """
    cfg_path = Path(__file__).parent / "copilot_config.json"
    defaults = {
        "gateway_url":         "ws://localhost:8000/ws/copilot",
        "session_id":          None,
        "garage_token":        None,
        "enable_mic":          True,
        "enable_system_audio": False,
        "overlay_opacity":     0.95,
        "stealth_mode":        False,
        "hotkey_toggle":       "Ctrl+Shift+G",
    }
    if cfg_path.exists():
        try:
            saved = json.loads(cfg_path.read_text())
            defaults.update(saved)
        except Exception:
            pass
    return defaults


if HAS_QT:
    class CopilotApp:
        """
        Top-level application. Mirrors Tauri's Builder::default() chain in main.rs:
          - Always-on-top frameless transparent overlay window
          - QWebChannel IPC bridge (all invoke handlers registered)
          - System tray with Toggle / Quit menu
          - Positions window bottom-right (mirrors main.rs position calculation)
        """

        def __init__(
            self,
            frontend_url: str,
            session_id: str,
            token: str,
            gateway_url: str,
            audio_device: Optional[str] = None,
        ):
            self._qt_app = QApplication.instance() or QApplication(sys.argv)
            self._config = _load_config()
            self._config["session_id"]   = session_id
            self._config["garage_token"] = token
            self._config["gateway_url"]  = gateway_url

            self._audio_engine = AudioCaptureEngine()

            # Build overlay window (mirrors WebviewWindowBuilder in main.rs)
            self._window  = self._build_window(frontend_url)
            self._overlay = OverlayManager(self._window)
            self._overlay.set_opacity(self._config["overlay_opacity"])

            # IPC bridge (all Tauri invoke handlers)
            self._bridge = IPCBridge(self._audio_engine, self._overlay, self._config)

            # Register bridge with QWebChannel so React can call it
            channel = QWebChannel()
            channel.registerObject("ipc", self._bridge)
            self._browser.page().setWebChannel(channel)

            # System tray (mirrors TrayIconBuilder in main.rs)
            self._setup_tray()

            # Auto-start audio capture (no need to click a button)
            logger.info("Auto-starting audio capture...")
            result = self._bridge.start_audio_capture(
                gateway_url=gateway_url,
                session_id=session_id,
                token=token,
                enable_mic=True,
                enable_system_audio=False,
                mic_device_id=audio_device or "",
            )
            result_data = json.loads(result)
            if result_data.get("success"):
                logger.info("✓ Audio capture started automatically")
            else:
                logger.warning("⚠ Audio capture failed to start: %s", result_data.get("error"))

            logger.info("CopilotApp ready — session=%s gateway=%s", session_id, gateway_url)

        # ── Window builder ─────────────────────────────────────────────────

        def _build_window(self, frontend_url: str) -> QMainWindow:
            """
            Mirrors Tauri WebviewWindowBuilder:
              .always_on_top(true) .decorations(false) .transparent(true)
              .skip_taskbar(true) .inner_size(420, 700)
              .position(screen.width - 440, screen.height - 730)
            """
            win = QMainWindow()
            win.setWindowTitle("Garage Meeting Copilot")
            win.setWindowFlags(
                Qt.WindowType.FramelessWindowHint      |
                Qt.WindowType.WindowStaysOnTopHint     |
                Qt.WindowType.Tool                      # skip taskbar
            )
            win.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

            # Bottom-right of primary screen (mirrors main.rs position calc)
            screen = self._qt_app.primaryScreen()
            if screen:
                g = screen.geometry()
                x, y = g.width() - 440, g.height() - 730
            else:
                x, y = 1480, 350
            win.setGeometry(x, y, 420, 700)

            self._browser = QWebEngineView()
            self._browser.load(QUrl(frontend_url))

            layout = QVBoxLayout()
            layout.setContentsMargins(0, 0, 0, 0)
            layout.addWidget(self._browser)
            container = QWidget()
            container.setLayout(layout)
            win.setCentralWidget(container)
            win.show()
            return win

        # ── System tray ────────────────────────────────────────────────────

        def _setup_tray(self):
            """
            Mirrors TrayIconBuilder with toggle + quit menu items in main.rs.
            Left-click on tray icon shows overlay (mirrors on_tray_icon_event).
            """
            tray = QSystemTrayIcon(self._qt_app)
            icon_path = Path(__file__).parent / "tray_icon.png"
            if icon_path.exists():
                tray.setIcon(QIcon(str(icon_path)))

            menu = QMenu()

            toggle_action = QAction("Toggle Overlay", self._qt_app)
            toggle_action.triggered.connect(self._overlay.toggle)
            menu.addAction(toggle_action)

            menu.addSeparator()

            quit_action = QAction("Quit Copilot", self._qt_app)
            quit_action.triggered.connect(self._quit)
            menu.addAction(quit_action)

            tray.setContextMenu(menu)
            tray.activated.connect(
                lambda reason: self._overlay.toggle()
                if reason == QSystemTrayIcon.ActivationReason.Trigger
                else None
            )
            tray.show()
            self._tray = tray

        def _quit(self):
            self._bridge.stop_audio_capture()
            self._qt_app.quit()

        def run(self) -> int:
            return self._qt_app.exec()


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def main():
    """
    Usage:
      python desktop_agent.py "http://localhost:1420/#token=<JWT>&session_id=<ID>&gateway_url=<WS_URL>" [--audio-device <ID>]

    Or via environment variables:
      SESSION_ID=<id> GARAGE_TOKEN=<jwt> AUDIO_DEVICE=1 python desktop_agent.py
    
    To list available audio devices:
      python list_audio_devices.py
    """
    if not HAS_QT:
        print("ERROR: PyQt6 not installed. Run:")
        print("  pip install PyQt6==6.7.1 PyQt6-WebEngine==6.7.0")
        sys.exit(1)

    # Defaults from env
    gateway_url  = os.getenv("GATEWAY_URL",  "ws://localhost:8000/ws/copilot")
    frontend_url = os.getenv("FRONTEND_URL", "http://localhost:1420")
    session_id   = os.getenv("SESSION_ID")
    token        = os.getenv("GARAGE_TOKEN")
    audio_device = os.getenv("AUDIO_DEVICE")  # e.g., "1" for headset

    # Override from URL argument (matches launch_desktop_agent.bat format)
    args = sys.argv[1:]
    url_arg = None
    
    # Parse arguments
    i = 0
    while i < len(args):
        if args[i] == "--audio-device" and i + 1 < len(args):
            audio_device = args[i + 1]
            i += 2
        elif args[i].startswith("http"):
            url_arg = args[i]
            i += 1
        else:
            i += 1
    
    if url_arg:
        parsed = urlparse(url_arg)
        if parsed.fragment:
            params       = parse_qs(parsed.fragment)
            token        = params.get("token",       [token])[0] if params.get("token") else token
            session_id   = params.get("session_id",  [session_id])[0] if params.get("session_id") else session_id
            gateway_url  = params.get("gateway_url", [gateway_url])[0] if params.get("gateway_url") else gateway_url
        frontend_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"

    if not token or not session_id:
        print(
            "Usage: python desktop_agent.py "
            "'http://localhost:1420/#token=<JWT>&session_id=<ID>&gateway_url=<WS_URL>' [--audio-device <ID>]"
        )
        print("Or set SESSION_ID and GARAGE_TOKEN environment variables.")
        print("\nList audio devices with: python list_audio_devices.py")
        sys.exit(1)

    # Rebuild full URL with hash params for the React app
    full_url = (
        f"{frontend_url}/"
        f"#token={token}"
        f"&session_id={session_id}"
        f"&gateway_url={gateway_url}"
    )

    logger.info("Launching overlay → %s", frontend_url)
    logger.info("Session: %s", session_id)
    logger.info("Gateway: %s", gateway_url)
    logger.info("Audio Device: %s", audio_device or "default (system)")

    app = CopilotApp(full_url, session_id, token, gateway_url, audio_device=audio_device)
    sys.exit(app.run())


if __name__ == "__main__":
    main()
