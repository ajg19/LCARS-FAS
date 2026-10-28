/* ==========================================================================
   WEATHER GCR -- the charts of the GCR view (galactic cosmic rays seen by
   neutron monitors): the 30-day record at Oulu and Dome C with a tile, and
   the 25-year solar-cycle chart against the sunspot number.

   Needs weatherCharts.js (fetch helpers, tiles) and chartTime.js; loaded by
   weatherPanel.js the first time GCR is opened. Data: siteWeather.db series
   gcrOulu... and gcrDomc... (scripts/ingestionGCR.py) and silsoMonthlyMean.

   The conventions are those of spaceWeatherChartsPlan.md section 14, note 17:
   hourly rows are stamped at the START of the hour, so they are drawn as
   steps from hh:00 to hh+1:00; the series are pressure-corrected; per cent
   is 100 x (I / reference - 1); the reference of Oulu is its mean over solar
   cycles 20 to 24 (6177 cts/min), of Dome C its level in November 2019 when
   Oulu was at 6177 (1081 cts/min) -- the same numbers as
   OULU_REFERENCE_CTS_MIN and DOMC_REFERENCE_CTS_MIN in ingestionGCR.py.
   ========================================================================== */

const OULU_REFERENCE_CTS_MIN = 6177;
const DOMC_REFERENCE_CTS_MIN = 1081;
const GCR_HOUR_MS = 3600000;
const FORBUSH_POINTS = 2;            // a latest 3-hour mean this far below the 5-day high is called a possible Forbush decrease
const GCR_LADDER = [{ min: -6, max: 3, ticks: [-6, -3, 0, 3] }, { min: -10, max: 5, ticks: [-10, -5, 0, 5] }, { min: -20, max: 5, ticks: [-20, -10, 0, 5] }];

const percentOfReference = (value, reference) => 100 * (value / reference - 1);
const pointsAsPercent = (points, reference) => points.filter((p) => p[1] !== null).map((p) => [p[0], percentOfReference(p[1], reference)]);

/* --- COSMIC RAYS NOW: a tile and the 30-day record ------------------------------------------------- */

const gcrNowTip = [
    ['What', 'How many cosmic rays are reaching the ground, as seen by two neutron monitors, for the last 30 days. Cosmic rays are fast particles from outside the '
        + 'solar system; when a coronal mass ejection passes Earth its magnetic cloud sweeps some of them aside and the count dips for a day or more (a '
        + '<b>Forbush decrease</b>) before recovering over days. The solar wind is the Sun pushing them away, so a busy Sun means fewer. Vertical markers: a shock seen at Earth (salmon) '
        + 'and the start of a geomagnetic storm (sand), the usual causes of a dip.'],
    ['Where from', 'Two ground neutron monitors, so no spacecraft: <b>Oulu</b> (Finland, 65 degrees N; Sodankyla Geophysical Observatory, University of Oulu), the reference station, '
        + 'and <b>Dome C</b> (Concordia station, Antarctic plateau, 75 degrees S), a southern-hemisphere check. Hourly counts from the Oulu server, collected here about hourly. '
        + 'Dome C\'s data arrive about a day later than Oulu\'s (a delivery delay, not a time shift: the series is never shifted); the chart says "Dome C data to" its last hour. '
        + '"Now" is taken from Oulu.'],
    ['Units and formulae', 'Count rate in counts per minute, corrected for air pressure (more air overhead means fewer neutrons): I = I<sub>raw</sub> &times; exp(&beta; (P &minus; P<sub>0</sub>)), '
        + 'with &beta; of about 0.77% per millibar, applied by the station. Shown as per cent of a reference level: <b>% = 100 &times; (I / I<sub>ref</sub> &minus; 1)</b>, with '
        + 'I<sub>ref</sub> = 6,177 counts/min for Oulu (its mean over solar cycles 20 to 24, October 1964 to November 2019) and 1,081 for Dome C (its level in November 2019). Each station is '
        + 'measured against its own reference, so the lines are not offsets of one another. Hourly values are stamped at the start of the hour and drawn as steps from that hour to the next.'],
    ['Limits', 'Dome C\'s swings are about 1.7 times Oulu\'s (it sits at a lower geomagnetic cutoff). The "possible Forbush decrease" flag is this site\'s rule: the latest '
        + '3-hour mean at Oulu is at least ' + FORBUSH_POINTS + ' percentage points below the highest hourly value of the previous 5 days. It is an indicator, not a catalogue entry. Provisional data may be revised.'],
    ['About', 'Neutron monitors count the secondary neutrons made when cosmic rays hit the atmosphere. Pilots and spacecraft electronics feel the same particles directly; '
        + 'a Forbush decrease is a short respite.'],
    ['Cite', 'Oulu Cosmic Ray Station, Sodankyla Geophysical Observatory, University of Oulu, Finland (cosmicrays.oulu.fi); Dome C neutron monitor data from the same server.'],
];

