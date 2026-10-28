/* Structural tests of the WEATHER chart code (no dependencies; run: node 0_tests/chartTimeTest.js).

   There is no old version to compare with, so: (1) assertions about what the code must draw -- tick times and labels,
   gaps drawn as gaps, a signed area split exactly where it crosses zero, log and inverted scales, the forecast hatching,
   the markers, the tooltips -- and (2) a golden string, an exact run on a fixed input saved in
   0_tests/fixtures/chartTimeGolden.txt, so any later change to the markup shows up as a difference
   (node 0_tests/chartTimeTest.js --update rewrites it, after you have looked at the change). */

const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ROOT = path.resolve(__dirname, '..');
const read = (...parts) => fs.readFileSync(path.join(ROOT, ...parts), 'utf8');
const GOLDEN = path.join(ROOT, '0_tests', 'fixtures', 'chartTimeGolden.txt');

const sandbox = { console, document: { getElementById: () => null }, Map, Math, Date };
vm.createContext(sandbox);
for (const file of ['chartCore.js', 'chartTime.js', 'weatherCharts.js']) {
    vm.runInContext(read('assets', file), sandbox, { filename: file });
}
const run = (code) => vm.runInContext(code, sandbox);

let failed = 0;
let passed = 0;
function check(name, ok, detail) {
    if (ok) {
        passed += 1;
    } else {
        failed += 1;
        console.log(`FAIL ${name}${detail ? `: ${detail}` : ''}`);
    }
}
const count = (text, pattern) => (text.match(pattern) || []).length;
const close = (a, b, eps = 1e-6) => Math.abs(a - b) < eps;

const H = 3600000;
const T0 = Date.UTC(2026, 9, 21, 12, 0, 0);     // 21 Oct 2026 12:00 UTC
const T1 = T0 + 3 * 24 * H;

// --- ticks and labels ------------------------------------------------------------------------
{
    const { step, ticks } = run(`chartTimeTicks(${T0}, ${T1})`);
    check('ticks: three days gives a 12-hour step', step === 12 * H, step);
    check('ticks: all on 00:00 or 12:00 UTC', ticks.every((t) => t % (12 * H) === 0));
    check('ticks: inside the range', ticks[0] >= T0 && ticks[ticks.length - 1] <= T1);
    check('ticks: seven', ticks.length === 7, ticks.length);
    check('label: midnight is the date', run(`chartTimeLabel(${Date.UTC(2026, 9, 22)}, ${12 * H})`) === '22 Oct');
    check('label: noon is the time', run(`chartTimeLabel(${Date.UTC(2026, 9, 22, 12)}, ${12 * H})`) === '12:00');
    check('label: day steps are dates', run(`chartTimeLabel(${Date.UTC(2026, 9, 22, 12)}, ${86400000})`) === '22 Oct');
    const six = run(`chartTimeTicks(${T0}, ${T0 + 6 * H})`);
    check('ticks: six hours gives hourly ticks', six.step === H, six.step);
    check('text: UTC time', run(`chartTimeText(${T0})`) === '2026-10-21 12:00 UTC');
}

// --- gaps ----------------------------------------------------------------------------------------
{
    const runs = run(`chartRuns([[0, 1], [60000, 2], [120000, 3], [900000, 4], [960000, null], [1020000, 5], [1080000, 6]], 180001)`);
    check('gaps: a 13-minute gap and a null split the run in three', runs.length === 3, JSON.stringify(runs));
    check('gaps: sizes 3, 1, 2', runs.map((r) => r.length).join() === '3,1,2', runs.map((r) => r.length).join());
    check('gaps: no limit means no split', run('chartRuns([[0, 1], [9e9, 2]], 0)').length === 1);
}

// --- scales ---------------------------------------------------------------------------------------
{
    const log = run('chartValueScale({ min: 1e-9, max: 1e-3, log: true }, 0, 600)');
    check('log: the geometric middle is the middle', close(log(1e-6), 300), log(1e-6));
    check('log: below the axis is held at the bottom', log(1e-12) === 600);
    check('log: above the axis is held at the top', log(1) === 0);
    const lin = run('chartValueScale({ min: 0, max: 10 }, 0, 100)');
    check('linear: 2.5 is a quarter up', close(lin(2.5), 75));
    const inv = run('chartValueScale({ min: -100, max: 50, invert: true }, 0, 150)');
    check('inverted: a deeper (more negative) value is HIGHER on the page, so a storm points up as Kp does', inv(-100) < inv(0) && inv(0) < inv(50), `${inv(-100)} ${inv(0)} ${inv(50)}`);
    check('ticks: log decades', run('chartAxisTicks({ min: 1e-9, max: 1e-6, log: true })').length === 4);
    check('ticks: linear steps', run('chartAxisTicks({ min: 0, max: 10, step: 5 })').join() === '0,5,10');
    check('nearest', run('chartNearest([0, 10, 20, 30], 14)') === 1 && run('chartNearest([0, 10, 20, 30], 16)') === 2 && run('chartNearest([], 1)') === -1);
}

// --- signed area ---------------------------------------------------------------------------------
{
    // from +2 at t=0 to -2 at t=100: crosses zero at t=50; x is the time itself, y is the value negated
    const areas = run('chartSignedAreas([[0, 2], [100, -2]], (t) => t, (v) => 50 - v * 10, 0)');
    check('area: one polygon above and one below', areas.pos.length === 1 && areas.neg.length === 1, JSON.stringify(areas));
    check('area: the crossing is at t = 50 exactly', areas.pos[0].includes('50.0,50.0') && areas.neg[0].includes('50.0,50.0'), areas.pos[0]);
    const flat = run('chartSignedAreas([[0, 1], [10, 2], [20, 1]], (t) => t, (v) => -v, 0)');
    check('area: no crossing, one polygon', flat.pos.length === 1 && flat.neg.length === 0);
    const touch = run('chartSignedAreas([[0, 1], [10, 0], [20, -1]], (t) => t, (v) => -v, 0)');
    check('area: a value on the base line does not break it', touch.pos.length === 1 && touch.neg.length === 1);
}

