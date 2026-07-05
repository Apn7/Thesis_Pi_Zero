#!/usr/bin/env python3
"""Pi-side entry point: read the HC-SR04, alert locally, stream to the phone.

STANDALONE-FIRST. The cane must protect its user even with no phone anywhere
near it, so this process is split into two halves with a strict rule — the
sensing half never waits on the network:

  sense loop (main thread — the cane's reflex arc):
      read HC-SR04 → median (sonar_reader) → verdict (verdict.py, same
      thresholds + hysteresis as the app) → buzzer/vibration (feedback.py)

  network thread (best-effort telemetry):
      detect the phone → connect → push newline-delimited centimetre lines
      (newest-wins; a slow/absent phone just misses readings, it can never
      stall the reflex arc)

Synchronization with the app is by construction, not coordination: the phone
receives the SAME median value classified here and applies the SAME rules
(`distance_alert_source.dart`), so when both are alive the stick vibrates when
the phone vibrates and the buzzer sounds when the app says critical. No
verdict bytes travel over the wire — each device computes its own.

Usage:
    python3 sonar_main.py                       # standalone + auto-detect phone
    python3 sonar_main.py --host 192.168.43.1
    python3 sonar_main.py --no-feedback         # bench: sensor/network only

Auto-detection handles both topologies: on the phone's hotspot (dev) the
phone is the default gateway; when the Pi hosts `smartcane-ap` (production)
the phone is the associated DHCP client. With no phone present the network
thread just keeps waiting — local feedback runs regardless. On a shared home
WiFi (early testing) pass the phone's IP with `--host`.

Runs happily alongside main.py (camera): different GPIOs, different TCP port.
"""

import argparse
import logging
import signal
import sys
import threading
import time

import config
from feedback import FeedbackController, FeedbackError
from gateway import detect_phone
from sonar_reader import NO_READING, Sonar, SonarError
from sonar_sender import SonarSender
from verdict import Verdict, verdict_for_distance_cm_sticky

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
    p = argparse.ArgumentParser(
        description="Pi Zero HC-SR04 distance: local alerts + phone sender"
    )
    p.add_argument("--host", default=None,
                   help="Phone IP. Default: auto-detect (gateway/AP client).")
    p.add_argument("--port", type=int, default=config.SONAR_PORT)
    p.add_argument("--interval", type=float, default=config.SONAR_INTERVAL_S,
                   help="Seconds between readings.")
    p.add_argument("--max-distance", type=float,
                   default=config.SONAR_MAX_DISTANCE_M,
                   help="Sensor max range in metres.")
    p.add_argument("--no-feedback", action="store_true",
                   help="Skip the buzzer/vibration (bench without modules).")
    return p.parse_args()


class LatestReading:
    """Newest-wins mailbox between the sense loop and the network thread.

    Same philosophy as the camera path's latest-frame-wins: if the network is
    slow, intermediate readings are dropped, never queued — the phone always
    gets the freshest picture and the sense loop never blocks.
    """

    def __init__(self):
        self._cond = threading.Condition()
        self._value = None
        self._seq = 0

    def publish(self, cm):
        with self._cond:
            self._value = cm
            self._seq += 1
            self._cond.notify_all()

    def take(self, last_seq, timeout):
        """Return (cm, seq) for a reading newer than last_seq, or
        (None, last_seq) on timeout."""
        with self._cond:
            if self._seq == last_seq:
                self._cond.wait(timeout)
            if self._seq == last_seq:
                return None, last_seq
            return self._value, self._seq


