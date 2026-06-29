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
import subprocess
import time

import config

log = logging.getLogger("pi_vision.camera")


class CameraError(RuntimeError):
    """Raised when the camera can't be initialised or captured from."""


def _lock_focus():
    """Pin the lens VCM to a sharp position via V4L2, before picamera2 opens.

    With the mainline `imx519` overlay there's no AF algorithm, so the VCM
    sits at its power-on default (0 = blurry at our range). We set
    `focus_absolute` directly on the lens subdev. This MUST run before
    `Picamera2()` opens the device, or v4l2-ctl can fail with "device busy".

    A focus failure is non-fatal: a blurry-but-running stream beats a crashed
    service, so we log and carry on rather than aborting camera start.
    """
    try:
        subprocess.run(
            [
                "v4l2-ctl",
                "-d", config.FOCUS_SUBDEV,
                "--set-ctrl", f"focus_absolute={config.FOCUS_ABSOLUTE}",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
        log.info(
            "Lens focus locked: %s focus_absolute=%d",
            config.FOCUS_SUBDEV, config.FOCUS_ABSOLUTE,
        )
    except (subprocess.SubprocessError, FileNotFoundError) as e:
        stderr = getattr(e, "stderr", "") or ""
        log.warning(
            "Could not lock lens focus (%s)%s — continuing; frames may be soft",
            e, f": {stderr.strip()}" if stderr.strip() else "",
        )


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

        # Drive the lens VCM before opening the device (else "device busy").
        _lock_focus()

        try:
            from libcamera import Transform, controls as libcontrols
            self._picam = Picamera2()
            # Exposure controls that FREEZE MOTION BLUR: keep auto-exposure on so
            # it still adapts to lighting, but bias/clamp it toward a short
            # shutter (letting gain rise instead). See config.py's exposure
            # section for the full rationale. Optional entries are only added when
            # enabled so we never pass controls libcamera would reject.
            cap_controls = {
                "Sharpness": config.CAPTURE_SHARPNESS,
                "Contrast": config.CAPTURE_CONTRAST,
                "AeEnable": True,  # keep AGC adapting to ambient light
                # Clamp the sensor frame time; the max also caps the longest
                # shutter the AGC may choose (shutter ≤ frame duration).
                "FrameDurationLimits": tuple(config.FRAME_DURATION_LIMITS_US),
            }
            if config.AE_EXPOSURE_MODE_SHORT:
                # Bias the AGC to prefer shorter exposures (more gain, less blur).
                cap_controls["AeExposureMode"] = (
                    libcontrols.AeExposureModeEnum.Short
                )
            if config.MAX_EXPOSURE_TIME_US is not None:
                # Hard shutter cap — surest motion freeze, but disables auto
                # brightness adaptation (the AGC can no longer lengthen shutter).
                cap_controls["ExposureTime"] = config.MAX_EXPOSURE_TIME_US
            cfg = self._picam.create_video_configuration(
                main={"size": self._size},
                transform=Transform(hflip=True, vflip=True),
                controls=cap_controls,
            )
            self._picam.configure(cfg)
            # JPEG quality for capture_file(format="jpeg").
            self._picam.options["quality"] = self._quality
            self._picam.start()
            # Re-assert focus AFTER start: if picamera2 reset the VCM to its
            # power-on default when it opened the device, this pins it back to
            # our sharp position. Harmless if it was already correct.
            _lock_focus()
            # Let auto-exposure settle so the first frames aren't black/dim.
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
