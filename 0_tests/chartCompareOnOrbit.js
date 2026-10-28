/* Structural check of the chart refactor, phase 2: ON-ORBIT (no dependencies; run: node 0_tests/chartCompareOnOrbit.js).

   Runs the OLD onOrbitPanel.js (a saved copy, 0_tests/fixtures/chartsBefore/) alone and the NEW one on top of
   assets/chartCore.js, each in its own sandbox with a minimal fake DOM, and compares the HTML/SVG strings:
     1. every chart of the panel (ON_ORBIT_CHARTS[...].render) on the same API-shaped data, over four data shapes
        (real-shaped, one row, long/awkward labels, no totals), both SpaceX settings, two kinds and three slot widths;
     2. the migrated helpers called directly, old positional signature against new config object, on edge inputs
        (empty, one row, long labels, with and without totals and tooltips);
     3. the old orbitFrameHtml / orbitStackedColumnsSvg against chartFrameHtml / stackedColumnsSvg in the core.

   Verdicts per string: IDENTICAL; WHITESPACE-ONLY (same once whitespace between tags is collapsed); ESCAPING-ONLY (same
   once &amp; &lt; &quot; are decoded: a hover tooltip in the old code was written raw into title="..." and the shared
   frame escapes it); REORDERED (the same elements in another order: only allowed for the debris-history chart, where
   the shared axis code writes the x ticks before the bars); DIFFERENT (a failure). Exit code 0 when no failure. */

const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ROOT = path.resolve(__dirname, '..');
const read = (...parts) => fs.readFileSync(path.join(ROOT, ...parts), 'utf8');

// ---------------------------------------------------------------------------------------------
function makeSandbox() {
    const document = {
        getElementById: () => null,
        createElement: () => ({ dataset: {}, innerHTML: '' }),
        querySelector: () => null,
    };
    const sandbox = { document, console, setTimeout, clearTimeout, window: { addEventListener() {} },
        registerPanelControls() {}, loadHelperHtml() {} };
    vm.createContext(sandbox);
    return sandbox;
}
const run = (sandbox, code, name) => vm.runInContext(code, sandbox, { filename: name || 'run' });

function loadOld() {
    const sandbox = makeSandbox();
    run(sandbox, read('0_tests', 'fixtures', 'chartsBefore', 'onOrbitPanel.js'), 'old/onOrbitPanel.js');
    return sandbox;
}
function loadNew() {
    const sandbox = makeSandbox();
    run(sandbox, read('assets', 'chartCore.js'), 'assets/chartCore.js');
    run(sandbox, read('assets', 'onOrbitPanel.js'), 'assets/onOrbitPanel.js');
    return sandbox;
}
const OLD = loadOld();
const NEW = loadNew();

// ---------------------------------------------------------------------------------------------
const normalise = (html) => String(html).replace(/>\s+</g, '><').replace(/\s+/g, ' ').replace(/\s*>\s*/g, '>').replace(/\s*<\s*/g, '<').trim();
const decode = (html) => html.replace(/&quot;/g, '"').replace(/&lt;/g, '<').replace(/&amp;/g, '&');
const elements = (html) => normalise(html).split(/(?=<)/).sort().join('\n');

const REORDER_ALLOWED = new Set(['debris-history', 'direct: barsAndLineSvg']);
const tally = { identical: 0, whitespace: 0, escaping: 0, reordered: 0, different: 0, byChart: {} };
const failures = [];
function compare(label, chart, oldHtml, newHtml) {
    const entry = tally.byChart[chart] || (tally.byChart[chart] = { identical: 0, whitespace: 0, escaping: 0, reordered: 0, different: 0 });
    const bump = (kind) => { tally[kind] += 1; entry[kind] += 1; };
    if (/^THREW/.test(String(oldHtml)) || /^THREW/.test(String(newHtml)) || /undefined|NaN/.test(String(newHtml).replace(/<title>[^<]*<\/title>/g, ''))
        && !/undefined|NaN/.test(String(oldHtml).replace(/<title>[^<]*<\/title>/g, ''))) {
        bump('different');
        failures.push({ label, chart, old: oldHtml, new: newHtml });
        return;
    }
    if (oldHtml === newHtml) {
        bump('identical');
        return;
    }
    if (oldHtml === null || newHtml === null || oldHtml === undefined || newHtml === undefined) {
        bump('different');
        failures.push({ label, chart, old: oldHtml, new: newHtml });
        return;
    }
    const o = normalise(oldHtml);
    const n = normalise(newHtml);
    if (o === n) {
        bump('whitespace');
    } else if (normalise(decode(oldHtml)) === normalise(decode(newHtml))) {
        bump('escaping');
    } else if (REORDER_ALLOWED.has(chart) && elements(decode(oldHtml)) === elements(decode(newHtml))) {
        bump('reordered');
    } else {
        bump('different');
        failures.push({ label, chart, old: oldHtml, new: newHtml });
    }
}

