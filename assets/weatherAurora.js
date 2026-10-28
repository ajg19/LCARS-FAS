/* ==========================================================================
   WEATHER AURORA -- the charts of AURORAE: where and whether the aurora can be seen, anywhere on Earth.

   NOW:         THE OVAL (the OVATION model's oval on a polar map or a globe, with its two edges), YOUR SKY TONIGHT (darkness,
                Moon, the aurora index at the visitor's place, Kp now against the Kp needed), ACTIVITY (hemispheric power with Kp).
   PREDICTIVE:  THE NEXT HOUR (the solar wind about to arrive, with the countdown), THE NEXT NIGHTS (the Kp forecast with the Kp the
                visitor needs outlined, the 27-day recurrence, the Earth-directed CMEs).

   The oval, its contours and its two edges are drawn on the round maps of weatherMap.js. The GLOBE, N POLE and S POLE buttons sit
   under the text beside the map (ovalHtml, AURORA_CONTROL); the globe turns by dragging.

   Nothing here is specific to one place: the visitor's place (USR LOCN) adds a ring and the personal cards, without it the page
   still shows both hemispheres.

   Needs weatherCharts.js, weatherEarth.js (K3, K4, K7, the Kp needed) and weatherMap.js; loaded by weatherPanel.js the first time
   AURORAE is opened.
   ========================================================================== */

const AURORA_MIN_LONS = 10;                       // Spock: an oval edge exists only where the oval reaches it at this many longitudes
const AURORA_LEVELS = [5, 10, 20, 40, 60];        // contour lines, aurora index
const AURORA_BANDS = [
    { from: 5, colour: 'var(--green)', opacity: 0.5, label: '5 to 10: faint' },
    { from: 10, colour: 'var(--tng-sand)', opacity: 0.9, label: '10 to 20' },
    { from: 20, colour: 'var(--tng-amber)', opacity: 0.95, label: '20 to 40' },
    { from: 40, colour: 'var(--tng-salmon)', opacity: 1, label: '40 to 60' },
    { from: 60, colour: 'var(--tng-alert)', opacity: 1, label: '60 and over' },
];
const AURORA_DARK_SUN_DEG = -12;                  // the Sun this far below the horizon: dark enough for faint aurora
const AURORA_MAP_MAX = 640;
const AURORA_VIEW = { globeLat: null, globeLon: null };   // where the globe is turned to; null until first drawn
// The view buttons' state: 'auto' (the visitor's hemisphere, north without a location), 'north', 'south' or 'globe'.
const AURORA_CONTROL = { view: 'auto' };

// One of the three buttons under the oval's text chose a view: redraw the oval card (its tag and the lit button change too).
function auroraSetView(view) {
    AURORA_CONTROL.view = view;
    const slot = document.getElementById('weather-au-oval');
    if (slot && slot.chartData) {
        weatherRedraw(slot);
    }
}

/* --- the oval, as numbers ------------------------------------------------------------------------------- */

function auroraColour(index) {
    let found = null;
    for (const band of AURORA_BANDS) {
        if (index >= band.from) {
            found = [band.colour, band.opacity];
        }
    }
    return found;
}

const auroraGrid = (map) => ({ values: map.rows, latFirst: map.latMin, latStep: map.step, lonMin: map.lonMin, lonStep: map.step });
const auroraWest = (lon) => (lon > 179 ? lon - 360 : lon);

// The peak of a hemisphere and where (the highest index; among equal ones the lowest |latitude|, then the lowest longitude), as the
// ingester takes it, and the edge of the visible oval as Spock defined it: the smoothed edge latitudes are used only where the oval
// reaches them at AURORA_MIN_LONS longitudes or more; the edge is the lowest latitude (the reach) and its longitude the middle of the
// longest run at the reach. tier 'edge' is the index-10 edge (naked eye), 'faint' the index-5 edge (camera only).
function auroraHemisphere(map, hemisphere) {
    const north = hemisphere === 'N';
    let best = null;
    for (let lat = north ? 1 : -90; north ? lat <= 90 : lat <= -1; lat += 1) {
        const row = map.rows[lat - map.latMin];
        for (let lon = 0; lon < 360; lon += 1) {
            const v = row[lon];
            if (best === null || v > best.index || (v === best.index && Math.abs(lat) < Math.abs(best.lat))) {
                best = { index: v, lat, lon };
            }
        }
    }
    const edgeOf = (list) => {
        const cover = list.filter((x) => x !== null && x !== undefined).length;
        if (cover < AURORA_MIN_LONS) {
            return null;
        }
        const reach = Math.min(...list.filter((x) => x !== null && x !== undefined));
        const at = list.map((x) => x === reach);
        let begin = 0;
        let length = 360;
        if (!at.every(Boolean)) {
            const first = at.indexOf(false);
            length = 0;
            let run = null;
            for (let i = 1; i <= 360; i += 1) {
                const lon = (first + i) % 360;
                if (at[lon]) {
                    run = run === null ? [lon, 1] : [run[0], run[1] + 1];
                    if (run[1] > length) {
                        [begin, length] = run;
                    }
                } else {
                    run = null;
                }
            }
        }
        return { lat: reach, lon: auroraWest((begin + Math.floor(length / 2)) % 360), cover };
    };
    return { hemisphere, peak: { index: best.index, lat: best.lat, lon: auroraWest(best.lon) },
        edge: edgeOf(north ? map.edgeN : map.edgeS), faint: edgeOf(north ? map.edgeFaintN : map.edgeFaintS) };
}

