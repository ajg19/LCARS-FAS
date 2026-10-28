/* ==========================================================================
   ON-ORBIT OVERVIEW PANEL -- what is on orbit, by nationality, sector
   (GCAT classes: academic, commercial, civil government, defence),
   orbital inclination and altitude. Lazy-loaded by
   openOnOrbitSection() in lcars.js the first time the ON-ORBIT
   menu button is clicked.

   A control-area table of payloads per CURRENT orbit regime
   (api/on-orbit/regimes), filter buttons, and charts in four groups chosen
   by the second button group -- LOCN (what is where), COMMERCIAL (who owns
   it), DEBRIS (where it is, what broke up) and COMMS (radio bands). The
   main area shows one group at a time; LOCN on opening. Some charts are
   precomputed by scripts/orbitStats.py (api/on-orbit/<chart>), the rest
   counted on request from its per-object table (api/on-orbit/chart?name=).
   The counting rules are written up for readers in
   assets/onOrbitMethodology.md and on the DEFS page.

   Not to be confused with the GRD-TRACK map section (section id
   'grd-track', assets/grdTrackPanel.js), which held the ON-ORBIT name and
   this file name until 2026-10-09.
   ========================================================================== */

// The filters. Values match scripts/orbitStats.py's STATUS_FILTERS /
// KIND_FILTERS / SPACEX_FILTERS (and server.py's ON_ORBIT_*_FILTERS); the
// first of each is the default (kind has three: satellites, spacecraft,
// objects). status and kind apply to every ON-ORBIT
// figure; spacex to every chart (the regime table already shows ALL and
// EXCL SPACEX side by side, and ignores it).
const onOrbitFilters = { status: 'active', kind: 'satellites', spacex: 'with' };

// KIND, a three-way toggle: the order clicks cycle through, the button's
// text, and the noun the charts use for each.
const ON_ORBIT_KINDS = ['satellites', 'spacecraft', 'objects'];
const ON_ORBIT_KIND_LABELS = { satellites: 'SATELLITES', spacecraft: 'ALL SPACECRAFT', objects: 'ALL OBJECTS' };
const ON_ORBIT_KIND_NOUNS = { satellites: 'satellites', spacecraft: 'spacecraft', objects: 'objects' };
// Short (Okudagram-style) button texts; ON_ORBIT_KIND_LABELS stays for the
// regime table's heading.
const ON_ORBIT_KIND_BUTTONS = { satellites: 'SAT ONLY', spacecraft: 'ALL S-CRFT', objects: 'ALL-OBJ' };
const ON_ORBIT_STATUS_BUTTONS = { active: 'ACT-ONLY', all: 'ACT +DEAD' };

function onOrbitQuery() {
    return `status=${onOrbitFilters.status}&kind=${onOrbitFilters.kind}&spacex=${onOrbitFilters.spacex}`;
}

// Main area: the charts, or (DEFINITIONS button) the static definitions
// and "how it's built" panel, #on-orbit-definitions, whose contents are the
// helper file assets/onOrbitDefs.html (fetched the first time it is shown).
let onOrbitShowingDefinitions = false;

