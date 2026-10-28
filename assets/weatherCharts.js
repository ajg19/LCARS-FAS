/* ==========================================================================
   WEATHER CHARTS -- the shared chart components of the WEATHER views
   (spaceWeatherChartsPlan.md, section 3: K1 to K10). Each is built once
   here and given its own pill title where a view shows it. Drawing is by
   assets/chartCore.js and assets/chartTime.js; this file holds what is
   specific to the data: series names, scales, colours, the words of the
   tooltips.

   Lazy: loaded, with the two chart files, the first time a view that shows
   a chart is opened (weatherPanel.js). Data from /api/weather/series
   (siteWeather.db; python scripts/publishSite.py weather).

   Built so far (SOL DRVR): K1 the L1 solar wind, K2 flares and particles, the 30-day flare record, the long view
   of F10.7 and the sunspot number, the solar cycle, K6 the CME timeline, K5 the outlook.
   ========================================================================== */

// The two bands of every view use the same two colours, so the reader learns them.
const WEATHER_BAND_COLOURS = { now: 'var(--tng-amber)', predictive: 'var(--tng-violet)' };

const WEATHER_DAY_MS = 86400000;

// A series as [[ms, value]], or [] if the site does not hold it (404) or the fetch fails.
async function weatherSeriesPoints(name, range) {
    try {
        const response = await fetch(`api/weather/series?name=${name}&range=${range}`);
        if (!response.ok) {
            return [];
        }
        const data = await response.json();
        return data.t.map((stamp, i) => [Date.parse(stamp), data.v[i]]);
    } catch (error) {
        console.error(`Error loading weather series ${name}:`, error);
        return [];
    }
}

// The smallest rung of a fixed ladder that holds the data: the scale depends on the size of
// the data in steps, never stretched to fit it, so two lines cannot be made to look alike.
function weatherLadder(maxValue, rungs) {
    return rungs.find((r) => r >= maxValue) || rungs[rungs.length - 1];
}

const weatherMaxOf = (points) => points.reduce((best, p) => (p[1] !== null && p[1] > best ? p[1] : best), 0);
const weatherSteps = (max, count) => Array.from({ length: count + 1 }, (_, i) => (max * i) / count);

/* --- K1: L1 solar wind ------------------------------------------------------- */

const L1_RANGE_DAYS = 3;
const L1_GAP_MS = 3 * 60000 + 1;          // joins gaps of up to three minutes; longer ones stay gaps
const L1_STRONG_DRIVING = 5;              // mV/m: the shading threshold of panel C (to be confirmed by Spock)
// Panel C scales go together in steps, so that neither line is stretched to the other.
const L1_COUPLING_LADDER = [[10, 40000], [20, 80000], [50, 200000]];   // [E mV/m, Newell]

// E = v x Bs (mV/m): speed in km/s times the southward part of Bz in nT, divided by 1000.
function l1ConvectionField(speed, bz) {
    const bzByTime = new Map(bz.map((p) => [p[0], p[1]]));
    return speed.map((p) => {
        const z = bzByTime.get(p[0]);
        return [p[0], p[1] === null || z === undefined || z === null ? null : (p[1] * Math.max(0, -z)) / 1000];
    });
}

// Runs of time where a series is at or above a threshold, [[from, to]], bridging gaps of up to three minutes.
function l1RunsAbove(points, threshold) {
    const runs = [];
    points.forEach((p) => {
        if (p[1] === null || p[1] < threshold) {
            return;
        }
        const last = runs[runs.length - 1];
        if (last && p[0] - last[1] <= L1_GAP_MS) {
            last[1] = p[0] + 60000;
        } else {
            runs.push([p[0], p[0] + 60000]);
        }
    });
    return runs;
}

const l1Tip = [
    ['What', 'The solar wind and its magnetic field as they pass the spacecraft that watches for the Sun\'s weather, '
        + 'three days on one UTC time axis. <b>A</b> speed (left) and density (right): a fast, dense wind pushes harder on '
        + 'Earth\'s magnetic field. <b>B</b> the field\'s north-south part, <b>Bz</b>, as an area (warm = southward, which '
        + 'connects to Earth\'s field and drives storms; cool = northward), with the total field <b>Bt</b> as a line. '
        + '<b>C</b> two indicators of how hard the wind is driving Earth\'s magnetosphere.'],
    ['Where from', 'NOAA SOLAR-1 (formerly SWFO-L1), real-time solar wind and magnetic field, via NOAA SWPC. A spacecraft at '
        + 'the Sun-Earth Lagrange point L1, sunward of Earth, about 1.5 million km away: about 5 light-seconds. '
        + 'When SOLAR-1 is unavailable SWPC publishes a back-up L1 spacecraft (ACE or DSCOVR), also about 5 light-seconds from Earth. '
        + 'One-minute values, provisional. This site collects them about hourly, so the right-hand edge can be an hour or more behind the spacecraft.'],
    ['Warning time', 'What the 5 light-seconds does <i>not</i> mean: the wind moves at 300 to 1,000 km/s, not at the speed of light, '
        + 'so it takes about 1,500,000 km / speed to reach Earth: about 60 minutes at 400 km/s, 30 minutes at 800 km/s '
        + '(the warning time is the travel time of the wind, not of light). A flare\'s light, by contrast, arrives in 8 minutes.'],
    ['Units', 'Speed km/s; density protons per cm&sup3;; fields in nanotesla (nT), GSM coordinates (Bz positive towards the '
        + 'north). Gaps up to 3 minutes are joined; longer ones are left as gaps. Nothing is interpolated or filled in from other spacecraft. '
        + 'Axes are fixed in steps (speed 200 to 800, 1,000 or 1,200 km/s; density up to 20, 50, 100 or 200), so a quiet '
        + 'day looks quiet.'],
    ['Panel C', '<b>E</b> = v &times; Bs / 1000 (mV/m), where v is the speed in km/s and Bs is the southward part of Bz in nT '
        + '(Bs = &minus;Bz when Bz is negative, otherwise 0): the electric field the wind carries across Earth\'s field. '
        + '<b>Newell function</b> dPhi/dt = v<sup>4/3</sup> &times; B<sub>T</sub><sup>2/3</sup> &times; |sin(&theta;/2)|<sup>8/3</sup>, '
        + 'with B<sub>T</sub> = &radic;(By&sup2; + Bz&sup2;) and &theta; = atan2(By, Bz) the clock angle of the field in the y-z plane '
        + '(units (km/s)<sup>4/3</sup> nT<sup>2/3</sup>; Newell et al. 2007). Both are <i>indicators</i> computed from the '
        + 'measurements, not measurements; they ignore density and the state of the magnetosphere, and Earth sees them '
        + 'delayed by the travel time above. The pale bands mark E at or above ' + L1_STRONG_DRIVING + ' mV/m (strong driving; threshold provisional).'],
    ['About', 'A storm needs Bz to stay southward for hours. Fast wind alone (from a coronal hole) with northward Bz '
        + 'does little; a modest wind with a long strong southward Bz can drive a big storm.'],
    ['Cite', 'NOAA Space Weather Prediction Center, services.swpc.noaa.gov (real-time solar wind); Newell, P. T., Sotirelis, T., '
        + 'Liou, K., Meng, C.-I. and Rich, F. J. (2007), J. Geophys. Res. 112, A01206.'],
];

async function loadL1Data() {
    const range = `${L1_RANGE_DAYS}d`;
    const [speed, density, bz, bt, newell] = await Promise.all(['l1WindSpeed', 'l1WindDensity', 'l1MagBzGSM', 'l1MagBt', 'derivedNewell']
        .map((name) => weatherSeriesPoints(name, range)));
    return { speed, density, bz, bt, newell, e: l1ConvectionField(speed, bz), loadedAt: Date.now() };
}

