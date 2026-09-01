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
