# Step 2 — WiFi Provisioning (make it work on *any* phone): session handoff

> **Read this first**, then `PI_ZERO_VISION_PLAN.md` (the full research/architecture doc; this is
> the focused "what's next" for the provisioning step). Step 1 is **done and working on hardware**.

---

## Where we are (status)

**✅ Step 1 — data path: BUILT and CONFIRMED ON HARDWARE (2026-06-26).**
Pi Zero 2 W + IMX519 streams JPEG frames over WiFi → phone runs `YOLO.predict()` → live overlay.
Measured on a real phone hotspot: **8–9 fps, ~90–100 ms latency, decent detection.** Accepted as a
win (the bar was "usable for a blind user", not a fixed FPS).

- App: `lib/services/pi_frame_server.dart`, `lib/presentation/screens/pi_vision_screen.dart`,
  flags/port in `lib/core/utils/constants.dart` (`enablePiVision`, `piFramePort=8765`), route
  `/pi-vision`, home tile "Cane Cam".
- Pi: `Thesis_pi_zero/pi_vision/` (`config.py`, `camera.py`, `frame_sender.py`, `main.py`).
- Details: see `PI_ZERO_VISION_PLAN.md` §7.

**⚠️ The limitation Step 2 fixes:** it only worked because the Pi had the hotspot SSID/password
**baked into its image** (via Imager). So it's locked to one phone and is untestable on others. We
need dynamic provisioning so **any phone running the app** can connect with zero pre-config.

---

## Decided this session (don't re-litigate)

**Detection stays on the PHONE, not the Pi.** The Pi Zero 2 W (quad A53 @1 GHz, **512 MB RAM, no NN
accelerator**) would run YOLOv11n at ~1–3 fps with thermal/RAM pressure — strictly worse than the
phone's 8–9 fps (GPU/NNAPI). The ~90–100 ms is dominated by phone-side inference + JPEG decode, not
the WiFi hop, so the latency lever is on the phone, not the Pi. Pi-side detection would also throw
away the thesis quantization instrumentation (FP16/INT8/CPU/GPU metrics live on the phone), and the
project already moved away from "Pi does YOLO" once.
- *The only_ reason to move detection to the Pi: detections are tiny JSON → fit over BLE → would
  **delete this whole provisioning problem**. But that only pays off with an **accelerated** Pi
  (Pi 5 + Hailo, or Coral TPU). Not worth it on Pi Zero 2 W. Note it in the thesis as
  "considered, rejected for this hardware."

---

## Step 2 goal & locked design

Make the app provision the headless Pi over **BLE** (the out-of-band channel that doesn't need
WiFi), using **Path A `LocalOnlyHotspot` (LOCKED)** for credentials.

