"""HC-SR04 ultrasonic reader using raw pigpio edge-timed callbacks.

**Why pigpio callbacks rather than gpiozero's `DistanceSensor`:** gpiozero's
distance algorithm is backend-agnostic and does NOT use pigpio's
hardware-timestamped edge callbacks — so even gpiozero+pigpio only buys you
steadier GPIO *access*, not steadier *timing*. Measuring the echo pulse from
pigpio's DMA-sampled edge ticks is the most accurate software method on a
non-real-time Pi, which matters most on the Pi Zero. (Refs: pigpio sonar
example; gpiozero docs note the algorithm is shared across backends.)

**Robustness:**
  * Each call pings once; we keep a short rolling window and return the MEDIAN,
    which rejects the occasional wild outlier without much lag.
  * No-echo handling distinguishes two cases:
      - echo started but never returned in time  → out of range → report the
        max distance (the phone reads that as a clear path / SAFE);
      - echo never even started (no rising edge) → sensor not responding →
        emit the ESP32-style NO_READING sentinel (-1) so the phone shows
        no-data rather than a false "clear path".

Wiring: TRIG → GPIO23 direct, ECHO → 4.5 kΩ series → GPIO24, VCC 5V, GND GND.
Requires the pigpiod daemon: `sudo systemctl enable --now pigpiod`.
"""

import logging
import time
from collections import deque

import config

log = logging.getLogger("pi_vision.sonar")

# ESP32-compatible "no valid reading" sentinel the phone parses as no-data.
NO_READING = -1.0

# Sentinel for an out-of-range ping (echo went out, nothing reflected in range).
_OUT_OF_RANGE = object()

# Speed of sound ≈ 343 m/s = 0.0343 cm/µs; halve for the round trip.
_CM_PER_US = 0.0343 / 2.0


class SonarError(RuntimeError):
    """Raised when the HC-SR04 / pigpiod can't be initialised."""


class Sonar:
    def __init__(
        self,
        trigger=None,
        echo=None,
        max_distance_m=None,
        median_window=None,
        echo_timeout_s=None,
    ):
        self._trig = config.SONAR_TRIG_GPIO if trigger is None else trigger
        self._echo = config.SONAR_ECHO_GPIO if echo is None else echo
        max_m = (
            config.SONAR_MAX_DISTANCE_M if max_distance_m is None else max_distance_m
        )
        self._max_cm = max_m * 100.0
        window = (
            config.SONAR_MEDIAN_WINDOW if median_window is None else median_window
        )
        self._timeout_s = (
            config.SONAR_ECHO_TIMEOUT_S if echo_timeout_s is None else echo_timeout_s
        )

        self._pi = None
        self._pigpio = None
        self._cb = None
        self._rise_tick = None
        self._echo_us = None
        self._samples = deque(maxlen=window)

    def start(self):
        """Connect to pigpiod and arm the echo callback. Raises SonarError."""
        try:
            import pigpio
        except ImportError as e:
            raise SonarError(
                "pigpio not installed — run `sudo apt install python3-pigpio` "
                "then `sudo systemctl enable --now pigpiod`."
            ) from e

        pi = pigpio.pi()  # connects to the local pigpiod daemon
        if not pi.connected:
            raise SonarError(
                "Could not connect to pigpiod. Start it with "
                "`sudo systemctl enable --now pigpiod`."
            )

        self._pigpio = pigpio
        self._pi = pi
        pi.set_mode(self._trig, pigpio.OUTPUT)
        pi.write(self._trig, 0)
        pi.set_mode(self._echo, pigpio.INPUT)
        self._cb = pi.callback(self._echo, pigpio.EITHER_EDGE, self._on_edge)
        time.sleep(0.05)  # let the sensor settle after power-on
        log.info(
            "HC-SR04 ready via pigpio callbacks (trigger=GPIO%d echo=GPIO%d "
            "max=%.0fcm)",
            self._trig, self._echo, self._max_cm,
        )

    def _on_edge(self, gpio, level, tick):
        # Runs in pigpio's callback thread. tick is a DMA-sampled microsecond
        # timestamp — far steadier than reading time.time() in Python.
        if level == 1:  # rising: echo pulse started
            self._rise_tick = tick
        elif level == 0 and self._rise_tick is not None:  # falling: echo back
            self._echo_us = self._pigpio.tickDiff(self._rise_tick, tick)
            self._rise_tick = None

    def _ping(self):
        """One measurement → cm (float), _OUT_OF_RANGE, or None (no response)."""
        self._echo_us = None
        self._rise_tick = None
        # 10 µs trigger pulse, timed precisely inside the daemon.
        self._pi.gpio_trigger(self._trig, config.SONAR_TRIGGER_PULSE_US, 1)

        deadline = time.monotonic() + self._timeout_s
        while self._echo_us is None and time.monotonic() < deadline:
            time.sleep(0.001)

        if self._echo_us is None:
            # No falling edge in time. A rising edge means the pulse went out
            # but nothing reflected in range; no rising edge means the sensor
            # isn't responding at all.
            return _OUT_OF_RANGE if self._rise_tick is not None else None

        cm = self._echo_us * _CM_PER_US
        if cm <= 0 or cm > self._max_cm:
            return _OUT_OF_RANGE
        return cm

    def read_cm(self):
        """Return distance in cm, max-range on a clear path, or NO_READING."""
        if self._pi is None:
            raise SonarError("Sonar not started")
        result = self._ping()
        if result is None:
            return NO_READING  # sensor not responding
        if result is _OUT_OF_RANGE:
            return self._max_cm  # clear path → SAFE on the phone
        self._samples.append(result)
        ordered = sorted(self._samples)
        return ordered[len(ordered) // 2]  # median rejects outliers

    def close(self):
        if self._cb is not None:
            try:
                self._cb.cancel()
            except Exception:
                pass
            self._cb = None
        if self._pi is not None:
            try:
                self._pi.stop()
            except Exception:
                pass
            self._pi = None
