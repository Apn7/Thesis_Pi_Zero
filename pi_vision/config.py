"""Shared constants for the Pi-side vision sender.

Keep these in sync with the Flutter app's `lib/core/utils/constants.dart`
(`piFramePort`, `piFrameHeaderBytes`, `piMaxFrameBytes`).
"""

# TCP port the *phone* listens on. The Pi dials the phone here (the phone is
# the server; on a hotspot the Pi can always reach the phone, but not vice
# versa — see PI_ZERO_VISION_PLAN.md). Must equal AppConstants.piFramePort.
FRAME_PORT = 8765

# Wire framing: 4-byte big-endian unsigned length, then that many JPEG bytes.
# Must match AppConstants.piFrameHeaderBytes / the app's getUint32(Endian.big).
HEADER_FORMAT = ">I"  # struct format: unsigned int, big-endian
HEADER_BYTES = 4

# Don't ever build a frame the app would reject as desync/corrupt.
# Must stay <= AppConstants.piMaxFrameBytes.
MAX_FRAME_BYTES = 4 * 1024 * 1024  # 4 MB

# Capture settings. Smaller frames = less bandwidth + faster decode/inference
# on the phone. YOLO letterboxes internally, so the exact size isn't critical;
# this is a bandwidth/latency knob, not an accuracy one.
CAPTURE_WIDTH = 640
CAPTURE_HEIGHT = 480
# 60 (was 70): ~25% fewer bytes per frame for a JPEG-artifact level YOLO
# doesn't care about. On the Pi-AP link airtime is the scarcest resource —
# every byte not sent is RF margin the weak brcmfmac radio gets back, and
# less margin pressure = fewer send stalls = fewer visible "drops".
JPEG_QUALITY = 60  # 1..100

# --- Sensor mode / field of view ---------------------------------------------
# CAPTURE_WIDTH/HEIGHT above is the ISP *output* size (what we JPEG + stream).
# It is NOT a sensor mode — the IMX519's smallest mode is 1280x720. When you ask
# libcamera for a small output it picks a sensor mode WITHOUT knowing each mode's
# crop, and lands on the 1280x720 mode whose crop is only (1048,1042)/2560x1440
# — i.e. it reads just a ~2560x1440 CENTRE slice of the 4656x3496 array (~55% of
# the width, ~41% of the height ≈ a 2x zoom-in). For a cane that throws away the
# peripheral field of view where obstacles first appear.
#
# Forcing the full-array binned mode 2328x1748 (crop (0,0)/4656x3496 = the WHOLE
# sensor, 2x2 binned, 30 fps) restores the full FoV and improves low light (2x2
# binning sums 4 photosites → less noise), while the ISP still scales the output
# down to CAPTURE_WIDTH/HEIGHT — so bandwidth and YOLO's 640 input are unchanged.
# It's also native 4:3, matching 640x480, so there's no extra aspect crop (the
# old 1280x720 mode is 16:9). We pass this as the raw-stream size; camera.py
# verifies the mode actually exists on the sensor and falls back to libcamera's
# auto-selection if not.
#
# Tradeoff: a wider FoV packs more scene into 640x480, so distant objects get
# fewer pixels — validate far-object detection on hardware. Set to None to
# restore the old auto-selected (cropped) behaviour.
SENSOR_OUTPUT_SIZE = (2328, 1748)  # full-FoV 2x2-binned IMX519 mode; None = auto

# Number of camera buffers libcamera allocates. picamera2 defaults video to 6,
# but the full-FoV raw stream above is ~5 MB/buffer and 6 of them overflow the
# Pi Zero's small CMA pool → "Cannot allocate memory" at start. We capture
# newest-frame-wins on demand, so 3 is plenty (≈3×(5 MB raw + 1.2 MB main) ≈
# 19 MB). Raise for smoother pacing only if CMA allows; lower if it still OOMs.
# If even 3 OOMs, increase CMA in /boot/firmware/config.txt instead (see
# REFLASH.md) — that's the kernel-side contiguous-memory budget, not RAM.
CAMERA_BUFFER_COUNT = 3

# --- Mount orientation -------------------------------------------------------
# Sensor-to-world flips, applied in-pipeline by libcamera (free — no CPU cost).
# These track HOW THE MODULE IS PHYSICALLY MOUNTED on the cane, so re-mounting
# the camera is a config edit, not a code change:
#   * original mount (through 2026-07): module upside down → hflip+vflip
#     (180°) undid it.
#   * current mount (2026-07-15): module flipped the OTHER way relative to the
#     original, i.e. right-side up → no correction needed.
# If the phone shows the world inverted after a re-mount, toggle BOTH together
# (they form a 180° rotation; toggling one alone mirrors the image, which
# would flip left/right in the app's zone logic).
CAMERA_HFLIP = False
CAMERA_VFLIP = False

