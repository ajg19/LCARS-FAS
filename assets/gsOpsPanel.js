/* ==========================================================================
   GS OPS PANEL

   Ground-station operations. Wraps registerLocationMapPanel()
   (assets/locationMapPanel.js) -- same shared base map + graticule +
   day/night terminator + user-location + CITY LBL behaviour as the EO
   panel -- and adds GRND STN (control-panel slot 3, directly below
   GS LOCN) and VIS NOW (slot 4) buttons. GRND STN opens a ground-station
   configuration form in #default, mirroring the GS LOCN / USR LOCN
   entry-form pattern.

   Lazily loaded the first time GS OPS is opened; openGsOpsSection() in
   lcars.js loads mapCore.js, onOrbitPanel.js and locationMapPanel.js
   first.
   ========================================================================== */

// Modulation + coding presets for the LINK / WAVEFORM group. `ebN0` is the
// approximate Eb/N0 (dB) for ~1e-5 BER over AWGN -- a first-pass figure,
// not a substitute for a real modem performance curve. Picking a preset
// fills REQ Eb/N0; editing that field switches the preset to Custom.
const GS_MODCOD_PRESETS = [
    { value: 'QPSK', label: 'QPSK uncoded', ebN0: 9.6 },
    { value: 'QPSK12', label: 'QPSK r1/2', ebN0: 4.5 },
    { value: 'QPSK34', label: 'QPSK r3/4', ebN0: 5.5 },
    { value: '8PSK23', label: '8PSK r2/3', ebN0: 6.6 },
    { value: 'LDPC', label: 'DVB-S2 LDPC', ebN0: 3.0 },
    { value: 'CUSTOM', label: 'Custom', ebN0: null },
];

const GS_POLARIZATIONS = [
    { value: 'RHCP', label: 'RHCP' },
    { value: 'LHCP', label: 'LHCP' },
    { value: 'LinV', label: 'Linear V' },
    { value: 'LinH', label: 'Linear H' },
    { value: 'AutoTrack', label: 'Auto-track' },
];

// IEEE band letter for a frequency in GHz -- shown in brackets after the
// unit on the UL/DL FREQ fields. `max` is the upper edge (exclusive);
// at or above the last edge reads as the final band.
const GS_FREQ_BANDS = [
    { max: 0.3, label: 'VHF' },
    { max: 1, label: 'UHF' },
    { max: 2, label: 'L' },
    { max: 4, label: 'S' },
    { max: 8, label: 'C' },
    { max: 12, label: 'X' },
    { max: 18, label: 'Ku' },
    { max: 27, label: 'K' },
    { max: 40, label: 'Ka' },
    { max: Infinity, label: 'Q/V' },
];

function gsFreqBandLabel(freqGHz) {
    if (!Number.isFinite(freqGHz) || freqGHz <= 0) {
        return '';
    }
    return (GS_FREQ_BANDS.find((b) => freqGHz < b.max) || {}).label || '';
}

// Hover text (title=) for the two mode toggles and the two selects; the
// per-field numeric hints live on GS_NUMERIC_FIELDS. All kept free of
// double quotes / angle brackets so they drop into an attribute as-is.
const GS_HINT = {
    gainMode: 'Gain source. CALC derives the antenna gain from dish diameter, aperture '
        + 'efficiency and frequency (shown as Rx / Tx). MANUAL lets you enter a measured '
        + 'gain instead, applied to both directions.',
    txDriveMode: 'Transmit drive. CALC derives the uplink EIRP from the transmitter power '
        + 'and the Tx antenna gain. MANUAL lets you enter a coordinated or licence-filed '
        + 'EIRP directly.',
    rxFomMode: 'Receive figure of merit. CALC derives G/T from the Rx antenna gain and the '
        + 'system noise temperature. MANUAL lets you enter a measured station G/T directly.',
    polarization: 'Polarization. The sense of the station receive and transmit polarization: '
        + 'right- or left-hand circular (RHCP / LHCP), or linear vertical or horizontal. A '
        + 'mismatch with the satellite (e.g. an RHCP station against an LHCP downlink) is a '
        + 'large loss folded into Lo; Auto-track follows the satellite polarization.',
    modCod: 'Modulation and coding. The modulation scheme plus its forward-error-correction '
        + 'rate. Selecting a preset fills REQ Eb/N0 with a typical value for a 1e-5 bit '
        + 'error rate; choose Custom to set your own.',
};

// Antenna-gain constant: 20 log10(pi x 1e9 / c) folded with the pi term,
// so G(dBi) = 20 log10(D_m) + 20 log10(f_GHz) + 10 log10(eta) + this.
const GS_GAIN_CONST_DB = 20.41;

function gsDishGainDBi(diameterM, efficiency, freqGHz) {
    if (![diameterM, efficiency, freqGHz].every((v) => Number.isFinite(v) && v > 0)) {
        return null;
    }
    return 20 * Math.log10(diameterM) + 20 * Math.log10(freqGHz)
        + 10 * Math.log10(efficiency) + GS_GAIN_CONST_DB;
}

