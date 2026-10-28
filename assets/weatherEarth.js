/* ==========================================================================
   WEATHER EARTH -- the charts of ERTH NOW, and the shared components that
   other views reuse: K3 (Kp with Dst), K4 (hemispheric power), K7 (the Kp
   forecast grid), K8 (the NOAA scales). Plus the storm strip, the main
   chart of ERTH NOW: the chain from the Sun to the ground on one time axis.

   Lazy, like weatherCharts.js, which it needs (the fetch helpers, K6 and
   the flare and L1 constants); loaded after it by weatherPanel.js the
   first time ERTH NOW is opened. Drawing is by assets/chartTime.js.
   ========================================================================== */

const SCALE_NAMES = { R: 'RADIO BLACKOUTS', S: 'SOLAR RADIATION STORMS', G: 'GEOMAGNETIC STORMS' };
const SCALE_WORDS = ['none', 'minor', 'moderate', 'strong', 'severe', 'extreme'];
const SCALE_TRIGGERS = {
    R: ['no flare of M class', 'M1 flare (1e-5 W/m2)', 'M5 flare', 'X1 flare', 'X10 flare', 'X20 flare'],
    S: ['below 10 pfu', '10 pfu above 10 MeV', '100 pfu', '1,000 pfu', '10,000 pfu', '100,000 pfu'],
    G: ['Kp below 5-', 'Kp 5', 'Kp 6', 'Kp 7', 'Kp 8, 9-', 'Kp 9'],
};
const SCALE_COLOURS = ['var(--tng-ice)', 'var(--tng-sand)', 'var(--tng-amber)', 'var(--tng-tan)', 'var(--tng-salmon)', 'var(--tng-alert)'];
const KP_BLOCK_MS = 3 * 3600000;

// NOAA's G level of a Kp (thirds included): G1 4.67 to 5.33 ... G5 9.
function gLevelOf(kp) {
    if (kp === null || kp === undefined) {
        return 0;
    }
    return kp >= 8.99 ? 5 : kp >= 7.66 ? 4 : kp >= 6.66 ? 3 : kp >= 5.66 ? 2 : kp >= 4.66 ? 1 : 0;
}

// The reading of a series nearest a time, within a tolerance, as text.
function nearReading(points, ms, toleranceMs, digits, unit) {
    const i = chartNearest(points.map((p) => p[0]), ms);
    return i >= 0 && Math.abs(points[i][0] - ms) <= toleranceMs && points[i][1] !== null ? `${points[i][1].toFixed(digits)}${unit ? ` ${unit}` : ''}` : 'no data';
}

// The value of the 3-hour block containing a time (blocks are stamped at their start), or null.
function kpBlockAt(points, ms) {
    const p = points.find((q) => q[0] <= ms && ms < q[0] + KP_BLOCK_MS);
    return p ? p[1] : null;
}


/* --- The visitor's place, geomagnetic latitude and the Kp needed for aurora there (ERTH NOW's forecast grid, AURORAE, TEC) ----- */

const DIPOLE_POLE = { lat: 80.7, lon: -72.7 };   // the tilted-dipole pole, about 2020
// NOAA's rule of thumb (Space Weather Scales, G1 to G5): aurora is commonly seen down to this geomagnetic latitude at each Kp. Below Kp 3 the
// usual equatorward edge of the visible oval is taken as 67 degrees. Between the listed Kp values the latitude is interpolated.
const KP_BOUNDARY = [[3, 67], [4, 65], [5, 60], [6, 55], [7, 50], [8, 45], [9, 40]];

// The visitor's place from the shared location form, or null.
function weatherPlace() {
    return typeof observerLocation !== 'undefined' && observerLocation && Number.isFinite(observerLocation.latitude) && Number.isFinite(observerLocation.longitude)
        ? { lat: observerLocation.latitude, lon: observerLocation.longitude } : null;
}

// Geomagnetic latitude (degrees) in the tilted-dipole model.
function geomagneticLat(lat, lon) {
    const rad = Math.PI / 180;
    const s = Math.sin(lat * rad) * Math.sin(DIPOLE_POLE.lat * rad)
        + Math.cos(lat * rad) * Math.cos(DIPOLE_POLE.lat * rad) * Math.cos((lon - DIPOLE_POLE.lon) * rad);
    return Math.asin(Math.max(-1, Math.min(1, s))) / rad;
}

// The Kp at which aurora commonly reaches a geomagnetic latitude (magnitude): 3 or less at 67 degrees and poleward, Infinity beyond Kp 9.
function requiredKpAt(magLat) {
    const m = Math.abs(magLat);
    if (m >= KP_BOUNDARY[0][1]) {
        return KP_BOUNDARY[0][0];
    }
    if (m < KP_BOUNDARY[KP_BOUNDARY.length - 1][1]) {
        return Infinity;
    }
    for (let i = 1; i < KP_BOUNDARY.length; i += 1) {
        const [kpA, latA] = KP_BOUNDARY[i - 1];
        const [kpB, latB] = KP_BOUNDARY[i];
        if (m >= latB) {
            return kpA + (kpB - kpA) * (latA - m) / (latA - latB);
        }
    }
    return Infinity;
}

// The Kp the visitor needs for aurora at their place, or null without a place.
function requiredKpHere() {
    const place = weatherPlace();
    return place ? requiredKpAt(geomagneticLat(place.lat, place.lon)) : null;
}

// A card that needs the visitor's location and says so (YOUR PATH, TEC at your location, YOUR SKY TONIGHT).
function satNeedLocation(title, tip) {
    return chartTipFrameHtml({ title, tag: 'YOUR LOCATION', tip, svg: '<p class="weather-status">Set your location with USR LOCN (top right of the control area) to see this for your place.</p>' });
}