async function loadCosmicRaysNow() {
    const [oulu, domc, shocks, storms] = await Promise.all([weatherSeries('gcrOuluCorrected', '30d'), weatherSeries('gcrDomcCorrected', '30d'),
        weatherEvents('ipsEarth', 31), weatherEvents('storm', 31)]);
    return { oulu: oulu.points.filter((p) => p[1] !== null), domc: domc.points.filter((p) => p[1] !== null), shocks, storms, loadedAt: Date.now() };
}

// The hourly value whose hour contains a time (values are stamped at the start of their hour).
function gcrHourAt(points, ms) {
    const p = points.find((q) => q[0] <= ms && ms < q[0] + GCR_HOUR_MS);
    return p || null;
}

// {drop, high, mean3}: the latest 3-hour mean against the highest hourly value of the 5 days before it, in per cent of the reference.
function forbushState(oulu) {
    if (oulu.length < 4) {
        return null;
    }
    const percent = pointsAsPercent(oulu, OULU_REFERENCE_CTS_MIN);
    const last = percent[percent.length - 1][0];
    const mean3 = percent.slice(-3).reduce((sum, p) => sum + p[1], 0) / 3;
    const earlier = percent.filter((p) => p[0] >= last - 5 * WEATHER_DAY_MS && p[0] < last - 2 * GCR_HOUR_MS);
    const high = earlier.length ? Math.max(...earlier.map((p) => p[1])) : mean3;
    return { drop: high - mean3, high, mean3, last };
}