// One row per savable numeric field. `grp` places it in a column
// (antenna / uplink / downlink / geom / link); `needs(cfg)` -- when
// present -- gates whether the field is shown-active and validated for a
// given toggle state; `derived` marks a field that is computed (and
// read-only) unless its own `needs` says the user chose to type it;
// `thousands` groups the value with separators; `signed` permits a
// leading minus. Bounds live here only, feeding both markup and the
// validate/collect loop in saveGroundStation().
const GS_NUMERIC_FIELDS = [
    // --- Antenna & gain ---
    {
        id: 'gs-dish', key: 'dishDiameterM', label: 'DISH DIA', unit: 'm', grp: 'antenna',
        min: 0.3, max: 30, needs: (c) => c.gainMode === 'calc',
        hint: 'Dish diameter. The physical diameter of the main reflector -- it sets both '
            + 'the antenna gain and the beamwidth (gain rises about 6 dB each time you '
            + 'double it). Typical: 0.5-1.2 m for a cubesat or UHF station, 3-7 m for '
            + 'S/X-band tracking, 12-35 m for deep-space work.',
    },
    {
        id: 'gs-eff', key: 'apertureEfficiency', label: 'APERT EFF', unit: '', grp: 'antenna',
        min: 0.3, max: 0.85, needs: (c) => c.gainMode === 'calc',
        hint: 'Aperture efficiency. The fraction of the physical dish area that is '
            + 'electromagnetically effective, after feed spillover, illumination taper, '
            + 'aperture blockage and rms surface error. A well-built reflector is 0.55 to '
            + '0.70. Enter it as a decimal, not a percentage.',
    },
    {
        id: 'gs-gain', key: 'antennaGainManualDBi', label: 'ANT GAIN', unit: 'dBi', grp: 'antenna',
        min: 5, max: 75, derived: true, needs: (c) => c.gainMode === 'manual',
        hint: 'Antenna gain. Peak gain of the dish over an isotropic radiator, in dBi. On '
            + 'CALC it is computed from dish diameter, aperture efficiency and frequency '
            + 'and shown as Rx / Tx (they differ because the uplink and downlink '
            + 'frequencies differ). Switch the dropdown to MANUAL to type a measured '
            + 'figure, applied to both directions.',
    },
    // --- Uplink (ground station transmits) ---
    {
        id: 'gs-ulf', key: 'uplinkFreqGHz', label: 'UL FREQ', unit: 'GHz', grp: 'uplink',
        min: 0.03, max: 60,
        hint: 'Uplink frequency. The centre frequency the ground station transmits on '
            + '(Earth to space), in GHz. Usually different from, and often higher than, '
            + 'the downlink -- e.g. S-band 2.02-2.12 GHz for command, X-band about 7.19 '
            + 'GHz, Ku-band about 14 GHz. The band letter shown in the box is derived '
            + 'from this value.',
    },
    {
        id: 'gs-txp', key: 'txPowerW', label: 'TX PWR', unit: 'W', grp: 'uplink',
        min: 0.1, max: 20000, thousands: true, needs: (c) => c.txDriveMode === 'power',
        hint: 'Transmit power. Transmitter output power delivered to the feed, before '
            + 'antenna gain, in watts. Combined with the Tx antenna gain it gives the '
            + 'station EIRP. Typical: 1-20 W for a cubesat ground station, 100 W to 3 kW '
            + 'for an S/X-band command uplink.',
    },
    {
        id: 'gs-eirp', key: 'eirpManualDBW', label: 'EIRP', unit: 'dBW', grp: 'uplink',
        min: 0, max: 110, derived: true, needs: (c) => c.txDriveMode === 'eirp',
        hint: 'Effective Isotropic Radiated Power. The power an isotropic antenna would '
            + 'need to match the station on-axis signal -- that is, transmit power plus Tx '
            + 'antenna gain minus feed loss, in dBW. On CALC it is computed from those; '
            + 'switch to MANUAL to enter a coordinated or licence-filed figure directly.',
    },
    // --- Downlink (ground station receives) ---
    {
        id: 'gs-dlf', key: 'downlinkFreqGHz', label: 'DL FREQ', unit: 'GHz', grp: 'downlink',
        min: 0.03, max: 60,
        hint: 'Downlink frequency. The centre frequency the ground station receives on '
            + '(space to Earth), in GHz. It sets the receive dish gain, the free-space '
            + 'path loss and the rain attenuation. Examples: S-band 2.2-2.3 GHz, X-band '
            + '8.0-8.4 GHz, Ka-band about 26 GHz. The band letter shown in the box is '
            + 'derived from this value.',
    },
    {
        id: 'gs-tsys', key: 'systemNoiseTempK', label: 'SYS TEMP', unit: 'K', grp: 'downlink',
        min: 20, max: 600, needs: (c) => c.rxFomMode === 'tsys',
        hint: 'System noise temperature. The whole receive chain expressed as an '
            + 'equivalent noise temperature in kelvin, referred to the antenna: sky and '
            + 'background noise, plus feed and line loss, plus LNA noise figure, combined. '
            + 'Lower is better. Typical: 60-120 K for a cooled X-band system, 120-250 K '
            + 'for an ambient S-band one.',
    },
    {
        id: 'gs-gt', key: 'gOverTManualDBK', label: 'G/T', unit: 'dB/K', grp: 'downlink',
        min: -10, max: 45, derived: true, signed: true, needs: (c) => c.rxFomMode === 'gt',
        hint: 'Gain-to-noise-temperature ratio. The receive figure of merit: antenna gain '
            + 'minus 10*log10(system noise temperature), in dB/K -- the single number for '
            + 'how weak a signal the station can pull out of the noise. On CALC it is '
            + 'computed from Rx gain and system temperature; switch to MANUAL to enter a '
            + 'measured value (it can be negative for a small or warm setup).',
    },
    // --- Losses & geometry ---
    {
        id: 'gs-loss', key: 'otherLossesDB', label: 'LOSS Lo', unit: 'dB', grp: 'geom',
        min: 0, max: 6,
        hint: 'Other losses (Lo). Fixed losses that are neither path nor atmospheric: '
            + 'feed, waveguide and cable loss, radome loss, antenna pointing error, and '
            + 'polarization mismatch, totalled in dB. A well-aligned station is a few '
            + 'tenths to about 1 dB; add margin for a radome or imperfect tracking.',
    },
    {
        id: 'gs-minel', key: 'minElevationDeg', label: 'MIN ELEV', unit: 'deg', grp: 'geom',
        min: 0, max: 30,
        hint: 'Minimum elevation angle. The lowest elevation above the horizon at which '
            + 'the station will work a pass -- its horizon mask, in degrees. It is also '
            + 'the worst-case link geometry: longest slant range and the most atmosphere '
            + 'to punch through. Typical 5-10 deg; higher where terrain or buildings '
            + 'obstruct.',
    },
    {
        id: 'gs-alt', key: 'stationAltitudeM', label: 'STN ALT', unit: 'm', grp: 'geom',
        min: 0, max: 5000,
        hint: 'Station altitude. Height of the station above mean sea level, in metres. '
            + 'Minor effect: it slightly extends the geometric horizon and shortens the '
            + 'slant range to the satellite. Leave at 0 if unknown or near sea level.',
    },
    // --- Link / waveform (per contact, not station hardware) ---
    {
        id: 'gs-ebn0', key: 'requiredEbN0DB', label: 'REQ Eb/N0', unit: 'dB', grp: 'link',
        min: 0, max: 16,
        hint: 'Required Eb/N0 (energy per bit divided by noise power spectral density). '
            + 'The Eb/N0 the waveform needs to reach its target bit error rate, in dB -- a '
            + 'property of the modulation and forward-error-correction, not of the '
            + 'hardware. Pick a MOD/COD preset to fill it, or type a figure from the '
            + 'modem performance curve.',
    },
    {
        id: 'gs-bw', key: 'rxBandwidthHz', label: 'RX BW', unit: 'Hz', grp: 'link',
        min: 1e3, max: 5e8, thousands: true,
        hint: 'Receiver bandwidth. The receiver noise (channel) bandwidth in hertz. It '
            + 'sets the noise power (N = k * Tsys * B) and the conversion from '
            + 'carrier-to-noise ratio to Eb/N0. Roughly the occupied bandwidth of the '
            + 'signal being received.',
    },
    {
        id: 'gs-rate', key: 'dataRateBps', label: 'DATA RATE', unit: 'bit/s', grp: 'link',
        min: 100, max: 1e9, thousands: true,
        hint: 'Data rate. The link information bit rate, in bits per second. It converts '
            + 'carrier-to-noise ratio to Eb/N0 via Eb/N0 = C/N + 10*log10(B / Rb). Set by '
            + 'the mission or the scheduled contact, not by the station hardware.',
    },
];

// Shown in the GRND STN form until the user saves their own -- a
// representative 3 m S-band tracking dish at 60% efficiency (~35 dBi,
// ~13 dB/K G/T against a 150 K system), ~100 W transmit (~54 dBW EIRP),
// a 10 deg mask, and a QPSK r1/2 waveform. Held in memory only -- SAVE
// is what persists a config.
const GS_DEFAULTS = {
    gainMode: 'calc',
    dishDiameterM: 3,
    apertureEfficiency: 0.6,
    antennaGainManualDBi: 35,
    uplinkFreqGHz: 2.09,
    txDriveMode: 'power',
    txPowerW: 100,
    eirpManualDBW: 54,
    downlinkFreqGHz: 2.25,
    rxFomMode: 'tsys',
    systemNoiseTempK: 150,
    gOverTManualDBK: 13,
    otherLossesDB: 1,
    polarization: 'RHCP',
    minElevationDeg: 10,
    stationAltitudeM: 0,
    modCod: 'QPSK12',
    requiredEbN0DB: 4.5,
    rxBandwidthHz: 2000000,
    dataRateBps: 1000000,
};

const GROUND_STATION_STORAGE_KEY = 'groundStationConfig';

// Bring a stored config up to the current shape. The pre-link-budget form
// stored { band, gainDbi, hpbwDeg, eirpW, minElevationDeg, slewRateDegPerSec };
// carry across what still maps (elevation mask, and the old gain / EIRP as
// manual-mode entries) and let the rest fall back to defaults.
function migrateGroundStationConfig(raw) {
    if (!raw || typeof raw !== 'object') {
        return null;
    }
    if (raw.gainMode) {
        return raw;
    }
    const out = { ...GS_DEFAULTS };
    if (Number.isFinite(raw.minElevationDeg)) {
        out.minElevationDeg = raw.minElevationDeg;
    }
    if (Number.isFinite(raw.gainDbi)) {
        out.gainMode = 'manual';
        out.antennaGainManualDBi = raw.gainDbi;
    }
    if (Number.isFinite(raw.eirpW) && raw.eirpW > 0) {
        out.txDriveMode = 'eirp';
        out.eirpManualDBW = Number((10 * Math.log10(raw.eirpW)).toFixed(1));
    }
    return out;
}