// ---------------------------------------------------------------------------------------------
// Data shaped as server.py's /api/on-orbit/* answers.
function rng(seed) {
    let s = seed;
    return () => { s = (s * 1664525 + 1013904223) % 4294967296; return s / 4294967296; };
}
const REGIMES = ['VLEO', 'LEO', 'MEO', 'GEO', '> GEO', 'HEO'];
const SECTORS = ['A', 'B', 'C', 'D', 'unknown'];
const TYPES = ['PAY', 'R/B', 'DEB', 'UNK'];
const BANDS = ['VHF', 'UHF', 'L', 'S', 'X', 'Ku', 'Ka'];
const CATEGORIES = ['COM', 'IMG', 'NAV', 'SIG', 'MET', 'SCI', 'TECH', 'SS', 'other', 'none'];

function makeData(variant) {
    const rand = rng(variant.length * 7919 + 13);
    const n = (max) => Math.floor(rand() * max) + 1;
    const big = variant === 'full' || variant === 'long' || variant === 'zeroTotals';
    const one = variant === 'one';
    const empty = variant === 'empty';
    const long = variant === 'long';
    const zeroTotals = variant === 'zeroTotals';
    const scale = big ? 1 : 0;
    const names = (i) => (long ? `A very long organisation name number ${i} & partners <Ltd> "quoted" with more and more words to wrap` : `Name ${i}`);
    const pickRows = (list) => (empty ? [] : one ? list.slice(0, 1) : list);
    const cross = (a, b, f) => a.flatMap((x) => b.map((y) => f(x, y))).filter((r) => r.n > 0);

    const data = {};
    data['regime-pie'] = { rows: empty ? [] : [...REGIMES, 'unclassified'].map((regime, i) => ({ regime,
        all: one && i ? 0 : n(9000) * (i === 1 ? 2 : 1), exclSpacex: one && i ? 0 : n(3000) * (i === 1 ? 1 : 1) }))
        .map((r) => (zeroTotals && r.regime === 'unclassified' ? { ...r, all: 0, exclSpacex: 0 } : r)) };
    data['active-by-regime'] = { rows: pickRows(cross(REGIMES, [0, 1], (regime, active) => ({ regime, active, n: n(5000) * (active ? 2 : 1) }))) };
    const buckets = Array.from({ length: 12 }, (_, i) => ({ from: i * 15, to: i * 15 + 15, payloads: scale * (i % 4 === 3 ? 0 : n(4000)) + (one && i === 5 ? 1 : 0) }));
    data.inclination = { buckets: empty ? [] : one ? [{ from: 0, to: 15, payloads: 1 }] : buckets, noInclination: zeroTotals ? 0 : 912 };
    data['inclination-by-regime'] = { rows: pickRows(cross(Array.from({ length: 36 }, (_, i) => i * 5), REGIMES, (band, regime) => ({ band, regime, n: rand() < 0.5 ? 0 : n(600) }))) };
    data.altitude = { rows: pickRows(Array.from({ length: 70 }, (_, i) => ({ band: 200 + i * 25, n: n(i % 9 === 0 ? 4000 : 80) }))) };
    data['altitude-vs-inclination'] = { rows: pickRows(Array.from({ length: 150 }, (_, i) => ({ alt: 300 + (i % 60) * 25, inc: (i * 7) % 99, sector: SECTORS[i % 5], n: n(300) }))) };
    data['geo-belt'] = { rows: pickRows(cross(Array.from({ length: 180 }, (_, i) => -180 + i * 2), SECTORS, (band, sector) => ({ band, sector, n: rand() < 0.8 ? 0 : n(40) }))) };
    data.age = { rows: pickRows(cross(Array.from({ length: 31 }, (_, i) => i), REGIMES, (band, regime) => ({ band, regime, n: rand() < 0.4 ? 0 : n(900) }))) };
    data['sector-pie'] = { rows: pickRows(SECTORS.map((sector) => ({ sector, payloads: n(5000) }))) };
    data['mission-pie'] = { rows: pickRows(CATEGORIES.map((category) => ({ category, n: n(3000) }))), total: 12345 };
    data.nationality = { rows: pickRows(Array.from({ length: 15 }, (_, i) => ({ label: i === 14 ? 'Other' : names(i), payloads: n(i === 0 ? 7000 : 300), stateCode: i === 14 ? null : `S${i}` }))), totalPayloads: 14000 };
    const stateNames = Object.fromEntries(Array.from({ length: 20 }, (_, i) => [`S${i}`, names(i)]));
    data['sector-by-country'] = { rows: pickRows(cross(Array.from({ length: 16 }, (_, i) => (i === 15 ? '' : `S${i}`)), SECTORS, (state, sector) => ({ state, sector, n: rand() < 0.3 ? 0 : n(700) }))), total: 54321, stateNames };
    const owners = Array.from({ length: 45 }, (_, i) => ({ label: names(i), fullName: long ? `${names(i)} Inc. & Sons` : `Full owner ${i}`, payloads: Math.max(1, Math.round(5000 / (i + 1))), stateCode: i % 5 ? `S${i % 20}` : null }));
    data.owners = { rows: empty ? [] : one ? owners.slice(0, 1) : owners, ownedPayloads: one ? owners[0].payloads : 20000, noOwner: zeroTotals ? 0 : 800, totalOwners: one ? 1 : 300 };
    data.manufacturers = { rows: pickRows(Array.from({ length: 20 }, (_, i) => ({ name: i % 6 === 5 ? null : names(i), code: `M${i}`, n: Math.max(1, Math.round(3000 / (i + 1))) }))), total: 9000 };
    data.buses = { rows: pickRows(Array.from({ length: 20 }, (_, i) => ({ bus: names(i), n: Math.max(1, Math.round(2000 / (i + 1))) }))), total: 7000 };
    data['payloads-by-year'] = { rows: pickRows(cross(Array.from({ length: 70 }, (_, i) => 1957 + i), SECTORS, (year, sector) => ({ year, sector, n: year < 1960 ? (sector === 'unknown' ? 1 : 0) : rand() < 0.2 ? 0 : n(year > 2015 ? 2500 : 120) }))) };
    data['country-owner-tree'] = { rows: pickRows(Array.from({ length: 60 }, (_, i) => ({ state: i % 7 === 6 ? '' : `S${i % 18}`, ownerName: i % 11 === 10 ? '' : names(i), n: n(500) }))), total: 22222, stateNames };
    data['catalogue-by-type'] = { rows: pickRows(cross(REGIMES, TYPES, (regime, objectType) => ({ regime, objectType, n: rand() < 0.2 ? 0 : n(8000) }))), total: 31000 };
    const years = Array.from({ length: 70 }, (_, i) => 1957 + i);
    data['debris-history'] = { rows: pickRows(years.map((year, i) => ({ year, created: i % 9 === 0 ? 0 : n(year === 2007 ? 3000 : 400), reentered: n(300), inOrbit: 200 + i * 130 + n(50) }))) };
    data['debris-altitude'] = { rows: pickRows(cross(Array.from({ length: 70 }, (_, i) => 200 + i * 25), TYPES, (band, objectType) => ({ band, objectType, n: rand() < 0.4 ? 0 : n(700) }))) };
    data['debris-inclination'] = { rows: pickRows(Array.from({ length: 36 }, (_, i) => ({ band: i * 5, n: n(i % 5 === 0 ? 9000 : 90) }))) };
    data['rocket-bodies-country'] = { rows: pickRows(Array.from({ length: 16 }, (_, i) => ({ state: i === 15 ? '' : `S${i}`, n: n(i === 0 ? 1500 : 60) }))), stateNames };
    data['rocket-bodies-vehicle'] = { rows: pickRows(Array.from({ length: 20 }, (_, i) => ({ vehicle: i === 19 ? '' : names(i), n: n(i === 0 ? 800 : 40) }))) };
    data['debris-origin'] = { rows: pickRows(Array.from({ length: 30 }, (_, i) => ({ parent: i === 29 ? '' : `P${i}`, name: names(i), year: i % 4 ? 1960 + i : null, n: Math.max(1, Math.round(4000 / (i + 1))) }))) };
    data['band-pie'] = { rows: pickRows([...BANDS, 'none'].map((band) => ({ band, n: n(3000) }))), total: 9876 };
    data['band-by-mission'] = { rows: pickRows(cross(BANDS, CATEGORIES, (band, category) => ({ band, category, n: rand() < 0.5 ? 0 : n(500) }))) };
    data['band-by-regime'] = { rows: pickRows(cross(BANDS, REGIMES, (band, regime) => ({ band, regime, n: rand() < 0.4 ? 0 : n(900) }))) };
    return data;
}