// The nearest reading within two minutes of a time, as text.
function l1ReadingAt(points, ms, digits, unit) {
    const times = points.map((p) => p[0]);
    const i = chartNearest(times, ms);
    return i >= 0 && Math.abs(times[i] - ms) <= 2 * 60000 && points[i][1] !== null ? `${points[i][1].toFixed(digits)} ${unit}` : 'no data';
}

// K1 as an HTML string, drawn to the width of its slot.
function l1SolarWindHtml(data, width) {
    const t1 = data.loadedAt;
    const t0 = t1 - L1_RANGE_DAYS * WEATHER_DAY_MS;
    const speedMax = weatherLadder(weatherMaxOf(data.speed), [800, 1000, 1200]);
    const densityMax = weatherLadder(weatherMaxOf(data.density), [20, 50, 100, 200]);
    const fieldMax = weatherLadder(Math.max(weatherMaxOf(data.bt), ...data.bz.map((p) => Math.abs(p[1] || 0))), [10, 20, 30, 50, 100]);
    const [eMax, newellMax] = L1_COUPLING_LADDER.find(([e, n]) => weatherMaxOf(data.e) <= e && weatherMaxOf(data.newell) <= n)
        || L1_COUPLING_LADDER[L1_COUPLING_LADDER.length - 1];
    const speedColour = 'var(--tng-periwinkle)';
    const densityColour = 'var(--tng-amber)';
    const eColour = 'var(--tng-sand)';
    const newellColour = 'var(--tng-lavender)';
    const gapMs = L1_GAP_MS;
    const panels = [
        { height: 150,
          left: { min: 200, max: speedMax, ticks: Array.from({ length: speedMax / 200 }, (_, i) => 200 + i * 200), label: 'SPEED (KM/S)', color: speedColour },
          right: { min: 0, max: densityMax, ticks: weatherSteps(densityMax, 4), label: 'DENSITY (CM-3), DASHED', color: densityColour },
          marks: [{ type: 'line', axis: 'left', points: data.speed, color: speedColour, gapMs },
                  { type: 'line', axis: 'right', points: data.density, color: densityColour, gapMs, dash: '6 4' }] },
        { height: 150,
          left: { min: -fieldMax, max: fieldMax, ticks: [-fieldMax, -fieldMax / 2, 0, fieldMax / 2, fieldMax], label: 'BZ AREA, BT LINE (NT)' },
          marks: [{ type: 'area', axis: 'left', points: data.bz, base: 0, colourNeg: 'var(--tng-salmon)', colourPos: 'var(--tng-periwinkle)', gapMs },
                  { type: 'line', axis: 'left', points: data.bt, color: 'var(--tng-sand)', gapMs, width: 1.5 }] },
        { height: 130,
          left: { min: 0, max: eMax, ticks: weatherSteps(eMax, 2), label: 'E = V x BS (MV/M)', color: eColour },
          right: { min: 0, max: newellMax, ticks: weatherSteps(newellMax, 2), label: 'NEWELL (x1000), DASHED', color: newellColour,
              format: (n) => (n / 1000).toLocaleString('en-GB') },
          marks: [{ type: 'shade', runs: l1RunsAbove(data.e, L1_STRONG_DRIVING), color: 'var(--tng-salmon)' },
                  { type: 'line', axis: 'left', points: data.e, color: eColour, gapMs },
                  { type: 'line', axis: 'right', points: data.newell, color: newellColour, gapMs, dash: '6 4' }] },
    ];
    const hoverText = (ms) => `${chartTimeText(ms)}\n`
        + `Speed ${l1ReadingAt(data.speed, ms, 0, 'km/s')}, density ${l1ReadingAt(data.density, ms, 1, 'cm-3')}\n`
        + `Bz ${l1ReadingAt(data.bz, ms, 1, 'nT')}, Bt ${l1ReadingAt(data.bt, ms, 1, 'nT')}\n`
        + `E ${l1ReadingAt(data.e, ms, 2, 'mV/m')}, Newell ${l1ReadingAt(data.newell, ms, 0, '')}`;
    const svg = timePanelsSvg({ width, t0, t1, panels, hoverText, title: 'L1 solar wind, three days' });
    return chartTipFrameHtml({
        title: 'L1 SOLAR WIND', tag: '3 DAYS', tip: l1Tip, svg,
        legend: [{ label: 'Speed', color: speedColour }, { label: 'Density (right axis)', color: densityColour },
            { label: 'Bz southward', color: 'var(--tng-salmon)' }, { label: 'Bz northward', color: 'var(--tng-periwinkle)' },
            { label: 'Bt', color: 'var(--tng-sand)' }, { label: 'E (left axis)', color: eColour },
            { label: 'Newell (right axis)', color: newellColour }],
        credit: 'NOAA SOLAR-1 at L1, about 1.5 million km sunward of Earth (about 5 light-seconds), real-time, via NOAA SWPC. '
            + 'The wind takes about 30 to 60 minutes to cover that distance.',
    });
}

/* --- Shared helpers for the charts below ------------------------------------------- */

// Requests are remembered for the life of one view opening (cleared by weatherForgetData()), so a series two
// charts need is fetched once.
const weatherFetchCache = new Map();

function weatherForgetData() {
    weatherFetchCache.clear();
}

// {points: [[ms, value]], q: [quality text]} of a series; empty if the site does not hold it. quality=true
// asks the server for the quality text of each sample (burst?, provisional, forecast included ...); sig rounds the
// values to that many significant figures (the log-scale charts need no more than 4), which shrinks the answer.
function weatherSeries(name, range, quality = false, sig = 0) {
    const key = `${name}|${range}|${quality}|${sig}`;
    if (!weatherFetchCache.has(key)) {
        weatherFetchCache.set(key, (async () => {
            try {
                const response = await fetch(`api/weather/series?name=${name}&range=${range}${quality ? '&quality=1' : ''}${sig ? `&sig=${sig}` : ''}`);
                if (!response.ok) {
                    return { points: [], q: [] };
                }
                const data = await response.json();
                return { points: data.t.map((stamp, i) => [Date.parse(stamp), data.v[i]]), q: data.q || [] };
            } catch (error) {
                console.error(`Error loading weather series ${name}:`, error);
                return { points: [], q: [] };
            }
        })());
    }
    return weatherFetchCache.get(key);
}

// [{startUtc, id, record}] of an event type from the last `days` days; empty on failure.
function weatherEvents(type, days) {
    const key = `events|${type}|${days}`;
    if (!weatherFetchCache.has(key)) {
        weatherFetchCache.set(key, (async () => {
            try {
                const response = await fetch(`api/weather/events?type=${type}&days=${days}`);
                return response.ok ? (await response.json()).events : [];
            } catch (error) {
                console.error(`Error loading weather events ${type}:`, error);
                return [];
            }
        })());
    }
    return weatherFetchCache.get(key);
}

// Draw a chart into a slot once the slot is near the screen (or at once where the browser cannot tell):
// the data of a chart far down the page are not fetched until the visitor scrolls towards it.
function weatherDrawWhenNear(slot, loader, drawer, minWidth = 480) {
    slot.dataset.weatherChart = '1';
    slot.drawer = drawer;
    slot.minWidth = minWidth;
    const start = async () => {
        slot.innerHTML = '<p class="weather-status">Loading...</p>';
        slot.chartData = await loader();
        weatherRedraw(slot);
    };
    if (typeof IntersectionObserver === 'undefined') {
        start();
        return;
    }
    const watcher = new IntersectionObserver((entries) => {
        if (entries.some((e) => e.isIntersecting)) {
            watcher.disconnect();
            start();
        }
    }, { rootMargin: '400px' });
    watcher.observe(slot);
}