# --- Focus / sharpness -------------------------------------------------------
# We use the mainline `imx519` dtoverlay, not Arducam's fork, so libcamera has
# no AF algorithm loaded — LENS_POSITION / AF_MODE are ignored by picamera2.
# The VCM defaults to position 0 (near focus) on power-on, which is blurry at
# our 1–5 m obstacle range. We drive the VCM directly over V4L2 instead.
#
# HYPERFOCAL FIXED FOCUS (the design choice — NOT autofocus):
# Autofocus "hunts" (re-racks the lens searching) which blurs frames and adds
# latency on a constantly-moving cane. Instead we lock the VCM once at the
# *hyperfocal distance* — the focus where everything from ~half that distance to
# infinity is acceptably sharp. For this IMX519 module (f≈4.28 mm, f/2.2, 1/2.53"
# sensor) the hyperfocal distance is ≈2 m, so focusing there yields ~1 m → ∞
# sharp, covering the whole 1–5 m+ detection range with no moving parts.
#
# `focus_absolute` is a raw VCM DAC value (range 0–4095), NOT metres, so the
# hyperfocal setting must be found empirically: run `focus_test.py` OUTDOORS
# pointing down a footpath, pick the value that maximises sharpness on FAR
# objects, and paste it below. The old 2050 was tuned on near/indoor objects,
# which is why far/outdoor frames were soft.
FOCUS_SUBDEV = "/dev/v4l-subdev1"
# Measured outdoors with focus_test.py (2026-06-29): broad sharpness plateau at
# 1675–1750, peak 1700 (~30× sharper on far objects than the old near-tuned 2050).
FOCUS_ABSOLUTE = 1700  # hyperfocal lock; re-run focus_test.py if the lens/mount changes

# Extra picamera2 ISP controls to crisp up the JPEG before it hits the phone.
CAPTURE_SHARPNESS = 2.0
CAPTURE_CONTRAST = 1.1

# --- Exposure / shutter (motion-blur control) --------------------------------
# The cane swings constantly, so the dominant image-quality problem isn't focus,
# it's MOTION BLUR: a long shutter smears moving edges and wrecks on-phone YOLO.
# picamera2's auto-exposure (AGC) drives `analogue_gain × exposure_time` to hit a
# brightness target; left alone it happily picks a long shutter in dim light. We
# bias it the other way — keep the SHUTTER SHORT, let GAIN rise to compensate.
# The tradeoff is more sensor noise in low light, which YOLO tolerates far better
# than blur. We keep AGC ON (AeEnable) so it still adapts to lighting; we just
# constrain the shutter it's allowed to choose.

# Bias the AGC toward shorter exposures (libcamera AeExposureModeEnum.Short).
# This nudges it to prefer gain over shutter without a hard cap, so it stays
# adaptive. Set False to use libcamera's default (Normal) metering.
AE_EXPOSURE_MODE_SHORT = True

# Sensor frame-duration limits (min_us, max_us). This clamps the per-frame SENSOR
# time, and the max also bounds the longest shutter the AGC can pick (the shutter
# can't exceed the frame it lives in) — WHILE keeping auto-exposure alive, so the
# AGC raises GAIN to keep brightness instead of going dark (unlike a hard
# ExposureTime cap). max=8000 µs caps the shutter at ~8 ms to freeze cane-swing
# motion; in dim light the AGC then pushes gain up rather than lengthening the
# shutter. Tighten max toward 5000–6000 for less blur (darker/noisier), or raise
# toward 10000–12000 for more light (more blur). This is the PRIMARY motion-blur
# knob now that the hard cap below is off.
# NOTE: this is the SENSOR clamp, NOT the software pacing knob below — MAX_FPS
# throttles how often *we* capture/send; this bounds the exposure physics. They
# are independent: capturing at 15 fps still lets the sensor expose for ≤8 ms.
FRAME_DURATION_LIMITS_US = (5000, 8000)

# Optional HARD shutter cap (µs). A short, fixed shutter is the surest way to
# freeze motion — ~5000 µs (5 ms) freezes normal walking / cane-swing. But a hard
# ExposureTime DISABLES auto-adaptation: the AGC can no longer lengthen the
# shutter for dark scenes (it must lean entirely on gain), so set this only if
# the Short + FRAME_DURATION_LIMITS_US approach above isn't freezing motion
# enough. None = let the AGC choose the shutter within the frame-duration limit.
MAX_EXPOSURE_TIME_US = None  # hard cap made frames DARK (it disables AE → gain stops
                             # compensating). Cap the shutter via FRAME_DURATION_LIMITS_US
                             # above instead, which keeps AE/gain alive. (2026-06-29)

