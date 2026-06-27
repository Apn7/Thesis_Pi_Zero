# Pi Zero 2 W — reflash & restore (Smart Cane vision sender)

Rebuild guide for the Raspberry Pi Zero 2 W after an SD-card wipe/corruption.
Reconstructed from `PI_ZERO_VISION_PLAN.md` and `STEP2_PROVISIONING_HANDOFF.md`
plus the live `/boot/firmware/config.txt` + `cmdline.txt`.

> **Scope:** this restores **Step 1 (the data path)** — the only thing ever
> deployed to hardware. **Step 2 (BLE WiFi-provisioning) was planned but never
> built**, so there is *no* `bluezero`, `nmcli` provisioning, or `dwc2` USB-gadget
> setup to reinstall. WiFi works purely from the hotspot creds baked into the
> image by Raspberry Pi Imager.

---

## 0. Target end-state (how you know you're done)
- Raspberry Pi OS **Bookworm** (64-bit, NetworkManager-based)
- User **`apn7`**, code at **`/home/apn7/Thesis_Pi_Zero/pi_vision`**
  (the systemd unit hard-codes this path — match it or edit the unit)
- IMX519 camera visible via libcamera (`dtoverlay=imx519`, `camera_auto_detect=0`)
- `python3-picamera2` + `v4l-utils` installed (focus lock calls `v4l2-ctl`)
- Pi and phone on the same network (hotspot creds baked into the image)

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
sudo apt update
sudo apt install -y --no-install-recommends python3-picamera2 v4l-utils git
```
- `python3-picamera2` — camera capture (apt, **never** pip)
- `v4l-utils` — provides `v4l2-ctl`, used for the focus lock
- `git` — to pull the code

No pip packages needed — Step 1 uses only the Python standard library.

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

## Do NOT reinstall
- **No `bluezero`, no `nmcli` provisioning, no `dtoverlay=dwc2` / `g_ether`.**
  Step 2 (BLE provisioning) was never built, so none of it was on the old card.

## Known limitation (inherited, not a regression)
WiFi creds are **baked into the image**, so this restore is locked to the one
phone whose hotspot you entered in Imager. Removing that lock is exactly what
Step 2 (`STEP2_PROVISIONING_HANDOFF.md`) was meant to do.