def _network_loop(args, latest, stop):
    """Best-effort sender: find the phone, connect, push readings, reconnect.

    Owns every blocking network operation (detection, connect timeouts,
    backoff sleeps) so none of it can ever delay the sense loop.
    """
    host_is_auto = args.host is None
    host = args.host
    sender = None
    backoff = config.RECONNECT_BACKOFF_START
    readings_sent = 0
    seq = 0

    while not stop.is_set():
        # 1) Know where the phone is. With the Pi as its own AP the service
        #    boots long before any phone joins — waiting here is the normal
        #    state, and the sense loop keeps alerting throughout.
        if host is None:
            host = detect_phone()
            if host is None:
                stop.wait(2.0)
                continue
            log.info("Phone detected at %s", host)
            sender = None  # force a fresh socket for the (new) host

        if sender is None:
            sender = SonarSender(host, args.port)

        # 2) Ensure a live connection (the app may not be up yet).
        if not sender.connected:
            try:
                sender.connect()
                backoff = config.RECONNECT_BACKOFF_START
            except OSError as e:
                log.warning(
                    "Connect to %s:%d failed (%s) — retrying in %.1fs",
                    host, args.port, e, backoff,
                )
                stop.wait(backoff)
                backoff = min(backoff * 2, config.RECONNECT_BACKOFF_MAX)
                # The phone may have moved (new hotspot / fresh DHCP lease on
                # our AP) — re-detect once we're at max backoff.
                if host_is_auto and backoff >= config.RECONNECT_BACKOFF_MAX:
                    fresh = detect_phone()
                    if fresh and fresh != host:
                        log.info("Phone moved %s → %s", host, fresh)
                        host = fresh
                        sender = None
                continue

        # 3) Ship the freshest reading (blocks briefly when none is new).
        cm, seq = latest.take(seq, timeout=1.0)
        if cm is None:
            continue
        try:
            sender.send_cm(cm)
            readings_sent += 1
            if readings_sent % 50 == 0:
                label = "no-echo" if cm == NO_READING else f"{cm:.1f}cm"
                log.info("Sent %d readings (last %s)", readings_sent, label)
        except ConnectionError as e:
            log.warning("Link dropped (%s) — will reconnect", e)

    if sender is not None:
        sender.close()


def _interruptible_sleep(seconds):
    """Sleep in small slices so a signal stops us promptly."""
    if seconds <= 0:
        return
    end = time.monotonic() + seconds
    while _running and time.monotonic() < end:
        time.sleep(min(0.1, end - time.monotonic()))


def run(args):
    """Sense loop: read → classify → local feedback → publish. Never blocks
    on the network. Returns an exit code."""
    sonar = Sonar(max_distance_m=args.max_distance)
    try:
        sonar.start()
    except SonarError as e:
        log.error("%s", e)
        return 2

    # Local feedback is the standalone safety layer — but a wiring fault in
    # the buzzer/motor must not take the distance stream down with it, so a
    # failed init degrades to network-only with a loud log instead of exiting.
    feedback = None
    if args.no_feedback:
        log.info("Local feedback disabled (--no-feedback)")
    else:
        fb = FeedbackController()
        try:
            fb.start()
            feedback = fb
        except FeedbackError as e:
            log.error("Feedback init failed (%s) — continuing without "
                      "cane-local alerts", e)

    latest = LatestReading()
    stop = threading.Event()
    net = threading.Thread(
        target=_network_loop, args=(args, latest, stop),
        name="network", daemon=True,
    )
    net.start()

    previous = Verdict.NO_DATA
    try:
        while _running:
            cm = sonar.read_cm()

            # Classify the exact value we ship — this is what keeps the
            # cane and the phone in lockstep (see module docstring).
            v = verdict_for_distance_cm_sticky(cm, previous)
            if v is not previous:
                log.info("Verdict %s → %s (%.1f cm)",
                         previous.value, v.value, cm)
                previous = v
            if feedback is not None:
                feedback.set_verdict(v)

            latest.publish(cm)
            _interruptible_sleep(args.interval)
    finally:
        stop.set()
        latest.publish(None)  # wake the network thread if it's in take()
        net.join(timeout=3.0)
        if feedback is not None:
            feedback.close()
        sonar.close()
    return 0


def main():
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)
    return run(parse_args())


if __name__ == "__main__":
    sys.exit(main())
