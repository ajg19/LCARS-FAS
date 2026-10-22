# Satellite–Ground Station Link Budget: Can Either Side Actually Hear the Other?

A satellite link has to work in both directions independently. The **downlink** (satellite transmits, ground station receives) and the **uplink** (ground station transmits, satellite receives) each need their own link budget — a strong downlink says nothing about whether the uplink will close, because the transmitter, receiver, and often the frequency are all different.

Both directions use the same underlying physics, summarised at the end. What differs is which side is "transmitter" and which is "receiver."

---

## 1. Downlink — Can the Ground Station Receive the Satellite?

### 1.1 The ordinary equation (multiplying real quantities)

Received power at the ground station:

```
                P_t · G_t · G_r
        P_r  =  ────────────────
                 L_fs · L_a · L_o
```

| Term | Meaning | Units |
|---|---|---|
| `P_r` | Power actually delivered to the ground station receiver | watts (W) |
| `P_t` | Satellite's transmitter output power | watts (W) |
| `G_t` | Satellite's transmit antenna gain | ratio (unitless) |
| `G_r` | Ground station dish's receive gain | ratio (unitless) |
| `L_fs` | Free-space path loss (signal spreading out over distance) | ratio (unitless, ≥ 1) |
| `L_a` | Atmospheric loss — cloud, rain, gas absorption | ratio (unitless, ≥ 1) |
| `L_o` | Other losses — pointing error, polarization mismatch, feed/cable loss | ratio (unitless, ≥ 1) |

Note that `P_t × G_t` together is what's usually just called **EIRP** (Effective Isotropic Radiated Power) — the satellite's transmit power and antenna gain are rarely quoted separately, because from the ground all that matters is their product.

Losses (`L_fs`, `L_a`, `L_o`) sit in the *denominator* because they're always ≥ 1: they can only reduce the signal, never add to it.

### 1.2 Converting to the dB version

Take 10·log₁₀ of both sides. Multiplication and division turn into addition and subtraction — this is the entire reason link budgets are done in dB:

```
P_r(dBW) = EIRP(dBW) + G_r(dBi) − L_fs(dB) − L_a(dB) − L_o(dB)
```

where `EIRP(dBW) = P_t(dBW) + G_t(dBi)`.

Every term is now a dB-referenced quantity rather than a raw multiplicative factor:

| Term | Meaning | Typical reference |
|---|---|---|
| `EIRP(dBW)` | Satellite's effective radiated power | published by the satellite operator / in its ITU filing |
| `G_r(dBi)` | Ground station dish gain, relative to a theoretical isotropic radiator | depends on dish diameter and frequency |
| `L_fs(dB)` | Free-space path loss | `20·log₁₀(d) + 20·log₁₀(f) + 92.45` (d in km, f in GHz) |
| `L_a(dB)` | Atmospheric/rain attenuation | depends on frequency, elevation angle, and weather — this is where your cloud-cover data feeds in |
| `L_o(dB)` | Pointing, polarization, feed losses | usually a design/measurement figure, a few tenths to ~1 dB when well-aligned |

The three subsections below derive `G_r`, `L_fs`, and `L_a` rather than just quoting the formulas.

#### 1.2.1 Where dish gain comes from

Gain is always measured relative to an **isotropic radiator** — a hypothetical antenna that radiates (or receives) equally in every direction, spreading its power over the full sphere of 4π steradians. Anything that concentrates energy into a narrower beam than that has gain greater than 1 (> 0 dBi) in the directions it favours.

For *any* lossless antenna, electromagnetic theory (via the reciprocity theorem) gives a fixed relationship between its gain and its **effective aperture** `A_eff` — the effective area it presents for capturing power, independent of whether you're using it to transmit or receive:

```
G = 4π · A_eff / λ²
```

For a parabolic dish, the effective aperture is a fraction of the dish's physical area:

```
A_eff = η · A_phys = η · (π D² / 4)
```

`D` is the dish diameter and `η` is the **aperture efficiency** — typically 0.55–0.70 for a well-built reflector. A dish never captures/radiates at 100% of its physical area's theoretical potential; real losses come from feed illumination taper (the feed doesn't light up the dish perfectly uniformly), spillover (some feed energy misses the dish edge entirely), blockage from the feed or subreflector sitting in the aperture, and small surface deviations from a true parabola causing phase errors across the wavefront.

Combining the two:

```
G = 4π · η · (π D² / 4) / λ²  =  η · (π D / λ)²
```