function weatherRedraw(slot) {
    if (slot.chartData && slot.drawer) {
        slot.innerHTML = slot.drawer(slot.chartData, chartWidth(slot, slot.minWidth || 480));
    }
}

// A drawer that shows the "no data yet" note instead of a chart when has(data) is false.
const weatherGuard = (has, draw) => (data, width) => (has(data) ? draw(data, width) : WEATHER_NO_DATA);

function weatherRedrawAll(root) {
    root.querySelectorAll('[data-weather-chart]').forEach(weatherRedraw);
}

const WEATHER_FLARE_COLOURS = { A: 'var(--tng-mauve)', B: 'var(--tng-mauve)', C: 'var(--tng-ice)', M: 'var(--tng-amber)', X: 'var(--tng-salmon)' };
const WEATHER_NO_DATA = '<p class="weather-status">No data yet for this chart. On a DEV server run <code>python scripts/publishSite.py weather</code>.</p>';

// "M1.6" from a flux in W/m2 (the GOES long channel): the letter is the decade, the number the multiple.
function xrayClassOf(flux) {
    if (!(flux > 0)) {
        return 'no data';
    }
    const [letter, base] = [['X', 1e-4], ['M', 1e-5], ['C', 1e-6], ['B', 1e-7]].find(([, b]) => flux >= b) || ['A', 1e-8];
    return `${letter}${(flux / base).toFixed(1)}`;
}

const weatherDateText = (ms) => `${new Date(ms).getUTCDate()} ${CHART_MONTHS[new Date(ms).getUTCMonth()]} ${new Date(ms).getUTCFullYear()}`;

// The log axes of the flare and proton charts: decades, with the NOAA class letters in faint bands.
const XRAY_CLASSES = [{ from: 1e-8, to: 1e-7, label: 'A' }, { from: 1e-7, to: 1e-6, label: 'B' }, { from: 1e-6, to: 1e-5, label: 'C' },
    { from: 1e-5, to: 1e-4, label: 'M' }, { from: 1e-4, to: 1e-3, label: 'X' }];
const XRAY_LINES = [{ axis: 'left', value: 1e-5, label: 'R1 (M1)' }, { axis: 'left', value: 5e-5, label: 'R2 (M5)' }, { axis: 'left', value: 1e-4, label: 'R3 (X1)' }];
const exponentText = (n) => `1e${Math.round(Math.log10(n))}`;

/* --- K2: flares and particles ------------------------------------------------------- */

const k2Tip = [
    ['What', 'Two panels on one UTC time axis, in the order things happen. <b>Top:</b> the Sun\'s X-ray output, on a log axis with '
        + 'the NOAA flare classes A, B, C, M and X; M-class and X-class flares are marked through both panels at their peak. '
        + '<b>Bottom:</b> energetic protons (above 10 MeV and above 100 MeV), also on a log axis, with the S1 radiation-storm '
        + 'line; solar energetic particle events are marked. The X-rays reach Earth at the speed of light, 8 minutes after the '
        + 'flare; the protons arrive from about 10 minutes to many hours later, if at all. That delay is why they are stacked, not overlaid.'],
    ['Where from', 'NOAA GOES-18 (the primary GOES satellite), in geostationary orbit 35,786 km above the equator, '
        + 'about 42,164 km from Earth\'s centre: about 0.14 light-seconds. X-rays from its XRS instrument (long channel, 0.1 to 0.8 nm), '
        + 'protons from its SEISS instrument, via NOAA SWPC. One-minute X-ray and five-minute proton values, collected about hourly '
        + 'by this site, so the right-hand edge can be an hour or more behind. Flare markers come from NOAA\'s edited event list; '
        + 'particle events from NASA\'s DONKI and from this site\'s own S-event rule below.'],
    ['Units and thresholds', 'X-ray flux in watts per square metre. Class = the decade of the peak flux, with a multiplier: '
        + 'A below 1e-7, B 1e-7, C 1e-6, M 1e-5, X 1e-4 (M3.4 is 3.4e-5 W/m&sup2;). NOAA radio-blackout scale: R1 at M1, R2 at M5, '
        + 'R3 at X1 (R4 at X10, R5 at X20). Protons in particles per cm&sup2; per second per steradian (pfu); S1 is 10 pfu above '
        + '10 MeV (S2 100, S3 1,000, S4 10,000, S5 100,000). An S-event starts at the first of three consecutive 5-minute values at or above 10 pfu and ends at the last value at or above 10 pfu.'],
    ['Limits', 'The proton floor (about 0.15 to 0.45 pfu) is galactic cosmic rays, not the Sun, so it is shaded and labelled GCR. '
        + 'The short X-ray channel is not drawn: most of it is contaminated by electrons. Gaps in the data are left as gaps.'],
    ['About', 'Flares are sudden releases of magnetic energy; their X-rays ionise the daylight side of Earth\'s upper atmosphere and '
        + 'can black out HF radio within minutes. Fast particles follow, driven by the flare or by the shock of a coronal mass ejection.'],
    ['Cite', 'NOAA Space Weather Prediction Center, services.swpc.noaa.gov (GOES-R XRS and SEISS data; NOAA Space Weather Scales); '
        + 'NASA CCMC DONKI, kauai.ccmc.gsfc.nasa.gov/DONKI (particle events).'],
];

async function loadK2() {
    const [xray, p10, p100, flares, sep, sEvents] = await Promise.all([
        weatherSeries('goesXrayLong', '3d', false, 4), weatherSeries('goesProtonGE10MeV', '3d', false, 3), weatherSeries('goesProtonGE100MeV', '3d', false, 3),
        weatherEvents('flare', 3), weatherEvents('sepGroup', 7), weatherEvents('sEvent', 3)]);
    return { xray: xray.points, p10: p10.points, p100: p100.points, flares, sep, sEvents, loadedAt: Date.now() };
}

// Flares of class M or X (one marker per peak time, whichever satellite listed them), SEP and S-event markers.
function k2Events(data, t0, t1) {
    const events = [];
    const seen = new Set();
    data.flares.forEach((f) => {
        const r = f.record;
        const cls = r.max_class || '';
        const t = Date.parse(r.max_time || f.startUtc);
        if (!/^[MX]/.test(cls) || seen.has(t)) {
            return;
        }
        seen.add(t);
        events.push({ t, color: cls[0] === 'X' ? WEATHER_FLARE_COLOURS.X : WEATHER_FLARE_COLOURS.M,
            label: `${cls} flare, peak ${chartTimeText(t)} (begin ${r.begin_class || '?'}, end ${r.end_class || '?'}), ${r.satellite ? `GOES-${r.satellite}` : 'GOES'}` });
    });
    data.sep.filter((e) => Date.parse(e.startUtc) >= t0 && Date.parse(e.startUtc) <= t1).forEach((e) => {
        events.push({ t: Date.parse(e.startUtc), color: 'var(--tng-lavender)', hollow: e.record.status !== 'observed',
            label: `Solar energetic particle event (NASA DONKI), ${e.record.status === 'observed' ? 'observed' : 'forecast by model'}, start ${chartTimeText(Date.parse(e.startUtc))}` });
    });
    data.sEvents.forEach((e) => {
        events.push({ t: Date.parse(e.startUtc), color: 'var(--tng-lavender)',
            label: `S-event (>10 MeV at or above 10 pfu) from ${chartTimeText(Date.parse(e.startUtc))}, peak ${Number(e.record.peakPfu).toFixed(0)} pfu` });
    });
    return events;
}

