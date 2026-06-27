#!/usr/bin/env python3
"""Pi-side entry point: read the HC-SR04 and stream distance to the phone.

The WiFi replacement for the ESP32 ultrasonic path. The phone runs the TCP
server (`PiDistanceService`, mirroring `PiFrameServer`); this dials it and
pushes newline-delimited centimetre readings. The phone classifies them into
the same CRITICAL/WARNING/CAUTION verdicts it used for the ESP32 — so no
firmware-style thresholds live here.

Usage:
    python3 sonar_main.py                       # auto-detect the phone (gateway)
    python3 sonar_main.py --host 192.168.43.1
    python3 sonar_main.py --port 8766 --interval 0.2 --max-distance 4.0

On a phone hotspot the phone is the Pi's default gateway, so `--host` can be
omitted. On a shared home WiFi (handy for early testing) the gateway is the
router, so pass the phone's IP with `--host`.

Runs happily alongside main.py (camera): different GPIOs, different TCP port —
both just need the phone reachable on WiFi.
"""

import argparse
import logging
import signal
import sys
import time

import config
from gateway import detect_gateway
from sonar_reader import NO_READING, Sonar, SonarError
from sonar_sender import SonarSender

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
log = logging.getLogger("pi_vision.sonar_main")

_running = True


def _handle_signal(signum, _frame):
    global _running
    log.info("Received signal %s — shutting down", signum)
    _running = False


def parse_args():
    p = argparse.ArgumentParser(description="Pi Zero HC-SR04 distance sender")
    p.add_argument("--host", default=None,
                   help="Phone IP. Default: auto-detect (default gateway).")
    p.add_argument("--port", type=int, default=config.SONAR_PORT)
    p.add_argument("--interval", type=float, default=config.SONAR_INTERVAL_S,
                   help="Seconds between readings.")
    p.add_argument("--max-distance", type=float,
                   default=config.SONAR_MAX_DISTANCE_M,
                   help="Sensor max range in metres.")
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


def run(args, host):
    """Main read→send loop with reconnect/backoff. Returns an exit code."""
    sonar = Sonar(max_distance_m=args.max_distance)
    try:
        sonar.start()
    except SonarError as e:
        log.error("%s", e)
        return 2

    sender = SonarSender(host, args.port)
    backoff = config.RECONNECT_BACKOFF_START
    readings_sent = 0

    try:
        while _running:
            # 1) Ensure a live connection (the app may not be up yet).
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
                    continue

            # 2) Read one distance and push it.
            cm = sonar.read_cm()
            try:
                sender.send_cm(cm)
                readings_sent += 1
                if readings_sent % 50 == 0:
                    label = "no-echo" if cm == NO_READING else f"{cm:.1f}cm"
                    log.info("Sent %d readings (last %s)", readings_sent, label)
            except ConnectionError as e:
                log.warning("Link dropped (%s) — will reconnect", e)
                # Loop back; the `not sender.connected` branch reconnects.
                continue

            # 3) Pace to the configured interval.
            _interruptible_sleep(args.interval)
    finally:
        sender.close()
        sonar.close()
    return 0


def _interruptible_sleep(seconds):
    """Sleep in small slices so a signal stops us promptly."""
    if seconds <= 0:
        return
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
