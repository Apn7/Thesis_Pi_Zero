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
# The subdev exposing the lens VCM as a `focus_absolute` control (range
# 0–4095). 2050 was measured as sharpest at the 1–5 m detection range.
FOCUS_SUBDEV = "/dev/v4l-subdev1"
FOCUS_ABSOLUTE = 2050

# Extra picamera2 ISP controls to crisp up the JPEG before it hits the phone.
CAPTURE_SHARPNESS = 2.0
CAPTURE_CONTRAST = 1.1

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

# Trigger pulse width (µs) — the HC-SR04 spec is 10 µs. pigpio generates this
# in the daemon, so the width is precise regardless of Python scheduling.
SONAR_TRIGGER_PULSE_US = 10