function k2Html(data, width, options = {}) {
    const t1 = data.loadedAt;
    const t0 = t1 - 3 * WEATHER_DAY_MS;
    const xrayColour = 'var(--tng-sand)';
    const p10Colour = 'var(--tng-amber)';
    const p100Colour = 'var(--tng-periwinkle)';
    const panels = [
        { height: 150,
          left: { min: 1e-8, max: 1e-3, log: true, label: 'X-RAY FLUX (W/M2), 0.1-0.8 NM', color: xrayColour, classes: XRAY_CLASSES, format: exponentText },
          lines: XRAY_LINES.map((l) => ({ ...l, color: 'var(--tng-salmon)' })),
          marks: [{ type: 'line', axis: 'left', points: data.xray, color: xrayColour, gapMs: L1_GAP_MS, width: 1.5 }] },
        { height: 150,
          left: { min: 0.1, max: 1e4, log: true, label: 'PROTONS (PFU)', classes: [{ from: 0.1, to: 0.5, label: 'GCR' }, { from: 10, to: 100, label: 'S1' },
              { from: 100, to: 1000, label: 'S2' }, { from: 1000, to: 1e4, label: 'S3' }], format: exponentText },
          lines: [{ axis: 'left', value: 10, label: 'S1 (10 pfu, >10 MeV)', color: 'var(--tng-salmon)' }],
          marks: [{ type: 'line', axis: 'left', points: data.p10, color: p10Colour, gapMs: 11 * 60000, width: 1.5 },
                  { type: 'line', axis: 'left', points: data.p100, color: p100Colour, gapMs: 11 * 60000, width: 1.5 }] },
    ];
    const events = k2Events(data, t0, t1);
    // readings: class text for the X-ray, pfu for the protons
    const xrayAt = (ms) => {
        const times = data.xray.map((p) => p[0]);
        const i = chartNearest(times, ms);
        return i >= 0 && Math.abs(times[i] - ms) <= 2 * 60000 && data.xray[i][1] !== null ? `${xrayClassOf(data.xray[i][1])} (${data.xray[i][1].toExponential(2)} W/m2)` : 'no data';
    };
    const hover = (ms) => `${chartTimeText(ms)}\nX-ray ${xrayAt(ms)}\nProtons >10 MeV ${l1ReadingAt(data.p10, ms, 2, 'pfu')}, >100 MeV ${l1ReadingAt(data.p100, ms, 2, 'pfu')}`;
    const svg = timePanelsSvg({ width, t0, t1, panels, events, hoverText: hover, title: 'Flares and particles, three days' });
    return chartTipFrameHtml({
        title: options.title || 'FLARES AND PARTICLES', tag: '3 DAYS', tip: options.tipExtra ? k2Tip.concat(options.tipExtra) : k2Tip, svg,
        legend: [{ label: 'X-ray, long channel', color: xrayColour }, { label: 'Protons >10 MeV', color: p10Colour }, { label: 'Protons >100 MeV', color: p100Colour },
            { label: 'M flare', color: WEATHER_FLARE_COLOURS.M }, { label: 'X flare', color: WEATHER_FLARE_COLOURS.X }, { label: 'Particle event', color: 'var(--tng-lavender)' }],
        credit: 'NOAA GOES-18, geostationary orbit, 42,164 km from Earth\'s centre (about 0.14 light-seconds), via NOAA SWPC; events NOAA SWPC and NASA DONKI.',
    });
}

/* --- Flare record: the largest flare of each day, 30 days ------------------------------- */

const flareTip = [
    ['What', 'The largest flare of each UTC day for the last 30 days, as a bar on the same log scale as the X-ray chart, coloured by '
        + 'class. Days with an M-class or X-class flare carry the class above the bar. A day with no bar has no data.'],
    ['Where from', 'NOAA GOES-18 (geostationary orbit, about 0.14 light-seconds from Earth), from NOAA SWPC\'s edited flare events of the primary '
        + 'GOES satellite only (the list gives each flare twice, once per satellite). Updated about hourly; a flare in progress counts when it is listed.'],
    ['Units', 'Peak flux in W/m&sup2; in the 0.1 to 0.8 nm band; class = decade (A 1e-8, B 1e-7, C 1e-6, M 1e-5, X 1e-4) with a multiplier.'],
    ['About', 'Near solar maximum a day without a C-class flare is unusual; M and X days are the ones that black out radio and can '
        + 'come with a coronal mass ejection.'],
    ['Cite', 'NOAA Space Weather Prediction Center, services.swpc.noaa.gov.'],
];

async function loadFlareRecord() {
    const { points, q } = await weatherSeries('derivedFlareMaxDay', '30d', true);
    return { points, q, loadedAt: Date.now() };
}

function flareRecordHtml(data, width) {
    const dayEnd = Math.ceil(data.loadedAt / WEATHER_DAY_MS) * WEATHER_DAY_MS;
    const t0 = dayEnd - 30 * WEATHER_DAY_MS;
    const classes = new Map(data.points.map((p, i) => [p[0], (data.q[i] || '').split(' ')[0] || xrayClassOf(p[1])]));
    const panels = [{ height: 190,
        left: { min: 1e-8, max: 1e-3, log: true, label: 'DAILY MAXIMUM (W/M2)', classes: XRAY_CLASSES, format: exponentText },
        marks: [{ type: 'bars', axis: 'left', points: data.points, barMs: WEATHER_DAY_MS, offsetMs: WEATHER_DAY_MS / 2,
            colorOf: (v) => WEATHER_FLARE_COLOURS[xrayClassOf(v)[0]],
            label: (p) => (/^[MX]/.test(classes.get(p[0]) || '') ? classes.get(p[0]) : ''),
            tipOf: (p) => `${weatherDateText(p[0])}: ${classes.get(p[0])} (${p[1].toExponential(2)} W/m2)` }] }];
    const svg = timePanelsSvg({ width, t0, t1: dayEnd, panels, title: 'Largest flare of each day, 30 days' });
    return chartTipFrameHtml({ title: 'FLARE RECORD', tag: '30 DAYS', tip: flareTip, svg,
        legend: [{ label: 'A-B', color: WEATHER_FLARE_COLOURS.B }, { label: 'C', color: WEATHER_FLARE_COLOURS.C },
            { label: 'M', color: WEATHER_FLARE_COLOURS.M }, { label: 'X', color: WEATHER_FLARE_COLOURS.X }],
        credit: 'NOAA GOES-18 (about 0.14 light-seconds from Earth), via NOAA SWPC.' });
}

/* --- The Sun's long view: F10.7 with the sunspot number, 13 months ----------------------- */

const LONG_DAYS = 400;

const longViewTip = [
    ['What', 'Thirteen months of the Sun\'s slow pulse. <b>Left axis:</b> the daily solar radio flux F10.7 (dots) with its 81-day mean '
        + '(line). <b>Right axis:</b> the daily sunspot number (thin line). Both measure how active the Sun is, so they share the chart; '
        + 'the two axes are fixed, not stretched to match. A hollow dot is a day whose radio flux was taken during a flare radio burst: '
        + '"flare radio burst during the 20 UT measurement; not representative of the day". The last stretch of the 81-day mean is dashed '
        + 'because it includes the SWPC 45-day forecast.'],
    ['Where from', 'F10.7: measured on the ground at the Dominion Radio Astrophysical Observatory, Penticton, Canada (no spacecraft), daily '
        + 'values processed by GFZ Potsdam (the single 20 UT reading). Sunspot number: daily estimates from GFZ Potsdam. The 81-day mean is '
        + 'computed by this site. Updated daily.'],
    ['Units and formula', 'F10.7 in solar flux units (1 sfu = 1e-22 W/m&sup2;/Hz) at 10.7 cm. The 81-day mean is a <i>centred</i> mean of the '
        + 'cleaned observed flux (burst days replaced by the median of the day\'s three readings, else the mean of the neighbours): '
        + 'F10.7A = mean of the 81 days from 40 days before to 40 days after, shown only where at least 75 of the 81 days exist. It is the '
        + 'F10.7A that atmosphere models (NRLMSISE-00, JB2008) use for satellite drag. A burst day is one more than 15% above the mean of the days either side.'],
    ['About', 'F10.7 follows the Sun\'s ultraviolet output, which heats the upper atmosphere and sets satellite drag, more steadily than sunspots do. '
        + 'The sunspot number is the older, longer record. The 27-day wobble is the Sun\'s rotation.'],
    ['Cite', 'GFZ German Research Centre for Geosciences, Potsdam (Matzka et al. 2021, Space Weather 19, e2020SW002641); Dominion Radio '
        + 'Astrophysical Observatory, Penticton (NRC Canada); NOAA SWPC (forecast).'],
];

