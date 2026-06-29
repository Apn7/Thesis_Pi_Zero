"""Shared constants for the Pi-side vision sender.

Keep these in sync with the Flutter app's `lib/core/utils/constants.dart`
(`piFramePort`, `piFrameHeaderBytes`, `piMaxFrameBytes`).
"""

# TCP port the *phone* listens on. The Pi dials the phone here (the phone is
# the server; on a hotspot the Pi can always reach the phone, but not vice
# versa — see PI_ZERO_VISION_PLAN.md). Must equal AppConstants.piFramePort.
FRAME_PORT = 8765

# Wire framing: 4-byte big-endian unsigned length, then that many JPEG bytes.
# Must match AppConstants.piFrameHeaderBytes / the app's getUint32(Endian.big).
HEADER_FORMAT = ">I"  # struct format: unsigned int, big-endian
HEADER_BYTES = 4

# Don't ever build a frame the app would reject as desync/corrupt.
# Must stay <= AppConstants.piMaxFrameBytes.
MAX_FRAME_BYTES = 4 * 1024 * 1024  # 4 MB

# Capture settings. Smaller frames = less bandwidth + faster decode/inference
# on the phone. YOLO letterboxes internally, so the exact size isn't critical;
# this is a bandwidth/latency knob, not an accuracy one.
CAPTURE_WIDTH = 640
CAPTURE_HEIGHT = 480
JPEG_QUALITY = 70  # 1..100

# --- Focus / sharpness -------------------------------------------------------
# We use the mainline `imx519` dtoverlay, not Arducam's fork, so libcamera has
# no AF algorithm loaded — LENS_POSITION / AF_MODE are ignored by picamera2.
# The VCM defaults to position 0 (near focus) on power-on, which is blurry at
# our 1–5 m obstacle range. We drive the VCM directly over V4L2 instead.
#
# HYPERFOCAL FIXED FOCUS (the design choice — NOT autofocus):
# Autofocus "hunts" (re-racks the lens searching) which blurs frames and adds
# latency on a constantly-moving cane. Instead we lock the VCM once at the
# *hyperfocal distance* — the focus where everything from ~half that distance to
# infinity is acceptably sharp. For this IMX519 module (f≈4.28 mm, f/2.2, 1/2.53"
# sensor) the hyperfocal distance is ≈2 m, so focusing there yields ~1 m → ∞
# sharp, covering the whole 1–5 m+ detection range with no moving parts.
#
# `focus_absolute` is a raw VCM DAC value (range 0–4095), NOT metres, so the
# hyperfocal setting must be found empirically: run `focus_test.py` OUTDOORS
# pointing down a footpath, pick the value that maximises sharpness on FAR
# objects, and paste it below. The old 2050 was tuned on near/indoor objects,
# which is why far/outdoor frames were soft.
FOCUS_SUBDEV = "/dev/v4l-subdev1"
# Measured outdoors with focus_test.py (2026-06-29): broad sharpness plateau at
# 1675–1750, peak 1700 (~30× sharper on far objects than the old near-tuned 2050).
FOCUS_ABSOLUTE = 1700  # hyperfocal lock; re-run focus_test.py if the lens/mount changes

# Extra picamera2 ISP controls to crisp up the JPEG before it hits the phone.
CAPTURE_SHARPNESS = 2.0
CAPTURE_CONTRAST = 1.1

# --- Exposure / shutter (motion-blur control) --------------------------------
# The cane swings constantly, so the dominant image-quality problem isn't focus,
# it's MOTION BLUR: a long shutter smears moving edges and wrecks on-phone YOLO.
# picamera2's auto-exposure (AGC) drives `analogue_gain × exposure_time` to hit a
# brightness target; left alone it happily picks a long shutter in dim light. We
# bias it the other way — keep the SHUTTER SHORT, let GAIN rise to compensate.
# The tradeoff is more sensor noise in low light, which YOLO tolerates far better
# than blur. We keep AGC ON (AeEnable) so it still adapts to lighting; we just
# constrain the shutter it's allowed to choose.

# Bias the AGC toward shorter exposures (libcamera AeExposureModeEnum.Short).
# This nudges it to prefer gain over shutter without a hard cap, so it stays
# adaptive. Set False to use libcamera's default (Normal) metering.
AE_EXPOSURE_MODE_SHORT = True

