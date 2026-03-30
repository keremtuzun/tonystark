#!/usr/bin/env python3
"""
Hand Clap Gesture Launcher - Tony Stark Mode

First double clap  → say "WELCOME KEREM", open all apps, play music
Second double clap → stop music, close tabs, go back to listening

Usage:
  python3 clap_launcher.py             # normal mode
  python3 clap_launcher.py --calibrate # see live amplitude to tune sensitivity

Requirements:
  pip install sounddevice numpy yt-dlp
"""

import glob
import os
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

CLAP_RATIO     = 12.0   # clap must be this many × louder than background noise
CLAP_MIN_AMP   = 0.03   # absolute minimum amplitude — filters out mouse clicks
CLAP_HF_RATIO  = 0.35   # fraction of energy above 1 kHz (claps are broadband)
CLAPS_REQUIRED = 2
CLAP_WINDOW    = 1.5    # seconds — window to count claps in
INTER_CLAP_SILENCE = 0.15  # seconds — debounce gap between clap counts
TRIGGER_COOLDOWN   = 3.0   # seconds — min gap between full triggers

URLS_TO_OPEN = [
    "https://claude.ai/code",
    "https://claude.ai",
    "https://classroom.google.com",
    "https://docs.google.com",
]


MUSIC_QUERY = "AC/DC Back in Black"
MUSIC_TMP   = "/tmp/tonystark_music"

# --- State ---
clap_times: list[float] = []
last_trigger_time: float = 0.0
last_clap_time: float    = 0.0
background_level: float  = 0.001
_lock = threading.Lock()

# Toggle state: "idle" → activate on clap; "active" → deactivate on clap
app_state = "idle"


# ---------------------------------------------------------------------------
# Chrome helpers
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


def get_open_chrome_urls() -> list[str]:
    """Return a list of all URLs currently open in Chrome tabs (macOS)."""
    if sys.platform != "darwin":
        return []
    script = """
    tell application "Google Chrome"
        set urlList to {}
        repeat with w in (every window)
            repeat with t in (every tab of w)
                set end of urlList to (URL of t)
            end repeat
        end repeat
        return urlList
    end tell
    """
    result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    if result.returncode != 0:
        return []
    # osascript returns comma-separated values
    return [u.strip() for u in result.stdout.strip().split(",") if u.strip()]


def is_tab_open(target_url: str, open_urls: list[str]) -> bool:
    """Check if a tab with exactly this URL (ignoring trailing slash) is already open."""
    target = target_url.rstrip("/")
    return any(u.rstrip("/") == target for u in open_urls)


# ---------------------------------------------------------------------------
# Music
# ---------------------------------------------------------------------------

def stop_music() -> None:
    subprocess.run(["pkill", "afplay"], capture_output=True)
    subprocess.run(["pkill", "mpv"],    capture_output=True)


