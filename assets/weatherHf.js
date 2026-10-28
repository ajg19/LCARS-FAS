/* ==========================================================================
   WEATHER HF -- the charts of HF COMMS (shortwave radio) that are built
   from K1 to K8 and the D-RAP numbers: the flare and proton chart with the
   radio-blackout reading (K2), the absorption status and map, the
   aviation board of indicative lights, the radio outlook (K8 chances with
   the last hour of the solar wind, K1).

   The D-RAP world map is drawn by the reusable map component in weatherMap.js, only when it earns its
   place (5 MHz or more, or a proton event) or when the visitor asks for it.

   YOUR PATH (foF2 inferred from TEC, D-RAP now) and the GNSS TEC lamp use the stored TEC data through
   weatherTec.js. Not built: a D-RAP history at the visitor's place (only the latest global map is stored)
   and any measured foF2 (no ionosonde data). See chartCorePlan.md.

   Needs weatherCharts.js, weatherEarth.js (K8, the scale colours), weatherMap.js and weatherTec.js;
   loaded by weatherPanel.js the first time HF COMM is opened.
   ========================================================================== */

const HF_BAND_MHZ = [3, 30];
const HF_ABSORPTION_AMBER = 5;      // MHz: the D-RAP map is worth showing from here (Spock, note 8); also the amber light
const HF_ABSORPTION_RED = 15;       // MHz: provisional red light

// What the radio operator should read into each: the extra paragraphs on the K2 tooltip for this view.
const hfFlareTip = [
    ['For HF radio', 'A flare\'s X-rays ionise the sunlit D layer of the ionosphere, which then absorbs HF waves: the blackout starts within minutes, lasts as long as the flare '
        + '(minutes to an hour), is strongest under the Sun and at the lowest frequencies, and fades with distance from the sub-solar point. R1 (M1) degrades the lowest HF bands on the '
        + 'sunlit side, R3 (X1) can black out the whole sunlit HF band. Protons above 10 MeV arrive hours later along the field lines and fill the polar caps: <b>polar cap absorption</b> '
        + 'on high-latitude paths, day and night, for days. The S1 line (10 pfu) is where it becomes significant. Above about 30 MHz the effect is small.'],
];

/* --- ABSORPTION NOW: the D-RAP reading and, when it matters, the world map ------------------------------- */

// Colour bands of the map, MHz of the highest affected frequency. Below 1 MHz nothing is drawn. The 5 and 15 MHz
// edges are the lamp thresholds above.
const HF_MAP_LEVELS = [
    { from: 1, colour: 'var(--tng-periwinkle)', label: '1 to 5 MHz' },
    { from: HF_ABSORPTION_AMBER, colour: 'var(--tng-sand)', label: '5 to 10 MHz' },
    { from: 10, colour: 'var(--tng-amber)', label: '10 to 15 MHz' },
    { from: HF_ABSORPTION_RED, colour: 'var(--tng-salmon)', label: '15 to 20 MHz' },
    { from: 20, colour: 'var(--red)', label: '20 to 30 MHz' },
    { from: 30, colour: 'var(--tng-pink)', label: '30 MHz and over' },
];

// The colour of a map cell: the stored value is in tenths of a MHz.
function hfMapColour(tenths) {
    const mhz = tenths / 10;
    let found = null;
    for (const level of HF_MAP_LEVELS) {
        if (mhz >= level.from) {
            found = level.colour;
        }
    }
    return found;
}

// NOAA's proton message travels in the quality text of the D-RAP maximum ("Normal X-ray Background; Normal Proton Background").
function hfProtonMessage(quality) {
    const part = String(quality || '').split(';').map((x) => x.trim()).find((x) => /proton/i.test(x));
    return part && !/^normal proton background$/i.test(part) ? part : null;
}

