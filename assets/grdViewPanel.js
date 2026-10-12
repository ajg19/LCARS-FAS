/* ==========================================================================
   GRD VIEW PANEL

   What is in the sky from the user's location right now, in the direction
   they are looking: the naked-eye stars (to magnitude 6, coloured by their
   B-V index), the Milky Way, the bright deep-sky objects, the
   constellations, the Sun, the Moon (drawn in its phase) and the planets,
   on a canvas in main, with a table of the Sun, Moon and planets below it,
   and the satellites and rocket bodies that could be seen with the naked
   eye (see Satellites below and assets/grdViewSatWorker.js).

   Stars, constellation lines and labels come from api/sky/catalogue
   (ingestionDBs/skyCatalogue.db, J2000). Everything else is calculated in
   the browser with Astronomy Engine (assets/astronomy/): one rotation
   matrix per redraw takes every star from J2000 to the observer's
   horizontal frame (x north, y west, z zenith), with precession and
   nutation included; the Sun, Moon and planets are computed directly.
   The view is a stereographic projection centred on AZM / ALT,
   GRD_VIEW_FOV_DEG wide: it keeps shapes true near the centre.

   Location reuses the shared LAT/LON/PLACE form and store from
   grdTrackPanel.js (toggleUserLocationForm(), observerLocation,
   ensureObserverLocation()) -- the same location GRD-TRACK, GS OPS and EO
   use. openGrdViewSection() in lcars.js loads mapCore.js, grdTrackPanel.js
   and Astronomy Engine first.

   Control panel, satellite group (left of the rule): STATUS, KIND and
   SPACEX filter the satellites as on ON-ORBIT; HIGHLIGHT OBJECTS puts a
   small target round every satellite shown.
   Control panel: USR LOCN in slot 1 opens the location form; SHW CONST /
   HDE CONST in slot 2 shows or hides the constellations, SHW DSO / HDE DSO
   in slot 3 the deep-sky objects' symbols and names (their glow always
   shows), SHW NAMES / HDE NAMES in slot 4 the bright-star names. The resting
   control area is a small table -- the observer's latitude and longitude,
   and the direction of view (AZM and ALT, editable) -- and a circular
   control with an azimuth and an altitude slider, which turn the view
   live. An amber rule separates it from the buttons.
   ========================================================================== */

// Direction of view: the compass bearing faced (azimuth, 0-360, 0 = north,
// 90 = east) and the altitude of the centre of the field of view (0 =
// horizon, 90 = straight up). Defaults: due north, 20 degrees up. Kept in
// localStorage as a per-viewer convenience; it can come back empty.
const GRD_VIEW_DIRECTION_KEY = 'grdViewDirection';
const GRD_VIEW_DEFAULT_DIRECTION = { azimuth: 0, altitude: 20 };

function loadGrdViewDirection() {
    try {
        const saved = JSON.parse(localStorage.getItem(GRD_VIEW_DIRECTION_KEY));
        if (saved && Number.isFinite(saved.azimuth) && Number.isFinite(saved.altitude)) {
            return saved;
        }
    } catch (error) {
        // Storage blocked or unreadable: use the defaults.
    }
    return { ...GRD_VIEW_DEFAULT_DIRECTION };
}

let grdViewDirection = loadGrdViewDirection();

function saveGrdViewDirection() {
    try {
        localStorage.setItem(GRD_VIEW_DIRECTION_KEY, JSON.stringify(grdViewDirection));
    } catch (error) {
        // Not persisted; the in-memory value still applies this session.
    }
}

// Displayed like the LAT/LON values (formatSignedCoordinate()) but
// unsigned: integer part zero-padded to 2 digits, 2 decimal places, e.g.
// "00.00", "90.00", "270.50".
function formatGrdViewAngle(value) {
    const [intPart, fracPart] = value.toFixed(2).split('.');
    return `${intPart.padStart(2, '0')}.${fracPart}`;
}

// On blur (Enter blurs too): a valid entry is stored, redisplayed in that
// format and the sky redrawn; an invalid one is flagged red and the last
// good value kept. Azimuth 360 is stored as 0.
function commitGrdViewDirection(input, field, min, max) {
    const value = parseFloat(input.value.trim());
    const valid = Number.isFinite(value) && value >= min && value <= max;
    input.classList.toggle('invalid', !valid);
    if (!valid) {
        return;
    }
    grdViewDirection[field] = field === 'azimuth' ? value % 360 : value;
    saveGrdViewDirection();
    input.value = formatGrdViewAngle(grdViewDirection[field]);
    syncGrdViewDial();
    drawGrdViewSky();
}

// While typing in AZM / ALT: each keystroke that makes a valid number moves
// the dial and redraws the sky at once; the box keeps what was typed (it is
// tidied, and a bad entry flagged, when the box is left -- see above).
function previewGrdViewDirection(input, field, min, max) {
    input.classList.remove('invalid');
    const value = parseFloat(input.value.trim());
    if (!Number.isFinite(value) || value < min || value > max) {
        return;
    }
    grdViewDirection[field] = field === 'azimuth' ? value % 360 : value;
    syncGrdViewDial();
    drawGrdViewSky();
}

// The circular direction control beside the table: a horizontal azimuth
// slider, -180..+180 (0 north, -90 west, +90 east, either end south), and a
// vertical altitude slider, 0 (bottom) to 90 (top), crossing at the centre.
// Moving either redraws the sky live (at most once a frame) and updates the
// AZM / ALT values; typing a value moves the sliders (syncGrdViewDial()).
function sliderFromAzimuth(azimuth) {
    return azimuth > 180 ? azimuth - 360 : azimuth;
}

let grdViewDialFrame = null;

function onGrdViewDial() {
    const azm = document.getElementById('grd-view-dial-azm');
    const alt = document.getElementById('grd-view-dial-alt');
    if (!azm || !alt) {
        return;
    }
    grdViewDirection.azimuth = (parseFloat(azm.value) + 360) % 360;
    grdViewDirection.altitude = parseFloat(alt.value);
    const azimuthText = document.getElementById('grd-view-azimuth');
    const altitudeText = document.getElementById('grd-view-altitude');
    if (azimuthText) azimuthText.value = formatGrdViewAngle(grdViewDirection.azimuth);
    if (altitudeText) altitudeText.value = formatGrdViewAngle(grdViewDirection.altitude);
    if (!grdViewDialFrame) {
        grdViewDialFrame = requestAnimationFrame(() => {
            grdViewDialFrame = null;
            drawGrdViewSky();
        });
    }
}

function syncGrdViewDial() {
    const azm = document.getElementById('grd-view-dial-azm');
    const alt = document.getElementById('grd-view-dial-alt');
    if (azm) azm.value = sliderFromAzimuth(grdViewDirection.azimuth);
    if (alt) alt.value = grdViewDirection.altitude;
}

function renderGrdViewDial() {
    return `<div class="grd-view-dial">
        <input type="range" id="grd-view-dial-azm" class="grd-view-dial-azm" aria-label="Azimuth"
            min="-180" max="180" step="0.5" value="${sliderFromAzimuth(grdViewDirection.azimuth)}"
            oninput="onGrdViewDial()" onchange="saveGrdViewDirection()">
        <input type="range" id="grd-view-dial-alt" class="grd-view-dial-alt" aria-label="Altitude"
            min="0" max="90" step="0.5" value="${grdViewDirection.altitude}"
            oninput="onGrdViewDial()" onchange="saveGrdViewDirection()">
        <span class="grd-view-dial-mark grd-view-dial-w">-180</span>
        <span class="grd-view-dial-mark grd-view-dial-e">+180</span>
        <span class="grd-view-dial-mark grd-view-dial-up">90</span>
        <span class="grd-view-dial-mark grd-view-dial-down">0</span>
    </div>`;
}

