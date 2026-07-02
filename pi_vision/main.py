#!/usr/bin/env python3
"""Pi-side entry point: capture IMX519 frames and stream them to the phone.

Step 1 of PI_ZERO_VISION_PLAN.md (data path, no BLE yet). The phone runs the
TCP server (`PiFrameServer`); this dials it and pushes length-prefixed JPEGs.

Usage:
    python3 main.py                 # auto-detect the phone (default gateway)
    python3 main.py --host 192.168.1.50
    python3 main.py --host 192.168.43.1 --port 8765 --width 640 --height 480

On a phone hotspot the phone is the Pi's default gateway, so `--host` can be
omitted. On a shared home WiFi (handy for early testing) the gateway is the
router, not the phone, so pass the phone's IP with `--host`.
"""

import argparse
import logging
import signal
import subprocess
import sys
import time

import config
from camera import Camera, CameraError
from frame_sender import FrameSender
from gateway import detect_gateway

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
log = logging.getLogger("pi_vision.main")

_running = True


def _handle_signal(signum, _frame):
    global _running
    log.info("Received signal %s — shutting down", signum)
    _running = False


def parse_args():
    p = argparse.ArgumentParser(description="Pi Zero vision frame sender")
    p.add_argument("--host", default=None,
                   help="Phone IP. Default: auto-detect (default gateway).")
    p.add_argument("--port", type=int, default=config.FRAME_PORT)
    p.add_argument("--width", type=int, default=config.CAPTURE_WIDTH)
    p.add_argument("--height", type=int, default=config.CAPTURE_HEIGHT)
    p.add_argument("--quality", type=int, default=config.JPEG_QUALITY)
    p.add_argument("--max-fps", type=float, default=config.MAX_FPS,
                   help="0 or negative = uncapped.")
    return p.parse_args()


def resolve_host(args):
    if args.host:
        return args.host
    gw = detect_gateway()
    if gw:
        log.info("Auto-detected phone (default gateway): %s", gw)
        return gw
    log.error(
        "No --host given and no default gateway found. Connect to the phone's "
        "hotspot first, or pass --host <phone-ip>."
    )
    return None


def _log_health():
    """Log SoC temperature + throttle/under-voltage flags via vcgencmd.

    Under-voltage (bit 0 / sticky bit 16 of get_throttled) is the classic
    power-bank failure mode, and thermal throttling silently halves the frame
    rate in a sealed cane housing — both must show up in journalctl, and both
    feed the thesis power/thermal measurements. Best-effort: never fatal.
    """
    try:
        temp = subprocess.check_output(
            ["vcgencmd", "measure_temp"], text=True, timeout=3
        ).strip()
        throttled = subprocess.check_output(
            ["vcgencmd", "get_throttled"], text=True, timeout=3
        ).strip()
        flags = int(throttled.split("=")[1], 16)
        notes = []
        if flags & 0x1:
            notes.append("UNDER-VOLTAGE NOW")
        if flags & 0x4:
            notes.append("THROTTLED NOW")
        if flags & 0x10000:
            notes.append("under-voltage occurred")
        if flags & 0x40000:
            notes.append("throttling occurred")
        log.info(
            "Health: %s %s%s",
            temp, throttled, f" [{', '.join(notes)}]" if notes else "",
        )
    except Exception as e:  # pragma: no cover - telemetry only
        log.debug("Health probe unavailable: %s", e)


def run(args, host):
    """Main capture→send loop with reconnect/backoff. Returns an exit code."""
    min_frame_interval = (
        1.0 / args.max_fps if args.max_fps and args.max_fps > 0 else 0.0
    )
    # Host came from gateway auto-detection (no --host): allow re-detection if
    # the connection keeps failing — the Pi may have re-associated to a
    # different network, making the remembered gateway stale forever.
    host_is_auto = args.host is None

    camera = Camera(args.width, args.height, args.quality)
    try:
        camera.start()
    except CameraError as e:
        log.error("%s", e)
        return 2

    sender = FrameSender(host, args.port)
    backoff = config.RECONNECT_BACKOFF_START
    last_frame_at = 0.0
    frames_sent = 0
    last_health_at = 0.0

    try:
        while _running:
            # 0) Periodic device health (temperature / under-voltage) log.
            if (
                config.HEALTH_LOG_INTERVAL_S
                and time.monotonic() - last_health_at
                    >= config.HEALTH_LOG_INTERVAL_S
            ):
                last_health_at = time.monotonic()
                _log_health()

            # 1) Ensure we have a live connection (the app may not be up yet).
            if not sender.connected:
                try:
                    sender.connect()
                    backoff = config.RECONNECT_BACKOFF_START
                except OSError as e:
                    log.warning(
                        "Connect to %s:%d failed (%s) — retrying in %.1fs",
                        host, args.port, e, backoff,
                    )
                    _interruptible_sleep(backoff)
                    backoff = min(backoff * 2, config.RECONNECT_BACKOFF_MAX)
                    # The gateway may have changed (new hotspot / re-associated
                    # WiFi) — re-detect once we're at max backoff.
                    if host_is_auto and backoff >= config.RECONNECT_BACKOFF_MAX:
                        fresh = detect_gateway()
                        if fresh and fresh != host:
                            log.info("Gateway changed %s → %s", host, fresh)
                            host = fresh
                            sender = FrameSender(host, args.port)
                    continue

            # 2) Pace to the FPS cap.
            if min_frame_interval:
                wait = min_frame_interval - (time.monotonic() - last_frame_at)
                if wait > 0:
                    _interruptible_sleep(wait)
            last_frame_at = time.monotonic()

            # 3) Capture the freshest frame and push it.
            try:
                jpeg = camera.capture_jpeg()
            except CameraError as e:
                # Camera went away mid-run — unrecoverable here, bail out so
                # systemd (later) can restart us cleanly.
                log.error("Capture failed: %s", e)
                return 2

            try:
                sender.send(jpeg)
                frames_sent += 1
                if frames_sent % 30 == 0:
                    log.info("Sent %d frames (last %d bytes)", frames_sent, len(jpeg))
            except ConnectionError as e:
                log.warning("Link dropped (%s) — will reconnect", e)
                # Loop back; the `not sender.connected` branch reconnects.
    finally:
        sender.close()
        camera.stop()
    return 0


def _interruptible_sleep(seconds):
    """Sleep in small slices so a signal stops us promptly."""
    end = time.monotonic() + seconds
    while _running and time.monotonic() < end:
        time.sleep(min(0.1, end - time.monotonic()))


def main():
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    args = parse_args()
    host = resolve_host(args)
    if not host:
        return 1
    return run(args, host)


if __name__ == "__main__":
    sys.exit(main())