const hfAbsorptionTip = [
    ['What', 'The highest frequency now affected by absorption of HF radio in the sunlit ionosphere, the "highest affected frequency" (HAF) of NOAA\'s D-RAP model. Below it, signals '
        + 'passing through the D layer are noticeably weakened; above it they are not. When it is below 5 MHz, and NOAA reports no proton event, there is nothing worth mapping: this card says so '
        + 'in a line and offers the map on request.'],
    ['The map', 'Longitude across and latitude up (plain latitude-longitude, so the poles are stretched). Colour is the HAF in the bands of the key; nothing is drawn below 1 MHz. The shaded part is night, '
        + 'worked out here from the time of the map: flare absorption lies on the sunlit side only, while polar cap absorption from protons fills the polar caps by day and night. The ring marks where the '
        + 'maximum is; when several cells tie it is the one nearest the point under the Sun. The model grid is 4 degrees of longitude by 2 of latitude. Move the pointer over the map for the value at a place.'],
    ['Where from', 'NOAA SWPC\'s D-Region Absorption Predictions model (D-RAP), driven by the X-ray flux and proton flux of NOAA GOES-18 (geostationary, about 0.14 light-seconds from Earth), '
        + 'updated about every minute; this site collects it about hourly. It is not auroral absorption, which D-RAP does not include. Outlines: country boundaries, simplified.'],
    ['Units and formula', 'Megahertz. For flares the model\'s X-ray term has the form HAF = (10 log<sub>10</sub> F + 65) / (cos &chi;)<sup>0.75</sup>, with F the X-ray flux in W/m&sup2; and &chi; the solar zenith '
        + 'angle, so it is largest under the Sun; protons add a polar term. HF radio occupies about ' + HF_BAND_MHZ[0] + ' to ' + HF_BAND_MHZ[1] + ' MHz, so a HAF of 5 MHz touches only its low end and one above 20 MHz affects almost all of it.'],
    ['Cite', 'NOAA Space Weather Prediction Center, D-Region Absorption Predictions (swpc.noaa.gov/products/d-region-absorption-predictions-d-rap).'],
];

// Does the map earn its place now? From 5 MHz, or during a proton event (Spock, note 8); or when the visitor asks.
function hfMapWanted(data) {
    const latest = data.latest || {};
    const max = latest.drapMax && latest.drapMax[1] !== null ? latest.drapMax : null;
    return Boolean(data.wantMap || (max && (max[1] >= HF_ABSORPTION_AMBER || hfProtonMessage(max[3]))));
}

async function loadAbsorption() {
    const data = { ...(await weatherNow()), map: null, coast: null, wantMap: false };
    if (hfMapWanted(data)) {
        await hfLoadMap(data);
    }
    return data;
}

// The D-RAP map and the outline, into the card's data. The outline is only fetched here, when a map is to be drawn.
async function hfLoadMap(data) {
    const [map, coast] = await Promise.all([weatherMapData('drapGlobal'), weatherCoastRings()]);
    data.map = map;
    data.coast = coast;
}

// The link under a quiet card: show the map anyway, or put it away again.
async function hfShowMap(show) {
    const slot = document.getElementById('weather-hf-absorption');
    if (!slot || !slot.chartData) {
        return;
    }
    slot.chartData.wantMap = show;
    if (show && !slot.chartData.map) {
        slot.innerHTML = '<p class="weather-status">Loading the map...</p>';
        await hfLoadMap(slot.chartData);
    }
    weatherRedraw(slot);
}