function loadGroundStationConfig() {
    try {
        const raw = localStorage.getItem(GROUND_STATION_STORAGE_KEY);
        return raw ? migrateGroundStationConfig(JSON.parse(raw)) : null;
    } catch (error) {
        console.error('Could not read ground station config from localStorage:', error);
        return null;
    }
}

function saveGroundStationConfig(config) {
    try {
        localStorage.setItem(GROUND_STATION_STORAGE_KEY, JSON.stringify(config));
    } catch (error) {
        console.error('Could not save ground station config to localStorage:', error);
    }
}

// Loaded once at script startup, same pattern as observerLocation. Falls
// back to the 3 m S-band defaults so the form -- and VISIBLE NOW's
// elevation mask -- have sensible values before the user ever opens
// GRND STN; SAVE replaces this with the entered config and persists it.
let groundStationConfig = loadGroundStationConfig() || { ...GS_DEFAULTS };

// Set by the GRND STN button each time it opens the form (see the
// registerLocationMapPanel() call below): the location-map panel's own
// renderDefaultArea, which empties #default and re-centres the map. The
// form's close paths (toggle-shut, successful SAVE) call it to get back
// to the section's resting state.
let groundStationFormRestingRenderer = null;

// Working copy of the config while the form is open -- seeded from
// groundStationConfig on open, updated in place as the mode toggles are
// clicked (so a re-render keeps unsaved edits), and read by SAVE.
let groundStationFormState = null;

// Wired to every numeric field's oninput -- strips anything that isn't a
// digit or the first decimal point as it's typed, so the field can only
// ever hold a plain non-negative number (no letters, signs, exponents, or
// a second dot even via paste; any thousands commas from a grouped field
// are dropped while editing and re-applied on blur). Also clears any
// stale .invalid flag. The value is only reassigned when sanitising
// actually changed something, to keep the caret steady on ordinary digit
// entry.
function gsSanitizeNumeric(input) {
    let cleaned = input.value.replace(/[^0-9.]/g, '');
    const firstDot = cleaned.indexOf('.');
    if (firstDot !== -1) {
        cleaned = cleaned.slice(0, firstDot + 1) + cleaned.slice(firstDot + 1).replace(/\./g, '');
    }
    if (cleaned !== input.value) {
        input.value = cleaned;
    }
    input.classList.remove('invalid');
}

// As gsSanitizeNumeric, but keeps a single leading minus -- for G/T,
// which can be negative for a small/warm station.
function gsSanitizeSignedNumeric(input) {
    let cleaned = input.value.replace(/[^0-9.\-]/g, '').replace(/(?!^)-/g, '');
    const firstDot = cleaned.indexOf('.');
    if (firstDot !== -1) {
        cleaned = cleaned.slice(0, firstDot + 1) + cleaned.slice(firstDot + 1).replace(/\./g, '');
    }
    if (cleaned !== input.value) {
        input.value = cleaned;
    }
    input.classList.remove('invalid');
}

// Wired to a grouped field's (EIRP) onblur -- re-displays the entered
// number with thousands separators. parseFloat ignores the commas it
// already contains from a previous blur; a non-numeric / empty value is
// left untouched for saveGroundStation() to flag.
function gsGroupOnBlur(input) {
    const value = parseFloat(input.value.replace(/[\s,]/g, ''));
    if (Number.isFinite(value)) {
        input.value = value.toLocaleString('en-GB', { maximumFractionDigits: 6 });
    }
}

// Every value the four derived read-outs need, computed from a config
// (partial is fine). A figure is null when its inputs are missing or the
// user has switched that group to manual entry.
function gsComputeDerived(c) {
    let gRx = null;
    let gTx = null;
    if (c.gainMode === 'manual') {
        gRx = Number.isFinite(c.antennaGainManualDBi) ? c.antennaGainManualDBi : null;
        gTx = gRx;
    } else {
        gRx = gsDishGainDBi(c.dishDiameterM, c.apertureEfficiency, c.downlinkFreqGHz);
        gTx = gsDishGainDBi(c.dishDiameterM, c.apertureEfficiency, c.uplinkFreqGHz);
    }
    let eirp = null;
    if (c.txDriveMode === 'eirp') {
        eirp = Number.isFinite(c.eirpManualDBW) ? c.eirpManualDBW : null;
    } else if (Number.isFinite(c.txPowerW) && c.txPowerW > 0 && gTx != null) {
        eirp = 10 * Math.log10(c.txPowerW) + gTx;
    }
    let gt = null;
    if (c.rxFomMode === 'gt') {
        gt = Number.isFinite(c.gOverTManualDBK) ? c.gOverTManualDBK : null;
    } else if (gRx != null && Number.isFinite(c.systemNoiseTempK) && c.systemNoiseTempK > 0) {
        gt = gRx - 10 * Math.log10(c.systemNoiseTempK);
    }
    return { gRxDBi: gRx, gTxDBi: gTx, eirpDBW: eirp, gOverTDBK: gt };
}

// Scrape the currently-rendered form into a partial config -- numeric
// fields (commas/space stripped), plus the two selects. Mode toggles
// aren't inputs; they live on groundStationFormState.
function gsReadForm() {
    const out = {};
    GS_NUMERIC_FIELDS.forEach((f) => {
        const el = document.getElementById(f.id);
        if (!el || el.readOnly || el.value.trim() === '') {
            return;
        }
        const value = parseFloat(el.value.replace(/[\s,]/g, ''));
        if (Number.isFinite(value)) {
            out[f.key] = value;
        }
    });
    ['gainMode', 'txDriveMode', 'rxFomMode'].forEach((k) => {
        const el = document.getElementById(`gs-${k}`);
        if (el) {
            out[k] = el.value;
        }
    });
    const pol = document.getElementById('gs-pol');
    if (pol) {
        out.polarization = pol.value;
    }
    const modCod = document.getElementById('gs-modcod');
    if (modCod) {
        out.modCod = modCod.value;
    }
    return out;
}

// Refresh the derived read-only inputs from whatever is in the form + the
// current mode dropdowns. Only writes a derived <input> when that field is
// in its computed mode, so a manual entry is never clobbered.
function gsRefreshDerived() {
    const c = { ...(groundStationFormState || {}), ...gsReadForm() };
    const d = gsComputeDerived(c);
    if (c.gainMode === 'calc') {
        const el = document.getElementById('gs-gain');
        if (el) {
            el.value = d.gRxDBi != null ? `${d.gRxDBi.toFixed(1)}/${d.gTxDBi.toFixed(1)}` : '—';
        }
    }
    if (c.txDriveMode === 'power') {
        const el = document.getElementById('gs-eirp');
        if (el) {
            el.value = d.eirpDBW != null ? d.eirpDBW.toFixed(1) : '—';
        }
    }
    if (c.rxFomMode === 'tsys') {
        const el = document.getElementById('gs-gt');
        if (el) {
            el.value = d.gOverTDBK != null ? d.gOverTDBK.toFixed(1) : '—';
        }
    }
    const ulBand = gsFreqBandLabel(c.uplinkFreqGHz);
    const dlBand = gsFreqBandLabel(c.downlinkFreqGHz);
    const ulEl = document.getElementById('gs-ulf-band');
    const dlEl = document.getElementById('gs-dlf-band');
    if (ulEl) {
        ulEl.textContent = ulBand ? ` (${ulBand})` : '';
    }
    if (dlEl) {
        dlEl.textContent = dlBand ? ` (${dlBand})` : '';
    }
}

// Enter in any field advances focus to the next one, like Tab: DOM order
// over the enabled inputs / selects / buttons (derived read-only fields
// carry tabindex=-1 and are skipped), wrapping from the last back to the
// first. Wired to every field's onkeydown.
function gsFocusNextField(current) {
    const form = document.getElementById('ground-station-form');
    if (!form) {
        return;
    }
    const fields = Array.from(form.querySelectorAll(
        'input:not([readonly]):not([tabindex="-1"]), select, button'
    ));
    const i = fields.indexOf(current);
    if (i === -1) {
        return;
    }
    const next = fields[(i + 1) % fields.length];
    next.focus();
    if (typeof next.select === 'function') {
        next.select();
    }
}

