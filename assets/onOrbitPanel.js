/* ==========================================================================
   ON-ORBIT OVERVIEW PANEL -- what is on orbit, by nationality, sector
   (GCAT classes: academic, commercial, civil government, defence),
   orbital inclination and altitude. Lazy-loaded by
   openOnOrbitSection() in lcars.js the first time the ON-ORBIT
   menu button is clicked.

   So far: a control-area table of payloads per CURRENT orbit regime
   (api/on-orbit/regimes) and two main-area charts -- payloads BY
   NATIONALITY (api/on-orbit/nationality) and BY INCLINATION, a vertical-bar
   histogram in 5-degree buckets (api/on-orbit/inclination), both log
   scale -- all precomputed by
   scripts/orbitStats.py from the NORAD catalogue cross-referenced with
   GCAT. Two filter toggles in the control area apply to both. The
   counting rules are written up for readers in assets/onOrbitMethodology.md.

   Not to be confused with the GRD-TRACK map section (section id
   'grd-track', assets/grdTrackPanel.js), which held the ON-ORBIT name and
   this file name until 2026-10-09.
   ========================================================================== */

// The filters. Values match scripts/orbitStats.py's STATUS_FILTERS /
// KIND_FILTERS / SPACEX_FILTERS (and server.py's ON_ORBIT_*_FILTERS); the
// first of each is the default. status and kind apply to every ON-ORBIT
// figure; spacex to every chart (the regime table already shows ALL and
// EXCL SPACEX side by side, and ignores it).
const onOrbitFilters = { status: 'active', kind: 'satellites', spacex: 'with' };

function onOrbitQuery() {
    return `status=${onOrbitFilters.status}&kind=${onOrbitFilters.kind}&spacex=${onOrbitFilters.spacex}`;
}

// Main area: the charts, or (DEFINITIONS button) the static definitions
// and "how it's built" panel in index.html, #on-orbit-definitions.
let onOrbitShowingDefinitions = false;

function applyOnOrbitMainView() {
    const charts = document.getElementById('on-orbit-charts');
    const definitions = document.getElementById('on-orbit-definitions');
    if (charts && definitions) {
        charts.style.display = onOrbitShowingDefinitions ? 'none' : '';
        definitions.style.display = onOrbitShowingDefinitions ? '' : 'none';
    }
    if (onOrbitShowingDefinitions) {
        renderOnOrbitReconciliation();
    }
}

// Back to the charts -- called by openOnOrbitSection() (lcars.js) each time
// the ON-ORBIT menu button is clicked.
function showOnOrbitCharts() {
    onOrbitShowingDefinitions = false;
    applyOnOrbitMainView();
}

// The live part of the definitions page's reconciliation section: every
// total for the CURRENT button settings, and what separates them -- from
// the same endpoints the table and charts use, so the figures always match
// what those show. Re-run whenever the definitions are shown or a button
// changes while they are.
let onOrbitReconciliationSeq = 0;