**Why Path A makes it phone-agnostic:** Android `WifiManager.startLocalOnlyHotspot()` *creates a
fresh local AP and returns a random SSID + password to the app in its callback*. The app forwards
those to the Pi over BLE. The Pi pre-knows nothing → **any** phone works, no typing. Creds are
ephemeral per session (re-provision each session — fine, more secure). Local-only = the Pi gets no
internet (doesn't need it); the phone keeps **cellular** for cloud Groq.

### Target flow
1. Open Cane Cam → app connects to Pi over **BLE** (GATT; Pi = peripheral named `SmartCane`).
2. App calls `startLocalOnlyHotspot()` → gets SSID + password from the OS callback.
3. App writes `ssid` / `psk` / `frame_port` over BLE, then triggers `apply`.
4. Pi joins via `nmcli`, notifies `WIFI_OK` over the BLE `status` characteristic.
5. Pi reads its default gateway (= the phone) and **dials** `gateway:frame_port`.
6. Existing Step 1 data path takes over → frames + overlay.
7. Teardown on leaving the screen: close the `LocalOnlyHotspotReservation`.

---

## ⚠️ De-risk BEFORE building: 3 device-specific unknowns

These decide whether Path A is smooth. **Strongly recommend a ~30-min manual spike first**
(this is "Option A" below):

1. **Internet coexistence (biggest risk).** On many phones, starting a local hotspot **drops the
   phone off its own WiFi** and falls back to **cellular**. Cloud Groq (voice) needs internet *while
   the camera runs* → **mobile data must stay on**. Verify the phone keeps data with the local
   hotspot up.
2. **2.4 GHz band.** Pi Zero 2 W is **2.4 GHz only**. Most phones bring up LocalOnlyHotspot at
   2.4 GHz, but some default to 5 GHz, which the Pi **cannot see**. Verify the band.
3. **Location gotcha.** `startLocalOnlyHotspot()` typically needs **fine-location permission granted
   + location services ON**, or the callback fails (`onFailed`). Handle in code; it's the #1 silent
   failure.

`onFailed` reason codes to surface to the user: `NO_CHANNEL`, `GENERIC`, `INCOMPATIBLE_MODE`,
`TETHERING_DISALLOWED` (e.g. another app/tether already holds an AP — only one at a time).

### 🔒 Safety rail (do this before automating nmcli on the Pi)
Keep an **SSH lifeline independent of the hotspot** so a provisioning bug can't lock you out of the
Pi: best is **USB-gadget Ethernet** (`dtoverlay=dwc2` + `modules-load=dwc2,g_ether`, SSH over the
USB cable); fallback is a second saved home-WiFi with autoconnect. The Pi code must **only ever
create/delete the `phone-hotspot` NetworkManager profile**, never the management one.

---

## Two ways to start next session (pick one)

- **Option A (recommended): validation spike first.** Build a throwaway path where the app starts
  `LocalOnlyHotspot` and just shows the SSID/password on screen; type them into `nmcli` on the Pi by
  hand. Confirm (a) the Pi joins a **never-before-baked-in** hotspot, and (b) the phone keeps
  internet for Groq, and (c) band is 2.4 GHz. ~30 min, de-risks the locked assumption cheaply.
- **Option B: build the full BLE provisioning now** (if confident on the 3 risks above).

---

## Build tasks (when greenlit) — condensed from the plan

### Pi side (`Thesis_pi_zero/pi_vision/`)
- **A1. BLE GATT provisioning peripheral** — `bluezero` (BlueZ on Bookworm). Advertise `SmartCane`.
  Service chars: `ssid` (write), `psk` (write), `frame_port` (write), `apply` (write trigger),
  `status` (read + notify: `IDLE/CONNECTING/WIFI_OK/WIFI_FAIL/STREAMING`). Adds `bluezero` to
  `requirements.txt` (the Step-1 README already notes this).
- **A2. WiFi apply via NetworkManager** — on `apply`: `nmcli con add/modify` a profile named
  `phone-hotspot` → `nmcli con up`; report `WIFI_OK`/`WIFI_FAIL(+reason)` over `status`. Never touch
  the management/SSH connection.
- **A5. Orchestrator + boot** — extend `main.py` into a state machine (BLE → WiFi → camera →
  sender); add a `systemd` unit for headless boot. (Camera A3 + sender A4 already exist from Step 1
  — reuse unchanged once WiFi is up.)

### App side (`Test_app/test_app_1/`)
- **B1. `PiProvisioningService`** — BLE central, **clone `lib/services/esp_ble_service.dart`**
  (proven scan/connect/discover/notify/auto-reconnect). Scan/connect `SmartCane`, write
  `ssid`/`psk`/`frame_port`, subscribe to `status`. Use a **bonded/encrypted** link for the
  password.
- **B2. `LocalOnlyHotspot` via `MethodChannel` in `MainActivity.kt`** — start the AP, return
  generated SSID+password to Dart, manage the `LocalOnlyHotspotReservation` lifecycle (close on
  teardown). Request fine-location + ensure location services on. (Mirror the existing native
  channel pattern already used by `hardware_key_service.dart` / `MainActivity.kt`.)
- **B5. Wiring** — pick a **fresh 128-bit BLE service UUID** (do NOT reuse the ESP `a1b2c3d4-…`
  UUIDs) + char UUIDs; mirror them into `constants.dart` next to the existing Pi-vision constants.
  Drive the flow from `PiVisionScreen` (provision → wait for `WIFI_OK`/first frame → existing data
  path). Keep Step 1's manual `--host` path usable as a fallback during dev.

### Reference code already in the repo
- `lib/services/esp_ble_service.dart` — BLE central patterns to clone for B1.
- `lib/services/hardware_key_service.dart` + `android/.../MainActivity.kt` — existing MethodChannel
  pattern to mirror for B2.
- `lib/services/pi_frame_server.dart` / `pi_vision_screen.dart` — the Step-1 data path that takes
  over after `WIFI_OK`.
- `lib/core/utils/constants.dart` — where the Pi flags/port/UUIDs live.

---

## Definition of done for Step 2
A phone that has **never** had its hotspot baked into the Pi (ideally a *second* phone) opens Cane
Cam, and with no manual `nmcli`/`--host`, the Pi joins and frames appear — while the phone keeps
internet for voice. (Plan's "proving it works" test: delete any existing `phone-hotspot` NM profile,
then provision a never-before-seen hotspot from the app.)
