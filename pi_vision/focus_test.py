#!/usr/bin/env python3
"""Empirically find the hyperfocal `focus_absolute` for the IMX519 cane camera.

WHY: on the mainline `imx519` overlay there is no autofocus algorithm, and
`focus_absolute` is a raw VCM DAC value (0–4095), not metres — so there's no
formula that maps "2 m hyperfocal" to a DAC number. This tool sweeps the VCM
across its range, captures a frame at each step, scores its sharpness, and saves
a labelled JPEG so you can pick the value that makes FAR objects crisp. That
value is your hyperfocal lock — paste it into `config.FOCUS_ABSOLUTE`.

HOW TO USE (run on the Pi, OUTDOORS):
    # Point the camera down a real footpath: something ~2 m away AND stuff far
    # off (10 m+ / end of street) both in frame. Hold it steady.
    python3 focus_test.py

    # The sweep measures sharpness on the IMAGE CENTRE by default. To optimise
    # for distant objects, frame the far scene in the centre, or use --region.

    # Coarse sweep first (default), then narrow around the best value:
    python3 focus_test.py --min 1500 --max 2600 --step 50

Output: ./focus_sweep/focus_<value>_sharp_<score>.jpg for every step, plus a
ranked table printed to the console (highest sharpness = sharpest). Copy the
images off the Pi to eyeball them — the numeric score is a guide, your eyes on
the far objects are the final call.

No OpenCV dependency: sharpness is a numpy-only gradient-energy metric (variance
of the gradient magnitude — higher = more fine detail = sharper).
"""

import argparse
import logging
import os
import subprocess
import sys
import time

import config

log = logging.getLogger("pi_vision.focus_test")


def _set_focus(value):
    """Drive the lens VCM to `value` via V4L2. Works while picamera2 streams."""
    subprocess.run(
        [
            "v4l2-ctl",
            "-d", config.FOCUS_SUBDEV,
            "--set-ctrl", f"focus_absolute={int(value)}",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=5,
    )


def _sharpness(rgb, region=None):
    """Gradient-energy sharpness of an RGB numpy frame (higher = sharper).

    Converts to luma, optionally crops to `region` (x0,y0,x1,y1 as 0..1
    fractions), then returns the variance of the per-pixel gradient magnitude.
    Blur smooths out fine gradients, so a sharp image scores much higher.
    """
    import numpy as np

    # Rec.601 luma — cheap and good enough for a focus metric.
    gray = (0.299 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.114 * rgb[..., 2])
    if region is not None:
        h, w = gray.shape
        x0, y0, x1, y1 = region
        gray = gray[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)]
    gray = gray.astype(np.float32)
    gx = np.diff(gray, axis=1)
    gy = np.diff(gray, axis=0)
    # Match shapes so we can sum the two gradient directions.
    n = min(gx.shape[0], gy.shape[0]), min(gx.shape[1], gy.shape[1])
    mag = gx[:n[0], :n[1]] ** 2 + gy[:n[0], :n[1]] ** 2
    return float(mag.var())


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    p = argparse.ArgumentParser(description="IMX519 hyperfocal focus sweep")
    p.add_argument("--min", type=int, default=0, help="lowest focus_absolute")
    p.add_argument("--max", type=int, default=4095, help="highest focus_absolute")
    p.add_argument("--step", type=int, default=256, help="sweep step size")
    p.add_argument("--settle", type=float, default=0.5,
                   help="seconds to let the lens settle after each move")
    p.add_argument("--outdir", default="focus_sweep", help="where to save JPEGs")
    p.add_argument("--region", default="0.3,0.3,0.7,0.7",
                   help="sharpness measurement crop as x0,y0,x1,y1 fractions "
                        "(default: centre 40%%). Use 0,0,1,1 for whole frame.")
    args = p.parse_args(argv)

    try:
        region = tuple(float(v) for v in args.region.split(","))
        assert len(region) == 4
    except (ValueError, AssertionError):
        log.error("--region must be four comma-separated fractions, e.g. 0.3,0.3,0.7,0.7")
        return 2

    try:
        from picamera2 import Picamera2
        from libcamera import Transform
    except ImportError:
        log.error("picamera2 not available — run this ON THE PI "
                  "(sudo apt install -y python3-picamera2).")
        return 2

    os.makedirs(args.outdir, exist_ok=True)

    picam = Picamera2()
    cfg = picam.create_video_configuration(
        main={"size": (config.CAPTURE_WIDTH, config.CAPTURE_HEIGHT),
              "format": "RGB888"},
        transform=Transform(hflip=True, vflip=True),
    )
    picam.configure(cfg)
    picam.start()
    time.sleep(1.0)  # let auto-exposure settle before we start scoring

    results = []
    try:
        for value in range(args.min, args.max + 1, args.step):
            try:
                _set_focus(value)
            except subprocess.SubprocessError as e:
                log.warning("skip %d: could not set focus (%s)", value, e)
                continue
            time.sleep(args.settle)  # wait for the VCM to physically move
            rgb = picam.capture_array("main")
            score = _sharpness(rgb, region)
            # Save the JPEG so you can eyeball the far objects yourself.
            path = os.path.join(args.outdir, f"focus_{value:04d}_sharp_{score:.0f}.jpg")
            picam.capture_file(path, format="jpeg")
            results.append((score, value, path))
            log.info("focus_absolute=%4d  sharpness=%12.1f  -> %s", value, score, path)
    finally:
        picam.stop()
        picam.close()

    if not results:
        log.error("No frames captured.")
        return 1

    results.sort(reverse=True)  # highest sharpness first
    log.info("\n=== Ranked sharpest-first (region=%s) ===", args.region)
    for score, value, _ in results[:10]:
        log.info("focus_absolute=%4d   sharpness=%12.1f", value, score)
    best = results[0]
    log.info("\nSharpest: focus_absolute=%d (score %.1f)", best[1], best[0])
    log.info("Eyeball the FAR objects in %s before committing.", best[2])
    log.info("Then set FOCUS_ABSOLUTE = %d in config.py", best[1])
    return 0


if __name__ == "__main__":
    sys.exit(main())
