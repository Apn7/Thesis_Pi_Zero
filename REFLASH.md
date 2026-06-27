# Pi Zero 2 W — reflash & restore (Smart Cane vision sender)

Rebuild guide for the Raspberry Pi Zero 2 W after an SD-card wipe/corruption.
Reconstructed from `PI_ZERO_VISION_PLAN.md` and `STEP2_PROVISIONING_HANDOFF.md`
plus the live `/boot/firmware/config.txt` + `cmdline.txt`.

> **Scope:** this restores **Step 1 (the camera data path)** — the original
> hardware deployment — **plus the newer HC-SR04 sonar-over-WiFi path**
> (**Section 7**), the WiFi replacement for the ESP32 distance sensor.
> **Step 2 (BLE WiFi-provisioning) was planned but never built**, so there is
> *no* `bluezero`, `nmcli` provisioning, or `dwc2` USB-gadget setup to reinstall.
> WiFi works purely from the hotspot creds baked into the image by Raspberry Pi
> Imager.
>
> The camera and sonar are **independent** — you can restore one without the
> other. Sections 1–6 are the camera; Section 7 is the sonar.

---

## 0. Target end-state (how you know you're done)
- Raspberry Pi OS **Bookworm** (64-bit, NetworkManager-based)
- User **`apn7`**, code at **`/home/apn7/Thesis_Pi_Zero/pi_vision`**
  (the systemd unit hard-codes this path — match it or edit the unit)
- IMX519 camera visible via libcamera (`dtoverlay=imx519`, `camera_auto_detect=0`)
- `python3-picamera2` + `v4l-utils` installed (focus lock calls `v4l2-ctl`)
- Pi and phone on the same network (hotspot creds baked into the image) —
  **camera streams on port 8765, sonar on port 8766**
- *(sonar)* HC-SR04 wired per **Section 7.1**; `python3-lgpio` present (it ships
  with Bookworm) — no daemon needed

---

## 1. Flash with Raspberry Pi Imager
Choose **Raspberry Pi OS (64-bit, Bookworm)**. In **⚙ OS Customisation** set:

- **Username / password:** `apn7` / your password
  — *must be `apn7`* or you'll have to edit the systemd unit paths later.
- **Wireless LAN:** your **phone hotspot SSID + password**;
  **Wireless LAN country = `BD`** (this is the baked-in creds + the
  `cfg80211.ieee80211_regdom=BD` seen in `cmdline.txt`).
- **Locale:** as before.
- **Services → Enable SSH** (password auth).