const auroraDeg = (lat, lon) => `${Math.abs(lat).toFixed(0)}${lat >= 0 ? 'N' : 'S'}, ${Math.abs(lon).toFixed(0)}${lon >= 0 ? 'E' : 'W'}`;

// What the oval means for someone in that hemisphere, in the words Spock settled (the edge numbers are degrees of latitude).
function auroraWording(h, validMs) {
    const s = h.hemisphere === 'N' ? 'N' : 'S';
    if (h.edge) {
        return `Aurora possible overhead poleward of ${h.edge.lat.toFixed(0)}${s}, low on the horizon from about ${(h.edge.lat - 5).toFixed(0)}${s}, if the sky is dark.`;
    }
    if (h.faint) {
        return `Faint aurora only. Cameras may catch it, the eye probably not, poleward of ${h.faint.lat.toFixed(0)}${s} near longitude ${Math.abs(h.faint.lon).toFixed(0)}${h.faint.lon >= 0 ? 'E' : 'W'}, if the sky is dark.`;
    }
    return `No visible aurora expected. The oval peaks at index ${h.peak.index} near ${auroraDeg(h.peak.lat, h.peak.lon)} (forecast for ${chartTimeText(validMs).slice(11)}).`;
}

// The oval's latitude on the visitor's meridian: { index here, edge lat there, hemisphere } from the stored map.
function auroraAt(map, lat, lon) {
    const row = map.rows[Math.min(map.rows.length - 1, Math.max(0, Math.round(lat - map.latMin)))];
    const col = ((Math.round(lon) % 360) + 360) % 360;
    const list = lat >= 0 ? map.edgeN : map.edgeS;
    const edge = list[col];
    return { index: row[col], edge: edge === null || edge === undefined ? null : (lat >= 0 ? edge : -edge) };
}

/* --- the Sun and the Moon, computed here --------------------------------------------------------------------- */

function auroraAltitude(decDeg, subLonDeg, lat, lon) {
    const rad = Math.PI / 180;
    const s = Math.sin(lat * rad) * Math.sin(decDeg * rad) + Math.cos(lat * rad) * Math.cos(decDeg * rad) * Math.cos((lon - subLonDeg) * rad);
    return Math.asin(Math.max(-1, Math.min(1, s))) / rad;
}

const auroraSunAltitude = (ms, lat, lon) => { const s = weatherSubsolarPoint(ms); return auroraAltitude(s.lat, s.lon, lat, lon); };

// The Moon's sub-lunar point and illuminated fraction (the truncated series of the Astronomical Almanac: the position is good to about
// half a degree, the altitude to about a degree with the parallax left out; the phase to a per cent or so).
function auroraMoon(ms) {
    const rad = Math.PI / 180;
    const d = (ms - Date.UTC(2000, 0, 1, 12)) / 86400000;
    const eclLon = (218.316 + 13.176396 * d + 6.289 * Math.sin((134.963 + 13.064993 * d) * rad)) * rad;
    const eclLat = 5.128 * Math.sin((93.272 + 13.229350 * d) * rad) * rad;
    const eps = (23.4393 - 3.563e-7 * d) * rad;
    const ra = Math.atan2(Math.sin(eclLon) * Math.cos(eps) - Math.tan(eclLat) * Math.sin(eps), Math.cos(eclLon));
    const dec = Math.asin(Math.sin(eclLat) * Math.cos(eps) + Math.cos(eclLat) * Math.sin(eps) * Math.sin(eclLon));
    const lon = ((ra / rad - (280.46061837 + 360.98564736629 * d)) % 360 + 540) % 360 - 180;
    const sun = weatherSubsolarPoint(ms);
    const cosElong = Math.sin(dec) * Math.sin(sun.lat * rad) + Math.cos(dec) * Math.cos(sun.lat * rad) * Math.cos((lon - sun.lon) * rad);
    // waxing while the Moon is east of the Sun in the sky (its right ascension is ahead): its sub-point then lies east of the sub-solar one
    const waxing = ((lon - sun.lon + 540) % 360 - 180) > 0;
    return { lat: dec / rad, lon, fraction: (1 - cosElong) / 2, waxing };
}

const auroraMoonAltitude = (ms, lat, lon) => { const m = auroraMoon(ms); return auroraAltitude(m.lat, m.lon, lat, lon); };

function auroraPhaseName(fraction, waxing) {
    if (fraction < 0.03) { return 'new Moon'; }
    if (fraction > 0.97) { return 'full Moon'; }
    if (Math.abs(fraction - 0.5) < 0.06) { return waxing ? 'first quarter' : 'last quarter'; }
    return `${waxing ? 'waxing' : 'waning'} ${fraction < 0.5 ? 'crescent' : 'gibbous'}`;
}

/* --- the oval map ------------------------------------------------------------------------------------------- */

