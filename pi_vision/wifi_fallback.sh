#!/bin/bash
# Smart Cane WiFi fallback (comitup pattern, minimal version).
#
# At boot, give NetworkManager a window to autoconnect a KNOWN client
# profile — i.e. the dev phone-hotspot, which keeps a higher priority so the
# development workflow is unchanged. If nothing connects within the window,
# bring up our own AP (`smartcane-ap`) so any phone running the app can join
# us via WifiNetworkSpecifier (production mode).
#
# The AP profile is created with autoconnect=no, so ONLY this script ever
# raises it: NM never fights for the radio, and adding/removing dev client
# profiles never interacts with the AP path. To leave AP mode by hand:
#   sudo nmcli connection down smartcane-ap
#
# Arguments / environment:
#   $1            — seconds to wait for a known client profile (default 25).
#                   Pass 0 to skip the wait and raise the AP UNCONDITIONALLY
#                   (deterministic demo/defense mode: the cane always
#                   advertises, no matter which WiFi it knows).
#   PRIORITY_CONS — optional space-separated allowlist of NM profile NAMES
#                   that are allowed to keep the radio in client mode (e.g.
#                   "dev-hotspot"). If set and the profile that connected is
#                   NOT in the list (say the Pi latched onto the home
#                   router), it is taken DOWN and the AP is raised instead —
#                   the cane's AP wins. Unset/empty = any known profile
#                   keeps priority (legacy behavior).
#
# One-time setup (see also STEP2_PROVISIONING_HANDOFF.md):
#   sudo nmcli connection add type wifi ifname wlan0 con-name smartcane-ap \
#     autoconnect no ssid SmartCane-Cam mode ap \
#     802-11-wireless.band bg 802-11-wireless.channel 6 \
#     802-11-wireless.powersave 2 \
#     wifi-sec.key-mgmt wpa-psk wifi-sec.psk smartcane123 \
#     ipv4.method shared ipv6.method disabled
#   chmod +x wifi_fallback.sh
# (SSID/PSK must match the app's AppConstants.piApSsid / piApPsk.)

WAIT_S="${1:-25}"
PRIORITY_CONS="${PRIORITY_CONS:-}"

# Name of the client profile currently active on wlan0 ("" if none).
active_con() {
    nmcli -t -f NAME,DEVICE connection show --active 2>/dev/null \
        | grep ':wlan0$' | cut -d: -f1 | head -n1
}

for _ in $(seq "$WAIT_S"); do
    # "connected" on wlan0 can only mean a known client profile succeeded
    # (the AP profile never autoconnects).
    if nmcli -t -f DEVICE,STATE device status | grep -q '^wlan0:connected$'; then
        CON="$(active_con)"
        if [ -z "$PRIORITY_CONS" ]; then
            echo "wlan0 connected to '$CON' — AP not needed."
            exit 0
        fi
        for allowed in $PRIORITY_CONS; do
            if [ "$CON" = "$allowed" ]; then
                echo "wlan0 connected to priority profile '$CON' — AP not needed."
                exit 0
            fi
        done
        echo "wlan0 connected to non-priority '$CON' — dropping it, AP wins."
        nmcli connection down "$CON" || true
        break
    fi
    sleep 1
done

echo "Starting smartcane-ap (waited up to ${WAIT_S}s)."

# ── Make the AP as loud and discoverable as the hardware allows ──────────
# Regulatory domain: the world/unset domain caps TX power and marks channels
# no-IR; pinning it lets the radio beacon at full legal power on channel 6.
iw reg set BD 2>/dev/null || true
# NM-level WiFi powersave OFF on the AP profile (2 = disable). brcmfmac
# power management is the classic cause of missed probe responses / erratic
# beacons on Pi Zero APs — a phone scanning for the cane then simply doesn't
# hear it. Idempotent; also baked into the one-time profile above.
nmcli connection modify smartcane-ap 802-11-wireless.powersave 2 2>/dev/null || true

nmcli connection up smartcane-ap || exit 1

# Belt-and-braces: force driver-level power save off on the live interface
# (NM's property covers most cases but the driver can re-enable it).
iw dev wlan0 set power_save off 2>/dev/null || true
# Best-effort max TX power (brcmfmac often ignores manual values — the reg
# domain above is the real lever; this just catches drivers that honor it).
iw dev wlan0 set txpower auto 2>/dev/null || true

# CRITICAL for AP stability: stop NM autoconnect-hunting on wlan0 while the
# AP serves. The saved client profiles (dev hotspot etc.) have autoconnect on,
# and NM's periodic hunt for them (a) triggers scans that yank the single
# radio OFF-CHANNEL — beacons go silent for hundreds of ms and clients drop —
# and (b) can outright tear the AP down to chase a hotspot that appears
# mid-session. Device-level runtime flag: clears on reboot, so the next boot's
# fallback decision (dev hotspot priority) is completely unaffected.
nmcli device set wlan0 autoconnect no 2>/dev/null || true

echo "smartcane-ap is up (powersave off, reg domain set, autoconnect-hunt off)."
