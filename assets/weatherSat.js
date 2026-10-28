/* ==========================================================================
   WEATHER SAT -- the charts of SAT COMMS: how the ionosphere changes satellite radio links.

   NOW:         TEC NOW (a world map of total electron content: CODE from Bern by default, NOAA GloTEC by a button,
                absolute or anomaly, with the numbers for the visitor's place beside it), EFFECT BY BAND (Faraday
                rotation, group delay and scintillation for VHF to Ka at the visitor's place), TEC AT YOUR LOCATION
                (the last 24 hours, with Kp beneath).
   PREDICTIVE:  TEC FORECAST (CODE's 1-, 2- and 5-day predictions on the same map, a day button and an hour slider;
                beneath, the visitor's place for five days) and STORM RISK (a lamp from the Kp forecast).

   The map is the reusable component of weatherMap.js; the data, colours and radio arithmetic are in weatherTec.js.
   The buttons keep their state in SAT_STATE and redraw their own card (satSet).

   Needs weatherCharts.js, weatherEarth.js (Kp bars and the Kp forecast), weatherMap.js and weatherTec.js; loaded by
   weatherPanel.js the first time SAT COMM is opened.
   ========================================================================== */

const SAT_STATE = { now: { source: 'code', mode: 'absolute' }, outlook: { day: null, hour: null } };
const SAT_SLOTS = { now: 'weather-sat-map', outlook: 'weather-sat-outlook-map' };
const SAT_EXAMPLE = { tecu: 20, microT: 50 };       // the example of DEFS, for a visitor with no location
const SAT_STORM_KP = { amber: 4, red: 5 };           // forecast Kp from which the storm-risk lamp changes (provisional)

/* --- buttons -------------------------------------------------------------------------------------------- */

function satSwitchHtml(card, key, label, options, current) {
    return `<span class="weather-switch-group"><span class="weather-switch-label">${label}</span>${options.map((o) => `<button type="button" class="weather-switch${o.value === current ? ' is-on' : ''}"`
        + `${o.title ? ` title="${escapeChartText(o.title)}"` : ''} onclick="satSet('${card}', '${key}', '${o.value}')">${o.label}</button>`).join('')}</span>`;
}

// A button was pressed: change the state, then fetch what the new state needs and redraw that card only.
function satSet(card, key, value) {
    const state = SAT_STATE[card];
    state[key] = key === 'hour' ? Number(value) : value;
    if (card === 'now') {
        if (key === 'mode' && value === 'anomaly') {
            state.source = 'glotec';            // CODE has no anomaly
        }
        if (key === 'source' && value === 'code') {
            state.mode = 'absolute';
        }
    }
    return satRefresh(card);
}

async function satRefresh(card) {
    const slot = document.getElementById(SAT_SLOTS[card]);
    if (!slot) {
        return;
    }
    slot.innerHTML = '<p class="weather-status">Loading the map...</p>';
    slot.chartData = await (card === 'now' ? loadTecNow() : loadTecOutlook());
    weatherRedraw(slot);
}

/* --- TEC NOW: the map ------------------------------------------------------------------------------------- */