This is the cleanest way to *see* the physics: `π D / λ` is (proportional to) how many wavelengths fit across the dish's diameter. A dish that's large compared to the wavelength focuses energy into a much narrower beam than one that's small compared to the wavelength — that ratio, squared, times the efficiency, is the gain.

Substituting `λ = c/f` and converting to dB (`10·log₁₀`) turns the squared ratio into two `20·log₁₀` terms plus a constant that absorbs `π`, `c`, the GHz↔Hz unit conversion, and `η`:

```
G_r(dBi) = 20·log₁₀(D) + 20·log₁₀(f) + [10·log₁₀(η) + 20·log₁₀(π·10⁹/c)]
                                        └────────────────┬────────────────┘
                                              ≈ 17.8 dB when η = 0.55
```
(D in metres, f in GHz.) Doubling the dish diameter, or doubling the frequency, each adds 6 dB of gain — because both double the number of wavelengths spanning the aperture. A different efficiency just shifts the constant: η = 0.65 pushes it to about 18.9 dB.

#### 1.2.2 Where free-space path loss comes from

Start from an isotropic transmitter radiating power `P_t` in every direction. At distance `d`, that power is spread uniformly over the surface of a sphere of radius `d`, so the power density (W/m²) there is:

```
S = P_t / (4π d²)
```

That's just the inverse-square law — nothing has been absorbed, the same total power is simply spread over a larger surface as the sphere grows. If the transmit antenna has gain `G_t` instead of being isotropic, it concentrates that same power into a narrower solid angle, so:

```
S = P_t · G_t / (4π d²) = EIRP / (4π d²)
```

The receive antenna doesn't capture the full sphere — it captures whatever power density lands on its effective aperture `A_eff,r`:

```
P_r = S · A_eff,r
```

Using the same gain–aperture relationship from §1.2.1, rearranged for the receiver — `A_eff,r = G_r · λ² / (4π)` — and substituting:

```
P_r = P_t · G_t · G_r · [λ / (4π d)]²
```

This is the **Friis transmission equation**. The bracketed term is the only piece that depends purely on geometry and wavelength — not on either antenna's gain, which is why it's pulled out and named separately as the free-space path loss:

```
L_fs = (4π d / λ)²
```

It isn't "loss" in the sense of energy being absorbed or destroyed; it's the geometric dilution of a spreading spherical wavefront, exactly analogous to why a flashlight looks dimmer from further away even though no light was absorbed in between.

Converting to dB, substituting `λ = c/f`, and folding `4π`, the speed of light, and the km/GHz unit conversions into one constant:

```
L_fs(dB) = 20·log₁₀(4π d / λ) = 20·log₁₀(d) + 20·log₁₀(f) + 92.45
```
(d in km, f in GHz — check: `20·log₁₀(4π × 10¹² / 3×10⁸) = 92.45`, confirming the constant above.) Doubling either distance or frequency costs another 6 dB, same pattern as antenna gain, just working against you here instead of for you.

#### 1.2.3 Where atmospheric loss comes from

Unlike gain and free-space loss, `L_a` has no single closed-form equation — it's the sum of several physically distinct mechanisms, each modeled semi-empirically (typically via the relevant ITU-R Recommendations) rather than derived from a clean formula:

- **Gaseous absorption** — oxygen and water-vapour molecules resonate at specific frequencies (an O₂ absorption complex near 60 GHz, water-vapour lines near 22.2 GHz and 183 GHz) and absorb energy there even in a perfectly clear sky. This baseline rises with frequency and is modeled by ITU-R P.676.
- **Cloud/fog attenuation** — non-precipitating liquid water droplets suspended in clouds absorb and scatter energy roughly in proportion to the integrated liquid water content along the path (ITU-R P.840). Small at L/Ku-band, increasingly relevant from Ka-band up.
- **Rain attenuation** — usually the dominant and most variable term at Ku-band and above, because raindrop size becomes comparable to the wavelength. ITU-R P.618 models the specific attenuation as `γ_R = k · R^α` (dB/km), where `R` is rain rate (mm/hr, usually the rate exceeded 0.01% of the time for the local climate zone) and `k`, `α` are empirical, frequency- and polarization-dependent coefficients (tabulated in ITU-R P.838), multiplied by an effective path length through the rain cell.
- **Elevation-angle geometry** — all of the above are normally characterized looking straight up (zenith). At a lower elevation angle the signal slants through much more atmosphere before reaching space. The standard first-order correction is the cosecant law:

