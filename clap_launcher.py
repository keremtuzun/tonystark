#!/usr/bin/env python3
"""
Hand Clap Gesture Launcher - Tony Stark Mode
Clap twice to open Claude Code in Chrome and play Tony Stark music!

Usage:
  python3 clap_launcher.py             # normal mode
  python3 clap_launcher.py --calibrate # see your live amplitude to tune threshold

Requirements:
  pip install sounddevice numpy
  # For music playback (one of):
  sudo apt install mpv          # recommended — plays YouTube directly
  pip install yt-dlp            # used by mpv under the hood
"""

import sounddevice as sd
import numpy as np
import subprocess
import webbrowser
import shutil
import time
import threading
import sys

# --- Configuration ---
SAMPLE_RATE = 44100
BLOCK_SIZE = 1024  # ~23 ms per block

# Ratio: clap must be this many times louder than the rolling background noise.
CLAP_RATIO = 6.0

CLAPS_REQUIRED = 2
CLAP_WINDOW = 1.5       # seconds — window to count claps in
INTER_CLAP_SILENCE = 0.15  # seconds — ignore re-triggers within this gap
TRIGGER_COOLDOWN = 3.0  # seconds — min gap between full triggers

CLAUDE_CODE_URL = "https://claude.ai/code"
MUSIC_QUERY = "AC/DC Shoot to Thrill Iron Man"

# --- State ---
clap_times: list[float] = []
last_trigger_time: float = 0.0
last_clap_time: float = 0.0
background_level: float = 0.001
_lock = threading.Lock()
_stop_event = threading.Event()   # set this to stop listening


def open_in_chrome(url: str) -> None:
    for browser in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        try:
            subprocess.Popen([browser, "--new-tab", url],
                             stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
            return
        except FileNotFoundError:
            continue
    webbrowser.open(url)


def play_music() -> None:
    """Play the Tony Stark music. Uses mpv if available, otherwise opens Chrome."""
    if shutil.which("mpv"):
        # mpv can stream YouTube audio directly via yt-dlp
        print("  Playing via mpv...")
        subprocess.Popen(
            ["mpv", f"ytdl://ytsearch1:{MUSIC_QUERY}", "--no-video"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    else:
        # Fallback: open YouTube search in Chrome and press Enter on first result
        # Build a direct-play URL using YouTube's autoplay search feature
        query = MUSIC_QUERY.replace(" ", "+")
        url = f"https://www.youtube.com/results?search_query={query}"
        open_in_chrome(url)
        # Give Chrome time to load, then send Enter to start the first video
        time.sleep(3)
        if shutil.which("xdotool"):
            subprocess.run(["xdotool", "key", "Tab", "Tab", "Return"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print("  Music opened in Chrome (install mpv for automatic playback)")


def activate_tony_stark_mode() -> None:
    print("\n*** TONY STARK MODE ACTIVATED — stopping listener ***\n")
    _stop_event.set()   # stop the main listening loop
    open_in_chrome(CLAUDE_CODE_URL)
    time.sleep(0.5)
    play_music()


def audio_callback(indata: np.ndarray, frames: int, time_info, status) -> None:
    global clap_times, last_trigger_time, last_clap_time, background_level

    if _stop_event.is_set():
        return

    if status:
        print(f"[audio] {status}", file=sys.stderr)

    amplitude = float(np.sqrt(np.mean(indata ** 2)))
    now = time.monotonic()

    if amplitude < background_level * 3:
        background_level = background_level * 0.995 + amplitude * 0.005

    ratio = amplitude / max(background_level, 1e-6)

    with _lock:
        if ratio >= CLAP_RATIO and (now - last_clap_time) >= INTER_CLAP_SILENCE:
            last_clap_time = now
            clap_times.append(now)
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
        print("Press Ctrl+C to quit.\n")
        try:
            with sd.InputStream(samplerate=SAMPLE_RATE, blocksize=BLOCK_SIZE,
                                channels=1, dtype="float32",
                                callback=calibrate_callback):
                while True:
                    time.sleep(0.1)
        except KeyboardInterrupt:
            print("\nDone calibrating.")
        return

    has_mpv = shutil.which("mpv") is not None
    music_note = "mpv (auto-play)" if has_mpv else "Chrome (install mpv for auto-play)"

    print("╔══════════════════════════════════════════════╗")
    print("║   Hand Clap Gesture Launcher — Tony Stark   ║")
    print("╠══════════════════════════════════════════════╣")
    print("║  Clap TWICE to:                              ║")
    print("║    • Open Claude Code in Chrome              ║")
    print("║    • Play Tony Stark music                   ║")
    print("║    • Stop listening                          ║")
    print("║                                              ║")
    print("║  Tip: run with --calibrate if not detecting  ║")
    print("║  Press Ctrl+C to quit.                       ║")
    print("╚══════════════════════════════════════════════╝")
    print(f"  Music player: {music_note}\n")

    try:
        with sd.InputStream(samplerate=SAMPLE_RATE, blocksize=BLOCK_SIZE,
                            channels=1, dtype="float32",
                            callback=audio_callback):
            print(f"Listening...  (ratio={CLAP_RATIO}x, need {CLAPS_REQUIRED} claps in {CLAP_WINDOW}s)\n")
            while not _stop_event.is_set():
                time.sleep(0.1)
        print("Listener stopped. Goodbye, Mr. Stark.")
    except KeyboardInterrupt:
        print("\nGoodbye, Mr. Stark.")
    except sd.PortAudioError as e:
        print(f"\nMicrophone error: {e}", file=sys.stderr)
        print("Make sure a microphone is connected and accessible.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
