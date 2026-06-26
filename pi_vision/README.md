# Pi Zero Vision — frame sender (Step 1: data path)

Captures IMX519 camera frames on the Raspberry Pi Zero 2 W and streams them as
length-prefixed JPEG over TCP to the Flutter app, which runs them through YOLO
(`YOLO.predict`). This is **Step 1** of `../PI_ZERO_VISION_PLAN.md` — the raw
data path, **no BLE / WiFi-provisioning yet** (that's Step 2). For now the Pi
and phone must already be on the same network and you point the Pi at the
phone's IP (or let it auto-detect the phone as the default gateway on a
hotspot).

## Files
- `config.py` — wire constants (port, framing, capture size). **Keep in sync
  with the app's `lib/core/utils/constants.dart`.**
- `camera.py` — IMX519 capture via picamera2 → JPEG bytes (newest frame).
- `frame_sender.py` — TCP client; sends `[4-byte big-endian length][JPEG]`.
- `main.py` — orchestrator: capture→send loop with reconnect/backoff.

## One-time setup (Raspberry Pi OS Bookworm)
1. IMX519 (Arducam Pivariety) driver + overlay — add to `/boot/firmware/config.txt`:
   ```
   dtoverlay=imx519
   ```
   then reboot. Verify the camera: `libcamera-hello --list-cameras`.
2. picamera2 (system package, not pip):
   ```
   sudo apt update && sudo apt install -y python3-picamera2
   ```

## Run
On the **phone**: open the app → **Cane Cam** screen (this starts the TCP
server on port `8765`).

On the **Pi**:
```bash
cd pi_vision
# Same WiFi as the phone — pass the phone's IP:
python3 main.py --host <PHONE_IP>

# On the phone's hotspot — phone is the gateway, so auto-detect works:
python3 main.py
```
You should see "Connected to …" on the Pi and a live, box-annotated feed on the
phone.

### Useful flags
```
--host <ip>     phone IP (default: auto-detect via default gateway)
--port <n>      must equal AppConstants.piFramePort (default 8765)
--width/--height/--quality   capture tuning (bandwidth/latency knobs)
--max-fps <f>   cap the send rate (0 = uncapped)
```

## Find the phone's IP
- Hotspot on: the Pi's `ip route show default` prints `default via <phone-ip>`.
- Shared WiFi: check the phone's WiFi details, or `--host` it manually.

## Troubleshooting
- **Pi keeps "retrying in Ns":** the app's Cane Cam screen isn't open (server
  not listening), wrong `--host`, wrong port, or the two aren't on the same
  network. Test reachability: `ping <PHONE_IP>`.
- **`picamera2 not available`:** install it with apt (above), not pip.
- **Black/blurry first frames:** expected for ~0.5 s while AE/AF settle.

## Next (Step 2, not built yet)
BLE provisioning so the phone hands the Pi the hotspot SSID/password, and the
Pi auto-dials the phone gateway — removing the manual `--host`. See the plan.