async function loadLongView() {
    const [obs, mean, ssn] = await Promise.all([weatherSeries('gfzF107Obs', `${LONG_DAYS}d`, true),
        weatherSeries('derivedF107A81', `${LONG_DAYS}d`, true), weatherSeries('gfzSunspotNumber', `${LONG_DAYS}d`, true)]);
    return { obs, mean, ssn, loadedAt: Date.now() };
}

// Dots for daily F10.7, hollow where the quality says burst.
function f107Dots(obs, from) {
    return obs.points.map((p, i) => {
        const burst = (obs.q[i] || '').startsWith('burst');
        return [p[0], p[1], { hollow: burst, tip: burst ? `${weatherDateText(p[0])}: F10.7 ${p[1]} sfu. Flare radio burst during the 20 UT measurement; not representative of the day.` : undefined }];
    }).filter((p) => p[0] >= from);
}

function longViewHtml(data, width) {
    const lastMean = data.mean.points.length ? data.mean.points[data.mean.points.length - 1][0] : data.loadedAt;
    const t1 = Math.max(data.loadedAt, lastMean);
    const t0 = t1 - LONG_DAYS * WEATHER_DAY_MS;
    const fluxMax = weatherLadder(Math.max(weatherMaxOf(data.obs.points), weatherMaxOf(data.mean.points)), [220, 260, 300, 340]);
    const ssnMax = weatherLadder(weatherMaxOf(data.ssn.points), [200, 300, 400]);
    const forecastIndex = data.mean.q.findIndex((q) => /forecast/.test(q || ''));
    const forecastFrom = forecastIndex >= 0 ? data.mean.points[forecastIndex][0] : undefined;
    const fluxColour = 'var(--tng-sand)';
    const ssnColour = 'var(--tng-periwinkle)';
    const panels = [{ height: 230,
        left: { min: 60, max: fluxMax, ticks: Array.from({ length: (fluxMax - 60) / 40 + 1 }, (_, i) => 60 + i * 40), label: 'F10.7 (SFU), 81-DAY MEAN LINE', color: fluxColour },
        right: { min: 0, max: ssnMax, ticks: Array.from({ length: ssnMax / 100 + 1 }, (_, i) => i * 100), label: 'SUNSPOT NUMBER', color: ssnColour },
        marks: [{ type: 'line', axis: 'right', points: data.ssn.points, color: ssnColour, width: 1, gapMs: 2.5 * WEATHER_DAY_MS },
                { type: 'dots', axis: 'left', points: f107Dots(data.obs, t0), color: fluxColour, r: 2.2 },
                { type: 'line', axis: 'left', points: data.mean.points, color: 'var(--tng-amber)', width: 2.5, gapMs: 2.5 * WEATHER_DAY_MS,
                  forecastFrom, noHatch: true }] }];
    const at = (points, ms, digits) => {
        const i = chartNearest(points.map((p) => p[0]), ms);
        return i >= 0 && Math.abs(points[i][0] - ms) < 0.6 * WEATHER_DAY_MS && points[i][1] !== null ? points[i][1].toFixed(digits) : 'no data';
    };
    const hover = (ms) => `${weatherDateText(ms)}\nF10.7 ${at(data.obs.points, ms, 1)} sfu, 81-day mean ${at(data.mean.points, ms, 1)} sfu\nSunspot number ${at(data.ssn.points, ms, 0)}`;
    const svg = timePanelsSvg({ width, t0, t1, panels, hoverText: hover, title: 'F10.7 and sunspot number, 13 months' });
    return chartTipFrameHtml({ title: 'THE SUN\'S LONG VIEW', tag: '13 MONTHS', tip: longViewTip, svg,
        legend: [{ label: 'F10.7, daily', color: fluxColour }, { label: '81-day mean (dashed: includes forecast)', color: 'var(--tng-amber)' },
            { label: 'Sunspot number (right axis)', color: ssnColour }],
        credit: 'F10.7: Dominion Radio Astrophysical Observatory, Penticton, via GFZ Potsdam and NOAA SWPC. Sunspot number: GFZ Potsdam. A ground record: no spacecraft.' });
}

/* --- The solar cycle: monthly sunspot number, 25 years ------------------------------------ */

const CYCLE_YEARS = 25;
// Minima that start the cycles in view (SILSO's smoothed minima): the cycle number and the month.
const SOLAR_CYCLE_STARTS = [{ n: 24, ms: Date.UTC(2008, 11, 1), text: 'Dec 2008' }, { n: 25, ms: Date.UTC(2019, 11, 1), text: 'Dec 2019' }];

const solarCycleTip = [
    ['What', 'Twenty-five years of the monthly mean sunspot number, a little over two solar cycles. The current cycle (25) is drawn in amber, '
        + 'earlier ones in blue; dashed markers show where cycles 24 and 25 began. A hollow dot is a provisional month; the dashed hollow dot '
        + 'is an estimate for the month in progress, from daily values.'],
    ['Where from', 'WDC-SILSO, Royal Observatory of Belgium, Brussels (the international sunspot number, version 2), monthly mean total sunspot number; '
        + 'the newest months are provisional until SILSO finalises them, about a quarter later. The estimate for the month in progress is the mean of '
        + 'GFZ Potsdam\'s daily values so far this month. A ground record: no spacecraft. Updated monthly.'],
    ['Units', 'Sunspot number: a weighted count of spots and groups (R = k (10 g + s)). A month with no data has no point.'],
    ['About', 'The Sun\'s activity rises and falls about every 11 years. Cycle 25 peaked higher than forecast, around 2024; the Sun is now on the declining side, '
        + 'which is when the largest storms often still come.'],
    ['Cite', 'SILSO World Data Center, Royal Observatory of Belgium, Brussels (CC BY-NC 4.0); GFZ Potsdam (daily estimate).'],
];

async function loadSolarCycle() {
    const [monthly, daily] = await Promise.all([weatherSeries('silsoMonthlyMean', '25y', true), weatherSeries('gfzSunspotNumber', `${LONG_DAYS}d`, true)]);
    return { monthly, daily: daily.points, loadedAt: Date.now() };
}

