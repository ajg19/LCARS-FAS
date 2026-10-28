/* ==========================================================================
   LAUNCHES PANEL -- launch charts in the LAUNCHES section's main area.
   Lazy-loaded by openLaunchesSection() in lcars.js the first time the
   LAUNCHES menu button is clicked.

   Three charts, each in its own slot so each loads and fails on its own:
   orbital launch attempts per year (line, api/launches/per-year, counted
   from GCAT's launch log on request); payloads launched per year (stacked
   area, api/launches/payloads-launched) and re-entries per year (stacked
   bars, api/launches/reentries), both precomputed by orbitStats.py. Same
   LCARS chart style as the
   ON-ORBIT charts (.orbit-chart: pill title bar, blue numbers, sand
   labels); drawn as SVG sized to the area, redrawn when the window is
   resized. The drawing code is assets/chartCore.js.
   ========================================================================== */

let launchesPerYearData = null;

// Filters:
//   spacex   INC / EX SPACEX -- launches SpaceX carried out (launch-log
//            charts) and objects SpaceX owns (payloads and re-entries
//            charts); as server.py's ON_ORBIT_SPACEX_FILTERS.
//   outcome  LCH-ALL / LCH-OK (all / successful launches) -- the three launch-log charts only
//            (server.py's LAUNCH_OUTCOME_FILTERS); payloads launched already
//            counts only payloads that reached orbit, and re-entries aren't
//            launches.
//   fromYear / toYear  the years shown on every chart (null: the full range,
//            LAUNCH_FIRST_YEAR to this year); set in the control area.
const launchesFilters = { spacex: 'with', outcome: 'all', fromYear: null, toYear: null };
const LAUNCH_FIRST_YEAR = 1957;

function launchLastYear() {
    return new Date().getUTCFullYear();
}

function launchYearRange() {
    return [launchesFilters.fromYear || LAUNCH_FIRST_YEAR, launchesFilters.toYear || launchLastYear()];
}

function inLaunchYearRange(year) {
    const [from, to] = launchYearRange();
    return Number(year) >= from && Number(year) <= to;
}
// Main area: the charts, or (DEFINITIONS button) the static definitions
// page, #launches-definitions, whose contents are the helper file
// assets/launchesDefs.html (fetched the first time it is shown).
let launchesShowingDefinitions = false;

function launchesQuery() {
    return `spacex=${launchesFilters.spacex}&outcome=${launchesFilters.outcome}`;
}

// Chart titles say when SpaceX is left out, and -- for the launch-log charts
// (launchBased) -- when only successful launches are counted.
function launchesTitle(title, launchBased = false) {
    let text = title;
    if (launchBased && launchesFilters.outcome === 'success') {
        text += ', successful only';
    }
    return launchesFilters.spacex === 'with' ? text : `${text} excl SpaceX`;
}

// --- Year range (control area) ---------------------------------------------------
// Two inputs, start and end year. A new value is checked when the user
// presses Enter or leaves the field: a whole year from LAUNCH_FIRST_YEAR to
// this year, start no later than end. A good value redraws every chart; a
// bad one is put back to the last good value, with the reason shown for a
// few seconds.
let launchYearMessageTimer = null;

function renderLaunchYearInputs() {
    const wrapper = document.getElementById('default');
    if (!wrapper) {
        return;
    }
    const [from, to] = launchYearRange();
    wrapper.innerHTML = `
        <div class="launch-years">
            <label class="launch-years-field">START YEAR
                <input id="launch-from-year" type="text" inputmode="numeric" maxlength="4" value="${from}"
                       aria-label="Start year"></label>
            <label class="launch-years-field">END YEAR
                <input id="launch-to-year" type="text" inputmode="numeric" maxlength="4" value="${to}"
                       aria-label="End year"></label>
            <div id="launch-years-message" class="launch-years-message" role="status"></div>
        </div>`;
    ['launch-from-year', 'launch-to-year'].forEach((id) => {
        const input = document.getElementById(id);
        input.addEventListener('keydown', (event) => {
            if (event.key === 'Enter') {
                event.preventDefault();
                input.blur();   // -> 'change', if the value changed
            }
        });
        input.addEventListener('change', () => applyLaunchYearInput(input, id === 'launch-from-year'));
    });
}

function showLaunchYearMessage(text) {
    const message = document.getElementById('launch-years-message');
    if (!message) {
        return;
    }
    message.textContent = text;
    clearTimeout(launchYearMessageTimer);
    launchYearMessageTimer = setTimeout(() => { message.textContent = ''; }, 4000);
}

