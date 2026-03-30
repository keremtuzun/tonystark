#!/usr/bin/env python3
"""
Hand Clap Gesture Launcher - Tony Stark Mode
Clap twice to open Claude Code in Chrome and play Tony Stark music!

Usage:
  python3 clap_launcher.py             # normal mode
  python3 clap_launcher.py --calibrate # see your live amplitude to tune threshold
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
BLOCK_SIZE = 1024  # ~23 ms per block

# Ratio: clap must be this many times louder than the rolling background noise.
# This is much more reliable than a fixed threshold because it adapts to your mic.
CLAP_RATIO = 6.0

# How many claps within CLAP_WINDOW seconds triggers the action
CLAPS_REQUIRED = 2
CLAP_WINDOW = 1.5  # seconds

# Ignore repeated triggers for this many seconds after a clap is counted
# (prevents one clap ringing out and being counted multiple times)
INTER_CLAP_SILENCE = 0.15  # seconds

# Minimum seconds between successive full triggers (prevents repeat-firing)
TRIGGER_COOLDOWN = 3.0

CLAUDE_CODE_URL = "https://claude.ai/code"
MUSIC_SEARCH_URL = "https://www.youtube.com/results?search_query=tony+stark+iron+man+shoot+to+thrill+acdc"

# --- State ---
clap_times: list[float] = []
last_trigger_time: float = 0.0
last_clap_time: float = 0.0
background_level: float = 0.001   # rolling average of quiet noise
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
    webbrowser.open(url)


def activate_tony_stark_mode() -> None:
    print("\n*** TONY STARK MODE ACTIVATED ***\n")
    open_in_chrome(CLAUDE_CODE_URL)
    time.sleep(0.8)
    open_in_chrome(MUSIC_SEARCH_URL)


def audio_callback(indata: np.ndarray, frames: int, time_info, status) -> None:
    global clap_times, last_trigger_time, last_clap_time, background_level

    if status:
        print(f"[audio] {status}", file=sys.stderr)

    amplitude = float(np.sqrt(np.mean(indata ** 2)))
    now = time.monotonic()

    # Update rolling background level slowly (only during quiet moments)
    if amplitude < background_level * 3:
        background_level = background_level * 0.995 + amplitude * 0.005

    ratio = amplitude / max(background_level, 1e-6)

    with _lock:
        # Clap detected: amplitude is significantly above background noise
        if ratio >= CLAP_RATIO and (now - last_clap_time) >= INTER_CLAP_SILENCE:
            last_clap_time = now
            clap_times.append(now)
            # Keep only claps within the detection window
            clap_times = [t for t in clap_times if now - t <= CLAP_WINDOW]
            print(f"  Clap! (x{len(clap_times)})  amplitude={amplitude:.4f}  ratio={ratio:.1f}x")

            if (
                len(clap_times) >= CLAPS_REQUIRED
                and (now - last_trigger_time) >= TRIGGER_COOLDOWN
            ):
                last_trigger_time = now
                clap_times.clear()
                threading.Thread(target=activate_tony_stark_mode, daemon=True).start()


def calibrate_callback(indata: np.ndarray, frames: int, time_info, status) -> None:
    amplitude = float(np.sqrt(np.mean(indata ** 2)))
    bar = "#" * int(amplitude * 400)
    print(f"\r  amplitude={amplitude:.5f}  |{bar:<40}|  ", end="", flush=True)


def main() -> None:
    calibrate_mode = "--calibrate" in sys.argv

    if calibrate_mode:
        print("=== CALIBRATION MODE ===")
        print("Watch the amplitude bar. Clap and note the peak value.")
        print("Set CLAP_RATIO so a clap is clearly above background noise.")
        print("Press Ctrl+C to quit.\n")
        try:
            with sd.InputStream(
                samplerate=SAMPLE_RATE,
                blocksize=BLOCK_SIZE,
                channels=1,
                dtype="float32",
                callback=calibrate_callback,
            ):
                while True:
                    time.sleep(0.1)
        except KeyboardInterrupt:
            print("\nDone calibrating.")
        return

    print("╔══════════════════════════════════════════════╗")
    print("║   Hand Clap Gesture Launcher — Tony Stark   ║")
    print("╠══════════════════════════════════════════════╣")
    print("║  Clap TWICE to:                              ║")
    print("║    • Open Claude Code in Chrome              ║")
    print("║    • Play Tony Stark music on YouTube        ║")
    print("║                                              ║")
    print("║  Tip: run with --calibrate if not detecting  ║")
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
            print(f"Listening...  (ratio threshold={CLAP_RATIO}x, need {CLAPS_REQUIRED} clap(s) in {CLAP_WINDOW}s)\n")
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
