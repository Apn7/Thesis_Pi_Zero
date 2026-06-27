"""Default-gateway detection shared by the Pi-side senders.

On the phone's hotspot the phone is the Pi's default gateway, so the senders
can find the phone without any hard-coded IP. Used by both `main.py` (camera
frames) and `sonar_main.py` (distance).
"""

import logging
import subprocess

log = logging.getLogger("pi_vision.gateway")


def detect_gateway():
    """Return the default-gateway IP (the phone, on its hotspot), or None."""
    try:
        out = subprocess.check_output(
            ["ip", "route", "show", "default"], text=True, timeout=3
        )
    except (subprocess.SubprocessError, FileNotFoundError) as e:
        log.warning("Could not run `ip route`: %s", e)
        return None
    for line in out.splitlines():
        parts = line.split()
        if "via" in parts:
            return parts[parts.index("via") + 1]
    return None
