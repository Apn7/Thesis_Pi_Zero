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

# Optional cap so we don't spin faster than useful. None = uncapped (the
# blocking send naturally paces capture to the link speed).
MAX_FPS = 15

# Reconnect backoff (seconds): start small, grow to a ceiling.
RECONNECT_BACKOFF_START = 0.5
RECONNECT_BACKOFF_MAX = 5.0

# Per-frame send timeout; a stalled phone shouldn't wedge the sender forever.
SEND_TIMEOUT_S = 5.0
CONNECT_TIMEOUT_S = 5.0