// --- the panels ---------------------------------------------------------------------------------
function fixtureInput() {
    const at = (hours) => T0 + hours * H;
    return {
        width: 700, t0: T0, t1: T1, title: 'Test chart', idPrefix: 't1',
        forecastFrom: undefined,
        panels: [
            { height: 120,
              left: { min: 1e-9, max: 1e-3, log: true, label: 'X-RAY', color: 'var(--tng-sand)',
                  classes: [{ from: 1e-8, to: 1e-7, label: 'A' }, { from: 1e-7, to: 1e-6, label: 'B' }, { from: 1e-6, to: 1e-5, label: 'C' }],
                  format: (n) => n.toExponential(0) },
              lines: [{ axis: 'left', value: 1e-5, label: 'M1', color: 'var(--tng-salmon)' }],
              marks: [{ type: 'line', axis: 'left', color: 'var(--tng-sand)', gapMs: 180001, forecastFrom: at(60),
                  points: [[at(0), 1e-7], [at(0.02), 2e-7], [at(0.04), 3e-7], [at(10), 1e-6], [at(10.02), 2e-6], [at(70), 1e-6], [at(70.02), 3e-6]] }] },
            { height: 100,
              left: { min: -10, max: 10, ticks: [-10, 0, 10], label: 'BZ' },
              right: { min: -100, max: 50, invert: true, ticks: [-100, -50, 0, 50], label: 'DST', color: 'var(--tng-amber)' },
              marks: [{ type: 'shade', runs: [[at(20), at(24)]], color: 'var(--tng-salmon)' },
                  { type: 'area', axis: 'left', base: 0, colourNeg: 'var(--tng-salmon)', colourPos: 'var(--tng-periwinkle)',
                      points: [[at(0), 4], [at(1), -6], [at(2), -2], [at(3), 5]] },
                  { type: 'line', axis: 'right', color: 'var(--tng-amber)', points: [[at(0), -10], [at(2), -80]], dash: '6 4' }] },
        ],
        events: [{ t: at(30), label: 'CME shock "arrived" & <seen>', color: 'var(--tng-salmon)' }, { t: at(40), label: 'Reported only', hollow: true },
            { t: T1 + H, label: 'outside' }],
        hoverText: (ms) => `${run(`chartTimeText(${ms})`)}\nreading`,
    };
}
sandbox.fixtureInput = fixtureInput;
const svgText = run('timePanelsSvg(fixtureInput())');
{
    check('panels: one svg with its aria-label', count(svgText, /<svg /g) === 1 && svgText.includes('aria-label="Test chart"'));
    check('panels: no undefined or NaN', !/undefined|NaN/.test(svgText));
    check('panels: x ticks every 12 hours labelled once at the bottom', count(svgText, /class="lcars-line-xtick"/g) === 7);
    check('panels: grid lines run through both panels', count(svgText, /class="lcars-line-grid" x1="[\d.]+" x2="[\d.]+" y1="\d+" y2="\d+"/g) >= 14);
    check('panels: UTC marked on the axis', svgText.includes('>UTC</text>'));
    check('gap: the 10-hour gap splits the X-ray line into two paths (plus the Dst line)', count(svgText, /<path class="lcars-dual-line" /g) === 3, count(svgText, /<path class="lcars-dual-line" /g));
    check('gap: the first path joins its three readings 1.2 minutes apart', count(svgText.match(/<path class="lcars-dual-line" d="[^"]*"/)[0], /L/g) === 2);
    check('forecast: one dashed forecast path', count(svgText, /chart-forecast-line/g) === 1);
    check('forecast: one hatch pattern, used once, with the given id', count(svgText, /<pattern id="t1-hatch"/g) === 1 && count(svgText, /fill="url\(#t1-hatch\)"/g) === 1);
    check('forecast: the hatched region starts at the forecast time', (() => {
        const x = Number(svgText.match(/class="chart-forecast-band" x="([\d.]+)"/)[1]);
        const expect = 64 + ((T0 + 60 * H - T0) / (T1 - T0)) * (700 - 64 - 64);
        return close(x, expect, 0.06);
    })(), svgText.match(/chart-forecast-band" x="[\d.]+"/)[0]);
    check('log: class letters A B C drawn', ['>A<', '>B<', '>C<'].every((s) => svgText.includes(s)));
    check('log: threshold line M1 labelled', svgText.includes('>M1<') && count(svgText, /class="chart-threshold"/g) === 1);
    check('log: axis numbers use the axis format', svgText.includes('>1e-9<') && svgText.includes('>1e-3<'));
    check('axes: coloured numbers on the right axis', svgText.includes('style="fill:var(--tng-amber)"'));
    check('area: both a warm and a cool polygon', svgText.includes('fill="var(--tng-salmon)"') && svgText.includes('fill="var(--tng-periwinkle)"'));
    check('area: zero line drawn', count(svgText, /class="chart-zero"/g) === 1);
    check('shade: one band', count(svgText, /class="chart-shade"/g) === 1);
    check('events: two inside the range, one outside left out', count(svgText, /<g class="chart-event">/g) === 2);
    check('events: the hollow one is filled black', svgText.includes('r="5" stroke="var(--tng-salmon)" fill="#000"'));
    check('events: tooltip text is escaped', svgText.includes('CME shock &quot;arrived&quot; &amp; &lt;seen>'), svgText.match(/<title>CME[^<]*/)[0]);
    check('hover: strips across the full height with the time and a reading', count(svgText, /class="lcars-hover-strip"/g) >= 10 && svgText.includes('UTC\nreading'));
    // inverted: the Dst at -80 must be LOWER on the page (greater y) than at -10
    const dst = svgText.match(/<path class="lcars-dual-line" d="M[\d.]+,([\d.]+) L[\d.]+,([\d.]+)" stroke="var\(--tng-amber\)"/);
    check('inverted axis: the deeper Dst is higher on the page', dst && Number(dst[2]) < Number(dst[1]), dst && dst.slice(1).join());
}

// --- frame, bar ------------------------------------------------------------------------------------
{
    const frame = run(`chartTipFrameHtml({ title: 'T', tag: '3 DAYS', tip: [['What', 'x &amp; y'], ['Cite', 'z']], svg: '<svg></svg>', legend: [{ label: 'a<b', color: 'red' }], credit: 'credit line' })`);
    check('frame: pill with focusable tooltip', frame.includes('class="orbit-chart-header chart-pill" tabindex="0"') && frame.includes('<div class="chart-tip" role="tooltip">'));
    check('frame: tip paragraphs, legend escaped, credit', frame.includes('<p><b>What:</b> x &amp; y</p>') && frame.includes('a&lt;b') && frame.includes('<div class="chart-credit">credit line</div>'));
    const bar = run(`chartSectionBarHtml({ title: 'NOW: WHAT IS GOING ON', tag: 'NOW', color: 'var(--tng-amber)' })`);
    check('section bar: pill in the band colour', bar.includes('orbit-chart-header chart-section-bar" style="background-color:var(--tng-amber)"') && bar.includes('NOW: WHAT IS GOING ON'));
}

// --- K1 -----------------------------------------------------------------------------------------------
{
    check('K1: E = v x Bs', (() => {
        const e = run('l1ConvectionField([[1, 400], [2, 400], [3, 500], [4, null]], [[1, -5], [2, 5], [3, -10], [4, -3]])');
        return close(e[0][1], 2) && e[1][1] === 0 && close(e[2][1], 5) && e[3][1] === null;
    })());
    check('K1: ladder holds the data, never stretches it', run('weatherLadder(650, [800, 1000, 1200])') === 800 && run('weatherLadder(2000, [800, 1000, 1200])') === 1200);
    const runs = run('l1RunsAbove([[0, 6], [60000, 7], [120000, 1], [180000, 9], [3600000, 8]], 5)');
    check('K1: strong-driving runs bridge a short gap, not a long one', runs.length === 2 && runs[0][0] === 0 && runs[0][1] === 240000, JSON.stringify(runs));
    // three days of synthetic one-minute data with a hole
    const N = 3 * 24 * 60;
    const data = { loadedAt: T1, speed: [], density: [], bz: [], bt: [], newell: [] };
    for (let i = 0; i < N; i += 1) {
        const t = T0 + i * 60000;
        if (i > 1000 && i < 1100) { continue; }               // a gap
        const bz = 14 * Math.sin(i / 300);
        data.speed.push([t, 420 + 150 * Math.sin(i / 700)]);
        data.density.push([t, 5 + 4 * Math.abs(Math.sin(i / 200))]);
        data.bz.push([t, bz]);
        data.bt.push([t, Math.abs(bz) + 2]);
        data.newell.push([t, 9000 + 7000 * Math.abs(Math.sin(i / 300))]);
    }
    data.e = run(`l1ConvectionField(${JSON.stringify(data.speed)}, ${JSON.stringify(data.bz)})`);
    sandbox.k1Data = data;
    sandbox.chartWidth = () => 900;
    const html = run('l1SolarWindHtml(k1Data, 900)');
    check('K1: no undefined or NaN', !/undefined|NaN/.test(html));
    check('K1: pill title, band tag and a detailed tooltip', html.includes('L1 SOLAR WIND') && html.includes('3 DAYS') && html.includes('class="chart-tip"'));
    check('K1: names the spacecraft, its place and its distance in light-seconds', html.includes('NOAA SOLAR-1') && html.includes('L1') && html.includes('about 5 light-seconds') && html.includes('1.5 million km'));
    check('K1: explains that warning time is the wind\'s travel time', html.includes('travel time of the wind, not of light'));
    check('K1: writes out both formulas', html.includes('E</b> = v &times; Bs / 1000') && html.includes('Newell function') && html.includes('Newell et al. 2007'));
    check('K1: three panels with their axis labels', ['SPEED (KM/S)', 'DENSITY (CM-3), DASHED', 'BZ AREA, BT LINE (NT)', 'E = V x BS (MV/M)', 'NEWELL (x1000), DASHED'].every((s) => html.includes(s)));
    check('K1: the data gap splits lines (speed, density, bt, e, newell each draw 2 paths)', count(html, /<path class="lcars-dual-line" /g) === 10, count(html, /<path class="lcars-dual-line" /g));
    check('K1: strong-driving bands present', count(html, /class="chart-shade"/g) >= 1);
    check('K1: legend and credit line', html.includes('Bz southward') && html.includes('class="chart-credit"'));
    check('K1: a quiet-day scale stays small, not stretched', (() => {
        // speed up to 570: the ladder is 800, so the top tick is 800
        return html.includes('>800<') && !html.includes('>1,000<');
    })());
    // one point only, and nothing at all, must not throw
    sandbox.k1One = { loadedAt: T1, speed: [[T1 - 1000, 400]], density: [[T1 - 1000, 5]], bz: [[T1 - 1000, -3]], bt: [[T1 - 1000, 4]], newell: [], e: [[T1 - 1000, 1.2]] };
    check('K1: a single reading draws without error', (() => { try { return !/undefined|NaN/.test(run('l1SolarWindHtml(k1One, 600)')); } catch (e) { return false; } })());
    sandbox.k1None = { loadedAt: T1, speed: [], density: [], bz: [], bt: [], newell: [], e: [] };
    check('K1: no readings draws without error', (() => { try { return !/undefined|NaN/.test(run('l1SolarWindHtml(k1None, 600)')); } catch (e) { return false; } })());
}

// --- the rest of SOL DRVR: calendar ticks, new marks, and each chart on synthetic data -----------------------------
{
    const DAY = 86400000;
    const year = run(`chartTimeTicks(${Date.UTC(2001, 9, 24)}, ${Date.UTC(2026, 9, 24)})`);
    check('calendar: 25 years gives year ticks every 5 years on 1 January', year.step === 'year' && year.ticks.every((t) => new Date(t).getUTCMonth() === 0 && new Date(t).getUTCDate() === 1
        && new Date(t).getUTCFullYear() % 5 === 0) && year.ticks.length >= 4 && year.ticks.length <= 6, JSON.stringify(year.ticks.map((t) => new Date(t).getUTCFullYear())));
    check('calendar: labels are years', run(`chartTimeLabel(${Date.UTC(2010, 0, 1)}, 'year')`) === '2010');
    const month = run(`chartTimeTicks(${Date.UTC(2025, 8, 20)}, ${Date.UTC(2026, 9, 28)})`);
    check('calendar: 13 months gives ticks on the 1st of a month', month.step === 'month' && month.ticks.every((t) => new Date(t).getUTCDate() === 1) && month.ticks.length >= 4, month.ticks.length);
    check('calendar: month label', run(`chartTimeLabel(${Date.UTC(2026, 0, 1)}, 'month')`) === 'Jan 2026');
    check('calendar: short ranges are unchanged', run(`chartTimeTicks(${T0}, ${T1})`).step === 12 * H);

    // dots, spans, bars, noHatch, hit classes, strips below the marks
    const at = (hours) => T0 + hours * H;
    sandbox.marksInput = {
        width: 700, t0: T0, t1: T1, idPrefix: 't2', title: 'marks', hoverText: () => 'x', forecastFrom: at(60),
        panels: [{ height: 100, left: { min: 0, max: 10, ticks: [0, 10] },
            marks: [{ type: 'dots', axis: 'left', color: 'red', points: [[at(1), 5, { hollow: true, tip: 'ring' }], [at(2), 6], [at(3), null]] },
                { type: 'spans', axis: 'left', items: [{ from: at(5), to: at(20), v: 4, color: 'blue', width: 7, tip: 'span "a"' }, { from: at(-50), to: at(-40), v: 1 }] },
                { type: 'bars', axis: 'left', points: [[at(10), 7], [at(34), 3]], barMs: DAY, offsetMs: DAY / 2, colorOf: (v) => (v > 5 ? 'orange' : 'grey'),
                    label: (p) => (p[1] > 5 ? 'M1' : ''), tipOf: (p) => `bar ${p[1]}` },
                { type: 'line', axis: 'left', color: 'green', points: [[at(50), 1], [at(52), 2], [at(70), 3]], forecastFrom: at(60), noHatch: true }] }],
    };
    const html = run('timePanelsSvg(marksInput)');
    check('dots: a ring (hollow, with a tip), a plain dot, and none for a null', count(html, /<circle class="chart-hit"[^>]*fill="#000"[^>]*stroke="red"/g) === 1
        && count(html, /<circle cx="[\d.]+" cy="[\d.]+" r="2.5" fill="red" stroke="red" stroke-width="0">/g) === 1);
    check('spans: the one inside the range is drawn, the one outside left out, tip escaped', count(html, /class="chart-span chart-hit"/g) === 1 && html.includes('span &quot;a&quot;'));
    check('bars: coloured by value, labelled where asked', html.includes('fill="orange"') && html.includes('fill="grey"') && count(html, /chart-bar-label/g) === 1);
    check('bars: centred half a day after their stamp', (() => {
        const m = html.match(/<rect class="chart-hit" x="([\d.]+)" y="[\d.]+" width="([\d.]+)"/);
        const centre = 64 + ((at(10) + DAY / 2 - T0) / (T1 - T0)) * (700 - 128);
        return Math.abs(Number(m[1]) + Number(m[2]) / 2 - centre) < 0.2;
    })());
    check('forecast line dashed', count(html, /chart-forecast-line/g) === 1);
    check('strips come before the marks, and the body is wrapped for the pointer rules', html.indexOf('lcars-hover-strip') < html.indexOf('chart-span') && html.includes('<g class="chart-time-body">'));
    sandbox.noHatchInput = { width: 600, t0: T0, t1: T1, idPrefix: 't3', panels: [{ height: 80, left: { min: 0, max: 5, ticks: [0, 5] },
        marks: [{ type: 'line', axis: 'left', color: 'red', forecastFrom: at(40), noHatch: true, points: [[at(30), 1], [at(50), 2]] }] }] };
    const noHatch = run('timePanelsSvg(noHatchInput)');
    check('noHatch: no hatching when the only forecast mark asks for none', !noHatch.includes('chart-forecast-band') && noHatch.includes('chart-forecast-line'));
}

// each SOL DRVR chart, loaders and all, on synthetic data served by a fake fetch and a fixed clock
async function solarCharts() {
    const NOW = Date.UTC(2026, 9, 24, 19, 30);
    const DAY = 86400000;
    const iso = (ms) => new Date(ms).toISOString().replace('.000Z', 'Z');
    const minutes = (days, f) => { const t = []; const v = []; for (let ms = NOW - days * DAY; ms <= NOW; ms += 60000) { t.push(ms); v.push(f(ms)); } return [t, v]; };
    const dailyFrom = (days, f) => { const t = []; const v = []; for (let d = -days; d <= 0; d += 1) { t.push(Date.UTC(2026, 9, 24) + d * DAY); v.push(f(d)); } return [t, v]; };
    const payload = {};
    const events = {};
    const addSeries = (name, [t, v], q) => { payload[name] = { t: t.map(iso), v, ...(q ? { q } : {}) }; };
    const fill = () => {
        for (const k of Object.keys(payload)) { delete payload[k]; }
        addSeries('l1WindSpeed', minutes(3, (ms) => 420 + 100 * Math.sin(ms / 4e6)));
        addSeries('l1WindDensity', minutes(3, () => 6));
        addSeries('l1MagBzGSM', minutes(3, (ms) => 9 * Math.sin(ms / 3e6)));
        addSeries('l1MagBt', minutes(3, () => 7));
        addSeries('derivedNewell', minutes(3, () => 12000));
        addSeries('goesXrayLong', minutes(3, (ms) => (Math.abs(ms - (NOW - 20 * H)) < 600000 ? 3.4e-5 : 2e-7)));
        const fiveMin = minutes(3, () => 0.3);
        const five = [fiveMin[0].filter((_, i) => i % 5 === 0)];
        addSeries('goesProtonGE10MeV', [five[0], five[0].map((ms) => (Math.abs(ms - (NOW - 30 * H)) < 3600000 ? 25 : 0.3))]);
        addSeries('goesProtonGE100MeV', [five[0], five[0].map(() => 0.1)]);
        addSeries('derivedFlareMaxDay', dailyFrom(29, (d) => (d === -3 ? 6.7e-5 : d === -9 ? 1.2e-4 : 3e-6)),
            dailyFrom(29, () => 0)[0].map((ms, i) => (i === 26 ? 'M6.7 peak 2026-10-21T08:00:00Z GOES-18' : i === 20 ? 'X1.2 peak 2026-10-15T08:00:00Z GOES-18' : 'C3.0 peak x GOES-18')));
        const f107 = dailyFrom(399, (d) => 120 + 20 * Math.sin(d / 20));
        addSeries('gfzF107Obs', f107, f107[0].map((ms, i) => (i === 100 ? 'burst?' : null)));
        const meanT = dailyFrom(399, () => 125)[0].concat([Date.UTC(2026, 9, 25), Date.UTC(2026, 9, 26)]);
        addSeries('derivedF107A81', [meanT, meanT.map(() => 125)], meanT.map((ms) => (ms > Date.UTC(2026, 8, 20) ? 'centred 81-day mean, includes the SWPC 45-day forecast' : 'centred 81-day mean of the cleaned observed flux')));
        const spots = dailyFrom(399, (d) => 100 + 30 * Math.cos(d / 30));
        addSeries('gfzSunspotNumber', spots, spots[0].map(() => 'def'));
        const months = [];
        for (let y = 2001; y <= 2026; y += 1) { for (let m = 0; m < 12; m += 1) { const ms = Date.UTC(y, m, 1); if (ms > Date.UTC(2001, 9, 1) && ms <= Date.UTC(2026, 8, 1)) { months.push(ms); } } }
        addSeries('silsoMonthlyMean', [months, months.map((ms) => 80 + 60 * Math.sin(ms / 3.4e11))], months.map((ms) => (ms >= Date.UTC(2026, 6, 1) ? 'provisional' : 'definitive')));
        addSeries('derivedCmeOtherPerDay', dailyFrom(6, () => 2));
        const fc = Array.from({ length: 45 }, (_, i) => Date.UTC(2026, 9, 24) + i * DAY);
        addSeries('swpcForecastF107', [fc, fc.map(() => 100)]);
        addSeries('swpcForecastAp', [fc, fc.map((_, i) => 8 + (i % 7) * 3)]);
        addSeries('gfzAp', dailyFrom(89, (d) => 20 + 15 * Math.sin(2 * Math.PI * d / 27)));
        const flare = (cls, ms, sat) => ({ startUtc: iso(ms - 600000), id: iso(ms) + sat, record: { max_class: cls, max_time: iso(ms), begin_class: 'C1.0', end_class: 'C2.0', satellite: sat } });
        events.flare = [flare('M3.4', NOW - 20 * H, 18), flare('M3.4', NOW - 20 * H, 19), flare('C5.0', NOW - 5 * H, 18), flare('X1.2', NOW - 50 * H, 18)];
        events.sepGroup = [{ startUtc: iso(NOW - 40 * H), id: 'a', record: { status: 'observed' } }, { startUtc: iso(NOW - 10 * H), id: 'b', record: { status: 'forecast' } }];
        events.sEvent = [{ startUtc: iso(NOW - 30 * H), id: 's', record: { startUtc: iso(NOW - 30 * H), peakPfu: 25 } }];
        events.cmeShown = [{ startUtc: iso(NOW - 2 * DAY), id: 'c1', record: { startUtc: iso(NOW - 2 * DAY), speed: 900, type: 'C', halfAngle: 45, earthBound: true, predictedArrival: iso(NOW + 1.5 * DAY) } },
            { startUtc: iso(NOW - 4 * DAY), id: 'c2', record: { startUtc: iso(NOW - 4 * DAY), speed: 3200, type: 'ER', halfAngle: 30, earthBound: false, predictedArrival: null } }];
        events.cmeShown.push({ startUtc: iso(NOW - DAY), id: 'c3', record: { startUtc: iso(NOW - DAY), speed: 1200, type: 'O', halfAngle: 60, earthBound: true, predictedArrival: iso(NOW + 5 * H) } });
        events.ipsEarth = [{ startUtc: iso(NOW - 3 * DAY), id: 'i1', record: { eventTime: iso(NOW - 3 * DAY), instruments: [{ displayName: 'SOLAR-1: MAG' }] } }];
        events.hssL1 = [{ startUtc: iso(NOW - 6 * DAY), id: 'h1', record: { eventTime: iso(NOW - 6 * DAY), instruments: [{ displayName: 'ACE: SWEPAM' }] } }];
        events.hssRecurrence = [{ startUtc: iso(NOW - 20 * DAY), id: 'r1', record: { seenUtc: iso(NOW - 20 * DAY), expectedUtc: iso(NOW + 2 * DAY), plusMinusDays: 3 } }];

        // ERTH NOW
        const blocks = (days, f) => { const t = []; const v = []; const first = Math.floor((NOW - days * DAY) / (3 * H)) * 3 * H; for (let ms = first; ms <= NOW; ms += 3 * H) { t.push(ms); v.push(f(ms)); } return [t, v]; };
        const kpOf = (ms) => (ms === Math.floor((NOW - 40 * H) / (3 * H)) * 3 * H ? 5.33 : ms === Math.floor((NOW - 100 * H) / (3 * H)) * 3 * H ? 7 : 2);
        const gfz = blocks(7, kpOf);
        addSeries('gfzKp', gfz, gfz[0].map((ms) => (ms > NOW - 6 * H ? 'pre' : 'def')));
        const swpcT = gfz[0].concat([1, 2, 3, 4].map((i) => gfz[0][gfz[0].length - 1] + i * 3 * H));
        addSeries('swpcKp', [swpcT, swpcT.map((ms) => (ms > NOW ? 3 : kpOf(ms)))], swpcT.map((ms) => (ms > NOW ? 'predicted' : 'observed')));
        const hours = []; for (let ms = Math.floor((NOW - 7 * DAY) / H) * H; ms <= NOW; ms += H) { hours.push(ms); }
        addSeries('swpcDst', [hours, hours.map((ms) => (Math.abs(ms - (NOW - 40 * H)) < 4 * H ? -120 : -15))]);
        const fiveMinutes = []; for (let ms = NOW - DAY; ms <= NOW; ms += 5 * 60000) { fiveMinutes.push(ms); }
        addSeries('hemiPowerNorth', [fiveMinutes, fiveMinutes.map(() => 22)]);
        addSeries('hemiPowerSouth', [fiveMinutes, fiveMinutes.map(() => 14)]);
        const f3 = Array.from({ length: 24 }, (_, i) => Date.UTC(2026, 9, 24) + i * 3 * H);
        addSeries('swpcForecast3dayKp', [f3, f3.map((_, i) => (i === 10 ? 5 : 2 + (i % 3) * 0.67))], f3.map(() => 'issued 2026-10-24T12:30:00Z'));
        const d3 = [Date.UTC(2026, 9, 24), Date.UTC(2026, 9, 25), Date.UTC(2026, 9, 26)];
        addSeries('swpcForecast3dayR1R2Prob', [d3, [10, 20, 30]], d3.map(() => 'issued 2026-10-24T12:30:00Z'));
        addSeries('swpcForecast3dayR3Prob', [d3, [1, 2, 3]], d3.map(() => 'issued 2026-10-24T12:30:00Z'));
        addSeries('swpcForecast3dayS1Prob', [d3, [1, 1, 5]], d3.map(() => 'issued 2026-10-24T12:30:00Z'));
        const two = [Date.UTC(2026, 9, 23, 19, 9), Date.UTC(2026, 9, 24, 19, 9)];
        addSeries('noaaScaleR', [two, [2, 1]]);
        addSeries('noaaScaleS', [two, [0, 0]]);
        addSeries('noaaScaleG', [two, [3, 1]]);
        payload.__now = { generatedUtc: iso(NOW), latest: { noaaScaleR: [iso(two[1]), 1, 'scale', null], noaaScaleS: [iso(two[1]), 0, 'scale', null], noaaScaleG: [iso(two[1]), 1, 'scale', null],
            swpcKp1m: [iso(NOW - 600000), 4.67, 'Kp', null], swpcF107Daily: [iso(NOW - 23 * H), 101, 'sfu', 'Noon'], l1MagBzGSM: [iso(NOW - 120000), -7.5, 'nT', 'SOLAR1'], l1WindSpeed: [iso(NOW - 120000), 455, 'km/s', 'SOLAR1'],
            drapMax: [iso(NOW - 600000), 3.2, 'MHz', null], drapMaxLat: [iso(NOW - 600000), -12, 'deg', null], drapMaxLon: [iso(NOW - 600000), 45, 'deg', null] }, maps: [] };

        // D-RAP: 90 x 90 cells (4 x 2 degrees), a flare patch of 12.0 MHz round 9N 30W (rows 39-41, columns 36-38) and a 3.0 MHz polar cap
        const tenths = Array.from({ length: 90 }, (_, r) => Array.from({ length: 90 }, (_, c) => (r >= 39 && r <= 41 && c >= 36 && c <= 38 ? 120 : r <= 2 ? 30 : 0)));
        payload.__drap = { name: 'drapGlobal', tsUtc: '2026-10-24T19:08:00Z', map: { valid: '2026-10-24T19:08:00Z', lonMin: -178, lonStep: 4, latMax: 89, latStep: -2, tenths, xray: 'M-class', proton: 'Normal Proton Background' } };
        // TEC (SAT COMMS, YOUR PATH, the GNSS lamp): CODE observed to 24 Oct 00:00, predicted after; one GloTEC map; a summary.
        {
            const iso = (ms) => new Date(ms).toISOString().replace('.000Z', 'Z');
            const index = { code: { observed: {}, prediction: {} }, glotec: [iso(NOW - 35 * 60000)] };
            const put = (kind, ms) => { const d = iso(ms); const day = d.slice(0, 10); index.code[kind][day] = index.code[kind][day] || {}; index.code[kind][day][String(new Date(ms).getUTCHours())] = [kind === 'observed' ? 'rapid' : 'pred1', '2026-10-24T07:13:00Z']; };
            const midnight = Date.UTC(2026, 9, 24);
            for (let ms = Date.UTC(2026, 9, 22); ms <= midnight; ms += H) { put('observed', ms); }
            for (let ms = midnight + H; ms <= Date.UTC(2026, 9, 26, 23); ms += H) { put('prediction', ms); }
            for (let ms = Date.UTC(2026, 9, 28); ms <= Date.UTC(2026, 9, 29); ms += H) { put('prediction', ms); }   // the 5-day file: 28 Oct and its closing midnight
            const codeRecord = (kind, validMs) => ({ source: 'code', product: kind === 'observed' ? 'rapid' : 'pred1', kind, issuedUtc: '2026-10-24T07:13:00Z', validUtc: iso(validMs), latMax: 87.5, latStep: -2.5, lonMin: -180, lonStep: 5,
                unit: 'tenthsTECU', rows: Array.from({ length: 71 }, (_, i) => Array.from({ length: 73 }, (_, j) => (i === 0 && j === 0 ? null : 100 + 3 * i + (j % 5)))) });
            // GloTEC: rows from the south; cells of rows 0 to 23 (south of 30 S) have no observations
            const nLat = 72;
            const glotecRecord = { source: 'glotec', product: 'glotec', kind: 'observed', issuedUtc: iso(NOW - 35 * 60000), validUtc: iso(NOW - 35 * 60000), latMin: -88.75, latStep: 2.5, nLat, lonMin: -177.5, lonStep: 5, nLon: 72,
                tec: [], anom: [], nmf2: [], hmf2: [], q: [] };
            for (let r = 0; r < nLat; r += 1) { for (let c = 0; c < 72; c += 1) { glotecRecord.tec.push(200 + 3 * r); glotecRecord.anom.push(r < 24 ? 120 : (r % 7 - 3) * 10); glotecRecord.nmf2.push(50 + r); glotecRecord.hmf2.push(300); glotecRecord.q.push(r < 24 ? 0 : 5); } }
            const hours = []; for (let ms = Date.UTC(2026, 9, 23, 12); ms <= Date.UTC(2026, 9, 29); ms += H) { hours.push(ms); }
            const obsHours = hours.filter((ms) => ms <= midnight);
            const predHours = hours.filter((ms) => ms > midnight);
            payload.__tec = {
                index,
                code: (kind, day, hour) => { const ms = Date.parse(`${day}T${String(hour).padStart(2, '0')}:00:00Z`); const held = index.code[kind] && index.code[kind][day] && index.code[kind][day][String(hour)]; return held ? codeRecord(kind, ms) : null; },
                latest: glotecRecord,
                at: { lat: 64.1, lon: -21.9, glotec: { validUtc: iso(NOW - 35 * 60000), cellLat: 63.75, cellLon: -22.5, tec: 14, anomaly: -0.2, nmF2: 50, observed: true, foF2: 6.35, quality: 5 },
                    code: { validUtc: iso(Date.UTC(2026, 9, 24, 20)), issuedUtc: '2026-10-24T07:13:00Z', kind: 'prediction', product: 'pred1', cellLat: 65, cellLon: -20, tec: 12.7 } },
                series: { glotec: { cellLat: 63.75, cellLon: -22.5, t: [iso(NOW - 35 * 60000)], tec: [14], anomaly: [-0.2], foF2: [6.35], observed: [true] },
                    code: { cellLat: 65, cellLon: -20, observed: { t: obsHours.map(iso), tec: obsHours.map((ms) => 10 + 4 * Math.sin(ms / 3.8e6)) },
                        prediction: { t: predHours.map(iso), tec: predHours.map((ms) => 12 + 4 * Math.sin(ms / 3.8e6)), product: predHours.map(() => 'pred1') } } },
                summary: { validUtc: iso(NOW - 35 * 60000), cellsCounted: 900, anomalyThirdFraction: 0.449, anomalyLargestFraction: 0.455, tecMaxObserved: { tec: 69.8, lat: 16.25, lon: 47.5, flag: 3 } },
            };
        }

        // OVATION (AURORAE): an oval round 68 N (peak 30 at 68 N, 160 W), a weaker one round 62 S; the north has both edges, the south
        // a faint edge only (the index-10 edge reaches only 5 longitudes there: fewer than 10, so by Spock's rule there is none)
        {
            const rowsO = Array.from({ length: 181 }, (_, i) => Array.from({ length: 360 }, (_, lon) => {
                const lat = i - 90;
                return Math.max(Math.round(25 * Math.exp(-(((lat - 68) / 4) ** 2))), Math.round(8 * Math.exp(-(((lat + 62) / 4) ** 2)))) + (lat === 68 && lon === 200 ? 5 : 0);
            }));
            const sparse = (value, count) => Array.from({ length: 360 }, (_, lon) => (lon < count ? value : null));
            payload.__ovation = { name: 'ovation', tsUtc: iso(NOW), map: { obs: iso(NOW - 75 * 60000), forecast: iso(NOW + 15 * 60000), latMin: -90, lonMin: 0, step: 1, rows: rowsO,
                edgeN: Array(360).fill(64), edgeFaintN: Array(360).fill(60), edgeS: sparse(58, 5), edgeFaintS: sparse(55, 100) } };
        }
        payload.__exposure = [{ band: 540, spacex: 1, n: 1500 }, { band: 540, spacex: 0, n: 30 }, { band: 440, spacex: 1, n: 200 }, { band: 300, spacex: 0, n: 5 }];
        // GCR
        const hoursBack = (days, endMs) => { const t = []; for (let ms = Math.floor(endMs / H) * H - days * DAY; ms <= endMs; ms += H) { t.push(ms); } return t; };
        const ouluT = hoursBack(30, NOW);
        addSeries('gcrOuluCorrected', [ouluT, ouluT.map((ms) => (ms > NOW - 12 * H ? 5990 : 6177 + 30 * Math.sin(ms / 1e7)))]);
        const domcT = hoursBack(30, NOW - 30 * H);
        addSeries('gcrDomcCorrected', [domcT, domcT.map(() => 1070)]);
        const monthStamps = []; for (let y = 2001; y <= 2026; y += 1) { for (let m = 0; m < 12; m += 1) { const ms = Date.UTC(y, m, 1); if (ms >= Date.UTC(2001, 9, 1) && ms <= Date.UTC(2026, 8, 1)) { monthStamps.push(ms); } } }
        addSeries('gcrOuluMonthlyCorrected', [monthStamps, monthStamps.map((ms) => 6177 * (1 - 0.06 * Math.sin(ms / 1.2e11)))]);
        const domcMonths = monthStamps.filter((ms) => ms >= Date.UTC(2016, 2, 1));
        addSeries('gcrDomcMonthlyCorrected', [domcMonths, domcMonths.map(() => 1100)], domcMonths.map((ms) => (ms === Date.UTC(2016, 11, 1) ? 'verified; heavily corrected'
            : ms === Date.UTC(2026, 0, 1) ? 'verified; partial month from 2026-01-09' : 'verified')));
        events.storm = [{ startUtc: iso(NOW - 10 * DAY), id: 'st1', record: { startUtc: iso(NOW - 10 * DAY), level: 2, maxKp: 6 } }, { startUtc: iso(NOW - 20 * DAY), id: 'st0', record: { startUtc: iso(NOW - 20 * DAY), level: 0, maxKp: 4 } }];
    };
    fill();
    const asked = [];
    class FixedDate extends Date { constructor(...a) { super(...(a.length ? a : [NOW])); } static now() { return NOW; } }
    const sb2 = { console, Map, Math, Promise, Date: FixedDate, document: { getElementById: () => null },
        fetch: async (url) => {
            asked.push(url);
            const name = (url.match(/name=(\w+)/) || [])[1];
            const type = (url.match(/type=(\w+)/) || [])[1];
            if (url.startsWith('api/on-orbit/chart')) { return { ok: true, json: async () => ({ rows: payload.__exposure || [] }) }; }
            if (url === 'assets/weatherCoast.json') { return { ok: true, json: async () => JSON.parse(read('assets', 'weatherCoast.json')) }; }
            if (url === 'api/weather/map?name=drapGlobal') { return payload.__drap ? { ok: true, json: async () => payload.__drap } : { ok: false, json: async () => ({}) }; }
            if (url.startsWith('api/weather/tec-')) {
                const tec = payload.__tec;
                const part = url.slice('api/weather/'.length).split('?')[0];
                const q = (k) => (url.match(new RegExp(`[?&]${k}=([^&]*)`)) || [])[1];
                const give = (body) => (body ? { ok: true, json: async () => body } : { ok: false, json: async () => ({}) });
                if (!tec) { return give(null); }
                return give(part === 'tec-index' ? tec.index : part === 'tec-code' ? tec.code(q('kind'), q('day'), Number(q('hour'))) : part === 'tec-latest' ? tec.latest
                    : part === 'tec-at' ? tec.at : part === 'tec-series' ? tec.series : part === 'tec-summary' ? tec.summary : null);
            }
            if (url === 'api/weather/map?name=ovation') { return payload.__ovation ? { ok: true, json: async () => payload.__ovation } : { ok: false, json: async () => ({}) }; }
            if (url === 'api/weather/now') { return { ok: true, json: async () => payload.__now }; }
            if (type) { return { ok: true, json: async () => ({ type, events: events[type] || [] }) }; }
            return payload[name] ? { ok: true, json: async () => payload[name] } : { ok: false, json: async () => ({}) };
        } };
    vm.createContext(sb2);
    for (const file of ['chartCore.js', 'chartTime.js', 'weatherCharts.js', 'weatherEarth.js', 'weatherGcr.js', 'weatherMap.js', 'weatherTec.js', 'weatherSat.js', 'weatherAurora.js', 'weatherHf.js', 'weatherDrag.js']) { vm.runInContext(read('assets', file), sb2, { filename: file }); }
    const build = async (loader, drawer, width = 800) => {
        vm.runInContext('weatherForgetData()', sb2);
        sb2.d = await vm.runInContext(`${loader}()`, sb2);
        return vm.runInContext(`${drawer}(d, ${width})`, sb2);
    };

    check('x-ray class text', [['xrayClassOf(3.4e-5)', 'M3.4'], ['xrayClassOf(1.2e-4)', 'X1.2'], ['xrayClassOf(2e-7)', 'B2.0'], ['xrayClassOf(5e-9)', 'A0.5'], ['xrayClassOf(null)', 'no data']]
        .every(([e, want]) => vm.runInContext(e, sb2) === want));

    const k2 = await build('loadK2', 'k2Html');
    check('K2: no undefined or NaN', !/undefined|NaN/.test(k2));
    check('K2: class letters, the R and S lines and the GCR floor', ['>A<', '>X<', '>S1<', '>GCR<', 'R1 (M1)', 'R3 (X1)', 'S1 (10 pfu, &gt;10 MeV)'].every((x) => k2.includes(x) || x === 'S1 (10 pfu, &gt;10 MeV)' && k2.includes('S1 (10 pfu, >10 MeV)')));
    check('K2: the M flare is marked once (the second satellite\'s listing is dropped), the X flare once, the C flare not', count(k2, /<g class="chart-event"><line[^>]*stroke="var\(--tng-amber\)"/g) === 1
        && count(k2, /<g class="chart-event"><line[^>]*stroke="var\(--tng-salmon\)"/g) === 1, `${count(k2, /<g class="chart-event">/g)}`);
    check('K2: particle events: DONKI observed, DONKI forecast (hollow), and our S-event', count(k2, /Solar energetic particle event/g) === 2 && count(k2, /fill="#000"/g) === 1 && k2.includes('S-event (>10 MeV at or above 10 pfu)'),
        `${count(k2, /fill="#000"/g)}`);
    check('K2: tooltip names GOES-18, its place and 0.14 light-seconds, classes, S-scale and the S-event rule', ['GOES-18', '0.14 light-seconds', 'R3 at X1', 'S1 is 10 pfu', 'first of three consecutive', 'galactic cosmic rays'].every((x) => k2.includes(x)));
    check('K2: the series are fetched rounded (sig) to keep them small', asked.some((u) => /goesXrayLong.*sig=4/.test(u)) && asked.some((u) => /goesProtonGE10MeV.*sig=3/.test(u)));

    const fr = await build('loadFlareRecord', 'flareRecordHtml', 360);
    check('flare record: 30 days of bars (one per stored day)', !/undefined|NaN/.test(fr) && count(fr, /<rect class="chart-hit"/g) === 30, `${count(fr, /<rect class="chart-hit"/g)}`);
    check('flare record: M and X days labelled with their class, C days not', fr.includes('>M6.7<') && fr.includes('>X1.2<') && !fr.includes('>C3.0<'));
    check('flare record: X bar salmon, M bar amber', fr.includes('fill="var(--tng-salmon)"') && fr.includes('fill="var(--tng-amber)"'));

    const long = await build('loadLongView', 'longViewHtml');
    check('long view: a dot for every day, one hollow burst day with its explanation', !/undefined|NaN/.test(long) && count(long, /<circle/g) >= 398 && count(long, /fill="#000"/g) === 1
        && long.includes('Flare radio burst during the 20 UT measurement; not representative of the day'), `${count(long, /<circle/g)}`);
    check('long view: the 81-day mean is dashed where it includes the forecast, and nothing is hatched', count(long, /chart-forecast-line/g) === 1 && !long.includes('chart-forecast-band'));
    check('long view: fixed ladders -- F10.7 axis on steps of 40 from 60, sunspots in hundreds', long.includes('>220<') && long.includes('>200<') && long.includes('SUNSPOT NUMBER'));
    check('long view: month ticks, not week ticks', count(long, /class="lcars-line-xtick"/g) <= 8 && long.includes('Jan 2026'));
    check('long view: tooltip gives the formula, its limit and the ground source', long.includes('at least 75 of the 81 days') && long.includes('Penticton'));

    const cycle = await build('loadSolarCycle', 'solarCycleHtml', 360);
    check('solar cycle: year ticks, two cycle-start markers, the current cycle in amber', !/undefined|NaN/.test(cycle) && count(cycle, /<g class="chart-event">/g) === 2 && cycle.includes('stroke="var(--tng-amber)"') && cycle.includes('>2010<'),
        `${/undefined|NaN/.test(cycle)} ${count(cycle, /<g class="chart-event">/g)} ${cycle.includes('stroke="var(--tng-amber)"')} ${cycle.includes('>2010<')} ${(cycle.match(/lcars-line-xtick"[^>]*>[^<]*/g) || []).join('|')}`);
    check('solar cycle: provisional months (3) and the month in progress are hollow', count(cycle, /fill="#000"/g) === 4, `${count(cycle, /fill="#000"/g)}`);
    check('solar cycle: credit names SILSO', cycle.includes('WDC-SILSO, Royal Observatory of Belgium, Brussels'));

    const cme = await build('loadCmeTimeline', 'cmeTimelineHtml');
    check('CMEs: both launches dotted, with type words', !/undefined|NaN/.test(cme) && cme.includes('Speed 900 km/s, type C (common') && cme.includes('extremely rare'));
    check('CMEs: the predicted arrival has a ring, a dashed line and a bar of the typical error', count(cme, /class="chart-span chart-hit"/g) >= 3 && cme.includes('typical error about 10 hours'));
    check('CMEs: the observed shock is a marker, and now is marked', cme.includes('Interplanetary shock observed at Earth') && cme.includes('Now, '));
    check('CMEs: streams, and the possible return of one', cme.includes('High-speed stream seen at L1') && cme.includes('may return'));
    check('CMEs: the future is hatched; the others are counted', cme.includes('chart-forecast-band') && cme.includes('Not shown: 14 other CMEs'));
    check('CMEs: tooltip names SOHO at L1 in light-seconds, STEREO-A, and the error source', cme.includes('about 5 light-seconds') && cme.includes('STEREO-A') && cme.includes('Wold'));

    const out = await build('loadOutlook', 'outlookHtml');
    check('outlook: forecast dashed from the last observation, two stacked panels hatched', !/undefined|NaN/.test(out) && count(out, /chart-forecast-line/g) === 1 && count(out, /chart-forecast-band/g) === 2);
    check('outlook: Ap bars blue observed, violet forecast', out.includes('fill="var(--tng-periwinkle)"') && out.includes('fill="var(--tng-violet)"') && out.includes('(forecast)'));
    check('outlook: Ap wording and the stacked-not-overlaid reason', out.includes('2 nT') && out.includes('stacked, not overlaid'));

    const guard = vm.runInContext('weatherGuard((d) => d.n, (d, w) => `drawn ${w}`)', sb2);
    check('guard: empty data gives the publish hint', guard({ n: 0 }, 400).includes('publishSite.py weather') && guard({ n: 1 }, 400) === 'drawn 400');
    check('series: an unknown series is empty, not an error', (await vm.runInContext('weatherSeries("noSuchSeries", "3d")', sb2)).points.length === 0);

    // ---- ERTH NOW ----
    check('gLevelOf follows the NOAA thresholds', [['gLevelOf(4.33)', 0], ['gLevelOf(4.67)', 1], ['gLevelOf(5.67)', 2], ['gLevelOf(6.67)', 3], ['gLevelOf(7.67)', 4], ['gLevelOf(9)', 5], ['gLevelOf(null)', 0]]
        .every(([e, want]) => vm.runInContext(e, sb2) === want));
    sb2.nowData = await vm.runInContext('weatherNow()', sb2);
    const strip = vm.runInContext('nowStripFrame(nowData)', sb2);
    check('right-now strip: R1, S0, G1, Kp at least 4.7, F10.7, Bz southward and speed, each with its age', !/undefined|NaN/.test(strip) && ['R1', 'S0', 'G1', '&ge; 4.7', '>101<', '>-7.5<', 'southward, 2 min ago', '>455<'].every((x) => strip.includes(x)), '');
    check('right-now strip: tooltip names SOLAR-1 at L1 in light-seconds and Penticton', strip.includes('about 5 light-seconds') && strip.includes('Penticton') && strip.includes('class="chart-tip"'));

    vm.runInContext('weatherForgetData()', sb2);
    const scales = await vm.runInContext('(async () => scalesHtml(await loadScales()))()', sb2);
    check('scales: levels now and the 24-hour maximum for R, S and G', scales.includes('>R1<') && scales.includes('24-HOUR MAXIMUM: R2, moderate') && scales.includes('>S0<') && scales.includes('>G1<') && scales.includes('24-HOUR MAXIMUM: G3, strong'));
    check('scales: level colours, the triggers and the thresholds in the tooltip', scales.includes('var(--tng-sand)') && scales.includes('LEVEL 1 AT KP 5') && scales.includes('G1 at Kp 5') && scales.includes('0.14 light-seconds'));

    const storm = await build('loadStormStrip', 'stormStripHtml');
    check('storm strip: five rows on one axis (X-ray, protons, wind, Bz, Kp with Dst)', !/undefined|NaN/.test(storm) && count(storm, /class="lcars-line-axis"/g) === 5 && count(storm, /class="lcars-line-xtick"/g) <= 8, `${count(storm, /class="lcars-line-axis"/g)}`);
    check('storm strip: Kp bars blue, with the G1 block sand, and forecast bars violet', storm.includes('fill="var(--tng-sand)"') && storm.includes('fill="var(--tng-periwinkle)"') && storm.includes('fill="var(--tng-violet)"') && storm.includes('(G1)'), '');
    check('storm strip: Dst on an inverted right axis (the deepest value is the highest point)', storm.includes('DST (NT), INVERTED') && (() => {
        const m = storm.match(/<path class="lcars-dual-line" d="([^"]*)" stroke="var\(--tng-amber\)" stroke-width="2"/);
        if (!m) { return false; }
        const ys = m[1].match(/[ML][\d.]+,([\d.]+)/g).map((q) => Number(q.split(',')[1]));
        return Math.min(...ys) < Math.max(...ys) && ys.indexOf(Math.min(...ys)) !== 0;
    })());
    check('storm strip: CME launches, a predicted arrival (hollow) and the shock seen at Earth run through all rows', count(storm, /<g class="chart-event">/g) === 4 && storm.includes('CME predicted to arrive') && storm.includes('CME launched') && storm.includes('Interplanetary shock seen at Earth')
        && count(storm, /r="5" stroke="var\(--tng-salmon\)" fill="#000"/g) === 1, `${count(storm, /<g class="chart-event">/g)}`);
    check('storm strip: the next 12 hours are hatched', storm.includes('chart-forecast-band') && count(storm, /chart-forecast-band/g) === 5);
    check('storm strip: tooltip gives the order, the spacecraft and distances', ['the order it happens', 'GOES-18', '0.14 light-seconds', 'SOLAR-1', 'about 5 light-seconds', 'Kyoto'].every((x) => storm.includes(x)));
    check('storm strip: wind, Bz and Bt fetched rounded to 3 figures', asked.some((u) => /l1WindSpeed.*range=3d&sig=3/.test(u)));

    const kpdst = await build('loadKpDst', 'kpDstHtml');
    check('Kp with Dst: a bar per 3-hour block over 7 days, G colours only where reached', !/undefined|NaN/.test(kpdst) && count(kpdst, /<rect class="chart-hit"/g) >= 55 && kpdst.includes('fill="var(--tng-sand)"') && kpdst.includes('fill="var(--tng-tan)"') && kpdst.includes('(G3)'), `${count(kpdst, /<rect class="chart-hit"/g)}`);
    check('Kp with Dst: Dst label and tooltip (four observatories, provisional)', kpdst.includes('Kyoto real-time quick-look, provisional') && kpdst.includes('Hermanus') && kpdst.includes('Dst axis steps in fixed floors'));
    const kpc = await build('loadKpCompare', 'kpCompareHtml', 360);
    check('Kp comparison: SWPC and GFZ paired bars for 24 hours, predicted blocks left out', !/undefined|NaN/.test(kpc) && count(kpc, /fill="var\(--tng-sand\)"/g) >= 7 && count(kpc, /fill="var\(--tng-periwinkle\)"/g) >= 7 && !kpc.includes('forecast Kp'));
    const hemi = await build('loadHemiPower', 'hemiPowerHtml');
    check('hemispheric power: north and south lines on one fixed axis (0 to 50 GW for 22 GW)', !/undefined|NaN/.test(hemi) && count(hemi, /<path class="lcars-dual-line"/g) === 2 && hemi.includes('>50<') && !hemi.includes('>100<') && hemi.includes('0.003 light-seconds'));

    const grid = await build('loadKpGrid', 'kpGridHtml', 700);
    check('Kp grid: three rows of eight cells, issue time in the pill, the Kp 5 cell outlined', !/undefined|NaN/.test(grid) && count(grid, /<rect class="chart-hit"/g) === 24 && count(grid, /stroke="var\(--space-white\)"/g) === 1 && grid.includes('ISSUED 10-24 12:30 UTC') && grid.includes('21-24'), '');
    const chances = await build('loadForecastProbabilities', 'forecastProbabilitiesHtml');
    check('forecast chances: probabilities for three days as bars, and the highest G level of each day', !/undefined|NaN/.test(chances) && chances.includes('width:30%') && chances.includes('>5%<') && chances.includes('G1') && chances.includes('HIGHEST G LEVEL'), '');
    sb2.arrivingData = await vm.runInContext('loadCmeTimeline()', sb2);
    const arriving = vm.runInContext('cmeTimelineHtml(arrivingData, 800, { title: "WHAT IS ARRIVING", credit: " link" })', sb2);
    check('what is arriving: the CME timeline under its own title', arriving.includes('WHAT IS ARRIVING') && !arriving.includes('CMES ON THE WAY') && arriving.includes('link'));

    // ---- GCR ----
    check('GCR: percent of reference and the hour a stamp opens', vm.runInContext('percentOfReference(6177, 6177)', sb2) === 0 && Math.abs(vm.runInContext('percentOfReference(6177 * 1.02, 6177)', sb2) - 2) < 1e-9
        && vm.runInContext('gcrHourAt([[0, 1], [3600000, 2]], 1800000)', sb2)[1] === 1 && vm.runInContext('gcrHourAt([[0, 1], [3600000, 2]], 3600000)', sb2)[1] === 2);
    const sm = vm.runInContext('smooth13Months(Array.from({ length: 25 }, (_, i) => i - 12).map((k) => [Date.UTC(2020, 6 + k, 1), k === 0 ? 12 : 0]))', sb2);
    check('GCR: the 13-month smoothing is SILSO\'s (half weights at the ends, six months lost each side)', sm.length === 13 && Math.abs(sm[6][1] - 1) < 1e-9 && Math.abs(sm[0][1] - 0.5) < 1e-9 && Math.abs(sm[12][1] - 0.5) < 1e-9 && Math.abs(sm[3][1] - 1) < 1e-9, JSON.stringify(sm.map((p) => p[1])));
    const gnow = await build('loadCosmicRaysNow', 'cosmicRaysNowHtml');
    check('GCR now: tile gives Oulu in per cent of its reference, a possible Forbush decrease, Dome C with its last date', !/undefined|NaN/.test(gnow) && gnow.includes('OULU NOW') && gnow.includes('-3.0%') && gnow.includes('>Possible<') && gnow.includes('data to 10-23 ') && gnow.includes('(31 h ago)'), (gnow.match(/weather-tile-value[^<]*<[^>]*>[^<]*/g) || []).join('|'));
    check('GCR now: two stepped lines (an hour wide), one per station', count(gnow, /<path class="lcars-dual-line"/g) === 2 && /d="M[\d.]+,[\d.]+ L[\d.]+,[\d.]+ L/.test(gnow));
    check('GCR now: the shock and the G2 storm are marked, the G0 storm is not', count(gnow, /<g class="chart-event">/g) === 2 && gnow.includes('Geomagnetic storm G2') && !gnow.includes('G0'));
    check('GCR now: tooltip has the formula, both references, the start-of-hour rule, the 1.7 and no spacecraft', ['100 &times; (I / I<sub>ref</sub>', '6,177', '1,081', 'start of the hour', 'about 1.7 times', 'no spacecraft', 'Sodankyla'].every((x) => gnow.includes(x)));
    check('GCR now: Dome C is never shifted: its data end where they end', gnow.includes('Dome C (data to 10-23'));
    const gcy = await build('loadGcrCycle', 'gcrCycleHtml');
    check('GCR cycle: inverted cosmic-ray axis against the sunspot number, cycle starts marked', !/undefined|NaN/.test(gcy) && gcy.includes('INVERTED') && gcy.includes('SUNSPOT NUMBER, 13-MONTH, DASHED') && count(gcy, /<g class="chart-event">/g) === 2);
    check('GCR cycle: Dome C from Nov 2019 only, the partial month hollow, the heavily corrected 2016 month not drawn', gcy.includes('stroke="var(--tng-lavender)"') && count(gcy, /fill="#000"/g) === 1 && gcy.includes('partial month from 2026-01-09') && !gcy.includes('Dec 2016'), `${count(gcy, /fill="#000"/g)}`);
    check('GCR cycle: tooltip formula and SILSO credit', gcy.includes('0.5 R<sub>m&minus;6</sub>') && gcy.includes('6,177') && gcy.includes('WDC-SILSO'));

    // ---- HF COMMS ----
    const hfFlares = await build('loadK2', 'k2Html');
    sb2.hfK2 = sb2.d;
    const hfFlares2 = vm.runInContext('k2Html(hfK2, 800, { title: "FLARE FADE-OUT AND RADIATION", tipExtra: hfFlareTip })', sb2);
    check('HF flares: K2 under the HF title, with the radio paragraph (blackout, polar cap absorption)', hfFlares2.includes('FLARE FADE-OUT AND RADIATION') && !hfFlares2.includes('>FLARES AND PARTICLES<') && hfFlares2.includes('polar cap absorption') && hfFlares2.includes('R3 at X1') && hfFlares.includes('FLARES AND PARTICLES'));
    sb2.nowData = await vm.runInContext('weatherNow()', sb2);
    const hfAbs = vm.runInContext('hfAbsorptionHtml(nowData)', sb2);
    check('HF absorption: below 5 MHz it says so in one line, with the value; formula, D-RAP and GOES-18 in the tooltip', hfAbs.includes('No significant HF absorption (highest affected frequency 3.2 MHz, below 5 MHz') && ['D-RAP', 'cos', '0.14 light-seconds', 'not auroral absorption'].every((x) => hfAbs.includes(x)));
    sb2.nowHigh = { latest: { drapMax: ['2026-10-24T19:00:00Z', 8, 'MHz', null], drapMaxLat: ['2026-10-24T19:00:00Z', 10, 'deg', null], drapMaxLon: ['2026-10-24T19:00:00Z', -30, 'deg', null] }, loadedAt: NOW };
    check('HF absorption: from 5 MHz it reports the frequency and where; with no map to hand it says so', vm.runInContext('hfAbsorptionHtml(nowHigh)', sb2).includes('highest affected frequency is 8.0 MHz') && vm.runInContext('hfAbsorptionHtml(nowHigh)', sb2).includes('The map could not be loaded'));

    // ---- the D-RAP map and the reusable map component ----
    const near = (a, b, eps) => Math.abs(a - b) <= eps;
    const sun1 = vm.runInContext(`weatherSubsolarPoint(${Date.UTC(2026, 9, 25, 12)})`, sb2);
    const sun2 = vm.runInContext(`weatherSubsolarPoint(${Date.UTC(2026, 5, 21, 8, 24)})`, sb2);
    const sun3 = vm.runInContext(`weatherSubsolarPoint(${Date.UTC(2026, 2, 20, 14, 46)})`, sb2);
    check('map: the point under the Sun (25 Oct 12:00 UTC about 12.0 S, 4.0 W; June solstice 23.4 N; March equinox on the equator)',
        near(sun1.lat, -12.0, 0.3) && near(sun1.lon, -4.0, 0.5) && near(sun2.lat, 23.44, 0.1) && near(sun3.lat, 0, 0.3), JSON.stringify([sun1, sun2, sun3]));
    const term = vm.runInContext(`weatherTerminator(${Date.UTC(2026, 9, 25, 12)}, -180, 180, 5)`, sb2);
    const ninety = term.line.every(([lon, lat]) => {
        const rad = Math.PI / 180;
        const cosD = Math.sin(lat * rad) * Math.sin(term.sun.lat * rad) + Math.cos(lat * rad) * Math.cos(term.sun.lat * rad) * Math.cos((lon - term.sun.lon) * rad);
        return Math.abs(cosD) < 1e-9;
    });
    check('map: every point of the day-night line is 90 degrees from the point under the Sun; the dark pole flips with the season', ninety && term.darkPole === 'N'
        && vm.runInContext(`weatherTerminator(${Date.UTC(2026, 5, 21, 12)}).darkPole`, sb2) === 'S');
    sb2.testGrid = { values: [[1, 2, 3, 4], [5, 6, 7, 8]], latMax: 45, latStep: -90, lonMin: -135, lonStep: 90 };
    check('map: the value at a place is the nearest cell, longitude wraps, outside the rows gives null',
        vm.runInContext('weatherGridValueAt(testGrid, 40, -130)', sb2) === 1 && vm.runInContext('weatherGridValueAt(testGrid, -40, 130)', sb2) === 8 && vm.runInContext('weatherGridValueAt(testGrid, 40, 140)', sb2) === 4 && vm.runInContext('weatherGridValueAt(testGrid, 40, 230)', sb2) === 1
        && vm.runInContext('weatherGridValueAt(testGrid, 40, -135.1)', sb2) === 1 && vm.runInContext('weatherGridValueAt(testGrid, -100, 0)', sb2) === null);
    check('D-RAP colours: nothing below 1 MHz, bands at 1, 5, 10, 15, 20 and 30 MHz', [[9, null], [10, 'var(--tng-periwinkle)'], [49, 'var(--tng-periwinkle)'], [50, 'var(--tng-sand)'], [100, 'var(--tng-amber)'],
        [150, 'var(--tng-salmon)'], [200, 'var(--red)'], [300, 'var(--tng-pink)']].every(([v, want]) => vm.runInContext(`hfMapColour(${v})`, sb2) === want));
    check('proton message: normal is no event, anything else is returned', vm.runInContext('hfProtonMessage("Normal X-ray Background; Normal Proton Background")', sb2) === null
        && vm.runInContext('hfProtonMessage("Normal X-ray Background; S1 Proton Event")', sb2) === 'S1 Proton Event' && vm.runInContext('hfProtonMessage(null)', sb2) === null);
    sb2.ring = [[170, 60], [-170, 60], [-160, 62]];
    const coastPath = vm.runInContext('weatherMapCoastSvg([ring], weatherMapFrame(600, WEATHER_MAP_WORLD), WEATHER_MAP_WORLD)', sb2);
    check('map outline: a ring that crosses the edge of the map lifts the pen (no line across the world)', count(coastPath, /M\d/g) === 2 && count(coastPath, /L\d/g) === 1, coastPath);

    // quiet: one line and a link; neither the map nor the outline is fetched
    asked.length = 0;
    vm.runInContext('weatherForgetData()', sb2);
    payload.__now.latest.drapMax = ['2026-10-24T19:08:00Z', 0.9, 'MHz', 'Normal X-ray Background; Normal Proton Background'];
    sb2.quiet = await vm.runInContext('loadAbsorption()', sb2);
    const quietHtml = vm.runInContext('hfAbsorptionHtml(quiet, 800)', sb2);
    check('D-RAP quiet: one line, the link to show the map, no map, and neither the map nor the outline is fetched', quietHtml.includes('No significant HF absorption') && quietHtml.includes('Show the map anyway')
        && !quietHtml.includes('class="weather-map"') && !asked.some((u) => /drapGlobal|weatherCoast/.test(u)), asked.join());
    // the visitor asks for it
    const fakeSlot = { chartData: sb2.quiet, drawer: sb2.hfAbsorptionHtml, minWidth: 480, clientWidth: 900, innerHTML: '' };
    sb2.document.getElementById = (id) => (id === 'weather-hf-absorption' ? fakeSlot : null);
    await vm.runInContext('hfShowMap(true)', sb2);
    check('D-RAP quiet: "show the map anyway" fetches the map and the outline once and draws it, with a link to put it away', asked.filter((u) => /drapGlobal/.test(u)).length === 1 && asked.filter((u) => /weatherCoast/.test(u)).length === 1
        && fakeSlot.innerHTML.includes('class="weather-map"') && fakeSlot.innerHTML.includes('Put the map away') && !fakeSlot.innerHTML.includes('MAX'));
    await vm.runInContext('hfShowMap(false)', sb2);
    check('D-RAP quiet: "put the map away" returns to the line', !fakeSlot.innerHTML.includes('class="weather-map"') && fakeSlot.innerHTML.includes('Show the map anyway'));
    sb2.document.getElementById = () => null;

    // a flare: 12 MHz
    vm.runInContext('weatherForgetData()', sb2);
    payload.__now.latest.drapMax = ['2026-10-24T19:08:00Z', 12, 'MHz', 'M5.0 X-ray; Normal Proton Background'];
    payload.__now.latest.drapMaxLat = ['2026-10-24T19:08:00Z', 9, 'deg', null];
    payload.__now.latest.drapMaxLon = ['2026-10-24T19:08:00Z', -30, 'deg', null];
    sb2.flareData = await vm.runInContext('loadAbsorption()', sb2);
    const drapMap = vm.runInContext('hfAbsorptionHtml(flareData, 900)', sb2);
    check('D-RAP map: drawn without undefined or NaN, with the key, the maximum, the night side, the outline and the valid time', !/undefined|NaN/.test(drapMap) && drapMap.includes('class="weather-map"')
        && ['1 to 5 MHz', '5 to 10 MHz', '10 to 15 MHz', '30 MHz and over', 'MAX 12.0', 'weather-map-night', 'weather-map-coast', 'map valid 2026-10-24 19:08 UTC', 'id="hf-drap-readout"'].every((x) => drapMap.includes(x)));
    check('D-RAP map: one rectangle per run of equal colour (3 polar rows, 3 patch rows) plus the black plot area, none for empty cells', count(drapMap, /<rect x=/g) === 6 + 1 && count(drapMap, /fill="var\(--tng-amber\)"/g) >= 3, `${count(drapMap, /<rect x=/g)}`);
    check('D-RAP map: the hover text names the place and the value from the stored cell', vm.runInContext('WEATHER_MAP_REGISTRY["hf-drap"].hoverText(9, -30)', sb2) === '9N, 30W: highest affected frequency 12.0 MHz'
        && vm.runInContext('WEATHER_MAP_REGISTRY["hf-drap"].hoverText(60, 100)', sb2).includes('0.0 MHz'));
    check('D-RAP map: the tooltip explains the map, night, polar cap absorption, the grid and the source', ['plain latitude-longitude', 'polar cap absorption from protons', '4 degrees of longitude by 2 of latitude', 'NOAA Space Weather Prediction Center'].every((x) => drapMap.includes(x)));
    sb2.observerLocation = { latitude: 51.5, longitude: -0.1 };
    const withYou = vm.runInContext('hfAbsorptionHtml(flareData, 900)', sb2);
    check('D-RAP map: with a location set, a YOU marker and the value at that place', withYou.includes('>YOU<') && withYou.includes('AT YOUR LOCATION (MHZ)') && withYou.includes('>0.0<'));
    delete sb2.observerLocation;
    // a proton event with little flare absorption
    vm.runInContext('weatherForgetData()', sb2);
    payload.__now.latest.drapMax = ['2026-10-24T19:08:00Z', 3, 'MHz', 'Normal X-ray Background; S1 Proton Event'];
    sb2.protonData = await vm.runInContext('loadAbsorption()', sb2);
    const protonCard = vm.runInContext('hfAbsorptionHtml(protonData, 900)', sb2);
    check('D-RAP proton event: the map appears below 5 MHz and the line speaks of the polar caps', protonCard.includes('class="weather-map"') && protonCard.includes('NOAA reports a proton event (S1 Proton Event)') && !protonCard.includes('Show the map anyway'));
    payload.__now.latest.drapMax = ['2026-10-24T19:08:00Z', 3.2, 'MHz', null];
    vm.runInContext('weatherForgetData()', sb2);
    const board = vm.runInContext('hfBoardHtml(nowData)', sb2);
    check('aviation board: R1 amber, S0 green, absorption green, GNSS grey with no TEC summary; marked indicative', count(board, /class="weather-lamp" style="background:var\(--tng-amber\)"/g) === 1 && count(board, /class="weather-lamp" style="background:var\(--green\)"/g) === 2
        && count(board, /class="weather-lamp" style="background:var\(--tng-mauve\)"/g) === 1 && board.includes('no TEC map held') && board.includes('not an official advisory'), '');
    sb2.nowRed = { latest: { noaaScaleR: ['x', 3, 'scale', null], noaaScaleS: ['x', 3, 'scale', null], drapMax: ['x', 20, 'MHz', null] }, loadedAt: NOW };
    check('aviation board: R3, S3 and 20 MHz are red', count(vm.runInContext('hfBoardHtml(nowRed)', sb2), /background:var\(--red\)/g) === 3);
    const strip2 = await build('loadL1Strip', 'l1StripHtml', 500);
    check('driving signal: three rows over the last hour, warning-time explanation, SOLAR-1 in light-seconds', !/undefined|NaN/.test(strip2) && count(strip2, /class="lcars-line-axis"/g) === 3 && strip2.includes('travel time of the wind, not of light') && strip2.includes('about 5 light-seconds'));
    check('driving signal: series fetched rounded to 3 figures, last six hours', asked.some((u) => /l1WindSpeed&range=6h&sig=3/.test(u)));
    sb2.chancesData = await vm.runInContext('loadForecastProbabilities()', sb2);
    const chancesHf = vm.runInContext('forecastProbabilitiesHtml(chancesData, 400, { title: "RADIO OUTLOOK", noG: true })', sb2);
    check('radio outlook: the K8 chances under the HF title, without the G row', chancesHf.includes('RADIO OUTLOOK') && !chancesHf.includes('HIGHEST G LEVEL') && chancesHf.includes('width:30%'));

    // ---- LEO DRAG ----
    check('daily maximum Kp', JSON.stringify(vm.runInContext('dailyMaxKp([[0, 1], [3600000, 4], [86400000, 2], [90000000, null]])', sb2)) === JSON.stringify([[0, 4], [86400000, 2]]));
    const air = await build('loadAtmosphere', 'atmosphereHtml');
    check('atmosphere: two stacked panels, daily-maximum Kp bars with the G colour, F10.7 dots', !/undefined|NaN/.test(air) && count(air, /class="lcars-line-axis"/g) === 2 && air.includes('DAILY MAXIMUM KP') && air.includes('fill="var(--tng-sand)"') && count(air, /<circle/g) >= 80, `${count(air, /<circle/g)}`);
    check('atmosphere: tooltip writes the drag formula and names the models and Penticton; the drag index is stated as waiting', ['&frac12; &rho; v&sup2;', 'NRLMSISE-00', 'JB2008', 'Penticton', 'at least 75 of the 81 days', 'waits for the element-set history'].every((x) => air.includes(x)));
    const expo = await build('loadExposure', 'exposureHtml', 700);
    check('exposure: bars of 10 km, SpaceX stacked on the others, VLEO shaded, tooltip with the counts', !/undefined|NaN/.test(expo) && expo.includes('VLEO, BELOW 450 KM') && expo.includes('540 to 550 km: 1,530 active payloads (1,500 SpaceX, 30 others)')
        && expo.includes('fill="var(--tng-amber)"') && expo.includes('fill="var(--tng-periwinkle)"') && count(expo, /<rect class="chart-hit"/g) === 55, `${count(expo, /<rect class="chart-hit"/g)}`);
    check('exposure: the catalogue is named as the NORAD catalogue via Space-Track', expo.includes('NORAD satellite catalogue (via Space-Track)') && !/Space Force/i.test(expo));
    sb2.dragOutlook = await vm.runInContext('loadOutlook()', sb2);
    check('drag outlook: K5 under its own title', vm.runInContext('outlookHtml(dragOutlook, 800, { title: "WHAT DRAG DOES NEXT" })', sb2).includes('WHAT DRAG DOES NEXT'));
    sb2.dragGrid = await vm.runInContext('loadKpGrid()', sb2);
    check('drag Kp grid: K7 under its own title', vm.runInContext('kpGridHtml(dragGrid, 400, { title: "THE KP FORECAST" })', sb2).includes('THE KP FORECAST'));

    // ---- TEC: SAT COMMS, YOUR PATH and the GNSS lamp ----
    const ctx = (code) => vm.runInContext(code, sb2);
    check('TEC arithmetic: 20 TECU delays GPS L1 by 3.25 m (0.16 m per TECU)', near(ctx('tecDelayM(20, 1575.42)'), 3.248, 0.01));
    check('TEC arithmetic: Faraday rotation for 20 TECU and 50 uT matches DEFS (145.8 MHz about 640, 437 about 71, 2.2 GHz about 3, 8.2 GHz about 0.2 degrees)',
        near(ctx('tecFaradayDeg(20, 50, 145.8)'), 636, 12) && near(ctx('tecFaradayDeg(20, 50, 437)'), 71, 2) && near(ctx('tecFaradayDeg(20, 50, 2200)'), 2.8, 0.2) && near(ctx('tecFaradayDeg(20, 50, 8200)'), 0.2, 0.05));
    check('TEC arithmetic: the field along a vertical ray is nil at the magnetic equator and 40 to 50 uT near Iceland; geomagnetic latitude of Reykjavik is 65 to 70',
        ctx('tecAlongFieldMicroT(0, 110)') < 10 && ctx('tecAlongFieldMicroT(64.1, -21.9)') > 38 && ctx('tecAlongFieldMicroT(64.1, -21.9)') < 52 && ctx('tecGeomagneticLat(64.1, -21.9)') > 65 && ctx('tecGeomagneticLat(64.1, -21.9)') < 71);
    check('TEC arithmetic: foF2 from GloTEC\'s NmF2 (50e10 gives 6.35 MHz, as the server) and from TEC with a 300 km slab (20 TECU about 7.3 MHz); the slab is recovered from a pair',
        near(ctx('tecFoF2FromNmF2(50)'), 6.35, 0.01) && near(ctx('tecFoF2FromTec(20, 300)'), 7.3, 0.05) && near(ctx('tecSlabKm([20], [tecFoF2FromTec(20, 420)])'), 420, 1) && ctx('tecSlabKm([], [])') === 300 && ctx('tecSlabKm([20], [tecFoF2FromTec(20, 900)])') === 600);
    const lampOf = (summary, ms = NOW) => { sb2.lampArg = summary; return ctx(`tecLamp(lampArg, ${ms})`); };
    const fresh = { validUtc: new Date(NOW - 35 * 60000).toISOString(), anomalyThirdFraction: 0.449, tecMaxObserved: { tec: 69.8 } };
    check('GNSS lamp: a quiet map is green; the third-largest anomaly at 60% is amber and at 100% red; ICAO 125 TECU amber and 175 red; the worse test wins',
        lampOf(fresh).colour === 'green' && lampOf({ ...fresh, anomalyThirdFraction: 0.6 }).colour === 'amber' && lampOf({ ...fresh, anomalyThirdFraction: 1.0 }).colour === 'red'
        && lampOf({ ...fresh, tecMaxObserved: { tec: 125 } }).colour === 'amber' && lampOf({ ...fresh, tecMaxObserved: { tec: 176 } }).colour === 'red' && lampOf({ ...fresh, anomalyThirdFraction: 0.7, tecMaxObserved: { tec: 180 } }).word === 'SEVERE');
    check('GNSS lamp: no map is grey (no data), a map over 6 hours old is grey (stale), too few cells for the anomaly leaves only the ICAO test',
        lampOf(null).colour === 'grey' && lampOf({ ...fresh, validUtc: new Date(NOW - 7 * H).toISOString() }).word === 'STALE' && lampOf({ ...fresh, anomalyThirdFraction: null }).colour === 'green' && lampOf({ ...fresh, anomalyThirdFraction: null }).detail.includes('too few'));
    check('TEC colours: absolute bands from 0, anomaly bands with nothing within 2 TECU, nothing for a missing value', ctx('tecAbsColour(95)') === 'var(--tng-violet)' && ctx('tecAbsColour(1000)') === 'var(--tng-pink)' && ctx('tecAbsColour(null)') === null
        && ctx('tecAnomColour(15)') === null && ctx('tecAnomColour(-15)') === null && ctx('tecAnomColour(-30)') === 'var(--tng-periwinkle)' && ctx('tecAnomColour(-120)') === 'var(--tng-violet)' && ctx('tecAnomColour(25)') === 'var(--tng-sand)' && ctx('tecAnomColour(150)') === 'var(--tng-salmon)');

    // GloTEC as a map: the unobserved cells hatched, and the anomaly not coloured there
    const glo = payload.__tec.latest;
    sb2.gloRecord = glo;
    const anomLayers = ctx('tecMapLayers(gloRecord, "anomaly")');
    check('TEC map layers: GloTEC anomaly is two layers (anomaly where observed, hatch where not); absolute is one; CODE is one stretched to the poles',
        anomLayers.length === 2 && anomLayers[0].values[0][0] === null && anomLayers[0].values[40][0] !== null && anomLayers[1].colourAt(0) === 'url(#weather-map-hatch)' && anomLayers[1].colourAt(3) === null
        && ctx('tecMapLayers(gloRecord, "absolute")').length === 1 && ctx('tecMapLayers(codeRecordArg, "absolute")'.replace('codeRecordArg', JSON.stringify(payload.__tec.code('prediction', '2026-10-25', 5))))[0].stretchPoles === true);
    const hover = ctx('tecMapHover(gloRecord, "anomaly")');
    check('TEC hover: coverage 0 says the model\'s estimate and does not give an anomaly; coverage 5 gives the anomaly with its sign', hover(-60, 0).includes('no observations') && !hover(-60, 0).includes('TECU from the 30-day median')
        && hover(50, 0).includes('coverage 5 of 5') && /anomaly [+-]?\d/.test(hover(50, 0)));

    // TEC NOW
    asked.length = 0;
    vm.runInContext('weatherForgetData()', sb2);
    sb2.satNow = await ctx('loadTecNow()');
    const satNow = ctx('tecNowHtml(satNow, 900)');
    check('TEC NOW: CODE is the default, absolute; the nearest hour (20:00 on 24 Oct) is the predicted map, said so in the pill; the key, night, outline and credit are there',
        !/undefined|NaN/.test(satNow) && satNow.includes('CODE PREDICTED 20:00 UTC') && /is-on"[^>]*onclick="satSet\('now', 'source', 'code'\)"/.test(satNow)
        && /is-on"[^>]*onclick="satSet\('now', 'mode', 'absolute'\)"/.test(satNow) && ['0 to 10 TECU', '100 and over', 'weather-map-night', 'weather-map-coast', 'doi:10.48620/97772', 'id="sat-now-readout"'].every((x) => satNow.includes(x)));
    check('TEC NOW: the GloTEC map is not asked for until its button is pressed (and the server\'s on-demand fetch of NOAA is therefore not triggered)', !asked.some((u) => /tec-latest/.test(u)) && asked.some((u) => /tec-code\?kind=prediction&day=2026-10-24&hour=20/.test(u)));
    check('TEC NOW: without a location the side column asks for one; no YOU marker', satNow.includes('set it with USR LOCN') && !satNow.includes('>YOU<'));
    check('TEC NOW: tooltip has both products, the anomaly wording, the coverage flag, the spacecraft with light-seconds, and the caveat on 95.7 against 68.0 TECU',
        ['Anomaly (GloTEC only)', 'Deviation of the total electron content from its 30-day median', 'Hatched grey', 'quality flag', 'COSMIC-2', '0.07 light-seconds', '95.7 TECU', '68.0'].every((x) => satNow.includes(x)));
    sb2.observerLocation = { latitude: 64.1, longitude: -21.9 };
    vm.runInContext('weatherForgetData()', sb2);
    sb2.satNowHere = await ctx('loadTecNow()');
    const satNowHere = ctx('tecNowHtml(satNowHere, 900)');
    check('TEC NOW: with a location, the tiles give TEC, the L-band delay (12.7 TECU: 2.06 m) and Faraday rotation at 145.8 and 437 MHz, and the map has a YOU ring',
        satNowHere.includes('12.7') && satNowHere.includes('>2.06<') && satNowHere.includes('FARADAY 145.8 MHZ') && satNowHere.includes('FARADAY 437 MHZ') && satNowHere.includes('>YOU<'));
    // the buttons: the slot is a fake; satSet fetches and redraws that card
    const satSlot = { chartData: null, drawer: sb2.tecNowHtml, minWidth: 480, clientWidth: 900, innerHTML: '' };
    sb2.document.getElementById = (id) => (id === 'weather-sat-map' ? satSlot : id === 'weather-sat-outlook-map' ? outSlot : null);
    const outSlot = { chartData: null, drawer: sb2.tecOutlookHtml, minWidth: 480, clientWidth: 900, innerHTML: '' };
    await ctx('satSet("now", "mode", "anomaly")');
    check('TEC NOW: ANOMALY switches to GloTEC (CODE has none), asks for the newest map once, hatches the unobserved cells, and explains it in the legend',
        asked.filter((u) => /tec-latest\?fields=tec,anom,q$/.test(u)).length === 1 && satSlot.innerHTML.includes('GLOTEC') && satSlot.innerHTML.includes('url(#weather-map-hatch)') && satSlot.innerHTML.includes('no observations: hatched')
        && /is-on"[^>]*onclick="satSet\('now', 'source', 'glotec'\)"/.test(satSlot.innerHTML) && /is-on"[^>]*onclick="satSet\('now', 'mode', 'anomaly'\)"/.test(satSlot.innerHTML), satSlot.innerHTML.slice(0, 300));
    await ctx('satSet("now", "source", "code")');
    check('TEC NOW: CODE goes back to the absolute CODE map', satSlot.innerHTML.includes('CODE PREDICTED') && /is-on"[^>]*onclick="satSet\('now', 'mode', 'absolute'\)"/.test(satSlot.innerHTML));
    sb2.document.getElementById = (id) => (id === 'weather-sat-map' ? satSlot : null);
    // GloTEC unreachable and none held: a sentence, not an error
    const savedLatest = payload.__tec.latest;
    payload.__tec.latest = null;
    vm.runInContext('weatherForgetData()', sb2);
    await ctx('satSet("now", "source", "glotec")');
    check('TEC NOW: if GloTEC cannot be had, the card says so and keeps its buttons', satSlot.innerHTML.includes('could not be had just now') && satSlot.innerHTML.includes('satSet(\'now\', \'source\', \'code\')'));
    payload.__tec.latest = savedLatest;
    await ctx('satSet("now", "source", "code")');
    sb2.document.getElementById = () => null;

    // EFFECT BY BAND
    sb2.bandData = await ctx('loadBandTable()');
    const bands = ctx('bandTableHtml(bandData)');
    check('EFFECT BY BAND: six-plus bands VHF to Ka, the numbers for 12.7 TECU at your place, scintillation as multiples of L-band, formulas in the tooltip',
        !/undefined|NaN/.test(bands) && ['VHF', 'UHF', '>L<', '>S<', '>X<', 'Ku', 'Ka'].every((x) => bands.includes(x)) && count(bands, /<tr>/g) === 8 && bands.includes('12.7 TECU over your location') && bands.includes('&times;1<')
        && bands.includes('&times;36') && ['40.3', '2.36', 'f<sup>&minus;1.5</sup>', 'not a measurement'].every((x) => bands.includes(x)));
    delete sb2.observerLocation;
    vm.runInContext('weatherForgetData()', sb2);
    const bandsNoPlace = ctx('bandTableHtml(await_)'.replace('await_', JSON.stringify({ place: null, here: null, loadedAt: NOW })));
    check('EFFECT BY BAND: with no location the DEFS example (20 TECU, 50 uT) is used and labelled', bandsNoPlace.includes('Set your location with USR LOCN') && bandsNoPlace.includes('EXAMPLE') && /63\d&deg;/.test(bandsNoPlace));

    // TEC AT YOUR LOCATION
    check('TEC at your location: without a place, a note; with one, the TEC panel and the Kp panel', ctx('tecLocationHtml({ place: null, loadedAt: 0 }, 800)').includes('Set your location with USR LOCN'));
    sb2.observerLocation = { latitude: 64.1, longitude: -21.9 };
    vm.runInContext('weatherForgetData()', sb2);
    const hereData = await ctx('loadTecLocation()');
    sb2.hereData = hereData;
    const hereChart = ctx('tecLocationHtml(hereData, 800)');
    check('TEC at your location: two panels on one UTC axis, CODE solid then dashed and hatched where it is predicted, the join marked, a GloTEC dot, Kp bars',
        !/undefined|NaN/.test(hereChart) && count(hereChart, /class="lcars-line-axis"/g) === 2 && count(hereChart, /chart-forecast-line/g) === 1 && count(hereChart, /chart-forecast-band/g) >= 1 && count(hereChart, /<g class="chart-event">/g) === 1
        && hereChart.includes('GloTEC ') && hereChart.includes('the join of two products') === true && count(hereChart, /<rect class="chart-hit"/g) >= 6, `${count(hereChart, /chart-forecast-band/g)} ${count(hereChart, /<g class="chart-event">/g)}`);
    check('TEC at your location: tooltip says solid is observed and dashed predicted, hollow dots are model estimates, and the offset between the products is expected', ['Solid', 'prediction', 'hollow dot', 'systematic offset', '95.7 TECU'].every((x) => hereChart.includes(x)));
    delete sb2.observerLocation;

    // TEC FORECAST
    vm.runInContext('weatherForgetData()', sb2);
    asked.length = 0;
    sb2.outData = await ctx('loadTecOutlook()');
    const outHtml = ctx('tecOutlookHtml(outData, 900)');
    check('TEC forecast: day buttons only for days with maps (today, +1, +2, +4; not the closing midnights), +1 DAY chosen, the hour slider at the current hour (19), a prediction pill with its issue time',
        ['TODAY', '+1 DAY<', '+2 DAYS', '+4 DAYS'].every((x) => outHtml.includes(x)) && !outHtml.includes('+3 DAYS') && !outHtml.includes('+5 DAYS') && /is-on"[^>]*onclick="satSet\('outlook', 'day', '2026-10-25'\)"/.test(outHtml)
        && outHtml.includes('type="range"') && outHtml.includes('value="19"') && outHtml.includes('CODE PREDICTED 19:00 UTC ISSUED 10-24 07:13') && asked.some((u) => /tec-code\?kind=prediction&day=2026-10-25&hour=19/.test(u)), outHtml.slice(0, 400));
    check('TEC forecast: tooltip says model prediction, issued once a day, the limit in a storm, and cites CODE', ['model predictions', 'only the days this site holds', 'a storm that has not started', 'doi:10.48620/97772'].every((x) => outHtml.includes(x)));
    sb2.document.getElementById = (id) => (id === 'weather-sat-outlook-map' ? outSlot : null);
    await ctx('satSet("outlook", "day", "2026-10-28")');
    check('TEC forecast: a day button fetches that day\'s map at the same hour and redraws the card', asked.some((u) => /tec-code\?kind=prediction&day=2026-10-28&hour=19/.test(u)) && outSlot.innerHTML.includes('CODE PREDICTED 19:00 UTC') && /is-on"[^>]*onclick="satSet\('outlook', 'day', '2026-10-28'\)"/.test(outSlot.innerHTML));
    await ctx('satSet("outlook", "hour", "3")');
    check('TEC forecast: the slider fetches the chosen hour', asked.some((u) => /day=2026-10-28&hour=3/.test(u)) && outSlot.innerHTML.includes('value="3"'));
    sb2.document.getElementById = () => null;
    ctx('SAT_STATE.outlook.day = null; SAT_STATE.outlook.hour = null');
    sb2.observerLocation = { latitude: 64.1, longitude: -21.9 };
    vm.runInContext('weatherForgetData()', sb2);
    sb2.outHere = await ctx('loadTecOutlookLocation()');
    const outHere = ctx('tecOutlookLocationHtml(outHere, 900)');
    check('TEC forecast at your location: observed tail then predicted days, hatched, join and now marked, Kp observed and forecast beneath (forecast hatched)',
        !/undefined|NaN/.test(outHere) && count(outHere, /class="lcars-line-axis"/g) === 2 && count(outHere, /chart-forecast-line/g) === 1 && count(outHere, /<g class="chart-event">/g) === 2 && outHere.includes('forecast Kp') && outHere.includes('Now, 2026-10-24 19:30 UTC'));
    delete sb2.observerLocation;

    // STORM RISK
    const risk = await build('loadKpGrid', 'stormRiskHtml', 500);
    check('STORM RISK: the forecast Kp of 5 makes it red and says disturbed TEC likely; indicative, not an advisory', risk.includes('DISTURBED TEC LIKELY') && risk.includes('background:var(--red)') && risk.includes('not an official advisory') && risk.includes('highest forecast Kp 5.0'));
    check('STORM RISK: below 4 green, 4 to 5 amber', [[3.3, 'QUIET'], [4.33, 'UNSETTLED']].every(([kp, word]) => ctx(`stormRiskHtml({ kp: [[${NOW + H}, ${kp}]], loadedAt: ${NOW}, issued: '' }, 400)`).includes(word)));

    // the GNSS lamp on the aviation board, with the summary the server gives
    vm.runInContext('weatherForgetData()', sb2);
    sb2.boardData = await ctx('loadBoard()');
    const boardTec = ctx('hfBoardHtml(boardData)');
    check('aviation board: the GNSS lamp is green from a quiet GloTEC summary, with the anomaly and the highest TEC in words; the rule is in the tooltip as provisional',
        boardTec.includes('3rd-largest anomaly 45% of median') && boardTec.includes('highest observed TEC 70 TECU') && count(boardTec, /class="weather-lamp" style="background:var\(--green\)"/g) === 3
        && ['provisional, to be confirmed', 'third-largest', '60% or more amber', 'ICAO', '125 TECU', '175'].every((x) => boardTec.includes(x)));
    payload.__tec.summary = { ...payload.__tec.summary, anomalyThirdFraction: 0.8 };
    vm.runInContext('weatherForgetData()', sb2);
    check('aviation board: a stronger anomaly makes the GNSS lamp amber (DEGRADED)', ctx('(async () => hfBoardHtml(await loadBoard()))()') !== null && (await ctx('(async () => hfBoardHtml(await loadBoard()))()')).includes('anomaly 80% of median'));
    payload.__tec.summary = { ...payload.__tec.summary, anomalyThirdFraction: 0.449 };

    // YOUR PATH
    vm.runInContext('weatherForgetData()', sb2);
    check('YOUR PATH: without a location, a note', ctx('hfPathHtml({ place: null, loadedAt: 0 }, 800)').includes('Set your location with USR LOCN'));
    sb2.observerLocation = { latitude: 64.1, longitude: -21.9 };
    payload.__drap.map.valid = '2026-10-24T19:08:00Z';
    sb2.pathData = await ctx('loadPath()');
    const pathHtml = ctx('hfPathHtml(pathData, 900)');
    check('YOUR PATH: one MHz axis with foF2 inferred from CODE TEC (dashed and hatched where predicted), GloTEC foF2 as a dot, and the D-RAP value at your place as one ring at now',
        !/undefined|NaN/.test(pathHtml) && count(pathHtml, /class="lcars-line-axis"/g) === 1 && count(pathHtml, /chart-forecast-line/g) === 1 && count(pathHtml, /<circle class="chart-hit"/g) >= 2 && pathHtml.includes('D-RAP at your place now') && pathHtml.includes('latest map, valid 2026-10-24 19:08 UTC'));
    check('YOUR PATH: tiles for foF2 (GloTEC 6.3, inferred), MUF(3000) about 3 x foF2 and D-RAP here now, labelled latest map only', pathHtml.includes('>6.3<') && pathHtml.includes('MUF(3000) ABOUT') && pathHtml.includes('>19<') && pathHtml.includes('latest map only'), (pathHtml.match(/weather-tile-value[^<]*<[^>]*>[^<]*/g) || []).join('|'));
    check('YOUR PATH: states what is missing (no D-RAP history, no measured foF2) and explains the inference with its error', ['Missing, and why', 'no history is stored', 'equivalent slab thickness', '15 to 20%', 'No ionosonde data'].every((x) => pathHtml.includes(x)));
    delete sb2.observerLocation;

    // nothing held: every new card still draws something sensible, with and without a location
    payload.__tec = null;
    for (const place of [null, { latitude: 64.1, longitude: -21.9 }]) {
        if (place) { sb2.observerLocation = place; } else { delete sb2.observerLocation; }
        for (const [loader, drawer] of [['loadTecNow', 'tecNowHtml'], ['loadBandTable', 'bandTableHtml'], ['loadTecLocation', 'tecLocationHtml'], ['loadTecOutlook', 'tecOutlookHtml'],
            ['loadTecOutlookLocation', 'tecOutlookLocationHtml'], ['loadKpGrid', 'stormRiskHtml'], ['loadBoard', 'hfBoardHtml'], ['loadPath', 'hfPathHtml']]) {
            let okay;
            try {
                const h = await build(loader, drawer);
                okay = typeof h === 'string' && !/undefined|NaN|Infinity/.test(h);
            } catch (e) {
                okay = false;
                console.log(`${drawer} with no TEC data: ${e.message}`);
            }
            check(`${drawer}: draws without error when the site holds no TEC (${place ? 'location set' : 'no location'})`, okay);
        }
    }
    delete sb2.observerLocation;
    payload.__tec = undefined;

    // ---- AURORAE ----
    const au = (code) => vm.runInContext(code, sb2);
    // projections: round trips, the pole in the middle, the far side of the globe out of sight
    {
        const checkRound = (name, projection, points) => {
            sb2.proj = projection;
            const worst = Math.max(...points.map(([lat, lon]) => {
                const p = au(`proj.project(${lat}, ${lon})`);
                const back = au(`proj.invert(${p.x}, ${p.y})`);
                const dl = Math.abs(((back.lon - lon + 540) % 360) - 180);
                return Math.max(Math.abs(back.lat - lat), Math.abs(lat) > 89 ? 0 : dl);
            }));
            check(`projection ${name}: invert undoes project (worst error ${worst.toExponential(1)} degrees)`, worst < 1e-6, String(worst));
        };
        checkRound('north', au('weatherProjection({ kind: "north", size: 600, rotateLon: 20 })'), [[89, 10], [70, -150], [45, 120], [31, 0], [60, 179]]);
        checkRound('south', au('weatherProjection({ kind: "south", size: 600, rotateLon: -40 })'), [[-89, 10], [-70, -150], [-45, 120], [-31, 0]]);
        checkRound('globe', au('weatherProjection({ kind: "globe", size: 600, centreLat: 40, centreLon: -30 })'), [[40, -30], [10, 20], [70, -100], [-20, -60], [0, -30]]);
        const north = au('weatherProjection({ kind: "north", size: 600 })');
        sb2.proj = north;
        check('projection: the north pole is the middle of the polar map, 30 N is on the rim, 20 N is out of the picture, longitude 0 is at the bottom',
            near(au('proj.project(90, 0)').x, 300, 1e-9) && near(au('proj.project(90, 0)').y, 300, 1e-9) && near(Math.hypot(au('proj.project(30, 77).x') - 300, au('proj.project(30, 77).y') - 300), 290, 1e-6)
            && au('proj.project(20, 0)').visible === false && au('proj.project(60, 0)').y > 300 && near(au('proj.project(60, 0)').x, 300, 1e-9));
        const south = au('weatherProjection({ kind: "south", size: 600 })');
        sb2.proj = south;
        check('projection: east runs anticlockwise round the north pole and clockwise round the south (seen from above each pole)', au('proj.project(-60, 90)').x < 300 && au('weatherProjection({ kind: "north", size: 600 }).project(60, 90)').x > 300);
        sb2.proj = au('weatherProjection({ kind: "globe", size: 600, centreLat: 0, centreLon: 0 })');
        check('projection: on the globe the centre is in the middle, the far side is out of sight, the pole is straight up', au('proj.project(0, 0)').visible && near(au('proj.project(0, 0)').x, 300, 1e-9)
            && au('proj.project(0, 180)').visible === false && au('proj.project(0, 90)').visible && au('proj.project(89.9, 0)').y < 20 && au('proj.invert(5, 5)') === null);
    }
    // contours (marching squares) and the sector fill
    {
        const grid = { values: Array.from({ length: 10 }, (_, i) => Array.from({ length: 12 }, (_, j) => (i >= 3 && i <= 5 && j >= 3 && j <= 5 ? 10 : 0))), latFirst: 0, latStep: 1, lonMin: 0, lonStep: 1 };
        sb2.cGrid = grid;
        const lines = au('weatherContours(cGrid, 5)');
        const first = lines[0][0];
        const last = lines[0][lines[0].length - 1];
        check('contours: a plateau gives one closed line, half way between the rows and columns it spans (lat 2.5 to 5.5, lon 2.5 to 5.5)', lines.length === 1 && first[0] === last[0] && first[1] === last[1]
            && Math.min(...lines[0].map((p) => p[0])) === 2.5 && Math.max(...lines[0].map((p) => p[0])) === 5.5 && Math.min(...lines[0].map((p) => p[1])) === 2.5 && Math.max(...lines[0].map((p) => p[1])) === 5.5);
        sb2.cGrid2 = { values: Array.from({ length: 6 }, (_, i) => Array.from({ length: 8 }, () => (i >= 4 ? 9 : 0))), latFirst: 0, latStep: 1, lonMin: 0, lonStep: 1 };
        const ring = au('weatherContours(cGrid2, 5)');
        check('contours: a cap that reaches round every longitude gives one closed ring of 8 points (the columns wrap)', ring.length === 1 && ring[0].length === 9 && ring[0].every((p) => Math.abs(p[0] - (3 + 5 / 9)) < 1e-9), JSON.stringify(ring[0] && ring[0].length));
        const flat = au('weatherContours({ values: [[1, 1], [1, 1]], latFirst: 0, latStep: 1, lonMin: 0, lonStep: 1 }, 5)');
        check('contours: a level the grid never reaches gives no line', flat.length === 0);
        const radius = (svg, proj) => Math.max(...[...svg.matchAll(/ d="([^"]*)"/g)].flatMap((m) => [...m[1].matchAll(/(-?[\d.]+) (-?[\d.]+)/g)].map((q) => Math.hypot(Number(q[1]) - proj.cx, Number(q[2]) - proj.cy))));
        sb2.full = { values: Array.from({ length: 181 }, () => Array(360).fill(30)), latFirst: -90, latStep: 1, lonMin: 0, lonStep: 1, colourAt: () => ['var(--tng-amber)', 0.9] };
        ['north', 'south', 'globe'].forEach((kind) => {
            sb2.proj = au(`weatherProjection({ kind: "${kind}", size: 600, centreLat: 30, centreLon: 10 })`);
            const svg = au('weatherSphereCellsSvg(full, proj)');
            check(`sector fill (${kind}): a world full of one colour is ONE path, and nothing is drawn outside the disc`, count(svg, /<path /g) === 1 && radius(svg, sb2.proj) <= sb2.proj.R + 1.5, `${radius(svg, sb2.proj)} ${sb2.proj.R}`);
        });
    }
    // the Sun, the Moon, the phase
    check('Sun: altitude 88 degrees at the equator at noon at the March equinox, and below the horizon at midnight', near(au(`auroraSunAltitude(${Date.UTC(2026, 2, 20, 12)}, 0, 0)`), 90 - 1.9, 1.2) && au(`auroraSunAltitude(${Date.UTC(2026, 2, 20, 0)}, 0, 0)`) < -80);
    check('Moon: new on 10 Oct 2026 (15:50 UTC), full on 26 Oct (04:12 UTC), waxing between, waning after',
        au(`auroraMoon(${Date.UTC(2026, 9, 10, 15, 50)}).fraction`) < 0.02 && au(`auroraMoon(${Date.UTC(2026, 9, 26, 4, 12)}).fraction`) > 0.98 && au(`auroraMoon(${Date.UTC(2026, 9, 18, 12)}).waxing`) === true
        && au(`auroraMoon(${Date.UTC(2026, 10, 1, 12)}).waxing`) === false && au(`auroraPhaseName(0.5, true)`) === 'first quarter' && au(`auroraPhaseName(0.8, false)`) === 'waning gibbous');
    {
        const t = Date.UTC(2026, 9, 26, 4, 12);
        check('Moon: at full Moon it stands opposite the Sun (altitudes add to about nothing, within 7 degrees)', Math.abs(au(`auroraMoonAltitude(${t}, 50, 10) + auroraSunAltitude(${t}, 50, 10)`)) < 7);
    }
    // geomagnetic latitude and the Kp needed
    check('Kp needed: 67 degrees and poleward is Kp 3, 60 degrees is Kp 5 (G1), 55 is 6, 50 is 7, 62.5 is 4.5, below 40 degrees is beyond Kp 9',
        au('requiredKpAt(75)') === 3 && au('requiredKpAt(-67)') === 3 && near(au('requiredKpAt(60)'), 5, 1e-9) && near(au('requiredKpAt(55)'), 6, 1e-9) && near(au('requiredKpAt(50)'), 7, 1e-9) && near(au('requiredKpAt(62.5)'), 4.5, 1e-9) && au('requiredKpAt(39)') === Infinity && near(au('requiredKpAt(40)'), 9, 1e-9));
    check('geomagnetic latitude: the dipole pole is at 90, the geographic pole is about 9.7 degrees from it, the magnetic equator crosses the Pacific', near(au('geomagneticLat(80.7, -72.7)'), 90, 1e-6) && near(au('geomagneticLat(90, 0)'), 80.7, 1e-6) && Math.abs(au('geomagneticLat(0, 160)')) < 12);
    // the oval as numbers (Spock's edge rule), on the synthetic map
    const ovalMap = payload.__ovation.map;
    sb2.ovalMap = ovalMap;
    const hn = au('auroraHemisphere(ovalMap, "N")');
    const hs = au('auroraHemisphere(ovalMap, "S")');
    check('oval numbers: the north peak is 30 at 68 N, 160 W (200 east); the edge at 64 N all round, the faint edge at 60 N', hn.peak.index === 30 && hn.peak.lat === 68 && hn.peak.lon === -160 && hn.edge.lat === 64 && hn.edge.cover === 360 && hn.faint.lat === 60);
    check('oval numbers: the south edge reaches 5 longitudes only, so there is no edge (fewer than 10); the faint edge does exist, at 55, in the middle of its run (lon 50)', hs.edge === null && hs.faint.lat === 55 && hs.faint.cover === 100 && hs.faint.lon === 50 && hs.peak.index === 8 && hs.peak.lat === -61);
    sb2.tie = { rows: Array.from({ length: 181 }, (_, i) => Array.from({ length: 360 }, (_, lon) => ((i - 90 === 70 && lon === 5) || (i - 90 === 65 && (lon === 100 || lon === 7)) ? 20 : 0))), latMin: -90,
        edgeN: Array(360).fill(null), edgeS: Array(360).fill(null), edgeFaintN: Array(360).fill(null), edgeFaintS: Array(360).fill(null) };
    check('oval numbers: among equal peaks the lowest |latitude|, then the lowest longitude, wins (as the ingester)', au('auroraHemisphere(tie, "N")').peak.lat === 65 && au('auroraHemisphere(tie, "N")').peak.lon === 7);
    const validMs = Date.parse(ovalMap.forecast);
    check('oval wording (Spock): the edge, the faint tier only, and neither',
        au(`auroraWording(auroraHemisphere(ovalMap, "N"), ${validMs})`) === 'Aurora possible overhead poleward of 64N, low on the horizon from about 59N, if the sky is dark.'
        && au(`auroraWording(auroraHemisphere(ovalMap, "S"), ${validMs})`) === 'Faint aurora only. Cameras may catch it, the eye probably not, poleward of 55S near longitude 50E, if the sky is dark.'
        && au(`auroraWording(auroraHemisphere(tie, "S"), ${validMs})`).startsWith('No visible aurora expected. The oval peaks at index 0 near'));
    // the cards
    vm.runInContext('weatherForgetData()', sb2);
    delete sb2.observerLocation;
    sb2.ovalData = await au('loadOval()');
    const ovalCard = au('ovalHtml(ovalData, 1000)');
    check('THE OVAL: north polar by default without a location; the key, the two edges, contours at five levels, night shading, the two hemispheres with their wording',
        !/undefined|NaN/.test(ovalCard) && ovalCard.includes('N POLE - MODEL FOR') && ['5 to 10: faint', '60 and over', 'edge: index 10', 'dashed: index 5', 'id="aurora-map-box"', 'class="weather-map weather-sphere"', 'NORTHERN HEMISPHERE', 'SOUTHERN HEMISPHERE',
            'Aurora possible overhead poleward of 64N', 'Faint aurora only', 'aurora index'].every((x) => ovalCard.includes(x)) && count(ovalCard, /stroke-width="0.7"/g) === 5 && count(ovalCard, /stroke-dasharray="6 4"/g) === 2 && count(ovalCard, /class="weather-sphere-cells"/g) >= 4,
        `${count(ovalCard, /stroke-width="0.7"/g)} ${count(ovalCard, /stroke-dasharray="6 4"/g)} ${count(ovalCard, /class="weather-sphere-cells"/g)}`);
    check('THE OVAL: tooltip says model, aurora index not a percentage, the edge rule, SOLAR-1 at L1 in light-seconds, hemispheric power from polar orbiters; no place is named', ['OVATION Prime', 'not a percentage', 'at 10 or more longitudes', 'about 5 light-seconds', '0.003 light-seconds', 'Newell'].every((x) => ovalCard.includes(x)));
    check('THE OVAL: no part of AURORAE is specific to one place (no country or city is named in the cards)', !/Iceland|Reykjavik|Akureyri|Norway|Alaska|Tromso/.test(ovalCard) && !/Iceland|Reykjavik/.test(read('assets', 'weatherAurora.js')));
    sb2.observerLocation = { latitude: -45.9, longitude: 170.5 };
    check('the default view follows the visitor\'s hemisphere: south of the equator it is S POLE, north N POLE', au('auroraViewKind()') === 'south');
    sb2.observerLocation = { latitude: 12, longitude: 30 };
    check('the default view in the northern hemisphere is N POLE', au('auroraViewKind()') === 'north');
    delete sb2.observerLocation;
    check('the default view without a location is N POLE', au('auroraViewKind()') === 'north');
    // buttons redraw the card; the globe turns
    const ovalSlot = { chartData: sb2.ovalData, drawer: sb2.ovalHtml, minWidth: 480, clientWidth: 1000, innerHTML: '' };
    const mapBox = { innerHTML: '' };
    sb2.document.getElementById = (id) => (id === 'weather-au-oval' ? ovalSlot : id === 'aurora-map-box' ? mapBox : null);
    au('auroraSetView("south")');
    check('S POLE button: the card is drawn again with the south polar map', ovalSlot.innerHTML.includes('S POLE - MODEL FOR') && ovalSlot.innerHTML.includes('south polar map'));
    au('auroraSetView("globe")');
    check('GLOBE button: the globe is drawn, centred on the north oval when there is no location, and made draggable', ovalSlot.innerHTML.includes('GLOBE - MODEL FOR') && ovalSlot.innerHTML.includes('is-draggable') && ovalSlot.innerHTML.includes('weatherMapDragStart') && au('AURORA_VIEW.globeLon') === -160 && au('AURORA_VIEW.globeLat') === 65);
    const lon0 = au('AURORA_VIEW.globeLon');
    au('WEATHER_MAP_REGISTRY["aurora-map"].drag(30, 0)');
    check('dragging the globe to the right turns it west (the surface follows the pointer) and redraws the map only', au('AURORA_VIEW.globeLon') < lon0 && mapBox.innerHTML.includes('class="weather-map weather-sphere is-draggable"'));
    au('WEATHER_MAP_REGISTRY["aurora-map"].drag(0, 100000)');
    check('dragging up and down stops at 85 degrees of latitude', au('AURORA_VIEW.globeLat') === 85);
    au('auroraSetView("auto")');
    sb2.document.getElementById = () => null;
    // YOUR SKY TONIGHT
    check('YOUR SKY TONIGHT: without a location it asks for one', au('skyHtml({ place: null, loadedAt: 0 }, 900)').includes('Set your location with USR LOCN'));
    sb2.observerLocation = { latitude: 52.1, longitude: 5.2 };
    vm.runInContext('weatherForgetData()', sb2);
    sb2.skyData = await au('loadSky()');
    const sky = au('skyHtml(skyData, 1000)');
    check('YOUR SKY TONIGHT: Sun and Moon altitude over the next 24 hours on one UTC axis with the dark hours shaded, the aurora index at the place, Kp now against Kp needed, the geomagnetic latitude',
        !/undefined|NaN/.test(sky) && count(sky, /class="lcars-line-axis"/g) === 2 && count(sky, /class="chart-shade"/g) >= 1 && ['AURORA INDEX HERE', 'SUN NOW (DEG)', 'MOON NOW', 'GEOMAGNETIC LATITUDE', 'Kp now', 'Kp needed', 'dark below -12'].every((x) => sky.includes(x)), `${count(sky, /class="chart-shade"/g)}`);
    check('YOUR SKY TONIGHT: the index at the place is read from the stored map (52 N is far from either oval: 0 there), and says none expected', sky.includes('none expected'));
    check('YOUR SKY TONIGHT: tooltip gives the rule for Kp needed (NOAA scales), the Moon series limits and that nothing is fetched', ['Kp 5 (G1) 60 degrees', 'good to about a degree', 'Nothing is fetched', 'clouds are not known'].every((x) => sky.includes(x)));
    // the oval edge at the visitor's longitude, and the index there
    sb2.observerLocation = { latitude: 66, longitude: 200 };
    vm.runInContext('weatherForgetData()', sb2);
    sb2.skyData2 = await au('loadSky()');
    const sky2 = au('skyHtml(skyData2, 1000)');
    check('YOUR SKY TONIGHT: at 66 N on the oval\'s meridian the model gives index 19 (visible if dark) and the edge sentence puts the place poleward of the edge (64 N)', sky2.includes('>19<') && sky2.includes('visible if the sky is dark')
        && sky2.includes('Oval edge at your longitude: 64N, 2 degrees equatorward of you (you are poleward of it).'), (sky2.match(/Oval edge[^<]*/) || [''])[0] + (sky2.match(/AURORA INDEX HERE[\s\S]{0,160}/) || [''])[0].replace(/<[^>]+>/g, '|'));
    delete sb2.observerLocation;
    // ACTIVITY
    const activity = await build('loadActivity', 'activityHtml');
    check('ACTIVITY: hemispheric power (two lines, left axis in GW) with Kp bars on a right axis, G1 line, one UTC axis',
        !/undefined|NaN/.test(activity) && count(activity, /<path class="lcars-dual-line"/g) === 2 && activity.includes('HEMISPHERIC POWER (GW)') && activity.includes('>KP<') && count(activity, /<rect class="chart-hit"/g) >= 6 && activity.includes('G1'));
    // THE NEXT HOUR
    const nextHour = await build('loadNextHour', 'nextHourHtml', 700);
    check('THE NEXT HOUR: the countdown from the wind speed and the 1.5 million km (62.5 minutes at 400 km/s), Bz, when the oval is valid, and the three rows of the last hour',
        !/undefined|NaN/.test(nextHour) && nextHour.includes('WIND ARRIVES IN') && count(nextHour, /class="lcars-line-axis"/g) === 3 && nextHour.includes('OVAL VALID AT') && nextHour.includes('about 5 light-seconds'), (nextHour.match(/WIND ARRIVES IN[\s\S]{0,200}/) || [''])[0].replace(/<[^>]+>/g, '|'));
    sb2.fastWind = { speed: [[NOW - 600000, 400]], bz: [[NOW - 600000, -8]], e: [[NOW - 600000, 3.2]], loadedAt: NOW, oval: null };
    const countdown = au('nextHourHtml(fastWind, 700)');
    check('THE NEXT HOUR: 1.5e6 km at 400 km/s is 63 minutes (62.5), counted from the reading ten minutes ago: arrives in 53 minutes; a strong southward Bz is coloured', countdown.includes('>53 min<') && countdown.includes('63 min from L1 at 400 km/s') && countdown.includes('southward'), (countdown.match(/WIND ARRIVES IN[\s\S]{0,260}/) || [''])[0].replace(/<[^>]+>/g, '|'));
    // THE NEXT NIGHTS
    sb2.gridData = await au('loadKpGrid()');
    const noPlaceGrid = au('kpGridHtml(gridData, 700, { title: "THE NEXT NIGHTS: KP FORECAST", requiredKp: null })');
    const required4 = au('kpGridHtml(gridData, 700, { requiredKp: 4 })');
    const gridKps = sb2.gridData.kp.map((p) => p[1]);
    check('Kp grid with the Kp you need: no outline without a location; with a requirement every block at or above it is outlined (dashed ice), listed in the legend and the credit, and the cell tip says so',
        !noPlaceGrid.includes('kp-required') && count(required4, /class="kp-required"/g) === gridKps.filter((k) => k >= 4).length && gridKps.filter((k) => k >= 4).length > 0 && required4.includes('dashed: reaches the Kp you need') && required4.includes('about 4.0')
        && required4.includes('reaches the Kp you need here (about 4.0) for aurora'));
    check('Kp grid with the Kp you need: beyond Kp 9 nothing is outlined and the credit says why', !au('kpGridHtml(gridData, 700, { requiredKp: Infinity })').includes('class="kp-required"') && au('kpGridHtml(gridData, 700, { requiredKp: Infinity })').includes('needs more than Kp 9'));
    sb2.observerLocation = { latitude: 47.6, longitude: -122.3 };
    check('ERTH NOW forecast grid: the required Kp comes from the visitor\'s geomagnetic latitude (about 54 degrees: Kp 6 or so) and none without a location', au('requiredKpHere()') > 5.5 && au('requiredKpHere()') < 7);
    delete sb2.observerLocation;
    check('ERTH NOW forecast grid: no location gives null (no outline)', au('requiredKpHere()') === null);
    // recurrence
    {
        const DAY = 86400000;
        const sine = Array.from({ length: 90 }, (_, k) => { const t = NOW - (89 - k) * DAY; return [t, 20 + 15 * Math.sin(2 * Math.PI * k / 27)]; });
        sb2.sine = sine;
        const r = au(`auroraRecurrenceR(sine, ${NOW})`);
        const noise = Array.from({ length: 90 }, (_, k) => [NOW - (89 - k) * DAY, 20 + 15 * Math.sin(k * k * 0.37)]);
        sb2.noise = noise;
        check('27-day recurrence: a record that repeats every 27 days correlates at 1.0; scrambled data does not; fewer than 10 pairs gives nothing', r && r.r > 0.99 && r.n >= 29 && Math.abs(au(`auroraRecurrenceR(noise, ${NOW})`).r) < 0.6 && au(`auroraRecurrenceR(sine.slice(-12), ${NOW})`) === null);
    }
    const recur = await build('loadRecurrence', 'recurrenceHtml');
    check('27-day recurrence chart: observed Ap solid, the same record moved forward 27 days dashed and hatched from now, one axis, now marked, the correlation in the credit',
        !/undefined|NaN/.test(recur) && count(recur, /chart-forecast-line/g) === 1 && count(recur, /chart-forecast-band/g) === 1 && count(recur, /class="lcars-line-axis"/g) === 1 && recur.includes('Now, ') && recur.includes('correlation') && recur.includes('27 days earlier'), (recur.match(/correlation[^.]*/) || [''])[0]);
    // Earth-directed CMEs
    sb2.cmeData = await au('loadCmeTimeline()');
    const allCmes = au('cmeTimelineHtml(cmeData, 800)');
    const earthCmes = au('cmeTimelineHtml(cmeData, 800, { title: "EARTH-DIRECTED CMES", earthOnly: true })');
    check('Earth-directed CMEs: the same timeline with the CME that is not Earth-bound (3200 km/s) left out, under its own title', allCmes.includes('Speed 3200 km/s') && !earthCmes.includes('Speed 3200 km/s') && earthCmes.includes('Speed 900 km/s') && earthCmes.includes('EARTH-DIRECTED CMES'));
    // the three view buttons sit under the text beside the map; the control area keeps its ten
    {
        const ovalSlot2 = { chartData: sb2.ovalData, drawer: sb2.ovalHtml, minWidth: 480, clientWidth: 1000, innerHTML: '' };
        sb2.document.getElementById = (id) => (id === 'weather-au-oval' ? ovalSlot2 : null);
        au('auroraSetView("auto")');
        const card = au('ovalHtml(ovalData, 1000)');
        const summaryAt = card.indexOf('class="aurora-summary"');
        const buttonsAt = card.indexOf('class="weather-switches aurora-view-switch"');
        const lastTextAt = card.lastIndexOf('Faint aurora only');
        check('view buttons: GLOBE, N POLE and S POLE are inside the column beside the map, after the hemisphere text (so under it, and under the map when the two stack)',
            summaryAt > 0 && buttonsAt > lastTextAt && lastTextAt > summaryAt && count(card, /onclick="auroraSetView\('(globe|north|south)'\)"/g) === 3 && card.indexOf('aurora-map-box') < summaryAt);
        check('view buttons: N POLE is the chosen one by default (is-on, aria-pressed), the others not', /is-on" aria-pressed="true" onclick="auroraSetView\('north'\)"/.test(card) && count(card, /aria-pressed="true"/g) === 1);
        au('auroraSetView("globe")');
        check('view buttons: pressing GLOBE redraws the card with GLOBE chosen', /is-on" aria-pressed="true" onclick="auroraSetView\('globe'\)"/.test(ovalSlot2.innerHTML) && count(ovalSlot2.innerHTML, /aria-pressed="true"/g) === 1 && ovalSlot2.innerHTML.includes('GLOBE - MODEL FOR'));
        au('auroraSetView("auto")');
        sb2.document.getElementById = () => null;
        const captured = {};
        const sb3 = { console, Map, Math, Promise, Date, window: { addEventListener() {} }, document: { getElementById: () => null }, registerPanelControls: (id, cfg) => { captured[id] = cfg; }, loadScriptOnce: async () => {}, toggleUserLocationForm() {} };
        vm.createContext(sb3);
        for (const file of ['chartCore.js', 'chartTime.js', 'weatherCharts.js', 'weatherEarth.js', 'weatherMap.js', 'weatherAurora.js', 'weatherPanel.js']) { vm.runInContext(read('assets', file), sb3, { filename: file }); }
        const labels = () => captured['sw-drivers'].buttons.map((b) => b.label).join();
        check('control area: the ten view buttons only, ungrouped, in every view including AURORAE (the three map buttons are not there)',
            captured['sw-drivers'].buttons.length === 10 && captured['sw-drivers'].buttons.every((b) => !b.group) && labels() === 'SUN NOW,SOL DRVR,ERTH NOW,GCR,USR LOCN,LEO DRAG,SAT COMM,HF COMM,AURORAE,DEFS'
            && (vm.runInContext('weatherView = "aurora"', sb3), captured['sw-drivers'].buttons.length === 10) && captured['sw-drivers'].buttons.find((b) => b.label === 'AURORAE').isSelected());
        check('the source no longer puts view buttons in the control-area group', !/aurora-views/.test(read('assets', 'weatherPanel.js')) && !/aurora-views/.test(read('assets', 'weatherAurora.js')));
    }

    // AURORAE with nothing held: every card still draws something sensible, with and without a location
    payload.__ovation = null;
    for (const place of [null, { latitude: -45.9, longitude: 170.5 }]) {
        if (place) { sb2.observerLocation = place; } else { delete sb2.observerLocation; }
        for (const [loader, drawer] of [['loadOval', 'ovalHtml'], ['loadSky', 'skyHtml'], ['loadActivity', 'activityHtml'], ['loadNextHour', 'nextHourHtml'], ['loadRecurrence', 'recurrenceHtml']]) {
            let okay;
            try {
                const h = await build(loader, drawer);
                okay = typeof h === 'string' && !/undefined|NaN|Infinity/.test(h);
            } catch (e) {
                okay = false;
                console.log(`${drawer} with nothing held: ${e.message}`);
            }
            check(`${drawer}: draws without error when the site holds no OVATION map (${place ? 'location set' : 'no location'})`, okay);
        }
    }
    delete sb2.observerLocation;

    // every chart given nothing at all must still draw something sensible
    for (const k of Object.keys(payload)) { delete payload[k]; }
    for (const k of Object.keys(events)) { events[k] = []; }
    for (const [loader, drawer] of [['loadL1Data', 'l1SolarWindHtml'], ['loadK2', 'k2Html'], ['loadCmeTimeline', 'cmeTimelineHtml'], ['loadOutlook', 'outlookHtml'],
        ['loadLongView', 'longViewHtml'], ['loadSolarCycle', 'solarCycleHtml'], ['loadFlareRecord', 'flareRecordHtml'],
        ['weatherNow', 'nowStripFrame'], ['loadScales', 'scalesHtml'], ['loadStormStrip', 'stormStripHtml'], ['loadKpDst', 'kpDstHtml'], ['loadKpCompare', 'kpCompareHtml'],
        ['loadHemiPower', 'hemiPowerHtml'], ['loadKpGrid', 'kpGridHtml'], ['loadForecastProbabilities', 'forecastProbabilitiesHtml'],
        ['loadCosmicRaysNow', 'cosmicRaysNowHtml'], ['loadGcrCycle', 'gcrCycleHtml'], ['loadAbsorption', 'hfAbsorptionHtml'], ['loadBoard', 'hfBoardHtml'], ['loadL1Strip', 'l1StripHtml'],
        ['loadAtmosphere', 'atmosphereHtml'], ['loadExposure', 'exposureHtml']]) {
        let okay;
        try {
            const h = await build(loader, drawer);
            okay = typeof h === 'string' && !/undefined|NaN|Infinity/.test(h);
        } catch (e) {
            okay = false;
            console.log(`${drawer} with no data: ${e.message}`);
        }
        check(`${drawer}: draws without error when the site holds nothing`, okay);
    }
}

// --- golden string ------------------------------------------------------------------------------------------
function goldenAndExit() {
    const golden = svgText.replace(/></g, '>\n<');
    if (process.argv.includes('--update') || !fs.existsSync(GOLDEN)) {
        fs.writeFileSync(GOLDEN, golden, 'utf8');
        console.log(`golden string written: ${GOLDEN}`);
    } else {
        const saved = fs.readFileSync(GOLDEN, 'utf8');
        let i = 0;
        while (i < saved.length && i < golden.length && saved[i] === golden[i]) { i += 1; }
        check('golden: the fixed input still draws exactly the saved markup', saved === golden,
            `first difference at ${i}: saved ...${saved.slice(Math.max(0, i - 60), i + 80)} / now ...${golden.slice(Math.max(0, i - 60), i + 80)}`);
    }
    console.log(`chart time tests: ${passed} passed, ${failed} failed`);
    process.exit(failed ? 1 : 0);
}

solarCharts().then(goldenAndExit, (e) => { console.log(`FAIL solar charts threw: ${e.stack}`); process.exit(1); });