const tecNowTip = [
    ['What', 'A map of the <b>total electron content</b> (TEC) of the ionosphere: the number of free electrons in a column one square metre across, from the ground up through the whole ionosphere, '
        + 'in TECU (1 TECU = 10<sup>16</sup> electrons per m&sup2;). Radio waves are slowed and their polarisation twisted in proportion to the TEC, so it is the first number to look at for a satellite link. '
        + 'The shaded part of the map is night (worked out here from the time of the map); TEC is largest in the afternoon, near the magnetic equator.'],
    ['Two products', '<b>CODE</b> (the default) is made at the University of Bern from about a hundred GNSS ground stations of the IGS: vertical TEC in a thin shell at 450 km, a fit on a 2.5 by 5 degree grid, hourly. '
        + 'Its maps are issued once a day at about 08:00 UTC; the maps for the current hours are CODE\'s <b>1-day prediction</b>, not an observation (the tag says which). '
        + '<b>GloTEC</b> (the button) is NOAA SWPC\'s data-assimilation model on its own 2.5 by 5 degree grid, made every 10 minutes from the same kind of ground receivers and from COSMIC-2 radio occultation; '
        + 'this site stores one every 3 hours and asks NOAA for a newer one at most every 30 minutes. The two are defined differently (GloTEC may include electrons above the ionosphere, in the plasmasphere), '
        + 'so a systematic difference between them is expected: on 24 Oct 2026 CODE\'s peak was 95.7 TECU and GloTEC\'s 68.0.'],
    ['Anomaly (GloTEC only)', 'Deviation of the total electron content from its 30-day median. In full (partly inferred, about 95% sure): how far TEC is above (+) or below (&minus;) its median at this time of day over the previous 30 days, in TECU. '
        + 'The key: cool colours below the median, warm above, nothing within 2 TECU. <b>Hatched grey</b> where GloTEC had no observations (coverage 0 of 5; about 72% of the map on 24 Oct): there the anomaly is the model\'s response to season and solar flux, not observed weather, so it is not coloured.'],
    ['Coverage', 'The hover text gives GloTEC\'s <b>quality flag</b>, 0 to 5: how many GNSS measurements constrain that cell (0 = none, the value is the model\'s estimate; 5 = dense). It measures how much data went in, not an error.'],
    ['Where from', 'GNSS satellites (GPS, Galileo and others, in medium Earth orbit about 20,200 km up, about 0.07 light-seconds from Earth) seen from the ground; COSMIC-2 (low Earth orbit, about 550 km, 0.002 light-seconds). '
        + 'The ring marks your location, if set. Move the pointer over the map for the value at a place.'],
    ['Limits', 'Maps are smooth fits: they miss small structures (irregularities, scintillation) and are least reliable over oceans, the poles and where there are few receivers.'],
    ['Cite', satCodeCredit + ' NOAA Space Weather Prediction Center, GloTEC (spaceweather.gov/products/glotec).'],
];

// The numbers for the visitor's place, from tec-at (the tile column beside the map).
function satHereTiles(here, place) {
    if (!place) {
        return weatherTile('YOUR LOCATION', '--', 'set it with USR LOCN for your numbers');
    }
    if (!here) {
        return weatherTile('YOUR LOCATION', '--', 'no TEC held for your place');
    }
    return weatherTile('TEC HERE (TECU)', here.tec.toFixed(1), `${here.source} ${here.kind === 'prediction' ? 'predicted' : 'observed'}, ${chartTimeText(Date.parse(here.validUtc)).slice(11)}`)
        + weatherTile('L-BAND DELAY (M)', here.delayL.toFixed(2), 'GPS L1 1575.42 MHz, one way, overhead')
        + weatherTile('FARADAY 145.8 MHZ', `${Math.round(here.faraday145).toLocaleString('en-GB')}&deg;`, `overhead; ${here.microT.toFixed(0)} &micro;T field, dipole model`)
        + weatherTile('FARADAY 437 MHZ', `${Math.round(here.faraday437).toLocaleString('en-GB')}&deg;`, 'overhead, same field');
}

function satMapBlock(record, mode, width, id, place, coast, here) {
    const markers = place ? [{ lat: place.lat, lon: place.lon, label: 'YOU', color: 'var(--tng-ice)' }] : [];
    const map = weatherMapSvg({ id, width: Math.round(width * 0.7), coast, terminatorMs: Date.parse(record.validUtc), markers, hoverText: tecMapHover(record, mode),
        title: record.source === 'code' ? 'World map of total electron content, CODE' : 'World map of total electron content, GloTEC', layers: tecMapLayers(record, mode) });
    return `<div class="weather-map-side"><div>${map}</div><div class="weather-tiles weather-tiles-column">${satHereTiles(here, place)}</div></div>`;
}

