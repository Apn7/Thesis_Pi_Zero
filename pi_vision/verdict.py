"""Distance → verdict classification, a direct port of the app's logic.

Mirrors `lib/services/distance_alert_source.dart` in the Flutter app
(`ObstacleVerdict`, `verdictForDistanceCm`, `verdictForDistanceCmSticky`).
The cane must alert standalone (phone dead, app closed), which forces the
classification to exist on both devices. To keep them synchronized we rely on
construction, not luck: the Pi classifies the SAME median centimetre value it
sends down the wire, with the same thresholds and the same hysteresis, so when
both devices are alive they compute identical verdicts from identical input —
the stick vibrates exactly when the phone vibrates.

Thresholds live in config.py (OBSTACLE_*_CM / VERDICT_HYSTERESIS_CM) with a
keep-in-sync note pointing at constants.dart. If the app's rules ever change
shape (not just values), re-port this file.
"""

from enum import Enum

import config


class Verdict(Enum):
    """Mirror of the app's `ObstacleVerdict`."""

    NO_DATA = "no_data"    # no valid reading (sensor fault / -1 sentinel)
    CRITICAL = "critical"  # < OBSTACLE_CRITICAL_CM
    WARNING = "warning"    # < OBSTACLE_WARNING_CM
    CAUTION = "caution"    # < OBSTACLE_CAUTION_CM
    SAFE = "safe"          # clear path

    @property
    def severity(self):
        """Ordinal severity for escalation comparisons (== the app's)."""
        return _SEVERITY[self]


_SEVERITY = {
    Verdict.CRITICAL: 3,
    Verdict.WARNING: 2,
    Verdict.CAUTION: 1,
    Verdict.SAFE: 0,
    Verdict.NO_DATA: 0,
}

# Boundary a *previous* verdict holds on to during de-escalation.
_BOUNDARY_CM = {
    Verdict.CRITICAL: config.OBSTACLE_CRITICAL_CM,
    Verdict.WARNING: config.OBSTACLE_WARNING_CM,
    Verdict.CAUTION: config.OBSTACLE_CAUTION_CM,
}


def verdict_for_distance_cm(distance_cm):
    """Raw classification — mirrors the app's `verdictForDistanceCm`.

    A negative value is the ESP32-style "no valid reading" sentinel (the same
    convention the phone's parser uses), not a distance.
    """
    if distance_cm is None or distance_cm < 0:
        return Verdict.NO_DATA
    if distance_cm < config.OBSTACLE_CRITICAL_CM:
        return Verdict.CRITICAL
    if distance_cm < config.OBSTACLE_WARNING_CM:
        return Verdict.WARNING
    if distance_cm < config.OBSTACLE_CAUTION_CM:
        return Verdict.CAUTION
    return Verdict.SAFE


def verdict_for_distance_cm_sticky(distance_cm, previous):
    """Classification with de-escalation hysteresis — mirrors the app's
    `verdictForDistanceCmSticky`.

    A cane swinging at a threshold boundary makes the raw verdict flap between
    adjacent levels on nearly every reading, restarting the alert pattern each
    time. Same policy as the phone:

      * Escalation is instant — severity going UP passes through unmodified.
      * De-escalation is sticky — the reading must clear the previous
        verdict's boundary by VERDICT_HYSTERESIS_CM before relaxing.
      * NO_DATA always passes through — a dead sensor must silence the alarm,
        never latch it.
    """
    raw = verdict_for_distance_cm(distance_cm)
    if raw is Verdict.NO_DATA:
        return raw
    if raw.severity >= previous.severity:
        return raw

    boundary = _BOUNDARY_CM.get(previous)
    if boundary is None:  # previous was SAFE/NO_DATA — nothing to hold on to
        return raw
    held = distance_cm < boundary + config.VERDICT_HYSTERESIS_CM
    return previous if held else raw
