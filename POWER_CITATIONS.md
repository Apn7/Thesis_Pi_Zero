# Power Source: Literature Support for the Custom 18650 + IP5306 Pack

> **2026-07-05 correction:** this document previously assumed a COTS power bank (e.g. a
> 10,000 mAh QCY PB10C bought as a finished product). That was never what got built and should not
> have been asserted — the actual hardware is a **custom pack: three 800 mAh 18650 cells wired in
> parallel (1S3P), feeding a small commercial power-bank-management IC (IP5306) breakout board**
> (micro-USB charge in, USB-A 5 V boost out). This rewrite corrects the citations and numbers to
> match. See `Thesis_pi_zero/BUZZER_VIBRATION_WIRING.md` §7 for how the buzzer/motor draw fits the
> IP5306's output budget.

For thesis writeup — justifies using a commercial power-management IC + hand-built pack instead of
a fully bespoke charge/protection circuit.

## What was actually built

- **Cells:** 3× "HL IMR18650-800mAh, 3.7V, 2.96Wh" wired **in parallel** (1S3P) — combined
  **2,400 mAh @ 3.7V nominal ≈ 8.88 Wh** raw pack energy. This is a single-cell-voltage pack (not a
  higher-voltage series pack), which matters below.
- **Power management: IP5306** (Injoinic), a fully-integrated single-cell power-bank
  system-on-chip — the same chip found inside most small COTS power banks. Confirmed specs from
  the datasheet:
  - Charging in: micro-USB, DC 4.5–5.5 V, up to ~2.1 A (buck, 750 kHz), up to 97% efficiency.
  - Discharge out: boost converter, 500 kHz, **5 V @ up to ~2.1–2.4 A**, up to 92% efficiency.
  - Protections: overcurrent (OCP), overvoltage (OVP), short-circuit (SCP), over-temperature (OTP)
    — all on-chip, no separate BMS board needed for a single-cell-voltage (1S) pack.
  - Known quirk: auto-standby (cuts the 5 V boost) if total output load stays under ~45–50 mA for
    30+ seconds — irrelevant to this rig since the streaming Pi alone draws far more, but worth
    knowing if the board is ever bench-tested with everything else unplugged.
- **Why parallel, not series:** the IP5306 is rated for a single Li-ion cell's voltage range
  (3.0–4.2 V-class), not a 3-cell-series ~11.1 V pack. Wiring the cells in parallel keeps the pack
  at the voltage the IC expects while summing capacity — the correct topology for this chip.

## Suggested thesis sentence

> "The onboard electronics are powered by a hand-assembled 2,400 mAh (1S3P, three 800 mAh 18650
> cells) lithium-ion pack, regulated by a commercial single-cell power-bank management IC (IP5306)
> that supplies the 5 V rail, battery charging, and cell protection. This follows the same
> power-bank-based supply strategy used in comparable ETA prototypes [1, 2, 3] while sizing pack
> capacity and form factor to the cane rather than adopting an off-the-shelf power-bank enclosure."

## Confirmed sources (peer-reviewed) — Li-ion/power-bank-style supply precedent

**[1] Pi 3B+ wearable ETA — 5000 mAh USB power bank**
- Citation: PMC9229985 — peer-reviewed wearable assistive device for blind pedestrians.
- Quote: *"To provide the Raspberry Pi 3B+ with a stable power supply, we chose a 5000 mAh mobile
  power supply, which is enough to keep the device running for more than 3 h."*
- URL: https://pmc.ncbi.nlm.nih.gov/articles/PMC9229985/
- Relevance: same class of hardware (Pi + camera, YOLO-style detection), same power-bank-IC-style
  approach. Note their pack is ~2× the raw energy of ours (18.5 Wh vs our 8.88 Wh) — see runtime
  estimate below; don't assume the same "3 h+" figure transfers without measuring on hardware.

**[2] Pi 3B+ smart assistant — "ordinary power bank"**
- Citation: PMC9185302 — peer-reviewed smart assistant for the visually impaired.
- Quote: *"The central unit is supplied from an ordinary power bank, requiring 5 W/h."*
- URL: https://pmc.ncbi.nlm.nih.gov/articles/PMC9185302/
- Relevance: "ordinary" signals it's treated as a non-decision; standard practice.

**[3] MDPI 2025 smart cane — 10,000 mAh LiPo 5V/3A as the power supply**
- Citation: MDPI Information 2025, info16080707 — Pi 4 + two cameras cane.
- Quote: *"The hardware unit comprises four main components: a battery serving as the power supply,
  a Raspberry Pi 4 Model B…"* (10,000 mAh LiPo, 5V/3A).
- URL: https://www.mdpi.com/2078-2489/16/8/707
- Relevance: confirms a power-bank-class Li-ion supply (much larger than ours) is a published
  choice for this hardware class; a useful upper-capacity comparator, not a match for the actual
  pack size built here.