// Resting control area: a small table of the observer's latitude and
// longitude and the direction of view, whose AZM (azimuth) and ALT
// (altitude) are editable. Also the location form's on-close renderer, so
// a newly entered location shows at once -- and the sky is redrawn for it.
function renderGrdViewDefaultArea() {
    const wrapper = document.getElementById('default');
    if (!wrapper) {
        return;
    }
    const coordinate = (value) => (observerLocation ? formatSignedCoordinate(value) : '—');
    const directionInput = (field, min, max) => `<input type="text" inputmode="decimal"
        id="grd-view-${field}" class="loc-value grd-view-input" value="${formatGrdViewAngle(grdViewDirection[field])}"
        onblur="commitGrdViewDirection(this, '${field}', ${min}, ${max})"
        oninput="previewGrdViewDirection(this, '${field}', ${min}, ${max})"
        onkeydown="if (event.key === 'Enter') this.blur()">`;
    wrapper.innerHTML = `<div class="grd-view-table">
        <span class="loc-label">LAT</span><span class="loc-value">${coordinate(observerLocation && observerLocation.latitude)}</span>
        <span class="loc-label">LON</span><span class="loc-value">${coordinate(observerLocation && observerLocation.longitude)}</span>
        <label class="loc-label" for="grd-view-azimuth">AZM</label>${directionInput('azimuth', 0, 360)}
        <label class="loc-label" for="grd-view-altitude">ALT</label>${directionInput('altitude', 0, 90)}
    </div>${renderGrdViewDial()}`;
    drawGrdViewSky();
    requestGrdViewSatellites();
}

/* --------------------------------------------------------------------------
   Satellites
   -------------------------------------------------------------------------- */

// Payloads and rocket bodies that could ever reach naked-eye brightness
// (filtered by the server, api/sky/satellites), positioned in a background
// thread (assets/grdViewSatWorker.js) every GRD_VIEW_SAT_REFRESH_MS, at that
// moment and GRD_VIEW_SAT_REFRESH_MS later. Between results each dot glides
// from the first position towards the second, drawn on its own canvas
// (#grd-view-sat-canvas, over the star chart) about GRD_VIEW_SAT_FPS times
// a second -- the star chart itself is not redrawn for that.
const GRD_VIEW_SAT_REFRESH_MS = 1000;   // low-orbit satellites cross ~0.5 deg of sky a second
const GRD_VIEW_SAT_FPS = 30;
const GRD_VIEW_SAT_LIMIT_MAG = 5;       // as server.py VISIBLE_LIMIT_MAG: a moving point under a good dark sky
const GRD_VIEW_DARK_SUN_ALT = -6;       // observer's sky dark enough once the Sun is this low

let grdViewSatRows = null;      // rows from api/sky/satellites
let grdViewSatWorker = null;
let grdViewSatResults = [];     // [index, altitude, azimuth, magnitude, sunlit, altitude2, azimuth2] above the horizon
let grdViewSatTracks = [];      // per result: from / to unit vectors for gliding
let grdViewSatResultTime = 0;   // the moment the latest result is for (ms)
let grdViewSatTimer = null;
let grdViewSatBusy = false;
let grdViewSunAltitude = -90;   // from the latest star-chart draw
let grdViewSatFrame = null;
let grdViewSatLastFrame = 0;

async function startGrdViewSatellites() {
    if (grdViewSatWorker) {
        return;
    }
    const response = await fetch('api/sky/satellites');
    if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
    }
    grdViewSatRows = await response.json();
    grdViewSatWorker = new Worker('assets/grdViewSatWorker.js');
    grdViewSatWorker.onmessage = (event) => {
        if (event.data.type !== 'result') return;
        grdViewSatBusy = false;
        grdViewSatResults = event.data.objects;
        grdViewSatResultTime = event.data.timeMs;
        grdViewSatTracks = grdViewSatResults.map((r) => [horizontalVector(r[1], r[2]), horizontalVector(r[5], r[6])]);
        startGrdViewSatAnimation();
    };
    grdViewSatWorker.onerror = (error) => {
        grdViewSatBusy = false;
        console.error('Satellite worker error:', error.message);
    };
    grdViewSatWorker.postMessage({ type: 'init', rows: grdViewSatRows });
}

// Names and details are not in the download (it carries NORAD numbers
// only): a labelled object's name is fetched from api/sky/object the first
// time it is needed and kept for the visit; until it arrives the label
// shows the NORAD number.
const grdViewSatNames = new Map();
const grdViewSatNamesPending = new Set();

function grdViewSatName(noradID) {
    if (grdViewSatNames.has(noradID)) {
        return grdViewSatNames.get(noradID);
    }
    if (!grdViewSatNamesPending.has(noradID)) {
        grdViewSatNamesPending.add(noradID);
        fetchGrdViewObject(noradID)
            .then((details) => {
                grdViewSatNames.set(noradID, details.name || `#${noradID}`);
                drawGrdViewSky();
            })
            .catch(() => grdViewSatNames.set(noradID, `#${noradID}`))
            .finally(() => grdViewSatNamesPending.delete(noradID));
    }
    return `#${noradID}`;
}

async function fetchGrdViewObject(noradID) {
    const response = await fetch(`api/sky/object?noradID=${noradID}`);
    if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
    }
    return response.json();
}

// Where each satellite was last drawn, for clicks: [noradID, x, y, index].
let grdViewSatDrawn = [];

// A click on the sky chart: the nearest satellite drawn within
// GRD_VIEW_CLICK_PX opens its details; a click anywhere else closes them.
const GRD_VIEW_CLICK_PX = 10;

function onGrdViewCanvasClick(event) {
    const canvas = event.currentTarget;
    const rect = canvas.getBoundingClientRect();
    const x = event.clientX - rect.left;
    const y = event.clientY - rect.top;
    let best = null;
    let bestDistance = GRD_VIEW_CLICK_PX;
    grdViewSatDrawn.forEach((entry) => {
        const distance = Math.hypot(entry[1] - x, entry[2] - y);
        if (distance <= bestDistance) {
            best = entry;
            bestDistance = distance;
        }
    });
    if (!best) {
        hideGrdViewPopup();
        return;
    }
    showGrdViewPopup(best[0], best[3], x, y);
}

function hideGrdViewPopup() {
    const popup = document.getElementById('grd-view-popup');
    if (popup) popup.remove();
}