/* --- EARTH RIGHT NOW: the header strip --------------------------------------------------- */

const nowStripTip = [
    ['What', 'The latest value of the seven things that matter most at Earth, with how old each is: the three NOAA scales (radio blackouts R, '
        + 'solar radiation storms S, geomagnetic storms G), the Kp index so far in the current 3-hour block, the solar radio flux F10.7, and the '
        + 'speed and north-south field (Bz) of the solar wind about an hour upstream.'],
    ['Where from', 'NOAA SWPC. R, S and G: SWPC\'s scales. Kp: SWPC\'s estimate from ground magnetometers, "at least" because the block is not finished. '
        + 'F10.7: the noon reading at the Dominion Radio Astrophysical Observatory, Penticton (ground, no spacecraft). Speed and Bz: NOAA SOLAR-1 at the '
        + 'Sun-Earth Lagrange point L1, about 1.5 million km sunward of Earth, about 5 light-seconds away; the wind itself takes about 30 to 60 minutes to cover '
        + 'that distance, so these are what Earth will feel within the hour. This site collects them about hourly, so each can be an hour or more old.'],
    ['Reading it', 'A negative Bz (warm) is the field direction that drives storms. Scales go from 0 (none) to 5 (extreme); see NOAA SCALES below.'],
    ['Cite', 'NOAA Space Weather Prediction Center, services.swpc.noaa.gov; NOAA Space Weather Scales.'],
];

function nowStripHtml(data) {
    const latest = data.latest || {};
    const get = (name) => latest[name] && latest[name][1] !== null ? latest[name] : null;
    const age = (entry) => (entry ? weatherAgo(Date.parse(entry[0]), data.loadedAt) : 'no data');
    const scale = (letter) => {
        const e = get(`noaaScale${letter}`);
        return weatherTile({ R: 'RADIO BLACKOUT', S: 'RADIATION STORM', G: 'GEOMAGNETIC STORM' }[letter],
            e ? `${letter}${e[1]}` : '--', e ? `${SCALE_WORDS[e[1]]}, ${age(e)}` : 'no data', e ? SCALE_COLOURS[e[1]] : undefined);
    };
    const kp = get('swpcKp1m');
    const f107 = get('swpcF107Daily');
    const bz = get('l1MagBzGSM');
    const speed = get('l1WindSpeed');
    return `<div class="weather-tiles">${scale('R')}${scale('S')}${scale('G')}`
        + weatherTile('KP, THIS BLOCK SO FAR', kp ? `&ge; ${kp[1].toFixed(1)}` : '--', kp ? `${age(kp)}` : 'no data', kp ? SCALE_COLOURS[gLevelOf(kp[1])] : undefined)
        + weatherTile('F10.7 (SFU)', f107 ? f107[1].toFixed(0) : '--', f107 ? `noon reading, ${age(f107)}` : 'no data')
        + weatherTile('BZ AT L1 (NT)', bz ? bz[1].toFixed(1) : '--', bz ? `${bz[1] < 0 ? 'southward, ' : 'northward, '}${age(bz)}` : 'no data', bz && bz[1] < 0 ? 'var(--tng-salmon)' : undefined)
        + weatherTile('WIND SPEED (KM/S)', speed ? speed[1].toFixed(0) : '--', speed ? age(speed) : 'no data') + '</div>';
}

function nowStripFrame(data) {
    return chartTipFrameHtml({ title: 'EARTH RIGHT NOW', tag: 'LATEST', tip: nowStripTip, svg: nowStripHtml(data),
        credit: 'NOAA SWPC; solar wind from NOAA SOLAR-1 at L1 (about 1.5 million km, about 5 light-seconds); F10.7 from Penticton (ground).' });
}

/* --- K8: the NOAA scales (levels now and the 24-hour maximum) ---------------------------------- */

const scalesTip = [
    ['What', 'NOAA\'s three space-weather scales, each from 0 (none) to 5 (extreme), as a level now and the highest level in the last 24 hours. '
        + '<b>R</b> radio blackouts, caused by solar flares; <b>S</b> solar radiation storms, energetic protons; <b>G</b> geomagnetic storms, a disturbed magnetic field.'],
    ['Where from', 'NOAA SWPC\'s scales feed, updated about every minute; this site collects it about hourly. R from the X-ray flux and S from the proton flux of '
        + 'GOES-18 (geostationary orbit, about 0.14 light-seconds from Earth); G from the planetary Kp index, measured by ground magnetometers.'],
    ['Thresholds', 'R1 at an M1 flare (1e-5 W/m&sup2;), R2 at M5, R3 at X1, R4 at X10, R5 at X20. S1 at 10 pfu of protons above 10 MeV, S2 100, S3 1,000, S4 10,000, S5 100,000. '
        + 'G1 at Kp 5, G2 Kp 6, G3 Kp 7, G4 Kp 8 and 9-, G5 Kp 9. The words: 1 minor, 2 moderate, 3 strong, 4 severe, 5 extreme.'],
    ['About', 'NOAA\'s counts per 11-year cycle: about 1,700 G1 storms but only about 4 at G5; the storm of 10 to 11 May 2024 reached G5.'],
    ['Cite', 'NOAA Space Weather Prediction Center, Space Weather Scales, swpc.noaa.gov/noaa-scales-explanation.'],
];

async function loadScales() {
    const [r, s, g] = await Promise.all(['noaaScaleR', 'noaaScaleS', 'noaaScaleG'].map((n) => weatherSeries(n, '3d')));
    // the feed's two rows: the earlier is the last 24 hours' maximum, the later is now
    const pick = (series) => {
        const p = series.points.filter((q) => q[1] !== null);
        return { now: p.length ? p[p.length - 1] : null, max: p.length > 1 ? p[p.length - 2] : null };
    };
    return { R: pick(r), S: pick(s), G: pick(g) };
}