function cosmicRaysNowHtml(data, width) {
    const now = data.loadedAt;
    const t1 = now;
    const t0 = now - 30 * WEATHER_DAY_MS;
    const ouluPct = pointsAsPercent(data.oulu, OULU_REFERENCE_CTS_MIN);
    const domcPct = pointsAsPercent(data.domc, DOMC_REFERENCE_CTS_MIN);
    const all = ouluPct.concat(domcPct).map((p) => p[1]);
    const ladder = GCR_LADDER.find((l) => (all.length ? Math.min(...all) >= l.min && Math.max(...all) <= l.max : true)) || GCR_LADDER[GCR_LADDER.length - 1];
    const state = forbushState(data.oulu);
    const lastOulu = data.oulu.length ? data.oulu[data.oulu.length - 1] : null;
    const lastDomc = data.domc.length ? data.domc[data.domc.length - 1] : null;
    const sign = (v) => `${v >= 0 ? '+' : ''}${v.toFixed(1)}%`;
    const tiles = '<div class="weather-tiles">'
        + weatherTile('OULU NOW (% OF REFERENCE)', lastOulu ? sign(percentOfReference(lastOulu[1], OULU_REFERENCE_CTS_MIN)) : '--',
            lastOulu ? `${lastOulu[1].toFixed(0)} counts/min, hour starting ${chartTimeText(lastOulu[0]).slice(11, 16)} UTC` : 'no data',
            state && state.drop >= FORBUSH_POINTS ? 'var(--tng-salmon)' : undefined)
        + weatherTile('FORBUSH DECREASE?', state ? (state.drop >= FORBUSH_POINTS ? 'Possible' : 'No') : '--',
            state ? `${state.drop.toFixed(1)} points below the 5-day high` : 'no data', state && state.drop >= FORBUSH_POINTS ? 'var(--tng-salmon)' : undefined)
        + weatherTile('DOME C (% OF REFERENCE)', lastDomc ? sign(percentOfReference(lastDomc[1], DOMC_REFERENCE_CTS_MIN)) : '--',
            lastDomc ? `data to ${chartTimeText(lastDomc[0]).slice(5, 16)} UTC (${weatherAgo(lastDomc[0], now)})` : 'no data')
        + '</div>';
    const events = [];
    data.shocks.forEach((s) => events.push({ t: Date.parse(s.record.eventTime), color: 'var(--tng-salmon)',
        label: `Interplanetary shock seen at Earth ${chartTimeText(Date.parse(s.record.eventTime))}` }));
    data.storms.filter((s) => s.record.level >= 1).forEach((s) => events.push({ t: Date.parse(s.startUtc), color: 'var(--tng-sand)',
        label: `Geomagnetic storm G${s.record.level} (Kp up to ${s.record.maxKp}) begins ${chartTimeText(Date.parse(s.startUtc))}` }));
    const panels = [{ height: 210,
        left: { min: ladder.min, max: ladder.max, ticks: ladder.ticks, label: '% OF EACH STATION\'S REFERENCE', format: (n) => `${n > 0 ? '+' : ''}${n}` },
        lines: [{ axis: 'left', value: 0, label: 'reference', color: 'var(--status-label-color)', dash: false }],
        marks: [{ type: 'line', axis: 'left', points: ouluPct, color: 'var(--tng-sand)', width: 1.5, step: true, stepMs: GCR_HOUR_MS, gapMs: 1.5 * GCR_HOUR_MS },
                { type: 'line', axis: 'left', points: domcPct, color: 'var(--tng-periwinkle)', width: 1.5, step: true, stepMs: GCR_HOUR_MS, gapMs: 1.5 * GCR_HOUR_MS }] }];
    const hover = (ms) => {
        const o = gcrHourAt(data.oulu, ms);
        const d = gcrHourAt(data.domc, ms);
        return `${chartTimeText(ms)}\nOulu ${o ? `${sign(percentOfReference(o[1], OULU_REFERENCE_CTS_MIN))} (${o[1].toFixed(0)} counts/min)` : 'no data'}\n`
            + `Dome C ${d ? `${sign(percentOfReference(d[1], DOMC_REFERENCE_CTS_MIN))} (${d[1].toFixed(0)} counts/min)` : 'no data'}`;
    };
    const svg = tiles + timePanelsSvg({ width, t0, t1, panels, events, hoverText: hover, title: 'Cosmic rays at Oulu and Dome C, 30 days' });
    return chartTipFrameHtml({ title: 'COSMIC RAYS NOW', tag: '30 DAYS', tip: gcrNowTip, svg,
        legend: [{ label: 'Oulu', color: 'var(--tng-sand)' }, { label: lastDomc ? `Dome C (data to ${chartTimeText(lastDomc[0]).slice(5, 16)} UTC)` : 'Dome C', color: 'var(--tng-periwinkle)' },
            { label: 'Shock seen at Earth', color: 'var(--tng-salmon)' }, { label: 'Storm begins', color: 'var(--tng-sand)' }],
        credit: 'Oulu Cosmic Ray Station, Sodankyla Geophysical Observatory, University of Oulu; Dome C neutron monitor. Ground detectors: no spacecraft.' });
}

/* --- THE SOLAR CYCLE: cosmic rays against sunspots, 25 years ------------------------------------------------ */

