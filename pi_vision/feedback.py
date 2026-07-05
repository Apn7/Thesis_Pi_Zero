"""Cane-local alert feedback: vibration motor + buzzer driven by the verdict.

This is what makes the cane STANDALONE: `sonar_main.py` classifies every
distance reading on the Pi (verdict.py) and this module turns the verdict into
physical alerts — no phone, no app, no network required. When the app IS
connected it receives the same readings and classifies them with the same
rules, so phone and cane alert in lockstep rather than fighting each other.

Pattern vocabulary — deliberately the same *rhythms* as the app's
`home_screen.dart` `_vibrateForVerdict`, so the cane grip and the phone in the
pocket speak one haptic language:

  CRITICAL  motor: five 600 ms pulses / 80 ms gaps, then a ~90 % duty loop
                   (450 ms on / 50 ms off) — effectively continuous.
            buzzer: fast beeps (100 ms on / 100 ms off) the whole time the
                   verdict holds — the audible "stop right now" cue. The
                   buzzer is reserved for CRITICAL (like the app's alert
                   tone): scarcity is what keeps it meaningful.
  WARNING   motor: double pulse (250/120/250 ms), then one 250 ms pulse every
                   1.5 s. Buzzer silent.
  CAUTION   motor: triple tap (80 on / 80 off ×3) every 2.5 s. Buzzer silent.
  SAFE /    everything off. Absence of alarm IS the all-clear; and a sensor
  NO_DATA   fault (NO_DATA) must silence the alarm, never latch it.

The motor always runs at 100 % drive: the app separates CAUTION by a softer
intensity (200/255), but an ERM motor needs a full-power kick-start and an
80 ms tap at partial duty may not spin up from rest at all. Tiers stay
distinguishable by rhythm — the app itself relies on rhythm, not strength.

Engine: one daemon thread ticks every FEEDBACK_TICK_S and computes the desired
motor/buzzer state purely from (verdict, time-since-verdict-change). Stateless
pattern math means no drift, no queued pulses to cancel, and a verdict change
takes effect within one tick. GPIO is touched only from this thread (plus
`close()` after the thread has been joined), so no lgpio call ever races.

Hardware notes (validated on the bench 2026-07-05, see
BUZZER_VIBRATION_WIRING.md): MH-FMD buzzer on GPIO5 is ACTIVE-LOW through a
PNP high-side switch and its piezo is PASSIVE — it must be driven with a PWM
tone (`lgpio.tx_pwm` at BUZZER_TONE_HZ), a static LOW only clicks once. The
KS0450-class motor on GPIO13 is ACTIVE-HIGH. Both idle states are safe at
boot thanks to the pin choice (GPIO5 pulls up, GPIO13 pulls down).

Self-test (replaces the old feedback_test.py — run after wiring changes):

    python3 feedback.py            # plays CAUTION → WARNING → CRITICAL → off

If a run ever dies leaving the buzzer latched on (kill -9, power glitch), the
manual kill switch is `pinctrl set 5 op dh` (buzzer off) /
`pinctrl set 13 op dl` (motor off).
"""

import logging
import threading
import time

import config
from verdict import Verdict

log = logging.getLogger("pi_vision.feedback")

# Trigger polarities, from the hardware (see module docstring).
_MOTOR_ON, _MOTOR_OFF = 1, 0   # KS0450-class: high-level trigger
_BUZZER_OFF = 1                # PNP off = silent; ON is a PWM tone, not a level


class FeedbackError(RuntimeError):
    """Raised when the buzzer/motor GPIOs can't be initialised."""


def _pattern_states(verdict, t_ms):
    """(motor_on, buzzer_on) for a verdict at t_ms since the verdict began.

    Pure function of time — mirrors home_screen.dart's timings (see the
    module docstring for the vocabulary and the rationale).
    """
    if verdict is Verdict.CRITICAL:
        if t_ms < 3400:  # opening burst: 5 × (600 on + 80 off)
            motor = (t_ms % 680) < 600
        else:            # sustained ~90 % duty loop
            motor = ((t_ms - 3400) % 500) < 450
        buzzer = (t_ms % 200) < 100  # fast beeps for as long as CRITICAL holds
        return motor, buzzer

    if verdict is Verdict.WARNING:
        # Opening double pulse (250/120/250), then one 250 ms pulse per 1.5 s.
        # t % 1500 < 250 covers both the first pulse and every repeat; the
        # 370–620 window is the second pulse of the opening double (once only).
        motor = (t_ms % 1500) < 250 or (370 <= t_ms < 620)
        return motor, False

    if verdict is Verdict.CAUTION:
        # Triple tap (80 on / 80 off ×3 = 400 ms window) every 2.5 s.
        p = t_ms % 2500
        motor = p < 400 and (p % 160) < 80
        return motor, False

    return False, False  # SAFE / NO_DATA: everything off


