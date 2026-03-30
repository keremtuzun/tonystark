#!/usr/bin/env python3
"""
Hand Clap Gesture Launcher - Tony Stark Mode
Clap twice to open Claude Code in Chrome and play Tony Stark music!
"""

import sounddevice as sd
import numpy as np
import subprocess
import webbrowser
import time
import threading
import sys

# --- Configuration ---
SAMPLE_RATE = 44100
BLOCK_SIZE = 1024

# Amplitude threshold (0.0–1.0). Raise if too sensitive, lower if claps aren't detected.
CLAP_THRESHOLD = 0.25

# How many claps within CLAP_WINDOW seconds triggers the action
CLAPS_REQUIRED = 2
CLAP_WINDOW = 1.5  # seconds

# Minimum seconds between successive triggers (prevents repeat-firing)
TRIGGER_COOLDOWN = 3.0

CLAUDE_CODE_URL = "https://claude.ai/code"
MUSIC_SEARCH_URL = "https://www.youtube.com/results?search_query=tony+stark+iron+man+shoot+to+thrill+acdc"

# --- State ---
clap_times: list[float] = []
last_trigger_time: float = 0.0
_lock = threading.Lock()


def open_in_chrome(url: str) -> None:
    """Try to open a URL in Chrome/Chromium, fall back to default browser."""
    for browser in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        try:
            subprocess.Popen([browser, "--new-tab", url],
                             stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
            return
        except FileNotFoundError:
            continue
    # Fall back to the system default browser
    webbrowser.open(url)


def activate_tony_stark_mode() -> None:
    print("\n🔴 TONY STARK MODE ACTIVATED!\n")
    open_in_chrome(CLAUDE_CODE_URL)
    time.sleep(0.8)
    open_in_chrome(MUSIC_SEARCH_URL)


def audio_callback(indata: np.ndarray, frames: int, time_info, status) -> None:
    global clap_times, last_trigger_time

    if status:
        print(f"[audio] {status}", file=sys.stderr)

    amplitude = float(np.sqrt(np.mean(indata ** 2)))
    now = time.monotonic()

    if amplitude >= CLAP_THRESHOLD:
        with _lock:
            clap_times.append(now)
            # Keep only claps within the detection window
            clap_times = [t for t in clap_times if now - t <= CLAP_WINDOW]

            if (
                len(clap_times) >= CLAPS_REQUIRED
                and (now - last_trigger_time) >= TRIGGER_COOLDOWN
            ):
                last_trigger_time = now
                clap_times.clear()
                print("Clap clap! Launching...")
                threading.Thread(target=activate_tony_stark_mode, daemon=True).start()


def main() -> None:
    print("╔══════════════════════════════════════════════╗")
    print("║   Hand Clap Gesture Launcher — Tony Stark   ║")
    print("╠══════════════════════════════════════════════╣")
    print("║  👏 Clap TWICE to:                           ║")
    print("║    • Open Claude Code in Chrome              ║")
    print("║    • Play Tony Stark music on YouTube        ║")
    print("║                                              ║")
    print("║  Press Ctrl+C to quit.                       ║")
    print("╚══════════════════════════════════════════════╝\n")

    try:
        with sd.InputStream(
            samplerate=SAMPLE_RATE,
            blocksize=BLOCK_SIZE,
            channels=1,
            dtype="float32",
            callback=audio_callback,
        ):
            print(f"Listening... (threshold={CLAP_THRESHOLD}, need {CLAPS_REQUIRED} clap(s) in {CLAP_WINDOW}s)\n")
            while True:
                time.sleep(0.1)
    except KeyboardInterrupt:
        print("\nGoodbye, Mr. Stark.")
    except sd.PortAudioError as e:
        print(f"\nMicrophone error: {e}", file=sys.stderr)
        print("Make sure a microphone is connected and accessible.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