const VARIANTS = ['full', 'one', 'long', 'zeroTotals', 'empty'];
const DATA = Object.fromEntries(VARIANTS.map((v) => [v, makeData(v)]));
const KEYS = Object.keys(DATA.full);

// ---------------------------------------------------------------------------------------------
// 1. every chart of the panel through its real render function.
function renderAll(sandbox, variant, filters, width) {
    run(sandbox, `onOrbitFilters.status = ${JSON.stringify(filters.status)}; onOrbitFilters.kind = ${JSON.stringify(filters.kind)};
        onOrbitFilters.spacex = ${JSON.stringify(filters.spacex)};`);
    sandbox.__data = DATA[variant];
    sandbox.__slot = { clientWidth: width };
    const out = {};
    for (const key of KEYS) {
        try {
            out[key] = run(sandbox, `(ON_ORBIT_CHARTS.find((c) => c.key === ${JSON.stringify(key)})).render(__data[${JSON.stringify(key)}], __slot)`);
        } catch (error) {
            out[key] = `THREW: ${error.message}`;
        }
    }
    return out;
}
let scenarios = 0;
const keysInPanel = run(NEW, 'ON_ORBIT_CHARTS.map((c) => c.key)');
const missing = keysInPanel.filter((k) => !KEYS.includes(k));
if (missing.length) {
    throw new Error(`no test data for chart(s): ${missing.join(', ')}`);
}
for (const variant of VARIANTS) {
    for (const spacex of ['with', 'without']) {
        for (const [status, kind] of [['active', 'satellites'], ['all', 'objects']]) {
            for (const width of [320, 700, 1400]) {
                const filters = { status, kind, spacex };
                const before = renderAll(OLD, variant, filters, width);
                const after = renderAll(NEW, variant, filters, width);
                scenarios += 1;
                for (const key of KEYS) {
                    compare(JSON.stringify({ variant, ...filters, width }), key, before[key], after[key]);
                }
            }
        }
    }
}