class FeedbackController:
    """Owns the buzzer + motor GPIOs and plays the pattern for the current
    verdict until told otherwise.

    Usage: `start()` once (raises FeedbackError if the GPIOs are unusable),
    then `set_verdict()` from any thread as often as you like — it's a cheap
    atomic assignment; the worker notices changes within one tick. `close()`
    stops the thread and parks both pins in their safe state.
    """

    def __init__(self, gpiochip=None):
        self._gpiochip = config.SONAR_GPIOCHIP if gpiochip is None else gpiochip
        self._lgpio = None
        self._h = None
        self._has_pwm = False
        self._verdict = Verdict.NO_DATA
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        """Claim the GPIOs (safe idle levels) and start the pattern thread."""
        try:
            import lgpio
        except ImportError as e:
            raise FeedbackError(
                "lgpio not installed — run `sudo apt install -y python3-lgpio`."
            ) from e

        try:
            h = lgpio.gpiochip_open(self._gpiochip)
        except Exception as e:
            raise FeedbackError(
                f"Could not open gpiochip{self._gpiochip}: {e}. Is the user "
                "in the `gpio` group? (`sudo usermod -aG gpio $USER`)"
            ) from e

        self._lgpio = lgpio
        self._h = h
        try:
            # Claiming with these initial levels must not make a sound.
            lgpio.gpio_claim_output(h, config.BUZZER_GPIO, _BUZZER_OFF)
            lgpio.gpio_claim_output(h, config.MOTOR_GPIO, _MOTOR_OFF)
        except Exception as e:
            self.close()
            raise FeedbackError(f"Could not claim feedback GPIOs: {e}") from e

        # The passive piezo needs tx_pwm to make any sound at all. A build
        # without it degrades to vibration-only rather than failing the cane.
        self._has_pwm = hasattr(lgpio, "tx_pwm")
        if not self._has_pwm:
            log.warning(
                "lgpio.tx_pwm unavailable — passive buzzer disabled, "
                "vibration-only feedback"
            )

        self._thread = threading.Thread(
            target=self._run, name="feedback", daemon=True
        )
        self._thread.start()
        log.info(
            "Feedback ready (buzzer=GPIO%d%s, motor=GPIO%d)",
            config.BUZZER_GPIO,
            "" if self._has_pwm else " [DISABLED: no tx_pwm]",
            config.MOTOR_GPIO,
        )

    def set_verdict(self, verdict):
        """Switch the active pattern. Atomic assignment — safe from any
        thread; a change restarts the new pattern from t=0 within one tick."""
        self._verdict = verdict

    def _run(self):
        active = self._verdict
        t0 = time.monotonic()
        motor_on = False
        buzzer_on = False
        while not self._stop.wait(config.FEEDBACK_TICK_S):
            v = self._verdict
            if v is not active:  # verdict changed → new pattern from t=0
                active = v
                t0 = time.monotonic()
            t_ms = (time.monotonic() - t0) * 1000.0

            want_motor, want_buzzer = _pattern_states(active, t_ms)
            # Apply only edges — re-issuing tx_pwm every tick would restart
            # the tone's phase and waste syscalls.
            if want_motor != motor_on:
                self._set_motor(want_motor)
                motor_on = want_motor
            if want_buzzer != buzzer_on:
                self._set_buzzer(want_buzzer)
                buzzer_on = want_buzzer

    def _set_motor(self, on):
        try:
            self._lgpio.gpio_write(
                self._h, config.MOTOR_GPIO, _MOTOR_ON if on else _MOTOR_OFF
            )
        except Exception as e:  # a GPIO hiccup must not kill the thread
            log.warning("Motor write failed: %s", e)

    def _set_buzzer(self, on):
        if not self._has_pwm:
            return  # passive piezo: without PWM there is no tone to make
        try:
            if on:
                self._lgpio.tx_pwm(
                    self._h, config.BUZZER_GPIO, config.BUZZER_TONE_HZ, 50
                )
            else:
                self._lgpio.tx_pwm(self._h, config.BUZZER_GPIO, 0, 0)
                self._lgpio.gpio_write(self._h, config.BUZZER_GPIO, _BUZZER_OFF)
        except Exception as e:
            log.warning("Buzzer write failed: %s", e)

    def close(self):
        """Stop the pattern thread and park both pins in their safe state."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        if self._h is not None and self._lgpio is not None:
            # Whatever happened, leave the hardware quiet.
            if self._has_pwm:
                try:
                    self._lgpio.tx_pwm(self._h, config.BUZZER_GPIO, 0, 0)
                except Exception:
                    pass
            for gpio, level in (
                (config.BUZZER_GPIO, _BUZZER_OFF),
                (config.MOTOR_GPIO, _MOTOR_OFF),
            ):
                try:
                    self._lgpio.gpio_write(self._h, gpio, level)
                except Exception:
                    pass
            try:
                self._lgpio.gpiochip_close(self._h)
            except Exception:
                pass
            self._h = None


def _self_test():
    """Hardware bring-up check: play each verdict's pattern for a few seconds.

    What you should hear/feel:
      CAUTION  — tic-tic-tic taps, repeating every 2.5 s, silent buzzer
      WARNING  — heavier double pulse then single pulses, silent buzzer
      CRITICAL — near-continuous shake + fast beeping
      then silence (SAFE) and safe pin states on exit, even via Ctrl-C.
    """
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    fb = FeedbackController()
    try:
        fb.start()
    except FeedbackError as e:
        print(f"FAILED: {e}")
        return 2
    try:
        for v, seconds in (
            (Verdict.CAUTION, 6.0),
            (Verdict.WARNING, 5.0),
            (Verdict.CRITICAL, 5.0),
            (Verdict.SAFE, 1.0),
        ):
            print(f"--> {v.value.upper()} for {seconds:.0f} s")
            fb.set_verdict(v)
            time.sleep(seconds)
        print("Done — rhythms match the app's? Bring-up complete.")
        return 0
    except KeyboardInterrupt:
        print("\nInterrupted — restoring safe pin states.")
        return 130
    finally:
        fb.close()


if __name__ == "__main__":
    import sys

    sys.exit(_self_test())