def play_music() -> None:
    if shutil.which("mpv"):
        print("  Playing via mpv...")
        subprocess.Popen(
            ["mpv", f"ytdl://ytsearch1:{MUSIC_QUERY}", "--no-video"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return

    if sys.platform == "darwin":
        for old in glob.glob(MUSIC_TMP + ".*"):
            try:
                os.remove(old)
            except OSError:
                pass
        print("  Downloading music via yt-dlp...")
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
                    print("  Playing via afplay...")
                    subprocess.Popen(
                        ["afplay", files[0]],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        start_new_session=True,
                    )
                    return
        except subprocess.TimeoutExpired:
            print("  Download timed out.")
        except Exception as e:
            print(f"  yt-dlp error: {e}")

    query = MUSIC_QUERY.replace(" ", "+")
    open_in_chrome(f"https://www.youtube.com/results?search_query={query}")


# ---------------------------------------------------------------------------
# Activate / Deactivate
# ---------------------------------------------------------------------------

def activate() -> None:
    global app_state
    app_state = "active"
    print("\n*** TONY STARK MODE ACTIVATED ***\n")

    # Voice greeting
    subprocess.Popen(["say", "-r", "180", "WELCOME KEREM"],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # Open tabs only if not already open
    open_urls = get_open_chrome_urls()
    for url in URLS_TO_OPEN:
        if is_tab_open(url, open_urls):
            print(f"  Already open, skipping: {url}")
        else:
            open_in_chrome(url)
            time.sleep(0.3)

    # Play music (blocking download if needed — daemon=False keeps process alive)
    play_music()


def deactivate() -> None:
    global app_state
    app_state = "idle"
    print("\n*** STOPPING MUSIC ***\n")
    stop_music()


def handle_trigger() -> None:
    """Called in a non-daemon thread on each confirmed double clap."""
    global app_state
    if app_state == "idle":
        activate()
    else:
        deactivate()


# ---------------------------------------------------------------------------
# Audio detection
# ---------------------------------------------------------------------------

def audio_callback(indata: np.ndarray, frames: int, time_info, status) -> None:
    global clap_times, last_trigger_time, last_clap_time, background_level

    if status:
        print(f"[audio] {status}", file=sys.stderr)

    amplitude = float(np.sqrt(np.mean(indata ** 2)))
    now = time.monotonic()

    if amplitude < background_level * 3:
        background_level = background_level * 0.995 + amplitude * 0.005

    ratio = amplitude / max(background_level, 1e-6)

    frame = indata[:, 0]
    fft_mag = np.abs(np.fft.rfft(frame)) ** 2
    freqs   = np.fft.rfftfreq(len(frame), 1.0 / SAMPLE_RATE)
    total   = fft_mag.sum()
    hf_ratio = float(fft_mag[freqs >= 1000].sum() / max(total, 1e-10))

    with _lock:
        is_clap = (
            amplitude >= CLAP_MIN_AMP
            and ratio  >= CLAP_RATIO
            and hf_ratio >= CLAP_HF_RATIO
            and (now - last_clap_time) >= INTER_CLAP_SILENCE
        )
        if is_clap:
            last_clap_time = now
            clap_times.append(now)
            clap_times = [t for t in clap_times if now - t <= CLAP_WINDOW]
            print(f"  Clap! (x{len(clap_times)})  amp={amplitude:.4f}  ratio={ratio:.1f}x  hf={hf_ratio:.2f}")

            if (len(clap_times) >= CLAPS_REQUIRED
                    and (now - last_trigger_time) >= TRIGGER_COOLDOWN):
                last_trigger_time = now
                clap_times.clear()
                threading.Thread(target=handle_trigger, daemon=False).start()


def calibrate_callback(indata: np.ndarray, frames: int, time_info, status) -> None:
    amplitude = float(np.sqrt(np.mean(indata ** 2)))
    frame    = indata[:, 0]
    fft_mag  = np.abs(np.fft.rfft(frame)) ** 2
    freqs    = np.fft.rfftfreq(len(frame), 1.0 / SAMPLE_RATE)
    hf_ratio = float(fft_mag[freqs >= 1000].sum() / max(fft_mag.sum(), 1e-10))
    bar = "#" * int(amplitude * 400)
    print(f"\r  amp={amplitude:.5f}  hf={hf_ratio:.2f}  |{bar:<40}|  ", end="", flush=True)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    if "--calibrate" in sys.argv:
        print("=== CALIBRATION MODE ===")
        print("Clap and note amp + hf values. Mouse clicks should show low amp.")
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

    print("╔══════════════════════════════════════════════════════╗")
    print("║       Hand Clap Gesture Launcher — Tony Stark       ║")
    print("╠══════════════════════════════════════════════════════╣")
    print("║  Clap TWICE to activate:                            ║")
    print("║    • Says  \"WELCOME KEREM\"                          ║")
    print("║    • Opens Claude Code, Claude, Classroom, Docs     ║")
    print("║    • Plays AC/DC Back in Black                      ║")
    print("║  Clap TWICE again to close everything               ║")
    print("║  --calibrate  to tune sensitivity                   ║")
    print("╚══════════════════════════════════════════════════════╝\n")

    try:
        with sd.InputStream(samplerate=SAMPLE_RATE, blocksize=BLOCK_SIZE,
                            channels=1, dtype="float32",
                            callback=audio_callback):
            print(f"Listening... (ratio={CLAP_RATIO}x, {CLAPS_REQUIRED} claps in {CLAP_WINDOW}s)\n")
            while True:
                time.sleep(0.1)
    except KeyboardInterrupt:
        print("\nGoodbye, Mr. Stark.")
    except sd.PortAudioError as e:
        print(f"\nMicrophone error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
