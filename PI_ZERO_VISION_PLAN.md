# Pi Zero Vision — Implementation Plan & Context Handoff

> **Purpose of this doc:** hand a fresh Claude Code session (or a teammate) everything needed to
> implement and reason about the Pi Zero camera-streaming feature without re-deriving the
> research. Read the **Context** section first, then the **Plan**.

---

## 1. Context (what's going on and why)

### Project
**Smart Cane** — assistive tech for visually impaired navigation in Bangladesh. Two parts:
- `Test_app/test_app_1/` — Flutter app (Android + Windows). Bilingual Bangla/English voice UI,
  BLE, GPS, **on-device YOLOv11n object detection** (via the `ultralytics_yolo` plugin, ~15 fps
  using the **phone camera**), cloud Groq LLaMA for voice intents (on-device Gemma is disabled).
- `Thesis_pi_zero/` — the embedded backend (this folder). Currently a placeholder; **this is
  where the new Pi-side code goes.** It is its own git repo.

> Note: the repo's older root `CLAUDE.md` references a `Thesis_pie/Thesis-pie/` Python YOLO
> backend and an ESP32. Both are historical. The ESP32 (`SmartCane_ESP`, ultrasonic distance
> over BLE) is the thing the Pi Zero is **replacing**.

### The goal of this feature
Today the app's YOLO runs on **phone-camera** frames. We want the **camera frames to come from a
Raspberry Pi Zero 2 W** (with an **Arducam IMX519 16MP autofocus** camera mounted on the cane),
delivered to the phone, then fed into the **existing** detection pipeline — "same object
detection, just a different frame source." Minimal app disruption.

### Hardware (fixed)
- **Raspberry Pi Zero 2 W** — quad Cortex-A53 @1 GHz, **512 MB RAM**, **Bluetooth 4.2 / BLE**
  (LE 1M PHY only — no BLE 5.0 2M PHY), 2.4 GHz 802.11n WiFi, single shared antenna,
  VideoCore IV with **hardware H.264 encoder**. OS: Raspberry Pi OS **Bookworm**
  (NetworkManager-based).
- **Arducam IMX519** — *Pivariety* sensor, **not mainline**; needs Arducam driver +
  `dtoverlay=imx519`, then works via libcamera/`picamera2`. Pi Zero needs the **narrow mini-CSI
  ribbon** (not a standard Pi cam cable).

### The decisive research findings (don't re-litigate these)

1. **BLE cannot carry the video stream.** BLE 4.2 realistic ceiling is ~90–100 KB/s
   (~0.7–0.8 Mbit/s). 15 fps of even marginal 320×240 JPEG (~18 KB) is ~270 KB/s — **~3–10×
   over** what BLE can do. So frames must go over **WiFi**, not BLE. BLE is kept for control.

2. **Transport = WiFi over the phone's hotspot, no router.** Pi Zero 2 W joins the phone's
   hotspot. The phone is the gateway, so **the Pi can always reach the phone at its default
   gateway IP** → the Pi *initiates* the connection (dials the phone). **No mDNS / no discovery
   needed.** (Android hotspots may isolate client↔client, but client↔gateway/phone is always
   allowed.)

3. **WiFi provisioning is the real problem.** Credentials are currently **baked into the Pi
   image** via Imager — that's why "is the app connecting?" is untestable and why other phones
   can't use it. Fix = **dynamic provisioning over BLE** (a standard headless-Pi pattern:
   BerryLan / Improv / `ble-wifi-setup`). BLE is the out-of-band channel that hands SSID+password
   to the Pi. **This is the load-bearing reason we keep BLE.**

4. **Android can't read an existing hotspot's password.** An app can only know credentials for a
   hotspot **it created** via `startLocalOnlyHotspot()` (returns SSID+password in its callback;
   local-only, no internet sharing — which is fine, the Pi needs no internet). The user's
   voice/LLM path uses **cloud Groq**, so the phone must keep **cellular** internet while it's the
   AP — generally works, verify per device.

5. **Field convention is frame-by-frame, not video codecs.** Assistive-vision projects that
   offload send **discrete JPEG frames** (often sampled), not H.264 streams; continuous video is
   reserved for human-in-the-loop remote assistance. For detection you want the **freshest frame,
   drop the backlog**. So: **MJPEG-style latest-frame-wins**, not RTSP/H.264. (H.264 stays a
   fallback only if bandwidth ever disappoints — WiFi has plenty.)