function scalesHtml(data) {
    const tile = (letter) => {
        const d = data[letter];
        const now = d.now ? d.now[1] : null;
        const max = d.max ? Math.max(d.max[1], now === null ? 0 : now) : null;
        return `<div class="weather-scale-tile" style="border-color:${now === null ? 'var(--tng-periwinkle)' : SCALE_COLOURS[now]}">`
            + `<div class="weather-scale-name">${SCALE_NAMES[letter]}</div>`
            + `<div class="weather-scale-level" style="color:${now === null ? 'var(--status-data-color)' : SCALE_COLOURS[now]}">${now === null ? '--' : `${letter}${now}`}</div>`
            + `<div class="weather-scale-line">NOW: ${now === null ? 'no data' : SCALE_WORDS[now]}</div>`
            + `<div class="weather-scale-line">24-HOUR MAXIMUM: ${max === null ? 'no data' : `${letter}${max}, ${SCALE_WORDS[max]}`}</div>`
            + `<div class="weather-scale-line weather-scale-trigger">LEVEL 1 AT ${SCALE_TRIGGERS[letter][1].toUpperCase()}</div></div>`;
    };
    const stamp = (data.G.now || data.R.now || data.S.now);
    return chartTipFrameHtml({ title: 'NOAA SCALES', tag: stamp ? `AS OF ${chartTimeText(stamp[0]).slice(11, 16)} UTC` : 'NOW', tip: scalesTip,
        svg: `<div class="weather-scale-tiles">${tile('R')}${tile('S')}${tile('G')}</div>`,
        credit: 'NOAA SWPC; GOES-18 (geostationary, about 0.14 light-seconds from Earth) for R and S, ground magnetometers for G.' });
}

/* --- the storm strip: the chain from the Sun to the ground, on one time axis ------------------------ */

const STORM_BACK_DAYS = 3;
const STORM_FORWARD_MS = 12 * 3600000;

const stormTip = [
    ['What', 'The whole chain of a space-weather event on one UTC time axis, in the order it happens, three days back and the next 12 hours (hatched). '
        + 'From the top: the Sun\'s X-ray flash (a flare); the protons it or its shock sends; the solar wind\'s speed and the field\'s north-south part (Bz) at L1; '
        + 'and, at the bottom, Earth\'s response: the Kp bars (coloured where a G storm level is reached) and the Dst ring-current index (inverted, so a storm points '
        + 'the same way on both). Vertical markers run through every row: a hollow-ringed marker is a CME predicted to arrive; a solid sand marker is a CME at launch; a solid salmon marker is a shock actually seen at Earth.'],
    ['Reading it', 'Follow a flare to the right: X-rays are felt at once (8 minutes), protons within minutes to hours, the CME\'s shock in one to four days, '
        + 'then Bz turning south, and then Kp rising within hours. Fast wind alone, or a north-pointing Bz, does little.'],
    ['Where from', 'X-rays and protons: NOAA GOES-18, geostationary, about 0.14 light-seconds from Earth. Speed and Bz: NOAA SOLAR-1 at the Sun-Earth Lagrange point L1, '
        + 'about 1.5 million km sunward, about 5 light-seconds away (the wind takes about 30 to 60 minutes to arrive). Kp: GFZ Potsdam from ground magnetometers (definitive, else '
        + 'preliminary), the forecast bars from NOAA SWPC. Dst: Kyoto\'s real-time quick-look values via NOAA SWPC, provisional, from four equatorial observatories. '
        + 'CMEs: NASA DONKI. All collected about hourly. The data and their gaps are exactly those of the other charts: nothing is interpolated.'],
    ['Units', 'X-ray in W/m&sup2; (classes A to X); protons above 10 MeV in pfu (S1 at 10); speed km/s; Bz nT (GSM; warm = southward); Kp 0 to 9 in thirds '
        + '(G1 at 4.67); Dst nT (more negative = stronger storm).'],
    ['Cite', 'NOAA SWPC; GFZ Potsdam (Matzka et al. 2021, Space Weather 19, e2020SW002641); WDC for Geomagnetism, Kyoto (via NOAA SWPC); NASA CCMC DONKI.'],
];

async function loadStormStrip() {
    const [xray, p10, speed, bz, bt, kp, kpSwpc, dst, cmes, shocks] = await Promise.all([
        weatherSeries('goesXrayLong', '3d', false, 4), weatherSeries('goesProtonGE10MeV', '3d', false, 3),
        weatherSeries('l1WindSpeed', '3d', false, 3), weatherSeries('l1MagBzGSM', '3d', false, 3), weatherSeries('l1MagBt', '3d', false, 3),
        weatherSeries('gfzKp', '3d', true), weatherSeries('swpcKp', '3d', true), weatherSeries('swpcDst', '3d'),
        weatherEvents('cmeShown', 9), weatherEvents('ipsEarth', 4)]);
    return { xray: xray.points, p10: p10.points, speed: speed.points, bz: bz.points, bt: bt.points, kp: kp.points, kpSwpc, dst: dst.points, cmes, shocks, loadedAt: Date.now() };
}

// Dst axis: a fixed ladder of floors, ticks at the floor, half of it, zero and +50.
function dstAxis(points) {
    const floor = [-100, -200, -400, -600].find((f) => Math.min(0, ...points.map((p) => p[1] === null ? 0 : p[1])) >= f) || -600;
    return { min: floor, max: 50, invert: true, ticks: [floor, floor / 2, 0, 50], label: 'DST (NT), INVERTED', color: 'var(--tng-amber)' };
}

