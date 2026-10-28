/* ==========================================================================
   WEATHER TEC -- what SAT COMMS (weatherSat.js) and HF COMMS (weatherHf.js: the GNSS lamp and YOUR PATH)
   share about total electron content (TEC): fetching the stored maps and series, the colour bands of the
   maps and the grids they draw, the radio-link arithmetic (group delay, Faraday rotation, foF2 from TEC),
   and the provisional rule of the GNSS lamp.

   Data (all from tecMaps in siteWeather.db, via /api/weather/tec-*):
     tec-index    what is held; tec-code  one CODE (Bern) hourly map, observed or predicted;
     tec-latest   the newest NOAA GloTEC map (the server asks NOAA at most every 30 minutes, on demand);
     tec-at       TEC and foF2 at a place; tec-series  the same over the stored 7 days;
     tec-summary  the newest stored GloTEC map in a few numbers (for the lamp; never asks NOAA).
   Every fetch is remembered for one opening of a view (weatherCharts.js) and answers null on failure.

   Needs weatherCharts.js and weatherMap.js. Loaded by weatherPanel.js with SAT COMM and HF COMM.
   ========================================================================== */

const TEC_DELAY_K = 40.3;               // group delay (m) = 40.3 x TEC (electrons/m2) / f2 (Hz2)
const TEC_FARADAY_K = 2.36e4;           // Faraday rotation (rad) = 2.36e4 x B (tesla) x TEC / f2 (SI units, as DEFS)
const TEC_DIPOLE_EQUATOR_MICROT = 29.4;              // surface field at the magnetic equator of the dipole
const TEC_F_LAYER_KM = 350;             // height at which the field is taken
const TEC_SLAB_DEFAULT_KM = 300;        // equivalent slab thickness (TEC / NmF2) used when GloTEC gives no pair to calibrate with
const LAMP_COLOURS = { green: 'var(--green)', amber: 'var(--tng-amber)', red: 'var(--red)', grey: 'var(--tng-mauve)' };   // the lights of HF COMMS and SAT COMMS
const TEC_FRESH_MS = 6 * 3600000;       // a GloTEC summary older than this is not used for the lamp
// The GNSS lamp (provisional, indicative; Spock to confirm): see tecLamp().
const TEC_LAMP = { anomalyAmber: 0.6, anomalyRed: 1.0, icaoAmber: 125, icaoRed: 175 };

// Representative carrier frequencies (MHz) of the bands of EFFECT BY BAND.
const TEC_BANDS = [
    { band: 'VHF', mhz: 145.8, example: '2 m amateur satellites' },
    { band: 'UHF', mhz: 437, example: '70 cm amateur satellites' },
    { band: 'L', mhz: 1575.42, example: 'GPS L1' },
    { band: 'S', mhz: 2200, example: 'S-band downlinks' },
    { band: 'X', mhz: 8200, example: 'Earth-observation downlinks' },
    { band: 'Ku', mhz: 12000, example: 'Ku-band downlinks' },
    { band: 'Ka', mhz: 26000, example: 'Ka-band downlinks' },
];

/* --- fetching ------------------------------------------------------------------------------------------ */

// JSON from a URL, or null; a failure is not remembered, so the next ask tries again.
function tecFetchJson(url) {
    if (!weatherFetchCache.has(url)) {
        weatherFetchCache.set(url, (async () => {
            try {
                const response = await fetch(url);
                if (response.ok) {
                    return await response.json();
                }
            } catch (error) {
                console.error(`Error loading ${url}:`, error);
            }
            weatherFetchCache.delete(url);
            return null;
        })());
    }
    return weatherFetchCache.get(url);
}

