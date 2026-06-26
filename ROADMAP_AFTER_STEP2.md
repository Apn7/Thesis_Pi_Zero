# Roadmap — after Step 2 (integration, hardening & product/thesis work)

> Step 1 (data path) is **done + hardware-confirmed** (8–9 fps, ~90–100 ms). Step 2 (WiFi
> provisioning so any phone connects) has its **own** doc: `STEP2_PROVISIONING_HANDOFF.md`.
> **This file is everything *after* Step 2.** Order is roughly priority, but the product-level
> items (esp. spoken alerts) are decoupled and can be slotted in anytime.

---

## Step 3 — Integration (after provisioning works)

Goal: turn today's two manual steps (open screen, then `python3 main.py`) into one smooth flow.

- Pi **auto-dials the phone gateway** immediately after provisioning reports `WIFI_OK` — no manual
  `--host`. (Camera + sender from Step 1 reused unchanged; just triggered by the provisioning state
  machine instead of by hand.)
- App `PiVisionScreen` drives the whole sequence: BLE connect → start `LocalOnlyHotspot` →
  provision → wait for `WIFI_OK`/first frame → existing data path renders. Show clear progress
  states for each stage.
- **Reconnect handling across the full chain:** Pi reboots, BLE drops, WiFi drops, or TCP drops →
  recover to the right stage rather than dead-ending. (The Step-1 `PiFrameServer` already
  newest-frame/reconnects at the TCP layer; this extends it up through BLE+WiFi.)
- Keep the manual `--host` path as a **dev fallback**.

**Done when:** open Cane Cam on a fresh phone → frames appear with zero terminal commands.

---

## Step 4 — Hardening (only as needed)

Address these when they actually bite, not preemptively:

- **WiFi drop → auto re-provision** (re-hand creds over BLE if the hotspot cycles).
- **BLE + WiFi coexistence** on the Pi Zero 2 W's **single shared antenna** under sustained frame
  load — watch for throughput/latency degradation when both radios are busy.
- **Thermals / 512 MB RAM / battery** under sustained capture+encode+stream. Watch for throttling.
- **Graceful fallback to the phone camera** (`VisionDemoScreen`) if the Pi is absent/unreachable, so
  the app is still useful without the cane hardware.
- **Frame tuning** only if cadence feels unusable: smaller capture size, JPEG quality, or revisit
  `YOLO.predict()` throughput (INT8). Per the plan, 15 fps is **not** a requirement.

---

## Product-level (decoupled — high value, not gated on Steps 2–4)

- **🔊 Spoken detection alerts (highest product value).** Both vision screens currently only *show*
  boxes — but the user is blind. Detections need **TTS announcements**. Building blocks already
  exist: `lib/core/utils/voice_announcer.dart` (`VoiceAnnouncer`), `TtsService`, and
  `Detection.position` (`PositionZone` left/center/right, already bilingual). Needs: throttling/
  debounce so it doesn't spam, priority by danger/proximity, and bilingual phrasing
  ("person, center" / "মানুষ, মাঝে"). **Independent of the Pi work — also improves the phone-camera
  path.** Good standalone win.
- **Decommission / reconcile the ESP32.** The Pi Zero replaces `SmartCane_ESP` (ultrasonic over
  BLE). Once the Pi covers obstacle sensing, decide: retire `enableEspBle` + the
  `EspBleService`/distance path, or keep both coexisting. Update `constants.dart` flags and the
  app/root `CLAUDE.md` accordingly.

---

## Thesis / measurement

- Capture the quantization-study numbers while everything's fresh: **FP16 vs INT8 × CPU vs GPU**
  latency/FPS (phone-camera `VisionDemoScreen` toggles) **plus** the **Pi-path** latency/FPS
  (`PiVisionScreen` metrics). Note INT8 isn't bundled yet (`yolo11n_int8.tflite`) — export via
  `export_yolo_models.py` if INT8 numbers are needed.
- Write up the **"Pi-side detection considered and rejected"** decision (Pi Zero 2 W: 512 MB, no NN
  accelerator → ~1–3 fps vs phone's 8–9; would only flip with an accelerated Pi). See
  `STEP2_PROVISIONING_HANDOFF.md` for the full reasoning.