// Kp bars: blue, and the colour of the G level where one is reached.
const kpBarColour = (kp) => (gLevelOf(kp) ? SCALE_COLOURS[gLevelOf(kp)] : 'var(--tng-periwinkle)');
const KP_AXIS = { min: 0, max: 9, ticks: [0, 3, 6, 9], label: 'KP' };
const G1_LINE = { axis: 'left', value: 4.67, label: 'G1', color: 'var(--tng-salmon)' };

function stormStripHtml(data, width) {
    const now = data.loadedAt;
    const t1 = now + STORM_FORWARD_MS;
    const t0 = now - STORM_BACK_DAYS * WEATHER_DAY_MS;
    const lastKp = data.kp.length ? data.kp[data.kp.length - 1][0] : now;
    const kpForecast = data.kpSwpc.points.filter((p, i) => /predicted/.test(data.kpSwpc.q[i] || '') && p[0] > lastKp && p[0] <= t1);
    const speedColour = 'var(--tng-periwinkle)';
    const fieldMax = weatherLadder(Math.max(weatherMaxOf(data.bt), ...data.bz.map((p) => Math.abs(p[1] || 0))), [10, 20, 30, 50, 100]);
    const speedMax = weatherLadder(weatherMaxOf(data.speed), [800, 1000, 1200]);
    const panels = [
        { height: 100, left: { min: 1e-8, max: 1e-3, log: true, label: 'X-RAY (W/M2)', color: 'var(--tng-sand)', classes: XRAY_CLASSES, format: exponentText },
          marks: [{ type: 'line', axis: 'left', points: data.xray, color: 'var(--tng-sand)', gapMs: L1_GAP_MS, width: 1.5 }] },
        { height: 100, left: { min: 0.1, max: 1e4, log: true, label: 'PROTONS >10 MEV (PFU)', color: 'var(--tng-amber)', format: exponentText },
          lines: [{ axis: 'left', value: 10, label: 'S1', color: 'var(--tng-salmon)' }],
          marks: [{ type: 'line', axis: 'left', points: data.p10, color: 'var(--tng-amber)', gapMs: 11 * 60000, width: 1.5 }] },
        { height: 90, left: { min: 200, max: speedMax, ticks: Array.from({ length: speedMax / 200 }, (_, i) => 200 + i * 200), label: 'WIND SPEED (KM/S)', color: speedColour },
          marks: [{ type: 'line', axis: 'left', points: data.speed, color: speedColour, gapMs: L1_GAP_MS, width: 1.5 }] },
        { height: 90, left: { min: -fieldMax, max: fieldMax, ticks: [-fieldMax, 0, fieldMax], label: 'BZ AREA, BT LINE (NT)' },
          marks: [{ type: 'area', axis: 'left', points: data.bz, base: 0, colourNeg: 'var(--tng-salmon)', colourPos: 'var(--tng-periwinkle)', gapMs: L1_GAP_MS },
                  { type: 'line', axis: 'left', points: data.bt, color: 'var(--tng-sand)', gapMs: L1_GAP_MS, width: 1 }] },
        { height: 130, left: { ...KP_AXIS, color: 'var(--tng-periwinkle)' }, right: dstAxis(data.dst), lines: [G1_LINE],
          marks: [{ type: 'bars', axis: 'left', points: data.kp, barMs: KP_BLOCK_MS * 0.9, offsetMs: KP_BLOCK_MS / 2, colorOf: kpBarColour,
                    tipOf: (p) => `${chartTimeText(p[0])} block: Kp ${p[1]}${gLevelOf(p[1]) ? ` (G${gLevelOf(p[1])})` : ''}` },
                  { type: 'bars', axis: 'left', points: kpForecast, barMs: KP_BLOCK_MS * 0.9, offsetMs: KP_BLOCK_MS / 2, colorOf: () => 'var(--tng-violet)',
                    tipOf: (p) => `${chartTimeText(p[0])} block: forecast Kp ${p[1]} (NOAA SWPC)` },
                  { type: 'line', axis: 'right', points: data.dst, color: 'var(--tng-amber)', width: 2, gapMs: 2.5 * 3600000 }] },
    ];
    // the CME chain: launches, predicted arrivals, shocks seen
    const events = [];
    data.cmes.forEach((c) => {
        const r = c.record;
        const launch = Date.parse(r.startUtc);
        const arrival = r.predictedArrival ? Date.parse(r.predictedArrival) : NaN;
        if (launch >= t0 && launch <= t1) {
            events.push({ t: launch, color: 'var(--tng-sand)', label: `CME launched ${chartTimeText(launch)}: ${r.speed} km/s${r.earthBound ? ', predicted to reach Earth' : ''}` });
        }
        if (!Number.isNaN(arrival) && arrival >= t0 && arrival <= t1) {
            events.push({ t: arrival, color: 'var(--tng-salmon)', hollow: true, label: `CME predicted to arrive ${chartTimeText(arrival)} (typical error about 10 hours); launched ${chartTimeText(launch)}, ${r.speed} km/s` });
        }
    });
    data.shocks.forEach((s) => {
        events.push({ t: Date.parse(s.record.eventTime), color: 'var(--tng-salmon)',
            label: `Interplanetary shock seen at Earth (L1) ${chartTimeText(Date.parse(s.record.eventTime))}` });
    });
    const xrayAt = (ms) => {
        const i = chartNearest(data.xray.map((p) => p[0]), ms);
        return i >= 0 && Math.abs(data.xray[i][0] - ms) <= 2 * 60000 && data.xray[i][1] !== null ? `${xrayClassOf(data.xray[i][1])}` : 'no data';
    };
    const hover = (ms) => `${chartTimeText(ms)}\nX-ray ${xrayAt(ms)}, protons >10 MeV ${nearReading(data.p10, ms, 6 * 60000, 2, 'pfu')}\n`
        + `Wind ${nearReading(data.speed, ms, 2 * 60000, 0, 'km/s')}, Bz ${nearReading(data.bz, ms, 2 * 60000, 1, 'nT')}\n`
        + `Kp ${kpBlockAt(data.kp, ms) !== null ? kpBlockAt(data.kp, ms) : (kpBlockAt(kpForecast, ms) !== null ? `${kpBlockAt(kpForecast, ms)} (forecast)` : 'no data')}, Dst ${nearReading(data.dst, ms, 70 * 60000, 0, 'nT')}`;
    const svg = timePanelsSvg({ width, t0, t1, panels, events, hoverText: hover, forecastFrom: now, title: 'The storm in order: flare, protons, solar wind, Kp and Dst' });
    return chartTipFrameHtml({ title: 'THE STORM IN ORDER', tag: '3 DAYS', tip: stormTip, svg,
        legend: [{ label: 'X-ray', color: 'var(--tng-sand)' }, { label: 'Protons >10 MeV', color: 'var(--tng-amber)' }, { label: 'Wind speed', color: speedColour },
            { label: 'Bz southward', color: 'var(--tng-salmon)' }, { label: 'Kp (G colours where reached)', color: 'var(--tng-periwinkle)' }, { label: 'Kp forecast', color: 'var(--tng-violet)' },
            { label: 'Dst (inverted)', color: 'var(--tng-amber)' }],
        credit: 'NOAA GOES-18 (about 0.14 light-seconds from Earth) and SOLAR-1 at L1 (about 1.5 million km, about 5 light-seconds); Kp from GFZ Potsdam; Dst from Kyoto (provisional); CMEs from NASA DONKI.' });
}

