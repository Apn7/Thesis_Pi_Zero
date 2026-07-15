"""Find the passive buzzer's loudest drive frequency by ear.

The MH-FMD module's piezo is passive and unlabelled: its mechanical resonance
is unknown, and a piezo driven AT resonance is dramatically louder than a few
hundred hertz off it. config.BUZZER_TONE_HZ (2700) was picked by ear; this
tool sweeps a band of candidate tones so you can pick the true peak.

Usage (on the Pi, wired per BUZZER_VIBRATION_WIRING.md):

    python3 buzzer_sweep.py                 # 1800..4400 Hz in 200 Hz steps
    python3 buzzer_sweep.py 2400 3200 100   # start, stop, step overrides
    python3 buzzer_sweep.py --fine 3000     # ±300 Hz around 3000 in 50 Hz steps

Each tone plays ~0.6 s with its frequency printed first; note the one or two
loudest, re-run with --fine around the winner, then write the result into
config.BUZZER_TONE_HZ. Run it with the buzzer mounted in the cane grip — the
enclosure shifts the effective resonance, so don't tune it bare on a bench.

Same drive path as feedback.py (lgpio tx_pwm at 50 % duty through the
active-low PNP), so what you hear is exactly what the alert will sound like.
Ctrl-C safe: pins are parked silent on any exit.
"""

import sys
import time

import config

TONE_S = 0.6   # per-tone play time
GAP_S = 0.25   # silence between tones (lets the ear reset)
_BUZZER_OFF = 1  # PNP high-side: high = silent (same as feedback.py)


def _parse_args(argv):
    if argv and argv[0] == "--fine":
        center = int(argv[1]) if len(argv) > 1 else config.BUZZER_TONE_HZ
        return center - 300, center + 300, 50
    start = int(argv[0]) if len(argv) > 0 else 1800
    stop = int(argv[1]) if len(argv) > 1 else 4400
    step = int(argv[2]) if len(argv) > 2 else 200
    return start, stop, step


def main(argv):
    start, stop, step = _parse_args(argv)
    try:
        import lgpio
    except ImportError:
        print("lgpio not installed — run `sudo apt install -y python3-lgpio`.")
        return 2
    if not hasattr(lgpio, "tx_pwm"):
        print("This lgpio build has no tx_pwm — cannot drive a passive piezo.")
        return 2

    h = lgpio.gpiochip_open(config.SONAR_GPIOCHIP)
    lgpio.gpio_claim_output(h, config.BUZZER_GPIO, _BUZZER_OFF)
    print(f"Sweeping {start}..{stop} Hz in {step} Hz steps "
          f"({TONE_S:.1f} s per tone). Note the loudest; Ctrl-C to stop.")
    try:
        for hz in range(start, stop + 1, step):
            print(f"  {hz} Hz")
            lgpio.tx_pwm(h, config.BUZZER_GPIO, hz, 50)
            time.sleep(TONE_S)
            lgpio.tx_pwm(h, config.BUZZER_GPIO, 0, 0)
            lgpio.gpio_write(h, config.BUZZER_GPIO, _BUZZER_OFF)
            time.sleep(GAP_S)
        print("Done. Re-run with `--fine <loudest>` to narrow, then set "
              "config.BUZZER_TONE_HZ.")
        return 0
    except KeyboardInterrupt:
        print("\nInterrupted.")
        return 130
    finally:
        try:
            lgpio.tx_pwm(h, config.BUZZER_GPIO, 0, 0)
            lgpio.gpio_write(h, config.BUZZER_GPIO, _BUZZER_OFF)
        except Exception:
            pass
        lgpio.gpiochip_close(h)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