function hfAbsorptionHtml(data, width = 900) {
    const latest = data.latest || {};
    const max = latest.drapMax && latest.drapMax[1] !== null ? latest.drapMax : null;
    const lat = latest.drapMaxLat ? latest.drapMaxLat[1] : null;
    const lon = latest.drapMaxLon ? latest.drapMaxLon[1] : null;
    const significant = max && max[1] >= HF_ABSORPTION_AMBER;
    const proton = max ? hfProtonMessage(max[3]) : null;
    const drap = hfMapWanted(data) && data.map && data.map.map;   // a map fetched earlier stays out of sight once put away
    const where = lat !== null && lon !== null ? `, at its greatest near ${lat.toFixed(0)}, ${lon.toFixed(0)} degrees (latitude, longitude)` : '';
    let text;
    if (!max) {
        text = 'No D-RAP reading is held yet.';
    } else if (significant) {
        text = `HF absorption: the highest affected frequency is ${max[1].toFixed(1)} MHz${where}.${drap ? '' : ' The map could not be loaded.'}`;
    } else if (proton) {
        text = `NOAA reports a proton event (${escapeChartText(proton)}): the polar caps may absorb HF radio, day and night, although the highest affected frequency is only ${max[1].toFixed(1)} MHz.${drap ? '' : ' The map could not be loaded.'}`;
    } else {
        text = `No significant HF absorption (highest affected frequency ${max[1].toFixed(1)} MHz, below ${HF_ABSORPTION_AMBER} MHz, the bottom of the HF band 3 to 30 MHz).`;
    }
    const quietLink = max && !significant && !proton
        ? (drap ? ' <a href="#" onclick="hfShowMap(false); return false;">Put the map away.</a>'
            : ' <a href="#" onclick="hfShowMap(true); return false;">Show the map anyway.</a>') : '';
    const here = typeof observerLocation !== 'undefined' && observerLocation && drap
        ? { lat: observerLocation.latitude, lon: observerLocation.longitude } : null;
    const hereValue = here ? weatherGridValueAt(hfGrid(drap), here.lat, here.lon) : null;
    const tiles = `<div class="weather-tiles">${weatherTile('HIGHEST AFFECTED FREQUENCY (MHZ)', max ? max[1].toFixed(1) : '--', max ? weatherAgo(Date.parse(max[0]), data.loadedAt) : 'no data',
        significant ? LAMP_COLOURS.amber : undefined)}${hereValue !== null ? weatherTile('AT YOUR LOCATION (MHZ)', (hereValue / 10).toFixed(1), 'nearest map cell') : ''}</div>`
        + `<p class="weather-status">${text}${quietLink}</p>`;
    let map = '';
    let legend;
    if (drap) {
        const markers = [];
        if (significant && lat !== null && lon !== null) {
            markers.push({ lat, lon, label: `MAX ${max[1].toFixed(1)}`, color: 'var(--space-white)' });
        }
        if (here) {
            markers.push({ lat: here.lat, lon: here.lon, label: 'YOU', color: 'var(--tng-ice)' });
        }
        const grid = hfGrid(drap);
        const validMs = Date.parse(drap.valid);
        map = weatherMapSvg({ id: 'hf-drap', width, coast: data.coast, terminatorMs: validMs, markers, title: 'World map of the highest affected frequency',
            layers: [{ ...grid, colourAt: hfMapColour }],
            hoverText: (la, lo) => {
                const v = weatherGridValueAt(grid, la, lo);
                return `${Math.abs(la).toFixed(0)}${la >= 0 ? 'N' : 'S'}, ${Math.abs(lo).toFixed(0)}${lo >= 0 ? 'E' : 'W'}: ${v === null ? 'no value' : `highest affected frequency ${(v / 10).toFixed(1)} MHz`}`;
            } });
        legend = weatherMapLegend(HF_MAP_LEVELS);
    }
    return chartTipFrameHtml({ title: 'ABSORPTION NOW', tag: 'D-RAP', tip: hfAbsorptionTip, legend, svg: tiles + map,
        credit: `NOAA SWPC D-RAP, driven by GOES-18 (geostationary, about 0.14 light-seconds from Earth)${drap ? `; map valid ${chartTimeText(Date.parse(drap.valid))}` : ''}.` });
}

// The stored map as the grid the map component draws.
function hfGrid(drap) {
    return { values: drap.tenths, latMax: drap.latMax, latStep: drap.latStep, lonMin: drap.lonMin, lonStep: drap.lonStep };
}

/* --- AVIATION BOARD: indicative lights ------------------------------------------------------------- */

