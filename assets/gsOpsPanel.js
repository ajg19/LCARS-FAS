/* ==========================================================================
   GS OPS PANEL

   Ground-station operations. Wraps registerLocationMapPanel()
   (assets/locationMapPanel.js) -- same shared base map + graticule +
   day/night terminator + user-location + CITY LBL behaviour as the EO
   panel -- and adds a GRND STN button (control-panel slot 4, directly
   below GS LOCN) that opens a ground-station configuration form in
   #default, mirroring the GS LOCN / USR LOCN entry-form pattern.

   Lazily loaded the first time GS OPS is opened; openGsOpsSection() in
   lcars.js loads mapCore.js, onOrbitPanel.js and locationMapPanel.js
   first.
   ========================================================================== */

// Satellite frequency bands for the GRND STN form's dropdown. IEEE
// radar-band letters (L..Ka and up), plus the VHF/UHF ranges commonly
// used for cubesat / amateur TT&C. `value` is the short code stored in
// the config; the label carries the nominal frequency span. A single
// band pick for now -- an explicit uplink/downlink centre-frequency pair
// can be added later if the link-budget maths needs finer than a band.
const SATELLITE_BANDS = [
    { value: 'VHF', label: 'VHF (30-300 MHz)' },
    { value: 'UHF', label: 'UHF (0.3-1 GHz)' },
    { value: 'L', label: 'L-band (1-2 GHz)' },
    { value: 'S', label: 'S-band (2-4 GHz)' },
    { value: 'C', label: 'C-band (4-8 GHz)' },
    { value: 'X', label: 'X-band (8-12 GHz)' },
    { value: 'Ku', label: 'Ku-band (12-18 GHz)' },
    { value: 'K', label: 'K-band (18-27 GHz)' },
    { value: 'Ka', label: 'Ka-band (27-40 GHz)' },
    { value: 'Q', label: 'Q/V-band (33-75 GHz)' },
];

// Hover text for the BAND control -- see numericInput()/renderGround
// StationFormMarkup() where it and the per-field `hint`s below are put on
// both the <label> and the input as `title` attributes. Kept quote-free
// so it drops straight into a double-quoted attribute.
const GS_BAND_HINT = 'Frequency band the station transmits/receives on. '
    + 'Ground stations commonly use S-band (2-4 GHz) for telemetry/command and '
    + 'LEO downlink, X-band (8-12 GHz) for Earth-observation payload downlink, and '
    + 'Ka-band (27-40 GHz) for high-rate links; UHF for cubesat/amateur work.';

// One row per numeric field: the input id, its label, the stored-config
// key, the accepted range, the unit (shown as a chip beside the input),
// and `hint` (hover tooltip: what it is + a typical range). Drives both
// the form markup and the validate/collect loop so a field's bounds live
// in exactly one place.
const GROUND_STATION_NUMERIC_FIELDS = [
    {
        id: 'gs-gain', label: 'ANT GAIN', key: 'gainDbi', unit: 'dBi',
        min: 0, max: 90,
        hint: 'Peak antenna gain relative to an isotropic radiator. Typical: '
            + '15-25 dBi for a small UHF/S-band Yagi or dish, 35-45 dBi for a '
            + '3-7 m S/X-band dish, 50-65 dBi for a large deep-space or Ka aperture.',
    },
    {
        id: 'gs-hpbw', label: 'HPBW', key: 'hpbwDeg', unit: 'deg',
        min: 0.01, max: 180,
        hint: 'Half-power (-3 dB) beamwidth of the main lobe, roughly 70*wavelength/'
            + 'diameter. Typical: 5-20 deg for small tracking antennas, 0.5-2 deg for '
            + 'a few-metre dish, under 0.2 deg for large apertures. Narrower beam = '
            + 'more gain but tighter pointing.',
    },
    {
        id: 'gs-eirp', label: 'EIRP', key: 'eirpW', unit: 'W', group: true,
        min: 0, max: 1e9,
        hint: 'Effective isotropic radiated power on transmit = Tx power x antenna '
            + 'gain, minus feed loss. Typical: tens of W for a cubesat uplink station, '
            + '100 W - 10 kW for S/X-band command uplinks, more for large Ka terminals.',
    },
    {
        id: 'gs-minel', label: 'MIN ELEV', key: 'minElevationDeg', unit: 'deg',
        min: 0, max: 90,
        hint: 'Lowest elevation above the horizon the station will track (horizon '
            + 'mask). Typical: 5 deg for a clear site, 8-10 deg to avoid ground '
            + 'clutter, multipath and atmospheric loss, higher where terrain or '
            + 'buildings obstruct.',
    },
    {
        id: 'gs-slew', label: 'SLEW RATE', key: 'slewRateDegPerSec', unit: 'deg/s',
        min: 0.01, max: 60,
        hint: 'Maximum angular speed the mount drives each axis. Typical: 1-3 deg/s '
            + 'for large/older dishes, 5-10 deg/s for LEO-tracking antennas, 20+ deg/s '
            + 'for fast small trackers. Must beat a satellite’s apparent rate near '
            + 'zenith (several deg/s for low LEO).',
    },
];

