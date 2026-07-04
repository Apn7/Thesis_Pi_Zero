#!/bin/bash
# Smart Cane WiFi fallback (comitup pattern, minimal version).
#
# At boot, give NetworkManager a window to autoconnect any KNOWN client
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
# One-time setup (see also STEP2_PROVISIONING_HANDOFF.md):
#   sudo nmcli connection add type wifi ifname wlan0 con-name smartcane-ap \
#     autoconnect no ssid SmartCane-Cam mode ap \
#     802-11-wireless.band bg 802-11-wireless.channel 6 \
#     wifi-sec.key-mgmt wpa-psk wifi-sec.psk smartcane123 \
#     ipv4.method shared ipv6.method disabled
#   chmod +x wifi_fallback.sh
# (SSID/PSK must match the app's AppConstants.piApSsid / piApPsk.)

WAIT_S="${1:-25}"

for _ in $(seq "$WAIT_S"); do
    # "connected" on wlan0 can only mean a known client profile succeeded
    # (the AP profile never autoconnects) — dev hotspot found, nothing to do.
    if nmcli -t -f DEVICE,STATE device status | grep -q '^wlan0:connected$'; then
        echo "wlan0 connected to a known network — AP not needed."
        exit 0
    fi
    sleep 1
done

echo "No known WiFi after ${WAIT_S}s — starting smartcane-ap."
exec nmcli connection up smartcane-ap