const hfBoardTip = [
    ['What', 'Four traffic lights for the things a high-latitude or polar HF user, or an aircraft crew, watches: HF absorption, polar cap absorption, flare radio fade-out, and GNSS (satellite navigation) signal '
        + 'delay. Green = nothing to note; amber = some paths or bands degraded; red = serious. <b>Indicative, not an official advisory</b>: for operations use the advisories of the '
        + 'authority for your airspace (for example ICAO\'s space-weather centres).'],
    ['Rules (provisional)', 'HF absorption: D-RAP highest affected frequency under 5 MHz green, 5 to 15 amber, 15 or more red. Polar cap absorption: NOAA S level 0 green, S1 or S2 amber, S3 or more red. '
        + 'Flare fade-out: NOAA R level 0 green, R1 or R2 amber, R3 or more red. '
        + '<b>GNSS TEC (provisional, to be confirmed)</b>: from the newest stored NOAA GloTEC map, the worse of two tests. (1) The anomaly: the cell\'s deviation from its own 30-day median as a fraction of that median, the third-largest among '
        + 'well-observed cells (quality flag 3 or more, median at least 10 TECU, so one odd cell cannot light the lamp): ' + TEC_LAMP.anomalyAmber * 100 + '% or more amber, ' + TEC_LAMP.anomalyRed * 100 + '% or more red '
        + '(a quiet day reaches about 45%, because the two equatorial crests are lopsided). (2) ICAO\'s absolute GNSS thresholds: highest observed TEC ' + TEC_LAMP.icaoAmber + ' TECU moderate (amber), '
        + TEC_LAMP.icaoRed + ' severe (red). Grey if the map is more than 6 hours old or none is held. Cells with no observations (quality flag 0) are model estimates and are left out of both tests.'],
    ['Where from', 'NOAA SWPC: D-RAP and the NOAA scales, from GOES-18 (geostationary orbit, about 0.14 light-seconds from Earth). Updated about every minute; collected here about hourly.'],
    ['Cite', 'NOAA Space Weather Prediction Center, services.swpc.noaa.gov; NOAA Space Weather Scales.'],
];

// The board's data: the latest values and the GloTEC summary (null if none is held).
async function loadBoard() {
    const [now, tec] = await Promise.all([weatherNow(), tecSummary()]);
    return { ...now, tec };
}

function hfBoardHtml(now) {
    const latest = now.latest || {};
    const level = (name) => (latest[name] && latest[name][1] !== null ? latest[name][1] : null);
    const haf = latest.drapMax && latest.drapMax[1] !== null ? latest.drapMax[1] : null;
    const lamp = (label, colour, word, detail) => `<div class="weather-lamp-card"><span class="weather-lamp" style="background:${LAMP_COLOURS[colour]}"></span>`
        + `<span class="weather-lamp-text"><span class="weather-tile-label">${label}</span><span class="weather-lamp-word">${word}</span><span class="weather-tile-note">${detail}</span></span></div>`;
    const byLevel = (n, amberAt, redAt) => (n === null ? 'grey' : n >= redAt ? 'red' : n >= amberAt ? 'amber' : 'green');
    const r = level('noaaScaleR');
    const s = level('noaaScaleS');
    const hafColour = haf === null ? 'grey' : haf >= HF_ABSORPTION_RED ? 'red' : haf >= HF_ABSORPTION_AMBER ? 'amber' : 'green';
    const words = { green: 'CLEAR', amber: 'DEGRADED', red: 'SEVERE', grey: 'NO DATA' };
    const gnss = tecLamp(now.tec, now.loadedAt || Date.now());
    const cards = lamp('HF ABSORPTION', hafColour, words[hafColour], haf === null ? 'no D-RAP reading' : `highest affected frequency ${haf.toFixed(1)} MHz`)
        + lamp('POLAR CAP ABSORPTION', byLevel(s, 1, 3), words[byLevel(s, 1, 3)], s === null ? 'no reading' : `radiation storm level S${s}`)
        + lamp('FLARE FADE-OUT', byLevel(r, 1, 3), words[byLevel(r, 1, 3)], r === null ? 'no reading' : `radio blackout level R${r}`)
        + lamp('GNSS TEC', gnss.colour, gnss.word, gnss.detail);
    return chartTipFrameHtml({ title: 'AVIATION BOARD', tag: 'INDICATIVE', tip: hfBoardTip, svg: `<div class="weather-lamps">${cards}</div>`,
        credit: 'Indicative, not an official advisory. NOAA SWPC (GOES-18, geostationary, about 0.14 light-seconds from Earth; GloTEC from GNSS ground receivers and COSMIC-2).' });
}

/* --- YOUR PATH: foF2 and D-RAP at the visitor's place ------------------------------------------------------ */

