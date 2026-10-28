/* Structural check of the chart refactor (no dependencies; run: node 0_tests/chartCompare.js).

   Runs the OLD launchesPanel.js (a saved copy, 0_tests/fixtures/chartsBefore/) and the NEW one (assets/chartCore.js +
   assets/launchesPanel.js) in two sandboxes with a minimal fake DOM, feeds both the same data, filters, year ranges and
   widths, redraws every LAUNCHES chart and compares the HTML/SVG strings in each chart's slot. Also compares the old
   orbitPieChartHtml with the new pieChartHtml.

   Verdicts per string: IDENTICAL; WHITESPACE-ONLY (the same once whitespace between tags and runs of spaces are
   collapsed -- layout in the source, not in the page); DIFFERENT (a failure unless listed in JUSTIFIED below).
   Exit code 0 when there is no unjustified difference. */

const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ROOT = path.resolve(__dirname, '..');
const read = (...parts) => fs.readFileSync(path.join(ROOT, ...parts), 'utf8');

// ---------------------------------------------------------------------------------------------
// A fake DOM that is just enough for the panel: the #launches-charts container with its slots.
function makeSandbox(width) {
    const slots = {};
    const container = {
        clientWidth: width,
        offsetParent: {},
        style: {},
        querySelector(selector) {
            const match = /\[data-chart="([^"]+)"\]/.exec(selector);
            return match ? (slots[match[1]] || null) : null;
        },
        appendChild(slot) { slots[slot.dataset.chart] = slot; },
    };
    const document = {
        getElementById: (id) => (id === 'launches-charts' ? container : null),
        createElement: () => ({ dataset: {}, innerHTML: '' }),
        querySelector: () => null,
    };
    const sandbox = {
        document, console, setTimeout, clearTimeout, slots,
        window: { addEventListener() {} },
        registerPanelControls() {}, loadHelperHtml() {},
    };
    vm.createContext(sandbox);
    return sandbox;
}

function run(sandbox, code, name) {
    return vm.runInContext(code, sandbox, { filename: name });
}

function loadOld(width) {
    const sandbox = makeSandbox(width);
    run(sandbox, read('0_tests', 'fixtures', 'chartsBefore', 'launchesPanel.js'), 'old/launchesPanel.js');
    return sandbox;
}

function loadNew(width) {
    const sandbox = makeSandbox(width);
    run(sandbox, read('assets', 'chartCore.js'), 'assets/chartCore.js');
    run(sandbox, read('assets', 'launchesPanel.js'), 'assets/launchesPanel.js');
    return sandbox;
}

// ---------------------------------------------------------------------------------------------
// Data shaped as server.py's /api/launches/* answer it.
function makeData() {
    const years = [];
    for (let y = 1957; y <= 2026; y += 1) {
        years.push(y);
    }
    const perYear = {
        latestLaunch: '2026-10-23T14:09:00Z',
        rows: years.map((year) => {
            const launches = Math.round(8 + 5 * Math.sin(year / 7) ** 2 * (year - 1950) / 3 + (year > 2018 ? (year - 2018) * 22 : 0));
            return { year: String(year), launches, failures: year % 4 === 0 ? 3 : 0, payloads: Math.round(launches * (1.2 + (year - 1957) / 25)) };
        }),
    };
    const countries = ['US', 'SU', 'RU', 'CN', 'EU', 'J', 'IN', 'NZ', 'other'];
    const byCountry = { rows: [] };
    years.forEach((year, i) => countries.forEach((country, c) => {
        const active = (country === 'SU' ? year < 1992 : country === 'RU' ? year >= 1992 : country === 'NZ' ? year > 2016 : year > 1960 + c * 3);
        byCountry.rows.push({ year: String(year), country, launches: active ? (i * (c + 2)) % 37 + (country === 'US' ? 12 : 0) : 0 });
    }));
    const sectors = ['A', 'B', 'C', 'D', 'unknown'];
    const payloads = { rows: [] };
    years.forEach((year, i) => sectors.forEach((series, s) => payloads.rows.push(
        { year: String(year), series, payloads: year < 1960 ? (s === 4 ? 1 : 0) : ((i * (s + 3)) % 29) * (year > 2015 ? 9 : 1) })));
    const kinds = ['P', 'R', 'D', 'other'];
    const reentries = { rows: [] };
    years.forEach((year, i) => kinds.forEach((kind, k) => reentries.rows.push(
        { year: String(year), kind, objects: year < 1958 ? 0 : ((i * (k + 5)) % 61) + (year > 2019 ? 80 : 0) })));
    return { perYear, byCountry, payloads, reentries };
}

const DATASETS = {
    full: makeData(),
    empty: { perYear: { latestLaunch: null, rows: [] }, byCountry: { rows: [] }, payloads: { rows: [] }, reentries: { rows: [] } },
};

const SCENARIOS = [];
for (const width of [480, 700, 1000, 1500]) {
    for (const spacex of ['with', 'without']) {
        for (const outcome of ['all', 'success']) {
            for (const [fromYear, toYear] of [[null, null], [1990, 2010], [2005, 2026], [1957, 1960], [2026, 2026], [1999, 2000]]) {
                SCENARIOS.push({ dataset: 'full', width, spacex, outcome, fromYear, toYear });
            }
        }
    }
}
SCENARIOS.push({ dataset: 'empty', width: 1000, spacex: 'with', outcome: 'all', fromYear: null, toYear: null });