function applyLaunchYearInput(input, isStart) {
    const [from, to] = launchYearRange();
    const first = LAUNCH_FIRST_YEAR;
    const last = launchLastYear();
    const text = input.value.trim();
    const year = Number(text);
    let problem = null;
    if (!/^\d{4}$/.test(text) || year < first || year > last) {
        problem = `${isStart ? 'START' : 'END'} YEAR MUST BE A YEAR FROM ${first} TO ${last}`;
    } else if (isStart && year > to) {
        problem = `START YEAR CAN'T BE AFTER THE END YEAR (${to})`;
    } else if (!isStart && year < from) {
        problem = `END YEAR CAN'T BE BEFORE THE START YEAR (${from})`;
    }
    if (problem) {
        input.value = isStart ? from : to;   // back to the last good value
        input.classList.add('is-invalid');
        setTimeout(() => input.classList.remove('is-invalid'), 1500);
        showLaunchYearMessage(problem);
        return;
    }
    if (isStart) {
        launchesFilters.fromYear = year === first ? null : year;
    } else {
        launchesFilters.toYear = year === last ? null : year;
    }
    input.value = year;
    showLaunchYearMessage('');
    redrawLaunchCharts();   // the data is already loaded; the range only trims it
}

async function applyLaunchesMainView() {
    const charts = document.getElementById('launches-charts');
    const definitions = document.getElementById('launches-definitions');
    if (launchesShowingDefinitions) {
        await loadHelperHtml('assets/launchesDefs.html', 'launches-definitions');
    }
    if (charts && definitions) {
        charts.style.display = launchesShowingDefinitions ? 'none' : '';
        definitions.style.display = launchesShowingDefinitions ? '' : 'none';
    }
    if (!launchesShowingDefinitions) {
        redrawLaunchCharts();   // to the area's width, which was 0 while hidden
    }
}

// Back to the charts -- called by openLaunchesSection() (lcars.js) each time
// the LAUNCHES menu button is clicked.
function showLaunchCharts() {
    launchesShowingDefinitions = false;
    applyLaunchesMainView();
}

// Control area: the start / end year inputs on the left; four buttons laid
// out 2 x 2 as ON-ORBIT's, same checkerboard colours -- the outcome filter
// top left, the SpaceX filter top right, DEFINITIONS / CHARTS bottom right,
// and a blank placeholder bottom left.
registerPanelControls('launches', {
    defaultAreaMode: 'custom',
    renderDefaultArea: renderLaunchYearInputs,
    buttons: [
        {
            label: 'OUTCOME',
            color: 'var(--tng-sand)',
            // LCH-ALL: every launch attempt; LCH-OK: successful launches only.
            getText: () => (launchesFilters.outcome === 'all' ? 'LCH-ALL' : 'LCH-OK'),
            onClick: () => {
                launchesFilters.outcome = launchesFilters.outcome === 'all' ? 'success' : 'all';
                renderLaunchesPerYear();
            },
        },
        {
            label: 'SPACEX',
            color: 'var(--tng-periwinkle)',
            getText: () => (launchesFilters.spacex === 'with' ? 'INC SPACEX' : 'EX SPACEX'),
            onClick: () => {
                launchesFilters.spacex = launchesFilters.spacex === 'with' ? 'without' : 'with';
                renderLaunchesPerYear();
            },
        },
        { label: '', color: 'var(--tng-lavender)' },
        {
            label: 'DEFINITIONS',
            color: 'var(--tng-amber)',
            getText: () => (launchesShowingDefinitions ? 'CHARTS' : 'DEFS'),
            onClick: () => {
                launchesShowingDefinitions = !launchesShowingDefinitions;
                applyLaunchesMainView();
            },
        },
    ],
});

// The chart code (frame, axes, line, dual-axis, stacked area / bar) is
// assets/chartCore.js, loaded before this file by openLaunchesSection().
function launchesChartWidth() {
    return chartWidth('launches-charts');
}

// Sector colours: the site-wide --sector-* tokens (classic.css), as in the
// ON-ORBIT sector pie.
const SECTOR_COLOURS = {
    A: 'var(--sector-academic)', B: 'var(--sector-commercial)', C: 'var(--sector-civil)',
    D: 'var(--sector-defence)', unknown: 'var(--sector-unknown)',
};
const SECTOR_LABELS = {
    A: 'Academic & amateur', B: 'Commercial', C: 'Civil government', D: 'Defence', unknown: 'Unknown sector',
};
// Launches by launch-vehicle country (server.py's LAUNCH_COUNTRY_SERIES).
const LAUNCH_COUNTRY_COLOURS = {
    US: 'var(--tng-periwinkle)', SU: 'var(--tng-salmon)', RU: 'var(--tng-pink)', CN: 'var(--tng-amber)',
    EU: 'var(--tng-lavender)', J: 'var(--tng-ice)', IN: 'var(--tng-sand)', NZ: 'var(--tng-tan)',
    other: 'var(--tng-mauve)',
};
const LAUNCH_COUNTRY_LABELS = {
    US: 'United States', SU: 'Soviet Union', RU: 'Russia', CN: 'China', EU: 'Europe', J: 'Japan',
    IN: 'India', NZ: 'New Zealand (Rocket Lab)', other: 'Other',
};