const hfPathTip = [
    ['What', 'The two numbers that set what an HF path over your location can do, in the same unit (MHz), on one axis. <b>foF2</b> is the highest frequency the F2 layer reflects straight back: '
        + 'a signal above it passes through. For a path of about 3,000 km the <b>maximum usable frequency</b> is roughly 3 times foF2 (MUF(3000)F2, indicative: within about 20%). '
        + '<b>D-RAP</b> is the highest frequency absorbed in the sunlit D layer; the usable window lies between the absorbed frequencies and the MUF.'],
    ['How foF2 is got', '<b>Dots</b>: NOAA GloTEC\'s own peak electron density, foF2 = 8.98 &radic;(NmF2) Hz with NmF2 in electrons per m&sup3; (a hollow dot: GloTEC had no observations in your cell, so the value is the model\'s estimate). '
        + '<b>Line</b> (<b>inferred</b>, not measured): CODE\'s hourly TEC turned into NmF2 with an <i>equivalent slab thickness</i> (TEC / NmF2, about 300 km), here calibrated against GloTEC where both exist; '
        + 'dashed and hatched where CODE\'s TEC is itself a prediction. The thickness really varies between day and night by a factor of about 1.5, so the inferred foF2 is good to roughly 15 to 20% and is a guide to the trend, not a measurement. '
        + 'No ionosonde data are used.'],
    ['What is a now-value and what is missing', '<b>D-RAP at your place is the latest global map only</b> (one ring at "now"): the site stores no D-RAP history, so there is no line for it. '
        + 'The GloTEC dots only go back as far as this site has been collecting (one map every 3 hours).'],
    ['Where from', 'TEC: CODE (Bern) from IGS ground receivers; GloTEC from NOAA SWPC (GNSS receivers and COSMIC-2 radio occultation). D-RAP: NOAA SWPC, from GOES-18 (geostationary, about 0.14 light-seconds from Earth).'],
    ['Cite', 'Davies, K. (1990), Ionospheric Radio; ' + satCodeCredit + ' NOAA SWPC GloTEC and D-RAP.'],
];

async function loadPath() {
    const place = tecPlace();
    if (!place) {
        return { place: null, loadedAt: Date.now() };
    }
    const [series, drap] = await Promise.all([tecSeriesAt(place), weatherMapData('drapGlobal')]);
    return { place, series, drap, loadedAt: Date.now() };
}