async function loadTecNow() {
    const state = { ...SAT_STATE.now };
    const place = tecPlace();
    const [index, coast, at] = await Promise.all([tecIndex(), weatherCoastRings(), place ? tecAt(place) : null]);
    const now = Date.now();
    let record = null;
    let error = null;
    if (state.source === 'glotec') {
        record = await tecLatestRecord();
        error = record ? null : 'The GloTEC map could not be had just now (NOAA unreachable and none held). Try again later, or use CODE.';
    } else {
        const near = tecNearestHour(now);
        const kind = tecHours(index, 'observed', near.day).includes(near.hour) ? 'observed' : tecHours(index, 'prediction', near.day).includes(near.hour) ? 'prediction' : null;
        record = kind ? await tecCodeRecord(kind, near.day, near.hour) : null;
        error = record ? null : 'No CODE map is held for this hour yet (CODE issues at about 08:00 UTC; the site collects at 09:15).';
    }
    return { state, record, error, coast, here: tecHere(at, place), place, loadedAt: now };
}

function tecTitleTag(record) {
    const time = chartTimeText(Date.parse(record.validUtc)).slice(11);
    return record.source === 'code' ? `CODE ${record.kind === 'prediction' ? 'PREDICTED' : 'OBSERVED'} ${time}` : `GLOTEC ${time}`;
}

function tecMapCredit(record) {
    return record.source === 'code'
        ? `${satCodeCredit} Map valid ${chartTimeText(Date.parse(record.validUtc))}, issued ${chartTimeText(Date.parse(record.issuedUtc))}.`
        : `NOAA SWPC GloTEC, map valid ${chartTimeText(Date.parse(record.validUtc))}. GNSS ground receivers and COSMIC-2 (about 550 km up, 0.002 light-seconds).`;
}

function tecNowHtml(data, width) {
    const state = data.state;
    const controls = `<div class="weather-switches">${satSwitchHtml('now', 'source', 'MAP', [{ value: 'code', label: 'CODE (BERN)' },
        { value: 'glotec', label: 'NOAA GLOTEC', title: 'The newer, larger NOAA map; the server asks NOAA at most every 30 minutes' }], state.source)}`
        + `${satSwitchHtml('now', 'mode', 'SHOW', [{ value: 'absolute', label: 'ABSOLUTE' }, { value: 'anomaly', label: 'ANOMALY', title: 'Only GloTEC has an anomaly' }], state.mode)}</div>`;
    if (data.error || !data.record) {
        return chartTipFrameHtml({ title: 'TEC NOW', tag: state.source === 'code' ? 'CODE' : 'GLOTEC', tip: tecNowTip, svg: `${controls}<p class="weather-status">${data.error}</p>` });
    }
    const mode = data.record.source === 'code' ? 'absolute' : state.mode;
    return chartTipFrameHtml({ title: 'TEC NOW', tag: tecTitleTag(data.record), tip: tecNowTip, legend: tecLegend(mode),
        svg: controls + satMapBlock(data.record, mode, width, 'sat-now', data.place, data.coast, data.here), credit: tecMapCredit(data.record) });
}

/* --- EFFECT BY BAND -------------------------------------------------------------------------------------- */

const bandTip = [
    ['What', 'What the ionosphere does to a radio signal passing straight up through it, band by band, for the TEC over your location (or, with no location set, for the example of the DEFS page: 20 TECU and a 50 &micro;T field). '
        + 'Three effects: <b>Faraday rotation</b> twists the polarisation of a linearly polarised signal; <b>group delay</b> lengthens the apparent path, which matters for ranging and GNSS; <b>scintillation</b> is rapid fading and phase jitter from irregularities.'],
    ['Formulas', 'Faraday rotation &Omega; = 2.36&times;10<sup>4</sup> &middot; B<sub>&#8741;</sub> &middot; TEC / f<sup>2</sup> radians (SI units: B in tesla, TEC in electrons per m&sup2;, f in hertz). '
        + 'B<sub>&#8741;</sub> is the field along the ray: here from a tilted-dipole model at 350 km for a ray from straight overhead, B<sub>&#8741;</sub> = 2 B<sub>eq</sub> sin(geomagnetic latitude), good to a few tens of per cent; a slanted ray or the real field changes it. '
        + 'Group delay = 40.3 &middot; TEC / f<sup>2</sup> metres, one way, so a signal that also travels back doubles it. Both fall as 1/f<sup>2</sup>. '
        + 'Scintillation has no open feed: the column gives the weak-scatter rule of thumb, S4 &prop; f<sup>&minus;1.5</sup>, as a multiple of the L-band value, not a measurement.'],
    ['Where scintillation strikes', 'Strongest within about 20&deg; of the magnetic equator in the hours after sunset, and at high latitudes in storms; weak at mid-latitudes. Phase scintillation dominates at high latitudes.'],
    ['Cite', 'Davies, K. (1990), Ionospheric Radio; Kintner et al. (2007), GPS and ionospheric scintillations, Space Weather 5, S09003. TEC: ' + satCodeCredit],
];