// ---------------------------------------------------------------------------------------------
// 2. the migrated helpers, old positional call against new config object.
const oldFn = (name) => run(OLD, name);
const newFn = (name) => run(NEW, name);
const longLabel = 'An extremely long label & more <b>"words"</b> '.repeat(4);

function direct(chart, calls) {
    calls.forEach(([label, oldArgs, newArg]) => {
        let before;
        let after;
        try { before = oldFn(chart.old)(...oldArgs); } catch (e) { before = `THREW ${e.message}`; }
        try { after = newFn(chart.new)(newArg); } catch (e) { after = `THREW ${e.message}`; }
        compare(`${chart.new}: ${label}`, `direct: ${chart.new}`, before, after);
    });
}

const rowsOf = (count, f) => Array.from({ length: count }, (_, i) => f(i));
const barSets = {
    'real-shaped': rowsOf(20, (i) => ({ label: `Row ${i}`, value: Math.max(1, Math.round(9000 / (i + 1))) })),
    'one row': [{ label: 'Only', value: 1 }],
    'one big row': [{ label: 'Only', value: 123456 }],
    'long labels, muted': [{ label: longLabel, value: 50 }, { label: 'Other', value: 5, muted: true }],
    'value 0 and 1': [{ label: 'zero', value: 0 }, { label: 'one', value: 1 }, { label: 'ten', value: 10 }, { label: 'hundred', value: 100 }],
};
direct({ old: 'orbitBarChartHtml', new: 'logBarChartHtml' }, Object.entries(barSets).map(([label, rows]) =>
    [label, ['Title & <x>', '12,345 THINGS', rows, '# THINGS (LOG SCALE)'], { title: 'Title & <x>', totalText: '12,345 THINGS', rows, axisTitle: '# THINGS (LOG SCALE)' }]));