function solarCycleHtml(data, width) {
    const t1 = data.loadedAt;
    const t0 = t1 - CYCLE_YEARS * 365.25 * WEATHER_DAY_MS;
    const current = SOLAR_CYCLE_STARTS[SOLAR_CYCLE_STARTS.length - 1].ms;
    const provisional = data.monthly.points.filter((p, i) => /prov/.test(data.monthly.q[i] || ''));
    // the month in progress, from GFZ's daily values so far
    const monthStart = Date.UTC(new Date(t1).getUTCFullYear(), new Date(t1).getUTCMonth(), 1);
    const sofar = data.daily.filter((p) => p[0] >= monthStart && p[1] !== null);
    const estimate = sofar.length >= 3 && !data.monthly.points.some((p) => p[0] === monthStart)
        ? [monthStart, sofar.reduce((sum, p) => sum + p[1], 0) / sofar.length] : null;
    const max = weatherLadder(weatherMaxOf(data.monthly.points), [200, 300]);
    const colour = 'var(--tng-periwinkle)';
    const now = 'var(--tng-amber)';
    const marks = [{ type: 'line', axis: 'left', points: data.monthly.points.filter((p) => p[0] <= current), color: colour, width: 1.5, gapMs: 40 * WEATHER_DAY_MS },
        { type: 'line', axis: 'left', points: data.monthly.points.filter((p) => p[0] >= current), color: now, width: 2, gapMs: 40 * WEATHER_DAY_MS },
        { type: 'dots', axis: 'left', points: provisional.map((p) => [p[0], p[1], { hollow: true, tip: `${weatherDateText(p[0])}: provisional monthly mean ${p[1]}` }]), color: now, r: 3.5 }];
    if (estimate) {
        marks.push({ type: 'dots', axis: 'left', color: now, r: 3.5,
            points: [[estimate[0], estimate[1], { hollow: true, tip: `${weatherDateText(t1)}: estimate for the month in progress, ${estimate[1].toFixed(0)} (mean of ${sofar.length} daily values, GFZ Potsdam)` }]] });
    }
    const panels = [{ height: 230, left: { min: 0, max, ticks: Array.from({ length: max / 50 + 1 }, (_, i) => i * 50), label: 'MONTHLY SUNSPOT NUMBER' }, marks }];
    const events = SOLAR_CYCLE_STARTS.map((c) => ({ t: c.ms, color: 'var(--tng-sand)', label: `Cycle ${c.n} begins (${c.text}, SILSO smoothed minimum)` }));
    const at = (ms) => {
        const i = chartNearest(data.monthly.points.map((p) => p[0]), ms);
        return i >= 0 && Math.abs(data.monthly.points[i][0] - ms) < 20 * WEATHER_DAY_MS ? `${data.monthly.points[i][1]}${/prov/.test(data.monthly.q[i] || '') ? ' (provisional)' : ''}` : 'no data';
    };
    const hover = (ms) => `${CHART_MONTHS[new Date(ms).getUTCMonth()]} ${new Date(ms).getUTCFullYear()}: monthly mean ${at(ms)}`;
    const svg = timePanelsSvg({ width, t0, t1, panels, events, hoverText: hover, title: 'Monthly sunspot number, 25 years' });
    return chartTipFrameHtml({ title: 'THE SOLAR CYCLE', tag: '25 YEARS', tip: solarCycleTip, svg,
        legend: [{ label: 'Earlier cycles', color: colour }, { label: 'Cycle 25', color: now }],
        credit: 'WDC-SILSO, Royal Observatory of Belgium, Brussels. A ground record: no spacecraft.' });
}

/* --- K6: CMEs on the way ------------------------------------------------------------------------ */

const CME_BACK_DAYS = 7;
const CME_FORWARD_DAYS = 3;
const CME_ARRIVAL_ERROR_MS = 10 * 3600000;   // typical error of an arrival-time forecast, about 10 hours
const CME_TYPES = { S: 'slow (under 500 km/s)', C: 'common (500 to 1,000 km/s)', O: 'occasional (1,000 to 2,000 km/s)', R: 'rare (2,000 to 3,000 km/s)', ER: 'extremely rare (over 3,000 km/s)' };

const cmeTip = [
    ['What', 'A timeline of the coronal mass ejections (CMEs) that matter for Earth: seven days back and three forward. Each dot is a CME at the moment '
        + 'it left the Sun, placed by its speed (vertical axis) and sized by its angular width; red = predicted to reach Earth, blue = not. For those with a '
        + 'predicted arrival a dashed line runs to the forecast arrival time (hollow ring), with a pale bar for the typical error of about 10 hours. A solid vertical '
        + 'line is a shock that has <i>actually</i> been seen at Earth. The strip below marks high-speed solar-wind streams seen at L1 (dots), and, hollow, where a '
        + 'stream seen earlier from the STEREO-A spacecraft may return (about 22 days after, give or take 3 days). The hatched region is the future.'],
    ['Where from', 'NASA\'s Community Coordinated Modeling Center DONKI database: CME analyses from the coronagraphs on SOHO (at the Sun-Earth '
        + 'Lagrange point L1, about 1.5 million km sunward of Earth, about 5 light-seconds) and STEREO-A (a spacecraft orbiting the Sun ahead of Earth, up to about '
        + '500 light-seconds away), and arrival forecasts from the WSA-ENLIL model. Shocks and streams are those logged as seen by SOLAR-1, ACE, IMAP, DSCOVR or WIND at L1. '
        + 'This site collects DONKI about hourly. Shown: CMEs with an ENLIL arrival forecast or a speed of 1,000 km/s or more.'],
    ['Reading it', 'Speed is the CME\'s leading-edge speed near the Sun; it slows or speeds up on the way as it meets the solar wind, so arrival times '
        + 'are only good to about 10 hours (mean absolute error of real-time ENLIL runs, Wold et al. 2018). A big dot is a wide CME. The wording of the count under the chart '
        + 'covers the rest. A CME that misses Earth can still be a threat to spacecraft elsewhere.'],
    ['About', 'A CME is a cloud of magnetised plasma. It takes one to four days to cross the 150 million km to Earth, much longer than light or flare particles, '
        + 'and what it does on arrival depends on its magnetic field direction, which cannot be seen until it reaches L1.'],
    ['Cite', 'NASA CCMC DONKI, kauai.ccmc.gsfc.nasa.gov/DONKI; Wold, A. M., et al. (2018), J. Space Weather Space Clim. 8, A17 (arrival-time errors).'],
];

async function loadCmeTimeline() {
    const [cmes, shocks, streams, recurrence, others] = await Promise.all([weatherEvents('cmeShown', CME_BACK_DAYS + 1), weatherEvents('ipsEarth', CME_BACK_DAYS + 1),
        weatherEvents('hssL1', CME_BACK_DAYS + 1), weatherEvents('hssRecurrence', 30), weatherSeries('derivedCmeOtherPerDay', '7d')]);
    return { cmes, shocks, streams, recurrence, others: others.points, loadedAt: Date.now() };
}

