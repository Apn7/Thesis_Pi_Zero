"""Phone-IP discovery shared by the Pi-side senders.

Two network topologies, one question — "what IP do I dial?":

* **Client mode (dev):** the Pi joined the phone's hotspot, so the phone is
  the Pi's default gateway on wlan0.
* **AP mode (production):** the Pi hosts its own `smartcane-ap` and the app
  joins *us* (WifiNetworkSpecifier). There is no wlan gateway; the phone is
  a DHCP client of our shared-mode dnsmasq, so we look it up in the lease
  table, cross-checked against the stations actually associated right now.

`detect_phone()` tries both, in that order. Used by `main.py` (camera
frames) and `sonar_main.py` (distance).
"""

import glob
import logging
import subprocess

log = logging.getLogger("pi_vision.gateway")

# NetworkManager's shared-mode dnsmasq writes DHCP leases here (one file per
# interface). Lines look like: "<expiry-epoch> <mac> <ip> <hostname> <clientid>"
_LEASE_GLOB = "/var/lib/NetworkManager/dnsmasq-wlan*.leases"


def _run(cmd):
    """Run a command, returning stdout text or None (never raises)."""
    try:
        return subprocess.check_output(cmd, text=True, timeout=3)
    except (subprocess.SubprocessError, FileNotFoundError) as e:
        log.debug("`%s` failed: %s", " ".join(cmd), e)
        return None


def detect_gateway():
    """Return the default-gateway IP (the phone, on its hotspot), or None.

    Prefers a default route on wlan0: with the USB-gadget SSH lifeline plugged
    in (or any second interface), another default route can exist, and dialing
    that gateway would mean streaming frames at a laptop. Falls back to the
    first default route if none is on wlan0.
    """
    out = _run(["ip", "route", "show", "default"])
    if out is None:
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


def _associated_stations():
    """MAC addresses of clients associated to our AP right now (may be empty)."""
    out = _run(["iw", "dev", "wlan0", "station", "dump"])
    if not out:
        return set()
    return {
        line.split()[1].lower()
        for line in out.splitlines()
        if line.startswith("Station ") and len(line.split()) >= 2
    }


def detect_ap_client():
    """Return the IP of a phone associated to our own AP, or None.

    DHCP leases alone can be stale (yesterday's phone) and the neighbour table
    alone can hold FAILED junk, so we anchor on the ground truth — the station
    list of who is associated *right now* — and map MAC→IP via the freshest
    matching lease, falling back to the kernel neighbour table.
    """
    macs = _associated_stations()
    if not macs:
        return None

    # 1) Freshest DHCP lease belonging to an associated station.
    best = None  # (expiry, ip)
    for path in glob.glob(_LEASE_GLOB):
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                lines = f.read().splitlines()
        except OSError:
            continue
        for line in lines:
            parts = line.split()
            if len(parts) >= 3 and parts[1].lower() in macs:
                try:
                    expiry = int(parts[0])
                except ValueError:
                    expiry = 0
                if best is None or expiry > best[0]:
                    best = (expiry, parts[2])
    if best:
        return best[1]

    # 2) Neighbour table (covers static-IP clients / a missing lease file).
    out = _run(["ip", "-4", "neigh", "show", "dev", "wlan0"])
    if not out:
        return None
    for line in out.splitlines():
        parts = line.split()
        if "lladdr" in parts and "FAILED" not in parts:
            mac = parts[parts.index("lladdr") + 1].lower()
            if mac in macs:
                return parts[0]
    return None


def detect_phone():
    """Best current guess at the phone's IP, or None if no phone is present.

    Order matters: a wlan default gateway means we're on the phone's hotspot
    (dev mode) and the gateway IS the phone. Otherwise, if a station is
    associated to our AP, that's the phone (production mode). The non-wlan
    gateway fallback (e.g. home-router testing) stays last — on those setups
    `--host` remains the honest answer.
    """
    out = _run(["ip", "route", "show", "default"])
    fallback = None
    if out:
        for line in out.splitlines():
            parts = line.split()
            if "via" not in parts:
                continue
            gw = parts[parts.index("via") + 1]
            if "dev" in parts and parts[parts.index("dev") + 1].startswith("wlan"):
                log.info("Phone = wlan default gateway (hotspot mode): %s", gw)
                return gw
            if fallback is None:
                fallback = gw
    client = detect_ap_client()
    if client:
        log.info("Phone = associated AP client (AP mode): %s", client)
        return client
    return fallback