const rankedTooltip = (row) => `${row.label} -- "${row.value}" & <more>`;
direct({ old: 'orbitRankedColumnChartHtml', new: 'rankedColumnChartHtml' }, Object.entries(barSets).flatMap(([label, rows]) => [
    [`${label}, tooltip`, ['Owners', 'TOP 40', rows.map((r) => ({ ...r, percentText: '1.5%' })), '# sats (LOG)', 'Total & "tip"', rankedTooltip],
        { title: 'Owners', totalText: 'TOP 40', rows: rows.map((r) => ({ ...r, percentText: '1.5%' })), yTitle: '# sats (LOG)', totalTooltip: 'Total & "tip"', tooltipOf: rankedTooltip }],
    [`${label}, no tooltip, no percent`, ['Owners', 'TOP 40', rows, '# sats (LOG)', undefined, rankedTooltip],
        { title: 'Owners', totalText: 'TOP 40', rows, yTitle: '# sats (LOG)', tooltipOf: rankedTooltip }],
]));

const bucketSets = {
    'real-shaped': rowsOf(12, (i) => ({ from: i * 15, to: i * 15 + 15, value: i % 4 === 3 ? 0 : 10 ** (i % 5) + i })),
    'one bucket': [{ from: 0, to: 15, value: 1 }],
    'all zero': rowsOf(3, (i) => ({ from: i * 15, to: i * 15 + 15, value: 0 })),
    'huge': rowsOf(12, (i) => ({ from: i * 15, to: i * 15 + 15, value: 1e7 + i })),
};
direct({ old: 'orbitColumnChartHtml', new: 'columnHistogramHtml' }, Object.entries(bucketSets).flatMap(([label, buckets]) => [
    [`${label}, tooltip`, ['Inclination', '99 SATS', buckets, 'INCLINATION', '# SATS (LOG)', 15, 'Excludes 5 with none'],
        { title: 'Inclination', totalText: '99 SATS', buckets, xTitle: 'INCLINATION', yTitle: '# SATS (LOG)', xTickEvery: 15, totalTooltip: 'Excludes 5 with none', unit: '°' }],
    [`${label}, no tooltip`, ['Inclination', '99 SATS', buckets, 'INCLINATION', '# SATS (LOG)', 30, ''],
        { title: 'Inclination', totalText: '99 SATS', buckets, xTitle: 'INCLINATION', yTitle: '# SATS (LOG)', xTickEvery: 30, totalTooltip: '', unit: '°' }],
]));

const yearSets = {
    'real-shaped 1957-2026': rowsOf(70, (i) => 1957 + i),
    'one year': [2020],
    'short span 2015-2026': rowsOf(12, (i) => 2015 + i),
    'span with a gap': [1990, 1991, 1995, 2000, 2001],
};
Object.entries(yearSets).forEach(([label, years]) => {
    const sets = {
        'rising': { created: years.map((y, i) => i * 40), inOrbit: years.map((y, i) => 100 + i * 900) },
        'with zeros': { created: years.map((y, i) => (i % 3 ? 0 : 5000)), inOrbit: years.map(() => 0) },
        'all zero': { created: years.map(() => 0), inOrbit: years.map(() => 0) },
        'tiny': { created: years.map(() => 1), inOrbit: years.map(() => 1) },
    };
    Object.entries(sets).forEach(([k, s]) => {
        const tooltipOf = (i) => `${years[i]}: "${s.created[i]}" & <x>`;
        [320, 900, 1500].forEach((width) => {
            const oldArgs = { width, years, bars: { values: s.created, color: 'var(--a)' }, line: { values: s.inOrbit, color: 'var(--b)' }, tooltipOf };
            compare(`barsAndLineSvg: ${label}, ${k}, ${width}`, 'direct: barsAndLineSvg', oldFn('orbitBarsAndLineSvg')(oldArgs), newFn('barsAndLineSvg')(oldArgs));
        });
    });
});

