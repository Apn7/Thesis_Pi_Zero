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
  802-11-wireless.powersave 2 \
  wifi-sec.key-mgmt wpa-psk wifi-sec.psk smartcane123 \
  ipv4.method shared ipv6.method disabled
sudo raspi-config nonint do_wifi_country BD   # full TX power (world domain throttles)
chmod +x ~/Thesis_Pi_Zero/pi_vision/wifi_fallback.sh
sudo cp ~/Thesis_Pi_Zero/pi_vision/pi-wifi-fallback.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable pi-wifi-fallback.service
# re-enable the senders if still stopped from the spike:
sudo systemctl enable --now pi-vision.service pi-sonar.service
```

(`powersave 2` = disable — brcmfmac power management is the classic cause of a
Pi AP missing the phone's probe requests, i.e. the phone scanning and simply
not hearing the cane. `wifi_fallback.sh` also re-asserts both idempotently and
forces `iw ... set power_save off` after the AP is up.)

---

## Home-WiFi contention — why the cane didn't always win, and the fix (2026-07-05)

**Symptom:** phone already on home WiFi + app open → the cane join sat in
`requesting` forever; the Pi AP never "replaced" the home WiFi. First-ever join
(with its dialog) worked; the *silent* re-join path did not.

**Root cause (AOSP, verified in the Android 13 source):** the platform only
evaluates a specifier request when it is **freshly filed**, and on Android 12/13
`WifiNetworkFactory` **revokes the remembered silent approval** whenever the
phone is associated to another WiFi and the radio can't host a second station
interface — verbatim comment: *"we want to escalate and display the dialog to
the user EVEN if we have a normal bypass."* On top of that, the platform's 10 s
request scans stop while the screen is off, and OEM builds (ColorOS) can wedge a
long-lived unfulfilled request. The app used to file the request **once** and
wait — so when the OS decided a new consent was needed, nobody ever asked again.

**App fix (built + `flutter analyze`/Kotlin compile clean):**
- `PiWifiService` now runs a **stuck-join watchdog**: while state stays
  `requesting`, every `AppConstants.piWifiRefileSeconds` (45 s) it **re-files
  the request natively** (`refreshNetwork` in `MainActivity.kt` — drop +
  fresh register, no-op when connected). Each re-file restarts the platform's
  periodic scans with an immediate sweep and forces a fresh
  connect-or-consent decision — the cane keeps contesting the radio instead
  of waiting forever. The watchdog never runs before the first pairing (it
  would dismiss the consent dialog mid-guidance).
- New natives: `getCurrentWifiSsid` (who is hogging the radio) and
  `isLocalOnlyStaSupported` (dual-STA capable phones join the cane *without*
  leaving home WiFi and keep the silent bypass — diagnostic).
- `home_screen.dart` speaks a one-shot Bangla nudge when the watchdog reports
  the phone parked on another WiFi: the consent window will appear — pick
  SmartCane-Cam, press Connect.
- Scan nudger now fires its first kick at 3 s (was 25 s).

**Pi fix (louder, more stubborn AP):** `wifi_fallback.sh` now disables WiFi
power save (NM property + `iw ... power_save off`), sets the regulatory domain,
and supports two "AP wins" knobs (documented in `pi-wifi-fallback.service`):
- `wifi_fallback.sh 0` → raise the AP **unconditionally** (defense/demo mode).
- `PRIORITY_CONS="<dev-hotspot-profile>"` → only the dev hotspot may keep
  client mode; if the Pi latched onto any other known WiFi (e.g. the home
  router — which previously meant **no AP existed at all** for the app to
  find), that connection is dropped and the AP raised.

**Defense-day preflight (run once the evening before):**
1. Pin the Pi: `sudo systemctl edit pi-wifi-fallback.service` → override
   `ExecStart=` with `... wifi_fallback.sh 0` (AP always), reboot, confirm
   `journalctl -u pi-wifi-fallback.service -b` says the AP is up.
2. Phone check while it sits on home/campus WiFi: open the app → within ~45 s
   either it joins silently (dual-STA phones) or the consent window
   re-appears → tap Connect (remember the ColorOS chooser: pick **"Settings"**,
   never "Wireless Settings").
3. If anything is odd, watch the decision live:
   `adb logcat | grep -Ei "WifiNetworkFactory|PiWifiService"` and check
   dual-STA support: `adb shell dumpsys wifi | grep -i concurrency`.

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