async function renderOnOrbitReconciliation() {
    const target = document.getElementById('orbit-reconciliation-live');
    if (!target) {
        return;
    }
    const seq = ++onOrbitReconciliationSeq;
    const { status, kind, spacex } = onOrbitFilters;
    const getJson = async (url) => {
        const response = await fetch(url);
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }
        return response.json();
    };
    const populationOf = (s, k) =>
        getJson(`api/on-orbit/nationality?status=${s}&kind=${k}&spacex=${spacex}`).then((d) => d.totalPayloads);
    let html;
    try {
        const otherKind = kind === 'satellites' ? 'spacecraft' : 'satellites';
        const otherStatus = status === 'active' ? 'all' : 'active';
        const [population, otherKindPopulation, otherStatusPopulation, regimes, inclination] = await Promise.all([
            populationOf(status, kind),
            populationOf(status, otherKind),
            populationOf(otherStatus, kind),
            getJson(`api/on-orbit/regimes?status=${status}&kind=${kind}`),
            getJson(`api/on-orbit/inclination?${onOrbitQuery()}`),
        ]);
        // The table row matching the SpaceX button: ALL, or EXCL SPACEX.
        const column = spacex === 'with' ? 'all' : 'exclSpacex';
        const noOrbit = (regimes.rows.find((row) => row.regime === 'unclassified') || {})[column] || 0;
        const tableTotal = regimes.rows
            .filter((row) => row.regime !== 'unclassified')
            .reduce((sum, row) => sum + row[column], 0);
        const inclinationTotal = inclination.buckets.reduce((sum, bucket) => sum + bucket.payloads, 0);
        const format = (n) => n.toLocaleString('en-GB');
        const noun = onOrbitNoun();
        const line = (label, value, cls = '') =>
            `<tr${cls ? ` class="${cls}"` : ''}><td>${label}</td><td>${value}</td></tr>`;
        const signed = (n) => (n > 0 ? `+ ${format(n)}` : n < 0 ? `− ${format(-n)}` : '0');
        html = `
            <p>${onOrbitPopulationLabel()} in orbit:</p>
            <table class="orbit-recon-table">
                ${line('Population = nationality chart total', format(population), 'orbit-recon-key')}
                ${line('less: no current perigee or apogee', `− ${format(noOrbit)}`)}
                ${line(`= Regime table TOTAL (${spacex === 'with' ? 'ALL' : 'EXCL SPACEX'} row)`, format(tableTotal), 'orbit-recon-key')}
                ${line('Population, less: no inclination on file', `− ${format(inclination.noInclination)}`)}
                ${line('= Inclination chart total', format(inclinationTotal), 'orbit-recon-key')}
                ${line(`${kind === 'satellites' ? 'ALL SPACECRAFT' : 'SATELLITES'} instead`,
                       `${format(otherKindPopulation)} (${signed(otherKindPopulation - population)})`)}
                ${line(`${status === 'active' ? 'ACTIVE + INACTIVE' : 'ACTIVE'} instead`,
                       `${format(otherStatusPopulation)} (${signed(otherStatusPopulation - population)})`)}
            </table>
            ${population - noOrbit !== tableTotal || population - inclination.noInclination !== inclinationTotal
                ? '<p class="orbit-recon-warn">THESE DO NOT ADD UP -- THE FIGURES MAY BE MID-REFRESH; RELOAD SHORTLY.</p>'
                : ''}`;
        if (spacex === 'without') {
            html += `<p>(All ${noun} figures here are without SpaceX.)</p>`;
        }
    } catch (error) {
        console.error('Could not load the reconciliation figures:', error);
        html = '<p class="orbit-recon-warn">ERR: COULD NOT LOAD THE FIGURES</p>';
    }
    if (seq === onOrbitReconciliationSeq) {
        target.innerHTML = html;
    }
}

// Re-draws both the control-area table and the main-area chart after a
// filter changes.
function refreshOnOrbitView() {
    renderOnOrbitRegimeTable();
    renderOnOrbitCharts();
    if (onOrbitShowingDefinitions) {
        renderOnOrbitReconciliation();
    }
}