// 3. the frame: old orbitFrameHtml({body}) against chartFrameHtml({svg}).
const legends = { none: undefined, empty: [], some: [{ label: 'Active & "live"', color: 'var(--c1)' }, { label: 'Dead <x>', color: 'var(--c2)' }] };
for (const [lname, legend] of Object.entries(legends)) {
    for (const yTitle of [undefined, '# THINGS']) {
        for (const totalTooltip of [undefined, '', 'Hover & "text" <here>']) {
            const base = { title: 'Title', yTitle, totalText: '5 THINGS', totalTooltip, legend };
            compare(`frame: legend ${lname}, yTitle ${yTitle}, tooltip ${totalTooltip}`, 'direct: chartFrameHtml',
                oldFn('orbitFrameHtml')({ ...base, body: '<p>body</p>' }), newFn('chartFrameHtml')({ ...base, svg: '<p>body</p>' }));
        }
    }
}

// the stacked columns, moved to the core (stackedColumnsSvg).
const stackCases = [];
for (const log of [false, true]) {
    for (const [label, categories] of [['many', Array.from({ length: 36 }, (_, i) => i * 5)], ['one', [0]], ['few', ['A', 'B']]]) {
        for (const centreLabels of [false, true]) {
            stackCases.push({ log, label, categories, centreLabels });
        }
    }
}
stackCases.forEach(({ log, label, categories, centreLabels }) => {
    const series = log ? [{ key: 'n', color: 'var(--p)' }] : [{ key: 'x', label: 'X', color: 'var(--p)' }, { key: 'y', label: 'Y', color: 'var(--q)' }];
    [320, 900].forEach((width) => {
        const args = { width, categories, series, log, centreLabels, xTitle: 'AXIS',
            valueOf: (c, s) => ((String(c).length * 37 + s.key.charCodeAt(0)) % 11) * (log ? 1000 : 3),
            labelOf: (c, i) => (i % 2 ? '' : String(c)), tooltipOf: (c, i, t) => `${c}: "${t}" & <x>` };
        compare(`stackedColumns: ${label}, log ${log}, centre ${centreLabels}, ${width}`, 'direct: stackedColumnsSvg',
            oldFn('orbitStackedColumnsSvg')(args), newFn('stackedColumnsSvg')(args));
    });
});
// the niceAxisStep default: the old orbitNiceStep default was 5 ticks, the shared one 6.
[1, 7, 99, 100, 1234, 56789, 1e6].forEach((v) => compare(`step(${v}, 5)`, 'direct: niceAxisStep(v, 5)', String(oldFn('orbitNiceStep')(v)), String(newFn('niceAxisStep')(v, 5))));

// ---------------------------------------------------------------------------------------------
console.log('ON-ORBIT chart comparison, old against new');
for (const [chart, t] of Object.entries(tally.byChart)) {
    console.log(`  ${chart.padEnd(40)} identical ${String(t.identical).padStart(3)}  whitespace ${String(t.whitespace).padStart(3)}  `
        + `escaping ${String(t.escaping).padStart(3)}  reordered ${String(t.reordered).padStart(3)}  different ${String(t.different).padStart(3)}`);
}
console.log(`  total: ${tally.identical} identical, ${tally.whitespace} whitespace-only, ${tally.escaping} escaping-only, `
    + `${tally.reordered} reordered, ${tally.different} different; ${scenarios} panel scenarios x ${KEYS.length} charts`);
if (failures.length) {
    console.log(`\n${failures.length} UNJUSTIFIED difference(s); first five:`);
    for (const f of failures.slice(0, 5)) {
        const o = String(f.old);
        const n = String(f.new);
        let i = 0;
        while (i < o.length && i < n.length && o[i] === n[i]) {
            i += 1;
        }
        console.log(`--- ${f.chart} :: ${f.label}\n  old ...${o.slice(Math.max(0, i - 100), i + 160)}\n  new ...${n.slice(Math.max(0, i - 100), i + 160)}`);
    }
    process.exit(1);
}
process.exit(0);