const ovalTip = [
    ['What', 'NOAA\'s model of where the aurora is, on a map of the polar region or of the whole globe (the GLOBE, N POLE and S POLE buttons under the text beside the map; drag the globe to turn it). Colour is the '
        + '<b>aurora index</b> (0 to 100, the model\'s intensity scale, not a percentage): below 5 nothing is drawn, 5 to 9 is dim, 10 and over is full colour, and the thin lines are contours at 5, 10, 20, 40 and 60. '
        + 'The two heavier lines are the <b>edges</b> of the oval: solid, where the index falls to 10 (the naked-eye limit); dashed, where it falls to 5 (camera only). The shading is night (the Sun below the horizon, darker below 12 degrees), worked out here for the time of the map.'],
    ['The model', 'OVATION Prime (Newell et al. 2014), run by NOAA SWPC: the energy and number flux of electrons and ions falling into the atmosphere, fitted to years of satellite measurements and driven by the solar wind '
        + 'measured at L1 by NOAA SOLAR-1 (about 1.5 million km sunward of Earth, about 5 light-seconds). It gives the oval for a time 30 to 90 minutes after the solar wind it was run on: there is no separate "now" map, '
        + 'and this one already is the short forecast. It is a statistical model, not an observation, and smooths away individual arcs and substorms.'],
    ['The edge', 'The edge exists only where the oval reaches it at 10 or more longitudes (otherwise no visible aurora is expected anywhere in that hemisphere). It is the equatorward limit of the oval, taken from the lowest latitude '
        + 'and smoothed in longitude; "low on the horizon from about 5 degrees nearer the equator" is the rule of thumb for the glow seen from further away. A bright, dark, clear sky is still needed: this is where it can happen, not a promise.'],
    ['Hemispheric power', 'From NOAA\'s polar-orbiting satellites (about 850 km up, 0.003 light-seconds from Earth), the total power of the particles in each hemisphere: more power, a brighter and wider oval.'],
    ['Cite', 'NOAA Space Weather Prediction Center, services.swpc.noaa.gov (OVATION aurora forecast); Newell, P. T., Liou, K., Zhang, Y., Sotirelis, T., Paxton, L. J. and Mitchell, E. J. (2014), Space Weather 12, 368.'],
];

async function loadOval() {
    const [payload, coast, north, south] = await Promise.all([weatherMapData('ovation'), weatherCoastRings(), weatherSeries('hemiPowerNorth', '24h'), weatherSeries('hemiPowerSouth', '24h')]);
    const last = (series) => (series.points.length ? series.points[series.points.length - 1] : null);
    return { map: payload ? payload.map : null, coast, power: { N: last(north), S: last(south) }, loadedAt: Date.now(), contours: null };
}

// The contour lines of the stored map, made once per map.
function auroraContours(data) {
    if (!data.contours) {
        data.contours = AURORA_LEVELS.map((level) => ({ level, polylines: weatherContours(auroraGrid(data.map), level) }));
    }
    return data.contours;
}

// The sunlit/twilight/dark classes on a 2-degree grid (0 day, 1 night, 2 dark): rows outside the picture are left out.
function auroraNightLayer(ms, proj) {
    const values = [];
    const sun = weatherSubsolarPoint(ms);
    for (let i = 0; i < 90; i += 1) {
        const lat = -89 + 2 * i;
        if (proj.kind === 'north' && lat < proj.latLimit - 2) { values.push(null); continue; }
        if (proj.kind === 'south' && lat > -proj.latLimit + 2) { values.push(null); continue; }
        const row = [];
        for (let j = 0; j < 180; j += 1) {
            const alt = auroraAltitude(sun.lat, sun.lon, lat, -179 + 2 * j);
            row.push(alt < AURORA_DARK_SUN_DEG ? 2 : alt < 0 ? 1 : 0);
        }
        values.push(row);
    }
    return { values, latFirst: -89, latStep: 2, lonMin: -179, lonStep: 2, colourAt: (v) => (v === 2 ? ['#000', 0.62] : v === 1 ? ['#000', 0.32] : null) };
}

function auroraEdgeLines(map) {
    const line = (list, sign) => {
        const out = [];
        let cur = [];
        for (let lon = 0; lon <= 360; lon += 1) {
            const v = list[lon % 360];
            if (v === null || v === undefined) {
                if (cur.length) { out.push(cur); }
                cur = [];
            } else {
                cur.push([sign * v, lon]);
            }
        }
        if (cur.length) { out.push(cur); }
        return out;
    };
    const lines = [];
    const n = auroraHemisphere(map, 'N');
    const s = auroraHemisphere(map, 'S');
    if (n.edge) { lines.push({ polylines: line(map.edgeN, 1), stroke: 'var(--space-white)', width: 2.2 }); }
    if (s.edge) { lines.push({ polylines: line(map.edgeS, -1), stroke: 'var(--space-white)', width: 2.2 }); }
    if (n.faint) { lines.push({ polylines: line(map.edgeFaintN, 1), stroke: 'var(--tng-ice)', width: 1.8, dash: '6 4' }); }
    if (s.faint) { lines.push({ polylines: line(map.edgeFaintS, -1), stroke: 'var(--tng-ice)', width: 1.8, dash: '6 4' }); }
    return lines;
}

// The view the buttons chose: 'globe', 'north' or 'south' (AURORA_CONTROL, weatherPanel.js), the default being the visitor's hemisphere.
function auroraViewKind() {
    if (AURORA_CONTROL.view === 'auto') {
        const place = weatherPlace();
        return place && place.lat < 0 ? 'south' : 'north';
    }
    return AURORA_CONTROL.view;
}