async function loadBandTable() {
    const place = tecPlace();
    const at = place ? await tecAt(place) : null;
    return { place, here: tecHere(at, place), loadedAt: Date.now() };
}

const satDegrees = (deg) => (deg < 0.1 ? `${deg.toFixed(2)}&deg;` : deg < 10 ? `${deg.toFixed(1)}&deg;` : `${Math.round(deg).toLocaleString('en-GB')}&deg;${deg >= 360 ? ` (${(deg / 360).toFixed(1)} turns)` : ''}`);
const satMetres = (m) => (m < 0.01 ? `${(m * 1000).toFixed(1)} mm` : `${m.toFixed(2)} m`);

function bandTableHtml(data) {
    const tecu = data.here ? data.here.tec : SAT_EXAMPLE.tecu;
    const microT = data.here ? data.here.microT : SAT_EXAMPLE.microT;
    const note = data.here ? `For ${data.here.tec.toFixed(1)} TECU over your location (${data.here.source}, ${chartTimeText(Date.parse(data.here.validUtc))}) and a ${microT.toFixed(0)} &micro;T field along the ray.`
        : data.place ? 'No TEC is held for your place yet; the example below uses 20 TECU and a 50 &micro;T field (the DEFS example).'
            : 'Example: 20 TECU and a 50 &micro;T field (the DEFS example). Set your location with USR LOCN for your own numbers.';
    const rows = TEC_BANDS.map((b) => {
        const factor = (1575.42 / b.mhz) ** 1.5;
        return `<tr><td>${b.band}</td><td>${b.mhz.toLocaleString('en-GB')} MHz <span class="weather-tile-note">${b.example}</span></td><td>${satDegrees(tecFaradayDeg(tecu, microT, b.mhz))}</td>`
            + `<td>${satMetres(tecDelayM(tecu, b.mhz))}</td><td>&times;${factor >= 10 ? Math.round(factor) : Number(factor.toPrecision(2))}</td></tr>`;
    }).join('');
    const table = `<table class="weather-band-table"><thead><tr><th>BAND</th><th>FREQUENCY</th><th>FARADAY ROTATION</th><th>DELAY, ONE WAY</th><th>SCINTILLATION VS L-BAND</th></tr></thead><tbody>${rows}</tbody></table>`;
    return chartTipFrameHtml({ title: 'EFFECT BY BAND', tag: data.here ? 'YOUR LOCATION' : 'EXAMPLE', tip: bandTip, svg: `<p class="weather-status">${note}</p>${table}`,
        credit: 'Rotation and delay are calculated from TEC (CODE or GloTEC); scintillation is a rule of thumb, not a measurement. Straight overhead; low elevations are worse.' });
}

/* --- TEC AT YOUR LOCATION: the last 24 hours, Kp beneath ------------------------------------------------------ */