function cmeTimelineHtml(data, width, options = {}) {
    const now = data.loadedAt;
    const t0 = now - CME_BACK_DAYS * WEATHER_DAY_MS;
    const t1 = now + CME_FORWARD_DAYS * WEATHER_DAY_MS;
    const hit = 'var(--tng-salmon)';
    const miss = 'var(--tng-periwinkle)';
    const dots = [];
    const spans = [];
    const rings = [];
    (options.earthOnly ? data.cmes.filter((c) => c.record.earthBound) : data.cmes).forEach((c) => {
        const r = c.record;
        const launch = Date.parse(r.startUtc);
        if (Number.isNaN(launch) || launch < t0 - 5 * WEATHER_DAY_MS) {
            return;
        }
        const colour = r.earthBound ? hit : miss;
        const arrival = r.predictedArrival ? Date.parse(r.predictedArrival) : NaN;
        const text = `CME launched ${chartTimeText(launch)}\nSpeed ${r.speed} km/s, type ${r.type} (${CME_TYPES[r.type] || 'unknown'})\nHalf-angle ${r.halfAngle} degrees\n`
            + (Number.isNaN(arrival) ? 'No Earth arrival predicted' : `Predicted Earth arrival ${chartTimeText(arrival)} (typical error about 10 hours)`);
        if (launch >= t0) {
            dots.push([launch, Math.min(r.speed, 2500), { r: 3 + Math.min(r.halfAngle || 0, 90) / 9, color: colour, tip: text }]);
        }
        if (!Number.isNaN(arrival)) {
            spans.push({ from: launch, to: arrival, v: Math.min(r.speed, 2500), color: colour, width: 1.5, dash: '4 4', opacity: 0.7 });
            spans.push({ from: arrival - CME_ARRIVAL_ERROR_MS, to: arrival + CME_ARRIVAL_ERROR_MS, v: Math.min(r.speed, 2500), color: colour, width: 7, opacity: 0.4, tip: text });
            rings.push([arrival, Math.min(r.speed, 2500), { r: 4, color: colour, hollow: true, tip: text }]);
        }
    });
    const shocks = data.shocks.map((s) => ({ t: Date.parse(s.record.eventTime), color: hit,
        label: `Interplanetary shock observed at Earth (L1) ${chartTimeText(Date.parse(s.record.eventTime))}: ${(s.record.instruments || []).map((i) => i.displayName).join(', ')}` }));
    const streamDots = data.streams.map((s) => [Date.parse(s.record.eventTime), 0.5, { r: 5, color: 'var(--tng-sand)',
        tip: `High-speed stream seen at L1 ${chartTimeText(Date.parse(s.record.eventTime))}: ${(s.record.instruments || []).map((i) => i.displayName).join(', ')}` }]);
    const returns = data.recurrence.filter((s) => Date.parse(s.record.expectedUtc) >= t0 - 3 * WEATHER_DAY_MS && Date.parse(s.record.expectedUtc) <= t1 + 3 * WEATHER_DAY_MS);
    const returnSpans = returns.map((s) => {
        const e = Date.parse(s.record.expectedUtc);
        return { from: e - 3 * WEATHER_DAY_MS, to: e + 3 * WEATHER_DAY_MS, v: 0.5, color: 'var(--tng-lavender)', width: 8, opacity: 0.35,
            tip: `A stream seen by STEREO-A on ${chartTimeText(Date.parse(s.record.seenUtc))} may return about ${chartTimeText(e)} (give or take 3 days), if its coronal hole persists` };
    });
    const panels = [
        { height: 210, left: { min: 0, max: 2500, ticks: [0, 500, 1000, 1500, 2000, 2500], label: 'CME SPEED (KM/S)' },
          marks: [{ type: 'spans', axis: 'left', items: spans }, { type: 'dots', axis: 'left', points: dots.concat(rings), color: miss }] },
        { height: 46, left: { min: 0, max: 1, ticks: [], label: 'HIGH-SPEED STREAMS' },
          marks: [{ type: 'spans', axis: 'left', items: returnSpans }, { type: 'dots', axis: 'left', points: streamDots, color: 'var(--tng-sand)' }] },
    ];
    const events = shocks.concat([{ t: now, color: 'var(--space-white)', label: `Now, ${chartTimeText(now)}` }]);
    const svg = timePanelsSvg({ width, t0, t1, panels, events, forecastFrom: now, title: 'CMEs, seven days back and three forward' });
    const otherCount = data.others.reduce((sum, p) => sum + (p[1] || 0), 0);
    const notShown = data.others.length ? `Not shown: ${otherCount} other CMEs in the last 7 days (slower, and not predicted to reach Earth).` : '';
    const empty = data.cmes.length ? '' : ' No CME with an Earth arrival forecast, or faster than 1,000 km/s, in this period.';
    return chartTipFrameHtml({ title: options.title || 'CMES ON THE WAY', tag: '10 DAYS', tip: cmeTip, svg,
        legend: [{ label: 'CME predicted to reach Earth', color: hit }, { label: 'CME not predicted to', color: miss }, { label: 'Shock seen at Earth', color: hit },
            { label: 'High-speed stream at L1', color: 'var(--tng-sand)' }, { label: 'May return (STEREO-A)', color: 'var(--tng-lavender)' }],
        credit: `NASA CCMC DONKI: coronagraph analyses from SOHO at L1 (about 5 light-seconds from Earth) and STEREO-A; WSA-ENLIL arrival forecasts. ${notShown}${empty}${options.credit || ''}` });
}

/* --- K5: the outlook, 45 days ---------------------------------------------------------------------- */

const outlookTip = [
    ['What', 'Where the Sun\'s radio flux and the geomagnetic activity are expected to go, over the next 45 days, on one UTC time axis with the last 30 days '
        + 'for reference. <b>Top:</b> F10.7, observed (dots; hollow = flare radio burst) and the forecast (dashed line from the last observation). '
        + '<b>Bottom:</b> the daily Ap index, observed (blue bars) and forecast (violet bars). The hatched region is forecast. The two are stacked, not overlaid, '
        + 'because F10.7 is a measure of the Sun and Ap of Earth\'s magnetic field.'],
    ['Where from', 'NOAA SWPC\'s 45-day forecast (issued daily; F10.7 and Ap), which is largely a persistence of the Sun\'s 27-day rotation pattern '
        + 'and has little skill beyond about two weeks. Observations: F10.7 from the Dominion Radio Astrophysical Observatory, Penticton, and Ap from the global network of '
        + 'ground magnetometers, both via GFZ Potsdam. No spacecraft. Collected about daily.'],
    ['Units', 'F10.7 in solar flux units (1 sfu = 1e-22 W/m&sup2;/Hz). Ap: the daily planetary index, in index units; times 2 nT it is about the disturbance at '
        + '50 degrees geomagnetic latitude. Rough guide: Ap under 15 is quiet, over 30 is active to stormy; a G1 storm (Kp 5) is about Ap 40 for the day.'],
    ['Limits', 'A forecast, not a measurement: recurrent coronal holes and active regions that come round again are anticipated; a new eruption is not. '
        + 'Beyond a week, treat the bars as a climatology with a 27-day echo.'],
    ['Cite', 'NOAA Space Weather Prediction Center, services.swpc.noaa.gov (45-day Ap and F10.7 forecast); GFZ Potsdam, Matzka et al. 2021, Space Weather 19, e2020SW002641.'],
];

async function loadOutlook() {
    const [obs, fcF107, fcAp, ap] = await Promise.all([weatherSeries('gfzF107Obs', `${LONG_DAYS}d`, true), weatherSeries('swpcForecastF107', '3d'),
        weatherSeries('swpcForecastAp', '3d'), weatherSeries('gfzAp', '30d')]);
    return { obs, fcF107: fcF107.points, fcAp: fcAp.points, ap: ap.points, loadedAt: Date.now() };
}