const tecIndex = () => tecFetchJson('api/weather/tec-index');
const tecCodeRecord = (kind, day, hour) => tecFetchJson(`api/weather/tec-code?kind=${kind}&day=${day}&hour=${hour}`);
// only the three lists the map draws (TEC, anomaly, quality flag): about 40% smaller than the whole record
const tecLatestRecord = () => tecFetchJson('api/weather/tec-latest?fields=tec,anom,q');
const tecSummary = () => tecFetchJson('api/weather/tec-summary');
const tecPlaceQuery = (place) => `lat=${place.lat.toFixed(2)}&lon=${place.lon.toFixed(2)}`;
const tecAt = (place) => tecFetchJson(`api/weather/tec-at?${tecPlaceQuery(place)}`);
const tecSeriesAt = (place) => tecFetchJson(`api/weather/tec-series?${tecPlaceQuery(place)}`);

// The visitor's place (weatherPlace() in weatherEarth.js) or null.
const tecPlace = () => weatherPlace();

// Hours with a CODE map of a kind on a day: [0, 1, ...] sorted; days = { 'yyyy-mm-dd': hours } from the index.
function tecHours(index, kind, day) {
    const byHour = index && index.code && index.code[kind] && index.code[kind][day];
    return byHour ? Object.keys(byHour).map(Number).sort((a, b) => a - b) : [];
}

// Days with at least `minMaps` maps of a kind (a prediction file's closing midnight map is not a day).
function tecDaysHeld(index, kind, minMaps = 6) {
    return index && index.code && index.code[kind] ? Object.keys(index.code[kind]).sort().filter((d) => tecHours(index, kind, d).length >= minMaps) : [];
}

// The hour (UTC) whose map is nearest to a time: {day, hour, valid}.
function tecNearestHour(ms) {
    const t = Math.round(ms / 3600000) * 3600000;
    const iso = new Date(t).toISOString();
    return { day: iso.slice(0, 10), hour: new Date(t).getUTCHours(), valid: iso.slice(0, 13) + ':00:00Z' };
}

/* --- radio-link arithmetic ------------------------------------------------------------------------------ */

// One-way group delay in metres of a signal of `mhz` through `tecu` TECU.
const tecDelayM = (tecu, mhz) => TEC_DELAY_K * tecu * 1e16 / (mhz * 1e6) ** 2;

// Geomagnetic latitude (degrees) in the tilted-dipole model (weatherEarth.js).
const tecGeomagneticLat = (lat, lon) => geomagneticLat(lat, lon);

// The field component along a ray from straight overhead (microtesla), dipole model at 350 km: B_z = 2 B_eq sin(geomagnetic latitude).
// A rough figure (the real field, and a slanted ray, differ by tens of per cent); only the size matters for a Faraday estimate.
function tecAlongFieldMicroT(lat, lon) {
    const bEquator = TEC_DIPOLE_EQUATOR_MICROT * (6371 / (6371 + TEC_F_LAYER_KM)) ** 3;
    return 2 * bEquator * Math.abs(Math.sin(tecGeomagneticLat(lat, lon) * Math.PI / 180));
}

// Faraday rotation in degrees.
const tecFaradayDeg = (tecu, microT, mhz) => (TEC_FARADAY_K * microT * 1e-6 * tecu * 1e16 / (mhz * 1e6) ** 2) * 180 / Math.PI;

// foF2 (MHz) from NmF2 (in 1e10 electrons/m3, as GloTEC stores it): foF2 = 8.98 sqrt(NmF2) Hz.
const tecFoF2FromNmF2 = (nmf2e10) => 8.98 * Math.sqrt(nmf2e10 * 1e10) / 1e6;

// foF2 (MHz) inferred from TEC with an equivalent slab thickness (km): NmF2 = TEC / thickness.
const tecFoF2FromTec = (tecu, slabKm) => 8.98 * Math.sqrt(tecu * 1e16 / (slabKm * 1e3)) / 1e6;