const tecHereTip = [
    ['What', 'TEC in the map cell nearest you over the last 24 hours, with the Kp index beneath on the same time axis (a geomagnetic storm raises or lowers TEC for hours to days). '
        + '<b>Solid</b>: CODE maps made from observations. <b>Dashed and hatched</b>: CODE\'s 1-day <b>prediction</b>, which is all that exists for the hours since its last observed map; the dashed vertical line marks the join. '
        + '<b>Dots</b>: NOAA GloTEC maps stored by this site (one every 3 hours); a hollow dot is a cell GloTEC had no observations for.'],
    ['Two products on one axis', 'Both are TEC in TECU, so one axis is honest, but the two are defined differently (CODE: vertical TEC in a thin shell at 450 km from a spherical-harmonic fit; GloTEC: a data-assimilation model that may include plasmasphere electrons), '
        + 'so a systematic offset between the lines is expected, and is not a change in the ionosphere (on 24 Oct 2026 CODE\'s peak was 95.7 TECU, GloTEC\'s 68.0).'],
    ['Where from', 'CODE (Bern) from the IGS ground network; GloTEC from NOAA SWPC; Kp from GFZ Potsdam (ground magnetometers). No spacecraft is plotted; the GNSS satellites that carry the signals are about 20,200 km up (0.07 light-seconds).'],
    ['Cite', satCodeCredit + ' NOAA SWPC GloTEC; GFZ Potsdam (Matzka et al. 2021, Space Weather 19, e2020SW002641).'],
];

async function loadTecLocation() {
    const place = tecPlace();
    if (!place) {
        return { place: null, loadedAt: Date.now() };
    }
    const [series, kp] = await Promise.all([tecSeriesAt(place), weatherSeries('gfzKp', '3d', true)]);
    return { place, series, kp, loadedAt: Date.now() };
}

function tecLocationHtml(data, width) {
    if (!data.place) {
        return satNeedLocation('TEC AT YOUR LOCATION', tecHereTip);
    }
    if (!data.series) {
        return WEATHER_NO_DATA;
    }
    const t1 = data.loadedAt;
    const t0 = t1 - 24 * 3600000;
    const s = tecSeriesPoints(data.series);
    const inWindow = (p) => p[0] >= t0 && p[0] <= t1;
    const tecPanel = { height: 170, left: satTecAxis(s.line.filter(inWindow).concat(s.glotec.filter(inWindow))),
        marks: [{ type: 'line', axis: 'left', points: s.line, color: 'var(--tng-sand)', width: 2, gapMs: 2.5 * 3600000, forecastFrom: s.firstPrediction && s.firstPrediction < t1 ? s.firstPrediction : undefined },
            { type: 'dots', axis: 'left', points: s.glotec, color: 'var(--tng-periwinkle)' }] };
    const kpPanel = { height: 90, left: { ...KP_AXIS, color: 'var(--tng-periwinkle)' }, lines: [G1_LINE],
        marks: [{ type: 'bars', axis: 'left', points: data.kp.points, barMs: KP_BLOCK_MS * 0.85, offsetMs: KP_BLOCK_MS / 2, colorOf: kpBarColour,
            tipOf: (p) => `${chartTimeText(p[0])} block: Kp ${p[1]}${gLevelOf(p[1]) ? ` (G${gLevelOf(p[1])})` : ''}` }] };
    const hover = (ms) => `${chartTimeText(ms)}\nCODE ${nearReading(s.line, ms, 70 * 60000, 1, 'TECU')}${s.firstPrediction && ms >= s.firstPrediction ? ' (predicted)' : ''}\nGloTEC ${nearReading(s.glotec, ms, 100 * 60000, 1, 'TECU')}\nKp ${kpBlockAt(data.kp.points, ms) !== null ? kpBlockAt(data.kp.points, ms) : 'no data'}`;
    const svg = timePanelsSvg({ width, t0, t1, panels: [tecPanel, kpPanel], events: satJoinEvents(s.firstPrediction && s.firstPrediction > t0 && s.firstPrediction < t1 ? s.firstPrediction : null, null),
        hoverText: hover, title: 'TEC at your location, 24 hours' });
    return chartTipFrameHtml({ title: 'TEC AT YOUR LOCATION', tag: '24 HOURS', tip: tecHereTip, svg,
        legend: [{ label: 'CODE (solid observed, dashed predicted)', color: 'var(--tng-sand)' }, { label: 'GloTEC maps', color: 'var(--tng-periwinkle)' }, { label: 'Kp', color: 'var(--tng-periwinkle)' }],
        credit: `Nearest cells: CODE ${data.series.code.cellLat !== undefined ? `${data.series.code.cellLat}, ${data.series.code.cellLon}` : 'none'}, GloTEC ${data.series.glotec.cellLat !== undefined ? `${data.series.glotec.cellLat}, ${data.series.glotec.cellLon}` : 'none'} (latitude, longitude). CODE (Bern), NOAA SWPC GloTEC, GFZ Potsdam.` });
}