```
L_a(elevation) ≈ L_a(zenith) / sin(elevation angle)
```

  (Near the horizon this flat-atmosphere approximation breaks down — below roughly 10° elevation, proper models switch to curved-Earth ray tracing — but cosecant scaling captures the dominant effect: a satellite low on the horizon can see several times the atmospheric loss of one directly overhead.)

Because `L_a` is a statistical, time-varying quantity rather than a fixed constant, link budgets don't use a single number for it — they hold back a **rain-fade margin**, sized to whatever percentage-of-time availability the link needs (e.g. enough margin to stay closed 99.5% vs. 99.99% of the year). This is exactly where empirical, site-specific weather history — like historical cloud-cover and precipitation records for a candidate ground-station location — earns its keep: it turns "atmospheric loss" from a textbook constant into a defensible, climate-specific design margin for *that* site.

### 1.3 Is the received signal actually usable?

`P_r` alone doesn't answer "can I receive it" — a signal below the receiver's noise floor is just noise. You need the **carrier-to-noise ratio**, C/N:

```
C/N (dB) = P_r(dBW) − N(dBW)
```

where the noise power `N` is:

```
N(dBW) = 10·log₁₀(k) + 10·log₁₀(T_sys) + 10·log₁₀(B)
```

`k` is Boltzmann's constant (a fixed value, −228.6 dBW/K/Hz), `T_sys` is your receive system's total noise temperature in Kelvin (sky noise + feed loss + LNA noise figure, combined), and `B` is your receiver bandwidth in Hz.

**The verdict:** if `C/N` (or `Eb/N0`, which further accounts for data rate) clears the minimum threshold the satellite's modulation and coding scheme requires — *with margin held back for rain fade* — the downlink closes. If not, it doesn't, regardless of how strong `P_r` looks in isolation.

---

## 2. Uplink — Can the Satellite Receive the Ground Station?

Same physics, roles reversed: now the ground station is the transmitter and the satellite is the receiver.

### 2.1 The ordinary equation

```
                  P_t,gs · G_t,gs · G_r,sat
        P_r,sat = ──────────────────────────
                     L_fs · L_a · L_o
```

| Term | Meaning | Units |
|---|---|---|
| `P_r,sat` | Power delivered to the satellite's receiver | watts (W) |
| `P_t,gs` | Ground station's transmitter output power | watts (W) |
| `G_t,gs` | Ground station dish's transmit gain | ratio (unitless) |
| `G_r,sat` | Satellite's receive antenna gain | ratio (unitless) |
| `L_fs`, `L_a`, `L_o` | Same categories as the downlink — path loss, atmospheric loss, other losses | ratio (unitless, ≥ 1) |

`P_t,gs × G_t,gs` is the ground station's own EIRP — the same concept as the satellite's downlink EIRP, just calculated from your dish and transmitter instead of theirs. `G_t,gs` is derived exactly as in §1.2.1 (it's the same physical dish, just transmitting instead of receiving — gain doesn't care which direction the energy is flowing). `L_fs` and `L_a` are derived exactly as in §1.2.2 and §1.2.3, evaluated at the uplink frequency rather than the downlink frequency.

### 2.2 The dB version

```
P_r,sat(dBW) = EIRP_gs(dBW) + G_r,sat(dBi) − L_fs(dB) − L_a(dB) − L_o(dB)
```

where `EIRP_gs(dBW) = P_t,gs(dBW) + G_t,gs(dBi)`.

### 2.3 Is it usable? Same C/N test, but usually the harder direction

```
C/N (dB) = P_r,sat(dBW) − N_sat(dBW)
```

using the satellite's own noise temperature and bandwidth in place of the ground station's.

**Two things that usually make the uplink the tighter constraint, not the downlink:**

- Satellites carry small receive antennas by necessity (mass and power budget), so `G_r,sat` and the satellite's noise performance are typically much worse than a large ground dish's. This is why ground stations often need substantial transmit EIRP — a big dish, real transmitter power, or both — to close the uplink, even though the satellite's downlink to that same dish is comparatively easy.
- Uplink and downlink almost always use different frequencies (e.g. Ku-band: ~14 GHz up, ~11-12 GHz down). Since both free-space path loss and rain attenuation increase with frequency, the (usually higher-frequency) uplink typically suffers *more* atmospheric loss than the downlink, on top of already having the weaker receiver on the far end.

---

## 3. The Decision Recipe: Green / Yellow / Red

Everything above computes a number in dB. This section turns that number into an answer. A single pass/fail cutoff (like the "C/N > 1" question from earlier) is the wrong tool, because atmospheric loss and system noise are both weather- and geometry-dependent, not fixed — the same hardware can close the link on a clear day at high elevation and fail during a rainstorm at low elevation. So the recipe evaluates the link twice — once under the best realistic conditions, once under the worst conditions you're willing to design against — and the *gap between those two results* is what actually determines the answer.