const gcrCycleTip = [
    ['What', 'Twenty-five years of monthly values, smoothed over 13 months: the count of cosmic rays at Oulu (on an <b>inverted</b> left axis, so up means fewer) and the sunspot number '
        + '(right axis, dashed). They are mirror images: when the Sun is active its wind and magnetic field push cosmic rays away, so the count is lowest at solar maximum and highest at '
        + 'solar minimum. Both measure the Sun\'s state, so they share the chart, each on a fixed scale; dashed markers show where cycles 24 and 25 began.'],
    ['Where from', 'Oulu neutron monitor (Finland, ground; Sodankyla Geophysical Observatory, University of Oulu), monthly means since 1964, pressure-corrected. Sunspot number: WDC-SILSO, '
        + 'Royal Observatory of Belgium, Brussels (international sunspot number v2). Updated monthly; no spacecraft.'],
    ['Units and formulae', 'Cosmic rays as <b>% = 100 &times; (I / 6,177 &minus; 1)</b>, I in counts/min and 6,177 the Oulu mean over solar cycles 20 to 24 (1964-2019). '
        + 'The 13-month smoothing is SILSO\'s: S<sub>m</sub> = (0.5 R<sub>m&minus;6</sub> + R<sub>m&minus;5</sub> + ... + R<sub>m+5</sub> + 0.5 R<sub>m+6</sub>) / 12, which needs six months '
        + 'either side, so the smoothed lines stop six months before the newest data. The thin sand line is the unsmoothed monthly cosmic-ray value. The lavender line is the Dome C monthly record from November 2019 (when its reference level was set), '
        + 'as % = 100 &times; (D / 1,081 &minus; 1); its swings are about 1.7 times Oulu\'s. A hollow ring is a Dome C month with a partial record or a correction over 12% ("heavily corrected").'],
    ['About', 'The record shows the 2008-09 minimum, when cosmic rays were at a space-age high, and the 2024 maximum of cycle 25. The lag of a few months between the Sun and the '
        + 'cosmic rays is real: the heliosphere takes time to fill.'],
    ['Cite', 'Oulu Cosmic Ray Station, University of Oulu; SILSO World Data Center, Royal Observatory of Belgium, Brussels (CC BY-NC 4.0).'],
];

// SILSO's 13-month smoothing of consecutive monthly values; null-free windows only. points: [[ms, value]].
function smooth13Months(points) {
    const index = (ms) => new Date(ms).getUTCFullYear() * 12 + new Date(ms).getUTCMonth();
    const byMonth = new Map(points.filter((p) => p[1] !== null).map((p) => [index(p[0]), p[1]]));
    const out = [];
    points.forEach((p) => {
        const m = index(p[0]);
        let sum = 0;
        for (let k = -6; k <= 6; k += 1) {
            const v = byMonth.get(m + k);
            if (v === undefined) {
                return;
            }
            sum += (Math.abs(k) === 6 ? 0.5 : 1) * v;
        }
        out.push([p[0], sum / 12]);
    });
    return out;
}

async function loadGcrCycle() {
    const [neutrons, spots, domc] = await Promise.all([weatherSeries('gcrOuluMonthlyCorrected', '25y'), weatherSeries('silsoMonthlyMean', '25y', true),
        weatherSeries('gcrDomcMonthlyCorrected', '25y', true)]);
    return { neutrons: neutrons.points, spots, domc, loadedAt: Date.now() };
}

