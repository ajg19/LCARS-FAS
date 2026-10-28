/* ==========================================================================
   WEATHER DRAG -- the charts of LEO DRAG that need no Space-Track history:
   the drivers of the upper atmosphere (F10.7 and Kp) on one time axis, and
   "who is exposed", the active payloads by altitude from the catalogue
   already held for ON-ORBIT. The predictive band reuses K5 (the outlook)
   and K7 (the Kp forecast grid).

   Not here, and why: the FAS drag index and the decay-rate-against-altitude
   chart, which need the Space-Track element-set history table (gpHistory,
   not built); the pass-timing card (it belongs to GS OPS).

   Needs weatherCharts.js and weatherEarth.js; loaded by weatherPanel.js the
   first time LEO DRAG is opened.
   ========================================================================== */

const DRAG_DAYS = 90;
const VLEO_CEILING_KM = 450;          // scripts/orbitStats.py: VLEO is below 450 km

/* --- THE ATMOSPHERE BREATHES: F10.7 and Kp, 90 days ---------------------------------------------------- */

const atmosphereTip = [
    ['What', 'The two things that heat and swell the upper atmosphere, on one UTC time axis for the last 90 days. <b>Top:</b> the solar radio flux F10.7 (daily dots, hollow on days of a flare radio burst) '
        + 'and its 81-day mean (line), the measure of the Sun\'s ultraviolet output, which sets the slow, seasonal-scale density. <b>Bottom:</b> the largest Kp of each day, coloured with the NOAA G level '
        + 'where one is reached: geomagnetic storms deposit energy at high latitudes and the atmosphere swells within hours, so satellites feel more drag for a day or two. '
        + 'The two are stacked, not overlaid: one is a measure of the Sun, the other of Earth\'s magnetic field.'],
    ['Where from', 'F10.7: measured on the ground at the Dominion Radio Astrophysical Observatory, Penticton, Canada, daily values processed by GFZ Potsdam (no spacecraft). Kp: GFZ Potsdam, from '
        + 'ground magnetometers worldwide (definitive, else preliminary). The 81-day mean is computed by this site. Collected about daily and hourly.'],
    ['Formulae', 'Drag decelerates a satellite by a = &frac12; &rho; v&sup2; C<sub>D</sub> (A / m), with &rho; the air density at its altitude, v its speed (about 7.6 km/s in low orbit), C<sub>D</sub> its '
        + 'drag coefficient (about 2.2) and A / m its area-to-mass ratio. Density &rho; is what changes: atmosphere models such as NRLMSISE-00 and JB2008 take the daily F10.7, the '
        + '<i>centred</i> 81-day mean F10.7A = mean of the 81 days from 40 days before to 40 days after (shown only where at least 75 of the 81 days exist; the newest 40 days include the SWPC 45-day forecast, '
        + 'drawn dashed) and a geomagnetic index. Density at 400 km can change by a factor of several between solar minimum and maximum, and by tens of per cent in a strong storm.'],
    ['Limits', 'This chart shows the drivers, not the drag itself; the FAS drag index (how much satellites actually felt) waits for the element-set history table. Kp is a daily maximum here, so a storm at the end of a day shows on that day.'],
    ['Cite', 'GFZ German Research Centre for Geosciences, Potsdam (Matzka et al. 2021, Space Weather 19, e2020SW002641); Dominion Radio Astrophysical Observatory (NRC Canada); '
        + 'Picone et al. 2002 (NRLMSISE-00), J. Geophys. Res. 107, 1468; Bowman et al. 2008 (JB2008), AIAA 2008-6438.'],
];

async function loadAtmosphere() {
    const [obs, mean, kp] = await Promise.all([weatherSeries('gfzF107Obs', `${DRAG_DAYS}d`, true), weatherSeries('derivedF107A81', `${DRAG_DAYS}d`, true), weatherSeries('gfzKp', `${DRAG_DAYS}d`)]);
    return { obs, mean, kp: kp.points, loadedAt: Date.now() };
}

// The largest Kp of each UTC day: [[dayStartMs, kp]].
function dailyMaxKp(points) {
    const days = new Map();
    points.forEach((p) => {
        if (p[1] !== null) {
            const day = Math.floor(p[0] / WEATHER_DAY_MS) * WEATHER_DAY_MS;
            days.set(day, Math.max(days.get(day) === undefined ? -1 : days.get(day), p[1]));
        }
    });
    return [...days.entries()].sort((a, b) => a[0] - b[0]);
}