/* --- TEC FORECAST: the map on a day and hour, and your place for five days ------------------------------------ */

const tecOutlookTip = [
    ['What', 'CODE\'s <b>predicted</b> TEC maps for later hours and days, on the same map and colours as TEC NOW. Choose a day with the buttons and an hour (UTC) with the slider. '
        + 'The maps are model predictions issued once a day at about 08:00 UTC from the previous days\' observed maps and the solar flux: CODE\'s 1-day prediction covers today, the 2-day prediction tomorrow, the 5-day prediction the fifth day; '
        + 'only the days this site holds are offered (the days in between are not published as maps here).'],
    ['Limits', 'A prediction cannot know a storm that has not started: when the Kp forecast is high (see STORM RISK) expect TEC to differ from the map, by tens of per cent, for hours to days. Predicted maps are smoother than observed ones.'],
    ['Where from', 'CODE (Center for Orbit Determination in Europe), Astronomical Institute of the University of Bern; models driven by IGS ground-network observations of GNSS satellites (about 20,200 km up, 0.07 light-seconds).'],
    ['Cite', satCodeCredit],
];

const tecOutlookLocationTip = [
    ['What', 'TEC in the map cell nearest you: the observed tail of the last two days joined to CODE\'s predictions for the days ahead. The prediction is <b>dashed and hatched</b>; the dashed vertical line marks where observed maps end and predicted ones begin (the join of two files of one product: no offset is expected there). '
        + 'Dots are NOAA GloTEC maps stored by this site, a different product with a systematic offset from CODE. Beneath: Kp observed (GFZ) and forecast (NOAA, hatched), because storms move TEC.'],
    ['Where from', 'CODE (Bern); NOAA SWPC GloTEC and three-day Kp forecast; GFZ Potsdam Kp. Predictions only cover the days this site holds; a gap is drawn as a gap.'],
    ['Cite', satCodeCredit + ' NOAA SWPC; GFZ Potsdam (Matzka et al. 2021).'],
];

async function loadTecOutlook() {
    const state = SAT_STATE.outlook;
    const place = tecPlace();
    const [index, coast, at] = await Promise.all([tecIndex(), weatherCoastRings(), place ? tecAt(place) : null]);
    const now = Date.now();
    const today = new Date(now).toISOString().slice(0, 10);
    const days = tecDaysHeld(index, 'prediction').filter((d) => d >= today);
    const day = days.includes(state.day) ? state.day : days.find((d) => d > today) || days[0] || null;
    let hours = day ? tecHours(index, 'prediction', day) : [];
    const wanted = state.hour === null ? new Date(now).getUTCHours() : state.hour;
    const hour = hours.length ? hours.reduce((best, h) => (Math.abs(h - wanted) < Math.abs(best - wanted) ? h : best), hours[0]) : null;
    const record = day !== null && hour !== null ? await tecCodeRecord('prediction', day, hour) : null;
    return { state: { day, hour }, days, today, hours, record, coast, place, here: tecHere(at, place), loadedAt: now,
        error: record ? null : 'No CODE prediction is held yet (CODE issues at about 08:00 UTC; the site collects at 09:15).' };
}

const tecDayLabel = (day, today) => {
    const n = Math.round((Date.parse(day) - Date.parse(today)) / 86400000);
    return n === 0 ? 'TODAY' : `+${n} DAY${n === 1 ? '' : 'S'}`;
};