function auroraMapMarkup(data, size) {
    const kind = auroraViewKind();
    const place = weatherPlace();
    const validMs = Date.parse(data.map.forecast);
    const centreLon = place ? place.lon : 0;
    if (kind === 'globe' && AURORA_VIEW.globeLat === null) {
        AURORA_VIEW.globeLat = place ? Math.max(-80, Math.min(80, place.lat)) : 65;
        AURORA_VIEW.globeLon = place ? place.lon : auroraHemisphere(data.map, 'N').peak.lon;
    }
    const projection = weatherProjection({ kind, size, centreLat: AURORA_VIEW.globeLat, centreLon: AURORA_VIEW.globeLon, rotateLon: centreLon, latLimit: 30 });
    const lines = auroraContours(data).map((c) => ({ polylines: c.polylines, stroke: 'var(--space-white)', width: 0.7, opacity: 0.55 })).concat(auroraEdgeLines(data.map));
    const markers = place ? [{ lat: place.lat, lon: place.lon, label: 'YOU', color: 'var(--tng-ice)' }] : [];
    const hover = (lat, lon) => {
        const there = auroraAt(data.map, lat, lon);
        const alt = auroraSunAltitude(validMs, lat, lon);
        const word = there.index >= 10 ? 'visible if the sky is dark' : there.index >= 5 ? 'faint' : 'none expected';
        return `${auroraDeg(lat, lon)}: aurora index ${there.index} (${word}); Sun ${alt.toFixed(0)} degrees ${alt > 0 ? 'above' : 'below'} the horizon${alt < AURORA_DARK_SUN_DEG ? ' (dark)' : ''}`;
    };
    const drag = kind === 'globe' ? (dx, dy) => {
        const perPx = 180 / Math.PI / projection.R;
        AURORA_VIEW.globeLon = (((AURORA_VIEW.globeLon - dx * perPx + 540) % 360) + 360) % 360 - 180;
        AURORA_VIEW.globeLat = Math.max(-85, Math.min(85, AURORA_VIEW.globeLat + dy * perPx));
        auroraRedrawMap();
    } : null;
    return weatherSphereSvg({ id: 'aurora-map', size, projection, coast: data.coast, markers, hoverText: hover, drag,
        title: `Auroral oval, ${kind === 'globe' ? 'globe' : kind === 'north' ? 'north polar map' : 'south polar map'}`,
        layers: [auroraNightLayer(validMs, projection), { ...auroraGrid(data.map), colourAt: auroraColour }], lines });
}

function auroraMapSize(width) {
    return Math.min(AURORA_MAP_MAX, Math.max(320, Math.round(width * 0.6)));
}

// A button changed the view, or the globe was dragged: redraw the map only.
function auroraRedrawMap() {
    const slot = document.getElementById('weather-au-oval');
    const box = document.getElementById('aurora-map-box');
    if (slot && box && slot.chartData && slot.chartData.map) {
        box.innerHTML = auroraMapMarkup(slot.chartData, auroraMapSize(chartWidth(slot, 480)));
    }
}

function auroraHemisphereTiles(data) {
    const validMs = Date.parse(data.map.forecast);
    return ['N', 'S'].map((hemi) => {
        const h = auroraHemisphere(data.map, hemi);
        const s = hemi;
        const power = data.power[hemi];
        const edge = h.edge ? `${h.edge.lat.toFixed(0)}${s}` : h.faint ? `${h.faint.lat.toFixed(0)}${s} (faint)` : '--';
        return `<div class="aurora-hemisphere"><div class="weather-tile-label">${hemi === 'N' ? 'NORTHERN' : 'SOUTHERN'} HEMISPHERE</div><div class="weather-tiles">`
            + weatherTile('PEAK INDEX', String(h.peak.index), `near ${auroraDeg(h.peak.lat, h.peak.lon)}`)
            + weatherTile('EQUATORWARD EDGE', edge, h.edge ? `index 10, near ${Math.abs(h.edge.lon).toFixed(0)}${h.edge.lon >= 0 ? 'E' : 'W'}` : h.faint ? 'index 5 only' : 'no edge')
            + weatherTile('POWER (GW)', power ? power[1].toFixed(0) : '--', power ? weatherAgo(power[0], data.loadedAt) : 'no data')
            + `</div><p class="weather-status">${auroraWording(h, validMs)}</p></div>`;
    }).join('');
}

function ovalHtml(data, width) {
    if (!data.map) {
        return WEATHER_NO_DATA;
    }
    const kind = auroraViewKind();
    const validMs = Date.parse(data.map.forecast);
    const legend = AURORA_BANDS.map((b) => ({ color: b.colour, label: b.label })).concat([{ color: 'var(--space-white)', label: 'edge: index 10 (naked eye)' }, { color: 'var(--tng-ice)', label: 'dashed: index 5 (camera only)' }]);
    const views = [['globe', 'GLOBE'], ['north', 'N POLE'], ['south', 'S POLE']];
    const buttons = `<div class="weather-switches aurora-view-switch" role="group" aria-label="Map view">${views.map(([view, label]) => `<button type="button" class="weather-switch${view === kind ? ' is-on' : ''}" `
        + `aria-pressed="${view === kind}" onclick="auroraSetView('${view}')">${label}</button>`).join('')}</div>`;
    const body = `<div class="weather-map-side"><div id="aurora-map-box">${auroraMapMarkup(data, auroraMapSize(width))}</div><div class="aurora-summary">${auroraHemisphereTiles(data)}${buttons}</div></div>`;
    return chartTipFrameHtml({ title: 'THE OVAL', tag: `${kind === 'globe' ? 'GLOBE' : kind === 'north' ? 'N POLE' : 'S POLE'} - MODEL FOR ${chartTimeText(validMs).slice(11)}`, tip: ovalTip, legend, svg: body,
        credit: `NOAA SWPC OVATION Prime, driven by NOAA SOLAR-1 at L1 (about 5 light-seconds); valid ${chartTimeText(validMs)}, from observations at ${chartTimeText(Date.parse(data.map.obs))}. A model, not an observation. Night shading is computed here.` });
}

