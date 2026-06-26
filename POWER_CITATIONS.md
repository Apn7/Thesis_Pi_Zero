# Power Source: Literature Support for COTS Power Bank

For thesis writeup — justifies using a commercial USB power bank instead of custom battery management.

## Suggested thesis sentence

> "Following established ETA prototypes [1, 2], the system is powered by a commercial USB power
> bank providing regulated 5V, integrated protection, and recharging — keeping the contribution
> focused on on-phone inference efficiency rather than power electronics."

## Confirmed sources (peer-reviewed)

**[1] Pi 3B+ wearable ETA — 5000 mAh USB power bank**
- Citation: PMC9229985 — peer-reviewed wearable assistive device for blind pedestrians.
- Quote: *"To provide the Raspberry Pi 3B+ with a stable power supply, we chose a 5000 mAh mobile
  power supply, which is enough to keep the device running for more than 3 h."*
- URL: https://pmc.ncbi.nlm.nih.gov/articles/PMC9229985/
- Relevance: same class of hardware (Pi + camera, YOLO-style detection), identical power approach.

**[2] Pi 3B+ smart assistant — "ordinary power bank"**
- Citation: PMC9185302 — peer-reviewed smart assistant for the visually impaired.
- Quote: *"The central unit is supplied from an ordinary power bank, requiring 5 W/h."*
- URL: https://pmc.ncbi.nlm.nih.gov/articles/PMC9185302/
- Relevance: "ordinary" signals it's treated as a non-decision; standard practice.

**[3] MDPI 2025 smart cane — 10,000 mAh LiPo 5V/3A as the power supply**
- Citation: MDPI Information 2025, info16080707 — Pi 4 + two cameras cane.
- Quote: *"The hardware unit comprises four main components: a battery serving as the power supply,
  a Raspberry Pi 4 Model B…"* (10,000 mAh LiPo, 5V/3A — power-bank-class spec)
- URL: https://www.mdpi.com/2078-2489/16/8/707
- Relevance: confirms 10,000 mAh / 5V/3A (matching your QCY PB10C exactly) is a published choice.

## What the commercial products do (different bar — not needed for thesis justification)

- **WeWALK Smart Cane**: integrated built-in rechargeable battery, ~20 h. (wewalk.io)
- **Glide AI Aid**: integrated battery, USB-C wall charging. (glidance.io)

Note: commercial products integrate the battery into the handle for UX/aesthetics — a thesis
prototype is not held to that standard. The two peer-reviewed papers above are the right comparators.

---

## Full research analysis

**Verdict: A COTS power bank is common and well-precedented in research prototypes — exactly this
situation. Custom battery management is mostly a commercial-product concern.**

**Academic papers / theses use power banks routinely, and describe it as unremarkable:**

- A peer-reviewed wearable ETA powered its Raspberry Pi 3B+ from a 5000 mAh USB power bank,
  justified simply as "stable power supply… more than 3 h" runtime. (PMC9229985)
- Another peer-reviewed Pi 3B+ smart-assistant for the blind says the central unit "is supplied
  from an ordinary power bank" — note the word *ordinary*; they treat it as a non-issue. (PMC9185302)
- An MDPI 2025 smart cane uses a 10,000 mAh LiPo rated 5V/3A as "the power supply" for a Pi 4 +
  two cameras — essentially a power-bank-class battery in that role. (MDPI info16080707)

**Custom battery management (bare LiPo + boost/charge board) does appear — but typically in tightly
integrated cane builds, not Pi+camera streaming rigs:**

- An IoT cane drives its electronics from a LiPo + PowerBoost module (custom). (arXiv 2508.16698)
  (2-1 adversarial vote — slightly less certain.)

**Commercial products go integrated, not external power bank — because they're polished consumer
devices, a different bar than a thesis:**

- WeWALK: built-in rechargeable battery, ~20 h.
- Glide: integrated battery, USB-C wall charging.

**What this means for this thesis:**

Using a COTS power bank is a defensible, literature-backed choice for a Master's prototype —
multiple peer-reviewed ETAs do exactly this, and one even powers the same Pi+camera class of
system. The custom-BMS route (TP4056 + boost) is what you'd reach for only if productizing into an
integrated handle — i.e. the "fancy version" later, matching what WeWALK/Glide do.

**Caveat:** a few power-bank claims from a VisBuddy arXiv source and a TP4056 module source
couldn't be fully adversarially verified (hit session limit mid-run) — but they don't change the
conclusion, which rests on the four confirmed peer-reviewed/commercial sources above.