/* --- K3: Kp with Dst, 7 days ------------------------------------------------------------------------ */

const kpDstTip = [
    ['What', 'The strength of geomagnetic activity over seven days. Bars: the planetary <b>Kp</b> index in 3-hour blocks, 0 to 9, blue and coloured with the NOAA G level (G1 sand, G2 amber, G3 tan, G4 salmon, G5 red) '
        + 'only where one is reached. Line: <b>Dst</b>, the ring current around Earth, on an inverted right axis so that a storm points the same way on both. Kp and Dst both measure the same thing, how disturbed Earth\'s '
        + 'magnetic field is, so they share a chart.'],
    ['Where from', 'Kp: GFZ Potsdam, derived from ground magnetometers around the world (definitive when available, else preliminary). Dst: the World Data Center for '
        + 'Geomagnetism, Kyoto, from four low-latitude observatories (Hermanus, Kakioka, Honolulu and San Juan); the real-time quick-look values via NOAA SWPC are provisional '
        + 'and revised later. Ground stations: no spacecraft. Collected about hourly.'],
    ['Units and thresholds', 'Kp is quasi-logarithmic from 0 (quiet) to 9, in thirds (G1 at 4.67, G2 5.67, G3 6.67, G4 7.67, G5 9). Dst in nanotesla: below &minus;30 a '
        + 'weak storm, &minus;50 moderate, &minus;100 intense, &minus;250 super-storm. The Dst axis steps in fixed floors, so a quiet week looks quiet.'],
    ['About', 'Kp responds within hours to a southward Bz; Dst falls over hours as the ring current builds and recovers over a day or more. A long gap between the two '
        + 'tells how long the magnetosphere was loaded.'],
    ['Cite', 'GFZ German Research Centre for Geosciences (Matzka et al. 2021, Space Weather 19, e2020SW002641); WDC for Geomagnetism, Kyoto (Dst), via NOAA SWPC.'],
];

async function loadKpDst() {
    const [kp, dst] = await Promise.all([weatherSeries('gfzKp', '7d', true), weatherSeries('swpcDst', '7d')]);
    return { kp, dst: dst.points, loadedAt: Date.now() };
}

function kpDstHtml(data, width) {
    const t1 = data.loadedAt;
    const t0 = t1 - 7 * WEATHER_DAY_MS;
    const panels = [{ height: 210, left: { ...KP_AXIS, color: 'var(--tng-periwinkle)' }, right: dstAxis(data.dst), lines: [G1_LINE],
        marks: [{ type: 'bars', axis: 'left', points: data.kp.points, barMs: KP_BLOCK_MS * 0.85, offsetMs: KP_BLOCK_MS / 2, colorOf: kpBarColour,
                  tipOf: (p) => `${chartTimeText(p[0])} block: Kp ${p[1]}${gLevelOf(p[1]) ? ` (G${gLevelOf(p[1])})` : ''}` },
                { type: 'line', axis: 'right', points: data.dst, color: 'var(--tng-amber)', width: 2, gapMs: 2.5 * 3600000 }] }];
    const hover = (ms) => `${chartTimeText(ms)}\nKp ${kpBlockAt(data.kp.points, ms) !== null ? kpBlockAt(data.kp.points, ms) : 'no data'}, Dst ${nearReading(data.dst, ms, 70 * 60000, 0, 'nT')}`;
    const svg = timePanelsSvg({ width, t0, t1, panels, hoverText: hover, title: 'Kp and Dst, seven days' });
    return chartTipFrameHtml({ title: 'GEOMAGNETIC ACTIVITY', tag: '7 DAYS', tip: kpDstTip, svg,
        legend: [{ label: 'Kp', color: 'var(--tng-periwinkle)' }, { label: 'Kp, G1 or more', color: SCALE_COLOURS[1] }, { label: 'Dst (Kyoto real-time quick-look, provisional), right axis, inverted', color: 'var(--tng-amber)' }],
        credit: 'Kp: GFZ Potsdam. Dst: WDC for Geomagnetism, Kyoto (via NOAA SWPC). Ground stations: no spacecraft.' });
}

