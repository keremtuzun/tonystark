#!/usr/bin/env python3
"""
Hand Clap Gesture Launcher - Tony Stark Mode
Clap twice to open Claude Code in Chrome and play Tony Stark music!

Usage:
  python3 clap_launcher.py             # normal mode
  python3 clap_launcher.py --calibrate # see live amplitude to tune sensitivity

Requirements:
  pip install sounddevice numpy yt-dlp
"""

import glob
import shutil
import subprocess
import sys
import threading
import time
import webbrowser

import numpy as np
import sounddevice as sd

# --- Configuration ---
SAMPLE_RATE = 44100
BLOCK_SIZE = 1024

CLAP_RATIO = 6.0          # clap must be this many × louder than background noise
CLAPS_REQUIRED = 2
CLAP_WINDOW = 1.5         # seconds — window to count claps in
INTER_CLAP_SILENCE = 0.15 # seconds — debounce gap between clap counts
TRIGGER_COOLDOWN = 3.0    # seconds — min gap between full triggers

CLAUDE_CODE_URL = "https://claude.ai/code"
MUSIC_QUERY = "AC/DC Shoot to Thrill Iron Man"
MUSIC_TMP = "/tmp/tonystark_music"  # yt-dlp appends the right extension

# --- State ---
clap_times: list[float] = []
last_trigger_time: float = 0.0
last_clap_time: float = 0.0
background_level: float = 0.001
_lock = threading.Lock()
_stop_event = threading.Event()


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------

def open_in_chrome(url: str) -> None:
    if sys.platform == "darwin":
        subprocess.Popen(["open", "-a", "Google Chrome", url],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return
    for browser in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        try:
            subprocess.Popen([browser, "--new-tab", url],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        except FileNotFoundError:
            continue
    webbrowser.open(url)


def play_music() -> None:
    """Download Tony Stark music via yt-dlp then play with afplay / mpv."""

    # --- mpv (if installed via brew) ---
    if shutil.which("mpv"):
        print("  Playing via mpv...")
        subprocess.Popen(
            ["mpv", f"ytdl://ytsearch1:{MUSIC_QUERY}", "--no-video"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return

    # --- yt-dlp download → afplay (Mac built-in, no brew needed) ---
    if sys.platform == "darwin":
        # Clean up any leftover temp files first
        for old in glob.glob(MUSIC_TMP + ".*"):
            try:
                import os; os.remove(old)
            except OSError:
                pass

        print("  Downloading music via yt-dlp (takes a few seconds)...")
        try:
            ret = subprocess.run(
                [sys.executable, "-m", "yt_dlp",
                 "-f", "bestaudio[ext=m4a]/bestaudio/best",
                 "--no-playlist", "--no-progress", "-q",
                 "-o", MUSIC_TMP + ".%(ext)s",
                 f"ytsearch1:{MUSIC_QUERY}"],
                timeout=60,
            )
            if ret.returncode == 0:
                files = glob.glob(MUSIC_TMP + ".*")
                if files:
                    print(f"  Playing via afplay...")
                    subprocess.Popen(
                        ["afplay", files[0]],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        start_new_session=True,  # keeps playing after this script exits
                    )
                    return
        except subprocess.TimeoutExpired:
            print("  Download timed out.")
        except Exception as e:
            print(f"  yt-dlp error: {e}")

    # --- Final fallback: open YouTube in Chrome ---
    query = MUSIC_QUERY.replace(" ", "+")
    open_in_chrome(f"https://www.youtube.com/results?search_query={query}")
    print("  Opened YouTube in Chrome (install yt-dlp for auto-play: pip install yt-dlp)")


def activate_tony_stark_mode() -> None:
    """Called in a non-daemon thread — keeps process alive until music starts."""
    print("\n*** TONY STARK MODE ACTIVATED ***\n")
    _stop_event.set()

    # Immediate audio feedback so user knows the clap registered
    subprocess.run(["osascript", "-e", "beep"], capture_output=True)

    open_in_chrome(CLAUDE_CODE_URL)
    time.sleep(0.5)
    play_music()
    # Script exits here → LaunchAgent will restart it automatically


# ---------------------------------------------------------------------------
# Audio detection
# ---------------------------------------------------------------------------

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
            print(f"  Clap! (x{len(clap_times)})  amp={amplitude:.4f}  ratio={ratio:.1f}x")

            if (len(clap_times) >= CLAPS_REQUIRED
                    and (now - last_trigger_time) >= TRIGGER_COOLDOWN):
                last_trigger_time = now
                clap_times.clear()
                # daemon=False so process stays alive until music download finishes
                threading.Thread(target=activate_tony_stark_mode, daemon=False).start()


def calibrate_callback(indata: np.ndarray, frames: int, time_info, status) -> None:
    amplitude = float(np.sqrt(np.mean(indata ** 2)))
    bar = "#" * int(amplitude * 400)
    print(f"\r  amp={amplitude:.5f}  |{bar:<40}|  ", end="", flush=True)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    if "--calibrate" in sys.argv:
        print("=== CALIBRATION MODE ===")
        print("Watch the bar — clap and note the peak amplitude.")
        print("If claps are missed, lower CLAP_RATIO. If too sensitive, raise it.")
        print("Press Ctrl+C to quit.\n")
        try:
            with sd.InputStream(samplerate=SAMPLE_RATE, blocksize=BLOCK_SIZE,
                                channels=1, dtype="float32",
                                callback=calibrate_callback):
                while True:
                    time.sleep(0.1)
        except KeyboardInterrupt:
            print("\nDone.")
        return

    print("╔══════════════════════════════════════════════╗")
    print("║   Hand Clap Gesture Launcher — Tony Stark   ║")
    print("╠══════════════════════════════════════════════╣")
    print("║  Clap TWICE to:                              ║")
    print("║    • Open Claude Code in Chrome              ║")
    print("║    • Play Tony Stark music                   ║")
    print("║  --calibrate  to tune sensitivity            ║")
    print("╚══════════════════════════════════════════════╝\n")

    try:
        with sd.InputStream(samplerate=SAMPLE_RATE, blocksize=BLOCK_SIZE,
                            channels=1, dtype="float32",
                            callback=audio_callback):
            print(f"Listening... (ratio={CLAP_RATIO}x, {CLAPS_REQUIRED} claps in {CLAP_WINDOW}s)\n")
            while not _stop_event.is_set():
                time.sleep(0.1)
        print("Listener stopped.")
    except KeyboardInterrupt:
        print("\nGoodbye, Mr. Stark.")
    except sd.PortAudioError as e:
        print(f"\nMicrophone error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