# Sensor frame-duration limits (min_us, max_us). This clamps the per-frame SENSOR
# time, and the max also bounds the longest shutter the AGC can pick (the shutter
# can't exceed the frame it lives in). 16666 µs ≈ 60 fps, 33333 µs ≈ 30 fps, so
# the AGC may stretch the shutter to at most ~33 ms before it must add gain.
# NOTE: this is the SENSOR clamp, NOT the software pacing knob below — MAX_FPS
# throttles how often *we* capture/send; this bounds the exposure physics. They
# are independent: capturing at 15 fps still lets the sensor expose for ≤33 ms.
FRAME_DURATION_LIMITS_US = (16666, 33333)

# Optional HARD shutter cap (µs). A short, fixed shutter is the surest way to
# freeze motion — ~5000 µs (5 ms) freezes normal walking / cane-swing. But a hard
# ExposureTime DISABLES auto-adaptation: the AGC can no longer lengthen the
# shutter for dark scenes (it must lean entirely on gain), so set this only if
# the Short + FRAME_DURATION_LIMITS_US approach above isn't freezing motion
# enough. None = let the AGC choose the shutter within the frame-duration limit.
MAX_EXPOSURE_TIME_US = 5000  # hard 5 ms cap to freeze cane-swing motion (2026-06-29)

# Optional cap so we don't spin faster than useful. None = uncapped (the
# blocking send naturally paces capture to the link speed).
MAX_FPS = 15

# Reconnect backoff (seconds): start small, grow to a ceiling.
RECONNECT_BACKOFF_START = 0.5
RECONNECT_BACKOFF_MAX = 5.0

# Per-frame send timeout; a stalled phone shouldn't wedge the sender forever.
SEND_TIMEOUT_S = 5.0
CONNECT_TIMEOUT_S = 5.0

# ── Sonar (HC-SR04 distance over WiFi) ───────────────────────────────────────
# A separate, tiny text stream that REPLACES the ESP32 ultrasonic path. The Pi
# reads the HC-SR04 and pushes newline-delimited centimetre readings to the
# phone, which classifies them into the same CRITICAL/WARNING/CAUTION verdicts
# it used for the ESP32. Runs alongside the camera: distinct GPIOs, distinct TCP
# port, so the two never interfere.
#
# Keep in sync with the app's constants.dart:
#   SONAR_PORT == AppConstants.piDistancePort

# TCP port the *phone* listens on for distance. The Pi dials it (same role
# reversal as the camera path). Must equal AppConstants.piDistancePort.
SONAR_PORT = 8766

# BCM GPIO numbers (see the wiring diagram). TRIG drives the sensor directly;
# ECHO comes back through the single 4.5 kΩ series resistor into GPIO24.
SONAR_TRIG_GPIO = 23
SONAR_ECHO_GPIO = 24

# gpiochip the pins live on. Pi Zero 2 W (and Pi 1–4) = chip 0; the Pi 5 moved
# the 40-pin header to chip 4.
SONAR_GPIOCHIP = 0

# Max range the sensor reports (metres). gpiozero saturates at this value when
# nothing is in range; we treat that as a clear path (SAFE on the phone), not a
# fault.
SONAR_MAX_DISTANCE_M = 4.0

# How often we read + send a distance (seconds). ~5 Hz mirrors the old ESP32
# cadence and is plenty for walking-speed obstacle alerts.
SONAR_INTERVAL_S = 0.2

# Median smoothing: we keep the last N single-ping readings and report their
# median, which rejects the occasional wild outlier without adding much lag.
# 5 @ 5 Hz ≈ a 0.4 s effective lag; drop to 3 for snappier response.
SONAR_MEDIAN_WINDOW = 5

# How long to wait for the echo to return before calling it out-of-range
# (4 m round trip ≈ 23 ms; 40 ms leaves margin).
SONAR_ECHO_TIMEOUT_S = 0.04

# Trigger pulse width (µs) — the HC-SR04 spec is 10 µs. We hold TRIG high for
# this long with a tight busy-wait; a bit longer is harmless since only the ECHO
# timing (measured from kernel callback timestamps) affects the distance.
SONAR_TRIGGER_PULSE_US = 10