// Re-entries by object type (D here is debris, not defence).
const REENTRY_KIND_COLOURS = {
    P: 'var(--tng-periwinkle)', R: 'var(--tng-amber)', D: 'var(--tng-lavender)', other: 'var(--tng-mauve)',
};
const REENTRY_KIND_LABELS = { P: 'Payloads', R: 'Rocket bodies', D: 'Debris', other: 'Other' };

// One slot per chart in #launches-charts, created on first use, in page order.
const LAUNCH_CHART_KEYS = ['per-year', 'payloads-per-launch', 'by-country', 'payloads-launched', 'reentries'];

function launchChartSlot(key) {
    const container = document.getElementById('launches-charts');
    if (!container) {
        return null;
    }
    LAUNCH_CHART_KEYS.forEach((k) => {
        if (!container.querySelector(`[data-chart="${k}"]`)) {
            const slot = document.createElement('div');
            slot.dataset.chart = k;
            container.appendChild(slot);
        }
    });
    return container.querySelector(`[data-chart="${key}"]`);
}

function drawLaunchesPerYear() {
    const container = launchChartSlot('per-year');
    if (!container || !launchesPerYearData) {
        return;
    }
    const data = launchesPerYearData;
    if (!data.rows.length) {
        container.innerHTML = '<p class="orbit-chart-note">NO LAUNCH DATA YET -- RUN scripts/ingestGcat.py</p>';
        return;
    }
    const format = (n) => n.toLocaleString('en-GB');
    const points = data.rows.filter((row) => inLaunchYearRange(row.year))
        .map((row) => ({ x: Number(row.year), y: row.launches, failures: row.failures }));
    if (!points.length) {
        container.innerHTML = '<p class="orbit-chart-note">NO LAUNCHES IN THIS RANGE OF YEARS</p>';
        return;
    }
    const total = points.reduce((sum, p) => sum + p.y, 0);
    const lastYear = points[points.length - 1].x;
    // The current year is still running: its point is a count to date.
    const toDate = data.latestLaunch ? data.latestLaunch.slice(0, 10) : null;
    container.innerHTML = lineChartHtml({
        width: launchesChartWidth(),
        title: launchesTitle('Orbital launch attempts per year', true),
        yTitle: '# LAUNCHES',
        xTitle: 'YEAR',
        totalText: `${format(total)} LAUNCHES ${points[0].x}–${lastYear}`,
        totalTooltip: (launchesFilters.outcome === 'success'
            ? 'Every successful orbital and deep-space launch'
            : 'Every orbital and deep-space launch attempt, successful or not,')
            + ' from GCAT\'s launch log (J. McDowell, planet4589.org). Suborbital tests are not counted. '
            + (launchesFilters.spacex === 'without' ? 'Launches carried out by SpaceX are left out. ' : '')
            + (toDate ? `${lastYear} is the year to date (latest launch ${toDate}).` : ''),
        points,
        pointTooltip: (p) => `${p.x}: ${format(p.y)} launches${p.failures ? `, ${format(p.failures)} failed` : ''}`
            + (p.x === lastYear && toDate ? ' (year to date)' : ''),
        // The current year is still running, so its point isn't joined to the line.
        detachLast: Number(lastYear) === launchLastYear(),
    });
}

let payloadsLaunchedData = null;
let launchesByCountryData = null;