async function showGrdViewPopup(noradID, resultIndex, x, y) {
    hideGrdViewPopup();
    const canvas = document.getElementById('grd-view-canvas');
    const popup = document.createElement('div');
    popup.id = 'grd-view-popup';
    popup.className = 'grd-view-popup';
    popup.style.left = `${Math.min(x + 14, canvas.clientWidth - 320)}px`;
    popup.style.top = `${Math.min(y + 14, canvas.clientHeight - 60)}px`;
    popup.innerHTML = `<div class="grd-view-popup-title">#${noradID} &hellip;</div>`;
    canvas.parentElement.appendChild(popup);

    let details;
    try {
        details = await fetchGrdViewObject(noradID);
    } catch (error) {
        popup.innerHTML = `<div class="grd-view-popup-title">#${noradID}: DETAILS UNAVAILABLE</div>`;
        return;
    }
    if (!document.body.contains(popup)) return;   // closed meanwhile
    grdViewSatNames.set(noradID, details.name || `#${noradID}`);
    const now = grdViewSatResults.find((r) => grdViewSatRows[r[0]][0] === noradID);
    const metres = (v) => (v ? `${v} m` : null);
    const rows = [
        ['NORAD ID', noradID],
        ['Type', { PAY: 'Payload', 'R/B': 'Rocket body' }[details.objectType] || details.objectType],
        ['Owner', [details.owners, details.stateCode].filter(Boolean).join(', ') || details.owner],
        ['Launched', [details.launchDate, details.launchSite].filter(Boolean).join(', ')],
        ['Maker / bus', [details.manufacturer, details.bus].filter(Boolean).join(' / ')],
        ['Orbit', details.perigee != null ? `${Math.round(details.perigee).toLocaleString('en-GB')} \u2013 ${Math.round(details.apogee).toLocaleString('en-GB')} km, ${Number(details.inclination).toFixed(1)}\u00b0, ${Number(details.period).toFixed(1)} min` : null],
        ['Size (L \u00d7 D, span)', details.lengthM ? `${metres(details.lengthM)} \u00d7 ${metres(details.diameterM)}, ${metres(details.spanM)}` : null],
        ['Mass', details.massKg ? `${Math.round(details.massKg).toLocaleString('en-GB')} kg` : null],
        ['Standard magnitude', details.stdMag != null ? `${details.stdMag.toFixed(1)} (${details.brightnessSource})` : null],
        ['Now', now ? `alt ${now[1].toFixed(1)}\u00b0, azm ${now[2].toFixed(1)}\u00b0, mag ${now[3] !== null && now[3] < 50 ? now[3].toFixed(1) : '\u2014'}${now[4] ? '' : ', in shadow'}` : null],
        ['Downlink band', details.downlinkBand],
    ].filter(([, value]) => value !== null && value !== undefined && value !== '');
    popup.innerHTML = `<button class="grd-view-popup-close" aria-label="Close" onclick="hideGrdViewPopup()">\u00d7</button>
        <div class="grd-view-popup-title">${(details.name || `#${noradID}`).toUpperCase()}</div>
        <div class="grd-view-popup-grid">${rows.map(([label, value]) =>
            `<span class="loc-label">${label}</span><span class="loc-value">${value}</span>`).join('')}</div>`;
}

// Satellite filters, as on ON-ORBIT (same button labels): STATUS active
// only / active and dead; KIND satellites only (payloads that are not
// stations or their visiting vehicles) / all spacecraft (payloads) / all
// objects (payloads and rocket bodies -- debris is never in the data); and
// SpaceX included or excluded. Defaults show everything: dead satellites
// and rocket bodies are among the brightest things in the sky.
const GRD_VIEW_KINDS = ['satellites', 'spacecraft', 'objects'];
const GRD_VIEW_KIND_BUTTONS = { satellites: 'SAT ONLY', spacecraft: 'ALL S-CRFT', objects: 'ALL-OBJ' };
const GRD_VIEW_STATUS_BUTTONS = { active: 'ACT-ONLY', all: 'ACT +DEAD' };
const grdViewSatFilters = { status: 'all', kind: 'objects', spacex: 'with' };

// row: [noradID, kind, stdMag, active, spacex, ...elements, station]
function grdViewSatPasses(row) {
    if (grdViewSatFilters.status === 'active' && !row[3]) return false;
    if (grdViewSatFilters.kind === 'satellites' && (row[1] !== 'P' || row[15])) return false;
    if (grdViewSatFilters.kind === 'spacecraft' && row[1] !== 'P') return false;
    if (grdViewSatFilters.spacex === 'without' && row[4]) return false;
    return true;
}

// HIGHLIGHT OBJECTS: when on, a small amber target -- a ring with four
// ticks -- around every satellite the filters are showing, so faint and
// ghost dots are easy to find.
let grdViewTargetsShown = false;

function toggleGrdViewTargets() {
    grdViewTargetsShown = !grdViewTargetsShown;
    drawGrdViewSatellites();
}

function drawGrdViewTarget(ctx, x, y) {
    const r = 7;
    ctx.beginPath();
    ctx.arc(x, y, r, 0, 2 * Math.PI);
    ctx.moveTo(x - r - 3, y); ctx.lineTo(x - r + 2, y);
    ctx.moveTo(x + r - 2, y); ctx.lineTo(x + r + 3, y);
    ctx.moveTo(x, y - r - 3); ctx.lineTo(x, y - r + 2);
    ctx.moveTo(x, y + r - 2); ctx.lineTo(x, y + r + 3);
    ctx.stroke();
}

// Asks the worker for positions now (skipped while it is still busy).
function requestGrdViewSatellites() {
    if (!grdViewSatWorker || !observerLocation || grdViewSatBusy) {
        return;
    }
    grdViewSatBusy = true;
    grdViewSatWorker.postMessage({
        type: 'compute',
        timeMs: Date.now(),
        aheadMs: GRD_VIEW_SAT_REFRESH_MS,
        latitude: observerLocation.latitude,
        longitude: observerLocation.longitude,
    });
}

// Redraws the satellite canvas every frame (capped at GRD_VIEW_SAT_FPS)
// while GRD VIEW is open; stops itself when the section is hidden.
function startGrdViewSatAnimation() {
    if (grdViewSatFrame) {
        return;
    }
    const step = (now) => {
        const section = document.querySelector('main [data-section="grd-view"]');
        if (!section || section.style.display === 'none') {
            grdViewSatFrame = null;
            return;
        }
        if (now - grdViewSatLastFrame >= 1000 / GRD_VIEW_SAT_FPS) {
            grdViewSatLastFrame = now;
            drawGrdViewSatellites();
        }
        grdViewSatFrame = requestAnimationFrame(step);
    };
    grdViewSatFrame = requestAnimationFrame(step);
}

// On the satellite canvas, each dot where it is now -- glided between the
// latest result's two positions by the time since it (and on past the
// second, if the next result is late). Visible (sunlit, magnitude
// GRD_VIEW_SAT_LIMIT_MAG or brighter, the observer's sky dark): a warm
// white dot sized by apparent magnitude; the stations and anything
// magnitude 3 or brighter named. Everything else above the horizon -- in
// shadow, too faint, or in daylight -- a faint ghost dot. A count in the
// corner.
function drawGrdViewSatellites() {
    const canvas = document.getElementById('grd-view-sat-canvas');
    if (!canvas || !grdViewSatRows) {
        return;
    }
    const width = canvas.clientWidth;
    const height = canvas.clientHeight;
    if (!width || !height) {
        return;
    }
    const ratio = window.devicePixelRatio || 1;
    if (canvas.width !== Math.round(width * ratio) || canvas.height !== Math.round(height * ratio)) {
        canvas.width = Math.round(width * ratio);
        canvas.height = Math.round(height * ratio);
    }
    const ctx = canvas.getContext('2d');
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    ctx.clearRect(0, 0, width, height);
    const project = makeGrdViewProjector(grdViewCamera(width), width, height);
    const onCanvas = (p) => p && p[0] > -10 && p[0] < width + 10 && p[1] > -10 && p[1] < height + 10;
    const f = Math.min(2, Math.max(0, (Date.now() - grdViewSatResultTime) / GRD_VIEW_SAT_REFRESH_MS));
    const dark = grdViewSunAltitude < GRD_VIEW_DARK_SUN_ALT;
    let visible = 0;
    grdViewSatDrawn = [];
    ctx.save();
    ctx.font = grdViewButtonFont();
    ctx.textAlign = 'left';
    const glide = ([a, b]) => {
        const v = [a[0] + f * (b[0] - a[0]), a[1] + f * (b[1] - a[1]), a[2] + f * (b[2] - a[2])];
        const length = Math.hypot(v[0], v[1], v[2]) || 1;
        return [v[0] / length, v[1] / length, v[2] / length];
    };
    let aboveHorizon = 0;
    grdViewSatResults.forEach(([index, , , magnitude, sunlit], i) => {
        const row = grdViewSatRows[index];
        if (!grdViewSatPasses(row)) return;
        aboveHorizon++;
        const p = project(glide(grdViewSatTracks[i]));
        const seen = dark && sunlit && magnitude <= GRD_VIEW_SAT_LIMIT_MAG;
        if (seen) visible++;
        if (!onCanvas(p)) return;
        if (grdViewTargetsShown) {
            ctx.strokeStyle = 'rgba(234, 158, 65, 0.85)';   // LCARS amber
            ctx.lineWidth = 1;
            drawGrdViewTarget(ctx, p[0], p[1]);
        }
        grdViewSatDrawn.push([row[0], p[0], p[1], index]);
        ctx.beginPath();
        if (seen) {
            ctx.fillStyle = 'rgb(255, 240, 205)';
            ctx.arc(p[0], p[1], Math.max(1.5, radiusForMagnitude(magnitude)), 0, 2 * Math.PI);
            ctx.fill();
            if (magnitude <= 3 || row[0] === 25544 || row[0] === 48274) {
                ctx.fillStyle = '#ffcc99';   // LCARS peach
                ctx.fillText(`${grdViewSatName(row[0])} ${magnitude.toFixed(1)}`, p[0] + 6, p[1] - 6);
            }
        } else {
            ctx.fillStyle = 'rgba(160, 170, 190, 0.35)';
            ctx.arc(p[0], p[1], 1.2, 0, 2 * Math.PI);
            ctx.fill();
        }
    });
    ctx.fillStyle = '#ffcc99';
    ctx.fillText(`SATELLITES: ${visible} VISIBLE \u00b7 ${aboveHorizon} ABOVE HORIZON`, 12, 22);

    ctx.restore();
}

/* --------------------------------------------------------------------------
   Sky view
   -------------------------------------------------------------------------- */

// Horizontal field of view: about what the eyes take in comfortably
// without turning the head (binocular vision spans roughly 120 degrees).
const GRD_VIEW_FOV_DEG = 100;
const GRD_VIEW_REFRESH_MS = 30 * 1000;   // the sky turns 0.125 degrees in 30 s
const DEG = Math.PI / 180;

let grdViewCatalogue = null;             // { stars, lines, constellations } from api/sky/catalogue
let grdViewConstellationsVisible = false;   // off by default; SHW CONST turns them on
let grdViewStarNamesVisible = true;         // bright-star names; HDE NAMES hides them
let grdViewDeepSkyVisible = true;           // DSO symbols and names; HDE DSO hides them (the glow stays)
let grdViewRefreshTimer = null;

// The Sun, Moon and naked-eye planets (Uranus is at the limit, about
// magnitude 5.7). Disc colours are display choices.
const GRD_VIEW_BODIES = [
    { body: 'Sun', label: 'SUN', color: '#ffd75e' },
    { body: 'Moon', label: 'MOON', color: '#e8e8e8' },
    { body: 'Mercury', label: 'MERCURY', color: '#c8bfb3' },
    { body: 'Venus', label: 'VENUS', color: '#fff2c4' },
    { body: 'Mars', label: 'MARS', color: '#ff8f5a' },
    { body: 'Jupiter', label: 'JUPITER', color: '#f0d9b0' },
    { body: 'Saturn', label: 'SATURN', color: '#ead28a' },
    { body: 'Uranus', label: 'URANUS', color: '#a8e4ef' },
];

// J2000 unit vector for a right ascension and declination in degrees.
function equatorialUnit(raDeg, decDeg) {
    return [Math.cos(decDeg * DEG) * Math.cos(raDeg * DEG),
            Math.cos(decDeg * DEG) * Math.sin(raDeg * DEG),
            Math.sin(decDeg * DEG)];
}

// Horizontal-frame unit vector (x north, y west, z up) for an altitude and
// azimuth in degrees.
function horizontalVector(altDeg, azDeg) {
    return [Math.cos(altDeg * DEG) * Math.cos(azDeg * DEG),
            -Math.cos(altDeg * DEG) * Math.sin(azDeg * DEG),
            Math.sin(altDeg * DEG)];
}

async function loadGrdViewCatalogue() {
    if (grdViewCatalogue) {
        return grdViewCatalogue;
    }
    const response = await fetch('api/sky/catalogue');
    if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
    }
    const catalogue = await response.json();
    // Unit vectors worked out once, not on every redraw.
    catalogue.stars.forEach((star) => { star.v = equatorialUnit(star[0], star[1]); });
    catalogue.lines = catalogue.lines.map((line) => line.map(([ra, dec]) => equatorialUnit(ra, dec)));
    catalogue.constellations.forEach((c) => { c.v = equatorialUnit(c[1], c[2]); });
    catalogue.milkyWay = catalogue.milkyWay.map(([level, ring]) => ({ level, ring: ring.map(([ra, dec]) => equatorialUnit(ra, dec)) }));
    catalogue.deepSky.forEach((o) => { o.v = equatorialUnit(o[2], o[3]); });
    grdViewCatalogue = catalogue;
    return catalogue;
}

// Star colour from its B-V colour index: B-V to temperature (Ballesteros
// 2012), then temperature to RGB (a standard blackbody fit), mixed halfway
// to white so colours read as tints, as the eye sees them.
function starColorFromBv(bv) {
    if (bv === null || bv === undefined) {
        return 'rgb(255,255,255)';
    }
    const t = 4600 * (1 / (0.92 * bv + 1.7) + 1 / (0.92 * bv + 0.62)) / 100;
    const clamp = (x) => Math.max(0, Math.min(255, x));
    const r = t <= 66 ? 255 : clamp(329.7 * Math.pow(t - 60, -0.1332));
    const g = t <= 66 ? clamp(99.47 * Math.log(t) - 161.12) : clamp(288.12 * Math.pow(t - 60, -0.0755));
    const b = t >= 66 ? 255 : t <= 19 ? 0 : clamp(138.52 * Math.log(t - 10) - 305.04);
    const mix = (c) => Math.round((c + 255) / 2);
    return `rgb(${mix(r)},${mix(g)},${mix(b)})`;
}

// Canvas font matching the control-panel buttons (their computed size,
// which steps down on smaller screens), for the constellation and
// deep-sky labels.
function grdViewButtonFont() {
    const button = document.querySelector('.data-cascade-button-group nav button');
    const size = button ? getComputedStyle(button).fontSize : '16px';
    return `${size} Antonio, sans-serif`;
}

// Radius in CSS px for a magnitude: about 0.7px at 6, 3.4px at 0.
function radiusForMagnitude(mag) {
    return Math.max(0.6, 0.5 + (6.5 - mag) * 0.45);
}

// Camera for one redraw: unit vectors forward (the view direction), right
// and up, in the horizontal frame, and the stereographic scale in px.
function grdViewCamera(width) {
    const az = grdViewDirection.azimuth * DEG;
    const alt = grdViewDirection.altitude * DEG;
    const forward = [Math.cos(alt) * Math.cos(az), -Math.cos(alt) * Math.sin(az), Math.sin(alt)];
    const right = [-Math.sin(az), -Math.cos(az), 0];
    const up = [   // right x forward
        right[1] * forward[2] - right[2] * forward[1],
        right[2] * forward[0] - right[0] * forward[2],
        right[0] * forward[1] - right[1] * forward[0],
    ];
    const scale = (width / 2) / (2 * Math.tan(GRD_VIEW_FOV_DEG * DEG / 4));
    return { forward, right, up, scale };
}

// Horizontal-frame unit vector to canvas px, or null if it is well behind
// the viewer.
function makeGrdViewProjector(camera, width, height) {
    const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
    return (h) => {
        const z = dot(h, camera.forward);
        if (z < -0.2) {
            return null;
        }
        const k = 2 / (1 + z);
        return [width / 2 + camera.scale * k * dot(h, camera.right),
                height / 2 - camera.scale * k * dot(h, camera.up)];
    };
}

// The inverse: is the direction seen at canvas point (px, py) below the
// horizon? Stereographic inverse, then the zenith component.
function grdViewBelowHorizon(camera, px, py, width, height) {
    const X = (px - width / 2) / camera.scale;
    const Y = (height / 2 - py) / camera.scale;
    const r2 = X * X + Y * Y;
    const z = (4 - r2) / (4 + r2);   // component along forward
    const k = (1 + z) / 2;
    return z * camera.forward[2] + X * k * camera.right[2] + Y * k * camera.up[2] < 0;
}

// The Sun, Moon and planets now: altitude, azimuth, magnitude, distance,
// illuminated fraction, constellation and next rise and set.
function computeGrdViewBodies(time, observer) {
    return GRD_VIEW_BODIES.map((entry) => {
        const eq = Astronomy.Equator(entry.body, time, observer, true, true);
        const hor = Astronomy.Horizon(time, observer, eq.ra, eq.dec, 'normal');
        const illumination = Astronomy.Illumination(entry.body, time);
        const rise = Astronomy.SearchRiseSet(entry.body, observer, +1, time, 2);
        const set = Astronomy.SearchRiseSet(entry.body, observer, -1, time, 2);
        return {
            ...entry,
            altitude: hor.altitude,
            azimuth: hor.azimuth,
            mag: illumination.mag,
            phase: illumination.phase_fraction,
            distAu: eq.dist,
            constellation: Astronomy.Constellation(eq.ra, eq.dec).name,
            phaseName: entry.body === 'Moon' ? moonPhaseName(Astronomy.MoonPhase(time)) : null,
            rise: rise ? rise.date : null,
            set: set ? set.date : null,
        };
    });
}

// Sky colour and star visibility follow the Sun: black at night, deepening
// blues through twilight, blue by day, when stars are faint ghosts.
function skyStateForSun(sunAltitude) {
    if (sunAltitude > 0) return { sky: '#14365c', starAlpha: 0.15 };
    if (sunAltitude > -6) return { sky: '#0c2440', starAlpha: 0.4 };    // civil twilight
    if (sunAltitude > -12) return { sky: '#071628', starAlpha: 0.75 };  // nautical
    if (sunAltitude > -18) return { sky: '#030b14', starAlpha: 0.95 };  // astronomical
    return { sky: '#000000', starAlpha: 1 };
}

// Draws a polyline of horizontal-frame vectors, lifting the pen where a
// point is not drawable.
function strokeProjectedPath(ctx, project, vectors) {
    ctx.beginPath();
    let pen = false;
    vectors.forEach((h) => {
        const p = project(h);
        if (!p) {
            pen = false;
            return;
        }
        if (pen) ctx.lineTo(p[0], p[1]); else ctx.moveTo(p[0], p[1]);
        pen = true;
    });
    ctx.stroke();
}

// The ground (everything below the horizon) as filled 6px cells -- simple
// and right whatever the view direction -- then the horizon line.
function drawGrdViewGround(ctx, camera, project, width, height) {
    const step = 6;
    ctx.fillStyle = '#050505';
    for (let y = 0; y < height; y += step) {
        for (let x = 0; x < width; x += step) {
            if (grdViewBelowHorizon(camera, x + step / 2, y + step / 2, width, height)) {
                ctx.fillRect(x, y, step, step);
            }
        }
    }
    const horizon = [];
    for (let az = 0; az <= 360; az += 1) {
        horizon.push(horizontalVector(0, az));
    }
    ctx.strokeStyle = 'rgba(234, 158, 65, 0.8)';   // LCARS amber
    ctx.lineWidth = 1.5;
    strokeProjectedPath(ctx, project, horizon);
}

// Clips a ring of horizontal-frame unit vectors to the part of the sky in
// front of the viewer (dot with forward >= MIN_FORWARD), Sutherland-Hodgman
// against that plane. Projecting only the clipped part keeps every point
// finite -- the stereographic projection runs to infinity behind the
// viewer -- so a filled outline can't turn inside out. The clip edge lies
// well outside the canvas.
const MIN_FORWARD = -0.1;

//
// Where the ring leaves the front and comes back, the gap is closed along
// the clip circle itself (points with dot = MIN_FORWARD), not by a straight
// chord: a chord projects to a straight line that can cut right across the
// view, splitting the fill wrongly. The clip circle projects off-canvas.
function clipRingToFront(ring, forward) {
    const side = (h) => h[0] * forward[0] + h[1] * forward[1] + h[2] * forward[2] - MIN_FORWARD;
    const crossing = (a, b, sa, sb) => {
        const t = sa / (sa - sb);
        const p = [a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]), a[2] + t * (b[2] - a[2])];
        const n = Math.hypot(p[0], p[1], p[2]);
        return [p[0] / n, p[1] / n, p[2] / n];
    };
    // Points along the clip circle from a to b (both on it), by the shorter
    // way round, every 5 degrees or so.
    const arcAlongClip = (a, b) => {
        const c = MIN_FORWARD;
        const ua = [a[0] - c * forward[0], a[1] - c * forward[1], a[2] - c * forward[2]];
        const ub = [b[0] - c * forward[0], b[1] - c * forward[1], b[2] - c * forward[2]];
        const radius = Math.hypot(ua[0], ua[1], ua[2]) || 1;
        const e1 = ua.map((x) => x / radius);
        const e2 = [forward[1] * e1[2] - forward[2] * e1[1], forward[2] * e1[0] - forward[0] * e1[2], forward[0] * e1[1] - forward[1] * e1[0]];
        const angle = Math.atan2(ub[0] * e2[0] + ub[1] * e2[1] + ub[2] * e2[2], ub[0] * e1[0] + ub[1] * e1[1] + ub[2] * e1[2]);
        const steps = Math.ceil(Math.abs(angle) / (5 * DEG));
        const points = [];
        for (let s = 1; s < steps; s++) {
            const t = angle * s / steps;
            points.push([0, 1, 2].map((k) => c * forward[k] + radius * (Math.cos(t) * e1[k] + Math.sin(t) * e2[k])));
        }
        return points;
    };
    const out = [];
    let exit = null;        // where the ring last left the front
    let firstEntry = null;  // an entry seen before any exit (closes at the end)
    for (let i = 0; i < ring.length; i++) {
        const a = ring[i];
        const b = ring[(i + 1) % ring.length];
        const sa = side(a);
        const sb = side(b);
        if (sa >= 0) out.push(a);
        if ((sa >= 0) !== (sb >= 0)) {
            const p = crossing(a, b, sa, sb);
            if (sa >= 0) {          // leaving the front
                out.push(p);
                exit = p;
            } else {                // coming back
                if (exit) {
                    out.push(...arcAlongClip(exit, p));
                    exit = null;
                } else {
                    firstEntry = p;
                }
                out.push(p);
            }
        }
    }
    if (exit && firstEntry) {
        out.push(...arcAlongClip(exit, firstEntry));
    }
    return out;
}

// The galactic poles (J2000): always outside the Milky Way.
const GALACTIC_POLES = [equatorialUnit(192.8595, 27.1283), equatorialUnit(12.8595, -27.1283)];

// The Milky Way: each of its five brightness levels as one filled shape
// (its rings, even-odd), a faint white wash each, so the levels stack up
// into a brighter core.
//
// Its edges are loops running most of the way round the sky, and each
// clipped loop may enclose either of its two sides -- so a level's
// even-odd fill comes out either right or exactly inverted. The galactic
// pole in front of the viewer is always outside: if it lands inside the
// fill, the canvas rectangle is added to the path, which inverts it back.
function drawGrdViewMilkyWay(ctx, camera, project, toHorizontal, alpha, width, height) {
    const byLevel = new Map();
    grdViewCatalogue.milkyWay.forEach(({ level, ring }) => {
        if (!byLevel.has(level)) byLevel.set(level, []);
        byLevel.get(level).push(ring);
    });
    const poles = GALACTIC_POLES.map(toHorizontal);
    const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
    const pole = project(dot(poles[0], camera.forward) >= dot(poles[1], camera.forward) ? poles[0] : poles[1]);
    const ratio = ctx.getTransform().a;   // isPointInPath takes unscaled canvas px
    const margin = 4 * Math.max(width, height);

    ctx.save();
    ctx.fillStyle = `rgba(200, 210, 255, ${0.045 * alpha})`;
    byLevel.forEach((rings) => {
        const path = new Path2D();
        rings.forEach((ring) => {
            const clipped = clipRingToFront(ring.map(toHorizontal), camera.forward);
            let started = false;
            clipped.forEach((h) => {
                const p = project(h);
                if (!p) return;
                if (started) path.lineTo(p[0], p[1]); else path.moveTo(p[0], p[1]);
                started = true;
            });
            if (started) path.closePath();
        });
        if (pole && ctx.isPointInPath(path, pole[0] * ratio, pole[1] * ratio, 'evenodd')) {
            path.rect(-margin, -margin, width + 2 * margin, height + 2 * margin);
        }
        ctx.fill(path, 'evenodd');
    });
    ctx.restore();
}

// The deep-sky objects as the eye sees them: a soft smudge of light, sized
// to the object and brighter for brighter objects -- elongated like the
// symbol for galaxies, faintly blue-white for nebulae, warm white for the
// rest. Always drawn (HDE DSO hides only the symbols and names), beneath
// the stars so cluster members sit on top.
function drawGrdViewDeepSkyGlow(ctx, camera, project, toHorizontal, alpha) {
    ctx.save();
    grdViewCatalogue.deepSky.forEach((o) => {
        const h = toHorizontal(o.v);
        if (h[2] < 0) return;
        const p = project(h);
        const [, type, , , mag, dim] = o;
        const r = Math.max(4, (dim || 10) / 60 * DEG * camera.scale);
        if (!p || p[0] < -r || p[0] > ctx.canvas.clientWidth + r || p[1] < -r || p[1] > ctx.canvas.clientHeight + r) return;
        const strength = Math.max(0.06, Math.min(0.35, 0.35 - mag * 0.05)) * alpha;
        const rgb = ['en', 'sfr', 'bn', 'rn', 'pn'].includes(type) ? '220, 235, 255' : '255, 245, 230';
        const galaxy = ['s', 'sd', 'i'].includes(type);
        ctx.save();
        ctx.translate(p[0], p[1]);
        if (galaxy) {
            ctx.rotate(-0.5);
            ctx.scale(1, 0.45);   // the same squash as the galaxy symbol
        }
        const glow = ctx.createRadialGradient(0, 0, 0, 0, 0, r);
        glow.addColorStop(0, `rgba(${rgb}, ${strength})`);
        glow.addColorStop(0.5, `rgba(${rgb}, ${strength * 0.45})`);
        glow.addColorStop(1, `rgba(${rgb}, 0)`);
        ctx.fillStyle = glow;
        ctx.beginPath();
        ctx.arc(0, 0, r, 0, 2 * Math.PI);
        ctx.fill();
        ctx.restore();
    });
    ctx.restore();
}

// Bright deep-sky objects: a symbol sized to the object (at least 5px),
// by type -- galaxies an ellipse, open clusters a dashed circle, globulars
// a circle with a cross, nebulae a square -- and the name.
function drawGrdViewDeepSky(ctx, camera, project, toHorizontal, onCanvas, alpha) {
    ctx.save();
    ctx.globalAlpha = alpha;
    ctx.strokeStyle = 'rgba(204, 153, 255, 0.85)';   // LCARS lavender
    ctx.fillStyle = 'rgba(204, 153, 255, 0.85)';
    ctx.lineWidth = 1;
    ctx.font = grdViewButtonFont();
    ctx.textAlign = 'left';
    grdViewCatalogue.deepSky.forEach((o) => {
        const h = toHorizontal(o.v);
        if (h[2] < 0) return;
        const p = project(h);
        if (!onCanvas(p)) return;
        const [name, type, , , , dim] = o;
        const r = Math.max(5, (dim || 10) / 60 * DEG * camera.scale);   // arcmin to px, as a radius
        ctx.beginPath();
        ctx.setLineDash([]);
        if (['s', 'sd', 'i'].includes(type)) {
            ctx.ellipse(p[0], p[1], r, r * 0.45, -0.5, 0, 2 * Math.PI);
        } else if (type === 'oc') {
            ctx.setLineDash([2, 3]);
            ctx.arc(p[0], p[1], r, 0, 2 * Math.PI);
        } else if (type === 'gc') {
            ctx.arc(p[0], p[1], r, 0, 2 * Math.PI);
            ctx.moveTo(p[0] - r, p[1]); ctx.lineTo(p[0] + r, p[1]);
            ctx.moveTo(p[0], p[1] - r); ctx.lineTo(p[0], p[1] + r);
        } else {
            ctx.rect(p[0] - r, p[1] - r, 2 * r, 2 * r);
        }
        ctx.stroke();
        ctx.setLineDash([]);
        ctx.fillText(name.toUpperCase(), p[0] + r + 3, p[1] - 3);
    });
    ctx.restore();
}

// The Moon in its phase, lit on the side facing the Sun. The lit area is
// the half-disc towards the Sun bounded by the terminator, an ellipse of
// half-width |1 - 2k| x radius (k = illuminated fraction): k = 0 new,
// 0.5 a half-moon (straight terminator), 1 full.
function drawGrdViewMoon(ctx, project, p, radius, moon, sun) {
    // Direction to the Sun on screen: project a point a little way from the
    // Moon along the great circle towards the Sun.
    const m = horizontalVector(moon.altitude, moon.azimuth);
    const s = horizontalVector(sun.altitude, sun.azimuth);
    const d = m[0] * s[0] + m[1] * s[1] + m[2] * s[2];
    const t = [s[0] - d * m[0], s[1] - d * m[1], s[2] - d * m[2]];
    const tn = Math.hypot(t[0], t[1], t[2]) || 1;
    const q = project([m[0] + 0.02 * t[0] / tn, m[1] + 0.02 * t[1] / tn, m[2] + 0.02 * t[2] / tn]);
    const angle = q ? Math.atan2(q[1] - p[1], q[0] - p[0]) : 0;
    const k = moon.phase;

    ctx.save();
    ctx.translate(p[0], p[1]);
    ctx.rotate(angle);   // the Sun now lies along +x
    ctx.fillStyle = '#2a2a2a';   // the unlit Moon, just visible
    ctx.beginPath();
    ctx.arc(0, 0, radius, 0, 2 * Math.PI);
    ctx.fill();
    ctx.fillStyle = moon.color;
    ctx.beginPath();
    for (let i = 0; i <= 32; i++) {   // lit limb, top to bottom through the Sun side
        const a = -Math.PI / 2 + Math.PI * i / 32;
        ctx.lineTo(radius * Math.cos(a), radius * Math.sin(a));
    }
    for (let i = 0; i <= 32; i++) {   // terminator, bottom back to top
        const a = Math.PI / 2 - Math.PI * i / 32;
        ctx.lineTo((1 - 2 * k) * radius * Math.cos(a), radius * Math.sin(a));
    }
    ctx.fill();
    ctx.restore();
}

// Name of the Moon's phase from its ecliptic phase angle (Astronomy
// Engine's MoonPhase: 0 new, 90 first quarter, 180 full, 270 last quarter).
function moonPhaseName(angle) {
    const names = ['NEW', 'WAXING CRESCENT', 'FIRST QUARTER', 'WAXING GIBBOUS',
                   'FULL', 'WANING GIBBOUS', 'LAST QUARTER', 'WANING CRESCENT'];
    return names[Math.floor(((angle + 22.5) % 360) / 45)];
}

function drawGrdViewSky() {
    const canvas = document.getElementById('grd-view-canvas');
    if (!canvas || typeof Astronomy === 'undefined' || !grdViewCatalogue || !observerLocation) {
        return;
    }
    const width = canvas.clientWidth;
    const height = canvas.clientHeight;
    if (!width || !height) {
        return;   // section hidden
    }
    const ratio = window.devicePixelRatio || 1;
    canvas.width = Math.round(width * ratio);
    canvas.height = Math.round(height * ratio);
    const ctx = canvas.getContext('2d');
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);

    const time = Astronomy.MakeTime(new Date());
    const observer = new Astronomy.Observer(observerLocation.latitude, observerLocation.longitude, 0);
    const rot = Astronomy.Rotation_EQJ_HOR(time, observer).rot;
    const toHorizontal = (v) => [
        rot[0][0] * v[0] + rot[1][0] * v[1] + rot[2][0] * v[2],
        rot[0][1] * v[0] + rot[1][1] * v[1] + rot[2][1] * v[2],
        rot[0][2] * v[0] + rot[1][2] * v[1] + rot[2][2] * v[2],
    ];
    const camera = grdViewCamera(width);
    const project = makeGrdViewProjector(camera, width, height);
    const onCanvas = (p) => p && p[0] > -10 && p[0] < width + 10 && p[1] > -10 && p[1] < height + 10;
    const bodies = computeGrdViewBodies(time, observer);
    const { sky, starAlpha } = skyStateForSun(bodies[0].altitude);

    ctx.fillStyle = sky;
    ctx.fillRect(0, 0, width, height);

    drawGrdViewMilkyWay(ctx, camera, project, toHorizontal, starAlpha, width, height);

    // Constellations: lines, then names, both faint so the stars lead.
    if (grdViewConstellationsVisible) {
        ctx.strokeStyle = 'rgba(153, 153, 255, 0.35)';   // LCARS periwinkle, faint
        ctx.lineWidth = 1;
        grdViewCatalogue.lines.forEach((line) => strokeProjectedPath(ctx, project, line.map(toHorizontal)));
        ctx.fillStyle = 'rgba(153, 153, 255, 0.65)';
        ctx.font = grdViewButtonFont();
        ctx.textAlign = 'center';
        grdViewCatalogue.constellations.forEach((c) => {
            const h = toHorizontal(c.v);
            const p = h[2] > 0 ? project(h) : null;
            if (onCanvas(p)) ctx.fillText(c[0].toUpperCase(), p[0], p[1]);
        });
    }

    drawGrdViewDeepSkyGlow(ctx, camera, project, toHorizontal, starAlpha);

    // Stars, faintest first so the brightest sit on top; names for the
    // brightest.
    ctx.save();
    ctx.globalAlpha = starAlpha;
    ctx.font = '11px Antonio, sans-serif';
    ctx.textAlign = 'left';
    for (let i = grdViewCatalogue.stars.length - 1; i >= 0; i--) {
        const star = grdViewCatalogue.stars[i];
        const h = toHorizontal(star.v);
        if (h[2] < 0) continue;
        const p = project(h);
        if (!onCanvas(p)) continue;
        ctx.fillStyle = starColorFromBv(star[3]);
        ctx.beginPath();
        ctx.arc(p[0], p[1], radiusForMagnitude(star[2]), 0, 2 * Math.PI);
        ctx.fill();
        if (grdViewStarNamesVisible && star[4] && star[2] < 1.6) {
            ctx.fillStyle = 'rgba(241, 194, 116, 0.8)';   // LCARS sand
            ctx.fillText(star[4].toUpperCase(), p[0] + 5, p[1] - 4);
        }
    }
    ctx.restore();

    if (grdViewDeepSkyVisible) {
        drawGrdViewDeepSky(ctx, camera, project, toHorizontal, onCanvas, starAlpha);
    }

    // Ground over everything below the horizon, then compass points.
    drawGrdViewGround(ctx, camera, project, width, height);
    ctx.fillStyle = '#ea9e41';
    ctx.font = '14px Antonio, sans-serif';
    ctx.textAlign = 'center';
    ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'].forEach((name, i) => {
        const p = project(horizontalVector(0, i * 45));
        if (onCanvas(p)) ctx.fillText(name, p[0], p[1] + 18);
    });

    grdViewSunAltitude = bodies[0].altitude;
    drawGrdViewSatellites();   // the overlay follows any change of view at once

    // Sun, Moon and planets above the horizon, labelled.
    ctx.font = '12px Antonio, sans-serif';
    ctx.textAlign = 'left';
    bodies.forEach((b) => {
        if (b.altitude < 0) return;
        const p = project(horizontalVector(b.altitude, b.azimuth));
        if (!onCanvas(p)) return;
        const radius = b.body === 'Sun' ? 9 : b.body === 'Moon' ? 10 : Math.max(2.5, radiusForMagnitude(b.mag));
        if (b.body === 'Moon') {
            drawGrdViewMoon(ctx, project, p, radius, b, bodies[0]);
        } else {
            ctx.fillStyle = b.color;
            ctx.beginPath();
            ctx.arc(p[0], p[1], radius, 0, 2 * Math.PI);
            ctx.fill();
        }
        ctx.fillStyle = '#ffcc99';   // LCARS peach
        ctx.fillText(b.label, p[0] + radius + 4, p[1] + 4);
    });

    renderGrdViewBodiesTable(bodies);
}

// HH:MM UTC, or a dash.
function formatUtcTime(date) {
    return date ? `${String(date.getUTCHours()).padStart(2, '0')}:${String(date.getUTCMinutes()).padStart(2, '0')}` : '—';
}

// Below the chart: the Sun, Moon and planets now. Bodies below the horizon
// are dimmed.
function renderGrdViewBodiesTable(bodies) {
    const table = document.getElementById('grd-view-bodies');
    if (!table) {
        return;
    }
    const distance = (b) => (b.body === 'Moon'
        ? `${Math.round(b.distAu * 149597870.7).toLocaleString('en-GB')} km`
        : `${b.distAu.toFixed(3)} AU`);
    table.innerHTML = `<thead><tr>
            <th>Body</th><th>Alt</th><th>Azm</th><th>Mag</th><th>Lit</th><th>Distance</th><th>Constellation</th><th>Rises (UTC)</th><th>Sets (UTC)</th>
        </tr></thead>
        <tbody>${bodies.map((b) => `<tr${b.altitude < 0 ? ' class="below-horizon"' : ''}>
            <td>${b.label}</td>
            <td>${b.altitude.toFixed(1)}</td>
            <td>${b.azimuth.toFixed(1)}</td>
            <td>${b.mag.toFixed(1)}</td>
            <td>${b.body === 'Sun' ? '—' : `${Math.round(b.phase * 100)}%${b.phaseName ? ` ${b.phaseName}` : ''}`}</td>
            <td>${distance(b)}</td>
            <td>${b.constellation}</td>
            <td>${formatUtcTime(b.rise)}</td>
            <td>${formatUtcTime(b.set)}</td>
        </tr>`).join('')}</tbody>`;
}

function toggleGrdViewStarNames() {
    grdViewStarNamesVisible = !grdViewStarNamesVisible;
    drawGrdViewSky();
}

function toggleGrdViewDeepSky() {
    grdViewDeepSkyVisible = !grdViewDeepSkyVisible;
    drawGrdViewSky();
}

function toggleGrdViewConstellations() {
    grdViewConstellationsVisible = !grdViewConstellationsVisible;
    drawGrdViewSky();
}

registerPanelControls('grd-view', {
    defaultAreaMode: 'custom',
    renderDefaultArea: renderGrdViewDefaultArea,
    buttons: [
        {
            label: 'USR LOCN',
            color: 'var(--peach)',
            onClick: () => toggleUserLocationForm(renderGrdViewDefaultArea),
        },
        {
            label: 'CONST',
            color: 'var(--bluey)',
            // Names the action: HDE CONST while they are shown.
            getText: () => (grdViewConstellationsVisible ? 'HDE CONST' : 'SHW CONST'),
            onClick: toggleGrdViewConstellations,
        },
        {
            label: 'DSO',
            color: 'var(--bluey)',
            // Deep-sky objects; names the action, like the CONST button.
            getText: () => (grdViewDeepSkyVisible ? 'HDE DSO' : 'SHW DSO'),
            onClick: toggleGrdViewDeepSky,
        },
        {
            label: 'NAMES',
            color: 'var(--bluey)',
            // The bright-star names; names the action, like CONST and DSO.
            getText: () => (grdViewStarNamesVisible ? 'HDE NAMES' : 'SHW NAMES'),
            onClick: toggleGrdViewStarNames,
        },
        // The satellite buttons: a second 2 x 2 group, to the left of the
        // four above (grouped buttons render into #control-area-groups, as
        // ON-ORBIT's chart groups do) -- STATUS over SPACEX, KIND over
        // HIGHLIGHT OBJECTS. The filters are labelled with their current
        // setting, as on ON-ORBIT.
        {
            label: 'STATUS', color: 'var(--tng-sand)', group: 'grd-view-sats-1',
            getText: () => GRD_VIEW_STATUS_BUTTONS[grdViewSatFilters.status],
            onClick: () => {
                grdViewSatFilters.status = grdViewSatFilters.status === 'active' ? 'all' : 'active';
                drawGrdViewSatellites();
            },
        },
        {
            label: 'KIND', color: 'var(--tng-periwinkle)', group: 'grd-view-sats-2',
            // Three-way: SAT ONLY -> ALL S-CRFT -> ALL-OBJ -> ...
            getText: () => GRD_VIEW_KIND_BUTTONS[grdViewSatFilters.kind],
            onClick: () => {
                const next = (GRD_VIEW_KINDS.indexOf(grdViewSatFilters.kind) + 1) % GRD_VIEW_KINDS.length;
                grdViewSatFilters.kind = GRD_VIEW_KINDS[next];
                drawGrdViewSatellites();
            },
        },
        {
            label: 'SPACEX', color: 'var(--tng-lavender)', group: 'grd-view-sats-1',
            getText: () => (grdViewSatFilters.spacex === 'with' ? 'INC SPACEX' : 'EX SPACEX'),
            onClick: () => {
                grdViewSatFilters.spacex = grdViewSatFilters.spacex === 'with' ? 'without' : 'with';
                drawGrdViewSatellites();
            },
        },
        {
            label: 'HIGHLIGHT OBJECTS', color: 'var(--tng-amber)', group: 'grd-view-sats-2',
            isSelected: () => grdViewTargetsShown,   // lit white while on
            onClick: toggleGrdViewTargets,
        },
    ],
});

// Called by openGrdViewSection() after the section is shown: geolocates by
// IP if no location is set yet, loads the sky catalogue, then draws, and
// keeps redrawing every GRD_VIEW_REFRESH_MS while the section is open.
async function initGrdView() {
    await ensureObserverLocation();
    if (!document.getElementById('user-location-form')) {
        renderGrdViewDefaultArea();
    }
    try {
        await loadGrdViewCatalogue();
    } catch (error) {
        console.error('Could not load the sky catalogue:', error);
        const table = document.getElementById('grd-view-bodies');
        if (table) table.innerHTML = '<tbody><tr><td>ERR: COULD NOT LOAD SKY CATALOGUE</td></tr></tbody>';
        return;
    }
    drawGrdViewSky();
    const canvas = document.getElementById('grd-view-canvas');
    if (canvas && !canvas.dataset.clickBound) {
        canvas.addEventListener('click', onGrdViewCanvasClick);
        canvas.dataset.clickBound = '1';
    }
    startGrdViewSatellites()
        .then(requestGrdViewSatellites)
        .catch((error) => console.error('Could not load satellites:', error));
    clearInterval(grdViewSatTimer);
    grdViewSatTimer = setInterval(() => {
        const section = document.querySelector('main [data-section="grd-view"]');
        if (section && section.style.display !== 'none') {
            requestGrdViewSatellites();
        } else {
            clearInterval(grdViewSatTimer);
        }
    }, GRD_VIEW_SAT_REFRESH_MS);
    clearInterval(grdViewRefreshTimer);
    grdViewRefreshTimer = setInterval(() => {
        const section = document.querySelector('main [data-section="grd-view"]');
        if (section && section.style.display !== 'none') {
            drawGrdViewSky();
        } else {
            clearInterval(grdViewRefreshTimer);
        }
    }, GRD_VIEW_REFRESH_MS);
}

window.addEventListener('resize', drawGrdViewSky);