// The slab thickness (km) that makes GloTEC's own TEC and foF2 agree, the median over the pairs held; 300 km without any.
function tecSlabKm(tecs, foF2s) {
    const thicknesses = [];
    tecs.forEach((tecu, i) => {
        const f = foF2s[i];
        if (tecu > 0 && f > 0) {
            thicknesses.push(tecu * 1e16 / ((f * 1e6 / 8.98) ** 2) / 1e3);
        }
    });
    if (!thicknesses.length) {
        return TEC_SLAB_DEFAULT_KM;
    }
    thicknesses.sort((a, b) => a - b);
    const mid = thicknesses.length >> 1;
    const median = thicknesses.length % 2 ? thicknesses[mid] : (thicknesses[mid - 1] + thicknesses[mid]) / 2;
    return Math.min(600, Math.max(150, median));
}

// What a place's TEC means for the links: from tec-at's answer (CODE preferred, else GloTEC) or null without one.
function tecHere(at, place) {
    const code = at && at.code && at.code.tec !== null && at.code.tec !== undefined ? at.code : null;
    const glotec = at && at.glotec && at.glotec.tec !== null && at.glotec.tec !== undefined ? at.glotec : null;
    const pick = code ? { source: 'CODE', validUtc: code.validUtc, tec: code.tec, kind: code.kind } : glotec ? { source: 'GloTEC', validUtc: glotec.validUtc, tec: glotec.tec, kind: 'observed' } : null;
    if (!pick || !place) {
        return null;
    }
    const microT = tecAlongFieldMicroT(place.lat, place.lon);
    return { ...pick, microT, delayL: tecDelayM(pick.tec, 1575.42), faraday145: tecFaradayDeg(pick.tec, microT, 145.8), faraday437: tecFaradayDeg(pick.tec, microT, 437) };
}

/* --- the GNSS lamp ---------------------------------------------------------------------------------------- */

// Provisional rule, indicative only. Two tests on the newest stored GloTEC map, the worse one wins:
//  (1) the anomaly: |anomaly| / (the cell's own 30-day median), the THIRD-largest among cells with a quality flag of 3 or more and a
//      median of at least 10 TECU (server: tec-summary): 0.6 or more amber, 1.0 or more red;
//  (2) ICAO's absolute GNSS thresholds [ICAO, in DEFS]: the largest TEC where it is observed: 125 TECU moderate (amber), 175 severe (red).
// A map more than 6 hours old, or none, leaves the lamp grey.
function tecLamp(summary, nowMs) {
    if (!summary || !summary.validUtc) {
        return { colour: 'grey', word: 'NO DATA', detail: 'no TEC map held' };
    }
    const age = nowMs - Date.parse(summary.validUtc);
    if (age > TEC_FRESH_MS) {
        return { colour: 'grey', word: 'STALE', detail: `latest TEC map is ${Math.round(age / 3600000)} h old` };
    }
    const fraction = summary.anomalyThirdFraction;
    const peak = summary.tecMaxObserved ? summary.tecMaxObserved.tec : null;
    const byAnomaly = fraction === null || fraction === undefined ? 0 : fraction >= TEC_LAMP.anomalyRed ? 2 : fraction >= TEC_LAMP.anomalyAmber ? 1 : 0;
    const byTec = peak === null ? 0 : peak >= TEC_LAMP.icaoRed ? 2 : peak >= TEC_LAMP.icaoAmber ? 1 : 0;
    const level = Math.max(byAnomaly, byTec);
    const detail = [fraction === null || fraction === undefined ? 'anomaly: too few well-observed cells' : `3rd-largest anomaly ${(fraction * 100).toFixed(0)}% of median`,
        peak === null ? null : `highest observed TEC ${peak.toFixed(0)} TECU`].filter(Boolean).join('; ');
    return { colour: ['green', 'amber', 'red'][level], word: ['CLEAR', 'DEGRADED', 'SEVERE'][level], detail };
}

/* --- colour bands, grids, hover -------------------------------------------------------------------------- */