function drawLaunchesByCountry() {
    const slot = launchChartSlot('by-country');
    if (!slot || !launchesByCountryData) {
        return;
    }
    if (!launchesByCountryData.rows.length) {
        slot.innerHTML = '<p class="orbit-chart-note">NO LAUNCH DATA YET -- RUN scripts/ingestGcat.py</p>';
        return;
    }
    const rows = launchesByCountryData.rows.filter((row) => inLaunchYearRange(row.year));
    if (!rows.length) {
        slot.innerHTML = '<p class="orbit-chart-note">NO LAUNCHES IN THIS RANGE OF YEARS</p>';
        return;
    }
    const stack = chartStackRows(rows, 'country', 'launches');
    const total = rows.reduce((sum, row) => sum + row.launches, 0);
    slot.innerHTML = stackedBarChartHtml({
        width: launchesChartWidth(),
        title: launchesTitle('Launches per year by country', true),
        yTitle: '# LAUNCHES',
        xTitle: '',
        totalText: `${total.toLocaleString('en-GB')} LAUNCHES ${stack.years[0]}–${stack.years[stack.years.length - 1]}`,
        totalTooltip: (launchesFilters.outcome === 'success'
            ? 'Successful orbital and deep-space launches'
            : 'Orbital and deep-space launch attempts, successful or not,')
            + ' by the country GCAT gives the launch vehicle. Europe combines France (Arianespace), ESA, ELDO, Italy, Germany and the UK. GCAT '
            + 'codes Rocket Lab\'s Electron as New Zealand, where it launches from. Other: Iran, Israel, North and '
            + 'South Korea, Brazil, Australia and the Cayman Islands. This year: to date.'
            + (launchesFilters.spacex === 'without' ? ' Launches carried out by SpaceX are left out.' : ''),
        stack,
        colours: LAUNCH_COUNTRY_COLOURS,
        labels: LAUNCH_COUNTRY_LABELS,
        unit: 'launches',
        height: LCARS_CHART_HEIGHT * 2,   // twice the other charts' height
    });
}

// Launches and the payloads they carried per year (left axis), and payloads
// per launch (right axis) -- all from the launch log, so the three agree.
function drawPayloadsPerLaunch() {
    const slot = launchChartSlot('payloads-per-launch');
    if (!slot || !launchesPerYearData || !launchesPerYearData.rows.length) {
        return;
    }
    const rows = launchesPerYearData.rows.filter((row) => inLaunchYearRange(row.year));
    if (!rows.length) {
        slot.innerHTML = '<p class="orbit-chart-note">NO LAUNCHES IN THIS RANGE OF YEARS</p>';
        return;
    }
    const years = rows.map((row) => Number(row.year));
    const launches = rows.map((row) => row.launches);
    const payloads = rows.map((row) => row.payloads);
    const perLaunch = rows.map((row) => (row.launches ? row.payloads / row.launches : 0));
    const format = (n) => n.toLocaleString('en-GB');
    const lastYear = years[years.length - 1];
    const inProgress = lastYear === launchLastYear();
    const lastFull = inProgress && rows.length > 1 ? rows.length - 2 : rows.length - 1;
    slot.innerHTML = dualAxisLineChartHtml({
        width: launchesChartWidth(),
        title: launchesTitle('Launches and payloads per year', true),
        yTitle: '# LAUNCHES & PAYLOADS · PAYLOADS PER LAUNCH (RIGHT)',
        totalText: `${perLaunch[lastFull].toFixed(1)} PAYLOADS PER LAUNCH IN ${years[lastFull]}`,
        totalTooltip: 'From GCAT\'s launch log, which lists every payload on every orbital and deep-space launch '
            + 'attempt: launches counted once each, payloads as carried (including any lost in a failed launch, '
            + 'so slightly more than the payloads-launched chart). Payloads per launch is their ratio. '
            + (launchesFilters.spacex === 'without' ? 'SpaceX launches and the payloads they carried are left out. ' : '')
            + (inProgress ? `${lastYear} is the year to date.` : ''),
        years,
        left: [
            { label: 'Launches', color: 'var(--tng-periwinkle)', values: launches },
            { label: 'Payloads', color: 'var(--tng-amber)', values: payloads },
        ],
        right: { label: 'Payloads per launch', color: 'var(--tng-lavender)', values: perLaunch },
        tooltipOf: (i) => `${years[i]}${inProgress && i === rows.length - 1 ? ' (year to date)' : ''}: `
            + `${format(launches[i])} launches, ${format(payloads[i])} payloads, `
            + `${perLaunch[i].toFixed(1)} per launch`,
        detachLast: inProgress,
    });
}
let reentriesData = null;