// Control area (left side): payloads in orbit per CURRENT orbit regime --
// columns VLEO, LEO, MEO, GEO, > GEO, HEO and TOTAL; rows ALL and EXCL SPACEX,
// each followed by its % of that row's total. Payloads with no
// current orbit on file aren't placed in a regime; their count is noted
// beside the table instead.
async function renderOnOrbitRegimeTable() {
    const wrapper = document.getElementById('default');
    if (!wrapper) {
        return;
    }
    let rows = [];
    try {
        const response = await fetch(`api/on-orbit/regimes?${onOrbitQuery()}`);
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }
        rows = (await response.json()).rows;
    } catch (error) {
        console.error('Could not load orbit-regime counts:', error);
    }
    // The fetch may resolve after the user has moved to another section.
    if (wrapper.dataset.controlSection !== 'on-orbit') {
        return;
    }
    if (!rows.length) {
        wrapper.innerHTML = '<div class="on-orbit-status">NO ORBIT STATISTICS YET</div>';
        return;
    }
    const format = (n) => n.toLocaleString('en-GB');
    const regimes = rows.filter((row) => row.regime !== 'unclassified');
    const unclassified = rows.find((row) => row.regime === 'unclassified');
    const totalAll = regimes.reduce((sum, row) => sum + row.all, 0);
    const totalExcl = regimes.reduce((sum, row) => sum + row.exclSpacex, 0);
    const percent = (n, total) => (total ? `${((n / total) * 100).toFixed(1)}%` : '—');
    // Regimes run across as columns (TOTAL last); counts and their shares
    // run down as rows -- ALL, %, EXCL SPACEX, % -- each % a share of its
    // own row's TOTAL.
    const columns = [
        ...regimes.map((row) => ({ label: row.regime, all: row.all, excl: row.exclSpacex })),
        { label: 'TOTAL', all: totalAll, excl: totalExcl, total: true },
    ];
    const cell = (column, text) => `<td${column.total ? ' class="orbit-regime-total"' : ''}>${text}</td>`;
    const rowHtml = (label, valueOf) =>
        `<tr><td>${label}</td>${columns.map((column) => cell(column, valueOf(column))).join('')}</tr>`;
    // Same wording as the KIND toggle.
    const heading = onOrbitFilters.kind === 'satellites' ? 'SATELLITES' : 'ALL SPACECRAFT';
    wrapper.innerHTML = `
        <div class="orbit-regime-panel">
            <table class="orbit-regime-table">
                <thead><tr><th>${heading}</th>${columns.map((column) =>
                    `<th${column.total ? ' class="orbit-regime-total"' : ''}>${column.label}</th>`).join('')}</tr></thead>
                <tbody>
                    ${rowHtml('ALL', (column) => format(column.all))}
                    ${rowHtml('%', (column) => percent(column.all, totalAll))}
                    ${rowHtml('EXCL SPACEX', (column) => format(column.excl))}
                    ${rowHtml('%', (column) => percent(column.excl, totalExcl))}
                </tbody>
            </table>
            ${unclassified && unclassified.all
                ? `<div class="orbit-regime-note">+ ${format(unclassified.all)} IN ORBIT WITH NO CURRENT ORBIT ON FILE, NOT INCLUDED</div>`
                : ''}
        </div>`;
}

registerPanelControls('on-orbit', {
    defaultAreaMode: 'custom',
    renderDefaultArea: renderOnOrbitRegimeTable,
    // Laid out 2 x 2 by renderControlAreaButtons(), colours alternating
    // warm/cool in a checkerboard as the news buttons do. The first two are
    // the filter toggles, labelled with their current setting; the third
    // the SpaceX toggle (charts only) and the fourth (bottom right) DEFINITIONS.
    buttons: [
        {
            label: 'STATUS',
            color: 'var(--tng-sand)',
            getText: () => (onOrbitFilters.status === 'active' ? 'ACTIVE' : 'ACTIVE + INACTIVE'),
            onClick: () => {
                onOrbitFilters.status = onOrbitFilters.status === 'active' ? 'all' : 'active';
                refreshOnOrbitView();
            },
        },
        {
            label: 'KIND',
            color: 'var(--tng-periwinkle)',
            getText: () => (onOrbitFilters.kind === 'satellites' ? 'SATELLITES' : 'ALL SPACECRAFT'),
            onClick: () => {
                onOrbitFilters.kind = onOrbitFilters.kind === 'satellites' ? 'spacecraft' : 'satellites';
                refreshOnOrbitView();
            },
        },
        {
            label: 'SPACEX',
            color: 'var(--tng-lavender)',
            getText: () => (onOrbitFilters.spacex === 'with' ? 'WITH SPACEX' : 'W/O SPACEX'),
            onClick: () => {
                onOrbitFilters.spacex = onOrbitFilters.spacex === 'with' ? 'without' : 'with';
                renderOnOrbitCharts();
                if (onOrbitShowingDefinitions) {
                    renderOnOrbitReconciliation();
                }
            },
        },
        {
            // Toggles the main area between the charts and the definitions,
            // labelled with what a click will show: DEFINITIONS while the
            // charts are up, CHARTS while the definitions are.
            label: 'DEFINITIONS',
            color: 'var(--tng-amber)',
            getText: () => (onOrbitShowingDefinitions ? 'CHARTS' : 'DEFINITIONS'),
            onClick: () => {
                onOrbitShowingDefinitions = !onOrbitShowingDefinitions;
                applyOnOrbitMainView();
            },
        },
    ],
});