### 3.1 The core insight

Define **margin** as how far the achieved signal quality is above (or below) the minimum the waveform needs:

```
Margin (dB) = Eb/N0_achieved − Eb/N0_required
```

`Eb/N0_achieved` comes from the physical-layer chain (§3.2). `Eb/N0_required` is not a property of the dish or the satellite — it's a property of the *waveform* (modulation + coding + target bit-error-rate), supplied separately (§3.6 flags this and gives reference figures).

Compute Margin twice:

- **Margin_clear** — using the best-case atmospheric loss (clear sky, at the highest elevation angle the pass reaches). This answers: *can this link ever work, under ideal conditions?*
- **Margin_worst** — using the worst-case atmospheric loss you've decided to design against (e.g. the rain rate exceeded 0.01% of the year at that site, at the lowest elevation angle you intend to operate at). This answers: *does it keep working under the bad conditions you actually expect to encounter?*

### 3.2 Formula chain (run once per direction, twice per direction for clear/worst case)

**Step 1 — EIRP of the transmitting side**
```
EIRP(dBW) = P_t(dBW) + G_t(dBi)
```
`P_t` and `G_t` are given/published for whichever side is transmitting (satellite for downlink, ground dish for uplink).

**Step 2 — Gain of the receiving side's dish** (derivation: §1.2.1)
```
G_r(dBi) = 20·log₁₀(D) + 20·log₁₀(f) + 10·log₁₀(η) + 20·log₁₀(π×10⁹/c)
```

**Step 3 — Slant range** (needed for free-space loss; not a dish/satellite spec by itself, but computable from orbital altitude and elevation angle)
```
d = √(Re²·sin²(E) + h² + 2·h·Re) − Re·sin(E)
```
`Re` = Earth radius (6378 km), `h` = satellite altitude above the surface, `E` = elevation angle above the horizon. Evaluate at the **minimum operational elevation angle** for the worst-case run (longest, most oblique path) and at the pass's **maximum elevation** for the clear-case run (shortest, most favorable path) — or just use minimum elevation for both, which is the conservative choice.

**Step 4 — Free-space path loss** (derivation: §1.2.2)
```
L_fs(dB) = 20·log₁₀(d) + 20·log₁₀(f) + 92.45     (d in km, f in GHz)
```

**Step 5 — Atmospheric loss** (derivation: §1.2.3) — computed twice:
```
L_a,clear(dB)  = gaseous absorption only, at max elevation, clear sky
L_a,worst(dB)  = gaseous + cloud + rain attenuation, at min elevation,
                 at your target rain-rate exceedance percentile
```

**Step 6 — Received power**
```
P_r(dBW) = EIRP(dBW) + G_r(dBi) − L_fs(dB) − L_a(dB) − L_o(dB)
```

**Step 7 — Noise power** (derivation: §"noise" discussion above; linear form N = k·T_sys·B)
```
N(dBW) = 10·log₁₀(k) + 10·log₁₀(T_sys) + 10·log₁₀(B)
```
Note `T_sys` itself rises under the worst-case atmospheric run (rain and low elevation both add sky noise) — don't hold it fixed between the clear and worst-case passes.

**Step 8 — Signal quality achieved**
```
C/N(dB)      = P_r(dBW) − N(dBW)
Eb/N0(dB)    = C/N(dB) + 10·log₁₀(B / R_b)
```

**Step 9 — Margin**
```
Margin_clear = Eb/N0_achieved(clear-sky run)  − Eb/N0_required
Margin_worst = Eb/N0_achieved(worst-case run) − Eb/N0_required
```

### 3.3 The traffic light

| Result | Condition | Meaning |
|---|---|---|
| 🔴 **RED — no comms** | `Margin_clear < 0` | Fails even under the best possible conditions (clear sky, best elevation). No weather window fixes this; the hardware itself is undersized for this link. |
| 🟡 **YELLOW — maybe** | `Margin_clear ≥ 0` but `Margin_worst < 0` (typically also check `Margin_worst < ~1 dB` as a buffer for implementation losses not modeled here — aging, minor mispointing, cable degradation) | Closes in good conditions, drops out in bad weather or at low elevation. Usable, but availability is conditional — fine for opportunistic/best-effort links, risky for anything requiring guaranteed contact. |
| 🟢 **GREEN — clear comms** | `Margin_worst ≥ 0` (with the same ~1 dB implementation buffer) | Closes even under the worst conditions budgeted for. Reliable to whatever availability percentile `L_a,worst` was evaluated at. |