/* --- Kp: SWPC's estimate against GFZ's, last 24 hours -------------------------------------------------- */

const kpCompareTip = [
    ['What', 'Paired bars for each 3-hour block of the last 24 hours: NOAA SWPC\'s real-time estimate of Kp (blue) beside GFZ Potsdam\'s Kp (sand). The two are made '
        + 'from slightly different sets of ground magnetometers and methods, and differ while GFZ\'s value is still preliminary; the NOAA scales use SWPC\'s.'],
    ['Where from', 'SWPC: its estimated planetary Kp from real-time magnetometer data. GFZ: the nowcast Kp, definitive once checked. Ground stations: no spacecraft. Collected about hourly.'],
    ['Units', 'Kp 0 to 9 in thirds. G1 begins at 4.67 (dashed line).'],
    ['Cite', 'NOAA SWPC, services.swpc.noaa.gov; GFZ Potsdam (Matzka et al. 2021).'],
];

async function loadKpCompare() {
    const [swpc, gfz] = await Promise.all([weatherSeries('swpcKp', '3d', true), weatherSeries('gfzKp', '3d', true)]);
    return { swpc, gfz, loadedAt: Date.now() };
}

function kpCompareHtml(data, width) {
    const t1 = data.loadedAt;
    const t0 = t1 - 24 * 3600000;
    const swpc = data.swpc.points.filter((p, i) => /observed/.test(data.swpc.q[i] || ''));
    const bar = KP_BLOCK_MS * 0.42;
    const panels = [{ height: 170, left: { ...KP_AXIS, color: 'var(--tng-periwinkle)' }, lines: [G1_LINE],
        marks: [{ type: 'bars', axis: 'left', points: swpc, barMs: bar, offsetMs: KP_BLOCK_MS * 0.3, color: 'var(--tng-periwinkle)', tipOf: (p) => `${chartTimeText(p[0])} block: SWPC Kp ${p[1]}` },
                { type: 'bars', axis: 'left', points: data.gfz.points, barMs: bar, offsetMs: KP_BLOCK_MS * 0.74, color: 'var(--tng-sand)',
                  tipOf: (p) => `${chartTimeText(p[0])} block: GFZ Kp ${p[1]}` }] }];
    const gfzQ = (ms) => { const i = data.gfz.points.findIndex((q) => q[0] <= ms && ms < q[0] + KP_BLOCK_MS); return i >= 0 ? (data.gfz.q[i] === 'pre' ? ' (preliminary)' : '') : ''; };
    const hover = (ms) => `${chartTimeText(ms)} block\nSWPC Kp ${kpBlockAt(swpc, ms) !== null ? kpBlockAt(swpc, ms) : 'no data'}\nGFZ Kp ${kpBlockAt(data.gfz.points, ms) !== null ? kpBlockAt(data.gfz.points, ms) : 'no data'}${gfzQ(ms)}`;
    const svg = timePanelsSvg({ width, t0, t1, panels, hoverText: hover, title: 'Kp from SWPC and GFZ, 24 hours' });
    return chartTipFrameHtml({ title: 'KP: SWPC AND GFZ', tag: '24 HOURS', tip: kpCompareTip, svg,
        legend: [{ label: 'SWPC estimate', color: 'var(--tng-periwinkle)' }, { label: 'GFZ', color: 'var(--tng-sand)' }],
        credit: 'NOAA SWPC and GFZ Potsdam, from ground magnetometers: no spacecraft.' });
}

/* --- K4: hemispheric power, 24 hours -------------------------------------------------------------------------- */

const hemiTip = [
    ['What', 'How much power the aurora is dissipating, in each hemisphere, over the last 24 hours: north and south, one axis in gigawatts. Both hemispheres usually rise and '
        + 'fall together; the difference is mostly season and sunlight.'],
    ['Where from', 'NOAA SWPC\'s hemispheric power index, estimated from the energetic electrons and protons measured by NOAA and EUMETSAT polar-orbiting satellites '
        + '(low Earth polar orbits, about 850 km altitude, about 0.003 light-seconds from Earth). Updated about every 5 minutes; collected here about hourly.'],
    ['Units and scale', 'Gigawatts (GW) of particle energy flux into the atmosphere. Quiet: about 10 to 25 GW. Active: 50 to 100 GW. A big storm: several hundred GW. '
        + 'The axis steps in fixed ladders (50, 100, 200, 400 GW).'],
    ['About', 'More power means a brighter and more extended oval, pushed further from the pole. The AURORAE view shows where.'],
    ['Cite', 'NOAA Space Weather Prediction Center, services.swpc.noaa.gov (hemispheric power); Fuller-Rowell, T. J. and Evans, D. S. (1987), J. Geophys. Res. 92, 7606 (the power index from TIROS/NOAA particle data).'],
];

async function loadHemiPower() {
    const [north, south] = await Promise.all([weatherSeries('hemiPowerNorth', '24h'), weatherSeries('hemiPowerSouth', '24h')]);
    return { north: north.points, south: south.points, loadedAt: Date.now() };
}