/* --- Charts ---------------------------------------------------------------- */

// Log-scale axis: from 1 up to the next power of ten above the largest
// value, one tick per power of ten (1, 10, 100 ...). Bars start at 1, so a
// count of 1 is a stub, not a missing bar.
function logAxisTop(maxValue) {
    return 10 ** Math.max(1, Math.ceil(Math.log10(Math.max(maxValue, 1))));
}

function logAxisPercent(value, top) {
    return value <= 1 ? 0 : (Math.log10(value) / Math.log10(top)) * 100;
}

// One LCARS chart panel: a header bar (title, with a total at its end), a
// row per item -- label, bar and the exact count just past the bar's end --
// and a numbered log axis under the bars, its title (axisTitle) just above
// the axis at the right-hand end.
function orbitBarChartHtml(title, totalText, rows, axisTitle) {
    const top = logAxisTop(Math.max(...rows.map((row) => row.value)));
    const ticks = [];
    for (let value = 1; value <= top; value *= 10) {
        ticks.push(value);
    }
    const format = (n) => n.toLocaleString('en-GB');
    const barRows = rows.map((row) => `
        <div class="orbit-chart-label">${row.label}</div>
        <div class="orbit-chart-track">
            <div class="orbit-chart-bar${row.muted ? ' orbit-chart-bar-muted' : ''}"
                 style="width:${logAxisPercent(row.value, top)}%"></div>
            <span class="orbit-chart-value">${format(row.value)}</span>
        </div>`).join('');
    const axis = `
        <div></div>
        <div class="orbit-chart-axis">
            <span class="orbit-chart-axis-title">${axisTitle}</span>${ticks.map((value) => `
            <span class="orbit-chart-tick" style="left:${logAxisPercent(value, top)}%">${format(value)}</span>`).join('')}
        </div>`;
    return `
        <section class="orbit-chart">
            <header class="orbit-chart-header"><span>${title}</span><span>${totalText}</span></header>
            <div class="orbit-chart-grid">${barRows}${axis}</div>
        </section>`;
}

// Pie chart: a disc (conic gradient, slices clockwise from 12 o'clock in
// row order) beside a legend -- swatch, label, count and share for every
// slice, including those too thin to see. totalTooltip as for the
// histogram.
function orbitPieChartHtml(title, totalText, slices, totalTooltip) {
    const total = slices.reduce((sum, slice) => sum + slice.value, 0);
    const format = (n) => n.toLocaleString('en-GB');
    let start = 0;
    const stops = slices.map((slice) => {
        const end = start + (total ? (slice.value / total) * 100 : 0);
        const stop = `${slice.color} ${start}% ${end}%`;
        start = end;
        return stop;
    }).join(', ');
    const legend = slices.map((slice) => `
        <span class="orbit-pie-swatch" style="background:${slice.color}"></span>
        <span class="orbit-pie-label">${slice.label}</span>
        <span class="orbit-pie-value">${format(slice.value)}</span>
        <span class="orbit-pie-value">${total ? ((slice.value / total) * 100).toFixed(1) : '0.0'}%</span>`).join('');
    return `
        <section class="orbit-chart">
            <header class="orbit-chart-header"><span>${title}</span><span${totalTooltip
                ? ` class="orbit-chart-total-tip" title="${totalTooltip}"` : ''}>${totalText}</span></header>
            <div class="orbit-pie">
                <div class="orbit-pie-disc" style="background: conic-gradient(${stops})"></div>
                <div class="orbit-pie-legend">${legend}</div>
            </div>
        </section>`;
}