The 0 dB lines are hard physical thresholds (below `Eb/N0_required`, the error rate is unacceptable, full stop); the ~1 dB implementation buffer is a standard engineering convention, not physics — real hardware always loses a bit more than the idealized formulas predict, so treat `Margin_worst` between 0 and ~1 dB as YELLOW rather than a confident GREEN.

### 3.4 Combining both directions

Comms requires **both** the downlink and the uplink to close — run the entire §3.2–3.3 procedure independently for each direction (different transmitter, different receiver, usually a different frequency), then combine:

```
Overall status = the worse of (Downlink status, Uplink status),  where RED < YELLOW < GREEN
```

A GREEN downlink paired with a RED uplink is an overall RED — you'd hear the satellite perfectly and it would never hear you back. As noted in §2.3, the uplink is very often the tighter constraint (smaller receive antenna and worse noise performance on the satellite side), so don't skip it on the assumption the downlink result generalizes.

### 3.5 Reference: typical `Eb/N0_required` values

`Eb/N0_required` cannot be derived from dish or satellite hardware parameters — it depends entirely on the chosen modulation and forward-error-correction scheme, and should come from the actual modem/standard's published performance curve. For a rough first pass, typical figures for a target BER around 10⁻⁵ over an AWGN channel:

| Waveform | Approx. Eb/N0 required |
|---|---|
| Uncoded BPSK/QPSK | ~9–10 dB |
| QPSK + rate-1/2 convolutional (Viterbi) | ~4–5 dB |
| QPSK/8PSK + concatenated coding (e.g. legacy DVB-S-class) | ~5–7 dB |
| Modern LDPC/turbo-coded schemes near capacity (e.g. DVB-S2-class) | ~1–4 dB, varies strongly with code rate and constellation |

These are ballpark figures for sanity-checking, not a substitute for the specific modem's real performance table.

### 3.6 Full parameter table