// oninput for every editable numeric field: sanitise, keep MOD/COD in
// sync when Eb/N0 is hand-edited, then recompute the derived read-outs.
function gsOnFieldInput(el) {
    if (el.dataset.signed) {
        gsSanitizeSignedNumeric(el);
    } else {
        gsSanitizeNumeric(el);
    }
    if (el.id === 'gs-ebn0') {
        const sel = document.getElementById('gs-modcod');
        if (sel) {
            sel.value = 'CUSTOM';
        }
    }
    gsRefreshDerived();
}

function gsOnModCodChange(sel) {
    const preset = GS_MODCOD_PRESETS.find((p) => p.value === sel.value);
    const el = document.getElementById('gs-ebn0');
    if (preset && preset.ebN0 != null && el) {
        el.value = preset.ebN0;
        el.classList.remove('invalid');
    }
    gsRefreshDerived();
}

// Flip a mode toggle (gainMode / txDriveMode / rxFomMode). Capture any
// unsaved edits first, then re-render the whole form from the new state.
function gsSetMode(modeKey, value) {
    groundStationFormState = { ...groundStationFormState, ...gsReadForm(), [modeKey]: value };
    gsRenderFormInto();
}

// Row 1 of the Antenna / Uplink / Downlink groups: a dropdown that picks
// the derive-or-enter mode. Changing it re-renders the form (gsSetMode).
function gsModeRow(labelText, hint, modeKey, current, options) {
    const opts = options.map((o) =>
        `<option value="${o.value}"${o.value === current ? ' selected' : ''}>${o.label}</option>`).join('');
    return `<label for="gs-${modeKey}" title="${hint}">${labelText}</label>`
        + `<select id="gs-${modeKey}" class="location-input" title="${hint}"`
        + ` onchange="gsSetMode('${modeKey}', this.value)"`
        + ` onkeydown="if (event.key === 'Enter') { event.preventDefault(); gsFocusNextField(this); }">${opts}</select>`;
}

function gsNumericRow(f, cfg) {
    const computed = f.derived && (!f.needs || !f.needs(cfg));
    // A non-derived field its toggle has switched out of use (dish/eff in
    // MAN gain mode, Tx power in EIRP mode, sys temp in G/T mode): still
    // shown and editable so a toggle-back is seamless, just dimmed.
    const inactive = !computed && f.needs && !f.needs(cfg);
    let value = '';
    if (!computed && cfg[f.key] != null) {
        value = f.thousands
            ? Number(cfg[f.key]).toLocaleString('en-GB', { maximumFractionDigits: 6 })
            : cfg[f.key];
    }
    const cls = `location-input${computed ? ' gs-derived-input' : ''}${inactive ? ' gs-inactive' : ''}`;
    const attrs = computed
        ? 'readonly tabindex="-1"'
        : `oninput="gsOnFieldInput(this)"${f.thousands ? ' onblur="gsGroupOnBlur(this)"' : ''}`
            + `${f.signed ? ' data-signed="1"' : ''}`
            + ` onkeydown="if (event.key === 'Enter') { event.preventDefault(); gsFocusNextField(this); }"`;
    // UL/DL FREQ carry the derived IEEE band letter in brackets after the
    // unit, inside the box (e.g. "GHz (S)"); gsRefreshDerived() fills it.
    const bandSuffix = f.key === 'uplinkFreqGHz'
        ? '<span id="gs-ulf-band"></span>'
        : f.key === 'downlinkFreqGHz'
            ? '<span id="gs-dlf-band"></span>'
            : '';
    return `
        <label for="${f.id}" title="${f.hint}">${f.label}</label>
        <span class="gs-field">
            <span class="gs-inbox">
                <input type="text" inputmode="decimal" autocomplete="off" id="${f.id}" class="${cls}"
                    title="${f.hint}" value="${value}" ${attrs}>
                <span class="gs-unit">${f.unit}${bandSuffix}</span>
            </span>
        </span>`;
}

// Reuses the ADD OBJ form's structural classes plus a .gs-form modifier
// (narrower inputs, inline toggles) -- five columns of four:
//   Antenna & gain | Uplink (Tx) | Downlink (Rx) | Losses & geometry | Link / waveform
// Position (lat/lon) isn't here -- it comes from GS LOCN (observerLocation).
// id="ground-station-form" is what toggleGroundStationForm() checks for.
function renderGroundStationFormMarkup() {
    const cfg = groundStationFormState || groundStationConfig || GS_DEFAULTS;
    const rows = (grp) => GS_NUMERIC_FIELDS
        .filter((f) => f.grp === grp)
        .map((f) => gsNumericRow(f, cfg))
        .join('');
    const polOptions = GS_POLARIZATIONS.map((p) =>
        `<option value="${p.value}"${cfg.polarization === p.value ? ' selected' : ''}>${p.label}</option>`).join('');
    const modOptions = GS_MODCOD_PRESETS.map((p) =>
        `<option value="${p.value}"${cfg.modCod === p.value ? ' selected' : ''}>${p.label}</option>`).join('');
    return `
        <div id="ground-station-form" class="add-object-form gs-form">
            <div class="add-object-fields">
                <div class="add-object-fields-col">
                    ${gsModeRow('GAIN SRC', GS_HINT.gainMode, 'gainMode', cfg.gainMode,
                        [{ value: 'calc', label: 'Calc' }, { value: 'manual', label: 'Manual' }])}
                    ${rows('antenna')}
                </div>
                <div class="add-object-fields-col">
                    ${gsModeRow('TX DRIVE', GS_HINT.txDriveMode, 'txDriveMode', cfg.txDriveMode,
                        [{ value: 'power', label: 'Calc' }, { value: 'eirp', label: 'Manual' }])}
                    ${rows('uplink')}
                </div>
                <div class="add-object-fields-col">
                    ${gsModeRow('RX FoM', GS_HINT.rxFomMode, 'rxFomMode', cfg.rxFomMode,
                        [{ value: 'tsys', label: 'Calc' }, { value: 'gt', label: 'Manual' }])}
                    ${rows('downlink')}
                </div>
                <div class="add-object-fields-col">
                    ${rows('geom')}
                    <label for="gs-pol" title="${GS_HINT.polarization}">POLARZN</label>
                    <select id="gs-pol" class="location-input" title="${GS_HINT.polarization}"
                        onchange="gsRefreshDerived()"
                        onkeydown="if (event.key === 'Enter') { event.preventDefault(); gsFocusNextField(this); }">${polOptions}</select>
                </div>
                <div class="add-object-fields-col">
                    <label for="gs-modcod" title="${GS_HINT.modCod}">MOD/COD</label>
                    <select id="gs-modcod" class="location-input" title="${GS_HINT.modCod}"
                        onchange="gsOnModCodChange(this)"
                        onkeydown="if (event.key === 'Enter') { event.preventDefault(); gsFocusNextField(this); }">${modOptions}</select>
                    ${rows('link')}
                </div>
            </div>
            <div class="add-object-actions gs-actions">
                <button class="location-btn" style="background-color: var(--golden-orange);" onclick="saveGroundStation()">SAVE</button>
                <button class="location-btn" style="background-color: var(--peach);" onclick="gsResetForm()">RESET</button>
                <div id="gs-status" class="gs-status is-hidden"></div>
            </div>
        </div>`;
}

function gsRenderFormInto() {
    const wrapper = document.getElementById('default');
    if (!wrapper) {
        return;
    }
    wrapper.innerHTML = renderGroundStationFormMarkup();
    gsRefreshDerived();
}

// RESET button -- reload the form from the 3 m S-band defaults without
// touching the saved config.
function gsResetForm() {
    groundStationFormState = { ...GS_DEFAULTS };
    gsRenderFormInto();
}

let groundStationStatusTimeout = null;

// Inline validation message under SAVE. In normal flow (not position:fixed
// like .usrloc-status) -- the single-button actions column leaves room for
// it inside #default's box.
function showGroundStationStatus(message) {
    const el = document.getElementById('gs-status');
    if (!el) {
        return;
    }
    el.textContent = message;
    el.classList.remove('is-hidden');
    clearTimeout(groundStationStatusTimeout);
    groundStationStatusTimeout = setTimeout(() => el.classList.add('is-hidden'), 4000);
}