function hemiPowerHtml(data, width) {
    const t1 = data.loadedAt;
    const t0 = t1 - 24 * 3600000;
    const max = weatherLadder(Math.max(weatherMaxOf(data.north), weatherMaxOf(data.south)), [50, 100, 200, 400]);
    const panels = [{ height: 150, left: { min: 0, max, ticks: weatherSteps(max, 4), label: 'HEMISPHERIC POWER (GW)' },
        marks: [{ type: 'line', axis: 'left', points: data.north, color: 'var(--tng-sand)', width: 2, gapMs: 11 * 60000 },
                { type: 'line', axis: 'left', points: data.south, color: 'var(--tng-periwinkle)', width: 2, gapMs: 11 * 60000 }] }];
    const hover = (ms) => `${chartTimeText(ms)}\nNorth ${nearReading(data.north, ms, 8 * 60000, 0, 'GW')}, south ${nearReading(data.south, ms, 8 * 60000, 0, 'GW')}`;
    const svg = timePanelsSvg({ width, t0, t1, panels, hoverText: hover, title: 'Hemispheric power, 24 hours' });
    return chartTipFrameHtml({ title: 'AURORAL POWER', tag: '24 HOURS', tip: hemiTip, svg,
        legend: [{ label: 'North', color: 'var(--tng-sand)' }, { label: 'South', color: 'var(--tng-periwinkle)' }],
        credit: 'NOAA SWPC, from NOAA and EUMETSAT polar-orbiting satellites (about 850 km up, about 0.003 light-seconds from Earth).' });
}

/* --- K7: the Kp forecast grid, 3 days; K8: the forecast probabilities ---------------------------------------- */

const kpGridTip = [
    ['What', 'NOAA\'s three-day forecast of the Kp index, one cell for each 3-hour block: a row for each day, the eight blocks across, the cell colour by the forecast Kp '
        + '(pale for quiet, sand for unsettled, and the G colours, sand to red, where a geomagnetic storm level is forecast; a cell that reaches G1 has a bright outline).'],
    ['Where from', 'NOAA SWPC\'s 3-day forecast, issued twice a day by forecasters at SWPC (around 00:30 and 12:30 UTC) from the Sun\'s state, coronal-hole and CME '
        + 'analysis and models; collected here about hourly. A forecast, not a measurement.'],
    ['Units', 'Kp 0 to 9 in thirds; G1 at 4.67, G2 5.67, G3 6.67, G4 7.67, G5 9. Times are UTC and are the start of each 3-hour block.'],
    ['Limits', 'Forecast skill falls quickly beyond a day; a CME that has not yet been seen at L1 can change the third day completely.'],
    ['Cite', 'NOAA Space Weather Prediction Center, services.swpc.noaa.gov, 3-day forecast (product 3-day-forecast.txt).'],
];

async function loadKpGrid() {
    const kp = await weatherSeries('swpcForecast3dayKp', '3d', true);
    return { kp: kp.points, issued: (kp.q.find((q) => /issued/.test(q || '')) || '').replace('issued ', ''), loadedAt: Date.now() };
}

function kpCellColour(kp) {
    return gLevelOf(kp) ? SCALE_COLOURS[gLevelOf(kp)] : kp >= 3.5 ? 'var(--tng-sand)' : kp >= 2 ? 'var(--tng-ice)' : 'var(--tng-periwinkle)';
}

// The sentence about the visitor's own required Kp under a Kp grid (nothing when there is no location).
function requiredKpCredit(required) {
    if (required === undefined || required === null) {
        return '';
    }
    return required === Infinity ? ' At your geomagnetic latitude aurora needs more than Kp 9, so no block is outlined.'
        : ` Dashed outline: a block whose forecast Kp reaches about ${required.toFixed(1)}, where aurora is commonly seen at your geomagnetic latitude (NOAA's rule of thumb, with the sky dark and clear).`;
}

function kpGridHtml(data, width, options = {}) {
    const days = [...new Set(data.kp.map((p) => Math.floor(p[0] / WEATHER_DAY_MS)))].sort();
    const left = 74;
    const top = 26;
    const cell = Math.max(24, (width - left - 8) / 8);
    const rowH = 36;
    const height = top + days.length * rowH + 4;
    let svg = '';
    for (let b = 0; b < 8; b += 1) {
        svg += `<text class="lcars-line-xtick" x="${(left + (b + 0.5) * cell).toFixed(1)}" y="16" text-anchor="middle">${String(b * 3).padStart(2, '0')}-${String(b * 3 + 3).padStart(2, '0')}</text>`;
    }
    days.forEach((day, row) => {
        svg += `<text class="lcars-line-ytick" x="${left - 8}" y="${top + row * rowH + rowH / 2}" dy="0.35em" text-anchor="end">${weatherDateText(day * WEATHER_DAY_MS).slice(0, -5)}</text>`;
        for (let b = 0; b < 8; b += 1) {
            const p = data.kp.find((q) => q[0] === day * WEATHER_DAY_MS + b * KP_BLOCK_MS);
            const x = left + b * cell;
            const y = top + row * rowH;
            if (!p) {
                svg += `<rect x="${x.toFixed(1)}" y="${y}" width="${(cell - 2).toFixed(1)}" height="${rowH - 3}" fill="#111"><title>${chartTimeText(day * WEATHER_DAY_MS + b * KP_BLOCK_MS)}: no forecast</title></rect>`;
                continue;
            }
            const reaches = options.requiredKp !== undefined && options.requiredKp !== null && p[1] >= options.requiredKp;
            svg += `<rect class="chart-hit" x="${x.toFixed(1)}" y="${y}" width="${(cell - 2).toFixed(1)}" height="${rowH - 3}" fill="${kpCellColour(p[1])}"${gLevelOf(p[1]) ? ' stroke="var(--space-white)" stroke-width="2"' : ''}>`
                + `<title>${chartTimeText(p[0])} block: forecast Kp ${p[1]}${gLevelOf(p[1]) ? ` (G${gLevelOf(p[1])})` : ''}${reaches ? ` -- reaches the Kp you need here (about ${options.requiredKp.toFixed(1)}) for aurora` : ''}</title></rect>`
                + (reaches ? `<rect class="kp-required" x="${(x + 4).toFixed(1)}" y="${y + 4}" width="${(cell - 10).toFixed(1)}" height="${rowH - 11}" fill="none" stroke="var(--tng-ice)" stroke-width="2" stroke-dasharray="4 3"/>` : '')
                + `<text x="${(x + (cell - 2) / 2).toFixed(1)}" y="${y + (rowH - 3) / 2}" dy="0.35em" text-anchor="middle" fill="#000">${p[1].toFixed(1)}</text>`;
        }
    });
    const grid = `<div class="chart-time-body">${chartSvgHtml(width, height, 'Forecast Kp, three days', [svg])}</div>`;
    return chartTipFrameHtml({ title: options.title || 'THREE-DAY FORECAST', tag: data.issued ? `ISSUED ${chartTimeText(Date.parse(data.issued)).slice(5, 16)} UTC` : '3 DAYS', tip: kpGridTip, svg: grid,
        legend: [{ label: 'Kp under 2', color: 'var(--tng-periwinkle)' }, { label: '2 to 3.5', color: 'var(--tng-ice)' }, { label: '3.5 to G1', color: 'var(--tng-sand)' }, { label: 'G1', color: SCALE_COLOURS[1] }, { label: 'G2 or more', color: SCALE_COLOURS[2] }]
            .concat(options.requiredKp !== undefined && options.requiredKp !== null ? [{ label: 'dashed: reaches the Kp you need for aurora', color: 'var(--tng-ice)' }] : []),
        credit: `NOAA SWPC three-day forecast: a forecast, not a measurement.${requiredKpCredit(options.requiredKp)}` });
}

