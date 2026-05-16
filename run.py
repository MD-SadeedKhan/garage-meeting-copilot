#!/usr/bin/env python3
"""
🎙️ Garage Meeting Copilot — Single-Command Launcher
Handles everything: session creation, device selection, and agent launch
"""

import os
import sys
import subprocess
import time
import uuid
import sounddevice as sd
from pathlib import Path

# ─────────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).parent
AI_SERVICE = REPO_ROOT / "ai-service"
DESKTOP_AGENT = REPO_ROOT / "desktop-agent"

BACKEND_URL = "http://localhost:8000/health"
FRONTEND_URL = "http://localhost:1420"
GATEWAY_WS = "ws://localhost:8000/ws/copilot"

# ─────────────────────────────────────────────────────────────────────────────
# Helper Functions
# ─────────────────────────────────────────────────────────────────────────────

def find_best_audio_device():
    """
    Automatically find the BEST audio input device on the system.
    Works with: Headsets, Earphones, USB Microphones, Webcam Mics, Built-in Mics, etc.
    
    Priority:
    1. Any device with "Headset" (covers wired/wireless earphones)
    2. Any device with "Microphone" (covers USB mics, webcam mics, etc.)
    3. Any device with "Audio" in the name
    4. First available input device (fallback)
    """
    try:
        devices = sd.query_devices()
        default_idx = sd.default.device[0]
        
        # Get all input devices
        input_devices = [
            (i, dev) for i, dev in enumerate(devices)
            if dev["max_input_channels"] > 0
        ]
        
        if not input_devices:
            print("⚠️  No input devices found, using system default")
            return None
        
        # Priority 1: Headset devices
        for idx, dev in input_devices:
            if "headset" in dev["name"].lower():
                print(f"✅ Auto-selected Headset: [{idx}] {dev['name']}")
                return idx
        
        # Priority 2: Any Microphone device
        for idx, dev in input_devices:
            if "microphone" in dev["name"].lower():
                print(f"✅ Auto-selected Microphone: [{idx}] {dev['name']}")
                return idx
        
        # Priority 3: Any Audio device
        for idx, dev in input_devices:
            if "audio" in dev["name"].lower():
                print(f"✅ Auto-selected Audio Device: [{idx}] {dev['name']}")
                return idx
        
        # Priority 4: First available input
        idx, dev = input_devices[0]
        print(f"✅ Auto-selected Available Device: [{idx}] {dev['name']}")
        return idx
        
    except Exception as e:
        print(f"⚠️  Error detecting audio device: {e}")
        return None

def is_port_open(port):
    """Check if a port is listening (with timeout)."""
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(1)  # 1 second timeout
    try:
        result = sock.connect_ex(('127.0.0.1', port))
        return result == 0
    except Exception as e:
        print(f"   [Debug] Port check error for {port}: {e}")
        return False
    finally:
        try:
            sock.close()
        except:
            pass

def create_session(session_id):
    """Create a new session in Redis."""
    print(f"\n📝 Creating session: {session_id}")
    result = subprocess.run(
        [sys.executable, "setup_test_session.py", session_id],
        cwd=AI_SERVICE,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        print("✅ Session created")
        return True
    else:
        print(f"❌ Failed to create session: {result.stderr}")
        return False

def launch_agent(session_id, audio_device):
    """Launch the desktop agent."""
    url = (
        f"http://localhost:1420/"
        f"#token=dev-token"
        f"&session_id={session_id}"
        f"&gateway_url=ws%3A%2F%2Flocalhost%3A8000%2Fws%2Fcopilot"
    )
    
    cmd = [
        sys.executable,
        "desktop_agent.py",
        url,
    ]
    
    if audio_device is not None:
        cmd.extend(["--audio-device", str(audio_device)])
    
    print(f"\n🚀 Launching desktop agent with device {audio_device}...")
    print(f"   Session: {session_id}")
    print(f"   Device: {audio_device}\n")
    
    # Run in foreground (blocking)
    subprocess.run(cmd, cwd=AI_SERVICE)

def main():
    print("""
╔════════════════════════════════════════════════════════════════╗
║  🎙️  Garage Meeting Copilot — Auto Launcher                    ║
║  Automatically detects all audio devices & starts recording   ║
╚════════════════════════════════════════════════════════════════╝
    """)

    # Allow overriding audio device from CLI: python run.py --device 13
    import argparse
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--device", type=int, default=None)
    args, _ = parser.parse_known_args()

    # Auto-detect best audio device (or use CLI override)
    print("\n🔍 Detecting audio devices...")
    if args.device is not None:
        audio_device = args.device
        print(f"✅ Using specified device: [{audio_device}]")
    else:
        audio_device = find_best_audio_device()
    
    # Generate unique session ID
    session_id = f"meeting-{uuid.uuid4().hex[:8]}"
    print(f"📝 Session ID: {session_id}\n")
    
    # Check if backend is running
    print("⏳ Checking backend (port 8000)...")
    for attempt in range(1, 4):
        if is_port_open(8000):
            print("✅ Backend is running\n")
            break
        if attempt < 3:
            print(f"   Attempt {attempt}/3 - retrying...")
            time.sleep(1)
    else:
        print("❌ Backend NOT running!")
        print("   Open a NEW terminal and run:")
        print("   >>> cd C:\\Users\\sadid\\garage-meeting-copilot\\ai-service")
        print("   >>> python main.py")
        sys.exit(1)
    
    # Create session
    print("📝 Creating session in database...")
    if not create_session(session_id):
        print("❌ Failed to create session. Exiting.")
        sys.exit(1)
    
    # Launch agent
    print("\n" + "="*70)
    print("  🚀 LAUNCHING MEETING COPILOT")
    print("  ")
    print(f"  Device: Auto-detected ({audio_device})")
    print(f"  Session: {session_id}")
    print("  ")
    print("  ✅ READY TO RECORD - Speak now!")
    print("  ")
    print("  💡 Tips:")
    print("     • Speak clearly into your microphone/headset")
    print("     • Real-time transcript will appear in the overlay")
    print("     • Check browser console if you see errors")
    print("="*70 + "\n")
    time.sleep(2)
    
    launch_agent(session_id, audio_device)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n👋 Shutting down...")
        sys.exit(0)