// Wired to the GRND STN control-panel button. Toggles #default between the
// section's resting state and the config form -- same "check for the
// form's own presence" mechanic as toggleUserLocationForm().
function toggleGroundStationForm(restingRenderer) {
    const wrapper = document.getElementById('default');
    if (!wrapper) {
        return;
    }
    if (restingRenderer) {
        groundStationFormRestingRenderer = restingRenderer;
    }
    if (document.getElementById('ground-station-form')) {
        if (groundStationFormRestingRenderer) {
            groundStationFormRestingRenderer();
        }
        if (visibleSatsShown) {
            renderVisibleSats(); // restore the VIS NOW status panel into #default
        }
        return;
    }
    groundStationFormState = { ...GS_DEFAULTS, ...(groundStationConfig || {}) };
    gsRenderFormInto();
}

// Wired to the SAVE button. Validates every field that applies under the
// current mode toggles (a field gated off by `needs` is skipped, a
// `derived` field in its computed mode is skipped and filled in after),
// flags bad ones red, then resolves gain / EIRP / G/T and persists.
function saveGroundStation() {
    const cfg = { ...groundStationFormState, ...gsReadForm() };
    cfg.gainMode = cfg.gainMode || 'calc';
    cfg.txDriveMode = cfg.txDriveMode || 'power';
    cfg.rxFomMode = cfg.rxFomMode || 'tsys';

    let firstBad = null;
    GS_NUMERIC_FIELDS.forEach((f) => {
        const el = document.getElementById(f.id);
        if (!el) {
            return;
        }
        if (f.needs && !f.needs(cfg)) {
            el.classList.remove('invalid');
            return;
        }
        const value = parseFloat(el.value.replace(/[\s,]/g, ''));
        const ok = Number.isFinite(value) && value >= f.min && value <= f.max;
        el.classList.toggle('invalid', !ok);
        if (!ok && !firstBad) {
            firstBad = f;
        }
        if (ok) {
            cfg[f.key] = value;
        }
    });
    if (firstBad) {
        showGroundStationStatus(`Enter a valid ${firstBad.label} (${firstBad.min} to ${firstBad.max}).`);
        return;
    }

    // Resolve the derived figures so downstream link-budget code can read
    // antennaGainRxDBi / antennaGainTxDBi / eirpDBW / gOverTDBK regardless
    // of which entry mode was used.
    const derived = gsComputeDerived(cfg);
    cfg.antennaGainRxDBi = derived.gRxDBi;
    cfg.antennaGainTxDBi = derived.gTxDBi;
    cfg.eirpDBW = derived.eirpDBW;
    cfg.gOverTDBK = derived.gOverTDBK;
    cfg.polarization = (document.getElementById('gs-pol') || {}).value || cfg.polarization || 'RHCP';
    cfg.modCod = (document.getElementById('gs-modcod') || {}).value || cfg.modCod || 'CUSTOM';

    groundStationConfig = cfg;
    groundStationFormState = cfg;
    saveGroundStationConfig(cfg);
    if (groundStationFormRestingRenderer) {
        groundStationFormRestingRenderer();
    }
    if (visibleSatsShown) {
        renderVisibleSats(); // new GS params -> recompute the link budget + status
    }
}

/* ==========================================================================
   VISIBLE NOW -- satellites currently in line of sight of the station

   Client-side SGP4 (satellite.js, same json2satrec path onOrbitPanel.js's
   ground tracks use) over every active payload from /api/orbital-objects/
   active (fetched once, cached), propagated to "now". A satellite counts
   as visible when its topocentric elevation from the station meets or
   exceeds the GRND STN MIN ELEV horizon mask (DEFAULT_MIN_ELEVATION_DEG
   when no config is saved). That mask is the only filter -- every visible
   payload is plotted, there is no cap -- so the operator controls the
   density entirely through MIN ELEV. Each gets a dot plus a small arrow
   rotated to its ground-track heading, both coloured by the two-way link
   budget (see the LINK BUDGET block, and LINK_STATE_STYLE): green filled
   when both directions close (Tx & Rx), cyan filled when one does
   (downlink only), grey filled when neither does (no comms), and a
   light-blue outline when the satellite's data is too thin to evaluate
   (unknown). Clicking a dot opens a popup with the link verdict and the
   catalogue metadata; a status panel (renderVisibleSatStatus) drops the
   counts and the colour key into #default. Refreshed on a timer while the
   toggle is on -- LEO moves fast.
   ========================================================================== */

// Fallback elevation mask, in degrees, used only until a GRND STN config
// is saved -- after that its MIN ELEV value is what applies. With no cap
// on the plotted set, this mask is the sole gate: a low value at a busy
// site can put several hundred dots on the map, so raise MIN ELEV in the
// GRND STN form to thin it.
const DEFAULT_MIN_ELEVATION_DEG = 10;
const VISIBLE_SAT_REFRESH_MS = 10000;
// Seconds ahead to propagate a second time, purely to derive each
// satellite's ground-track heading (bearing from the now sub-point to the
// now+dt sub-point) for the direction arrow.
const VISIBLE_SAT_HEADING_DT_S = 15;

// Map marker + status-key styling per link-budget state (satelliteLink
// Status().state). `fill:false` => an outline-only ring.
const LINK_STATE_STYLE = {
    both:    { key: 'Tx & Rx',        color: '#33ee66', fill: true,  fillOpacity: 0.95, radius: 3 },
    one:     { key: 'Downlink only',  color: '#9cf',    fill: true,  fillOpacity: 0.9,  radius: 2.5 },
    none:    { key: 'No comms',       color: '#8a94a6', fill: true,  fillOpacity: 0.9,  radius: 2.5 },
    unknown: { key: 'Unknown',        color: '#bcdcff', fill: false, fillOpacity: 0,    radius: 3 },
};

// { satrec, meta } per active payload -- fetched and built once per
// session, then only re-propagated on each refresh.
let activeSatCatalogue = null;
// Bare satrecs for the non-payload objects (rocket bodies + debris). Only
// used to count "objects in view" for the status panel -- never plotted
// or link-budgeted. Loaded lazily and non-blocking when VIS NOW turns on;
// stays null (and the count falls back to the satellite count) until it
// resolves or if the fetch fails.
let nonPayloadSatrecs = null;
let visibleSatLayer = null;
let visibleSatsShown = false;
let visibleSatRefreshTimer = null;

async function loadActiveSatCatalogue() {
    if (activeSatCatalogue) {
        return activeSatCatalogue;
    }
    await loadScriptOnce('assets/satellite/satellite.min.js');
    const response = await fetch('api/orbital-objects/active');
    if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
    }
    const rows = await response.json();
    activeSatCatalogue = rows
        .map((o) => {
            if (!Number.isFinite(o.meanMotion)) {
                return null;
            }
            let satrec;
            try {
                // json2satrec() wants OMM's UPPER_SNAKE keys -- same
                // remap onOrbitPanel.js's loadTrackedSatrecs() does.
                satrec = satellite.json2satrec({
                    NORAD_CAT_ID: o.noradID,
                    EPOCH: o.epoch,
                    MEAN_MOTION: o.meanMotion,
                    ECCENTRICITY: o.eccentricity,
                    INCLINATION: o.inclination,
                    RA_OF_ASC_NODE: o.raOfAscNode,
                    ARG_OF_PERICENTER: o.argOfPericenter,
                    MEAN_ANOMALY: o.meanAnomaly,
                    BSTAR: o.bstar,
                    MEAN_MOTION_DOT: o.meanMotionDot,
                    MEAN_MOTION_DDOT: o.meanMotionDdot,
                });
            } catch (error) {
                return null;
            }
            // Key names line up with satelliteCatalogRows(m) in
            // onOrbitPanel.js so the click popup can share it.
            return {
                satrec,
                noradID: o.noradID,
                name: o.name || String(o.noradID),
                owner: o.owner || null,
                launchYear: o.launchDate ? String(o.launchDate).slice(0, 4) : null,
                launchSite: o.launchSite || null,
                objectType: o.objectType || null,
                downlinkBand: o.downlinkBand || null,
                eirpDbw: o.eirpDbw,
                eirpSource: o.eirpSource || null,
                satGtDbk: o.satGtDbk,
                satGtSource: o.satGtSource || null,
                dlFreqHz: o.dlFreqHz,
                ulFreqHz: o.ulFreqHz,
                rfSource: o.rfSource || null,
                inclinationDeg: o.inclination,
                periodMin: o.period,
                apogeeKm: o.apogee,
                perigeeKm: o.perigee,
                rcsM2: o.rcsSize,
            };
        })
        .filter(Boolean);
    return activeSatCatalogue;
}

