# GRND STN Form — Redesign for the Link-Budget Algorithm

Design for the GS OPS → **GRND STN** form so it captures exactly the ground-station
inputs the `satellite_link_budget_2.md` algorithm consumes, no more and no less.

## Principles

- **Five groups, ≤ 4 fields each** — laid out as five short columns in the fixed-height control panel.
- **Derive-or-override** — where a figure can be computed from more primitive inputs
  (antenna gain, EIRP, G/T), the form shows the calculated value live and lets the user
  switch a toggle to type their own instead.
- Only **ground-station** parameters live here. Satellite figures, site climate data,
  and physical constants are pulled in elsewhere (see *Inputs not in this form*).
- `camelCase` keys, acronyms capitalised (`groundStationEIRPdBW`, `minElevationDeg`).

## Panel layout

```
┌ ANTENNA & GAIN ──┐ ┌ UPLINK  (GS Tx) ─┐ ┌ DOWNLINK (GS Rx) ┐ ┌ LOSSES & GEOMETRY┐ ┌ LINK / WAVEFORM ─┐
│ Dish diameter    │ │ Uplink frequency │ │ Downlink freq.   │ │ Other losses Lₒ  │ │ Modulation+coding│
│ Aperture effcy.  │ │ Drive: Pwr / EIRP│ │ FoM: Tsys / G÷T  │ │ Polarization     │ │ Required Eb/N0   │
│ Gain: Calc / Man │ │ Tx output power  │ │ System noise temp│ │ Min. elevation   │ │ Rx bandwidth     │
│ Antenna gain     │ │ Ground stn EIRP  │ │ Ground stn G/T   │ │ Station altitude │ │ Data rate        │
└──────────────────┘ └──────────────────┘ └──────────────────┘ └──────────────────┘ └──────────────────┘
     [ SAVE ]   [ RESET → 3 m S-BAND DEFAULTS ]        · derived values shown live beneath each group ·
```

---

## Group 1 — Antenna & gain

| Field | Key | Unit | Range / default | Behaviour |
|---|---|---|---|---|
| Dish diameter | `dishDiameterM` | m | 0.5 – 30 | Required when *Gain source = Calculated* |
| Aperture efficiency | `apertureEfficiency` | ratio | 0.40 – 0.80 · def **0.60** | Feed taper, spillover, blockage, surface error |
| Gain source | `gainSource` | — | `Calculated` (def) / `Manual` | Radio toggle |
| Antenna gain | `antennaGainDBi` | dBi | 5 – 75 | Read-only when *Calculated* (shows G at both f_up and f_down); editable when *Manual* |

**Derived:** `antennaGainDBi = 20·log₁₀(D) + 20·log₁₀(f) + 10·log₁₀(η) + 20.4`
(f in GHz; evaluated at `downlinkFreqGHz` → G_rx and at `uplinkFreqGHz` → G_tx).

---

## Group 2 — Uplink (ground station transmits)

| Field | Key | Unit | Range / default | Behaviour |
|---|---|---|---|---|
| Uplink centre frequency | `uplinkFreqGHz` | GHz | 0.1 – 50 | Also sets the band label |
| Drive source | `txDriveSource` | — | `TxPower` (def) / `EIRP` | Radio toggle |
| Tx output power | `txPowerW` | W | 1 – 20 000 | Used when *Drive = TxPower* |
| Ground-station EIRP | `groundStationEIRPdBW` | dBW | 10 – 110 | Read-only when *Drive = TxPower*; editable when *Drive = EIRP* |

**Derived:** `groundStationEIRPdBW = 10·log₁₀(txPowerW) + G_tx`.

---

## Group 3 — Downlink (ground station receives)

| Field | Key | Unit | Range / default | Behaviour |
|---|---|---|---|---|
| Downlink centre frequency | `downlinkFreqGHz` | GHz | 0.1 – 50 | Also sets the band label |
| Figure-of-merit source | `rxFomSource` | — | `NoiseTemp` (def) / `GOverT` | Radio toggle |
| System noise temperature | `systemNoiseTempK` | K | 20 – 600 | Used when *FoM = NoiseTemp*; sky + feed loss + LNA combined |
| Ground-station G/T | `groundStationGOverTdBK` | dB/K | −10 – 40 | Read-only when *FoM = NoiseTemp*; editable when *FoM = GOverT* |

**Derived:** `groundStationGOverTdBK = G_rx − 10·log₁₀(systemNoiseTempK)`.

---

## Group 4 — Losses, polarization & geometry