function atmosphereHtml(data, width) {
    const t1 = data.loadedAt;
    const t0 = t1 - DRAG_DAYS * WEATHER_DAY_MS;
    const fluxMax = weatherLadder(Math.max(weatherMaxOf(data.obs.points.filter((p) => p[0] >= t0)), weatherMaxOf(data.mean.points.filter((p) => p[0] >= t0))), [220, 260, 300, 340]);
    const forecastIndex = data.mean.q.findIndex((q) => /forecast/.test(q || ''));
    const forecastFrom = forecastIndex >= 0 ? data.mean.points[forecastIndex][0] : undefined;
    const fluxColour = 'var(--tng-sand)';
    const kpDays = dailyMaxKp(data.kp);
    const panels = [
        { height: 170, left: { min: 60, max: fluxMax, ticks: Array.from({ length: (fluxMax - 60) / 40 + 1 }, (_, i) => 60 + i * 40), label: 'F10.7 (SFU), 81-DAY MEAN LINE', color: fluxColour },
          marks: [{ type: 'dots', axis: 'left', points: f107Dots(data.obs, t0), color: fluxColour, r: 2.5 },
                  { type: 'line', axis: 'left', points: data.mean.points, color: 'var(--tng-amber)', width: 2.5, gapMs: 2.5 * WEATHER_DAY_MS, forecastFrom, noHatch: true }] },
        { height: 120, left: { ...KP_AXIS, label: 'DAILY MAXIMUM KP', color: 'var(--tng-periwinkle)' }, lines: [G1_LINE],
          marks: [{ type: 'bars', axis: 'left', points: kpDays, barMs: WEATHER_DAY_MS * 0.8, offsetMs: WEATHER_DAY_MS / 2, colorOf: kpBarColour,
                    tipOf: (p) => `${weatherDateText(p[0])}: highest Kp ${p[1]}${gLevelOf(p[1]) ? ` (G${gLevelOf(p[1])})` : ''}` }] },
    ];
    const at = (points, ms, digits) => {
        const i = chartNearest(points.map((p) => p[0]), ms);
        return i >= 0 && Math.abs(points[i][0] - ms) < 0.6 * WEATHER_DAY_MS && points[i][1] !== null ? points[i][1].toFixed(digits) : 'no data';
    };
    const hover = (ms) => `${weatherDateText(ms)}\nF10.7 ${at(data.obs.points, ms, 1)} sfu, 81-day mean ${at(data.mean.points, ms, 1)} sfu\nHighest Kp ${at(kpDays, ms, 2)}`;
    const svg = timePanelsSvg({ width, t0, t1, panels, hoverText: hover, title: 'F10.7 and Kp, 90 days' });
    return chartTipFrameHtml({ title: 'THE ATMOSPHERE BREATHES', tag: '90 DAYS', tip: atmosphereTip, svg,
        legend: [{ label: 'F10.7, daily', color: fluxColour }, { label: '81-day mean (dashed: includes forecast)', color: 'var(--tng-amber)' },
            { label: 'Highest Kp of the day', color: 'var(--tng-periwinkle)' }, { label: 'Kp, G1 or more', color: SCALE_COLOURS[1] }],
        credit: 'F10.7: Dominion Radio Astrophysical Observatory, Penticton, via GFZ Potsdam. Kp: GFZ Potsdam. Ground records: no spacecraft. The FAS drag index waits for the element-set history table.' });
}

/* --- WHERE SATELLITES FLY: who is exposed ---------------------------------------------------------------- */

const exposureTip = [
    ['What', 'Where the working satellites are: the number of active payloads in each 10 km band of mean altitude, from 150 to 700 km, with the SpaceX satellites stacked on top of all the others. '
        + 'The shaded part is <b>very low Earth orbit</b> (below 450 km), where drag is strongest, orbits decay fastest and a storm costs the most altitude. The big spike near 550 km is a constellation shell.'],
    ['Where from', 'The NORAD satellite catalogue (via Space-Track): orbital elements from ground radar and optical tracking, so no spacecraft is involved. Payload status from CelesTrak\'s list of active satellites, '
        + 'the launch and ownership records from Jonathan McDowell\'s GCAT. The same catalogue as ON-ORBIT, refreshed twice a day.'],
    ['Units and formula', 'Mean altitude = (perigee altitude + apogee altitude) / 2 above a spherical Earth, from the newest element set. A count of active payloads (rocket bodies and debris are not counted) per 10 km band. '
        + 'A satellite on an eccentric orbit dips lower than its mean altitude at perigee, so the mean understates its exposure.'],
    ['About', 'At 550 km the air is some ten trillion times thinner than at sea level and still enough to slowly brake a satellite; a strong storm can raise the density at 400 km several-fold within a day. '
        + 'Operators of very-low-orbit satellites accept the drag and use thrusters to stay up; a satellite that cannot re-enters.'],
    ['Cite', 'NORAD satellite catalogue (via Space-Track, space-track.org, with citation); CelesTrak (celestrak.org); McDowell, J. C., GCAT (planet4589.org/space/gcat).'],
];