// Rocket bodies + debris with usable elements -- bare satrecs, for the
// "objects in view" count only. json2satrec() must already be loaded (this
// runs after loadActiveSatCatalogue()).
async function loadNonPayloadCatalogue() {
    if (nonPayloadSatrecs) {
        return nonPayloadSatrecs;
    }
    const response = await fetch('api/orbital-objects/active-nonpayload');
    if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
    }
    const rows = await response.json();
    nonPayloadSatrecs = rows
        .map((o) => {
            if (!Number.isFinite(o.meanMotion)) {
                return null;
            }
            try {
                return satellite.json2satrec({
                    NORAD_CAT_ID: o.noradID,
                    EPOCH: o.epoch,
                    MEAN_MOTION: o.meanMotion,
                    ECCENTRICITY: o.eccentricity,
                    INCLINATION: o.inclination,
                    RA_OF_ASC_NODE: o.raOfAscNode,
                    ARG_OF_PERICENTER: o.argOfPericenter,
                    MEAN_ANOMALY: o.meanAnomaly,
                    BSTAR: o.bstar,
                    MEAN_MOTION_DOT: o.meanMotionDot,
                    MEAN_MOTION_DDOT: o.meanMotionDdot,
                });
            } catch (error) {
                return null;
            }
        })
        .filter(Boolean);
    return nonPayloadSatrecs;
}

// Initial great-circle bearing from point 1 to point 2, degrees clockwise
// from north.
function bearingDeg(lat1, lon1, lat2, lon2) {
    const toRad = Math.PI / 180;
    const phi1 = lat1 * toRad;
    const phi2 = lat2 * toRad;
    const dLon = (lon2 - lon1) * toRad;
    const y = Math.sin(dLon) * Math.cos(phi2);
    const x = Math.cos(phi1) * Math.sin(phi2) - Math.sin(phi1) * Math.cos(phi2) * Math.cos(dLon);
    return (Math.atan2(y, x) * 180 / Math.PI + 360) % 360;
}

// propagatePosition() lives in assets/onOrbitPanel.js, which
// openGsOpsSection() (lcars.js) always loads before this file -- shared
// with the on-orbit panel's ground tracks and live positions.

// Sub-satellite lat/lon (deg) at `time`, or null if SGP4 gives no
// position (decayed / numerically diverged element set).
function subPointDeg(satrec, time) {
    const position = propagatePosition(satrec, time);
    if (!position) {
        return null;
    }
    const geo = satellite.eciToGeodetic(position, satellite.gstime(time));
    return {
        lat: satellite.degreesLat(geo.latitude),
        lon: satellite.degreesLong(geo.longitude),
        altKm: geo.height,
    };
}

/* ==========================================================================
   LINK BUDGET -- can the station and a visible satellite close a link?

   A first-order two-way check per satellite, re-run every VIS NOW refresh
   on the current geometry. Method from satellite_link_budget_2.md:

     Eb/N0 = EIRP + G/T - Lfs - La - Lo + 228.6 - 10log10(dataRate)

   The receiver bandwidth cancels between C/N and the Eb/N0 conversion, so
   only the data rate matters. Clear-sky atmospheric loss only (there is no
   site rain data), plus a 1 dB implementation buffer.

   Ground-station side comes from the GRND STN form -- the resolved gain /
   EIRP / G/T, via gsComputeDerived() when nothing has been saved.
   Satellite side comes from enrichEirp (downlink EIRP and satellite G/T --
   both estimates) and ingestSatnogsRf (exact frequencies where known;
   otherwise the band mid-point). A direction whose inputs are missing
   counts as NOT closing.
   ========================================================================== */

// 10*log10(Boltzmann's constant), dBW/Hz/K -- the k term in N = k.T.B.
const BOLTZMANN_DB = -228.6;
// Standard engineering buffer for the losses the idealised chain omits.
const LINK_IMPL_MARGIN_DB = 1.0;

// Representative centre frequency, GHz, per IEEE band letter -- the
// downlink-frequency fallback when SatNOGS has no exact figure
// (satellite_link_budget_2.md Appendix A.2).
const BAND_MID_FREQ_GHZ = {
    VHF: 0.15, UHF: 0.4, L: 1.5, S: 2.25, C: 6.0,
    X: 9.0, Ku: 14.0, K: 22.0, Ka: 30.0, 'Q/V': 45.0,
};

function bandMidFreqGHz(band) {
    return BAND_MID_FREQ_GHZ[band] || null;
}

// Free-space path loss, dB. d in km, f in GHz.
function freeSpaceLossDB(rangeKm, freqGHz) {
    return 20 * Math.log10(rangeKm) + 20 * Math.log10(freqGHz) + 92.45;
}

// Clear-sky atmospheric loss, dB -- a crude band-keyed zenith gaseous
// figure scaled by the cosecant of the elevation angle (flat-atmosphere
// approximation, elevation floored at 3 deg to stay finite). No rain or
// cloud term: there is no site climate data here.
function clearSkyAtmosphericLossDB(freqGHz, elevationDeg) {
    let zenithDB;
    if (freqGHz < 3) {
        zenithDB = 0.04;
    } else if (freqGHz < 8) {
        zenithDB = 0.06;
    } else if (freqGHz < 15) {
        zenithDB = 0.12;
    } else if (freqGHz < 22) {
        zenithDB = 0.35; // approaching the 22 GHz water-vapour line
    } else if (freqGHz < 30) {
        zenithDB = 0.25;
    } else {
        zenithDB = 0.6;
    }
    return zenithDB / Math.sin(Math.max(elevationDeg, 3) * Math.PI / 180);
}

// Resolved ground-station link parameters -- prefers the values SAVE
// writes onto groundStationConfig, falls back to gsComputeDerived() so an
// unsaved (defaults-only) config still produces numbers.
function groundStationLinkParams() {
    const c = groundStationConfig || GS_DEFAULTS;
    const d = gsComputeDerived(c);
    const pick = (v, fallback) => (Number.isFinite(v) ? v : fallback);
    return {
        eirpDBW: pick(c.eirpDBW, d.eirpDBW),
        gOverTDBK: pick(c.gOverTDBK, d.gOverTDBK),
        otherLossesDB: pick(c.otherLossesDB, 1),
        uplinkFreqGHz: pick(c.uplinkFreqGHz, null),
        dataRateBps: pick(c.dataRateBps, 1e6),
        requiredEbN0DB: pick(c.requiredEbN0DB, 4.5),
    };
}

// Received Eb/N0 (dB) for one direction, or null when an input is missing.
function directionEbN0DB(p) {
    if (![p.eirpDBW, p.gOverTDBK, p.freqGHz, p.rangeKm, p.dataRateBps].every(Number.isFinite)
        || p.freqGHz <= 0 || p.rangeKm <= 0 || p.dataRateBps <= 0) {
        return null;
    }
    return p.eirpDBW + p.gOverTDBK
        - freeSpaceLossDB(p.rangeKm, p.freqGHz)
        - clearSkyAtmosphericLossDB(p.freqGHz, p.elevationDeg)
        - p.otherLossesDB
        - BOLTZMANN_DB
        - 10 * Math.log10(p.dataRateBps);
}