| Field | Key | Unit | Range / default | Notes |
|---|---|---|---|---|
| Other losses Lₒ | `otherLossesDB` | dB | 0 – 6 · def **1.0** | Feed/cable + pointing error + polarization mismatch |
| Polarization | `polarization` | — | `RHCP` / `LHCP` / `LinV` / `LinH` / `AutoTrack` | Refines the polarization term of Lₒ |
| Minimum elevation angle | `minElevationDeg` | deg | 0 – 30 · def **10** | Horizon mask → worst-case slant range |
| Station altitude | `stationAltitudeM` | m | −400 – 5000 · def **0** | Optional; tightens slant range |

Station **latitude / longitude** are *not* entered here — they come from **GS LOCN**.

---

## Group 5 — Link / waveform  *(per contact, not station hardware)*

| Field | Key | Unit | Range / default | Behaviour |
|---|---|---|---|---|
| Modulation & coding | `modCod` | — | preset dropdown | Selecting a preset fills `requiredEbN0dB` |
| Required Eb/N0 | `requiredEbN0dB` | dB | 0 – 15 | Auto from `modCod`; editable for a real modem curve |
| Rx / channel bandwidth | `receiverBandwidthHz` | Hz | 1e3 – 5e8 | Noise power + Eb/N0 conversion |
| Data rate | `dataRateBps` | bit/s | 1e2 – 1e9 | Eb/N0 conversion |

`modCod` presets → `requiredEbN0dB` (BER ≈ 1e-5, AWGN): QPSK uncoded ≈ 9.6 · QPSK r½ ≈ 4.5 ·
8PSK r⅔ ≈ 6.5 · DVB-S2-class LDPC ≈ 1–4.

---

## Derived values (shown live, never stored as primary)

| Value | Formula | Source fields |
|---|---|---|
| G_rx | `20log₁₀(D)+20log₁₀(f_down)+10log₁₀(η)+20.4` | Group 1 + `downlinkFreqGHz` |
| G_tx | `20log₁₀(D)+20log₁₀(f_up)+10log₁₀(η)+20.4` | Group 1 + `uplinkFreqGHz` |
| `groundStationEIRPdBW` | `10log₁₀(txPowerW) + G_tx` | Group 2 |
| `groundStationGOverTdBK` | `G_rx − 10log₁₀(systemNoiseTempK)` | Group 3 |

## Inputs the algorithm needs but **not** from this form

| Input | Source |
|---|---|
| Station latitude / longitude | GS LOCN (`observerLocation`) |
| Rain-rate exceedance, cloud liquid water, ITU k/α | Climate dataset keyed to the station location |
| Satellite EIRP, altitude, Rx antenna gain, T_sys, bandwidth | `orbital_objects` DB, per target |
| Implementation-margin buffer (≈ 1 dB), Boltzmann's constant, Earth radius | Fixed constants in the solver |

## Not part of the link budget (keep only if wanted for tracking feasibility)

`HPBW`, `SLEW RATE`, azimuth cable-wrap limits — mount/tracking capability, not signal
closure. If retained, put them in a separate **MOUNT** group rather than mixing them in here.

---

## 3 m S-band default set (RESET button)

| Key | Value | | Key | Value |
|---|---|---|---|---|
| `dishDiameterM` | 3 | | `rxFomSource` | `NoiseTemp` |
| `apertureEfficiency` | 0.60 | | `systemNoiseTempK` | 150 → G/T ≈ 13 dB/K |
| `gainSource` | `Calculated` → ≈ 34.8 dBi | | `otherLossesDB` | 1.0 |
| `uplinkFreqGHz` | 2.09 | | `polarization` | `RHCP` |
| `downlinkFreqGHz` | 2.25  (band label **S**) | | `minElevationDeg` | 10 |
| `txDriveSource` | `TxPower` | | `stationAltitudeM` | 0 |
| `txPowerW` | 100 → EIRP ≈ 55 dBW | | `modCod` | `QPSK r1/2` |
| | | | `requiredEbN0dB` | 4.5 |
| | | | `receiverBandwidthHz` | 2e6 |
| | | | `dataRateBps` | 1e6 |

## Validation & persistence

- Numeric-only entry with range checks on **SAVE** (existing `gsSanitizeNumeric` behaviour).
- `Calculated` / `TxPower` / `NoiseTemp` toggles require their primitive fields and grey out
  the manual field; `Manual` / `EIRP` / `GOverT` require the manual field and leave the
  primitives as optional reference.
- Persist a superset of today's `groundStationConfig` in `localStorage`; migrate the old
  keys (`antGain`→`antennaGainDBi`, `eirpW`→`txPowerW`, `minElev`→`minElevationDeg`, `band`
  is now derived from the two frequencies).