const probTip = [
    ['What', 'NOAA\'s three-day forecast chances for the next three UTC days: a solar flare of class M1 to M9 (R1 to R2) and of X class or more (R3 or more), and a solar '
        + 'radiation storm (S1 or more); and the highest geomagnetic storm level the Kp forecast reaches (G0 to G5). The bar is the probability in per cent.'],
    ['Where from', 'NOAA SWPC\'s 3-day forecast, issued about 00:30 and 12:30 UTC; the flare and proton chances are the forecasters\' judgement from the Sun\'s active regions '
        + 'seen by NASA SDO and the GOES satellites (geostationary, about 0.14 light-seconds from Earth). The G level is the highest of the day\'s forecast Kp blocks. Collected here about hourly.'],
    ['Limits', 'A probability of 15% means that in 100 such forecasts a flare of that class follows in about 15; it is not a prediction for one day. The R and S scales are defined in the NOAA SCALES tooltip.'],
    ['Cite', 'NOAA Space Weather Prediction Center, services.swpc.noaa.gov, 3-day forecast.'],
];

async function loadForecastProbabilities() {
    const [minor, major, proton, kp] = await Promise.all(['swpcForecast3dayR1R2Prob', 'swpcForecast3dayR3Prob', 'swpcForecast3dayS1Prob'].map((n) => weatherSeries(n, '3d', true))
        .concat([weatherSeries('swpcForecast3dayKp', '3d', true)]));
    return { minor: minor.points, major: major.points, proton: proton.points, kp: kp.points, issued: (minor.q.find((q) => /issued/.test(q || '')) || '').replace('issued ', ''), loadedAt: Date.now() };
}

function forecastProbabilitiesHtml(data, width, options = {}) {
    const days = [...new Set(data.minor.concat(data.major, data.proton).map((p) => p[0]))].sort().slice(0, 3);
    const bar = (points, day, colour, label) => {
        const p = points.find((q) => q[0] === day);
        return `<div class="weather-prob-cell" title="${escapeChartText(`${label}, ${weatherDateText(day)}: ${p ? `${p[1]}%` : 'no forecast'}`)}"><span class="weather-prob-bar" style="width:${p ? p[1] : 0}%;background:${colour}"></span>`
            + `<span class="weather-prob-text">${p ? `${p[1]}%` : '--'}</span></div>`;
    };
    const gMax = (day) => {
        const blocks = data.kp.filter((q) => q[0] >= day && q[0] < day + WEATHER_DAY_MS);
        return blocks.length ? Math.max(...blocks.map((q) => gLevelOf(q[1]))) : null;
    };
    const rows = [['FLARE R1-R2 (M)', data.minor, 'var(--tng-amber)'], ['FLARE R3+ (X)', data.major, 'var(--tng-salmon)'], ['PROTONS S1+', data.proton, 'var(--tng-lavender)']];
    const grid = `<div class="weather-prob"><span></span>${days.map((d) => `<span class="weather-prob-head">${weatherDateText(d).slice(0, -5)}</span>`).join('')}`
        + rows.map(([label, points, colour]) => `<span class="weather-prob-label">${label}</span>${days.map((d) => bar(points, d, colour, label)).join('')}`).join('')
        + (options.noG ? '' : `<span class="weather-prob-label">HIGHEST G LEVEL</span>${days.map((d) => `<div class="weather-prob-cell"><span class="weather-prob-text" style="color:${gMax(d) === null ? 'inherit' : SCALE_COLOURS[gMax(d)]}">${gMax(d) === null ? '--' : `G${gMax(d)}`}</span></div>`).join('')}`) + '</div>';
    return chartTipFrameHtml({ title: options.title || 'FORECAST CHANCES', tag: data.issued ? `ISSUED ${chartTimeText(Date.parse(data.issued)).slice(5, 16)} UTC` : '3 DAYS', tip: probTip, svg: grid,
        credit: 'NOAA SWPC three-day forecast: chances in per cent, not measurements.' });
}