// { rxCloses, txCloses, rxMarginDB, txMarginDB } for one visible satellite.
// rx = the station can receive the satellite (downlink); tx = the
// satellite can receive the station (uplink). Either is false when its
// budget is short OR its inputs are unknown.
function satelliteLinkStatus(entry, rangeKm, elevationDeg, gs) {
    const threshold = gs.requiredEbN0DB + LINK_IMPL_MARGIN_DB;

    const fDown = Number.isFinite(entry.dlFreqHz) && entry.dlFreqHz > 0
        ? entry.dlFreqHz / 1e9
        : bandMidFreqGHz(entry.downlinkBand);
    const rxEbN0 = directionEbN0DB({
        eirpDBW: entry.eirpDbw, gOverTDBK: gs.gOverTDBK, freqGHz: fDown, rangeKm,
        otherLossesDB: gs.otherLossesDB, dataRateBps: gs.dataRateBps, elevationDeg,
    });

    const fUp = Number.isFinite(entry.ulFreqHz) && entry.ulFreqHz > 0
        ? entry.ulFreqHz / 1e9
        : (Number.isFinite(gs.uplinkFreqGHz) ? gs.uplinkFreqGHz : bandMidFreqGHz(entry.downlinkBand));
    const txEbN0 = directionEbN0DB({
        eirpDBW: gs.eirpDBW, gOverTDBK: entry.satGtDbk, freqGHz: fUp, rangeKm,
        otherLossesDB: gs.otherLossesDB, dataRateBps: gs.dataRateBps, elevationDeg,
    });

    const rxCloses = rxEbN0 != null && rxEbN0 >= threshold;
    const txCloses = txEbN0 != null && txEbN0 >= threshold;
    // 'unknown' only when NEITHER direction could be evaluated (the
    // satellite lacks EIRP and G/T -- the enrichEirp 'unknown' tier). Once
    // at least one direction is computable, an uncomputable one is treated
    // as "does not close".
    let state;
    if (rxEbN0 == null && txEbN0 == null) {
        state = 'unknown';
    } else if (rxCloses && txCloses) {
        state = 'both';
    } else if (rxCloses || txCloses) {
        state = 'one';
    } else {
        state = 'none';
    }
    return {
        rxCloses,
        txCloses,
        state,
        rxMarginDB: rxEbN0 != null ? rxEbN0 - threshold : null,
        txMarginDB: txEbN0 != null ? txEbN0 - threshold : null,
    };
}

function computeVisibleSats(now) {
    if (!observerLocation) {
        return { sats: [], minElevationDeg: DEFAULT_MIN_ELEVATION_DEG, objectsInView: 0, nonPayloadCounted: false };
    }
    const minEl = groundStationConfig && Number.isFinite(groundStationConfig.minElevationDeg)
        ? groundStationConfig.minElevationDeg
        : DEFAULT_MIN_ELEVATION_DEG;
    const stationAltKm = groundStationConfig && Number.isFinite(groundStationConfig.stationAltitudeM)
        ? groundStationConfig.stationAltitudeM / 1000
        : 0;
    const observerGd = {
        longitude: satellite.degreesToRadians(observerLocation.longitude),
        latitude: satellite.degreesToRadians(observerLocation.latitude),
        height: stationAltKm, // km -- from the GRND STN form's STN ALT field
    };
    const gmst = satellite.gstime(now);

    const visible = [];
    activeSatCatalogue.forEach((entry) => {
        const position = propagatePosition(entry.satrec, now);
        if (!position) {
            return;
        }
        const ecf = satellite.eciToEcf(position, gmst);
        const look = satellite.ecfToLookAngles(observerGd, ecf);
        const elevationDeg = satellite.radiansToDegrees(look.elevation);
        if (!Number.isFinite(elevationDeg) || elevationDeg < minEl) {
            return;
        }
        const geo = satellite.eciToGeodetic(position, gmst);
        visible.push({
            entry,
            lat: satellite.degreesLat(geo.latitude),
            lon: satellite.degreesLong(geo.longitude),
            altKm: geo.height,
            elevationDeg,
            azimuthDeg: satellite.radiansToDegrees(look.azimuth),
            rangeKm: look.rangeSat,
        });
    });

    // Highest elevation first, so nearest-zenith dots draw last / on top.
    visible.sort((a, b) => b.elevationDeg - a.elevationDeg);

    // Second propagation, for every visible satellite, to get the heading
    // arrow (bearing from the now sub-point to the now+dt sub-point).
    const ahead = new Date(now.getTime() + VISIBLE_SAT_HEADING_DT_S * 1000);
    visible.forEach((sat) => {
        const next = subPointDeg(sat.entry.satrec, ahead);
        sat.headingDeg = next ? bearingDeg(sat.lat, sat.lon, next.lat, next.lon) : null;
    });

    // Two-way link budget for each, on the current geometry.
    const gs = groundStationLinkParams();
    visible.forEach((sat) => {
        sat.link = satelliteLinkStatus(sat.entry, sat.rangeKm, sat.elevationDeg, gs);
    });

    // Rocket bodies + debris above the mask -- counted only (no plotting).
    // Skipped entirely until the (non-blocking) catalogue has loaded.
    let nonPayloadInView = 0;
    if (nonPayloadSatrecs) {
        nonPayloadSatrecs.forEach((satrec) => {
            const position = propagatePosition(satrec, now);
            if (!position) {
                return;
            }
            const look = satellite.ecfToLookAngles(observerGd, satellite.eciToEcf(position, gmst));
            const el = satellite.radiansToDegrees(look.elevation);
            if (Number.isFinite(el) && el >= minEl) {
                nonPayloadInView += 1;
            }
        });
    }

    return {
        sats: visible,
        minElevationDeg: minEl,
        objectsInView: visible.length + nonPayloadInView,
        nonPayloadCounted: nonPayloadSatrecs != null,
    };
}

function visibleSatPopupHtml(sat) {
    const { entry } = sat;
    // Live station-relative rows first (why this object is on screen),
    // then the shared catalogue/enrichment block -- same fields and
    // formatting as the on-orbit GRD TRCK popup (satelliteCatalogRows()
    // in onOrbitPanel.js).
    const link = sat.link || {};
    const linkVerdict = link.state === 'unknown' ? 'UNKNOWN — insufficient satellite data'
        : link.rxCloses && link.txCloses ? 'Tx & Rx'
            : link.rxCloses ? 'Downlink only (station Rx)'
                : link.txCloses ? 'Uplink only (station Tx)'
                    : 'No comms';
    const rows = [
        ['EL / AZ', `${sat.elevationDeg.toFixed(0)}° / ${sat.azimuthDeg.toFixed(0)}°`],
        ['ALT', `${Math.round(sat.altKm).toLocaleString('en-GB')} km`],
        ['LINK (clear-sky)', linkVerdict],
        ...satelliteCatalogRows(entry),
    ];
    const body = rows
        .map(([k, v]) => `<span class="popup-meta">${k}:</span> <span class="popup-value">${v}</span>`)
        .join('<br>');
    return `<span class="popup-name">${entry.name}</span><br>${body}`;
}

// #default (the shared control-panel area) belongs to whichever section is
// open; only write the VIS NOW status into it when GS OPS is actually the
// visible section and the GRND STN form isn't sitting there.
function gsOpsDefaultAvailable() {
    const section = document.querySelector('[data-section="gs-ops"]');
    return section
        && section.style.display !== 'none'
        && !document.getElementById('ground-station-form');
}

