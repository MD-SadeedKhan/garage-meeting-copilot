#!/usr/bin/env python3
"""Quick mic level test — run this to verify your microphone is working."""
import sounddevice as sd
import numpy as np
import time

print("Available input devices:")
devices = sd.query_devices()
for i, dev in enumerate(devices):
    if dev["max_input_channels"] > 0:
        default = " <-- DEFAULT" if i == sd.default.device[0] else ""
        print(f"  [{i}] {dev['name']}{default}")

print("\nTesting device [1] for 3 seconds... SPEAK NOW!\n")

amplitudes = []

def callback(indata, frames, time_info, status):
    amp = float(np.max(np.abs(indata)))
    amplitudes.append(amp)
    bar = "#" * int(amp * 50)
    print(f"\r  Level: [{bar:<50}] {amp:.4f}", end="", flush=True)

try:
    with sd.InputStream(device=1, samplerate=16000, channels=1,
                        callback=callback, dtype="float32"):
        time.sleep(3)
    print()
    avg = sum(amplitudes) / len(amplitudes) if amplitudes else 0
    peak = max(amplitudes) if amplitudes else 0
    print(f"\nDevice [1] — avg: {avg:.4f}  peak: {peak:.4f}")
    if peak < 0.001:
        print("❌ SILENT — mic is muted or not working")
        print("   Fix: Windows Settings → Sound → Input → check mic level and unmute")
    else:
        print("✅ Mic is working!")
except Exception as e:
    print(f"Error: {e}")