# Optional cap so we don't spin faster than useful. None = uncapped (the
# blocking send naturally paces capture to the link speed).
# 10 (was 15): the phone's YOLO.predict consumes ~8-9 fps, so frames above
# ~10 fps are *discarded* by newest-frame-wins after burning airtime the
# Pi-AP radio badly needs. Capping at 10 loses zero processed frames and
# cuts RF load by a third — the cheapest stability win available.
MAX_FPS = 10

# Reconnect backoff (seconds): start small, grow to a ceiling.
RECONNECT_BACKOFF_START = 0.5
RECONNECT_BACKOFF_MAX = 5.0

# Per-frame send timeout; a stalled phone shouldn't wedge the sender forever.
# 10 s (was 5): a phone STA's radio legitimately stalls for 1-6 s (power-save
# wake cadence, OEM background scans going off-channel, RF retry bursts on a
# thin link). At 5 s those stalls crossed the threshold and got AMPLIFIED
# into full sever+redial cycles — the app-visible "sudden drops". At 10 s the
# link rides out a stall as a brief freeze and self-heals; TCP retransmission
# keeps the stalled frame flowing the instant the radio wakes. A genuinely
# vanished peer still surfaces in ~10 s + redial, and the app's persistent
# WifiNetworkSpecifier request re-joins on its own regardless.
SEND_TIMEOUT_S = 10.0
CONNECT_TIMEOUT_S = 5.0

# TCP keepalive (seconds / count). Without it, a silently-vanished phone (WiFi
# drop with no RST) is only detected when the send buffer fills — the sonar's
# tiny lines (~40 B/s) would take ~25 MINUTES to fill it, during which the Pi
# happily "sends" into the void and never redials the recovered phone. With
# these values a dead peer is detected in ~ IDLE + INTVL×CNT ≈ 14 s.
KEEPALIVE_IDLE_S = 5
KEEPALIVE_INTERVAL_S = 3
KEEPALIVE_COUNT = 3

# How often the camera sender logs SoC temperature + throttle/under-voltage
# flags (`vcgencmd`). Under-voltage is the classic power-bank failure mode and
# throttling silently halves the frame rate — both must be visible in
# `journalctl` (and both feed the thesis power/thermal section). 0 disables.
HEALTH_LOG_INTERVAL_S = 30

# ── Sonar (HC-SR04 distance over WiFi) ───────────────────────────────────────
# A separate, tiny text stream that REPLACES the ESP32 ultrasonic path. The Pi
# reads the HC-SR04 and pushes newline-delimited centimetre readings to the
# phone, which classifies them into the same CRITICAL/WARNING/CAUTION verdicts
# it used for the ESP32. Runs alongside the camera: distinct GPIOs, distinct TCP
# port, so the two never interfere.
#
# Keep in sync with the app's constants.dart:
#   SONAR_PORT == AppConstants.piDistancePort

# TCP port the *phone* listens on for distance. The Pi dials it (same role
# reversal as the camera path). Must equal AppConstants.piDistancePort.
SONAR_PORT = 8766

# BCM GPIO numbers (see the wiring diagram). TRIG drives the sensor directly;
# ECHO comes back through the single 4.5 kΩ series resistor into GPIO24.
SONAR_TRIG_GPIO = 23
SONAR_ECHO_GPIO = 24

# gpiochip the pins live on. Pi Zero 2 W (and Pi 1–4) = chip 0; the Pi 5 moved
# the 40-pin header to chip 4.
SONAR_GPIOCHIP = 0

# Max range the sensor reports (metres). gpiozero saturates at this value when
# nothing is in range; we treat that as a clear path (SAFE on the phone), not a
# fault.
SONAR_MAX_DISTANCE_M = 4.0

# How often we read + send a distance (seconds). ~5 Hz mirrors the old ESP32
# cadence and is plenty for walking-speed obstacle alerts.
SONAR_INTERVAL_S = 0.2

# Median smoothing: we keep the last N single-ping readings and report their
# median, which rejects the occasional wild outlier without adding much lag.
# 5 @ 5 Hz ≈ a 0.4 s effective lag; drop to 3 for snappier response.
SONAR_MEDIAN_WINDOW = 5

# How long to wait for the echo to return before calling it out-of-range
# (4 m round trip ≈ 23 ms; 40 ms leaves margin).
SONAR_ECHO_TIMEOUT_S = 0.04

# Trigger pulse width (µs) — the HC-SR04 spec is 10 µs. We hold TRIG high for
# this long with a tight busy-wait; a bit longer is harmless since only the ECHO
# timing (measured from kernel callback timestamps) affects the distance.
SONAR_TRIGGER_PULSE_US = 10

# How many CONSECUTIVE failed pings (no echo pulse at all — dead sensor, or a
# clone holding ECHO high after a missed echo) before we report the NO_READING
# fault sentinel instead of holding the last median. One or two misses are
# routine on a swinging cane and must not cancel an active alarm on the phone;
# 3 @ 5 Hz ≈ 0.6 s of true silence before we admit the sensor is gone.
SONAR_FAULT_AFTER_MISSES = 3