function tecOutlookHtml(data, width) {
    const dayButtons = data.days.map((d) => ({ value: d, label: tecDayLabel(d, data.today), title: d }));
    const slider = data.hours.length
        ? `<span class="weather-switch-group"><span class="weather-switch-label">HOUR UTC</span><input type="range" class="weather-hour" min="${data.hours[0]}" max="${data.hours[data.hours.length - 1]}" step="1" value="${data.state.hour}" `
            + `onchange="satSet('outlook', 'hour', this.value)" aria-label="Hour of the day, UTC"><span class="weather-switch-label">${String(data.state.hour).padStart(2, '0')}:00</span></span>` : '';
    const controls = `<div class="weather-switches">${dayButtons.length ? satSwitchHtml('outlook', 'day', 'DAY', dayButtons, data.state.day) : ''}${slider}</div>`;
    if (data.error || !data.record) {
        return chartTipFrameHtml({ title: 'TEC FORECAST', tag: 'CODE PREDICTED', tip: tecOutlookTip, svg: `${controls}<p class="weather-status">${data.error}</p>` });
    }
    return chartTipFrameHtml({ title: 'TEC FORECAST', tag: `${tecTitleTag(data.record)} ISSUED ${chartTimeText(Date.parse(data.record.issuedUtc)).slice(5, 16)}`, tip: tecOutlookTip, legend: tecLegend('absolute'),
        svg: controls + satMapBlock(data.record, 'absolute', width, 'sat-outlook', data.place, data.coast, data.here),
        credit: `Model prediction, issued ${chartTimeText(Date.parse(data.record.issuedUtc))}. ${satCodeCredit}` });
}

async function loadTecOutlookLocation() {
    const place = tecPlace();
    if (!place) {
        return { place: null, loadedAt: Date.now() };
    }
    const [series, kp, kpForecast] = await Promise.all([tecSeriesAt(place), weatherSeries('gfzKp', '7d', true), weatherSeries('swpcForecast3dayKp', '3d', true)]);
    return { place, series, kp, kpForecast, loadedAt: Date.now() };
}

function tecOutlookLocationHtml(data, width) {
    if (!data.place) {
        return satNeedLocation('TEC FORECAST AT YOUR LOCATION', tecOutlookLocationTip);
    }
    if (!data.series) {
        return WEATHER_NO_DATA;
    }
    const now = data.loadedAt;
    const s = tecSeriesPoints(data.series);
    const t0 = now - 48 * 3600000;
    const last = s.line.length ? s.line[s.line.length - 1][0] : now + 24 * 3600000;
    const t1 = Math.max(now + 24 * 3600000, Math.min(last, now + 6 * 86400000));
    const inWindow = (p) => p[0] >= t0 && p[0] <= t1;
    const forecastKp = data.kpForecast.points.filter((p) => p[0] + KP_BLOCK_MS > now);
    const tecPanel = { height: 170, left: satTecAxis(s.line.filter(inWindow).concat(s.glotec.filter(inWindow))),
        marks: [{ type: 'line', axis: 'left', points: s.line, color: 'var(--tng-sand)', width: 2, gapMs: 2.5 * 3600000, forecastFrom: s.firstPrediction || undefined },
            { type: 'dots', axis: 'left', points: s.glotec, color: 'var(--tng-periwinkle)' }] };
    const bar = { type: 'bars', axis: 'left', barMs: KP_BLOCK_MS * 0.85, offsetMs: KP_BLOCK_MS / 2, colorOf: kpBarColour };
    const kpPanel = { height: 90, left: { ...KP_AXIS, color: 'var(--tng-periwinkle)' }, lines: [G1_LINE],
        marks: [{ ...bar, points: data.kp.points.filter((p) => p[0] <= now), tipOf: (p) => `${chartTimeText(p[0])} block: Kp ${p[1]} (observed)` },
            { ...bar, points: forecastKp, forecastFrom: now, tipOf: (p) => `${chartTimeText(p[0])} block: forecast Kp ${p[1]}` }] };
    const hover = (ms) => `${chartTimeText(ms)}\nCODE ${nearReading(s.line, ms, 70 * 60000, 1, 'TECU')}${s.firstPrediction && ms >= s.firstPrediction ? ' (predicted)' : ''}\nKp ${kpBlockAt(forecastKp, ms) !== null ? `${kpBlockAt(forecastKp, ms)} (forecast)` : kpBlockAt(data.kp.points, ms) !== null ? kpBlockAt(data.kp.points, ms) : 'no data'}`;
    const svg = timePanelsSvg({ width, t0, t1, panels: [tecPanel, kpPanel], events: satJoinEvents(s.firstPrediction && s.firstPrediction > t0 ? s.firstPrediction : null, now), hoverText: hover, title: 'TEC at your location, observed tail and forecast' });
    return chartTipFrameHtml({ title: 'TEC FORECAST AT YOUR LOCATION', tag: 'DAYS', tip: tecOutlookLocationTip, svg,
        legend: [{ label: 'CODE (dashed and hatched: predicted)', color: 'var(--tng-sand)' }, { label: 'GloTEC maps', color: 'var(--tng-periwinkle)' }],
        credit: `Nearest CODE cell ${data.series.code.cellLat !== undefined ? `${data.series.code.cellLat}, ${data.series.code.cellLon}` : 'none'} (latitude, longitude). CODE (Bern), NOAA SWPC, GFZ Potsdam.` });
}

