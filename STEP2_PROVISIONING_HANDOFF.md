# Step 2 — WiFi provisioning (works on *any* phone): session handoff

> **Read this first**, then `PI_ZERO_VISION_PLAN.md` (full research/architecture doc).
> Step 1 (data path) is done and confirmed on hardware; this doc tracks Step 2.

---

## Where we are (status)

**✅ Step 1 — data path: BUILT and CONFIRMED ON HARDWARE (2026-06-26).**
Pi Zero 2 W + IMX519 streams JPEGs over WiFi → phone runs `YOLO.predict()` → live overlay.
8–9 fps, ~90–100 ms latency on a real phone hotspot. Sonar (HC-SR04, port 8766) rides the
same WiFi link — **this link carries the whole cane system, not just the camera.**

**✅ Step 2 decision — Path B (Pi hosts the AP): VALIDATED ON HARDWARE (2026-07-04).**
The old plan (Path A: app creates a `LocalOnlyHotspot`, sends creds to the Pi over BLE) was
**dropped** after research + a hardware spike:

- Path A's public API cannot force 2.4 GHz; a phone that raises its hotspot at 5 GHz simply
  cannot be seen by the Pi (2.4 GHz-only radio) and there is **no code-level fix**. It also
  needed a BLE GATT build on both sides and per-session re-provisioning.
- Path B uses Android's **Wi-Fi Network Request API (`WifiNetworkSpecifier`, Android 10+)**
  — the official mechanism for onboarding IoT cameras. The Pi hosts a fixed-credential AP
  (`SmartCane-Cam` / `smartcane123`, like the sticker on a commercial IP cam); the app joins
  it as an **app-scoped, local-only link** whose request strips `NET_CAPABILITY_INTERNET`,
  so the OS keeps **mobile data as the default route** (Groq + geocoding stay online).
  No BLE needed at all.

**Spike results on the real phone (2026-07-04):**
- Manual Settings join of the Pi AP **killed** mobile data (OEM crowns WiFi as default
  route) — confirming manual join is a dead end and the specifier API is required.
- Specifier join from the app: connected, phone showed "switched to mobile data" (that is
  the *success* state — WiFi stays associated, internet routes over cellular), **Groq
  worked while frames flowed** at Step-1 rates via `main.py --host <phone-ip>`.
- One-time system consent dialog on first join; Android remembers the approval.

---

## What's built (code, both sides)

### App (`Test_app/test_app_1/`)
- **`MainActivity.kt`** — `pi_wifi` MethodChannel: `requestNetwork` registers a
  **PERSISTENT** WifiNetworkSpecifier request (no timeout; INTERNET capability stripped;
  never binds the process) and pushes `onPiWifiAvailable`/`Unavailable`(=user declined)/
  `Lost` events to Dart; `releaseNetwork`, `isWifiEnabled`, `nudgeScan` (best-effort
  `startScan`). Manifest adds `CHANGE_NETWORK_STATE` + `ACCESS_WIFI_STATE` (normal perms).
- **`lib/services/pi_wifi_service.dart`** — states idle/requesting/connected/lost/failed/
  wifiOff; **auto-join maintainer** around the persistent request: register at start, the
  OS then joins whenever the cane's AP appears (app-before-cane "just works"); 25 s scan
  nudger while searching; re-register 2 s after loss; 60 s retry after a decline (no
  dialog spam); WiFi-toggle-off surfaced as `wifiOff`. Persists `pi_wifi_paired_once`
  (shared_preferences) after the first successful join.
- **`home_screen.dart`** — enables auto-join alongside fusion/foreground-service startup
  (zero taps). **First launch only**, speaks Bangla guidance that the one-time consent
  window is coming and what to press (the dialog is an Android security boundary — it
  cannot be auto-accepted; approval is remembered by the OS afterwards). WiFi-toggle-off
  is also spoken once. Gated by `AppConstants.enablePiAutoJoin`.
- **`pi_vision_screen.dart`** — manual WiFi button kept as debug/fallback.
- **`constants.dart`** — `piApSsid='SmartCane-Cam'`, `piApPsk='smartcane123'`,
  `enablePiAutoJoin=true`. SSID/PSK must match the Pi's `smartcane-ap` profile.

### Pi (`Thesis_pi_zero/pi_vision/`)
- **`gateway.py` → `detect_phone()`** — hotspot mode: phone = wlan default gateway (dev
  workflow unchanged); AP mode: phone = currently-associated station (`iw station dump`)
  mapped to its freshest DHCP lease (`/var/lib/NetworkManager/dnsmasq-wlan0.leases`),
  neighbour-table fallback. Used by both senders, including stale-host re-detection at
  max backoff (fixes the moved-DHCP-lease failure seen in the spike).
- **`main.py` / `sonar_main.py`** — auto mode now **waits** for a phone instead of exiting
  (AP boots with no phone associated; exiting made systemd crash-loop camera init).
- **`wifi_fallback.sh` + `pi-wifi-fallback.service`** — boot decision (comitup pattern):
  wait 25 s for any known client profile (dev hotspot keeps priority → dev SSH workflow
  unchanged), else `nmcli con up smartcane-ap`. AP profile has `autoconnect no`, so only
  this script raises it and the Pi code never touches the management/SSH profiles.

## ⏭️ One-time install still to run ON THE PI

```bash
sudo nmcli connection add type wifi ifname wlan0 con-name smartcane-ap \
  autoconnect no ssid SmartCane-Cam mode ap \
  802-11-wireless.band bg 802-11-wireless.channel 6 \
  wifi-sec.key-mgmt wpa-psk wifi-sec.psk smartcane123 \
  ipv4.method shared ipv6.method disabled
chmod +x ~/Thesis_Pi_Zero/pi_vision/wifi_fallback.sh
sudo cp ~/Thesis_Pi_Zero/pi_vision/pi-wifi-fallback.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable pi-wifi-fallback.service
# re-enable the senders if still stopped from the spike:
sudo systemctl enable --now pi-vision.service pi-sonar.service
```

Safety rails already in place: **USB-gadget Ethernet SSH** (used throughout the spike) is
hotspot-independent; in AP mode you can also SSH by joining `SmartCane-Cam` from the PC
(Pi = `10.42.0.1`).

---

## Definition of done for Step 2 (unchanged)

A phone that has **never** been baked into the Pi (ideally a *second* phone) opens the app,
approves the one-time consent dialog, and — with no manual `nmcli`/`--host` — sonar alerts
and Cane Cam frames appear while voice (Groq) keeps working. Test exactly this after the
install block above, first with your phone (hotspot OFF so the Pi falls back to AP), then
with a second phone.

Known limits to note in the thesis: Android 10+ required; one-tap consent on first pairing
(TalkBack-accessible); mobile data needed for cloud LLM while the cane link is up (same as
every considered design); Android 10 devices re-show the picker on each reconnect (11+
auto-approve). Path A (BLE + LocalOnlyHotspot) goes in the "considered, rejected" section
next to Pi-side detection: unmitigable 5 GHz ambiguity + per-session provisioning cost.