// Ranked vertical-bar chart (owners): log count axis on the left with
// faint gridlines, one bar per item, largest first, its count above it, and
// the item's name turned 90 degrees under the x axis (reading upwards).
// Each bar's tooltip gives tooltipOf(row); a row's percentText, if given,
// is written up the inside of its bar. Shares the histogram's styles.
function orbitRankedColumnChartHtml(title, totalText, rows, yTitle, totalTooltip, tooltipOf) {
    const top = logAxisTop(Math.max(...rows.map((row) => row.value)));
    const yTicks = [];
    for (let value = 1; value <= top; value *= 10) {
        yTicks.push(value);
    }
    const format = (n) => n.toLocaleString('en-GB');
    const escape = (text) => String(text).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;');
    const columns = rows.map((row) => {
        const height = logAxisPercent(row.value, top);
        return `
            <div class="orbit-histogram-col" title="${escape(tooltipOf(row))}">
                <div class="orbit-histogram-bar${row.muted ? ' orbit-chart-bar-muted' : ''}" style="height:${height}%">${row.percentText
                    ? `<span class="orbit-bar-percent">${row.percentText}</span>` : ''}</div>
                <span class="orbit-histogram-value" style="bottom:${height}%">${format(row.value)}</span>
            </div>`;
    }).join('');
    const labels = rows.map((row) => `
            <div class="orbit-ranked-label" title="${escape(tooltipOf(row))}"><span>${escape(row.label)}</span></div>`).join('');
    return `
        <section class="orbit-chart">
            <header class="orbit-chart-header"><span>${title} · ${yTitle}</span><span${totalTooltip
                ? ` class="orbit-chart-total-tip" title="${escape(totalTooltip)}"` : ''}>${totalText}</span></header>
            <div class="orbit-histogram orbit-ranked">
                <div class="orbit-histogram-yaxis">${yTicks.map((value) => `
                    <span class="orbit-histogram-ytick" style="bottom:${logAxisPercent(value, top)}%">${format(value)}</span>`).join('')}
                </div>
                <div class="orbit-histogram-plot">${yTicks.map((value) => `
                    <div class="orbit-histogram-grid" style="bottom:${logAxisPercent(value, top)}%"></div>`).join('')}
                    ${columns}
                </div>
                <div></div>
                <div class="orbit-ranked-labels">${labels}</div>
            </div>
        </section>`;
}

// Owners chart: the largest OWNERS_CHART_COUNT owners, then Other. A fixed
// number, chosen (October 2026) so that D-Orbit, 38th for active
// satellites, is on the chart; the bars share out the width between them.
const OWNERS_CHART_COUNT = 40;

// Slice colours: LCARS palette, neighbouring slices contrasting.
const ORBIT_REGIME_COLOURS = {
    VLEO: 'var(--tng-sand)', LEO: 'var(--tng-periwinkle)', MEO: 'var(--tng-amber)',
    GEO: 'var(--tng-lavender)', '> GEO': 'var(--tng-salmon)', HEO: 'var(--tng-pink)',
};
const ORBIT_SECTORS = {
    A: { label: 'A – Academic & amateur', color: 'var(--tng-sand)' },
    B: { label: 'B – Commercial', color: 'var(--tng-periwinkle)' },
    C: { label: 'C – Civil government', color: 'var(--tng-amber)' },
    D: { label: 'D – Defence', color: 'var(--tng-lavender)' },
    unknown: { label: 'Unknown', color: 'var(--tng-mauve)' },
};