// Absolute TEC, TECU (stored in tenths): one sequential run from dark to light and warm.
const TEC_ABS_LEVELS = [
    { from: 0, colour: 'var(--tng-violet)', label: '0 to 10 TECU' },
    { from: 10, colour: 'var(--tng-lavender)', label: '10 to 20' },
    { from: 20, colour: 'var(--tng-periwinkle)', label: '20 to 30' },
    { from: 30, colour: 'var(--tng-ice)', label: '30 to 40' },
    { from: 40, colour: 'var(--tng-sand)', label: '40 to 50' },
    { from: 50, colour: 'var(--tng-amber)', label: '50 to 70' },
    { from: 70, colour: 'var(--tng-salmon)', label: '70 to 100' },
    { from: 100, colour: 'var(--tng-pink)', label: '100 and over' },
];
// Anomaly, TECU: below the median cool, above warm; nothing within 2 TECU of it.
const TEC_ANOM_LEVELS = [
    { from: -Infinity, colour: 'var(--tng-violet)', label: 'below -10 TECU' },
    { from: -10, colour: 'var(--tng-lavender)', label: '-10 to -5' },
    { from: -5, colour: 'var(--tng-periwinkle)', label: '-5 to -2' },
    { from: -2, colour: null, label: 'within 2 of the median' },
    { from: 2, colour: 'var(--tng-sand)', label: '2 to 5' },
    { from: 5, colour: 'var(--tng-amber)', label: '5 to 10' },
    { from: 10, colour: 'var(--tng-salmon)', label: '10 TECU and over' },
];
const TEC_HATCH = 'url(#weather-map-hatch)';

function tecLevelColour(levels, tenths) {
    if (tenths === null || tenths === undefined) {
        return null;
    }
    let found = null;
    for (const level of levels) {
        if (tenths / 10 >= level.from) {
            found = level.colour;
        }
    }
    return found;
}
const tecAbsColour = (tenths) => tecLevelColour(TEC_ABS_LEVELS, tenths);
const tecAnomColour = (tenths) => tecLevelColour(TEC_ANOM_LEVELS, tenths);

// A CODE record as a map grid (rows from 87.5 down to -87.5 every 2.5, columns -180 to 180 every 5).
const tecCodeGrid = (record) => ({ values: record.rows, latFirst: record.latMax, latStep: record.latStep, lonMin: record.lonMin, lonStep: record.lonStep, stretchPoles: true });

// One flat GloTEC list as rows from the south (72 x 72).
function tecGlotecRows(record, field, mask) {
    const rows = [];
    for (let r = 0; r < record.nLat; r += 1) {
        const row = [];
        for (let c = 0; c < record.nLon; c += 1) {
            const i = r * record.nLon + c;
            row.push(mask && !mask(record.q[i]) ? null : record[field][i]);
        }
        rows.push(row);
    }
    return rows;
}
const tecGlotecGrid = (record, field, mask) => ({ values: tecGlotecRows(record, field, mask), latFirst: record.latMin, latStep: record.latStep, lonMin: record.lonMin, lonStep: record.lonStep, stretchPoles: true });

// The layers of a map: CODE and GloTEC absolute; GloTEC anomaly with the cells nobody observed hatched grey (Spock: there it is the model's
// response to season and F10.7, not weather).
function tecMapLayers(record, mode) {
    if (record.source === 'code') {
        return [{ ...tecCodeGrid(record), colourAt: tecAbsColour }];
    }
    if (mode === 'anomaly') {
        return [{ ...tecGlotecGrid(record, 'anom', (q) => q > 0), colourAt: tecAnomColour },
            { ...tecGlotecGrid(record, 'q'), colourAt: (q) => (q === 0 ? TEC_HATCH : null) }];
    }
    return [{ ...tecGlotecGrid(record, 'tec'), colourAt: tecAbsColour }];
}

const tecLegend = (mode) => weatherMapLegend((mode === 'anomaly' ? TEC_ANOM_LEVELS : TEC_ABS_LEVELS).filter((l) => l.colour))
    .concat(mode === 'anomaly' ? [{ color: 'var(--tng-mauve)', label: 'no observations: hatched' }] : []);