**[4] IP5306 — commercial power-bank management IC**
- Citation: Injoinic IP5306 datasheet.
- URL: https://www.laskakit.cz/user/related_files/ip5306.pdf
- Relevance: this is literally the IC used — establishes that the charge/boost/protection function
  is a standard, commercially-integrated single chip, not a bespoke circuit designed for this
  thesis. Supports the same "kept the contribution on inference efficiency, not power electronics"
  argument as citing a finished power bank, arguably more precisely (it names the exact component).

## Rough runtime estimate (calculate, then MEASURE on hardware for the writeup)

| Quantity | Value |
|---|---|
| Raw pack energy | 2,400 mAh × 3.7 V ≈ **8.88 Wh** |
| After IP5306 boost losses (~90%) | ≈ **7.5–8 Wh** deliverable at 5 V |
| Pi Zero 2 W streaming camera + WiFi | ~400–600 mA @ 5V ≈ 2–3 W (existing measurement) |
| + HC-SR04 | ~15 mA ≈ 0.08 W |
| + buzzer/motor (pulsed, time-averaged) | small — well under 0.3 W average |
| Estimated continuous draw | ≈ **2.2–3.3 W**, call it ~2.75 W |
| **Estimated runtime** | **≈ 2.5–3 hours** of continuous streaming |

This is meaningfully **shorter** than the ">3 h" figure in [1], because that paper's 5000 mAh
single-cell pack holds roughly double the raw energy of this 2,400 mAh pack. **Measure the actual
runtime on hardware** (a stopwatch + `journalctl` under-voltage/throttle flags from
`HEALTH_LOG_INTERVAL_S` is enough) before writing a specific number into the thesis — this table is
a sanity-check estimate, not a substitute for the real measurement.

If longer bench-test runtime is ever needed, the straightforward fix is more parallel cells (1S4P,
1S5P…) on the same IP5306 board — capacity scales linearly, voltage and IC choice don't change.

## What the commercial products do (different bar — not needed for thesis justification)

- **WeWALK Smart Cane**: integrated built-in rechargeable battery, ~20 h. (wewalk.io)
- **Glide AI Aid**: integrated battery, USB-C wall charging. (glidance.io)

Commercial products integrate the battery into the handle for UX/aesthetics — a thesis prototype
is not held to that standard.

## A note on cell safety (light-touch, not a redesign)

Parallel-wired raw 18650s without individual per-cell fusing is standard DIY-power-bank practice
(it's what's inside generic COTS banks too) and the IP5306 provides pack-level protection — no
change needed. Two cheap precautions worth keeping in mind if cells are ever replaced: don't mix a
new cell with significantly more-worn cells in the same parallel group (an imbalanced cell can
sink/source current from its neighbours at rest), and make sure the solder/spot-weld joints are
solid (a loose parallel connection is the usual failure mode, not the chemistry).

---

## Full research analysis (retained from the original pass)

**Verdict: A power-bank-style Li-ion supply (COTS or, as built here, a commercial power-management
IC + custom pack) is common and well-precedented in research prototypes.**

- A peer-reviewed wearable ETA powered its Raspberry Pi 3B+ from a 5000 mAh USB power bank,
  justified simply as "stable power supply… more than 3 h" runtime. (PMC9229985)
- Another peer-reviewed Pi 3B+ smart-assistant for the blind says the central unit "is supplied
  from an ordinary power bank" — note the word *ordinary*; they treat it as a non-issue. (PMC9185302)
- An MDPI 2025 smart cane uses a 10,000 mAh LiPo rated 5V/3A as "the power supply" for a Pi 4 +
  two cameras — essentially a power-bank-class battery in that role. (MDPI info16080707)

**Custom battery management (bare cells + boost/charge IC) also appears in the literature — and is
in fact the closer match to what was actually built here:**

- An IoT cane drives its electronics from a LiPo + PowerBoost module (custom). (arXiv 2508.16698)
  (2-1 adversarial vote — slightly less certain.)

**What this means for this thesis:**

Using a commercial power-management IC (IP5306) to drive a hand-sized custom pack is a defensible,
literature-backed middle ground: it avoids designing charge/protection circuitry from discrete
parts (which would be off-thesis-topic engineering), while not requiring a bulky pre-made power
bank enclosure either. The peer-reviewed comparators above establish that power-bank-style Li-ion
supply is standard for this hardware class; the runtime estimate above should be replaced with a
measured number before the thesis is finalized.

**Caveat:** a few power-bank claims from a VisBuddy arXiv source and a TP4056 module source
couldn't be fully adversarially verified in the original research pass (hit session limit mid-run)
— they don't change the conclusion, which rests on the confirmed peer-reviewed/datasheet sources
above.