6. **CRITICAL app-side constraint — the YOLO pipeline is NOT a swappable Dart frame loop.**
   The app uses the **`ultralytics_yolo` plugin** (`pubspec: ultralytics_yolo: ^0.6.2`). Its
   `YOLOView` is a **native platform view where Kotlin/CameraX owns the camera, preprocessing,
   inference, NMS, and overlay** — Flutter only receives results. `YOLOView` has **no external-
   frame input**, so we cannot "swap its source."
   **The escape hatch:** the plugin also exposes a `YOLO` class with
   **`predict(Uint8List imageBytes)`** for still-image inference (JPEG bytes in, detections out),
   independent of the camera. So the Pi path = receive JPEG → `YOLO.predict()` → render our own
   overlay. Note `predict()` is slower than `YOLOView`'s native camera pipeline — but **15 fps is
   not a requirement here** (see Priority/scope), so a lower, usable cadence is acceptable.

### Decisions already made (all locked)
- Frames over **WiFi (phone hotspot)**, BLE for **provisioning + control/status**.
- **Pi initiates** the data connection to the phone (gateway); phone runs a `ServerSocket`.
- **Latest-frame-wins JPEG** frames, length-prefixed.
- Keep the existing phone-camera `VisionDemoScreen` **untouched**; add a **parallel** Pi-fed
  screen using `YOLO.predict()`. Gate it behind a feature flag.