// ---------------------------------------------------------------------------------------------
function draw(sandbox, scenario) {
    const data = DATASETS[scenario.dataset];
    run(sandbox, `
        launchesPerYearData = ${JSON.stringify(data.perYear)};
        launchesByCountryData = ${JSON.stringify(data.byCountry)};
        payloadsLaunchedData = ${JSON.stringify(data.payloads)};
        reentriesData = ${JSON.stringify(data.reentries)};
        launchesFilters.spacex = ${JSON.stringify(scenario.spacex)};
        launchesFilters.outcome = ${JSON.stringify(scenario.outcome)};
        launchesFilters.fromYear = ${JSON.stringify(scenario.fromYear)};
        launchesFilters.toYear = ${JSON.stringify(scenario.toYear)};
        redrawLaunchCharts();`, 'draw');
    const out = {};
    for (const key of ['per-year', 'payloads-per-launch', 'by-country', 'payloads-launched', 'reentries']) {
        out[key] = sandbox.slots[key] ? sandbox.slots[key].innerHTML : null;
    }
    return out;
}

const normalise = (html) => String(html).replace(/>\s+</g, '><').replace(/\s+/g, ' ').replace(/\s*>\s*/g, '>').replace(/\s*<\s*/g, '<').trim();

// Differences that are intended, with the reason; the check passes on them but prints them.
const JUSTIFIED = [
    // The old pie wrote a tooltip into title="..." unescaped; the shared frame escapes it (& -> &amp;, < -> &lt;, " -> &quot;).
    // The browser shows the same text, and a quote or < in a tooltip can no longer break the page.
    { test: (label, chart) => chart === 'pie' && label.includes('ampersand') },
];

const tally = { identical: 0, whitespace: 0, different: 0, byChart: {} };
const failures = [];
function compare(label, chart, oldHtml, newHtml) {
    const entry = tally.byChart[chart] || (tally.byChart[chart] = { identical: 0, whitespace: 0, different: 0 });
    if (oldHtml === newHtml) {
        tally.identical += 1;
        entry.identical += 1;
    } else if (oldHtml !== null && newHtml !== null && normalise(oldHtml) === normalise(newHtml)) {
        tally.whitespace += 1;
        entry.whitespace += 1;
    } else {
        tally.different += 1;
        entry.different += 1;
        if (!JUSTIFIED.some((j) => j.test(label, chart))) {
            failures.push({ label, chart, old: oldHtml, new: newHtml });
        }
    }
}

for (const scenario of SCENARIOS) {
    const label = JSON.stringify(scenario);
    const before = draw(loadOld(scenario.width), scenario);
    const after = draw(loadNew(scenario.width), scenario);
    for (const chart of Object.keys(before)) {
        compare(label, chart, before[chart], after[chart]);
    }
}

// The pie: the old positional function from onOrbitPanel.js, extracted, against the new config-object one.
function extractFunction(source, name) {
    const start = source.indexOf(`function ${name}(`);
    const end = source.indexOf('\n}\n', start);
    if (start < 0 || end < 0) {
        throw new Error(`cannot find ${name}`);
    }
    return source.slice(start, end + 2);
}
const oldPie = vm.runInNewContext(`${extractFunction(read('0_tests', 'fixtures', 'chartsBefore', 'onOrbitPanel.js'), 'orbitPieChartHtml')}; orbitPieChartHtml`);
const pieSandbox = makeSandbox(900);
run(pieSandbox, read('assets', 'chartCore.js'), 'assets/chartCore.js');
const newPie = run(pieSandbox, 'pieChartHtml', 'pie');
const PIES = [
    ['ON-ORBIT by regime', 'Active satellites', '12,345 SATELLITES', [
        { label: 'VLEO', value: 1200, color: 'var(--tng-sand)' }, { label: 'LEO', value: 9000, color: 'var(--tng-periwinkle)' },
        { label: 'MEO', value: 120, color: 'var(--tng-amber)' }, { label: 'GEO', value: 700, color: 'var(--tng-lavender)' },
        { label: '> GEO', value: 3, color: 'var(--tng-salmon)' }, { label: 'HEO', value: 0, color: 'var(--tng-pink)' }], 'plain tooltip'],
    ['no tooltip', 'Sector', '5 PAYLOADS', [{ label: 'A – Academic & amateur', value: 5, color: 'var(--sector-academic)' }], undefined],
    ['empty pie', 'Nothing', '0', [{ label: 'x', value: 0, color: 'red' }], 'none'],
    ['tooltip with an ampersand', 'Mission', '10', [{ label: 'Signals & EW', value: 10, color: 'blue' }], 'Academic & amateur'],
];
for (const [label, title, totalText, slices, totalTooltip] of PIES) {
    compare(`pie: ${label}`, 'pie', oldPie(title, totalText, slices, totalTooltip), newPie({ title, totalText, slices, totalTooltip }));
}

// ---------------------------------------------------------------------------------------------
console.log('chart comparison, old against new');
for (const [chart, t] of Object.entries(tally.byChart)) {
    console.log(`  ${chart.padEnd(22)} identical ${String(t.identical).padStart(3)}   whitespace-only ${String(t.whitespace).padStart(3)}   different ${String(t.different).padStart(3)}`);
}
console.log(`  total: ${tally.identical} identical, ${tally.whitespace} whitespace-only, ${tally.different} different, `
    + `${SCENARIOS.length} scenarios`);
if (failures.length) {
    console.log(`\n${failures.length} UNJUSTIFIED difference(s); first three:`);
    for (const f of failures.slice(0, 3)) {
        const o = String(f.old);
        const n = String(f.new);
        let i = 0;
        while (i < o.length && i < n.length && o[i] === n[i]) {
            i += 1;
        }
        console.log(`--- ${f.chart} :: ${f.label}\n  old ...${o.slice(Math.max(0, i - 80), i + 120)}\n  new ...${n.slice(Math.max(0, i - 80), i + 120)}`);
    }
    process.exit(1);
}
process.exit(0);