const tecPlaceText = (la, lo) => `${Math.abs(la).toFixed(0)}${la >= 0 ? 'N' : 'S'}, ${Math.abs(lo).toFixed(0)}${lo >= 0 ? 'E' : 'W'}`;
const tecSigned = (v) => `${v > 0 ? '+' : ''}${v.toFixed(1)}`;

// The text under the map for the cell under the pointer.
function tecMapHover(record, mode) {
    const grids = record.source === 'code' ? null : { tec: tecGlotecGrid(record, 'tec'), anom: tecGlotecGrid(record, 'anom'), q: tecGlotecGrid(record, 'q') };
    return (la, lo) => {
        const place = tecPlaceText(la, lo);
        if (!grids) {
            const v = weatherGridValueAt(tecCodeGrid(record), la, lo);
            return `${place}: ${v === null ? 'no value' : `TEC ${(v / 10).toFixed(1)} TECU`}`;
        }
        const tec = weatherGridValueAt(grids.tec, la, lo);
        const anom = weatherGridValueAt(grids.anom, la, lo);
        const q = weatherGridValueAt(grids.q, la, lo);
        const coverage = q === null ? '' : q === 0 ? '; coverage 0 of 5: no observations, the value is the model\'s estimate' : `; coverage ${q} of 5`;
        if (mode === 'anomaly') {
            return `${place}: ${q === 0 ? 'anomaly not shown (no observations: the model\'s response to season and F10.7, not weather)' : `anomaly ${anom === null ? 'no value' : `${tecSigned(anom / 10)} TECU from the 30-day median`}`}; TEC ${tec === null ? 'no value' : `${(tec / 10).toFixed(1)} TECU`}${coverage}`;
        }
        return `${place}: TEC ${tec === null ? 'no value' : `${(tec / 10).toFixed(1)} TECU`}${coverage}`;
    };
}

/* --- shared by SAT COMMS and HF COMMS: credit, the series of a place, the chart pieces ---------------------------------- */

const satCodeCredit = 'CODE (Center for Orbit Determination in Europe), Astronomical Institute of the University of Bern: GNSS ground receivers of the IGS network. '
    + 'Dach, R. et al. (2026), CODE rapid product series for the IGS, doi:10.48620/97772.';

// The series of tec-series as { line: [[ms, TECU]], firstPrediction: ms|null, glotec: [[ms, TECU, {tip, hollow}]] }.
function tecSeriesPoints(series) {
    const observed = series.code.observed.t.map((t, i) => [Date.parse(t), series.code.observed.tec[i]]);
    const predicted = series.code.prediction.t.map((t, i) => [Date.parse(t), series.code.prediction.tec[i]]);
    const g = series.glotec;
    const glotec = (g.t || []).map((t, i) => [Date.parse(t), g.tec[i], { r: 3.5, hollow: g.observed[i] === false,
        tip: `GloTEC ${chartTimeText(Date.parse(t))}: ${g.tec[i] === null ? 'no value' : `${g.tec[i].toFixed(1)} TECU`}${g.observed[i] === false ? ' (no observations in this cell: the model\'s estimate)' : ''}` }]);
    return { line: observed.concat(predicted), firstPrediction: predicted.length ? predicted[0][0] : null, glotec };
}

const satTecAxis = (points) => { const max = weatherLadder(weatherMaxOf(points), [30, 60, 90, 120, 150, 200]); return { min: 0, max, ticks: weatherSteps(max, 3), label: 'TEC (TECU)', color: 'var(--tng-sand)' }; };

function satJoinEvents(first, nowMs) {
    const events = [];
    if (first !== null) {
        events.push({ t: first, label: 'CODE: observed maps end here; predicted maps follow (the join of two products)', color: 'var(--tng-lavender)', hollow: true });
    }
    if (nowMs !== null) {
        events.push({ t: nowMs, label: `Now, ${chartTimeText(nowMs)}`, color: 'var(--tng-ice)' });
    }
    return events;
}