// Two-column status block in #default while VIS NOW is on: a stats column
// (objects / satellites / TT&C / two-way counts) and a colour key matching
// the map markers (LINK_STATE_STYLE). Re-rendered every refresh.
function renderVisibleSatStatus(sats, objectsInView, nonPayloadCounted) {
    const wrapper = document.getElementById('default');
    if (!wrapper || !gsOpsDefaultAvailable()) {
        return;
    }
    // # TT&C: the satellite can receive the ground station (uplink closes).
    // # Tx & Rx: both directions close.
    const ttc = sats.reduce((n, s) => n + (s.link && s.link.txCloses ? 1 : 0), 0);
    const twoWay = sats.reduce((n, s) => n + (s.link && s.link.state === 'both' ? 1 : 0), 0);
    const num = (v) => (Number.isFinite(v) ? v.toLocaleString('en-GB') : '—');
    // "objects" needs the (non-blocking) R/B + debris catalogue -- show a
    // trailing dot until it has loaded so the number isn't mistaken for final.
    const objectsText = num(objectsInView) + (nonPayloadCounted ? '' : ' …');

    // Swatch is the same swept-dart glyph the map draws for each satellite
    // (renderVisibleSats), in the state's colour -- filled, or outline-only
    // for 'unknown' to match the empty ring on the map.
    const keyRow = (stateKey) => {
        const s = LINK_STATE_STYLE[stateKey];
        return `<span class="gs-key-swatch">`
            + `<svg viewBox="0 0 22 22" width="16" height="16" aria-hidden="true">`
            + `<path d="M11 1 L16.5 19 L11 14.5 L5.5 19 Z" `
            + `fill="${s.fill ? s.color : 'none'}" stroke="${s.color}" `
            + `stroke-width="1.6" stroke-linejoin="round"/></svg></span>`
            + `<span class="gs-key-label">${s.key}</span>`;
    };

    wrapper.innerHTML = `
        <div class="gs-status-panel">
            <div class="gs-status-stats">
                <span class="k"># Tx &amp; Rx</span><span class="v">${num(twoWay)}</span>
                <span class="k"># TT&amp;C</span><span class="v">${num(ttc)}</span>
                <span class="k">Satellites in view</span><span class="v">${num(sats.length)}</span>
                <span class="k">Objects in view</span><span class="v">${objectsText}</span>
            </div>
            <div class="gs-status-key">
                ${keyRow('both')}
                ${keyRow('one')}
                ${keyRow('none')}
                ${keyRow('unknown')}
            </div>
        </div>`;
}

// Remove the status block (VIS NOW turned off) -- but only if it's ours,
// so we never wipe the GRND STN form or another section's panel.
function clearVisibleSatStatus() {
    const wrapper = document.getElementById('default');
    if (wrapper && wrapper.querySelector('.gs-status-panel') && !document.getElementById('ground-station-form')) {
        wrapper.innerHTML = '';
    }
}

function renderVisibleSats() {
    const map = gsOpsLocationPanel.getMap();
    if (!map || typeof L === 'undefined' || typeof satellite === 'undefined') {
        return;
    }
    if (visibleSatLayer) {
        map.removeLayer(visibleSatLayer);
        visibleSatLayer = null;
    }
    if (!visibleSatsShown || !activeSatCatalogue) {
        clearVisibleSatStatus();
        return;
    }

    const { sats, minElevationDeg, objectsInView, nonPayloadCounted } = computeVisibleSats(new Date());
    renderVisibleSatStatus(sats, objectsInView, nonPayloadCounted);
    console.log(`VISIBLE NOW: ${sats.length} payload(s) at or above the ${minElevationDeg}° mask`);

    const layers = [];
    sats.forEach((sat) => {
        // Link-budget colour (see satelliteLinkStatus / LINK_STATE_STYLE):
        //   both     -> solid green   (Tx & Rx)
        //   one      -> solid cyan    (Downlink only)
        //   none     -> solid grey    (No comms)
        //   unknown  -> light-blue outline, no fill (insufficient data)
        const style = LINK_STATE_STYLE[(sat.link && sat.link.state) || 'unknown'];
        const markColor = style.color;
        const dotOpts = style.fill
            ? { radius: style.radius, color: markColor, weight: 1, fillColor: markColor, fillOpacity: style.fillOpacity }
            : { radius: style.radius, color: markColor, weight: 1.5, fill: false };

        // Visible dot -- cosmetic only. The `hit` circle below is the click
        // target, so this dot isn't hittable (interactive:false), which
        // also stops it stealing hover away from the larger halo.
        const dot = L.circleMarker([sat.lat, sat.lon], { ...dotOpts, interactive: false });
        layers.push(dot);

        if (sat.headingDeg != null) {
            // A swept dart drawn pointing north, rotated to the heading --
            // long narrow blade + concave tail reads as "travelling this
            // way" far more clearly than a squat triangle glyph. Drawn as
            // inline SVG in the divIcon so the shape is fully controllable;
            // the path's own transform attribute does the rotation (no CSS
            // transform to compose with Leaflet's positioning). Filled in
            // the same link-budget colour as the dot. pointer-events:none
            // (see .sat-arrow CSS) -- decorative, must not intercept clicks
            // meant for the satellite under it.
            const arrow = L.marker([sat.lat, sat.lon], {
                interactive: false,
                icon: L.divIcon({
                    className: 'sat-arrow',
                    html: `<svg viewBox="0 0 22 22" width="22" height="22"><path transform="rotate(${sat.headingDeg.toFixed(1)} 11 11)" d="M11 1 L16.5 19 L11 14.5 L5.5 19 Z" fill="${markColor}" stroke="#03121d" stroke-width="1.3" stroke-linejoin="round"/></svg>`,
                    iconSize: [22, 22],
                    iconAnchor: [11, 11],
                }),
            });
            layers.push(arrow);
        }

        // Invisible ~18px hit halo -- the actual click target. Transparent
        // fill, no stroke, but interactive, so a click anywhere on or near
        // the satellite (the dot is tiny and the arrow is click-through)
        // opens its popup.
        const hit = L.circleMarker([sat.lat, sat.lon], {
            radius: 9, stroke: false, fill: true, fillOpacity: 0,
            bubblingMouseEvents: false,
        });
        // Lazy popup: built only when opened, so a busy refresh isn't
        // hundreds of string builds and a popup-builder fault can't abort
        // the render.
        hit.bindPopup(() => visibleSatPopupHtml(sat));
        layers.push(hit);
    });

    visibleSatLayer = L.layerGroup(layers).addTo(map);
}

// Wired to the VIS NOW button. Toggle: on -> load the catalogue (once),
// render, and start the refresh timer; off -> stop the timer and clear
// the layer + the status panel. The button label carries ON/OFF; the
// live counts are in the #default status panel (renderVisibleSatStatus).
async function toggleVisibleSats() {
    visibleSatsShown = !visibleSatsShown;
    if (!visibleSatsShown) {
        clearInterval(visibleSatRefreshTimer);
        visibleSatRefreshTimer = null;
        renderVisibleSats();
        return;
    }
    try {
        await loadActiveSatCatalogue();
        // Non-blocking: the "objects in view" total fills in once the R/B +
        // debris catalogue arrives; a failure just leaves it at the sat count.
        loadNonPayloadCatalogue()
            .then(() => { if (visibleSatsShown) renderVisibleSats(); })
            .catch((err) => console.warn('non-payload catalogue unavailable:', err));
        renderVisibleSats();
        clearInterval(visibleSatRefreshTimer);
        visibleSatRefreshTimer = setInterval(renderVisibleSats, VISIBLE_SAT_REFRESH_MS);
    } catch (error) {
        console.error('VISIBLE NOW failed:', error);
        visibleSatsShown = false;
        clearInterval(visibleSatRefreshTimer);
        visibleSatRefreshTimer = null;
        renderVisibleSats(); // tears down any partially-added layer
    }
}

const gsOpsLocationPanel = registerLocationMapPanel({
    sectionId: 'gs-ops',
    containerId: 'gs-ops-map',
    buttonLabel: 'GS LOCN',
    extraButtons: [
        {
            label: 'GRND STN',
            color: 'var(--peach)',
            onClick: () => toggleGroundStationForm(gsOpsLocationPanel.renderDefaultArea),
        },
        {
            label: 'VIS NOW',
            color: 'var(--bluey)',
            // Dynamic ON/OFF label like the on-orbit GRD TRCK toggle. The
            // live count lands in the console on each refresh rather than
            // here -- a button label only re-renders on a button click,
            // so it would go stale between the timer's own refreshes.
            getText: () => `VIS NOW - ${visibleSatsShown ? 'ON' : 'OFF'}`,
            onClick: toggleVisibleSats,
        },
    ],
});

// Global alias so openGsOpsSection() (lcars.js) can call it the same way
// the other sections call initOnOrbitMap() / initInfrastructureMap().
function initGsOpsMap() {
    return gsOpsLocationPanel.initMap();
}