/* --- YOUR SKY TONIGHT ------------------------------------------------------------------------------------------- */

const skyTip = [
    ['What', 'The next 24 hours at your place: the Sun\'s altitude (aurora needs the Sun below about 12 degrees, the shaded dark hours) and the Moon\'s (a bright Moon above the horizon washes out faint aurora), '
        + 'and, beside it, the aurora index the model gives your place now and the Kp you would need. All times UTC.'],
    ['Computed here', 'The Sun and Moon are worked out in your browser from the time and your place (the Moon from a short series, good to about a degree in altitude, parallax left out; the phase to a per cent or so). Nothing is fetched.'],
    ['Kp needed', 'NOAA\'s rule of thumb for the geomagnetic latitude where aurora is commonly seen at each Kp: Kp 5 (G1) 60 degrees, Kp 6 55, Kp 7 50, Kp 8 45, Kp 9 40; Kp 4 about 65; 67 degrees and poleward at Kp 3 or less. '
        + 'Geomagnetic latitude is found from a tilted-dipole model of the field (good to a few degrees). The Kp shown for now is NOAA\'s estimate for the current 3-hour block.'],
    ['Limits', 'The model\'s aurora index and the Kp rule are different ways of asking the same question and will not always agree. Darkness, cloud and the Moon are what actually decide, and clouds are not known here.'],
    ['Cite', 'NOAA Space Weather Prediction Center, Space Weather Scales (G1 to G5) and OVATION; Meeus, J., Astronomical Algorithms (Sun and Moon).'],
];

async function loadSky() {
    const place = weatherPlace();
    if (!place) {
        return { place: null, loadedAt: Date.now() };
    }
    const [payload, kp] = await Promise.all([weatherMapData('ovation'), weatherSeries('swpcKp', '3d', true)]);
    return { place, map: payload ? payload.map : null, kp, loadedAt: Date.now() };
}