function gcrCycleHtml(data, width) {
    const t1 = data.loadedAt;
    const t0 = t1 - 25 * 365.25 * WEATHER_DAY_MS;
    const monthly = pointsAsPercent(data.neutrons, OULU_REFERENCE_CTS_MIN);
    const smooth = smooth13Months(monthly);
    const spotsSmooth = smooth13Months(data.spots.points);
    const spotMax = weatherLadder(weatherMaxOf(spotsSmooth), [200, 300]);
    // Dome C from November 2019 on (when its reference was set); partial months and heavily corrected months are hollow
    const domcRows = data.domc.points.map((p, i) => ({ p, q: data.domc.q[i] || '' })).filter((r) => r.p[0] >= Date.UTC(2019, 10, 1) && r.p[1] !== null);
    const domcPct = domcRows.map((r) => [r.p[0], percentOfReference(r.p[1], DOMC_REFERENCE_CTS_MIN)]);
    const domcFlagged = domcRows.filter((r) => /partial|heavily|provisional/.test(r.q)).map((r) => [r.p[0], percentOfReference(r.p[1], DOMC_REFERENCE_CTS_MIN),
        { hollow: true, tip: `${CHART_MONTHS[new Date(r.p[0]).getUTCMonth()]} ${new Date(r.p[0]).getUTCFullYear()}: Dome C ${r.q}` }]);
    const panels = [{ height: 240,
        left: { min: -25, max: 15, invert: true, ticks: [-20, -10, 0, 10], label: 'COSMIC RAYS AT OULU (% VS 1964-2019 MEAN), INVERTED', color: 'var(--tng-sand)', format: (n) => `${n > 0 ? '+' : ''}${n}` },
        right: { min: 0, max: spotMax, ticks: Array.from({ length: spotMax / 50 + 1 }, (_, i) => i * 50), label: 'SUNSPOT NUMBER, 13-MONTH, DASHED', color: 'var(--tng-periwinkle)' },
        marks: [{ type: 'line', axis: 'left', points: monthly, color: 'var(--tng-sand)', width: 1, gapMs: 40 * WEATHER_DAY_MS },
                { type: 'line', axis: 'left', points: smooth, color: 'var(--tng-sand)', width: 2.5, gapMs: 40 * WEATHER_DAY_MS },
                { type: 'line', axis: 'left', points: domcPct, color: 'var(--tng-lavender)', width: 1.5, gapMs: 40 * WEATHER_DAY_MS },
                { type: 'dots', axis: 'left', points: domcFlagged, color: 'var(--tng-lavender)', r: 3.5 },
                { type: 'line', axis: 'right', points: spotsSmooth, color: 'var(--tng-periwinkle)', width: 2.5, dash: '6 4', gapMs: 40 * WEATHER_DAY_MS }] }];
    const events = SOLAR_CYCLE_STARTS.map((c) => ({ t: c.ms, color: 'var(--tng-sand)', label: `Cycle ${c.n} begins (${c.text}, SILSO smoothed minimum)` }));
    const at = (points, ms) => { const i = chartNearest(points.map((p) => p[0]), ms); return i >= 0 && Math.abs(points[i][0] - ms) < 20 * WEATHER_DAY_MS ? points[i][1] : null; };
    const hover = (ms) => {
        const m = at(monthly, ms);
        const s = at(smooth, ms);
        const r = at(spotsSmooth, ms);
        const d = at(domcPct, ms);
        const f = (v, d, u) => (v === null ? 'no data' : `${v >= 0 && u === '%' ? '+' : ''}${v.toFixed(d)}${u}`);
        return `${CHART_MONTHS[new Date(ms).getUTCMonth()]} ${new Date(ms).getUTCFullYear()}\nCosmic rays: month ${f(m, 1, '%')}, 13-month ${f(s, 1, '%')}\nSunspot number, 13-month: ${f(r, 0, '')}${d === null ? '' : `
Dome C month ${f(d, 1, '%')}`}`;
    };
    const svg = timePanelsSvg({ width, t0, t1, panels, events, hoverText: hover, title: 'Cosmic rays at Oulu against the sunspot number, 25 years' });
    return chartTipFrameHtml({ title: 'THE SOLAR CYCLE', tag: '25 YEARS', tip: gcrCycleTip, svg,
        legend: [{ label: 'Cosmic rays at Oulu (inverted), 13-month and monthly', color: 'var(--tng-sand)' }, { label: 'Dome C, monthly, from Nov 2019 (hollow: partial or heavily corrected month)', color: 'var(--tng-lavender)' },
            { label: 'Sunspot number, 13-month (right axis)', color: 'var(--tng-periwinkle)' }],
        credit: 'Oulu Cosmic Ray Station, University of Oulu; WDC-SILSO, Royal Observatory of Belgium, Brussels. Ground records: no spacecraft.' });
}
