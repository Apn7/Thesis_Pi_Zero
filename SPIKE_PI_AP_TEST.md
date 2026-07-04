# Spike: does mobile data survive an app-scoped join to the Pi's AP?

**What this proves/disproves.** Manually joining the Pi's AP from Settings killed mobile
data — expected, because a manual join makes the internet-less WiFi the phone's *default
route*. The app now joins through `WifiNetworkSpecifier` + `requestNetwork` instead: an
**app-scoped, local-only link** whose request strips `NET_CAPABILITY_INTERNET`, so the OS
never makes it the default route and internet stays on mobile data. This spike verifies
that on YOUR phone. If it passes, Path B (Pi-hosted AP) is confirmed and we build the
fallback-AP boot logic. If it fails, we pivot to Plan C (phone's own hotspot + BLE creds).

## 0. One-time prep on the phone (IMPORTANT)

1. Settings → WiFi → saved networks → **FORGET `SmartCane-Cam`** (the manual-join profile
   from the last test would otherwise auto-join as a normal network and kill data again).
2. Mobile data **ON**. WiFi toggle **ON** but connected to nothing.
3. Rebuild + install the app (`flutter run` / `flutter build apk`) — it now has the
   `pi_wifi` MethodChannel and a WiFi button on the Cane Cam screen.

## 1. Pi side (over your USB-gadget SSH — hotspot-independent, you can't get locked out)

```bash
# Host the AP (2.4 GHz — the only band the Zero 2 W has):
sudo nmcli device wifi hotspot ifname wlan0 ssid SmartCane-Cam password smartcane123

# Confirm it's up:
nmcli connection show --active     # should list "Hotspot" on wlan0
```

Credentials must match the app's `AppConstants.piApSsid` / `piApPsk`
(`SmartCane-Cam` / `smartcane123`).

## 2. Phone side

1. Open **Cane Cam** → tap the **WiFi icon** in the top bar.
2. Android shows a system device-picker ("searching for devices…") → `SmartCane-Cam`
   appears → tap it → **Connect**. (One-time consent; Android remembers it.)
3. Snackbar says connected → now the real test: **use a voice command that needs Groq**,
   and/or open Chrome and load a page. Also check the status bar — the mobile-data
   arrows should still be active.

## 3. Read the result

- ✅ **Internet works while joined** → Path B validated on your phone. Next: fallback-AP
  boot profile on the Pi + phone-IP discovery in `frame_sender`, then the second-phone test.
- ❌ **Internet dead again** → your OEM breaks even app-scoped links; we pivot to Plan C
  (your normal hotspot + BLE credential transfer, typed once per phone).

## 4. Optional bonus: prove frames flow over this link too

The frame sender normally dials the phone at the Pi's *gateway* — but in AP mode the Pi
**is** the gateway, so give it the phone's real IP by hand (Step 1's `--host` fallback):

```bash
ip neigh show dev wlan0          # phone will be 10.42.0.x
cd ~/pi_vision && python3 main.py --host 10.42.0.<x>
```

Frames + detections should appear in Cane Cam exactly like the old hotspot setup.

## 5. Teardown (restore your dev setup)

```bash
sudo nmcli connection down Hotspot
sudo nmcli connection delete Hotspot
```

Your saved phone-hotspot profile is untouched; USB SSH is unaffected throughout.