# ── Cane-local verdict thresholds (cm) ───────────────────────────────────────
# MUST mirror the app: `constants.dart` espCriticalCm/espWarningCm/espCautionCm
# and verdictHysteresisCm, applied by `distance_alert_source.dart`. The Pi
# classifies the SAME median value it sends to the phone, so identical
# thresholds + identical hysteresis means the cane's buzzer/vibration and the
# phone's alerts can never disagree while both are alive. Change one side,
# change the other — this duplication is deliberate (the cane must classify
# with the phone absent), but drift between them is a bug.
OBSTACLE_CRITICAL_CM = 50.0   # == AppConstants.espCriticalCm
OBSTACLE_WARNING_CM = 100.0   # == AppConstants.espWarningCm
OBSTACLE_CAUTION_CM = 200.0   # == AppConstants.espCautionCm

# De-escalation hysteresis: escalation is instant; relaxing to a lower verdict
# requires clearing the previous boundary by this margin (leave CRITICAL at
# ≥ 60 cm, not 50). Kills alarm chatter when the cane swings at a boundary.
VERDICT_HYSTERESIS_CM = 10.0  # == AppConstants.verdictHysteresisCm

# Pattern-engine tick (s). 10 ms resolution against a shortest pattern segment
# of 80 ms — fine-grained enough that rhythms feel crisp, coarse enough that
# the Python loop is negligible load on the Zero 2 W.
FEEDBACK_TICK_S = 0.01

# ── Cane-local feedback (active buzzer + vibration motor) ────────────────────
# Wiring, bring-up and the full rationale live in BUZZER_VIBRATION_WIRING.md.
# The pin choices are load-bearing, not arbitrary: at power-on the SoC pulls
# GPIO0-8 UP and GPIO9-27 DOWN, so the ACTIVE-LOW buzzer must sit in the
# pull-up group (silent through boot) and the ACTIVE-HIGH motor in the
# pull-down group (off through boot). Swapping them makes the buzzer scream
# for the entire ~30 s boot.
#
# MH-FMD buzzer, LOW-level trigger (S8550 PNP high-side switch). Its VCC must
# be on 3V3 — at 5 V a 3.3 V GPIO high can no longer fully turn the PNP off
# and the buzzer whines forever (see the wiring doc, Rule 1).
#
# CONFIRMED PASSIVE (2026-07-05 field test): despite shipping under the same
# "MH-FMD, low-level-trigger" labeling as the active variant, this unit's
# piezo element has no internal oscillator — driving I/O to a static LOW just
# clicks once (the transient charge pulse) instead of sounding continuously.
# It must be driven with a continuous PWM square wave (BUZZER_TONE_HZ) through
# the PNP, not a static level. A static LOW still means "buzzer path
# energised"; PWM is what makes that energised path actually produce sound.
BUZZER_GPIO = 5   # physical pin 29; boot pull-UP keeps it silent
BUZZER_TONE_HZ = 2700   # audible passive-piezo drive frequency; not a spec
                        # value. LOUDNESS LEVER: an unlabelled piezo is
                        # noticeably louder at its mechanical resonance —
                        # run `python3 buzzer_sweep.py` on the cane, note the
                        # loudest frequency, and set it here. (The 50 % PWM
                        # duty in feedback.py is already the max-loudness duty
                        # for a square wave — don't bother tuning that.)

# KS0450-class vibration motor module, HIGH-level trigger (SI2302 N-MOSFET
# low-side switch, logic-level — fine from a 3.3 V GPIO). drive HIGH = vibrate;
# PWM on this pin scales intensity. VCC on 3V3 (5 V upgrade path in the doc).
MOTOR_GPIO = 13   # physical pin 33; boot pull-DOWN keeps it off

# Motor sustained-drive duty (%). INTENSITY LEVER: at 3V3 VCC keep 100 — the
# 3 V ERM has no headroom and PWM below 100 only weakens it. The real strength
# upgrade is hardware (BUZZER_VIBRATION_WIRING.md §9): move motor VCC from
# pin 17 (3V3) → pin 4 (5V) — much harder vibration — then cap sustained
# drive here at ~60 so the time-average is ≈3 V and the coin motor survives.
# 100 = plain on/off drive (no PWM involved). Values < 100 drive the pin with
# PWM after a full-power kick-start (an ERM at partial duty may never spin up
# from rest — feedback.py always opens each pulse at 100 % for
# MOTOR_KICKSTART_MS first).
MOTOR_PWM_DUTY_PCT = 100
MOTOR_PWM_HZ = 250        # ERM drive PWM rate; uncritical, well above flicker
MOTOR_KICKSTART_MS = 60   # full-drive spin-up before dropping to the duty cap