function hfPathHtml(data, width) {
    if (!data.place) {
        return satNeedLocation('YOUR PATH', hfPathTip);
    }
    if (!data.series) {
        return WEATHER_NO_DATA;
    }
    const now = data.loadedAt;
    const s = tecSeriesPoints(data.series);
    const g = data.series.glotec;
    const slab = tecSlabKm(g.tec || [], g.foF2 || []);
    const inferred = s.line.map((p) => [p[0], p[1] === null ? null : tecFoF2FromTec(p[1], slab)]);
    const gloDots = (g.t || []).map((t, i) => [Date.parse(t), g.foF2[i], { r: 3.5, hollow: g.observed[i] === false,
        tip: `GloTEC ${chartTimeText(Date.parse(t))}: foF2 ${g.foF2[i] === null ? 'no value' : `${g.foF2[i].toFixed(1)} MHz`}${g.observed[i] === false ? ' (no observations in this cell: the model\'s estimate)' : ''}` }]);
    const drapMap = data.drap && data.drap.map;
    const drapHere = drapMap ? weatherGridValueAt(hfGrid(drapMap), data.place.lat, data.place.lon) : null;
    const drapMhz = drapHere === null ? null : drapHere / 10;
    const t0 = now - 48 * 3600000;
    const t1 = now + 24 * 3600000;
    const shown = inferred.filter((p) => p[0] >= t0 && p[0] <= t1).concat(gloDots.filter((p) => p[0] >= t0 && p[0] <= t1), drapMhz === null ? [] : [[now, drapMhz]]);
    const max = weatherLadder(weatherMaxOf(shown), [10, 20, 30]);
    const marks = [{ type: 'line', axis: 'left', points: inferred, color: 'var(--tng-sand)', width: 2, gapMs: 2.5 * 3600000, forecastFrom: s.firstPrediction || undefined },
        { type: 'dots', axis: 'left', points: gloDots, color: 'var(--tng-periwinkle)' }];
    if (drapMhz !== null) {
        marks.push({ type: 'dots', axis: 'left', color: 'var(--tng-salmon)',
            points: [[now, drapMhz, { r: 6, tip: `D-RAP at your place now: highest affected frequency ${drapMhz.toFixed(1)} MHz (latest map, valid ${chartTimeText(Date.parse(drapMap.valid))}; no history is stored)` }]] });
    }
    const panel = { height: 190, left: { min: 0, max, ticks: Array.from({ length: max / 5 + 1 }, (_, i) => i * 5), label: 'MHZ', color: 'var(--tng-sand)' }, marks };
    const hover = (ms) => `${chartTimeText(ms)}\nfoF2 inferred from CODE TEC ${nearReading(inferred, ms, 70 * 60000, 1, 'MHz')}${s.firstPrediction && ms >= s.firstPrediction ? ' (predicted TEC)' : ''}\nfoF2 GloTEC ${nearReading(gloDots, ms, 100 * 60000, 1, 'MHz')}`;
    const svg = timePanelsSvg({ width, t0, t1, panels: [panel], events: satJoinEvents(s.firstPrediction && s.firstPrediction > t0 && s.firstPrediction < t1 ? s.firstPrediction : null, now),
        hoverText: hover, title: 'foF2 and D-RAP at your location' });
    const lastGlo = g.t && g.t.length ? g.t.length - 1 : -1;
    const foNow = lastGlo >= 0 && g.foF2[lastGlo] !== null ? g.foF2[lastGlo] : null;
    const inferredNow = (() => { const i = chartNearest(inferred.map((p) => p[0]), now); return i >= 0 && inferred[i][1] !== null ? inferred[i][1] : null; })();
    const muf = foNow !== null ? foNow : inferredNow;
    const tiles = `<div class="weather-tiles">`
        + weatherTile('FOF2, GLOTEC (MHZ)', foNow === null ? '--' : foNow.toFixed(1), foNow === null ? 'no GloTEC map held for your cell' : `${weatherAgo(Date.parse(g.t[lastGlo]), now)}${g.observed[lastGlo] === false ? ', model estimate' : ''}`)
        + weatherTile('FOF2, FROM CODE TEC (MHZ)', inferredNow === null ? '--' : inferredNow.toFixed(1), `inferred, slab ${Math.round(slab)} km`)
        + weatherTile('MUF(3000) ABOUT (MHZ)', muf === null ? '--' : (3 * muf).toFixed(0), '3 x foF2, indicative')
        + weatherTile('D-RAP HERE NOW (MHZ)', drapMhz === null ? '--' : drapMhz.toFixed(1), drapMap ? `latest map only, ${weatherAgo(Date.parse(drapMap.valid), now)}` : 'no D-RAP map held', drapMhz !== null && drapMhz >= HF_ABSORPTION_AMBER ? LAMP_COLOURS.amber : undefined)
        + `</div>`;
    const missing = '<p class="weather-status">Missing, and why: a D-RAP history at your place (only the latest global map is stored, so D-RAP is a now-value, the ring); GloTEC dots older than this site\'s collection; '
        + 'any measured foF2 (no ionosonde data). The line is inferred from TEC.</p>';
    return chartTipFrameHtml({ title: 'YOUR PATH', tag: '48 H AND 24 H AHEAD', tip: hfPathTip, svg: tiles + svg + missing,
        legend: [{ label: 'foF2 inferred from CODE TEC (dashed: predicted TEC)', color: 'var(--tng-sand)' }, { label: 'foF2 from GloTEC', color: 'var(--tng-periwinkle)' }, { label: 'D-RAP now', color: 'var(--tng-salmon)' }],
        credit: `Your cell: GloTEC ${g.cellLat !== undefined ? `${g.cellLat}, ${g.cellLon}` : 'none'}, CODE ${data.series.code.cellLat !== undefined ? `${data.series.code.cellLat}, ${data.series.code.cellLon}` : 'none'} (latitude, longitude). MUF indicative, within about 20%. NOAA SWPC, CODE (Bern).` });
}
