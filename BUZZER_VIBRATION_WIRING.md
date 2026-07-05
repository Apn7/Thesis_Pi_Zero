# Cane-Local Feedback: Active Buzzer + Vibration Motor — Wiring & Bring-Up

> **Scope:** adds two feedback modules to the existing Pi Zero 2 W cane rig
> (IMX519 camera on CSI + HC-SR04 sonar on GPIO23/24). Nothing in the existing
> wiring moves. **No new components are needed beyond 6 female–female Dupont
> jumper wires** — both modules have onboard transistor drivers, so they connect
> straight to the header. Your 4.5 kΩ resistors stay in the drawer.
>
> Every electrical claim below was verified against datasheets/vendor docs —
> sources at the bottom. Follow the steps in order and nothing gets damaged.

---

## 1. What the two boards are (identified from the photos)

### Module A — MH-FMD buzzer, **LOW-level trigger**, **PASSIVE piezo (confirmed 2026-07-05 field test)**
- Markings: `MH-FMD`, `低电平触发` = "low level trigger" (back silkscreen confirms:
  *Buzzer module — Low level trigger*).
- Pins: `GND`, `I/O`, `VCC`.
- Onboard: **S8550 PNP transistor** (SOT-23 marked `2TY`) as a **high-side**
  switch, 1 kΩ base resistor (SMD marked `102`).
- **Piezo element is PASSIVE, not active** — despite this exact "MH-FMD,
  low-level-trigger" labeling also being used on active-buzzer boards
  (confirmed by bring-up test: driving I/O to a static LOW via `pinctrl`
  produced a single click, not a sustained tone — the classic passive-piezo
  symptom, since a passive element has no internal oscillator and only moves
  once per voltage transition). **Consequence: the buzzer must be driven with
  a continuous PWM square wave (`config.BUZZER_TONE_HZ`, default 2700 Hz)
  through I/O, not a static level** — `feedback.py` does this via
  `lgpio.tx_pwm()`. A static LOW still means "buzzer path energised" (the PNP
  is on), it just won't produce sound by itself.
- Behaviour: **I/O toggling at audio rate while path is energised (I/O
  averaging LOW) → buzzer sounds. I/O HIGH (= VCC), no PWM → silent.**
- Spec: 3.3–5 V, ~30 mA @ 5 V (less at 3.3 V). The 85 dB @ 10 cm figure from
  the generic MH-FMD product sheet is for the **active** variant and may not
  match this unit — verify loudness by ear.

### Module B — vibration motor module (Keyestudio KS0450-class), **HIGH-level trigger**
- Markings: `Vibration Motor`, pins `IN`, `VCC`, `GND`.
- Onboard: **SI2302 N-channel MOSFET** (SOT-23 marked `A2SHB`) as a **low-side**
  switch, gate resistors (`1000` = 100 Ω series, `512` = 5.1 kΩ pull-down),
  flyback diode + capacitor across the 10 mm coin ERM motor.
- Behaviour: **IN HIGH → motor vibrates. IN LOW → stops.** PWM on IN controls
  intensity.
- Spec: vendor rates it "DC 5 V, 35 mA". The SI2302 is a **logic-level** MOSFET
  (turns on fully from 3.3 V), and the coin ERM inside is a 3 V-class motor, so
  running the whole module from 3.3 V is safe and correct. Budget up to
  ~120 mA momentarily at motor start-up to be conservative.

---

## 2. The three rules that protect your hardware