// Shown in the GRND STN form until the user saves their own -- a
// representative 3 m S-band tracking dish: ~2.25 GHz gives ~35 dBi and a
// ~3 deg beam for a 60%-efficient 3 m aperture; ~100 W into that antenna
// is ~50 dBW EIRP; 10 deg mask and a 5 deg/s mount are typical for LEO
// tracking. Held in memory only -- SAVE is what persists a config.
const GS_DEFAULTS = {
    band: 'S',
    gainDbi: 35,
    hpbwDeg: 3.1,
    eirpW: 100000,
    minElevationDeg: 10,
    slewRateDegPerSec: 5,
};

const GROUND_STATION_STORAGE_KEY = 'groundStationConfig';

function loadGroundStationConfig() {
    try {
        const raw = localStorage.getItem(GROUND_STATION_STORAGE_KEY);
        return raw ? JSON.parse(raw) : null;
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

// Reuses the ADD OBJ form's structural classes (.add-object-form /
// .add-object-fields / .add-object-fields-col / .add-object-actions /
// .location-input / .location-btn) -- a multi-column field layout that
// fits #default's fixed-height budget, unlike the 3-row LAT/LON/PLACE
// grid. Each numeric field carries a .gs-unit chip. id="ground-station-form"
// is what toggleGroundStationForm() checks for to decide open-vs-close.
// LAT/LON/altitude aren't here -- position comes from GS LOCN (the shared
// observerLocation).
function renderGroundStationFormMarkup() {
    const cfg = groundStationConfig || {};
    const bandOptions = ['<option value="">SELECT</option>']
        .concat(SATELLITE_BANDS.map((b) =>
            `<option value="${b.value}"${cfg.band === b.value ? ' selected' : ''}>${b.label}</option>`))
        .join('');
    const fieldValue = (f) => {
        if (cfg[f.key] == null) {
            return '';
        }
        return f.group ? Number(cfg[f.key]).toLocaleString('en-GB', { maximumFractionDigits: 6 }) : cfg[f.key];
    };
    const numericInput = (f) => `
        <label for="${f.id}" title="${f.hint}">${f.label}</label>
        <span class="gs-field">
            <input type="text" inputmode="decimal" autocomplete="off" id="${f.id}" class="location-input"
                title="${f.hint}" value="${fieldValue(f)}"
                oninput="gsSanitizeNumeric(this)"${f.group ? ' onblur="gsGroupOnBlur(this)"' : ''}
                onkeydown="if (event.key === 'Enter') saveGroundStation()">
            <span class="gs-unit">${f.unit}</span>
        </span>`;
    const [gain, hpbw, eirp, minel, slew] = GROUND_STATION_NUMERIC_FIELDS.map(numericInput);
    return `
        <div id="ground-station-form" class="add-object-form">
            <div class="add-object-fields">
                <div class="add-object-fields-col">
                    <label for="gs-band" title="${GS_BAND_HINT}">BAND</label>
                    <select id="gs-band" class="location-input" title="${GS_BAND_HINT}">${bandOptions}</select>
                    ${gain}
                    ${hpbw}
                </div>
                <div class="add-object-fields-col">
                    ${eirp}
                    ${minel}
                    ${slew}
                </div>
            </div>
            <div class="add-object-actions">
                <button class="location-btn" style="background-color: var(--golden-orange);" onclick="saveGroundStation()">SAVE</button>
                <div id="gs-status" class="gs-status is-hidden"></div>
            </div>
        </div>`;
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
        return;
    }
    wrapper.innerHTML = renderGroundStationFormMarkup();
}

// Wired to the SAVE button. Validates band + every numeric field against
// its range (flagging bad ones red, same .invalid class the LAT/LON
// fields use), persists the config, then closes the form.
function saveGroundStation() {
    const bandEl = document.getElementById('gs-band');
    if (!bandEl || !bandEl.value) {
        showGroundStationStatus('Select a frequency band.');
        return;
    }

    const values = {};
    let firstBad = null;
    GROUND_STATION_NUMERIC_FIELDS.forEach((f) => {
        const el = document.getElementById(f.id);
        if (!el) {
            return;
        }
        const value = parseFloat(el.value.replace(/[\s,]/g, ''));
        const ok = Number.isFinite(value) && value >= f.min && value <= f.max;
        el.classList.toggle('invalid', !ok);
        if (!ok && !firstBad) {
            firstBad = f;
        }
        values[f.key] = value;
    });
    if (firstBad) {
        showGroundStationStatus(`Enter a valid ${firstBad.label} (${firstBad.min}–${firstBad.max}).`);
        return;
    }

    groundStationConfig = {
        band: bandEl.value,
        gainDbi: values.gainDbi,
        hpbwDeg: values.hpbwDeg,
        eirpW: values.eirpW,
        minElevationDeg: values.minElevationDeg,
        slewRateDegPerSec: values.slewRateDegPerSec,
    };
    saveGroundStationConfig(groundStationConfig);
    if (groundStationFormRestingRenderer) {
        groundStationFormRestingRenderer();
    }
}

/* ==========================================================================
   VISIBLE NOW -- satellites currently in line of sight of the station

   Client-side SGP4 (satellite.js, same json2satrec path onOrbitPanel.js's
   ground tracks use) over every active payload from /api/orbital-objects/
   active (fetched once, cached), propagated to "now". A satellite counts
   as visible when its topocentric elevation from the station exceeds the
   GRND STN min-elevation mask (default DEFAULT_MIN_ELEVATION_DEG if no
   config saved yet). The kept set (highest elevation first, capped at
   VISIBLE_SAT_MAX) is plotted on the GS OPS map: a dot per satellite plus
   a small arrow rotated to its ground-track heading; clicking a dot opens
   a popup with name / type / altitude / launch year / owner. Refreshed on
   a timer while the toggle is on -- LEO moves fast.
   ========================================================================== */

// Fallback elevation mask when no GRND STN config is saved. 10 deg (not
// the 5 a permissive station might use) keeps the plot legible -- from any
// point on Earth a few hundred payloads clear 5 deg at once now, most of
// them low on the horizon and not usefully trackable.
const DEFAULT_MIN_ELEVATION_DEG = 10;
// Hard cap on plotted dots, highest-elevation first. Well below the true
// count when the sky is busy -- see the "showing X of Y" console line.
const VISIBLE_SAT_MAX = 80;
const VISIBLE_SAT_REFRESH_MS = 10000;
// Seconds ahead to propagate a second time, purely to derive each
// satellite's ground-track heading (bearing from the now sub-point to the
// now+dt sub-point) for the direction arrow.
const VISIBLE_SAT_HEADING_DT_S = 15;

// { satrec, meta } per active payload -- fetched and built once per
// session, then only re-propagated on each refresh.
let activeSatCatalogue = null;
let visibleSatLayer = null;
let visibleSatsShown = false;
let visibleSatCount = null;       // last render's visible-count (console/debug)
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
                periodMin: o.period,
                apogeeKm: o.apogee,
                perigeeKm: o.perigee,
                rcsM2: o.rcsSize,
            };
        })
        .filter(Boolean);
    return activeSatCatalogue;
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