async function loadExposure() {
    try {
        const response = await fetch('api/on-orbit/chart?name=exposure');
        return { rows: response.ok ? (await response.json()).rows : [], loadedAt: Date.now() };
    } catch (error) {
        console.error('Error loading the exposure histogram:', error);
        return { rows: [], loadedAt: Date.now() };
    }
}

function exposureHtml(data, width) {
    const from = 150;
    const to = 700;
    const bin = 10;
    const bins = Array.from({ length: (to - from) / bin }, (_, i) => from + i * bin);
    const count = (band, spacex) => data.rows.filter((r) => r.band === band && r.spacex === spacex).reduce((sum, r) => sum + r.n, 0);
    const totals = bins.map((b) => count(b, 0) + count(b, 1));
    const { step, max } = chartLinearAxis(Math.max(1, ...totals), 5);
    const m = { top: 16, right: 24, bottom: 36, left: 64 };
    const height = 230;
    const plotW = width - m.left - m.right;
    const plotH = height - m.top - m.bottom;
    const slot = plotW / bins.length;
    const sx = (km) => m.left + ((km - from) / (to - from)) * plotW;
    const sy = (v) => m.top + plotH - (v / max) * plotH;
    const format = (n) => n.toLocaleString('en-GB');
    let svg = `<rect class="chart-shade" x="${sx(from).toFixed(1)}" y="${m.top}" width="${(sx(VLEO_CEILING_KM) - sx(from)).toFixed(1)}" height="${plotH}" fill="var(--tng-sand)"></rect>`
        + `<text class="lcars-line-axis-title" x="${(sx(from) + 6).toFixed(1)}" y="${m.top + 13}" text-anchor="start">VLEO, BELOW ${VLEO_CEILING_KM} KM</text>`;
    for (let v = 0; v <= max + 1e-9; v += step) {
        svg += `<line class="lcars-line-grid" x1="${m.left}" x2="${m.left + plotW}" y1="${sy(v).toFixed(1)}" y2="${sy(v).toFixed(1)}"></line>`
            + `<text class="lcars-line-ytick" x="${m.left - 8}" y="${sy(v).toFixed(1)}" dy="0.35em" text-anchor="end">${format(v)}</text>`;
    }
    svg += `<line class="lcars-line-axis" x1="${m.left}" x2="${m.left + plotW}" y1="${m.top + plotH}" y2="${m.top + plotH}"></line>`;
    for (let km = from; km <= to; km += 50) {
        svg += `<line class="lcars-line-xtick-mark" x1="${sx(km).toFixed(1)}" x2="${sx(km).toFixed(1)}" y1="${m.top + plotH}" y2="${m.top + plotH + 5}"></line>`
            + `<text class="lcars-line-xtick" x="${sx(km).toFixed(1)}" y="${m.top + plotH + 20}" text-anchor="middle">${km}</text>`;
    }
    svg += `<text class="lcars-line-axis-title" x="${m.left + plotW}" y="${m.top + plotH + 32}" text-anchor="end">MEAN ALTITUDE (KM)</text>`;
    bins.forEach((b, i) => {
        const others = count(b, 0);
        const spacex = count(b, 1);
        const x = m.left + i * slot + 0.5;
        const w = Math.max(1, slot - 1);
        svg += (others ? `<rect x="${x.toFixed(1)}" y="${sy(others).toFixed(1)}" width="${w.toFixed(1)}" height="${(sy(0) - sy(others)).toFixed(1)}" fill="var(--tng-periwinkle)"></rect>` : '')
            + (spacex ? `<rect x="${x.toFixed(1)}" y="${sy(others + spacex).toFixed(1)}" width="${w.toFixed(1)}" height="${(sy(others) - sy(others + spacex)).toFixed(1)}" fill="var(--tng-amber)"></rect>` : '')
            + `<rect class="chart-hit" x="${x.toFixed(1)}" y="${m.top}" width="${w.toFixed(1)}" height="${plotH}" fill="transparent">`
            + `<title>${b} to ${b + bin} km: ${format(others + spacex)} active payloads (${format(spacex)} SpaceX, ${format(others)} others)</title></rect>`;
    });
    const body = `<div class="chart-time-body">${chartSvgHtml(width, height, 'Active payloads by altitude', [svg])}</div>`;
    return chartTipFrameHtml({ title: 'WHO IS EXPOSED', tag: 'SNAPSHOT', tip: exposureTip, svg: body,
        legend: [{ label: 'Others', color: 'var(--tng-periwinkle)' }, { label: 'SpaceX', color: 'var(--tng-amber)' }],
        credit: 'NORAD satellite catalogue (via Space-Track); CelesTrak active list; GCAT. Ground tracking: no spacecraft. The decay-rate chart waits for the element-set history table.' });
}