1. **The buzzer's VCC goes to 3.3 V — NEVER to 5 V.**
   This is the single most important line in this document. The S8550 is a PNP
   with its emitter at VCC: to silence it, the I/O pin must be pulled up to
   *VCC*. The Pi's GPIO high is only 3.3 V — if VCC were 5 V, the transistor
   base would sit 1.7 V below the emitter and the transistor stays partially
   on: **the buzzer whines/clicks and never fully turns off.** This is a
   widely documented failure with these modules on 3.3 V-logic boards. At
   3.3 V VCC everything is clean (just a bit quieter).
   *(The vibration module does not have this problem — its MOSFET is a
   low-side switch, so its trigger threshold doesn't depend on VCC.)*

2. **The pin assignments below are deliberate — don't swap them.**
   At power-on, before any software runs, the Pi's GPIOs are inputs with fixed
   default pulls baked into the SoC: **GPIO0–8 pull UP, GPIO9–27 pull DOWN.**
   - The buzzer is *active-low*, so it lives on **GPIO5** (pull-up group →
     held silent from the first millisecond of power). Put it on any
     GPIO9–27 pin and it will **scream through every boot (~30 s)**.
   - The motor is *active-high*, so it lives on **GPIO13** (pull-down group →
     held off during boot; the module's own 5.1 kΩ gate pull-down backs this up).

3. **Wire with the battery pack disconnected, and never route anything from the
   5 V pins (2/4) to the new modules.** Pi GPIOs are not 5 V tolerant; the only
   5 V consumer stays the HC-SR04, exactly as it is today.

---

## 3. Pin assignments

| Module pin | Pi physical pin | Pi signal | Why this pin |
|---|---|---|---|
| Buzzer **VCC** | **1** | 3V3 | 3.3 V only — see Rule 1 |
| Buzzer **I/O** | **29** | **GPIO5** | GPIO0–8 group: boot pull-up = silent boot |
| Buzzer **GND** | **30** | GND | adjacent to pin 29, tidy wiring |
| Motor **VCC** | **17** | 3V3 | safe for the 3 V coin motor (5 V upgrade path in §9) |
| Motor **IN** | **33** | **GPIO13** | GPIO9–27 group: boot pull-down = motor off at boot; PWM-capable |
| Motor **GND** | **34** | GND | adjacent to pin 33 |

Spares if a pin is ever damaged/occupied: buzzer → **GPIO6 (pin 31)** (same
boot-pull-up group); motor → **GPIO12 (pin 32)** or **GPIO19 (pin 35)** (same
boot-pull-down group, also PWM-capable). Update `pi_vision/config.py` if you
change them.

### Full header map (existing wiring marked — do not move it)

```
                 3V3  ( 1) ( 2)  5V      ← HC-SR04 VCC (existing — leave)
     (I2C) GPIO2  ( 3) ( 4)  5V      ← free (motor 5V upgrade path, §9)
     (I2C) GPIO3  ( 5) ( 6)  GND     ← HC-SR04 GND (existing — leave)
           GPIO4  ( 7) ( 8)  GPIO14 (UART)
             GND  ( 9) (10)  GPIO15 (UART)
          GPIO17 (11) (12)  GPIO18
          GPIO27 (13) (14)  GND
          GPIO22 (15) (16)  GPIO23   ← SONAR TRIG (existing — leave)
             3V3 (17) (18)  GPIO24   ← SONAR ECHO via 4.5 kΩ (existing — leave)
          GPIO10 (19) (20)  GND
           GPIO9 (21) (22)  GPIO25
          GPIO11 (23) (24)  GPIO8
             GND (25) (26)  GPIO7
    (EEPROM) GPIO0 (27) (28)  GPIO1 (EEPROM)
 BUZZER I/O→ GPIO5 (29) (30)  GND      ←BUZZER GND
           GPIO6 (31) (32)  GPIO12
  MOTOR IN→ GPIO13 (33) (34)  GND      ←MOTOR GND
          GPIO19 (35) (36)  GPIO16
          GPIO26 (37) (38)  GPIO20
             GND (39) (40)  GPIO21

 BUZZER VCC → pin 1 (3V3)     MOTOR VCC → pin 17 (3V3)
```

(If your HC-SR04 happens to sit on pin 4 / a different GND, fine — leave it
where it is; the free 5 V/GND pins adjust accordingly. GPIO0/1 are reserved for
HAT EEPROM and GPIO2/3 carry permanent onboard I2C pull-ups — that's why the
buzzer sits on GPIO5 rather than lower pins of the pull-up group.)

### Wiring diagrams

```
MH-FMD buzzer                          Pi Zero 2 W
  GND ────────────────────────────────  pin 30 (GND)
  I/O ────────────────────────────────  pin 29 (GPIO5)
  VCC ────────────────────────────────  pin 1  (3V3)    ⚠ 3.3 V ONLY

Vibration motor module
  IN  ────────────────────────────────  pin 33 (GPIO13)
  VCC ────────────────────────────────  pin 17 (3V3)
  GND ────────────────────────────────  pin 34 (GND)
```

No breadboard, no resistors, no soldering — 6 female–female jumpers, direct.

---

## 4. Assembly steps

1. **Power off.** Disconnect the battery pack (IP5306 module) from the Pi. Confirm the green LED is dead.
2. Connect the **buzzer**: GND → pin 30, I/O → pin 29, VCC → pin 1.
3. Connect the **motor module**: GND → pin 34, IN → pin 33, VCC → pin 17.
4. **Re-check against the table** — specifically: neither module touches pin 2
   or pin 4 (5 V). Count header positions twice; on the Zero the silkscreen
   numbers are tiny. Take a phone photo of the wiring for your records.
5. *(Optional, if you have a multimeter)*: continuity-check each jumper
   end-to-end, and confirm buzzer-VCC jumper lands on pin 1, not pin 2.

---

## 5. First power-on — acceptance test

1. Reconnect the battery pack. **Correct behaviour: total silence and no vibration,
   including during the whole ~30 s boot.**
   - Buzzer beeping during boot → it's not on GPIO5, or a wire is swapped. Power
     off and re-check.
   - Faint whine/click from the buzzer at idle → its VCC is on a 5 V pin. Power
     off and move it to pin 1.
2. SSH in and smoke-test **without any Python**, using Bookworm's `pinctrl`.
   **Note: the buzzer is a passive piezo (confirmed 2026-07-05) — a static
   `dl` only proves the PNP switches (you'll hear one click, not a tone); it
   does NOT confirm the buzzer can sound continuously. Use the motor test
   below to confirm wiring, then use step 3's Python test for the buzzer.**

   ```bash
   # Buzzer (active-LOW): a static level only clicks once — expected, not a bug.
   pinctrl set 5 op dl    # PNP ON  → one click
   pinctrl set 5 op dh    # PNP OFF → silent            ← leave it here

   # Motor (active-HIGH):
   pinctrl set 13 op dh   # drive HIGH → motor vibrates
   pinctrl set 13 op dl   # drive LOW  → motor OFF      ← leave it here
   ```

   If a script ever dies leaving the buzzer stuck on, `pinctrl set 5 op dh`
   is your manual kill switch.
3. Run the feedback self-test (uses `lgpio`, same library as the sonar —
   already installed). This plays the real production patterns, one verdict
   at a time:

   ```bash
   cd ~/Thesis_pi_zero/pi_vision        # wherever the repo lives on the Pi
   python3 feedback.py                  # CAUTION → WARNING → CRITICAL → off
   ```

   The script claims GPIO5/GPIO13 with safe initial levels and restores safe
   levels in a `finally:` block, so Ctrl-C never leaves the buzzer latched on.
   (The original bring-up script `feedback_test.py` was retired when the
   patterns moved into production `feedback.py`, 2026-07-05.)

---

## 6. Boot hardening (recommended, 1 minute)

The SoC's default pulls already keep both modules quiet from power-on, but you
can make the bootloader *actively drive* the safe levels within the first
seconds of boot. Add to `/boot/firmware/config.txt`:

```ini
# Cane feedback modules: force safe levels from the bootloader onward.
# GPIO5 = buzzer (active-low → drive high = silent)
# GPIO13 = vibration motor (active-high → drive low = off)
gpio=5=op,dh
gpio=13=op,dl
```

Then `sudo reboot` and confirm the boot is still silent. `lgpio` reclaims the
pins normally at runtime; these lines only set the state until your software
takes over. They also restore safe states on reboot if a program crashed with
the buzzer on.

---

## 7. Power budget (why this is comfortably safe)

| Load | Rail | Current | Notes |
|---|---|---|---|
| Pi Zero 2 W streaming camera + WiFi | 5 V | ~400–600 mA | existing |
| HC-SR04 | 5 V | ~15 mA | existing |
| Buzzer (only while sounding) | 3V3 | ~20–25 mA | 30 mA @ 5 V spec, less at 3.3 V |
| Motor (only while vibrating) | 3V3 | ~35 mA typ, ≤120 mA start-up | vendor 35 mA; conservative start-up budget |

The header's 3.3 V rail on the Zero 2 W comes from the onboard switching
regulator; community-accepted safe external draw is a few hundred mA
(~500 mA class). Worst case both modules together add ~150 mA in short bursts —
fine. The pack's IP5306-based boost module supplies 5 V at up to ~2.1–2.4 A
([Injoinic IP5306 datasheet](https://www.laskakit.cz/user/related_files/ip5306.pdf)),
comfortably covering this on top of the Pi's own ~400–600 mA camera+WiFi draw.
Alert patterns are pulsed anyway (§10), so average draw is far lower. One
IP5306 quirk worth knowing: it auto-standbys if the **total 5 V load** stays
below ~45–50 mA for 30+ seconds ([community reports](https://community.m5stack.com/topic/62/ip5306-automatic-standby)) —
irrelevant here since the streaming Pi alone is far above that floor, but don't
expect the board to hold 5 V through a bare-idle test with everything else
unplugged.

Watch `journalctl` for the existing under-voltage health logs
(`HEALTH_LOG_INTERVAL_S`) during the first combined test — if under-voltage
flags appear they'll be from the battery pack's cable/connector, not these
modules, but now is a convenient time to notice.

---

## 8. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Buzzer sounds during boot | Signal on a GPIO9–27 pin (boot pull-down) or wires swapped | Move signal to GPIO5 (pin 29); add §6 config.txt lines |
| Buzzer never fully silent / faint whine, clicks continuously | VCC on 5 V (Rule 1 violated) | Move VCC to pin 1 (3V3) |
| Buzzer only clicks once per on/off transition, no sustained tone | Passive piezo (confirmed on this unit) driven with a static level instead of PWM | Use `feedback.py` / `lgpio.tx_pwm()` at `config.BUZZER_TONE_HZ`, not `pinctrl set ... op dl` alone — a static level only proves the PNP switches, it won't make sound by itself |
| Buzzer works but quiet | Expected at 3.3 V (−5..10 dB vs 5 V) | Acceptable (it's at hand height); see §9 appendix if truly insufficient |
| Motor does nothing | IN not reaching the module / broken motor leads | `pinctrl set 13 op dh` then measure IN–GND ≈ 3.3 V; inspect the thin red/blue motor leads |
| Motor hums/twitches at low PWM but won't spin | ERM needs a kick-start | Start at 100 % duty for ~50 ms, then drop to target duty (test script does this) |
| Motor vibration too weak through the cane grip | 3.3 V drive + loose mounting | First fix mounting (§11), then consider the 5 V upgrade (§9) |
| `lgpio` permission error | User not in `gpio` group | `sudo usermod -aG gpio $USER`, re-login (same as sonar setup) |
| Script killed, buzzer stuck on | Pin left driven low | `pinctrl set 5 op dh`; §6 lines fix it on reboot |

---

## 9. Field-tuning: if the motor is too weak at 3.3 V

Unlike the buzzer, the motor module **may** move to 5 V, because its SI2302
low-side MOSFET switches fine from a 3.3 V gate regardless of VCC — the 5 V
never reaches the GPIO. Trade-off: the coin ERM is a 3 V-class motor, so at
5 V it vibrates much harder but runs hotter and wears faster.

Upgrade path (one wire): move **motor VCC from pin 17 → pin 4 (5 V)**. Then cap
sustained drive in software at **~60 % PWM duty** (≈3 V average) and reserve
100 % for short CRITICAL bursts. Do **not** apply any of this to the buzzer.

**Appendix — buzzer at 5 V loudness (only if field tests demand it; needs one
new part, any NPN like BC547/2N2222, ~5–10 টাকা):** GPIO → 4.5 kΩ (you have
these) → NPN base; emitter → GND; collector → buzzer `I/O`; buzzer VCC → 5 V.
The NPN pulls I/O to ground = buzzer ON, so the logic **inverts to
active-high** — move the signal to a GPIO9–27 pin (e.g. GPIO6 is now wrong;
use GPIO12) and flip the constants. Skip this unless truly needed.

---

## 10. Integration into the system (IMPLEMENTED 2026-07-05 — Pi-local reflex)

Option 1 below is now live: `sonar_main.py` classifies every median reading
on the Pi (`verdict.py`, a direct port of the app's
`distance_alert_source.dart` — same thresholds `config.py
OBSTACLE_CRITICAL/WARNING/CAUTION_CM` = 50/100/200 AND the same 10 cm
de-escalation hysteresis) and drives the modules via `feedback.py`, a
10 ms-tick pattern engine. The cane alerts standalone; when the app is also
connected, both devices classify the same value with the same rules, so they
alert in lockstep by construction.

Pattern vocabulary (mirrors the app's `home_screen.dart` vibration rhythms,
so cane grip and phone speak one haptic language):
- **CRITICAL** (<50 cm): motor five 600 ms pulses/80 ms gaps then ~90 % duty
  loop + fast beeps (100 ms on/off) for as long as the verdict holds.
- **WARNING** (<100 cm): motor double pulse (250/120/250 ms) then one 250 ms
  pulse every 1.5 s; buzzer silent.
- **CAUTION** (<200 cm): motor triple tap (80/80 ×3) every 2.5 s; buzzer
  silent (scarcity keeps the buzzer meaningful — it means STOP, nothing else).
- **SAFE / NO_DATA**: everything off; a sensor fault silences, never latches.

Kept for later (richer UX, not needed for sync): **phone-commanded feedback** —
the sonar TCP socket is full-duplex, so the app could write verdict/pattern
bytes back down the same connection (e.g. camera-derived alerts on the cane);
the Pi would add a small reader thread.

---

## 11. Mechanical notes (matters more than electronics for haptics)

- The coin motor transmits vibration through whatever it's **rigidly** bolted
  to. Velcro/loose tape = nothing felt at the grip. Zip-tie or screw the module
  (it has 3 mm holes) directly to the cane shaft near the handle.
- The motor's red/blue leads are hair-thin — put a dab of hot glue over the
  solder joints as strain relief before field use.
- Don't cover the buzzer's sound hole when enclosing.

---

## Sources

- Buzzer 5 V-VCC/3.3 V-logic failure + "power it at 3.3 V" fix: [eMariete — active/passive buzzer guide](https://emariete.com/en/buzzer-active-or-passive-buzzer-for-arduino-esp8266-nodemcu-esp32-etc/), [Raspberry Pi forums — low-trigger buzzer trouble](https://forums.raspberrypi.com/viewtopic.php?t=271942)
- MH-FMD module spec (S8550, low-level trigger, 3.3–5 V, ~30 mA, 85 dB): [HandsOn Tech product sheet](https://handsontec.com/index.php/product/active-buzzer-module-low-level-trigger/), [HIT.PS listing](https://hit.ps/product/active-buzzer-module-low-level-trigger-3-3v-5v-s8550-driver)
- GPIO boot pull defaults (GPIO0–8 up, GPIO9–27 down): [raspberrypi/firmware issue #487](https://github.com/raspberrypi/firmware/issues/487), [Pi forums — default pull state](https://forums.raspberrypi.com/viewtopic.php?t=123427), [boot-time GPIO errata](https://quorten.github.io/quorten-blog1/blog/2020/10/26/rpi-gpio-boot-errata)
- SI2302 / A2SHB logic-level N-MOSFET: [Soldering Mind — Si2302 pinout & specs](https://solderingmind.com/si2302/), [Sunrom datasheet page](https://www.sunrom.com/p/si2302-a2shb-sot23-n-ch-mosfet)
- Vibration module spec (DC 5 V, 35 mA, high trigger, PWM): [Keyestudio KS0450 docs](https://docs.keyestudio.com/projects/KS0450/en/latest/docs/KS0450.html)
- 3.3 V rail budget: [pinout.xyz — 3v3 power](https://pinout.xyz/pinout/pin1_3v3_power/), [Pi forums — 3.3 V max current](https://forums.raspberrypi.com/viewtopic.php?t=284104)
- ERM drive practice (kick-start, PWM): [Precision Microdrives AB-001](https://www.precisionmicrodrives.com/ab-001-discrete-driver-circuits-for-vibration-motors)
- IP5306 power-bank IC (5 V boost, ~2.1–2.4 A out; auto-standby below ~45–50 mA load): [Injoinic IP5306 datasheet](https://www.laskakit.cz/user/related_files/ip5306.pdf), [M5Stack community — auto-standby](https://community.m5stack.com/topic/62/ip5306-automatic-standby)