async function applyOnOrbitMainView() {
    const charts = document.getElementById('on-orbit-charts');
    const definitions = document.getElementById('on-orbit-definitions');
    if (onOrbitShowingDefinitions) {
        await loadHelperHtml('assets/onOrbitDefs.html', 'on-orbit-definitions');
    }
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
        const otherKinds = ON_ORBIT_KINDS.filter((k) => k !== kind);
        const otherStatus = status === 'active' ? 'all' : 'active';
        const [population, otherKindPopulations, otherStatusPopulation, regimes, inclination] = await Promise.all([
            populationOf(status, kind),
            Promise.all(otherKinds.map((k) => populationOf(status, k))),
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
                ${otherKinds.map((k, i) => line(`${ON_ORBIT_KIND_BUTTONS[k]} instead`,
                       `${format(otherKindPopulations[i])} (${signed(otherKindPopulations[i] - population)})`)).join('')}
                ${line(`${ON_ORBIT_STATUS_BUTTONS[otherStatus]} instead`,
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
// current orbit on file aren't placed in a regime (their count is in the
// orbit-type pie's tooltip and the DEFINITIONS page's reconciliation).
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
    const heading = ON_ORBIT_KIND_LABELS[onOrbitFilters.kind];
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
            getText: () => ON_ORBIT_STATUS_BUTTONS[onOrbitFilters.status],
            onClick: () => {
                onOrbitFilters.status = onOrbitFilters.status === 'active' ? 'all' : 'active';
                refreshOnOrbitView();
            },
        },
        {
            label: 'KIND',
            color: 'var(--tng-periwinkle)',
            // Three-way: SATELLITES -> ALL SPACECRAFT -> ALL OBJECTS -> ...
            getText: () => ON_ORBIT_KIND_BUTTONS[onOrbitFilters.kind],
            onClick: () => {
                const next = (ON_ORBIT_KINDS.indexOf(onOrbitFilters.kind) + 1) % ON_ORBIT_KINDS.length;
                onOrbitFilters.kind = ON_ORBIT_KINDS[next];
                refreshOnOrbitView();
            },
        },
        {
            label: 'SPACEX',
            color: 'var(--tng-lavender)',
            getText: () => (onOrbitFilters.spacex === 'with' ? 'INC SPACEX' : 'EX SPACEX'),
            onClick: () => {
                onOrbitFilters.spacex = onOrbitFilters.spacex === 'with' ? 'without' : 'with';
                renderOnOrbitCharts();
                if (onOrbitShowingDefinitions) {
                    renderOnOrbitReconciliation();
                }
            },
        },
        // The chart-group buttons: a second 2 x 2 group, to the left of the
        // four above (grouped buttons render into #control-area-groups,
        // beside nav) -- LOCN over DEBRIS, COMMERCIAL over COMMS. The group
        // showing is lit LCARS white.
        {
            label: 'LOCN', color: 'var(--tng-tan)', group: 'on-orbit-extra-1',
            isSelected: () => onOrbitGroup === 'locn',
            onClick: () => selectOnOrbitGroup('locn'),
        },
        {
            label: 'COMMERCIAL', color: 'var(--tng-ice)', group: 'on-orbit-extra-2',
            isSelected: () => onOrbitGroup === 'commercial',
            onClick: () => selectOnOrbitGroup('commercial'),
        },
        {
            label: 'DEBRIS', color: 'var(--tng-periwinkle)', group: 'on-orbit-extra-1',
            isSelected: () => onOrbitGroup === 'debris',
            onClick: () => selectOnOrbitGroup('debris'),
        },
        {
            label: 'COMMS', color: 'var(--tng-salmon)', group: 'on-orbit-extra-2',
            isSelected: () => onOrbitGroup === 'comms',
            onClick: () => selectOnOrbitGroup('comms'),
        },
        {
            // Toggles the main area between the charts and the definitions,
            // labelled with what a click will show: DEFINITIONS while the
            // charts are up, CHARTS while the definitions are.
            label: 'DEFINITIONS',
            color: 'var(--tng-amber)',
            getText: () => (onOrbitShowingDefinitions ? 'CHARTS' : 'DEFS'),
            onClick: () => {
                onOrbitShowingDefinitions = !onOrbitShowingDefinitions;
                applyOnOrbitMainView();
            },
        },
    ],
});

/* --- Charts ---------------------------------------------------------------- */

// Owners chart: the largest OWNERS_CHART_COUNT owners, then Other. A fixed
// number, chosen (October 2026) so that D-Orbit, 38th for active
// satellites, is on the chart; the bars share out the width between them.
const OWNERS_CHART_COUNT = 40;

// Slice colours: LCARS palette, neighbouring slices contrasting.
const ORBIT_REGIME_COLOURS = {
    VLEO: 'var(--tng-sand)', LEO: 'var(--tng-periwinkle)', MEO: 'var(--tng-amber)',
    GEO: 'var(--tng-lavender)', '> GEO': 'var(--tng-salmon)', HEO: 'var(--tng-pink)',
};
// Sector colours: the --sector-* tokens in classic.css, used for every
// sector chart site-wide.
const ORBIT_SECTORS = {
    A: { label: 'A – Academic & amateur', color: 'var(--sector-academic)' },
    B: { label: 'B – Commercial', color: 'var(--sector-commercial)' },
    C: { label: 'C – Civil government', color: 'var(--sector-civil)' },
    D: { label: 'D – Defence', color: 'var(--sector-defence)' },
    unknown: { label: 'Unknown', color: 'var(--sector-unknown)' },
};

// What the current filters select, in words -- for chart titles.
function onOrbitPopulationLabel() {
    const kind = onOrbitNoun();
    const label = onOrbitFilters.status === 'active' ? `Active ${kind}` : `All ${kind}`;
    return onOrbitFilters.spacex === 'with' ? label : `${label} excl SpaceX`;
}

// --- Chart groups -----------------------------------------------------------------
// The main area shows one group's charts at a time, chosen by the group
// buttons; LOCN when ON-ORBIT first opens. Kept between visits.
let onOrbitGroup = 'locn';

function selectOnOrbitGroup(group) {
    onOrbitGroup = group;
    if (onOrbitShowingDefinitions) {
        onOrbitShowingDefinitions = false;
        applyOnOrbitMainView();
    }
    renderOnOrbitCharts();
}

// --- SVG chart helpers (sized to their slot) ----------------------------------------
const ORBIT_SVG_MARGIN = { top: 16, right: 24, bottom: 34, left: 60 };

// Width available to a chart: its slot's width (a half-row slot is half).
function orbitSlotWidth(slot) {
    return Math.max(320, (slot && slot.clientWidth) || 900);
}

const ORBIT_REGIME_ORDER = ['VLEO', 'LEO', 'MEO', 'GEO', '> GEO', 'HEO'];
const ORBIT_SECTOR_ORDER = ['A', 'B', 'C', 'D', 'unknown'];
const ORBIT_SECTOR_SHORT = { A: 'Academic', B: 'Commercial', C: 'Civil', D: 'Defence', unknown: 'Unknown' };
const ORBIT_MISSIONS = {
    COM: { label: 'Communications', color: 'var(--tng-periwinkle)' },
    IMG: { label: 'Imaging', color: 'var(--tng-amber)' },
    NAV: { label: 'Navigation', color: 'var(--tng-lavender)' },
    SIG: { label: 'Signals & EW', color: 'var(--sector-defence)' },
    MET: { label: 'Weather & Earth science', color: 'var(--tng-ice)' },
    SCI: { label: 'Science & astronomy', color: 'var(--tng-sand)' },
    TECH: { label: 'Technology demo', color: 'var(--tng-tan)' },
    SS: { label: 'Crewed & stations', color: 'var(--tng-pink)' },
    other: { label: 'Other', color: 'var(--tng-salmon)' },
    none: { label: 'No category / not a payload', color: 'var(--tng-mauve)' },
};

function orbitFormat(n) {
    return Number(n).toLocaleString('en-GB');
}

function orbitLongitudeLabel(lon) {
    if (lon === 0 || lon === -180) {
        return lon === 0 ? '0°' : '180°';
    }
    return lon < 0 ? `${-lon}°W` : `${lon}°E`;
}

// Object types (as the LAUNCHES re-entries chart) and downlink bands.
const ORBIT_OBJECT_TYPES = [
    { key: 'PAY', label: 'Payloads', color: 'var(--tng-periwinkle)' },
    { key: 'R/B', label: 'Rocket bodies', color: 'var(--tng-amber)' },
    { key: 'DEB', label: 'Debris', color: 'var(--tng-lavender)' },
    { key: 'UNK', label: 'Unknown', color: 'var(--tng-mauve)' },
];
const ORBIT_BANDS = [
    { key: 'VHF', color: 'var(--tng-tan)' }, { key: 'UHF', color: 'var(--tng-sand)' },
    { key: 'L', color: 'var(--tng-ice)' }, { key: 'S', color: 'var(--tng-salmon)' },
    { key: 'X', color: 'var(--tng-amber)' }, { key: 'Ku', color: 'var(--tng-periwinkle)' },
    { key: 'Ka', color: 'var(--tng-lavender)' },
];

// How a band is written: UHF and VHF on their own, the rest "X band" etc.;
// Ku and Ka always with a lower-case u / a -- in HTML (asHtml) wrapped so
// the uppercase LCARS styling can't capitalise them.
function orbitBandText(key, asHtml = false) {
    const name = asHtml && /^K[ua]$/.test(key) ? `<span class="keep-case">${key}</span>` : key;
    return key === 'UHF' || key === 'VHF' ? name : `${name} band`;
}

// "Everything in orbit" label for the DEBRIS charts, which count every
// object whatever the status and kind buttons say.
function onOrbitEverythingLabel() {
    return onOrbitFilters.spacex === 'with' ? 'All objects' : 'All objects excl SpaceX';
}

// Country -> owner tree, drawn like a Unix/DOS directory listing: amber
// branch lines, names in sand, counts in blue with a small bar. Countries
// are click-to-open (<details>); the first three start open.
function orbitTreeHtml({ rootLabel, rootTotal, countries, ownersShown = 6, countriesShown = 15 }) {
    const bar = (n) => `<span class="orbit-tree-bar" style="width:${Math.max(1, (n / rootTotal) * 100)}%"></span>`;
    const line = (label, n, cls = '') => `<span class="orbit-tree-row ${cls}"><span class="orbit-tree-name">${escapeChartText(label)}</span>`
        + `<span class="orbit-tree-leader"></span><span class="orbit-tree-count">${orbitFormat(n)}</span>`
        + `<span class="orbit-tree-barbox">${bar(n)}</span></span>`;
    const shown = countries.slice(0, countriesShown);
    const rest = countries.slice(countriesShown);
    const items = shown.map((c, i) => {
        const owners = c.owners.slice(0, ownersShown);
        const more = c.owners.slice(ownersShown);
        const ownerItems = owners.map((o) => `<li>${line(o.name, o.n)}</li>`).join('')
            + (more.length ? `<li>${line(`… ${more.length} more owner${more.length === 1 ? '' : 's'}`,
                more.reduce((a, o) => a + o.n, 0), 'is-more')}</li>` : '');
        return `<li><details${i < 3 ? ' open' : ''}><summary>${line(c.name, c.n, 'is-country')}</summary>`
            + `<ul>${ownerItems}</ul></details></li>`;
    }).join('') + (rest.length ? `<li>${line(`… ${rest.length} more countries`,
        rest.reduce((a, c) => a + c.n, 0), 'is-more')}</li>` : '');
    return `<div class="orbit-tree">${line(rootLabel, rootTotal, 'is-root')}<ul>${items}</ul></div>`;
}

// The main-area charts, in page order within each group. Each loads and
// renders on its own: its own slot in #on-orbit-charts, its own fetch, its
// own error message. render(data, slot) returns the chart's HTML, or null
// when nothing is stored yet. row: charts sharing one sit side by side.
// endpoint: a precomputed figure (api/on-orbit/<chart>) or a chart counted
// on request (api/on-orbit/chart?name=<chart>).
const ON_ORBIT_CHARTS = [
    // ===== LOCN -- what is where ======================================================
    {
        // Same counts as the control-area regime table (its ALL row, or EXCL
        // SPACEX with EX SPACEX on), as a share of the whole.
        key: 'regime-pie',
        section: 'locn',
        title: 'orbit regime',
        row: 'locn-top',
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
            return pieChartHtml({
                title: `${onOrbitPopulationLabel()} by orbit type`,
                totalText: `${format(total)} ${onOrbitNoun()}`, slices, totalTooltip: tooltip,
            });
        },
    },
    {
        // Ignores ACT-ONLY: the point is active against dead.
        key: 'active-by-regime',
        section: 'locn',
        title: 'active by regime',
        row: 'locn-top',
        endpoint: 'api/on-orbit/chart?name=active-by-regime',
        render: (data, slot) => {
            if (!data.rows.length) {
                return null;
            }
            const counts = {};
            data.rows.forEach((r) => { counts[`${r.regime}|${r.active}`] = r.n; });
            const regimes = ORBIT_REGIME_ORDER.filter((g) => counts[`${g}|1`] || counts[`${g}|0`]);
            const series = [
                { key: 1, label: 'Active', color: 'var(--tng-periwinkle)' },
                { key: 0, label: 'Inactive', color: 'var(--tng-mauve)' },
            ];
            const dead = data.rows.filter((r) => !r.active).reduce((s, r) => s + r.n, 0);
            const all = data.rows.reduce((s, r) => s + r.n, 0);
            const kind = onOrbitNoun();
            const label = onOrbitFilters.spacex === 'with' ? `All ${kind}` : `All ${kind} excl SpaceX`;
            return chartFrameHtml({
                title: `${label}: active vs inactive by orbit type`,
                yTitle: `# ${kind}`,
                totalText: `${(all ? (dead / all) * 100 : 0).toFixed(1)}% INACTIVE`,
                totalTooltip: `Active or not by CelesTrak's active list, for every ${kind.replace(/s$/, '')} in orbit `
                    + '(this chart ignores the ACT-ONLY button: it compares the two).',
                legend: series,
                svg: stackedColumnsSvg({
                    width: orbitSlotWidth(slot), height: 300, categories: regimes, series,
                    valueOf: (g, s) => counts[`${g}|${s.key}`] || 0,
                    labelOf: (g) => g,
                    centreLabels: true,
                    tooltipOf: (g, i, t) => `${g}: ${orbitFormat(t)} -- ${orbitFormat(counts[`${g}|1`] || 0)} active, `
                        + `${orbitFormat(counts[`${g}|0`] || 0)} inactive (${t ? (((counts[`${g}|0`] || 0) / t) * 100).toFixed(1) : 0}%)`,
                }),
            });
        },
    },
    {
        key: 'inclination',
        section: 'locn',
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
            return columnHistogramHtml({
                title: `${onOrbitPopulationLabel()} in orbit by inclination`,
                yTitle: `# ${onOrbitNoun()} (LOG SCALE)`,
                xTitle: 'INCLINATION (DEGREES)',
                totalText: `${format(plotted)} ${onOrbitNoun()}`,
                totalTooltip: tooltip,
                buckets, xTickEvery: 15, unit: '°',
            });
        },
    },
    {
        key: 'inclination-by-regime',
        section: 'locn',
        title: 'inclination by orbit type',
        endpoint: 'api/on-orbit/chart?name=inclination-by-regime',
        render: (data, slot) => {
            if (!data.rows.length) {
                return null;
            }
            const counts = {};
            data.rows.forEach((r) => { counts[`${r.band}|${r.regime}`] = r.n; });
            const bands = Array.from({ length: 36 }, (_, i) => i * 5);
            const series = ORBIT_REGIME_ORDER.map((g) => ({ key: g, label: g, color: ORBIT_REGIME_COLOURS[g] }));
            const plotted = data.rows.reduce((s, r) => s + r.n, 0);
            return chartFrameHtml({
                title: `${onOrbitPopulationLabel()} by inclination and orbit type`,
                yTitle: `# ${onOrbitNoun()}`,
                totalText: `${orbitFormat(plotted)} ${onOrbitNoun()}`,
                totalTooltip: 'Current inclination in 5° bands, each band stacked by orbit type. Objects with no '
                    + 'inclination or no current orbit on file are not included.',
                legend: series,
                svg: stackedColumnsSvg({
                    width: orbitSlotWidth(slot), categories: bands, series,
                    valueOf: (b, s) => counts[`${b}|${s.key}`] || 0,
                    labelOf: (b) => (b % 15 === 0 ? `${b}°` : ''),
                    xTitle: 'INCLINATION',
                    tooltipOf: (b, i, t) => `${b}–${b + 5}°: ${orbitFormat(t)}\n`
                        + series.map((s) => `${s.label}: ${orbitFormat(counts[`${b}|${s.key}`] || 0)}`).join('\n'),
                }),
            });
        },
    },
    {
        key: 'altitude',
        section: 'locn',
        title: 'altitude',
        endpoint: 'api/on-orbit/chart?name=altitude',
        render: (data, slot) => {
            if (!data.rows.length) {
                return null;
            }
            const counts = {};
            data.rows.forEach((r) => { counts[r.band] = r.n; });
            const first = Math.min(...data.rows.map((r) => r.band));
            const bands = [];
            for (let b = Math.floor(first / 100) * 100; b < 2000; b += 25) {
                bands.push(b);
            }
            const plotted = data.rows.reduce((s, r) => s + r.n, 0);
            return chartFrameHtml({
                title: `${onOrbitPopulationLabel()} below 2,000 km by altitude`,
                yTitle: `# ${onOrbitNoun()} (LOG SCALE)`,
                totalText: `${orbitFormat(plotted)} ${onOrbitNoun()}`,
                totalTooltip: 'Mean altitude ((perigee + apogee) / 2) in 25 km bands, for objects in VLEO and '
                    + 'LEO -- below 2,000 km. The tall bars are constellation shells.',
                svg: stackedColumnsSvg({
                    width: orbitSlotWidth(slot), categories: bands, log: true,
                    series: [{ key: 'n', color: 'var(--tng-periwinkle)' }],
                    valueOf: (b) => counts[b] || 0,
                    labelOf: (b) => (b % 250 === 0 ? `${orbitFormat(b)}` : ''),
                    xTitle: 'MEAN ALTITUDE (KM)',
                    tooltipOf: (b) => `${orbitFormat(b)}–${orbitFormat(b + 25)} km: ${orbitFormat(counts[b] || 0)}`,
                }),
            });
        },
    },
    {
        key: 'altitude-vs-inclination',
        section: 'locn',
        title: 'altitude vs inclination',
        endpoint: 'api/on-orbit/chart?name=altitude-vs-inclination',
        render: (data, slot) => {
            if (!data.rows.length) {
                return null;
            }
            // One dot per 25 km x 1 degree cell, its area proportional to the
            // count, coloured by the sector with most objects in the cell.
            const cells = {};
            data.rows.forEach((r) => {
                const key = `${r.alt}|${r.inc}`;
                const cell = cells[key] || (cells[key] = { alt: r.alt, inc: r.inc, n: 0, bySector: {} });
                cell.n += r.n;
                cell.bySector[r.sector] = (cell.bySector[r.sector] || 0) + r.n;
            });
            const list = Object.values(cells);
            const width = orbitSlotWidth(slot);
            const height = 440;
            const m = ORBIT_SVG_MARGIN;
            const plotW = width - m.left - m.right;
            const plotH = height - m.top - m.bottom;
            const sx = (inc) => m.left + (inc / 180) * plotW;
            const sy = (alt) => m.top + plotH - ((alt - 150) / (2000 - 150)) * plotH;
            const maxN = Math.max(...list.map((c) => c.n));
            const radius = (n) => 1.5 + Math.sqrt(n / maxN) * 14;
            let svg = '';
            for (let alt = 250; alt <= 2000; alt += 250) {
                svg += `<line class="lcars-line-grid" x1="${m.left}" x2="${m.left + plotW}" y1="${sy(alt)}" y2="${sy(alt)}"></line>
                    <text class="lcars-line-ytick" x="${m.left - 8}" y="${sy(alt)}" dy="0.35em" text-anchor="end">${orbitFormat(alt)}</text>`;
            }
            svg += `<line class="lcars-line-axis" x1="${m.left}" x2="${m.left + plotW}" y1="${m.top + plotH}" y2="${m.top + plotH}"></line>`;
            for (let inc = 0; inc <= 180; inc += 15) {
                svg += `<line class="lcars-line-xtick-mark" x1="${sx(inc)}" x2="${sx(inc)}" y1="${m.top + plotH}" y2="${m.top + plotH + 5}"></line>
                    <text class="lcars-line-xtick" x="${sx(inc)}" y="${m.top + plotH + 20}" text-anchor="middle">${inc}°</text>`;
            }
            svg += `<text class="lcars-line-axis-title" x="${m.left + plotW}" y="${m.top + plotH - 8}" text-anchor="end">INCLINATION</text>`;
            list.sort((a, b) => b.n - a.n).forEach((c) => {
                const top = Object.entries(c.bySector).sort((a, b) => b[1] - a[1])[0][0];
                const tip = `${orbitFormat(c.alt)}–${orbitFormat(c.alt + 25)} km, ${c.inc}–${c.inc + 1}°: ${orbitFormat(c.n)}\n`
                    + ORBIT_SECTOR_ORDER.filter((k) => c.bySector[k]).map((k) => `${ORBIT_SECTOR_SHORT[k]}: ${orbitFormat(c.bySector[k])}`).join('\n');
                svg += `<circle class="lcars-bubble" cx="${sx(c.inc + 0.5)}" cy="${sy(c.alt + 12.5)}" r="${radius(c.n)}" fill="${ORBIT_SECTORS[top].color}"><title>${escapeChartText(tip)}</title></circle>`;
            });
            const plotted = list.reduce((s, c) => s + c.n, 0);
            return chartFrameHtml({
                title: `${onOrbitPopulationLabel()} below 2,000 km: altitude vs inclination`,
                yTitle: 'MEAN ALTITUDE (KM)',
                totalText: `${orbitFormat(plotted)} ${onOrbitNoun()}`,
                totalTooltip: 'One dot per 25 km x 1° cell, its area proportional to how many objects are in it, '
                    + 'coloured by the sector with most objects there. Constellation shells and sun-synchronous '
                    + 'orbits (about 97–99°) show up as clusters. Hover a dot for its figures.',
                legend: ORBIT_SECTOR_ORDER.map((k) => ({ label: ORBIT_SECTORS[k].label, color: ORBIT_SECTORS[k].color })),
                svg: `<svg class="lcars-line-chart" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" role="img">${svg}</svg>`,
            });
        },
    },
    {
        key: 'geo-belt',
        section: 'locn',
        title: 'GEO belt',
        endpoint: 'api/on-orbit/chart?name=geo-belt',
        render: (data, slot) => {
            if (!data.rows.length) {
                return null;
            }
            const counts = {};
            data.rows.forEach((r) => { counts[`${r.band}|${r.sector}`] = r.n; });
            const bands = Array.from({ length: 180 }, (_, i) => -180 + i * 2);
            const series = ORBIT_SECTOR_ORDER.map((k) => ({ key: k, label: ORBIT_SECTORS[k].label, color: ORBIT_SECTORS[k].color }));
            const plotted = data.rows.reduce((s, r) => s + r.n, 0);
            return chartFrameHtml({
                title: `${onOrbitPopulationLabel()} in GEO by longitude`,
                yTitle: `# ${onOrbitNoun()}`,
                totalText: `${orbitFormat(plotted)} ${onOrbitNoun()} IN GEO`,
                totalTooltip: 'Geostationary objects along the GEO arc, in 2° bands of longitude, stacked by sector. '
                    + 'Longitude is worked out from each object\'s latest element set and carried forward to '
                    + 'today by its drift. Graveyard orbits above GEO are not included.',
                legend: series,
                svg: stackedColumnsSvg({
                    width: orbitSlotWidth(slot), categories: bands, series,
                    valueOf: (b, s) => counts[`${b}|${s.key}`] || 0,
                    labelOf: (b) => (b % 30 === 0 ? orbitLongitudeLabel(b) : ''),
                    xTitle: 'LONGITUDE',
                    tooltipOf: (b, i, t) => `${orbitLongitudeLabel(b)} to ${orbitLongitudeLabel(b + 2)}: ${orbitFormat(t)}\n`
                        + series.filter((s) => counts[`${b}|${s.key}`]).map((s) => `${s.label}: ${orbitFormat(counts[`${b}|${s.key}`])}`).join('\n'),
                }),
            });
        },
    },
    {
        key: 'age',
        section: 'locn',
        title: 'age',
        endpoint: 'api/on-orbit/chart?name=age',
        render: (data, slot) => {
            if (!data.rows.length) {
                return null;
            }
            const counts = {};
            data.rows.forEach((r) => { counts[`${r.band}|${r.regime}`] = r.n; });
            const bands = Array.from({ length: 31 }, (_, i) => i);
            const series = ORBIT_REGIME_ORDER.map((g) => ({ key: g, label: g, color: ORBIT_REGIME_COLOURS[g] }));
            const plotted = data.rows.reduce((s, r) => s + r.n, 0);
            return chartFrameHtml({
                title: `${onOrbitPopulationLabel()} by age`,
                yTitle: `# ${onOrbitNoun()}`,
                totalText: `${orbitFormat(plotted)} ${onOrbitNoun()}`,
                totalTooltip: 'Years since launch (this year minus the launch year), stacked by orbit type; the '
                    + 'last bar is 30 years and over. Objects with no launch date or current orbit on file are '
                    + 'not included.',
                legend: series,
                svg: stackedColumnsSvg({
                    width: orbitSlotWidth(slot), categories: bands, series,
                    valueOf: (b, s) => counts[`${b}|${s.key}`] || 0,
                    labelOf: (b) => (b === 30 ? '30+' : b % 5 === 0 ? `${b}` : ''),
                    centreLabels: true,
                    xTitle: 'YEARS SINCE LAUNCH',
                    tooltipOf: (b, i, t) => `${b === 30 ? '30 or more' : b} year${b === 1 ? '' : 's'}: ${orbitFormat(t)}\n`
                        + series.filter((s) => counts[`${b}|${s.key}`]).map((s) => `${s.label}: ${orbitFormat(counts[`${b}|${s.key}`])}`).join('\n'),
                }),
            });
        },
    },

    // ===== COMMERCIAL -- who owns it ====================================================
    {
        key: 'sector-pie',
        section: 'commercial',
        title: 'sector',
        row: 'commercial-pies',
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
            return pieChartHtml({
                title: `${onOrbitPopulationLabel()} by sector (GCAT class)`,
                totalText: `${total.toLocaleString('en-GB')} ${onOrbitNoun()}`, slices,
                totalTooltip: 'GCAT classes each payload by sector: A academic / amateur / non-profit, B commercial, '
                    + 'C civil government, D defence. A payload with no class of its own takes its owner\'s. '
                    + 'Unknown: not yet in GCAT, or no class recorded.',
            });
        },
    },
    {
        key: 'mission-pie',
        section: 'commercial',
        title: 'mission category',
        row: 'commercial-pies',
        endpoint: 'api/on-orbit/chart?name=mission',
        render: (data) => {
            if (!data.rows.length) {
                return null;
            }
            const slices = Object.keys(ORBIT_MISSIONS)
                .map((k) => ({ k, n: (data.rows.find((r) => r.category === k) || {}).n || 0 }))
                .filter((s) => s.n)
                .map((s) => ({ label: ORBIT_MISSIONS[s.k].label, value: s.n, color: ORBIT_MISSIONS[s.k].color }));
            return pieChartHtml({
                title: `${onOrbitPopulationLabel()} by mission`,
                totalText: `${orbitFormat(data.total)} ${onOrbitNoun()}`, slices,
                totalTooltip: 'GCAT\'s mission category for each payload (its first, if it lists several), grouped: imaging '
                    + 'includes radar; signals & EW is signals intelligence and electronic warfare; weather & Earth '
                    + 'science includes geodesy. Rocket bodies and debris (ALL-OBJ) have no category.',
            });
        },
    },
    {
        key: 'nationality',
        section: 'commercial',
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
            return logBarChartHtml({
                title: `${onOrbitPopulationLabel()} in orbit by nationality`,
                totalText: `${data.totalPayloads.toLocaleString('en-GB')} ${onOrbitNoun()}`,
                rows, axisTitle: `# ${onOrbitNoun()} (LOG SCALE)`,
            });
        },
    },
    {
        key: 'sector-by-country',
        section: 'commercial',
        title: 'sector by country',
        endpoint: 'api/on-orbit/chart?name=sector-by-country',
        render: (data) => {
            if (!data.rows.length) {
                return null;
            }
            // The 12 countries with most objects, then everyone else; each
            // bar 100%, split by sector.
            const byState = {};
            data.rows.forEach((r) => {
                const s = byState[r.state] || (byState[r.state] = { state: r.state, total: 0, sectors: {} });
                s.total += r.n;
                s.sectors[r.sector] = (s.sectors[r.sector] || 0) + r.n;
            });
            const ranked = Object.values(byState).filter((s) => s.state).sort((a, b) => b.total - a.total);
            const shown = ranked.slice(0, 12);
            const rest = { state: null, total: 0, sectors: {} };
            [...ranked.slice(12), byState[''] || { total: 0, sectors: {} }].forEach((s) => {
                rest.total += s.total;
                Object.entries(s.sectors).forEach(([k, n]) => { rest.sectors[k] = (rest.sectors[k] || 0) + n; });
            });
            const bars = rest.total ? [...shown, rest] : shown;
            const nameOf = (s) => (s.state === null ? 'Other & unknown'
                : (data.stateNames || {})[s.state] || s.state);
            const rowsHtml = bars.map((s) => {
                const segments = ORBIT_SECTOR_ORDER.filter((k) => s.sectors[k]).map((k) => {
                    const pct = (s.sectors[k] / s.total) * 100;
                    return `<span class="orbit-share-seg" style="width:${pct}%;background:${ORBIT_SECTORS[k].color}"
                        title="${escapeChartText(`${nameOf(s)} -- ${ORBIT_SECTOR_SHORT[k]}: ${orbitFormat(s.sectors[k])} (${pct.toFixed(1)}%)`)}">${pct >= 9 ? `${Math.round(pct)}%` : ''}</span>`;
                }).join('');
                return `<div class="orbit-chart-label">${escapeChartText(nameOf(s))}</div>
                    <div class="orbit-share-bar">${segments}</div>
                    <div class="orbit-chart-value">${orbitFormat(s.total)}</div>`;
            }).join('');
            return chartFrameHtml({
                title: `${onOrbitPopulationLabel()}: sector mix by country`,
                yTitle: '% OF EACH COUNTRY',
                totalText: `${orbitFormat(data.total)} ${onOrbitNoun()}`,
                totalTooltip: 'Each country\'s objects split by GCAT sector, as a percentage of that country\'s '
                    + 'total (shown at the right). The 12 countries with most objects, then everyone else, '
                    + 'including objects not yet in GCAT. Hover a segment for its count.',
                legend: ORBIT_SECTOR_ORDER.map((k) => ({ label: ORBIT_SECTORS[k].label, color: ORBIT_SECTORS[k].color })),
                svg: `<div class="orbit-share-grid">${rowsHtml}</div>`,
            });
        },
    },
    {
        // At the bottom of the page: the largest OWNERS_CHART_COUNT owners.
        key: 'owners',
        section: 'commercial',
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
            return rankedColumnChartHtml({
                title: `${onOrbitPopulationLabel()} by owner`,
                yTitle: `# ${noun} (LOG SCALE)`,
                totalText: `TOP ${owners.length} OF ${format(data.totalOwners)} OWNERS SHOWN`,
                totalTooltip: tooltip,
                rows: bars,
                tooltipOf: (row) => (row.muted ? row.fullName
                    : `${row.fullName || row.label}${row.stateCode ? ` (${row.stateCode})` : ''}: ${format(row.value)} ${noun}`),
            });
        },
    },
    {
        key: 'manufacturers',
        section: 'commercial',
        title: 'manufacturers',
        row: 'commercial-makers',
        endpoint: 'api/on-orbit/chart?name=manufacturers',
        render: (data) => {
            if (!data.rows.length) {
                return null;
            }
            const rows = data.rows.map((r) => ({ label: r.name || r.code, value: r.n }));
            return logBarChartHtml({
                title: `${onOrbitPopulationLabel()}: top 20 manufacturers`,
                totalText: `${orbitFormat(data.total)} ${onOrbitNoun()}`, rows, axisTitle: `# ${onOrbitNoun()} (LOG SCALE)`,
            });
        },
    },
    {
        key: 'buses',
        section: 'commercial',
        title: 'satellite buses',
        row: 'commercial-makers',
        endpoint: 'api/on-orbit/chart?name=buses',
        render: (data) => {
            if (!data.rows.length) {
                return null;
            }
            const rows = data.rows.map((r) => ({ label: r.bus, value: r.n }));
            return logBarChartHtml({
                title: `${onOrbitPopulationLabel()}: top 20 satellite buses`,
                totalText: `${orbitFormat(data.total)} ${onOrbitNoun()}`, rows, axisTitle: `# ${onOrbitNoun()} (LOG SCALE)`,
            });
        },
    },
    {
        key: 'payloads-by-year',
        section: 'commercial',
        title: 'payloads in orbit by year',
        endpoint: 'api/on-orbit/chart?name=payloads-by-year',
        render: (data, slot) => {
            if (!data.rows.length) {
                return null;
            }
            const counts = {};
            const years = [];
            data.rows.forEach((r) => {
                if (!years.includes(r.year)) {
                    years.push(r.year);
                }
                counts[`${r.year}|${r.sector}`] = r.n;
            });
            const series = ORBIT_SECTOR_ORDER.filter((k) => years.some((y) => counts[`${y}|${k}`]))
                .map((k) => ({ key: k, label: ORBIT_SECTORS[k].label, color: ORBIT_SECTORS[k].color }));
            const width = orbitSlotWidth(slot);
            const height = 320;
            const m = ORBIT_SVG_MARGIN;
            const plotW = width - m.left - m.right;
            const plotH = height - m.top - m.bottom;
            const totals = years.map((y) => series.reduce((s, k) => s + (counts[`${y}|${k.key}`] || 0), 0));
            const step = niceAxisStep(Math.max(...totals), 5);
            const top = Math.ceil(Math.max(...totals) / step) * step;
            const sx = (y) => m.left + ((y - years[0]) / (years[years.length - 1] - years[0] || 1)) * plotW;
            const sy = (v) => m.top + plotH - (v / top) * plotH;
            let svg = '';
            for (let v = 0; v <= top + 1e-9; v += step) {
                svg += `<line class="lcars-line-grid" x1="${m.left}" x2="${m.left + plotW}" y1="${sy(v)}" y2="${sy(v)}"></line>
                    <text class="lcars-line-ytick" x="${m.left - 8}" y="${sy(v)}" dy="0.35em" text-anchor="end">${orbitFormat(v)}</text>`;
            }
            svg += `<line class="lcars-line-axis" x1="${m.left}" x2="${m.left + plotW}" y1="${m.top + plotH}" y2="${m.top + plotH}"></line>`;
            years.filter((y) => y % 10 === 0).forEach((y) => {
                svg += `<line class="lcars-line-xtick-mark" x1="${sx(y)}" x2="${sx(y)}" y1="${m.top + plotH}" y2="${m.top + plotH + 5}"></line>
                    <text class="lcars-line-xtick" x="${sx(y)}" y="${m.top + plotH + 20}" text-anchor="middle">${y}</text>`;
            });
            const below = years.map(() => 0);
            series.forEach((k) => {
                const lower = below.slice();
                const upper = years.map((y, i) => lower[i] + (counts[`${y}|${k.key}`] || 0));
                upper.forEach((v, i) => { below[i] = v; });
                const pts = years.map((y, i) => `${sx(y).toFixed(1)},${sy(upper[i]).toFixed(1)}`)
                    .concat(years.map((y, i) => `${sx(y).toFixed(1)},${sy(lower[i]).toFixed(1)}`).reverse());
                svg += `<polygon class="lcars-area-band" points="${pts.join(' ')}" fill="${k.color}"></polygon>`;
            });
            const half = plotW / Math.max(years.length - 1, 1) / 2;
            svg += years.map((y, i) => `<rect class="lcars-hover-strip" x="${sx(y) - half}" y="${m.top}" width="${half * 2}" height="${plotH}">`
                + `<title>${escapeChartText(`${y}: ${orbitFormat(totals[i])} payloads\n`
                + series.map((k) => `${k.label}: ${orbitFormat(counts[`${y}|${k.key}`] || 0)}`).join('\n'))}</title></rect>`).join('');
            const label = onOrbitFilters.spacex === 'with' ? 'Payloads' : 'Payloads excl SpaceX';
            return chartFrameHtml({
                title: `${label} in orbit by year`,
                yTitle: '# PAYLOADS',
                totalText: `${orbitFormat(totals[totals.length - 1])} IN ORBIT NOW`,
                totalTooltip: 'Payloads in Earth orbit at the end of each year (this year: today), from GCAT\'s '
                    + 'launch and decay dates, stacked by sector. Only the SpaceX button applies: GCAT has no '
                    + 'history of which satellites were active, and this counts payloads only.',
                legend: series,
                svg: `<svg class="lcars-line-chart" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" role="img">${svg}</svg>`,
            });
        },
    },
    {
        // COMMERCIAL, last: the country -> owner tree.
        key: 'country-owner-tree',
        section: 'commercial',
        title: 'country and owner tree',
        endpoint: 'api/on-orbit/chart?name=country-owner',
        render: (data) => {
            if (!data.rows.length) {
                return null;
            }
            const byState = {};
            data.rows.forEach((r) => {
                const c = byState[r.state] || (byState[r.state] = { state: r.state, n: 0, owners: [] });
                c.n += r.n;
                c.owners.push({ name: r.ownerName || 'No owner on file', n: r.n });
            });
            const countries = Object.values(byState).map((c) => ({
                ...c,
                name: c.state ? ((data.stateNames || {})[c.state] || c.state) : 'Not yet in GCAT',
                owners: c.owners.sort((a, b) => b.n - a.n),
            })).sort((a, b) => b.n - a.n);
            return chartFrameHtml({
                title: `${onOrbitPopulationLabel()}: country and owner tree`,
                yTitle: `# ${onOrbitNoun()}`,
                totalText: `${countries.length} COUNTRIES · ${orbitFormat(data.rows.length)} OWNERS`,
                totalTooltip: 'Countries (GCAT state) with their owners beneath, largest first, like a directory '
                    + 'listing. Click a country to open or close it. Each country shows its 6 largest owners and '
                    + 'the rest together; the 15 largest countries are listed, the rest together. Bars show the '
                    + 'share of the whole.',
                svg: orbitTreeHtml({ rootLabel: `${onOrbitPopulationLabel()} in orbit`, rootTotal: data.total, countries }),
            });
        },
    },

    // ===== DEBRIS -- where it is, how much, what broke up ===============================
    // Every object in orbit: the status and kind buttons don't apply here.
    {
        key: 'catalogue-by-type',
        section: 'debris',
        title: 'catalogue by object type',
        endpoint: 'api/on-orbit/chart?name=catalogue-by-type',
        render: (data, slot) => {
            if (!data.rows.length) {
                return null;
            }
            const counts = {};
            data.rows.forEach((r) => { counts[`${r.regime}|${r.objectType}`] = r.n; });
            const regimes = ORBIT_REGIME_ORDER.filter((g) => ORBIT_OBJECT_TYPES.some((t) => counts[`${g}|${t.key}`]));
            const debris = data.rows.filter((r) => r.objectType === 'DEB').reduce((a, r) => a + r.n, 0);
            return chartFrameHtml({
                title: `${onOrbitEverythingLabel()} in orbit by type and orbit`,
                yTitle: '# OBJECTS',
                totalText: `${orbitFormat(data.total)} OBJECTS · ${orbitFormat(debris)} DEBRIS`,
                totalTooltip: 'Every catalogued object in orbit, by orbit type, split into payloads, rocket bodies, '
                    + 'debris and unknown. The DEBRIS charts ignore the status and kind buttons -- debris is never '
                    + 'active and isn\'t a payload -- but follow the SpaceX button.',
                legend: ORBIT_OBJECT_TYPES,
                svg: stackedColumnsSvg({
                    width: orbitSlotWidth(slot), height: 300, categories: regimes, series: ORBIT_OBJECT_TYPES,
                    valueOf: (g, t) => counts[`${g}|${t.key}`] || 0,
                    labelOf: (g) => g,
                    centreLabels: true,
                    tooltipOf: (g, i, t) => `${g}: ${orbitFormat(t)}\n`
                        + ORBIT_OBJECT_TYPES.map((k) => `${k.label}: ${orbitFormat(counts[`${g}|${k.key}`] || 0)}`).join('\n'),
                }),
            });
        },
    },
    {
        // Bars: pieces created each year; line (right axis): pieces in orbit.
        key: 'debris-history',
        section: 'debris',
        title: 'debris history',
        endpoint: 'api/on-orbit/chart?name=debris-history',
        render: (data, slot) => {
            if (!data.rows.length) {
                return null;
            }
            const years = data.rows.map((r) => r.year);
            const created = data.rows.map((r) => r.created);
            const inOrbit = data.rows.map((r) => r.inOrbit);
            const peak = data.rows.reduce((best, r) => (r.created > best.created ? r : best), data.rows[0]);
            const label = onOrbitFilters.spacex === 'with' ? 'Debris' : 'Debris excl SpaceX';
            const legend = [
                { label: 'Pieces created that year', color: 'var(--tng-lavender)' },
                { label: 'Pieces in orbit at year end (right axis)', color: 'var(--tng-amber)' },
            ];
            return chartFrameHtml({
                title: `${label}: pieces created per year and in orbit`,
                yTitle: '# CREATED · # IN ORBIT (RIGHT)',
                totalText: `${orbitFormat(inOrbit[inOrbit.length - 1])} IN ORBIT NOW`,
                totalTooltip: 'From GCAT\'s catalogue of every piece of debris ever catalogued. Bars: pieces created '
                    + 'each year, by the date each piece broke off (not its parent\'s launch date). Line: pieces in '
                    + 'orbit at each year end -- every piece created so far, less every piece re-entered so far. '
                    + `The biggest year is ${peak.year} (${orbitFormat(peak.created)} pieces). Catalogued debris `
                    + 'only (roughly 10 cm and up in LEO); GCAT counts slightly more than the NORAD catalogue the '
                    + 'other charts use. This year: to date.',
                legend,
                svg: barsAndLineSvg({
                    width: orbitSlotWidth(slot), years,
                    bars: { values: created, color: 'var(--tng-lavender)' },
                    line: { values: inOrbit, color: 'var(--tng-amber)' },
                    tooltipOf: (i) => `${years[i]}: ${orbitFormat(created[i])} created, `
                        + `${orbitFormat(data.rows[i].reentered)} re-entered, ${orbitFormat(inOrbit[i])} in orbit at year end`,
                }),
            });
        },
    },
    {
        key: 'debris-altitude',
        section: 'debris',
        title: 'altitude by object type',
        endpoint: 'api/on-orbit/chart?name=debris-altitude',
        render: (data, slot) => {
            if (!data.rows.length) {
                return null;
            }
            const counts = {};
            data.rows.forEach((r) => { counts[`${r.band}|${r.objectType}`] = r.n; });
            const first = Math.min(...data.rows.map((r) => r.band));
            const bands = [];
            for (let b = Math.floor(first / 100) * 100; b < 2000; b += 25) {
                bands.push(b);
            }
            const plotted = data.rows.reduce((a, r) => a + r.n, 0);
            return chartFrameHtml({
                title: `${onOrbitEverythingLabel()} below 2,000 km by altitude`,
                yTitle: '# OBJECTS',
                totalText: `${orbitFormat(plotted)} OBJECTS`,
                totalTooltip: 'Where the debris is: every object below 2,000 km in 25 km bands of mean altitude, '
                    + 'split by type. The debris peaks around 750–900 km, where the largest break-ups happened '
                    + '(Fengyun-1C, Cosmos 2251 / Iridium 33).',
                legend: ORBIT_OBJECT_TYPES,
                svg: stackedColumnsSvg({
                    width: orbitSlotWidth(slot), categories: bands, series: ORBIT_OBJECT_TYPES,
                    valueOf: (b, t) => counts[`${b}|${t.key}`] || 0,
                    labelOf: (b) => (b % 250 === 0 ? orbitFormat(b) : ''),
                    xTitle: 'MEAN ALTITUDE (KM)',
                    tooltipOf: (b, i, t) => `${orbitFormat(b)}–${orbitFormat(b + 25)} km: ${orbitFormat(t)}\n`
                        + ORBIT_OBJECT_TYPES.map((k) => `${k.label}: ${orbitFormat(counts[`${b}|${k.key}`] || 0)}`).join('\n'),
                }),
            });
        },
    },
    {
        key: 'debris-inclination',
        section: 'debris',
        title: 'debris by inclination',
        endpoint: 'api/on-orbit/chart?name=debris-inclination',
        render: (data, slot) => {
            if (!data.rows.length) {
                return null;
            }
            const counts = {};
            data.rows.forEach((r) => { counts[r.band] = r.n; });
            const bands = Array.from({ length: 36 }, (_, i) => i * 5);
            const plotted = data.rows.reduce((a, r) => a + r.n, 0);
            return chartFrameHtml({
                title: `${onOrbitFilters.spacex === 'with' ? 'Debris' : 'Debris excl SpaceX'} in orbit by inclination`,
                yTitle: '# DEBRIS (LOG SCALE)',
                totalText: `${orbitFormat(plotted)} PIECES`,
                totalTooltip: 'Catalogued debris by current inclination in 5° bands -- the same form as the LOCN '
                    + 'inclination chart. Clusters show where break-ups happened: about 74° (Cosmos), 82–83° '
                    + '(Cosmos 2251), 86° (Iridium 33), 98–99° (Fengyun-1C, sun-synchronous stages).',
                svg: stackedColumnsSvg({
                    width: orbitSlotWidth(slot), categories: bands, log: true,
                    series: [{ key: 'n', color: 'var(--tng-lavender)' }],
                    valueOf: (b) => counts[b] || 0,
                    labelOf: (b) => (b % 15 === 0 ? `${b}°` : ''),
                    xTitle: 'INCLINATION',
                    tooltipOf: (b) => `${b}–${b + 5}°: ${orbitFormat(counts[b] || 0)} pieces`,
                }),
            });
        },
    },
    {
        key: 'rocket-bodies-country',
        section: 'debris',
        title: 'rocket bodies by country',
        row: 'debris-rocket-bodies',
        endpoint: 'api/on-orbit/chart?name=rocket-bodies-country',
        render: (data) => {
            if (!data.rows.length) {
                return null;
            }
            const named = data.rows.filter((r) => r.state);
            const rows = named.slice(0, 12).map((r) => ({ label: (data.stateNames || {})[r.state] || r.state, value: r.n }));
            const other = data.rows.reduce((a, r) => a + r.n, 0) - rows.reduce((a, r) => a + r.value, 0);
            if (other) {
                rows.push({ label: 'Other & unknown', value: other, muted: true });
            }
            const total = rows.reduce((a, r) => a + r.value, 0);
            return logBarChartHtml({
                title: `${onOrbitFilters.spacex === 'with' ? 'Rocket bodies' : 'Rocket bodies excl SpaceX'} in orbit by country`,
                totalText: `${orbitFormat(total)} ROCKET BODIES`, rows, axisTitle: '# ROCKET BODIES (LOG SCALE)',
            });
        },
    },
    {
        key: 'rocket-bodies-vehicle',
        section: 'debris',
        title: 'rocket bodies by launch vehicle',
        row: 'debris-rocket-bodies',
        endpoint: 'api/on-orbit/chart?name=rocket-bodies-vehicle',
        render: (data) => {
            if (!data.rows.length) {
                return null;
            }
            const named = data.rows.filter((r) => r.vehicle);
            const rows = named.slice(0, 15).map((r) => ({ label: r.vehicle, value: r.n }));
            const other = data.rows.reduce((a, r) => a + r.n, 0) - rows.reduce((a, r) => a + r.value, 0);
            if (other) {
                rows.push({ label: 'Other & unknown', value: other, muted: true });
            }
            const total = rows.reduce((a, r) => a + r.value, 0);
            return logBarChartHtml({
                title: `${onOrbitFilters.spacex === 'with' ? 'Rocket bodies' : 'Rocket bodies excl SpaceX'} by launch vehicle`,
                totalText: `${orbitFormat(total)} ROCKET BODIES`, rows, axisTitle: '# ROCKET BODIES (LOG SCALE)',
            });
        },
    },
    {
        key: 'debris-origin',
        section: 'debris',
        title: 'debris by origin',
        endpoint: 'api/on-orbit/chart?name=debris-origin',
        render: (data) => {
            if (!data.rows.length) {
                return null;
            }
            // The 20 objects with most debris still in orbit, named by GCAT
            // with their launch year; then the rest together.
            const named = data.rows.filter((r) => r.parent && r.name);
            const rows = named.slice(0, 20).map((r) => ({ label: `${r.name}${r.year ? ` (${r.year})` : ''}`, value: r.n }));
            const total = data.rows.reduce((a, r) => a + r.n, 0);
            const other = total - rows.reduce((a, r) => a + r.value, 0);
            if (other) {
                rows.push({ label: `Other & unidentified (${orbitFormat(data.rows.length - rows.length)} sources)`, value: other, muted: true });
            }
            return logBarChartHtml({
                title: `${onOrbitFilters.spacex === 'with' ? 'Debris' : 'Debris excl SpaceX'} in orbit by the object it broke off`,
                totalText: `${orbitFormat(total)} PIECES`, rows, axisTitle: '# PIECES IN ORBIT (LOG SCALE)',
            });
        },
    },

    // ===== COMMS -- radio ==============================================================
    {
        key: 'band-pie',
        section: 'comms',
        title: 'downlink band',
        endpoint: 'api/on-orbit/chart?name=band',
        render: (data) => {
            if (!data.rows.length) {
                return null;
            }
            const counts = {};
            data.rows.forEach((r) => { counts[r.band] = r.n; });
            const slices = ORBIT_BANDS.filter((b) => counts[b.key])
                .map((b) => ({ label: orbitBandText(b.key, true), value: counts[b.key], color: b.color }));
            if (counts.none) {
                slices.push({ label: 'No band on file', value: counts.none, color: 'var(--tng-mauve)' });
            }
            return pieChartHtml({
                title: `${onOrbitPopulationLabel()} by downlink band`,
                totalText: `${orbitFormat(data.total)} ${onOrbitNoun()}`, slices,
                totalTooltip: 'Each satellite\'s main downlink band. Mostly inferred, not measured: from the constellation it '
                    + 'belongs to (e.g. Starlink and OneWeb -> Ku, O3b -> Ka, Iridium -> L), or estimated from its type '
                    + 'and orbit; about 1,000 have an actual frequency from SatNOGS. One band per satellite, though '
                    + 'most use several. Try EX SPACEX: Starlink alone is three-quarters of Ku.',
            });
        },
    },
    {
        key: 'band-by-mission',
        section: 'comms',
        title: 'band by mission',
        endpoint: 'api/on-orbit/chart?name=band-by-mission',
        render: (data, slot) => {
            if (!data.rows.length) {
                return null;
            }
            const counts = {};
            data.rows.forEach((r) => { counts[`${r.band}|${r.category}`] = r.n; });
            const bands = ORBIT_BANDS.map((b) => b.key).filter((b) => data.rows.some((r) => r.band === b));
            const series = Object.entries(ORBIT_MISSIONS).map(([key, v]) => ({ key, label: v.label, color: v.color }))
                .filter((s) => data.rows.some((r) => r.category === s.key));
            const plotted = data.rows.reduce((a, r) => a + r.n, 0);
            return chartFrameHtml({
                title: `${onOrbitPopulationLabel()} by downlink band and mission`,
                yTitle: `# ${onOrbitNoun()}`,
                totalText: `${orbitFormat(plotted)} WITH A BAND`,
                totalTooltip: 'Each downlink band\'s satellites split by mission category. Only those with a band on '
                    + 'file; bands are mostly inferred (see the pie).',
                legend: series,
                svg: stackedColumnsSvg({
                    width: orbitSlotWidth(slot), height: 300, categories: bands, series,
                    valueOf: (b, s) => counts[`${b}|${s.key}`] || 0,
                    labelOf: (b) => b,
                    centreLabels: true,
                    xTitle: 'BAND',
                    tooltipOf: (b, i, t) => `${orbitBandText(b)}: ${orbitFormat(t)}\n`
                        + series.filter((s) => counts[`${b}|${s.key}`]).map((s) => `${s.label}: ${orbitFormat(counts[`${b}|${s.key}`])}`).join('\n'),
                }),
            });
        },
    },
    {
        key: 'band-by-regime',
        section: 'comms',
        title: 'band by orbit type',
        endpoint: 'api/on-orbit/chart?name=band-by-regime',
        render: (data, slot) => {
            if (!data.rows.length) {
                return null;
            }
            const counts = {};
            data.rows.forEach((r) => { counts[`${r.band}|${r.regime}`] = r.n; });
            const bands = ORBIT_BANDS.map((b) => b.key).filter((b) => data.rows.some((r) => r.band === b));
            const series = ORBIT_REGIME_ORDER.map((g) => ({ key: g, label: g, color: ORBIT_REGIME_COLOURS[g] }))
                .filter((s) => data.rows.some((r) => r.regime === s.key));
            const plotted = data.rows.reduce((a, r) => a + r.n, 0);
            return chartFrameHtml({
                title: `${onOrbitPopulationLabel()} by downlink band and orbit type`,
                yTitle: `# ${onOrbitNoun()}`,
                totalText: `${orbitFormat(plotted)} WITH A BAND`,
                totalTooltip: 'Each downlink band\'s satellites split by orbit type. Only those with a band on file.',
                legend: series,
                svg: stackedColumnsSvg({
                    width: orbitSlotWidth(slot), height: 300, categories: bands, series,
                    valueOf: (b, s) => counts[`${b}|${s.key}`] || 0,
                    labelOf: (b) => b,
                    centreLabels: true,
                    xTitle: 'BAND',
                    tooltipOf: (b, i, t) => `${orbitBandText(b)}: ${orbitFormat(t)}\n`
                        + series.filter((s) => counts[`${b}|${s.key}`]).map((s) => `${s.label}: ${orbitFormat(counts[`${b}|${s.key}`])}`).join('\n'),
                }),
            });
        },
    },
];

