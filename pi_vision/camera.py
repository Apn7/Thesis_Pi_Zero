"""IMX519 camera capture, producing one fresh JPEG per call.

Uses picamera2 (libcamera). On the Pi Zero 2 W the IMX519 is an Arducam
*Pivariety* sensor, so it needs the Arducam driver + `dtoverlay=imx519` in
`/boot/firmware/config.txt` before libcamera will see it. Per the plan the
camera is already brought up and tested — this module assumes that.

`capture_jpeg()` grabs the latest sensor frame on demand and hardware-encodes
it to JPEG. Capturing on demand (rather than running a queue) is what gives us
"newest frame wins" for free: we never send a stale, backlogged frame.
"""

import io
import logging
import time

log = logging.getLogger("pi_vision.camera")


class CameraError(RuntimeError):
    """Raised when the camera can't be initialised or captured from."""


class Camera:
    def __init__(self, width, height, quality):
        self._size = (int(width), int(height))
        self._quality = int(quality)
        self._picam = None

    def start(self):
        try:
            # Imported lazily so the module can be imported on a dev machine
            # (e.g. for linting) without picamera2 installed.
            from picamera2 import Picamera2
        except ImportError as e:  # pragma: no cover - hardware dependency
            raise CameraError(
                "picamera2 not available. On Raspberry Pi OS Bookworm install "
                "it with: sudo apt install -y python3-picamera2"
            ) from e

        try:
            from libcamera import Transform
            self._picam = Picamera2()
            cfg = self._picam.create_video_configuration(
                main={"size": self._size},
                transform=Transform(hflip=True, vflip=True),
            )
            self._picam.configure(cfg)
            # JPEG quality for capture_file(format="jpeg").
            self._picam.options["quality"] = self._quality
            self._picam.start()
            # Let auto-exposure / auto-focus settle so the first frames aren't
            # black or blurry.
            time.sleep(0.5)
            log.info("Camera started at %dx%d q=%d", *self._size, self._quality)
        except Exception as e:  # pragma: no cover - hardware dependency
            self.stop()
            raise CameraError(f"Failed to start IMX519 camera: {e}") from e

    def capture_jpeg(self):
        """Return the latest frame as JPEG bytes."""
        if self._picam is None:
            raise CameraError("Camera not started")
        buf = io.BytesIO()
        # picamera2 encodes natively (fast, correct colour order) — no PIL/cv2.
        self._picam.capture_file(buf, format="jpeg")
        return buf.getvalue()

    def stop(self):
        if self._picam is not None:
            try:
                self._picam.stop()
            except Exception:  # pragma: no cover
                pass
            try:
                self._picam.close()
            except Exception:  # pragma: no cover
                pass
            self._picam = None
            log.info("Camera stopped")