function outlookHtml(data, width, options = {}) {
    const lastForecast = Math.max(data.fcF107.length ? data.fcF107[data.fcF107.length - 1][0] : 0, data.fcAp.length ? data.fcAp[data.fcAp.length - 1][0] : 0, data.loadedAt);
    const t1 = lastForecast + WEATHER_DAY_MS;
    const t0 = data.loadedAt - 30 * WEATHER_DAY_MS;
    const cut = data.fcF107.length ? data.fcF107[0][0] : data.loadedAt;
    const observed = data.obs.points.filter((p) => p[0] >= t0 && p[1] !== null);
    const lastObs = observed.length ? observed[observed.length - 1] : null;
    const fluxMax = weatherLadder(Math.max(weatherMaxOf(data.fcF107), weatherMaxOf(observed)), [220, 260, 300, 340]);
    const apMax = weatherLadder(Math.max(weatherMaxOf(data.fcAp), weatherMaxOf(data.ap)), [40, 80, 160]);
    const fluxColour = 'var(--tng-sand)';
    const forecastPoints = (lastObs && lastObs[0] < cut ? [lastObs] : []).concat(data.fcF107);
    const panels = [
        { height: 170, left: { min: 60, max: fluxMax, ticks: Array.from({ length: (fluxMax - 60) / 40 + 1 }, (_, i) => 60 + i * 40), label: 'F10.7 (SFU)', color: fluxColour },
          marks: [{ type: 'dots', axis: 'left', points: f107Dots(data.obs, t0), color: fluxColour, r: 2.5 },
                  { type: 'line', axis: 'left', points: forecastPoints, color: fluxColour, width: 2.5, forecastFrom: cut, gapMs: 2.5 * WEATHER_DAY_MS }] },
        { height: 130, left: { min: 0, max: apMax, ticks: Array.from({ length: apMax / 20 + 1 }, (_, i) => i * 20), label: 'AP (INDEX)' },
          marks: [{ type: 'bars', axis: 'left', points: data.ap.concat(data.fcAp.filter((p) => p[0] >= cut)), barMs: WEATHER_DAY_MS, offsetMs: WEATHER_DAY_MS / 2,
              colorOf: (v, t) => (t >= cut ? 'var(--tng-violet)' : 'var(--tng-periwinkle)'),
              tipOf: (p) => `${weatherDateText(p[0])}: Ap ${p[1]}${p[0] >= cut ? ' (forecast)' : ''}` }] },
    ];
    const at = (points, ms, digits) => {
        const i = chartNearest(points.map((p) => p[0]), ms);
        return i >= 0 && Math.abs(points[i][0] - ms) < 0.6 * WEATHER_DAY_MS && points[i][1] !== null ? points[i][1].toFixed(digits) : 'no data';
    };
    const hover = (ms) => `${weatherDateText(ms)}${ms >= cut ? ' (forecast)' : ''}\nF10.7 ${at(ms >= cut ? data.fcF107 : observed, ms, 0)} sfu\nAp ${at(ms >= cut ? data.fcAp : data.ap, ms, 0)}`;
    const svg = timePanelsSvg({ width, t0, t1, panels, hoverText: hover, forecastFrom: cut, title: 'Outlook: F10.7 and Ap, 45 days' });
    return chartTipFrameHtml({ title: options.title || 'THE OUTLOOK', tag: '45 DAYS', tip: outlookTip, svg,
        legend: [{ label: 'F10.7 observed (dots), forecast (dashed)', color: fluxColour }, { label: 'Ap observed', color: 'var(--tng-periwinkle)' }, { label: 'Ap forecast', color: 'var(--tng-violet)' }],
        credit: 'NOAA SWPC 45-day forecast; observations from ground stations (Penticton for F10.7, the magnetometer network for Ap) via GFZ Potsdam. No spacecraft.' });
}

/* --- Small helpers shared by the tile-style charts ---------------------------------------------------- */

const weatherAgo = (ms, now) => {
    const minutes = Math.max(0, Math.round((now - ms) / 60000));
    return minutes < 90 ? `${minutes} min ago` : minutes < 2880 ? `${Math.round(minutes / 60)} h ago` : `${Math.round(minutes / 1440)} days ago`;
};

async function weatherNow() {
    if (!weatherFetchCache.has('now')) {
        weatherFetchCache.set('now', (async () => {
            try {
                const response = await fetch('api/weather/now');
                return response.ok ? { ...(await response.json()), loadedAt: Date.now() } : { latest: {}, loadedAt: Date.now() };
            } catch (error) {
                console.error('Error loading weather now:', error);
                return { latest: {}, loadedAt: Date.now() };
            }
        })());
    }
    return weatherFetchCache.get('now');
}

const weatherTile = (label, value, note, colour) => `<div class="weather-tile"><span class="weather-tile-label">${label}</span>`
    + `<span class="weather-tile-value" style="color:${colour || 'var(--status-data-color)'}">${value}</span><span class="weather-tile-note">${note}</span></div>`;

/* --- The last hour of the solar wind (K1 in brief): HF COMMS' RADIO OUTLOOK and AURORAE's THE NEXT HOUR ------------------------------------------ */

const l1StripTip = [
    ['What', 'The last hour of the solar wind as it passes the spacecraft upstream of Earth: speed, the north-south field Bz (warm = southward, the direction that drives storms) and the '
        + 'convection field E = v &times; Bs / 1000 (mV/m), where Bs is the southward part of Bz. A strong, sustained southward Bz in the next hour means a geomagnetic disturbance '
        + 'and, at high latitudes, degraded HF within about an hour.'],
    ['Where from', 'NOAA SOLAR-1 (formerly SWFO-L1), at the Sun-Earth Lagrange point L1, sunward of Earth, about 1.5 million km away: about 5 light-seconds. The wind itself takes 30 to 60 '
        + 'minutes to cover that distance (about 1,500,000 km divided by its speed): the warning time is the travel time of the wind, not of light. One-minute values, provisional; collected here about hourly, '
        + 'so the strip can end well before now.'],
    ['Units', 'km/s; nT (GSM, positive north); mV/m. Gaps up to 3 minutes are joined; longer ones are left as gaps. The full three-day version, with the Newell function, is under SOL DRVR.'],
    ['Cite', 'NOAA SWPC, services.swpc.noaa.gov (real-time solar wind).'],
];

async function loadL1Strip() {
    const [speed, bz] = await Promise.all([weatherSeries('l1WindSpeed', '6h', false, 3), weatherSeries('l1MagBzGSM', '6h', false, 3)]);
    return { speed: speed.points, bz: bz.points, e: l1ConvectionField(speed.points, bz.points), loadedAt: Date.now() };
}

// The three rows (speed, Bz, E) of the last hour as an SVG; the card around them is l1StripHtml, or AURORAE's THE NEXT HOUR.
function l1StripSvg(data, width) {
    const t1 = data.loadedAt;
    const t0 = t1 - 3600000;
    const speedMax = weatherLadder(weatherMaxOf(data.speed), [800, 1000, 1200]);
    const fieldMax = weatherLadder(Math.max(...data.bz.map((p) => Math.abs(p[1] || 0))), [10, 20, 30, 50, 100]);
    const eMax = weatherLadder(weatherMaxOf(data.e), [10, 20, 50]);
    const panels = [
        { height: 70, left: { min: 200, max: speedMax, ticks: [200, speedMax], label: 'SPEED (KM/S)', color: 'var(--tng-periwinkle)' },
          marks: [{ type: 'line', axis: 'left', points: data.speed, color: 'var(--tng-periwinkle)', gapMs: L1_GAP_MS, width: 1.5 }] },
        { height: 70, left: { min: -fieldMax, max: fieldMax, ticks: [-fieldMax, 0, fieldMax], label: 'BZ (NT)' },
          marks: [{ type: 'area', axis: 'left', points: data.bz, base: 0, colourNeg: 'var(--tng-salmon)', colourPos: 'var(--tng-periwinkle)', gapMs: L1_GAP_MS }] },
        { height: 70, left: { min: 0, max: eMax, ticks: [0, eMax], label: 'E (MV/M)', color: 'var(--tng-sand)' },
          marks: [{ type: 'line', axis: 'left', points: data.e, color: 'var(--tng-sand)', gapMs: L1_GAP_MS, width: 1.5 }] },
    ];
    const hover = (ms) => `${chartTimeText(ms)}\nSpeed ${nearReading(data.speed, ms, 2 * 60000, 0, 'km/s')}, Bz ${nearReading(data.bz, ms, 2 * 60000, 1, 'nT')}\nE ${nearReading(data.e, ms, 2 * 60000, 2, 'mV/m')}`;
    return timePanelsSvg({ width, t0, t1, panels, hoverText: hover, title: 'Solar wind, last hour' });
}

function l1StripHtml(data, width) {
    const svg = l1StripSvg(data, width);
    return chartTipFrameHtml({ title: 'DRIVING SIGNAL', tag: 'LAST HOUR', tip: l1StripTip, svg,
        credit: 'NOAA SOLAR-1 at L1, about 1.5 million km sunward of Earth (about 5 light-seconds); the wind takes about 30 to 60 minutes to cover that distance.' });
}