function skyHtml(data, width) {
    if (!data.place) {
        return satNeedLocation('YOUR SKY TONIGHT', skyTip);
    }
    const { lat, lon } = data.place;
    const now = data.loadedAt;
    const t0 = now;
    const t1 = now + 24 * 3600000;
    const step = 10 * 60000;
    const sun = [];
    const moon = [];
    const dark = [];
    let from = null;
    for (let t = t0; t <= t1; t += step) {
        const a = auroraSunAltitude(t, lat, lon);
        sun.push([t, a]);
        moon.push([t, auroraMoonAltitude(t, lat, lon)]);
        if (a < AURORA_DARK_SUN_DEG && from === null) { from = t; }
        if ((a >= AURORA_DARK_SUN_DEG || t + step > t1) && from !== null) { dark.push([from, a >= AURORA_DARK_SUN_DEG ? t : t1]); from = null; }
    }
    const axis = { min: -60, max: 60, ticks: [-60, -30, 0, 30, 60] };
    const panels = [
        { height: 95, left: { ...axis, label: 'SUN ALTITUDE (DEG)', color: 'var(--tng-sand)' }, lines: [{ axis: 'left', value: AURORA_DARK_SUN_DEG, label: 'dark below -12', color: 'var(--tng-violet)' }],
          marks: [{ type: 'shade', runs: dark, color: 'var(--tng-violet)' }, { type: 'line', axis: 'left', points: sun, color: 'var(--tng-sand)', width: 2 }] },
        { height: 95, left: { ...axis, label: 'MOON ALTITUDE (DEG)', color: 'var(--tng-ice)' }, marks: [{ type: 'line', axis: 'left', points: moon, color: 'var(--tng-ice)', width: 2 }] },
    ];
    const moonNow = auroraMoon(now);
    const phase = `${(moonNow.fraction * 100).toFixed(0)}% lit, ${auroraPhaseName(moonNow.fraction, moonNow.waxing)}`;
    const hover = (ms) => `${chartTimeText(ms)}\nSun ${auroraSunAltitude(ms, lat, lon).toFixed(0)} degrees\nMoon ${auroraMoonAltitude(ms, lat, lon).toFixed(0)} degrees, ${(auroraMoon(ms).fraction * 100).toFixed(0)}% lit`;
    const svg = timePanelsSvg({ width: Math.round(width * 0.64), t0, t1, panels, hoverText: hover, title: 'Sun and Moon altitude, next 24 hours' });
    const there = data.map ? auroraAt(data.map, lat, lon) : null;
    const magLat = geomagneticLat(lat, lon);
    const needed = requiredKpAt(magLat);
    const observed = data.kp.points.filter((p, i) => !/predicted/.test(data.kp.q[i] || '') && p[0] <= now && p[1] !== null);
    const kpNow = observed.length ? observed[observed.length - 1][1] : null;
    const bar = (label, value, colour) => `<div class="weather-prob-cell aurora-kp-bar" title="${escapeChartText(`${label}: ${value === null ? 'no data' : value === Infinity ? 'more than 9' : value.toFixed(1)}`)}">`
        + `<span class="weather-prob-bar" style="width:${value === null ? 0 : Math.min(100, value / 9 * 100)}%;background:${colour}"></span><span class="weather-prob-text">${label} ${value === null ? '--' : value === Infinity ? '9+' : value.toFixed(1)}</span></div>`;
    const sunNow = auroraSunAltitude(now, lat, lon);
    const edgeText = there && there.edge !== null ? `Oval edge at your longitude: ${Math.abs(there.edge).toFixed(0)}${there.edge >= 0 ? 'N' : 'S'}, ${Math.abs(Math.abs(lat) - Math.abs(there.edge)).toFixed(0)} degrees ${Math.abs(lat) >= Math.abs(there.edge) ? 'equatorward of you (you are poleward of it).' : 'poleward of you.'}` : 'No oval edge at your longitude.';
    const side = `<div class="weather-tiles weather-tiles-column">`
        + weatherTile('AURORA INDEX HERE', there ? String(there.index) : '--', there ? (there.index >= 10 ? 'visible if the sky is dark' : there.index >= 5 ? 'faint: cameras' : 'none expected') : 'no map held')
        + weatherTile('SUN NOW (DEG)', sunNow.toFixed(0), sunNow < AURORA_DARK_SUN_DEG ? 'dark' : sunNow < 0 ? 'twilight' : 'daylight')
        + weatherTile('MOON NOW', `${(moonNow.fraction * 100).toFixed(0)}%`, auroraPhaseName(moonNow.fraction, moonNow.waxing))
        + weatherTile('GEOMAGNETIC LATITUDE', `${Math.abs(magLat).toFixed(0)}${magLat >= 0 ? 'N' : 'S'}`, 'dipole model') + `</div>`
        + `<div class="aurora-kp"><div class="weather-tile-label">KP NOW AGAINST KP NEEDED HERE</div>${bar('Kp now', kpNow, kpNow !== null && kpNow >= needed ? 'var(--tng-sand)' : 'var(--tng-periwinkle)')}${bar('Kp needed', needed, 'var(--tng-ice)')}`
        + `<p class="weather-status">${edgeText}</p></div>`;
    return chartTipFrameHtml({ title: 'YOUR SKY TONIGHT', tag: '24 HOURS', tip: skyTip, svg: `<div class="weather-map-side aurora-sky-side"><div>${svg}</div><div>${side}</div></div>`,
        legend: [{ label: 'Sun altitude (shaded: dark, below -12)', color: 'var(--tng-sand)' }, { label: `Moon altitude (${phase} now)`, color: 'var(--tng-ice)' }],
        credit: `Sun and Moon computed in your browser for ${lat.toFixed(1)}, ${lon.toFixed(1)}. Aurora index: OVATION Prime (NOAA SWPC), valid ${data.map ? chartTimeText(Date.parse(data.map.forecast)) : 'no map'}. Kp: NOAA SWPC.` });
}

/* --- ACTIVITY: hemispheric power with Kp (one process, so a second axis is allowed) ----------------------------- */

const activityTip = [
    ['What', 'Two measures of the same thing, how active the aurora is, over the last 24 hours on one UTC time axis: the <b>hemispheric power</b> of the northern and southern aurora in gigawatts (lines, left axis) and the planetary <b>Kp</b> '
        + 'in 3-hour blocks (bars, right axis, coloured with the G level where one is reached). Both rise together in a storm. Since both measure auroral activity, a second axis is allowed; each is drawn in its own colour.'],
    ['Where from', 'Power: NOAA SWPC\'s hemispheric power index, from the particle detectors of NOAA and EUMETSAT polar-orbiting satellites (about 850 km up, 0.003 light-seconds from Earth). Kp: GFZ Potsdam, from ground magnetometers. Collected about hourly.'],
    ['Units', 'Gigawatts: quiet about 10 to 25, active 50 to 100, a big storm several hundred (the axis steps in fixed ladders). Kp 0 to 9 in thirds; G1 begins at 4.67.'],
    ['Cite', 'NOAA SWPC (hemispheric power); Fuller-Rowell, T. J. and Evans, D. S. (1987), J. Geophys. Res. 92, 7606; GFZ Potsdam (Matzka et al. 2021, Space Weather 19, e2020SW002641).'],
];

async function loadActivity() {
    const [north, south, kp] = await Promise.all([weatherSeries('hemiPowerNorth', '24h'), weatherSeries('hemiPowerSouth', '24h'), weatherSeries('gfzKp', '3d', true)]);
    return { north: north.points, south: south.points, kp, loadedAt: Date.now() };
}

