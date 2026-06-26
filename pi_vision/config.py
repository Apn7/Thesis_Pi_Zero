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