function drawPayloadsLaunched() {
    const slot = launchChartSlot('payloads-launched');
    if (!slot || !payloadsLaunchedData) {
        return;
    }
    if (!payloadsLaunchedData.rows.length) {
        slot.innerHTML = '<p class="orbit-chart-note">NO PAYLOAD HISTORY YET -- RUN scripts/orbitStats.py</p>';
        return;
    }
    const rows = payloadsLaunchedData.rows.filter((row) => inLaunchYearRange(row.year));
    if (!rows.length) {
        slot.innerHTML = '<p class="orbit-chart-note">NO PAYLOADS IN THIS RANGE OF YEARS</p>';
        return;
    }
    const stack = chartStackRows(rows, 'series', 'payloads');
    const total = rows.reduce((sum, row) => sum + row.payloads, 0);
    slot.innerHTML = stackedAreaChartHtml({
        width: launchesChartWidth(),
        title: launchesTitle('Payloads launched per year'),
        yTitle: '# PAYLOADS',
        xTitle: '',
        totalText: `${total.toLocaleString('en-GB')} PAYLOADS ${stack.years[0]}–${stack.years[stack.years.length - 1]}`,
        totalTooltip: 'New payloads reaching orbit each year, by launch date, from GCAT (this year: to date), '
            + 'by GCAT sector. Launch failures -- payloads that never reached orbit -- are not counted. '
            + 'Payloads only -- no rocket bodies or debris.',
        stack,
        colours: SECTOR_COLOURS,
        labels: SECTOR_LABELS,
        unit: 'payloads',
    });
}

function drawReentries() {
    const slot = launchChartSlot('reentries');
    if (!slot || !reentriesData) {
        return;
    }
    if (!reentriesData.rows.length) {
        slot.innerHTML = '<p class="orbit-chart-note">NO RE-ENTRY DATA YET -- RUN scripts/ingestGcat.py</p>';
        return;
    }
    const rows = reentriesData.rows.filter((row) => inLaunchYearRange(row.year));
    if (!rows.length) {
        slot.innerHTML = '<p class="orbit-chart-note">NO RE-ENTRIES IN THIS RANGE OF YEARS</p>';
        return;
    }
    const stack = chartStackRows(rows, 'kind', 'objects');
    const total = rows.reduce((sum, row) => sum + row.objects, 0);
    slot.innerHTML = stackedBarChartHtml({
        width: launchesChartWidth(),
        title: launchesTitle('Re-entries per year'),
        yTitle: '# OBJECTS',
        xTitle: '',
        totalText: `${total.toLocaleString('en-GB')} OBJECTS ${stack.years[0]}–${stack.years[stack.years.length - 1]}`,
        totalTooltip: 'Catalogued objects that came back down each year -- re-entered, de-orbited or landed -- '
            + 'from GCAT. Objects that came down attached to another (e.g. docked to a station) are not counted '
            + 'twice, and departures to deep space are not re-entries. Debris too small to catalogue is not '
            + 'included. This year: to date.',
        stack,
        colours: REENTRY_KIND_COLOURS,
        labels: REENTRY_KIND_LABELS,
        unit: 'objects',
    });
}

// Fetches one chart's data into its slot; a failure shows in that slot only.
async function loadLaunchChart(key, url, store, draw) {
    try {
        const response = await fetch(url);
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }
        store(await response.json());
        draw();
    } catch (error) {
        console.error(`Could not load the ${key} chart:`, error);
        const slot = launchChartSlot(key);
        if (slot) {
            slot.innerHTML = '<p class="orbit-chart-note" style="color: var(--red)">ERR: COULD NOT LOAD CHART DATA</p>';
        }
    }
}

function redrawLaunchCharts() {
    drawLaunchesPerYear();
    drawPayloadsPerLaunch();
    drawLaunchesByCountry();
    drawPayloadsLaunched();
    drawReentries();
}

async function renderLaunchesPerYear() {
    launchChartSlot('per-year');
    const query = launchesQuery();
    // One fetch feeds both the launch-attempts chart and the payloads-per-launch one.
    loadLaunchChart('per-year', `api/launches/per-year?${query}`, (d) => { launchesPerYearData = d; },
        () => { drawLaunchesPerYear(); drawPayloadsPerLaunch(); });
    loadLaunchChart('by-country', `api/launches/by-country?${query}`, (d) => { launchesByCountryData = d; },
        drawLaunchesByCountry);
    loadLaunchChart('payloads-launched', `api/launches/payloads-launched?${query}`,
        (d) => { payloadsLaunchedData = d; }, drawPayloadsLaunched);
    loadLaunchChart('reentries', `api/launches/reentries?${query}`, (d) => { reentriesData = d; }, drawReentries);
}

// Redrawn to the new width when the window is resized (debounced), while
// the section is showing.
let launchesResizeTimer = null;
window.addEventListener('resize', () => {
    clearTimeout(launchesResizeTimer);
    launchesResizeTimer = setTimeout(() => {
        const container = document.getElementById('launches-charts');
        if (container && container.offsetParent !== null) {
            redrawLaunchCharts();
        }
    }, 300);
});