function activityHtml(data, width) {
    const t1 = data.loadedAt;
    const t0 = t1 - 24 * 3600000;
    const max = weatherLadder(Math.max(weatherMaxOf(data.north), weatherMaxOf(data.south)), [50, 100, 200, 400]);
    const panels = [{ height: 170, left: { min: 0, max, ticks: weatherSteps(max, 4), label: 'HEMISPHERIC POWER (GW)', color: 'var(--tng-sand)' },
        right: { min: 0, max: 9, ticks: [0, 3, 6, 9], label: 'KP', color: 'var(--tng-periwinkle)' }, lines: [{ axis: 'right', value: 4.67, label: 'G1', color: 'var(--tng-salmon)' }],
        marks: [{ type: 'bars', axis: 'right', points: data.kp.points, barMs: KP_BLOCK_MS * 0.85, offsetMs: KP_BLOCK_MS / 2, colorOf: kpBarColour, tipOf: (p) => `${chartTimeText(p[0])} block: Kp ${p[1]}${gLevelOf(p[1]) ? ` (G${gLevelOf(p[1])})` : ''}` },
            { type: 'line', axis: 'left', points: data.north, color: 'var(--tng-sand)', width: 2, gapMs: 11 * 60000 },
            { type: 'line', axis: 'left', points: data.south, color: 'var(--tng-lavender)', width: 2, gapMs: 11 * 60000 }] }];
    const hover = (ms) => `${chartTimeText(ms)}\nNorth ${nearReading(data.north, ms, 8 * 60000, 0, 'GW')}, south ${nearReading(data.south, ms, 8 * 60000, 0, 'GW')}\nKp ${kpBlockAt(data.kp.points, ms) !== null ? kpBlockAt(data.kp.points, ms) : 'no data'}`;
    const svg = timePanelsSvg({ width, t0, t1, panels, hoverText: hover, title: 'Hemispheric power and Kp, 24 hours' });
    return chartTipFrameHtml({ title: 'ACTIVITY', tag: '24 HOURS', tip: activityTip, svg,
        legend: [{ label: 'North power', color: 'var(--tng-sand)' }, { label: 'South power', color: 'var(--tng-lavender)' }, { label: 'Kp (right axis)', color: 'var(--tng-periwinkle)' }, { label: 'Kp, G1 or more', color: SCALE_COLOURS[1] }],
        credit: 'NOAA SWPC (NOAA and EUMETSAT polar-orbiting satellites, about 850 km up, 0.003 light-seconds from Earth); Kp: GFZ Potsdam, from ground magnetometers: no spacecraft.' });
}

/* --- THE NEXT HOUR: the solar wind about to arrive ------------------------------------------------------------------ */

const nextHourTip = [
    ['What', 'The last hour of the solar wind as it passes the spacecraft upstream of Earth, and how long it will take to reach us. A strong, sustained southward Bz (warm, below the line) opens Earth\'s field and brightens and widens the oval '
        + 'within the hour. The oval on the map above already is the model\'s forecast for 30 to 90 minutes after the wind it was run on.'],
    ['Countdown', 'Distance from L1 to Earth about 1.5 million km divided by the wind speed: 30 to 60 minutes (about 62 at 400 km/s, 31 at 800). The warning time is the travel time of the wind, not of light. It is counted from the last reading held, which is up to an hour old.'],
    ['Where from', 'NOAA SOLAR-1 (formerly SWFO-L1) at the Sun-Earth Lagrange point L1, sunward of Earth, about 1.5 million km away: about 5 light-seconds. One-minute values, provisional; collected here about hourly.'],
    ['Cite', 'NOAA Space Weather Prediction Center, services.swpc.noaa.gov (real-time solar wind); Newell, P. T. et al. (2014), Space Weather 12, 368.'],
];

async function loadNextHour() {
    const strip = await loadL1Strip();
    const oval = await weatherMapData('ovation');
    return { ...strip, oval: oval ? oval.map : null };
}

function nextHourHtml(data, width) {
    const speeds = data.speed.filter((p) => p[1] !== null);
    const bzs = data.bz.filter((p) => p[1] !== null);
    const lastSpeed = speeds.length ? speeds[speeds.length - 1] : null;
    const lastBz = bzs.length ? bzs[bzs.length - 1] : null;
    const minutes = lastSpeed ? 1.5e6 / lastSpeed[1] / 60 : null;
    const arrival = lastSpeed ? lastSpeed[0] + minutes * 60000 : null;
    const left = arrival === null ? null : Math.round((arrival - data.loadedAt) / 60000);
    const tiles = '<div class="weather-tiles">'
        + weatherTile('WIND ARRIVES IN', left === null ? '--' : left > 0 ? `${left} min` : 'arrived', lastSpeed ? `${Math.round(minutes)} min from L1 at ${Math.round(lastSpeed[1])} km/s, from the reading ${weatherAgo(lastSpeed[0], data.loadedAt)}` : 'no wind speed held')
        + weatherTile('BZ AT L1 (NT)', lastBz ? lastBz[1].toFixed(1) : '--', lastBz ? `${lastBz[1] < 0 ? 'southward' : 'northward'}, ${weatherAgo(lastBz[0], data.loadedAt)}` : 'no reading', lastBz && lastBz[1] <= -5 ? 'var(--tng-salmon)' : undefined)
        + weatherTile('OVAL VALID AT', data.oval ? chartTimeText(Date.parse(data.oval.forecast)).slice(11) : '--', data.oval ? `model, from observations ${chartTimeText(Date.parse(data.oval.obs)).slice(11)}` : 'no map held') + '</div>';
    return chartTipFrameHtml({ title: 'THE NEXT HOUR', tag: 'LAST HOUR', tip: nextHourTip, svg: tiles + l1StripSvg(data, width),
        credit: 'NOAA SOLAR-1 at L1, about 1.5 million km sunward of Earth (about 5 light-seconds); the wind takes about 30 to 60 minutes to cover that distance.' });
}