Write, boot, let it join the hotspot, then `ssh apn7@<pi-ip>`
(find the IP via `ping <hostname>.local` or the phone's client list).

---

## 2. Boot config — `/boot/firmware/`

**`config.txt` — safe to copy-paste verbatim** from your saved copy (nothing in it
is card-specific). Either overwrite the fresh file with your saved one, or
hand-confirm these non-default lines are present:
```
camera_auto_detect=0
dtoverlay=imx519        # replaces the default dtoverlay=vc4-kms-v3d
max_framebuffers=2
disable_fw_kms_setup=1
```

**`cmdline.txt` — do NOT paste the old one.** It contains
`root=PARTUUID=c70cb5b3-02`, which is unique to the *old* SD card's partition
table. A fresh flash gets a different PARTUUID; pasting the old value makes the
Pi unbootable. The only custom token is `cfg80211.ieee80211_regdom=BD`, and that
is added automatically by setting **Wireless LAN country = BD** in Imager (Step 1).
Leave the fresh `cmdline.txt` as-is; only if `...regdom=BD` is missing, append
*just that token* to the existing line — never replace the line.

Reboot and verify the sensor:
```bash
sudo reboot
rpicam-hello --list-cameras         # should list the imx519
```

> On current Bookworm the camera CLI tools are `rpicam-*`, **not** the old
> `libcamera-*` names. If `rpicam-hello` is missing entirely:
> `sudo apt install -y rpicam-apps`. Note the CLI is only a convenience check —
> the streaming code uses **picamera2**, not these tools, so it's optional.

> We use the **mainline** `imx519` overlay (not Arducam's fork), so there is no
> autofocus algorithm — the code drives the lens VCM manually
> (`focus_absolute=2050` on `/dev/v4l-subdev1`). That's expected.

---

## 3. System packages (lightweight install)
`python3-picamera2` *recommends* the GUI preview stack (`python3-pyqt5`,
`python3-opengl`) which a headless frame-sender never uses. Skip it with
`--no-install-recommends` — important on the Pi Zero's 512 MB:

```bash
sudo apt update && apt upgrade -y
sudo apt install -y --no-install-recommends python3-picamera2 v4l-utils git
```
- `python3-picamera2` — camera capture (apt, **never** pip)
- `v4l-utils` — provides `v4l2-ctl`, used for the focus lock
- `git` — to pull the code

No pip packages needed — Step 1 uses only the Python standard library.

> *(Sonar)* the HC-SR04 path uses **`python3-lgpio`**, which already ships with
> Bookworm — see **Section 7.2**. No daemon, no pip.

---

## 4. Restore the code
```bash
cd /home/apn7
git clone <your-Thesis_pi_zero-repo-url> Thesis_Pi_Zero
```
The folder must end at `/home/apn7/Thesis_Pi_Zero/pi_vision` to match the
systemd unit. If your username/repo differ, rename the dir or edit the unit
(Step 6).

---

## 5. Manual test (before automating)
**Phone:** open the app → **Cane Cam** tile (starts the TCP server on port 8765).
**Pi:**
```bash
cd /home/apn7/Thesis_Pi_Zero/pi_vision
python3 main.py                 # auto-detects phone as default gateway (hotspot)
# or on shared WiFi:  python3 main.py --host <PHONE_IP>
```
Expect "Camera started…", "Connected to…", and a live box-annotated feed on the
phone (~8–9 fps, ~90–100 ms). First ~0.5 s may be dark/soft while AE/AF settle.

---

## 6. (Optional) Auto-start on boot — systemd
```bash
sudo cp /home/apn7/Thesis_Pi_Zero/pi_vision/pi-vision.service /etc/systemd/system/pi-vision.service
# Confirm User= and the two paths in the file match (whoami / pwd)
sudo systemctl daemon-reload
sudo systemctl enable --now pi-vision.service
systemctl status pi-vision.service
journalctl -u pi-vision.service -f
```

---

## 7. HC-SR04 sonar — distance over WiFi (replaces the ESP32)

The cane's obstacle distance now comes from an **HC-SR04 on the Pi**, streamed to
the phone over WiFi on **port 8766** (separate from the camera's 8765). This is
the WiFi replacement for the old ESP32 Bluetooth sensor; the phone classifies the
distance into the same CRITICAL / WARNING / CAUTION alerts. Independent of the
camera — different GPIOs, different port, separate systemd unit.

### 7.1 Wiring (Pi powered OFF while wiring)
| HC-SR04 | Connection | Pi Zero |
|---|---|---|
| VCC  | direct               | 5V · pin 2 |
| TRIG | direct               | GPIO23 · pin 16 |
| ECHO | **4.5 kΩ in series** | GPIO24 · pin 18 |
| GND  | direct               | GND · pin 6 |

ECHO swings to 5V but the Pi GPIO is 3.3V-max, so the single **4.5 kΩ resistor in
series** limits current into the pin's clamp diodes to ~0.4 mA (safe). **Never**
wire ECHO straight to the GPIO — it damages the Pi. (Pins are configurable in
`pi_vision/config.py`: `SONAR_TRIG_GPIO` / `SONAR_ECHO_GPIO`.)

### 7.2 GPIO library — lgpio (no daemon)
The reader uses **lgpio**, the native Bookworm GPIO library, which reads the
echo via kernel-timestamped edge callbacks. It normally ships with Bookworm; if
`import lgpio` fails, install it (and make sure your user can access the GPIO):
```bash
sudo apt install -y python3-lgpio
sudo usermod -aG gpio $USER     # then log out / back in (only if needed)
```
> **Note:** pigpio is *not* used — its daemon was dropped from Bookworm's repos
> (it doesn't work on the Pi 5). lgpio needs no daemon, so there's nothing to
> enable or keep running.

### 7.3 Manual test (before automating)
**Phone:** hotspot ON, app open on the home screen (it listens on port 8766).
**Pi:**
```bash
cd /home/apn7/Thesis_Pi_Zero/pi_vision
python3 sonar_main.py            # auto-detects phone as default gateway (hotspot)
# or on shared WiFi:  python3 sonar_main.py --host <PHONE_IP>
```
Expect `HC-SR04 ready via pigpio…` then `Connected to <phone>:8766`. Wave your
hand in front of the sensor — the phone's distance card should react and show the
verdict change. `Ctrl+C` to stop.

### 7.4 Auto-start on boot — systemd
```bash
sudo cp /home/apn7/Thesis_Pi_Zero/pi_vision/pi-sonar.service /etc/systemd/system/pi-sonar.service
# Confirm User= and the two paths in the file match (whoami / pwd)
sudo systemctl daemon-reload
sudo systemctl enable --now pi-sonar.service
systemctl status pi-sonar.service
journalctl -u pi-sonar.service -f
```
Runs alongside `pi-vision.service` (camera). No daemon dependency — lgpio is a
plain library.

### 7.5 If it fails
- `lgpio not installed` → `sudo apt install -y python3-lgpio`.
- `Could not open gpiochip0` / permission denied → add the user to the gpio
  group: `sudo usermod -aG gpio $USER`, then log out and back in.
- `Connect to <phone>:8766 failed` → phone hotspot off or app not open; it
  auto-retries, so just open the app.
- Readings stuck at max distance or `-1` → recheck **7.1** wiring, especially
  ECHO through the resistor and a shared GND between sensor and Pi.

---

## Do NOT reinstall
- **No `bluezero`, no `nmcli` provisioning, no `dtoverlay=dwc2` / `g_ether`.**
  Step 2 (BLE provisioning) was never built, so none of it was on the old card.

## Known limitation (inherited, not a regression)
WiFi creds are **baked into the image**, so this restore is locked to the one
phone whose hotspot you entered in Imager. Removing that lock is exactly what
Step 2 (`STEP2_PROVISIONING_HANDOFF.md`) was meant to do.