// Vertical-bar histogram (LCARS: flat bars, pill-rounded tops): a log
// count axis on the left with faint gridlines (its title, yTitle, in the
// header bar after the chart title), one column per bucket with its count just above the bar (blank when
// zero), and an x axis numbered every xTickEvery units under the bucket
// edges, its title (xTitle) just above the axis at the right-hand end.
// totalTooltip, if given, is shown on hovering the total in the header bar.
function orbitColumnChartHtml(title, totalText, buckets, xTitle, yTitle, xTickEvery, totalTooltip) {
    const top = logAxisTop(Math.max(...buckets.map((bucket) => bucket.value)));
    const yTicks = [];
    for (let value = 1; value <= top; value *= 10) {
        yTicks.push(value);
    }
    const format = (n) => n.toLocaleString('en-GB');
    const xFrom = buckets[0].from;
    const xTo = buckets[buckets.length - 1].to;
    const xTicks = [];
    for (let value = xFrom; value <= xTo; value += xTickEvery) {
        xTicks.push(value);
    }
    const xPercent = (value) => ((value - xFrom) / (xTo - xFrom)) * 100;
    const columns = buckets.map((bucket) => {
        const height = logAxisPercent(bucket.value, top);
        return `
            <div class="orbit-histogram-col" title="${bucket.from}–${bucket.to}°: ${format(bucket.value)}">
                ${bucket.value ? `
                <div class="orbit-histogram-bar" style="height:${height}%"></div>
                <span class="orbit-histogram-value" style="bottom:${height}%">${format(bucket.value)}</span>` : ''}
            </div>`;
    }).join('');
    return `
        <section class="orbit-chart">
            <header class="orbit-chart-header"><span>${title} · ${yTitle}</span><span${totalTooltip
                ? ` class="orbit-chart-total-tip" title="${totalTooltip}"` : ''}>${totalText}</span></header>
            <div class="orbit-histogram">
                <div class="orbit-histogram-yaxis">${yTicks.map((value) => `
                    <span class="orbit-histogram-ytick" style="bottom:${logAxisPercent(value, top)}%">${format(value)}</span>`).join('')}
                </div>
                <div class="orbit-histogram-plot">${yTicks.map((value) => `
                    <div class="orbit-histogram-grid" style="bottom:${logAxisPercent(value, top)}%"></div>`).join('')}
                    ${columns}
                </div>
                <div></div>
                <div class="orbit-chart-axis">
                    <span class="orbit-chart-axis-title">${xTitle}</span>${xTicks.map((value) => `
                    <span class="orbit-chart-tick" style="left:${xPercent(value)}%">${value}</span>`).join('')}
                </div>
            </div>
        </section>`;
}

// What the current filters select, in words -- for chart titles.
function onOrbitPopulationLabel() {
    const kind = onOrbitFilters.kind === 'satellites' ? 'satellites' : 'spacecraft';
    const label = onOrbitFilters.status === 'active' ? `Active ${kind}` : `All ${kind}`;
    return onOrbitFilters.spacex === 'with' ? label : `${label} excl SpaceX`;
}