/* --- THE NEXT NIGHTS: the 27-day recurrence ----------------------------------------------------------------------- */

const recurrenceTip = [
    ['What', 'The Sun turns once in about 27 days as seen from Earth, so a coronal hole or an active region that disturbed Earth\'s field comes round again. The solid line is the daily <b>Ap</b> index of the last 30 days; the dashed line is '
        + 'the same record <b>27 days earlier</b>, shifted forward by 27 days, so the part to the right of now (hatched) is what a repeat would look like. Both lines are on one axis because they are the same quantity.'],
    ['How good', 'Compare the lines to the left of now: where they follow each other the pattern is recurrent. The figure under the chart is the correlation between the last 30 days and the 27 days before them. A new eruption (a CME) does not recur, and a coronal hole can change or fade within a rotation.'],
    ['Where from', 'GFZ Potsdam, the daily Ap index from the world network of ground magnetometers: no spacecraft. 90 days are held here.'],
    ['Units', 'Ap in index units (times 2 nT it is about the disturbance at 50 degrees geomagnetic latitude); Ap 15 is quiet, over 30 active, about 40 for a day with a G1 storm.'],
    ['Cite', 'GFZ Potsdam (Matzka et al. 2021, Space Weather 19, e2020SW002641); NOAA SWPC 27-day outlook (the same idea, issued by forecasters).'],
];

async function loadRecurrence() {
    const ap = await weatherSeries('gfzAp', '90d');
    return { ap: ap.points.filter((p) => p[1] !== null), loadedAt: Date.now() };
}

// The correlation of the last `days` daily values with the values 27 days before them (null when fewer than 10 pairs).
function auroraRecurrenceR(points, now, days = 30) {
    const DAY = 86400000;
    const byDay = new Map(points.map((p) => [Math.floor(p[0] / DAY), p[1]]));
    const pairs = [];
    for (let d = Math.floor(now / DAY) - days; d <= Math.floor(now / DAY); d += 1) {
        if (byDay.has(d) && byDay.has(d - 27)) {
            pairs.push([byDay.get(d), byDay.get(d - 27)]);
        }
    }
    if (pairs.length < 10) {
        return null;
    }
    const mean = (i) => pairs.reduce((s, p) => s + p[i], 0) / pairs.length;
    const mx = mean(0);
    const my = mean(1);
    const sxy = pairs.reduce((s, p) => s + (p[0] - mx) * (p[1] - my), 0);
    const sxx = pairs.reduce((s, p) => s + (p[0] - mx) ** 2, 0);
    const syy = pairs.reduce((s, p) => s + (p[1] - my) ** 2, 0);
    return sxx > 0 && syy > 0 ? { r: sxy / Math.sqrt(sxx * syy), n: pairs.length } : null;
}

function recurrenceHtml(data, width) {
    const DAY = 86400000;
    const now = data.loadedAt;
    const t0 = now - 30 * DAY;
    const t1 = now + 27 * DAY;
    const observed = data.ap.filter((p) => p[0] <= now);
    const echo = data.ap.map((p) => [p[0] + 27 * DAY, p[1]]);
    const max = weatherLadder(Math.max(weatherMaxOf(observed.filter((p) => p[0] >= t0)), weatherMaxOf(echo.filter((p) => p[0] >= t0 && p[0] <= t1))), [50, 100, 200, 400]);
    const panels = [{ height: 170, left: { min: 0, max, ticks: weatherSteps(max, 2), label: 'AP (DAILY)', color: 'var(--tng-periwinkle)' },
        marks: [{ type: 'line', axis: 'left', points: echo, color: 'var(--tng-sand)', width: 2, gapMs: 2 * DAY, forecastFrom: now }, { type: 'line', axis: 'left', points: observed, color: 'var(--tng-periwinkle)', width: 2, gapMs: 2 * DAY }] }];
    const hover = (ms) => `${chartTimeText(ms)}\nAp ${nearReading(observed, ms, DAY, 0, '')}\n27 days earlier ${nearReading(echo, ms, DAY, 0, '')}`;
    const svg = timePanelsSvg({ width, t0, t1, panels, events: [{ t: now, color: 'var(--space-white)', label: `Now, ${chartTimeText(now)}` }], hoverText: hover, title: 'Ap now and 27 days earlier' });
    const corr = auroraRecurrenceR(data.ap, now);
    const text = corr ? `Last 30 days against the 27 days before them: correlation ${corr.r.toFixed(2)} over ${corr.n} days (about ${Math.round(Math.max(0, corr.r) ** 2 * 100)}% of the day-to-day variation repeats).` : 'Not enough days held to compare.';
    return chartTipFrameHtml({ title: '27-DAY RECURRENCE', tag: 'AP', tip: recurrenceTip, svg,
        legend: [{ label: 'Ap, observed', color: 'var(--tng-periwinkle)' }, { label: 'Ap 27 days earlier, moved forward (hatched: a repeat)', color: 'var(--tng-sand)' }],
        credit: `${text} GFZ Potsdam, from ground magnetometers: no spacecraft.` });
}