- **Hotspot credentials = Path A `LocalOnlyHotspot` (LOCKED).** The app creates the AP, gets the
  SSID+password from the OS callback, and sends them to the Pi over BLE. Fully automatic,
  phone-agnostic, no typing. Per-session creds are ephemeral → the Pi is re-provisioned each
  session (this is fine and more secure). Local-only = the Pi gets no internet (doesn't need it);
  the phone keeps cellular for Groq.

### Priority / scope right now
**Just make it work end-to-end.** Performance is explicitly secondary: **15 fps is NOT required** —
a cadence that's *usable for a blind user* is enough. The camera is already tested and working, so
**no bring-up benchmark is needed.** Don't gate progress on FPS; get the full
BLE→WiFi→frames→`predict()`→overlay loop running first, optimize later only if it feels unusable.

### Existing code references (app side)
- `lib/services/esp_ble_service.dart` — proven BLE **central** patterns (scan, connect,
  discover, notify, auto-reconnect). Clone for the Pi provisioning service.
- `lib/core/utils/constants.dart` — feature flags (`enableEspBle`, `enablePiBle`), BLE UUIDs,
  device names. Add `enablePiVision` + Pi UUIDs/port here.
- `lib/presentation/screens/vision_demo_screen.dart` — the existing `YOLOView` phone-camera
  screen (leave as-is; mirror its structure for the Pi screen).
- `lib/services/detection_models.dart` — `Detection`, `BBox`, `ModelVariant`, `InferenceDelegate`
  (reuse unchanged).
- `lib/presentation/widgets/detection_list_tile.dart` — reuse for the results list.
- Model asset: `assets/models/yolo11n_float16.tflite` (FP16; INT8 not bundled). Thresholds in
  use: confidence `0.25`, IoU `0.45`.

---

## 2. Architecture (locked)

```
PROVISIONING / CONTROL  (BLE: app = central, Pi = GATT peripheral)
  [App] ──write SSID + PSK + frame_port──►  [Pi]
  [Pi]  ──nmcli connect to phone hotspot──
  [Pi]  ──notify status (CONNECTING/WIFI_OK/WIFI_FAIL/STREAMING)──►  [App]

DATA PATH  (WiFi over phone hotspot, no router, Pi initiates)
  [Pi] capture(IMX519) → JPEG (latest-frame, drop-old)
       reads default gateway (= phone) → TCP connect → push [4-byte len][JPEG]…
  [App] ServerSocket accepts → keep newest frame
       → YOLO.predict(jpegBytes) → Detection → CustomPainter overlay + DetectionListTile
```

---

## 3. Implementation Plan

### Part A — Pi side (`Thesis_pi_zero/`)

> Camera is already tested/working (IMX519 via libcamera/`picamera2`). No bring-up benchmark step.

**A1. BLE GATT provisioning + control server**
- Use **`bluezero`** (BlueZ) on Bookworm. Advertise name `SmartCane`.
- Service with characteristics: `ssid` (write), `psk` (write), `frame_port` (write),
  `apply` (write trigger), `status` (read + notify: `IDLE/CONNECTING/WIFI_OK/WIFI_FAIL/STREAMING`).
- **Exit gate:** app (or nRF Connect) writes creds and reads status transitions.

**A2. WiFi apply via NetworkManager**
- On `apply`: `nmcli con add/modify` a profile named `phone-hotspot` → `nmcli con up`. **Never
  touch the management/`dev-ssh` connection** (keep SSH access alive — see note below).
- Report `WIFI_OK` / `WIFI_FAIL` (+ reason) over `status`.
- **Exit gate:** Pi joins a hotspot it never had baked in, confirmed over BLE.

**A3. Camera capture** — `picamera2`, IMX519, low-res stream at model input size, per-frame JPEG,
keep only newest frame.

**A4. Frame sender** — read default gateway (`ip route`), TCP connect to `gateway:frame_port`,
send `[4-byte big-endian length][JPEG]` per frame; reconnect with backoff on drop.

**A5. Orchestrator + boot** — `main.py` state machine (BLE → WiFi → camera → sender);
`systemd` unit for headless boot.

### Part B — App side (`Test_app/test_app_1/`)

**B1. `PiProvisioningService`** — BLE central, cloning `EspBleService` patterns. Scan/connect
`SmartCane`, write `ssid`/`psk`/`frame_port`, subscribe to `status`. Use a **bonded/encrypted**
link for the password.

**B2. Hotspot credential source (Path A — `LocalOnlyHotspot`)**
- Android `LocalOnlyHotspot` via a `MethodChannel` in `MainActivity.kt` → start the AP and return
  its generated SSID+password to Dart, then hand them to `PiProvisioningService` (B1) to write over
  BLE. Manage the `LocalOnlyHotspotReservation` lifecycle (close it on teardown).

**B3. `PiFrameServer`** — `dart:io ServerSocket` on `frame_port`; parse length-prefixed JPEGs;
expose `Stream<Uint8List>` that keeps only the newest frame (drop backlog).

**B4. `PiVisionScreen`** (new; parallels `VisionDemoScreen`) — consume frame stream →
`YOLO.predict(jpegBytes)` → map to existing `Detection` → render with a `CustomPainter` overlay +
reuse `DetectionListTile`, FP16 model, thresholds (0.25 / 0.45), metrics. **Existing phone-camera
screen untouched.**

**B5. Wiring** — add route + feature flag `enablePiVision` (mirror `enableEspBle`).

### Part C — Build sequence (get it working, simplest path first)
1. **Data path first, skip BLE:** A3+A4 → hardcoded IP, + B3+B4 over the *existing* WiFi. Prove
   "Pi frame → `predict()` → overlay" works end to end. (Goal: a usable live view, not a target
   FPS.)
2. **Onboarding:** A1+A2 + B1+B2 (Path A `LocalOnlyHotspot`) → provision a never-before-seen
   hotspot from the app.
3. **Integrate:** Pi auto-dials gateway after provisioning; full BLE→WiFi→frames→YOLO loop;
   reconnect handling.
4. **Harden later (only as needed):** WiFi drop → re-provision, BLE+WiFi antenna coexistence,
   thermals/battery, graceful fallback to phone camera.

---

## 4. Risks tracked (none are blockers for "just working")
- **`YOLO.predict()` throughput** — lower than `YOLOView`, but 15 fps is not required; only revisit
  (smaller input, INT8, etc.) if the live cadence feels unusable for a blind user.
- **`LocalOnlyHotspot` + cloud Groq** internet coexistence → verify per device.
- **512 MB RAM / thermals / single antenna (BLE+WiFi)** under sustained load — address in hardening,
  not now.

---

## 5. Test/dev notes
- **Keep an SSH lifeline independent of the phone hotspot** so provisioning tests can't lock you
  out: best is **USB-gadget Ethernet** (`dtoverlay=dwc2` + `modules-load=dwc2,g_ether`, SSH over
  the USB cable); fallback is a second saved WiFi (home router) with autoconnect. Provisioning
  must only ever create/delete the `phone-hotspot` NM profile, never the management one.
- **Proving it works without a clean flash:** delete any existing `phone-hotspot` NM profile, then
  provision a **never-before-seen** hotspot from the app (ideally a second phone). If the Pi joins
  an SSID it never had baked in, provisioning is proven and phone-agnostic.

---

## 6. Suggested frame/wire contract (proposal, not yet built)
- **Frame:** `[uint32 big-endian length][JPEG bytes]`, streamed over one TCP socket.
- **BLE GATT (Pi peripheral, name `SmartCane`):** pick a fresh 128-bit service UUID (do NOT reuse
  the ESP `a1b2c3d4-…` UUIDs); characteristics `ssid`/`psk`/`frame_port`/`apply` (write) +
  `status` (read/notify). Mirror the chosen UUIDs into `lib/core/utils/constants.dart`.

---

## 7. Implementation status

### ✅ Step 1 — data path (built 2026-06-26)
The full **Pi frame → `YOLO.predict()` → overlay** loop is implemented, no BLE yet.

**App side (`Test_app/test_app_1/`):**
- `lib/core/utils/constants.dart` — `enablePiVision` flag, `piFramePort = 8765`,
  `piMaxFrameBytes` (4 MB anti-OOM guard), `piFrameHeaderBytes = 4`.
- `lib/services/pi_frame_server.dart` — **`PiFrameServer`** (`ChangeNotifier`). Binds a
  `ServerSocket` on `anyIPv4:piFramePort`; reassembles `[uint32-BE len][JPEG]` framing across
  arbitrary TCP chunks; **newest-frame-wins** via `latestFrame`/`frameId`; replaces a stale client
  on redial; severs + waits for redial on an implausible length (desync guard); exposes
  `state`/`errorMessage`/`framesReceived`.
- `lib/presentation/screens/pi_vision_screen.dart` — **`PiVisionScreen`**. Owns a multi-instance
  `YOLO` (FP16, GPU). **Single-inflight** predict loop (`_busy` + `_lastProcessedId`) so predicts
  never pile up; decodes each JPEG once to a `ui.Image` and paints it letterboxed
  (`BoxFit.contain`) with boxes mapped into the *same* fitted rect (aspect-safe); pauses on
  app-background; reuses `DetectionListTile`; shows latency/FPS/frame-count + waiting/error states.
  Thresholds 0.25 / 0.45 (match `VisionDemoScreen`). **`VisionDemoScreen` left untouched.**
- Wired: route `AppRoutes.piVision` (`/pi-vision`) in `main.dart`; gated home tile **"Cane Cam"**;
  bilingual strings in `vision_strings.dart`. `INTERNET` permission already present (raw sockets
  bypass the cleartext-traffic flag).

**Pi side (`Thesis_pi_zero/pi_vision/`):** `config.py` (wire constants — keep in sync with the app),
`camera.py` (IMX519 via picamera2, native JPEG, newest-frame on demand), `frame_sender.py`
(TCP client, length-prefixed send, raises on drop), `main.py` (gateway auto-detect or `--host`,
capture→send loop with reconnect/backoff, FPS cap, SIGINT/SIGTERM cleanup), `README.md`,
`requirements.txt`. Python syntax-checked; **not yet run on hardware.**

**How to test:** phone → open *Cane Cam* (starts the server); Pi → `cd pi_vision && python3
main.py --host <PHONE_IP>` (same WiFi) or `python3 main.py` (on the phone hotspot).

### ⏳ Next — Step 2 (onboarding) & beyond
BLE provisioning: Pi GATT peripheral (`bluezero`) + `PiProvisioningService` (clone
`EspBleService`) + `LocalOnlyHotspot` via `MainActivity.kt`, so the Pi auto-dials the gateway and
`--host` disappears. Then integrate (Step 3) and harden (Step 4). Edge cases still open: WiFi-drop
re-provision, BLE+WiFi antenna coexistence, `YOLO.predict()` throughput on real frames.