function onOrbitNoun() {
    return ON_ORBIT_KIND_NOUNS[onOrbitFilters.kind];
}

// Bumped per chart on every load, so a slow response for an earlier filter
// setting can't overwrite a newer one.
const onOrbitChartLoadSeq = {};

async function renderOnOrbitChart(chart, slot) {
    const seq = (onOrbitChartLoadSeq[chart.key] || 0) + 1;
    onOrbitChartLoadSeq[chart.key] = seq;
    let html;
    try {
        const joiner = chart.endpoint.includes('?') ? '&' : '?';
        const response = await fetch(`${chart.endpoint}${joiner}${onOrbitQuery()}`);
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }
        html = chart.render(await response.json(), slot)
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
    // Switching group empties the area; then one slot per chart of the
    // group, created on first use and kept, so each chart redraws in place
    // without moving the others. Charts sharing a row sit side by side
    // (.orbit-chart-row), e.g. the two pies.
    if (container.dataset.group !== onOrbitGroup) {
        container.innerHTML = '';
        container.dataset.group = onOrbitGroup;
    }
    ON_ORBIT_CHARTS.filter((chart) => chart.section === onOrbitGroup).forEach((chart) => {
        let slot = container.querySelector(`[data-chart="${chart.key}"]`);
        if (!slot) {
            let parent = container;
            if (chart.row) {
                parent = container.querySelector(`[data-chart-row="${chart.row}"]`);
                if (!parent) {
                    parent = document.createElement('div');
                    parent.className = 'orbit-chart-row';
                    parent.dataset.chartRow = chart.row;
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

// The SVG charts are drawn to their slot's width: redraw the group when the
// window is resized (debounced), while it's showing.
let onOrbitResizeTimer = null;
window.addEventListener('resize', () => {
    clearTimeout(onOrbitResizeTimer);
    onOrbitResizeTimer = setTimeout(() => {
        const container = document.getElementById('on-orbit-charts');
        if (container && container.offsetParent !== null) {
            renderOnOrbitCharts();
        }
    }, 300);
});