/* --- STORM RISK ------------------------------------------------------------------------------------------ */

const stormRiskTip = [
    ['What', 'An indicative traffic light for whether TEC is likely to be disturbed in the next three days, read from NOAA\'s forecast of the Kp index: green if the largest forecast Kp is under ' + SAT_STORM_KP.amber
        + ', amber from ' + SAT_STORM_KP.amber + ', red from ' + SAT_STORM_KP.red + ' (a G1 storm begins at Kp 4.67). <b>Indicative, not an official advisory.</b> The thresholds are provisional.'],
    ['Why', 'Geomagnetic storms push ionospheric plasma around and heat the thermosphere: TEC can rise (a positive phase) or fall (a negative phase) by tens of per cent and become patchy for hours to days, which degrades GNSS accuracy and satellite links. '
        + 'The CODE prediction knows nothing of a storm that has not started.'],
    ['Where from', 'NOAA SWPC three-day forecast (issued about 00:30 and 12:30 UTC; ground-based and L1 observations, no single spacecraft). Collected here about hourly.'],
    ['Cite', 'NOAA Space Weather Prediction Center, services.swpc.noaa.gov, 3-day forecast.'],
];

function stormRiskHtml(data) {
    const blocks = data.kp.filter((p) => p[0] + KP_BLOCK_MS > data.loadedAt);
    if (!blocks.length) {
        return WEATHER_NO_DATA;
    }
    const top = blocks.reduce((best, p) => (p[1] > best[1] ? p : best), blocks[0]);
    const level = top[1] >= SAT_STORM_KP.red ? 'red' : top[1] >= SAT_STORM_KP.amber ? 'amber' : 'green';
    const word = { green: 'QUIET', amber: 'UNSETTLED', red: 'DISTURBED TEC LIKELY' }[level];
    const card = `<div class="weather-lamps"><div class="weather-lamp-card"><span class="weather-lamp" style="background:${LAMP_COLOURS[level]}"></span>`
        + `<span class="weather-lamp-text"><span class="weather-tile-label">NEXT THREE DAYS</span><span class="weather-lamp-word">${word}</span>`
        + `<span class="weather-tile-note">highest forecast Kp ${top[1].toFixed(1)}, block starting ${chartTimeText(top[0])}</span></span></div></div>`;
    return chartTipFrameHtml({ title: 'STORM RISK', tag: data.issued ? `ISSUED ${chartTimeText(Date.parse(data.issued)).slice(5, 16)} UTC` : 'INDICATIVE', tip: stormRiskTip, svg: card,
        credit: 'Indicative, not an official advisory. NOAA SWPC three-day forecast.' });
}