// The main-area charts, in page order. Each loads and renders on its own:
// it gets its own slot in #on-orbit-charts, its own fetch, and its own
// error message, so one chart's data failing doesn't blank the others.
// render(data) returns the chart's HTML, or null when nothing is stored yet.
const ON_ORBIT_CHARTS = [
    {
        // Same counts as the control-area regime table (its ALL row, or EXCL
        // SPACEX with W/O SPACEX on), as a share of the whole.
        key: 'regime-pie',
        title: 'orbit regime',
        group: 'pies',
        endpoint: 'api/on-orbit/regimes',
        render: (data) => {
            if (!data.rows.length) {
                return null;
            }
            const column = onOrbitFilters.spacex === 'with' ? 'all' : 'exclSpacex';
            const format = (n) => n.toLocaleString('en-GB');
            const slices = data.rows
                .filter((row) => row.regime !== 'unclassified')
                .map((row) => ({ label: row.regime, value: row[column], color: ORBIT_REGIME_COLOURS[row.regime] }));
            const total = slices.reduce((sum, slice) => sum + slice.value, 0);
            const noOrbit = (data.rows.find((row) => row.regime === 'unclassified') || {})[column] || 0;
            const tooltip = noOrbit
                ? `Excludes ${format(noOrbit)} ${onOrbitNoun()} with no current perigee or apogee on file, `
                    + 'which cannot be placed in a regime.'
                : '';
            return orbitPieChartHtml(`${onOrbitPopulationLabel()} by orbit type`,
                `${format(total)} ${onOrbitNoun()}`, slices, tooltip);
        },
    },
    {
        key: 'sector-pie',
        title: 'sector',
        group: 'pies',
        endpoint: 'api/on-orbit/sector',
        render: (data) => {
            if (!data.rows.length) {
                return null;
            }
            const slices = data.rows.map((row) => ({
                label: ORBIT_SECTORS[row.sector].label,
                value: row.payloads,
                color: ORBIT_SECTORS[row.sector].color,
            }));
            const total = slices.reduce((sum, slice) => sum + slice.value, 0);
            return orbitPieChartHtml(`${onOrbitPopulationLabel()} by sector (GCAT class)`,
                `${total.toLocaleString('en-GB')} ${onOrbitNoun()}`, slices,
                'GCAT classes each payload by sector: A academic / amateur / non-profit, B commercial, '
                + 'C civil government, D defence. A payload with no class of its own takes its owner\'s. '
                + 'Unknown: not yet in GCAT, or no class recorded.');
        },
    },
    {
        key: 'nationality',
        title: 'nationality',
        endpoint: 'api/on-orbit/nationality',
        render: (data) => {
            if (!data.rows.length) {
                return null;
            }
            const rows = data.rows.map((row) => ({
                label: row.label,
                value: row.payloads,
                muted: row.stateCode === null,   // the "Other" row
            }));
            return orbitBarChartHtml(
                `${onOrbitPopulationLabel()} in orbit by nationality`,
                `${data.totalPayloads.toLocaleString('en-GB')} ${onOrbitNoun()}`,
                rows, `# ${onOrbitNoun()} (LOG SCALE)`);
        },
    },
    {
        key: 'inclination',
        title: 'inclination',
        endpoint: 'api/on-orbit/inclination',
        render: (data) => {
            if (!data.buckets.length) {
                return null;
            }
            const format = (n) => n.toLocaleString('en-GB');
            const buckets = data.buckets.map((bucket) => ({ ...bucket, value: bucket.payloads }));
            const plotted = buckets.reduce((sum, bucket) => sum + bucket.value, 0);
            // On hovering the total: who isn't plotted, and why. These have
            // a perigee and apogee in the catalogue but no published orbital
            // elements, so no inclination -- mostly long-dead satellites in
            // high orbits (old GLONASS, Molniya, Cosmos, early US military)
            // no longer routinely tracked, plus a few recent launches.
            const tooltip = data.noInclination
                ? `Excludes ${format(data.noInclination)} ${onOrbitNoun()} with no inclination on file: `
                    + 'the catalogue gives their perigee and apogee but publishes no current orbital '
                    + 'elements for them. Most are long-dead satellites in high orbits that are no longer '
                    + 'routinely tracked (old GLONASS, Molniya, Cosmos and early US military satellites); '
                    + 'a few are recent launches not yet given elements.'
                : '';
            return orbitColumnChartHtml(
                `${onOrbitPopulationLabel()} in orbit by inclination`,
                `${format(plotted)} ${onOrbitNoun()}`,
                buckets, 'INCLINATION (DEGREES)', `# ${onOrbitNoun()} (LOG SCALE)`, 15, tooltip);
        },
    },
    {
        // At the bottom of the page: the largest OWNERS_CHART_COUNT owners.
        key: 'owners',
        title: 'owners',
        endpoint: 'api/on-orbit/owners',
        render: (data) => {
            if (!data.rows.length) {
                return null;
            }
            const format = (n) => n.toLocaleString('en-GB');
            const noun = onOrbitNoun();
            const population = data.ownedPayloads + data.noOwner;
            // The largest OWNERS_CHART_COUNT owners, then one bar for Other:
            // every owner not shown, plus the payloads with no owner on file
            // -- so the bars add up to the whole population.
            const owners = data.rows.slice(0, OWNERS_CHART_COUNT)
                .map((row) => ({ ...row, value: row.payloads }));
            const shownPayloads = owners.reduce((sum, row) => sum + row.value, 0);
            const otherOwners = data.totalOwners - owners.length;
            const otherOwned = data.ownedPayloads - shownPayloads;
            const other = otherOwned + data.noOwner;
            const bars = other
                ? [...owners, {
                    label: 'Other', value: other, muted: true,
                    fullName: `Other: ${format(otherOwned)} ${noun} of ${format(otherOwners)} smaller owners`
                        + (data.noOwner ? `, plus ${format(data.noOwner)} with no owner on file` : ''),
                }]
                : owners;
            const share = population ? ((shownPayloads / population) * 100).toFixed(1) : '0.0';
            const tooltip = `The ${owners.length} largest of ${format(data.totalOwners)} owners `
                + `hold ${format(shownPayloads)} of ${format(population)} ${noun} (${share}%). `
                + `Other: the remaining ${format(otherOwners)} owners, with ${format(otherOwned)}`
                + (data.noOwner ? `, plus ${format(data.noOwner)} with no owner on file (not yet in GCAT)` : '')
                + '. Owner: the first owner GCAT lists for each payload, as the legal entity it records '
                + '(one company can appear under more than one entity).';
            // Each bar's share of the whole population, written in the bar,
            // to one decimal place.
            bars.forEach((bar) => {
                bar.percentText = `${(population ? (bar.value / population) * 100 : 0).toFixed(1)}%`;
            });
            return orbitRankedColumnChartHtml(
                `${onOrbitPopulationLabel()} by owner`,
                `TOP ${owners.length} OF ${format(data.totalOwners)} OWNERS SHOWN`,
                bars, `# ${noun} (LOG SCALE)`, tooltip,
                (row) => (row.muted ? row.fullName
                    : `${row.fullName || row.label}${row.stateCode ? ` (${row.stateCode})` : ''}: ${format(row.value)} ${noun}`));
        },
    },
];

