"""HC-SR04 ultrasonic reader using lgpio with edge-timestamped callbacks.

**Why lgpio (not pigpio, not gpiozero):**
  * pigpio's daemon was *removed from Raspberry Pi OS Bookworm's repos* (it
    doesn't work on the Pi 5), so `apt install pigpio` / `pigpiod.service` no
    longer exist — it would need a from-source build.
  * gpiozero's DistanceSensor algorithm is backend-agnostic and doesn't use
    hardware edge timestamps, and its Bookworm/lgpio path is flaky for this
    sensor (PWM-fallback warnings).
  * lgpio is the *native* Bookworm GPIO library (no daemon), and its edge
    callbacks carry kernel CLOCK timestamps in nanoseconds — accurate echo
    timing without DMA, which is what we need on a non-real-time Pi.

**Robustness:**
  * Each call pings once; we keep a short rolling window and return the MEDIAN
    to reject the odd outlier without much lag.
  * Out-of-range pings (echo went out, nothing reflected) feed the max distance
    INTO the median window rather than bypassing it: on a swinging cane a
    single missed echo is routine, and reporting max instantly would flip the
    phone's verdict to SAFE mid-alarm (cancelling vibration + speech) for one
    bad ping. Through the median, a lone miss is outvoted; a genuinely clear
    path still reads max within ~3 pings (~0.6 s).
  * A no-response ping (no rising edge — sensor dead, or a clone holding ECHO
    high after a missed echo, a documented clone quirk) is tolerated
    transiently: we return the current median for the first few misses and
    emit the ESP32-style NO_READING sentinel (-1) only after
    `SONAR_FAULT_AFTER_MISSES` consecutive failures — a real fault signal, not
    a hiccup. The phone additionally has its own staleness watchdog.
  * Before each trigger we check ECHO is actually low; triggering while a
    hung clone still holds it high would corrupt the measurement.

Wiring: TRIG → GPIO23 direct, ECHO → 4.5 kΩ series → GPIO24, VCC 5V, GND GND.
No daemon required; the user just needs to be in the `gpio` group (default).
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
    """Raised when the HC-SR04 / lgpio can't be initialised."""


def _busy_wait_us(microseconds):
    """Tight spin for a very short, precise delay (the trigger pulse width)."""
    end = time.perf_counter_ns() + int(microseconds * 1000)
    while time.perf_counter_ns() < end:
        pass


class Sonar:
    def __init__(
        self,
        trigger=None,
        echo=None,
        max_distance_m=None,
        median_window=None,
        echo_timeout_s=None,
        gpiochip=None,
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
        self._gpiochip = config.SONAR_GPIOCHIP if gpiochip is None else gpiochip

        self._lgpio = None
        self._h = None
        self._cb = None
        self._rise_ns = None
        self._echo_us = None
        self._samples = deque(maxlen=window)
        self._consecutive_misses = 0

    def start(self):
        """Open the gpiochip and arm the echo callback. Raises SonarError."""
        try:
            import lgpio
        except ImportError as e:
            raise SonarError(
                "lgpio not installed — run `sudo apt install -y python3-lgpio`."
            ) from e

        try:
            h = lgpio.gpiochip_open(self._gpiochip)
        except Exception as e:
            raise SonarError(
                f"Could not open gpiochip{self._gpiochip}: {e}. Is the user in the "
                "`gpio` group? (`sudo usermod -aG gpio $USER`, then log out/in)"
            ) from e

        self._lgpio = lgpio
        self._h = h
        try:
            lgpio.gpio_claim_output(h, self._trig, 0)
            lgpio.gpio_claim_alert(h, self._echo, lgpio.BOTH_EDGES)
            self._cb = lgpio.callback(h, self._echo, lgpio.BOTH_EDGES, self._on_edge)
        except Exception as e:
            self.close()
            raise SonarError(f"Could not claim GPIO lines: {e}") from e

        time.sleep(0.05)  # let the sensor settle after power-on
        log.info(
            "HC-SR04 ready via lgpio (chip=%d trigger=GPIO%d echo=GPIO%d "
            "max=%.0fcm)",
            self._gpiochip, self._trig, self._echo, self._max_cm,
        )

    def _on_edge(self, chip, gpio, level, timestamp_ns):
        # Runs in lgpio's callback thread. level: 1 rising, 0 falling,
        # 2 watchdog. timestamp_ns is a kernel CLOCK timestamp — steady enough
        # for pulse width even though the Pi isn't real-time.
        if level == 1:  # rising: echo pulse started
            self._rise_ns = timestamp_ns
        elif level == 0 and self._rise_ns is not None:  # falling: echo back
            self._echo_us = (timestamp_ns - self._rise_ns) / 1000.0
            self._rise_ns = None

    def _ping(self):
        """One measurement → cm (float), _OUT_OF_RANGE, or None (no response)."""
        # Some HC-SR04 clones hold ECHO high (~150-240 ms, sometimes until
        # re-trigger) after a missed echo. Triggering while ECHO is still high
        # corrupts the measurement — treat it as a no-response ping instead
        # and let the next cycle retry once the line has released.
        try:
            if self._lgpio.gpio_read(self._h, self._echo) == 1:
                return None
        except Exception:
            pass  # a read failure shouldn't stop us from trying the ping

        self._echo_us = None
        self._rise_ns = None
        # 10 µs trigger pulse (a bit longer is harmless — only ECHO timing,
        # measured from the callback timestamps, affects the distance).
        self._lgpio.gpio_write(self._h, self._trig, 1)
        _busy_wait_us(config.SONAR_TRIGGER_PULSE_US)
        self._lgpio.gpio_write(self._h, self._trig, 0)

        deadline = time.monotonic() + self._timeout_s
        while self._echo_us is None and time.monotonic() < deadline:
            time.sleep(0.001)

        if self._echo_us is None:
            # No falling edge in time. A rising edge means the pulse went out
            # but nothing reflected in range; no rising edge means the sensor
            # isn't responding at all.
            return _OUT_OF_RANGE if self._rise_ns is not None else None

        cm = self._echo_us * _CM_PER_US
        if cm <= 0 or cm > self._max_cm:
            return _OUT_OF_RANGE
        return cm

    def read_cm(self):
        """Return the median distance in cm (max-range = clear path), or
        NO_READING after several consecutive failed pings (sensor fault)."""
        if self._h is None:
            raise SonarError("Sonar not started")
        result = self._ping()

        if result is None:
            # No response at all. One miss is a hiccup (clone quirk, EMI) —
            # hold the last known picture; several in a row is a real fault
            # the phone must hear about (it must never trust silence).
            self._consecutive_misses += 1
            if self._consecutive_misses >= config.SONAR_FAULT_AFTER_MISSES:
                self._samples.clear()  # stale data must not outlive the fault
                return NO_READING
            if self._samples:
                ordered = sorted(self._samples)
                return ordered[len(ordered) // 2]
            return NO_READING
        self._consecutive_misses = 0

        # Out-of-range is a legitimate "nothing within 4 m" measurement — feed
        # it through the median like any other sample. Bypassing the filter
        # here would let a single missed echo flip the phone to SAFE mid-alarm.
        self._samples.append(
            self._max_cm if result is _OUT_OF_RANGE else result
        )
        ordered = sorted(self._samples)
        return ordered[len(ordered) // 2]  # median rejects outliers

    def close(self):
        if self._cb is not None:
            try:
                self._cb.cancel()
            except Exception:
                pass
            self._cb = None
        if self._h is not None and self._lgpio is not None:
            try:
                self._lgpio.gpiochip_close(self._h)
            except Exception:
                pass
            self._h = None
