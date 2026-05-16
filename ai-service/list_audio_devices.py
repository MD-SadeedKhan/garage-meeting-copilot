#!/usr/bin/env python3
"""List all audio input devices available on this system."""

import sounddevice as sd

print("\n🎙️  AUDIO INPUT DEVICES ON THIS SYSTEM\n")
print("-" * 80)

devices = sd.query_devices()
input_devices = []

for i, dev in enumerate(devices):
    if dev["max_input_channels"] > 0:
        is_default = " ⭐ DEFAULT" if i == sd.default.device[0] else ""
        print(f"  [{i:2d}] {dev['name']}{is_default}")
        print(f"        Channels: {dev['max_input_channels']}, Sample Rate: {dev['default_samplerate']} Hz")
        input_devices.append((i, dev["name"]))

print("\n" + "-" * 80)
print(f"\nTo use a specific device, pass it to the desktop agent:")
print(f"  python desktop_agent.py <URL> --audio-device <ID>\n")
print(f"Example: python desktop_agent.py <URL> --audio-device 2\n")