function onOrbitNoun() {
    return onOrbitFilters.kind === 'satellites' ? 'satellites' : 'spacecraft';
}

// Bumped per chart on every load, so a slow response for an earlier filter
// setting can't overwrite a newer one.
const onOrbitChartLoadSeq = {};

async function renderOnOrbitChart(chart, slot) {
    const seq = (onOrbitChartLoadSeq[chart.key] || 0) + 1;
    onOrbitChartLoadSeq[chart.key] = seq;
    let html;
    try {
        const response = await fetch(`${chart.endpoint}?${onOrbitQuery()}`);
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }
        html = chart.render(await response.json())
            || `<p class="orbit-chart-note">NO ${chart.title.toUpperCase()} STATISTICS YET -- RUN scripts/orbitStats.py</p>`;
    } catch (error) {
        console.error(`Could not load the on-orbit ${chart.title} chart:`, error);
        html = `<p class="orbit-chart-note" style="color: var(--red)">ERR: COULD NOT LOAD ${chart.title.toUpperCase()} CHART DATA</p>`;
    }
    if (onOrbitChartLoadSeq[chart.key] === seq) {
        slot.innerHTML = html;
    }
}

function renderOnOrbitCharts() {
    const container = document.getElementById('on-orbit-charts');
    if (!container) {
        return;
    }
    // One slot per chart, created on first use and kept, so each chart
    // redraws in place without moving the others. Charts sharing a group
    // sit side by side in one row (.orbit-chart-row) -- e.g. the two pies.
    ON_ORBIT_CHARTS.forEach((chart) => {
        let slot = container.querySelector(`[data-chart="${chart.key}"]`);
        if (!slot) {
            let parent = container;
            if (chart.group) {
                parent = container.querySelector(`[data-chart-group="${chart.group}"]`);
                if (!parent) {
                    parent = document.createElement('div');
                    parent.className = 'orbit-chart-row';
                    parent.dataset.chartGroup = chart.group;
                    container.appendChild(parent);
                }
            }
            slot = document.createElement('div');
            slot.dataset.chart = chart.key;
            parent.appendChild(slot);
        }
        renderOnOrbitChart(chart, slot);
    });
}