| Parameter | Symbol | Units | Side | Used in step |
|---|---|---|---|---|
| Transmitter output power | `P_t` | W or dBW | Tx (sat or GS) | 1 |
| Transmit antenna gain | `G_t` | dBi | Tx (sat or GS) | 1 (or derive via dish row below if it's a dish) |
| Published/filed EIRP (if given directly) | `EIRP` | dBW | Tx (sat or GS) | 1 (shortcut, skips P_t/G_t if already known) |
| Dish diameter | `D` | m | Rx dish | 2 |
| Aperture efficiency | `η` | ratio (~0.55–0.70) | Rx dish (and Tx dish for uplink) | 2 |
| Operating frequency | `f` | GHz | Both | 2, 4, 5 |
| Orbital altitude | `h` | km | Satellite | 3 |
| Minimum operational elevation angle | `E_min` | degrees | Ground station | 3, 5 (worst case) |
| Maximum elevation angle for the pass | `E_max` | degrees | Ground station | 3, 5 (clear case) |
| Earth radius | `Re` | km (≈6378) | constant | 3 |
| Target rain-rate exceedance percentile | e.g. `R_0.01%` | mm/hr | Site climate data | 5 (worst case) |
| Rain specific-attenuation coefficients | `k`, `α` | (ITU-R P.838 tables) | frequency/polarization-dependent | 5 (worst case) |
| Integrated cloud liquid water content | — | kg/m² | Site climate data | 5 (worst case) |
| Pointing/polarization/feed loss | `L_o` | dB | Rx dish | 6 |
| System noise temperature | `T_sys` | K | Rx (dish or satellite) | 7 |
| Receiver bandwidth | `B` | Hz | Rx | 7, 8 |
| Data rate | `R_b` | bit/s | Link design | 8 |
| Boltzmann's constant | `k` | 1.38×10⁻²³ W/(Hz·K) | constant | 7 |
| Required Eb/N0 for target BER | `Eb/N0_required` | dB | Waveform/modem spec, not hardware | 9 (§3.5) |
| Implementation margin buffer | — | dB (~1 dB typical) | Engineering convention | 3.3 threshold |

Rows above the `L_o` line differ between downlink and uplink only in which side is "Tx" and which is "Rx" — run the table once with satellite-as-Tx/ground-as-Rx for the downlink, and again with ground-as-Tx/satellite-as-Rx for the uplink, per §3.4.

---

## The pattern, in one line

Both directions reduce to the same shape: **received power = transmitter's EIRP + receiver's antenna gain − every loss along the way**, worked out as a straightforward multiplication of real quantities, then converted to dB (where multiplication becomes addition) purely so a chain of five or six wildly different-sized numbers can be added and subtracted by hand instead of multiplied and divided.

---

## Appendix A — Sourcing the inputs: what the catalogues give us, and how the rest is estimated

The recipe in §3 needs roughly two dozen numbers per direction. They come from four places:

| Source | Parameters it provides |
|---|---|
| **Orbital catalogues** — the NORAD catalogue via Space-Track (OMM elements + SATCAT, the only orbit source); CelesTrak for group lists and radar cross-sections | orbital elements → altitude `h`, slant range `d`, elevation `E`, pass timing (all via SGP4); object type (Payload / R/B / Debris); radar cross-section `rcsSize`; period, apogee, perigee, inclination; owner, launch site, launch/decay dates |
| **Ground-station configuration** — the GRND STN form | dish `D`, `η`, antenna gain; `f_up`, `f_down`; Tx power / EIRP; `T_sys` / `G/T`; `L_o`; `E_min`; station altitude; bandwidth `B`; data rate `R_b`; required `Eb/N0` |
| **Site climate data** — keyed to the station's lat/lon | rain-rate exceedance percentile, integrated cloud liquid water, gaseous-absorption baseline → `L_a` |
| **Estimated for the satellite** — this appendix | downlink EIRP; downlink and uplink centre frequency; satellite receive-antenna gain; satellite noise temperature; satellite `G/T`; downlink bandwidth / data rate / required `Eb/N0` |

**Nothing in the orbital catalogues describes a satellite's radio payload.** SATCAT carries object type, a coarse size class and launch metadata — no frequency, no EIRP, no antenna or receiver data. Everything in the bottom row therefore has to be inferred.

The method throughout is **two-tier with a confidence flag**, the same pattern the EIRP enrichment already uses: a curated value where a public filing or a firm engineering convention exists, a class-typical value otherwise, and an explicit `unknown` when even the class is unclear. Every estimated quantity carries a `source` tag (`filing` / `convention` / `estimated` / `unknown`) so the solver — and the Green / Yellow / Red logic in §3.3 — can widen its margin on a guess and refuse to report GREEN on estimates alone.

### A.1 Downlink EIRP

Two tiers, produced by the ingestion-pipeline enrichment step:

- **`filing`** — a curated table keyed by constellation / operator, with values lifted from FCC Schedule S, ITU filings, GNSS ICDs and published footprint contours: Starlink Ku 38 dBW, OneWeb Ku 36, Kuiper Ka 38, GNSS L 27, Iridium-NEXT L 17, Globalstar S 20, ORBCOMM VHF 12, Planet X 13, GEO comms (SES / Intelsat / Eutelsat / Telesat) Ku ≈ 52. Matched by group membership, with a satellite-name-prefix fallback (`STARLINK-*`, `ONEWEB-*`, …) for objects that have drifted out of their group. The groups are built by the publish step (`scripts/groupRules.py`): CelesTrak's lists while CelesTrak is available (a successful fetch within 14 days), otherwise our own rules from GCAT owner codes, programmes and name prefixes. Ten groups whose rules agreed poorly with CelesTrak (among them ses, intelsat, telesat and orbcomm) have no rule and are absent while CelesTrak is unavailable; their members then reach `filing` only through the name prefix, or drop to `estimated`.
- **`estimated`** — no constellation match: the band is inferred from the object's mission class, and the EIRP read from a (band, mission-class) table — comms-GEO ≈ 50 dBW, EO-optical X-band ≈ 14, EO-radar X-band ≈ 18, weather-LEO ≈ 15, cubesat beacon ≈ 2, and so on. The class normally comes from CelesTrak's function groups (weather, cubesat, geo, …) and the orbit.
  - **GCAT class fallback.** CelesTrak's function groups have no rules of our own, so they are absent while CelesTrak is unavailable (as on the live server, which CelesTrak blocks). Only then, the publish step passes each payload's class from its GCAT entry (`enrichEirp.gcat_class`), applied only to payloads the groups place in no class. Rules, first match wins: GCAT category SS → station; mass ≤ 30 kg → amateur (payload class A) or cubesat; MET → weather-geo or weather-leo by orbit; IMG-R → eo-radar; IMG or EOSCI → eo-optical; COM in GEO → military-comms (class D) or comms-geo; COM elsewhere → comms-leo-narrow; SCI, AST or TECH → science; anything else stays unknown. The publish log says which tier it used. On DEV data (payloads in orbit) it turns 4,102 unknown into 1,261, with 4,881 estimated instead of 1,874; with CelesTrak available it is never used.
- Rocket bodies and debris are tagged `none` — they do not transmit.

About three-quarters of active payloads get a value. The standing caveat: every figure is a **boresight / filed-maximum** number, not the EIRP toward the station's actual position in a shaped or spot beam — fine for triage, not for operations.

### A.2 Downlink and uplink centre frequency

The budget needs a real frequency, not a band letter — both `L_fs` and rain attenuation scale with `f`, and X-band alone spans 8–12 GHz ≈ 3.5 dB of path-loss spread.

**Downlink:**

1. **`filing`** — exact `downlink_low` / `downlink_high` from the SatNOGS DB (crowd-sourced transmitter records). Covers the amateur / cubesat / university-smallsat / weather-satellite segment.

   **Where the figures come from.** `scripts/ingestionSatNOGS.py` stores SatNOGS's transmitter records as they are (`ingestionSatNOGS.db`); the frequencies reach the site at the **publish step** (`scripts/publishSite.py orbital`), which rebuilds `siteOrbital.db` after every SatNOGS or Space-Track run that changed something. There each transmitter is linked to a NORAD object, trying in order:
   1. its `norad_follow_id`, when that object is in the catalogue;
   2. the international designator in the TLE SatNOGS publishes under the transmitter's own number, matched to Space-Track's `objectID` — the only link for satellites launched since NORAD's 5-digit numbers ran out in July 2026, which SatNOGS carries under its own 98xxx/99xxx placeholder numbers (e.g. SatNOGS 98193, JACK-007 → 2026-229K);
   3. its own `norad_cat_id`, when that is a catalogued object.

   Transmitters that match none are dropped. Per satellite, `scripts/rfSelection.py` (`choose_rf`) then picks the main downlink and uplink (plausible 20 MHz–60 GHz, confirmed records before violating or unconfirmed ones, then active, then highest baud, then newest), and fills `dlFreqHz`, `ulFreqHz`, `dlBandwidthHz`, `rfMode`, `rfBaud`, with `rfSource = 'satnogs'`. Before the 2026-10 database refactor the frequencies were attached by `norad_cat_id` alone, so they sat on SatNOGS's 9xxxx placeholder rows instead of the real objects (384 satellites on LIVE); none do now.
2. **`convention`** — no SatNOGS record: take the mid-point of the enriched downlink band (S → 3.0 GHz, X → 10 GHz, …). Within-band error is ±1–3 dB on path loss, more on rain at Ka.
3. **`unknown`** — no band either.

**Uplink** is harder, because it is a *different* frequency from the downlink and usually in a different band (S up / X down, ~14 up / ~12 down):

1. **`filing`** — `uplink_low` / `uplink_high` from SatNOGS, present only for records typed transceiver or transponder.
2. **`convention`** — a curated per-constellation uplink band, or the standard paired Earth-to-space allocation for the downlink band (the fixed offsets in the ITU band plan), taken at mid-point.
3. **`unknown`** — otherwise. A satellite the station only needs to *receive* (a pure EO downlink) needs no uplink figure; a command uplink to an arbitrary satellite is simply not estimable without a documented transmitter.

### A.3 Satellite receive-antenna gain (`G_r,sat`)

Gain is aperture-limited by the same relation as the ground dish, `G ≈ η·(π D / λ)²`, and on a spacecraft `D` is bounded by the bus or the largest deployable. Two physical facts anchor the estimate:

- **Low frequencies are gain-capped.** A 3U cubesat with a ~0.3 m antenna at UHF (λ ≈ 0.7 m) cannot exceed ~2.5 dBi; the same aperture at S-band caps near 17 dBi.
- **A non-steered LEO satellite that must hear any station in view needs a near-hemispherical pattern.** From 600 km the Earth-to-horizon cone is ~120–140° wide, so a fixed receive antenna is 0–6 dBi. The broad beam is a deliberate design choice — it removes the need for attitude knowledge to be commandable.

Estimate by class; `rcsSize` + object type + orbit regime select the row:

| Class | Typical receive antenna | `G_r,sat` |
|---|---|---|
| Cubesat, UHF / VHF command | monopole / turnstile | 0–2 dBi |
| Smallsat, S-band command | patch | 4–8 dBi |
| GNSS | shaped Earth-coverage | ~13 dBi |
| GEO comms, Earth-coverage beam | horn | 17–20 dBi |
| Comms, spot beam | reflector / phased array | 30–40 dBi |

Confidence is ±3–6 dB for the broad-beam rows. The spot-beam row is the weak point: there the binding question is not the gain figure but **whether the beam is pointed at the station**, which no catalogue answers — flag those `estimated` with a wide margin, or `unknown`.

### A.4 Satellite system noise temperature (`T_sys,sat`)

This is **not symmetric** with the ground station's, and the reason is what each antenna looks at:

- The ground-station antenna points **up** at cold sky → antenna temperature 10–60 K.
- The satellite antenna points **down** at the warm Earth, which fills the beam → antenna temperature ≈ **290 K**.

The receiver contribution *is* loosely shared: both ends build LNAs from the same short menu of microwave transistor technologies (GaAs pHEMT, InP HEMT, SiGe), so an uncooled front end is ~50–150 K at S/X-band whichever end it sits on. But the satellite cannot cryogenically cool its receiver — no cryocooler mass or power budget — and it runs warmer thermally. So:

```
T_sys,sat  ≈  290 K (Earth-filling antenna)  +  ~150 K (uncooled LNA + feed)  ≈  400–600 K
```

Use **500 K (≈ 27 dB-K)** as the class default. It varies little between missions — the 290 K Earth dominates and swamps LNA differences — which makes it, paradoxically, easier to pin down than the ground station's own `T_sys`.

### A.5 Satellite `G/T`

Synthesised directly from A.3 and A.4:

```
G/T_sat (dB/K)  =  G_r,sat (dBi)  −  10·log₁₀(T_sys,sat)
```

| Case | `G_r,sat` | `T_sys,sat` | `G/T_sat` |
|---|---|---|---|
| Cubesat, UHF command | +2 dBi | 500 K | −25 dB/K |
| Smallsat, S-band | +6 dBi | 500 K | −21 dB/K |
| GEO, Earth-coverage | +18 dBi | 500 K | −9 dB/K |
| GEO, spot beam | +35 dBi | 500 K | +8 dB/K |

Net confidence ≈ ±3 dB. Coarse, but enough for the Green / Yellow / Red triage — and the strongly negative cubesat figures correctly predict that those uplinks need substantial ground-station EIRP to close.

### A.6 Downlink bandwidth, data rate, required `Eb/N0`

- **Bandwidth `B`** — from SatNOGS `baud` + `mode`: symbol rate × (1 + roll-off) for PSK / QPSK, Carson's rule for FM / FSK. No SatNOGS record → a class-typical occupied bandwidth.
- **Data rate `R_b`** — SatNOGS `baud` × bits-per-symbol implied by `mode` (≈ baud for BPSK / FSK / AFSK). Else class-typical.
- **Required `Eb/N0`** — `mode` gives the modulation but rarely the FEC; assign a per-mode figure assuming a typical code (uncoded BPSK/QPSK ≈ 9.6 dB, rate-½ coded ≈ 4–5 dB, modern LDPC ≈ 1–4 dB — see §3.5). Else the waveform-class default.

These three are strictly **link-design** parameters, not satellite hardware; where the scheduled contact's real waveform is known, it should override any estimate.

### A.7 Polarization

Deliberately **not** estimated per satellite. A polarization mismatch is straightforward to correct at the ground station (a switchable or auto-tracking feed), so it is carried as a fixed allowance inside `L_o` rather than as a per-satellite unknown.

### A.8 Confidence tags and how the solver uses them

| Tag | Meaning | Solver treatment |
|---|---|---|
| `filing` | from an FCC / ITU filing, an ICD, or a documented SatNOGS transmitter | nominal margin |
| `convention` | from a standard band plan, paired allocation, or mid-point rule | +1–2 dB extra margin |
| `estimated` | class-typical table value | +3–6 dB extra margin; never report GREEN on these alone |
| `unknown` | not even the class is clear | that direction cannot be evaluated — report it as such, not as RED |

### A.9 Known limitations

- **Steered high-gain antennas** — the A.3 gain table is meaningless when the real question is beam pointing; these resolve to `estimated` with a wide margin at best.
- **Coverage** — SatNOGS lists ~1.5–2.5 k satellites (amateur, cubesat, university, some commercial smallsat, weather). Large commercial GEO / LEO comms at per-satellite granularity, military and most operational government payloads are absent; for those, only the curated constellation tables and the class fallbacks apply.
- **Boresight figures** — estimated EIRP and `G/T` are on-axis / filed-maximum, not toward the station's actual position in a shaped or spot beam.
- **Estimated frequencies** — a band mid-point can be a few dB off on path loss and more on rain; treat any `convention`-tagged frequency result as indicative, not operational.