// satellite.propagate() is not consistently safe: for an element set SGP4
// can't handle (decayed object, numerically diverged mean elements) it
// may return null/false OR an object with a falsy .position OR throw a
// RangeError -- so never destructure its result directly. Returns the ECI
// position vector, or null.
function propagatePosition(satrec, time) {
    let pv;
    try {
        pv = satellite.propagate(satrec, time);
    } catch (error) {
        return null;
    }
    return pv && pv.position ? pv.position : null;
}

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

function computeVisibleSats(now) {
    if (!observerLocation) {
        return [];
    }
    const minEl = groundStationConfig && Number.isFinite(groundStationConfig.minElevationDeg)
        ? groundStationConfig.minElevationDeg
        : DEFAULT_MIN_ELEVATION_DEG;
    const observerGd = {
        longitude: satellite.degreesToRadians(observerLocation.longitude),
        latitude: satellite.degreesToRadians(observerLocation.latitude),
        height: 0, // km -- station altitude not captured yet
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

    visible.sort((a, b) => b.elevationDeg - a.elevationDeg);
    const kept = visible.slice(0, VISIBLE_SAT_MAX);

    // Second propagation, only for the kept set, to get the heading arrow.
    const ahead = new Date(now.getTime() + VISIBLE_SAT_HEADING_DT_S * 1000);
    kept.forEach((sat) => {
        const next = subPointDeg(sat.entry.satrec, ahead);
        sat.headingDeg = next ? bearingDeg(sat.lat, sat.lon, next.lat, next.lon) : null;
    });
    return { sats: kept, total: visible.length };
}

function visibleSatPopupHtml(sat) {
    const { entry } = sat;
    // Live station-relative rows first (why this object is on screen),
    // then the shared catalogue/enrichment block -- same fields and
    // formatting as the on-orbit GRD TRCK popup (satelliteCatalogRows()
    // in onOrbitPanel.js).
    const rows = [
        ['EL / AZ', `${sat.elevationDeg.toFixed(0)}° / ${sat.azimuthDeg.toFixed(0)}°`],
        ['ALT', `${Math.round(sat.altKm).toLocaleString('en-GB')} km`],
        ...satelliteCatalogRows(entry),
    ];
    const body = rows
        .map(([k, v]) => `<span class="popup-meta">${k}:</span> <span class="popup-value">${v}</span>`)
        .join('<br>');
    return `<span class="popup-name">${entry.name}</span><br>${body}`;
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
        return;
    }

    const { sats, total } = computeVisibleSats(new Date());
    visibleSatCount = total;
    console.log(`VISIBLE NOW: showing ${sats.length} of ${total} payload(s) above the mask`);

    const layers = [];
    sats.forEach((sat) => {
        const dot = L.circleMarker([sat.lat, sat.lon], {
            radius: 2.5, color: '#9cf', weight: 1, fillColor: '#9cf', fillOpacity: 0.9,
        });
        // Lazy: build the popup HTML only when it's actually opened, so
        // an 80-dot refresh isn't 80 string builds, and a fault in the
        // (shared) popup builder can't abort the whole render.
        dot.bindPopup(() => visibleSatPopupHtml(sat));
        layers.push(dot);

        if (sat.headingDeg != null) {
            // A swept dart drawn pointing north, rotated to the heading --
            // long narrow blade + concave tail reads as "travelling this
            // way" far more clearly than a squat triangle glyph. Drawn as
            // inline SVG in the divIcon so the shape is fully controllable;
            // the path's own transform attribute does the rotation (no CSS
            // transform to compose with Leaflet's positioning).
            const arrow = L.marker([sat.lat, sat.lon], {
                interactive: false,
                icon: L.divIcon({
                    className: 'sat-arrow',
                    html: `<svg viewBox="0 0 22 22" width="22" height="22"><path transform="rotate(${sat.headingDeg.toFixed(1)} 11 11)" d="M11 1 L16.5 19 L11 14.5 L5.5 19 Z" fill="#9cf" stroke="#03121d" stroke-width="1.3" stroke-linejoin="round"/></svg>`,
                    iconSize: [22, 22],
                    iconAnchor: [11, 11],
                }),
            });
            layers.push(arrow);
        }
    });

    visibleSatLayer = L.layerGroup(layers).addTo(map);
}

// Wired to the VIS NOW button. Toggle: on -> load the catalogue (once),
// render, and start the refresh timer; off -> stop the timer and clear
// the layer. The button's own label carries the state / live count.
async function toggleVisibleSats() {
    visibleSatsShown = !visibleSatsShown;
    if (!visibleSatsShown) {
        clearInterval(visibleSatRefreshTimer);
        visibleSatRefreshTimer = null;
        visibleSatCount = null;
        renderVisibleSats();
        return;
    }
    try {
        visibleSatCount = null; // shows "..." while the catalogue loads
        await loadActiveSatCatalogue();
        renderVisibleSats();
        clearInterval(visibleSatRefreshTimer);
        visibleSatRefreshTimer = setInterval(renderVisibleSats, VISIBLE_SAT_REFRESH_MS);
    } catch (error) {
        console.error('VISIBLE NOW failed:', error);
        visibleSatsShown = false;
        visibleSatCount = null;
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
