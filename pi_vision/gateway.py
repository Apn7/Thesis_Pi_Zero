"""Default-gateway detection shared by the Pi-side senders.

On the phone's hotspot the phone is the Pi's default gateway, so the senders
can find the phone without any hard-coded IP. Used by both `main.py` (camera
frames) and `sonar_main.py` (distance).
"""

import logging
import subprocess

log = logging.getLogger("pi_vision.gateway")


def detect_gateway():
    """Return the default-gateway IP (the phone, on its hotspot), or None.

    Prefers a default route on wlan0: with the USB-gadget SSH lifeline plugged
    in (or any second interface), another default route can exist, and dialing
    that gateway would mean streaming frames at a laptop. Falls back to the
    first default route if none is on wlan0.
    """
    try:
        out = subprocess.check_output(
            ["ip", "route", "show", "default"], text=True, timeout=3
        )
    except (subprocess.SubprocessError, FileNotFoundError) as e:
        log.warning("Could not run `ip route`: %s", e)
        return None
    fallback = None
    for line in out.splitlines():
        parts = line.split()
        if "via" not in parts:
            continue
        gw = parts[parts.index("via") + 1]
        if "dev" in parts and parts[parts.index("dev") + 1].startswith("wlan"):
            return gw  # the WiFi route is the phone — take it
        if fallback is None:
            fallback = gw
    return fallback
