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
   resized.
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
// page in index.html, #launches-definitions.
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

function applyLaunchesMainView() {
    const charts = document.getElementById('launches-charts');
    const definitions = document.getElementById('launches-definitions');
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

// Rounded step for a linear axis: about `targetTicks` ticks up to maxValue.
function niceAxisStep(maxValue, targetTicks = 6) {
    const rough = Math.max(maxValue, 1) / targetTicks;
    const power = 10 ** Math.floor(Math.log10(rough));
    const step = [1, 2, 2.5, 5, 10].map((m) => m * power).find((s) => s >= rough);
    return step;
}

// Shared frame for the SVG charts: size from the area's width, margins,
// and the pill title bar / legend markup around the SVG.
const LCARS_CHART_HEIGHT = 360;
const LCARS_CHART_MARGIN = { top: 24, right: 48, bottom: 34, left: 60 };

function launchesChartWidth() {
    const container = document.getElementById('launches-charts');
    return Math.max(480, container ? container.clientWidth : 900);
}

function escapeChartText(text) {
    return String(text).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/"/g, '&quot;');
}

function chartFrameHtml({ title, yTitle, totalText, totalTooltip, legend, svg }) {
    const legendHtml = legend ? `
            <div class="lcars-chart-legend">${legend.map((item) => `
                <span class="lcars-chart-legend-item"><span class="lcars-chart-swatch" style="background:${item.color}"></span>${escapeChartText(item.label)}</span>`).join('')}
            </div>` : '';
    return `
        <section class="orbit-chart">
            <header class="orbit-chart-header"><span>${title} · ${yTitle}</span><span${totalTooltip
                ? ` class="orbit-chart-total-tip" title="${escapeChartText(totalTooltip)}"` : ''}>${totalText}</span></header>
            ${legendHtml}
            ${svg}
        </section>`;
}

// Years between labelled ticks on a year axis, for a span of `span` years:
// round years, about 5-10 labels whatever range is chosen.
function yearTickStep(span) {
    if (span > 40) {
        return 10;
    }
    if (span > 15) {
        return 5;
    }
    return span > 6 ? 2 : 1;
}

// Linear y grid (faint lines, blue numbers on the left) and the year axis
// along the bottom with its title just above it at the right-hand end.
function chartAxesSvg({ width, plotW, plotH, yMax, step, sy, sx, xMin, xMax, xTitle }) {
    const margin = LCARS_CHART_MARGIN;
    const format = (n) => n.toLocaleString('en-GB');
    let svg = '';
    for (let y = 0; y <= yMax; y += step) {
        svg += `
            <line class="lcars-line-grid" x1="${margin.left}" x2="${margin.left + plotW}" y1="${sy(y)}" y2="${sy(y)}"></line>
            <text class="lcars-line-ytick" x="${margin.left - 8}" y="${sy(y)}" dy="0.35em" text-anchor="end">${format(y)}</text>`;
    }
    svg += `<line class="lcars-line-axis" x1="${margin.left}" x2="${margin.left + plotW}" y1="${margin.top + plotH}" y2="${margin.top + plotH}"></line>`;
    const xStep = yearTickStep(xMax - xMin);
    for (let x = Math.ceil(xMin / xStep) * xStep; x <= xMax; x += xStep) {
        svg += `
            <line class="lcars-line-xtick-mark" x1="${sx(x)}" x2="${sx(x)}" y1="${margin.top + plotH}" y2="${margin.top + plotH + 5}"></line>
            <text class="lcars-line-xtick" x="${sx(x)}" y="${margin.top + plotH + 20}" text-anchor="middle">${x}</text>`;
    }
    if (xTitle) {
        svg += `<text class="lcars-line-axis-title" x="${margin.left + plotW}" y="${margin.top + plotH - 8}" text-anchor="end">${xTitle}</text>`;
    }
    return svg;
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

// Rows of {year, key, value} -> {years, keys (in first-seen order), byYear}.
function stackRows(rows, keyField, valueField) {
    const years = [];
    const keys = [];
    const byYear = {};
    rows.forEach((row) => {
        if (!byYear[row.year]) {
            byYear[row.year] = {};
            years.push(row.year);
        }
        if (!keys.includes(row[keyField])) {
            keys.push(row[keyField]);
        }
        byYear[row.year][row[keyField]] = row[valueField];
    });
    // A series that is zero every year gets no band or legend entry.
    const used = keys.filter((k) => years.some((y) => byYear[y][k]));
    return { years, keys: used, byYear };
}

// Stacked area chart: one band per key, stacked bottom-up in key order;
// hover a year's dot strip for every band's figure.
function stackedAreaChartHtml({ title, yTitle, xTitle, totalText, totalTooltip, stack, colours, labels, unit }) {
    const { years, keys, byYear } = stack;
    const width = launchesChartWidth();
    const margin = LCARS_CHART_MARGIN;
    const plotW = width - margin.left - margin.right;
    const plotH = LCARS_CHART_HEIGHT - margin.top - margin.bottom;
    const totals = years.map((y) => keys.reduce((sum, k) => sum + (byYear[y][k] || 0), 0));
    const step = niceAxisStep(Math.max(...totals));
    const yMax = Math.ceil(Math.max(...totals) / step) * step;
    const xMin = years[0];
    const xMax = years[years.length - 1];
    const sx = (x) => margin.left + ((x - xMin) / (xMax - xMin || 1)) * plotW;
    const sy = (y) => margin.top + plotH - (y / (yMax || 1)) * plotH;
    const format = (n) => n.toLocaleString('en-GB');

    const below = years.map(() => 0);
    const bands = keys.map((key) => {
        const lower = below.slice();
        const upper = years.map((y, i) => lower[i] + (byYear[y][key] || 0));
        upper.forEach((v, i) => { below[i] = v; });
        const top = years.map((y, i) => `${sx(y).toFixed(1)},${sy(upper[i]).toFixed(1)}`);
        const bottom = years.map((y, i) => `${sx(y).toFixed(1)},${sy(lower[i]).toFixed(1)}`).reverse();
        return `<polygon class="lcars-area-band" points="${top.concat(bottom).join(' ')}" fill="${colours[key]}"></polygon>`;
    }).join('');
    // Invisible full-height strips, one per year, carrying its tooltip.
    const half = plotW / Math.max(years.length - 1, 1) / 2;
    const strips = years.map((y, i) => {
        const lines = keys.map((k) => `${labels[k]}: ${format(byYear[y][k] || 0)}`).join('\n');
        return `<rect class="lcars-hover-strip" x="${sx(y) - half}" y="${margin.top}" width="${half * 2}" height="${plotH}">`
            + `<title>${escapeChartText(`${y}: ${format(totals[i])} ${unit}\n${lines}`)}</title></rect>`;
    }).join('');
    const svg = `
        <svg class="lcars-line-chart" width="${width}" height="${LCARS_CHART_HEIGHT}" viewBox="0 0 ${width} ${LCARS_CHART_HEIGHT}" role="img" aria-label="${escapeChartText(title)}">
            ${chartAxesSvg({ width, plotW, plotH, yMax, step, sy, sx, xMin, xMax, xTitle })}
            ${bands}
            ${strips}
        </svg>`;
    return chartFrameHtml({ title, yTitle, totalText, totalTooltip, svg,
        legend: keys.map((k) => ({ label: labels[k], color: colours[k] })) });
}

// Stacked bar chart: one bar per year, segments stacked bottom-up in key
// order; hover a bar for its figures.
function stackedBarChartHtml({ title, yTitle, xTitle, totalText, totalTooltip, stack, colours, labels, unit,
    height = LCARS_CHART_HEIGHT }) {
    const { years, keys, byYear } = stack;
    const width = launchesChartWidth();
    const margin = LCARS_CHART_MARGIN;
    const plotW = width - margin.left - margin.right;
    const plotH = height - margin.top - margin.bottom;
    const totals = years.map((y) => keys.reduce((sum, k) => sum + (byYear[y][k] || 0), 0));
    const step = niceAxisStep(Math.max(...totals));
    const yMax = Math.ceil(Math.max(...totals) / step) * step;
    const xMin = years[0];
    const xMax = years[years.length - 1];
    const slot = plotW / (xMax - xMin + 1);
    const barW = Math.max(1, slot * 0.75);
    // Bars are centred on their year; the axis spans half a slot either side.
    const sx = (x) => margin.left + (x - xMin + 0.5) * slot;
    const sy = (y) => margin.top + plotH - (y / (yMax || 1)) * plotH;
    const format = (n) => n.toLocaleString('en-GB');
    const bars = years.map((y, i) => {
        let base = 0;
        const segments = keys.map((k) => {
            const v = byYear[y][k] || 0;
            if (!v) {
                return '';
            }
            const seg = `<rect x="${sx(y) - barW / 2}" y="${sy(base + v)}" width="${barW}" height="${sy(base) - sy(base + v)}" fill="${colours[k]}"></rect>`;
            base += v;
            return seg;
        }).join('');
        const lines = keys.map((k) => `${labels[k]}: ${format(byYear[y][k] || 0)}`).join('\n');
        return `<g class="lcars-bar">${segments}<title>${escapeChartText(`${y}: ${format(totals[i])} ${unit}\n${lines}`)}</title></g>`;
    }).join('');
    const svg = `
        <svg class="lcars-line-chart" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" role="img" aria-label="${escapeChartText(title)}">
            ${chartAxesSvg({ width, plotW, plotH, yMax, step, sy, sx, xMin, xMax, xTitle })}
            ${bars}
        </svg>`;
    return chartFrameHtml({ title, yTitle, totalText, totalTooltip, svg,
        legend: keys.map((k) => ({ label: labels[k], color: colours[k] })) });
}

// Two-axis line chart: series counted on the left axis (with gridlines) and
// one series on its own scale on a right-hand axis. A legend under the
// title bar names each line (the right-axis one says so). Hover a year for
// every figure. With detachLast, the last year (still in progress) is shown
// as dots only, not joined to the lines.
function dualAxisLineChartHtml({ title, yTitle, totalText, totalTooltip, years, left, right, tooltipOf, detachLast }) {
    const width = launchesChartWidth();
    const height = LCARS_CHART_HEIGHT;
    const margin = { ...LCARS_CHART_MARGIN, right: 60 };
    const plotW = width - margin.left - margin.right;
    const plotH = height - margin.top - margin.bottom;
    const xMin = years[0];
    const xMax = years[years.length - 1];
    const sx = (x) => margin.left + ((x - xMin) / (xMax - xMin || 1)) * plotW;
    const leftTop = Math.max(...left.flatMap((s) => s.values));
    const leftStep = niceAxisStep(leftTop);
    const leftMax = Math.ceil(leftTop / leftStep) * leftStep;
    const rightTop = Math.max(...right.values);
    const rightStep = niceAxisStep(rightTop, 5);
    const rightMax = Math.ceil(rightTop / rightStep) * rightStep;
    const syL = (y) => margin.top + plotH - (y / (leftMax || 1)) * plotH;
    const syR = (y) => margin.top + plotH - (y / (rightMax || 1)) * plotH;
    const format = (n) => n.toLocaleString('en-GB');
    const formatR = (n) => (rightStep < 1 ? n.toFixed(1) : format(n));

    // Left axis, gridlines and year axis (shared helper); right axis numbers.
    let svg = chartAxesSvg({ width, plotW, plotH, yMax: leftMax, step: leftStep, sy: syL, sx, xMin, xMax, xTitle: '' });
    for (let y = 0; y <= rightMax + 1e-9; y += rightStep) {
        svg += `<text class="lcars-line-ytick lcars-line-ytick-right" x="${margin.left + plotW + 8}" y="${syR(y)}" dy="0.35em" text-anchor="start">${formatR(y)}</text>`;
    }
    const lineOf = (values, sy) => {
        const n = detachLast ? values.length - 1 : values.length;
        return values.slice(0, n).map((v, i) => `${i ? 'L' : 'M'}${sx(years[i]).toFixed(1)},${sy(v).toFixed(1)}`).join(' ');
    };
    const lastDots = (values, sy, color) => (detachLast
        ? `<circle cx="${sx(years[years.length - 1])}" cy="${sy(values[values.length - 1])}" r="3.5" fill="${color}"></circle>` : '');
    left.forEach((s) => {
        svg += `<path class="lcars-dual-line" d="${lineOf(s.values, syL)}" stroke="${s.color}"></path>${lastDots(s.values, syL, s.color)}`;
    });
    svg += `<path class="lcars-dual-line lcars-dual-line-right" d="${lineOf(right.values, syR)}" stroke="${right.color}"></path>`
        + lastDots(right.values, syR, right.color);
    // Hover strips, one per year.
    const half = plotW / Math.max(years.length - 1, 1) / 2;
    svg += years.map((y, i) => `<rect class="lcars-hover-strip" x="${sx(y) - half}" y="${margin.top}" width="${half * 2}" height="${plotH}">`
        + `<title>${escapeChartText(tooltipOf(i))}</title></rect>`).join('');

    const legend = [...left.map((s) => ({ label: s.label, color: s.color })),
        { label: `${right.label} (right axis)`, color: right.color }];
    return chartFrameHtml({ title, yTitle, totalText, totalTooltip, legend, svg: `
        <svg class="lcars-line-chart" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" role="img" aria-label="${escapeChartText(title)}">
            ${svg}
        </svg>` });
}

// LCARS line chart: a pill title bar, faint horizontal gridlines with blue
// numbers on the left, a line with a dot per point (hover a dot for its
// figure), years along the bottom, and the x-axis title just above the axis
// at the right-hand end. With detachLast, the last point (e.g. a year still
// in progress) is a dot only, not joined to the line.
function lineChartHtml({ title, totalText, totalTooltip, points, xTitle, yTitle, pointTooltip, detachLast }) {
    const width = launchesChartWidth();
    const height = LCARS_CHART_HEIGHT;
    const margin = LCARS_CHART_MARGIN;
    const plotW = width - margin.left - margin.right;
    const plotH = height - margin.top - margin.bottom;

    const xs = points.map((p) => p.x);
    const xMin = Math.min(...xs);
    const xMax = Math.max(...xs);
    const step = niceAxisStep(Math.max(...points.map((p) => p.y)));
    const yMax = Math.ceil(Math.max(...points.map((p) => p.y)) / step) * step;
    const sx = (x) => margin.left + ((x - xMin) / (xMax - xMin || 1)) * plotW;
    const sy = (y) => margin.top + plotH - (y / (yMax || 1)) * plotH;
    const format = (n) => n.toLocaleString('en-GB');
    const escape = (text) => String(text).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/"/g, '&quot;');

    const grid = [];
    for (let y = 0; y <= yMax; y += step) {
        grid.push(`
            <line class="lcars-line-grid" x1="${margin.left}" x2="${margin.left + plotW}" y1="${sy(y)}" y2="${sy(y)}"></line>
            <text class="lcars-line-ytick" x="${margin.left - 8}" y="${sy(y)}" dy="0.35em" text-anchor="end">${format(y)}</text>`);
    }
    // Year ticks on round years, spaced to the span shown.
    const xStep = yearTickStep(xMax - xMin);
    const xTicks = [];
    for (let x = Math.ceil(xMin / xStep) * xStep; x <= xMax; x += xStep) {
        xTicks.push(`
            <line class="lcars-line-xtick-mark" x1="${sx(x)}" x2="${sx(x)}" y1="${margin.top + plotH}" y2="${margin.top + plotH + 5}"></line>
            <text class="lcars-line-xtick" x="${sx(x)}" y="${margin.top + plotH + 20}" text-anchor="middle">${x}</text>`);
    }
    const joined = detachLast ? points.slice(0, -1) : points;
    const path = joined.map((p, i) => `${i ? 'L' : 'M'}${sx(p.x).toFixed(1)},${sy(p.y).toFixed(1)}`).join(' ');
    const dots = points.map((p) => `
            <circle class="lcars-line-dot" cx="${sx(p.x)}" cy="${sy(p.y)}" r="3"><title>${escape(pointTooltip(p))}</title></circle>`).join('');

    return `
        <section class="orbit-chart">
            <header class="orbit-chart-header"><span>${title} · ${yTitle}</span><span${totalTooltip
                ? ` class="orbit-chart-total-tip" title="${escape(totalTooltip)}"` : ''}>${totalText}</span></header>
            <svg class="lcars-line-chart" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" role="img"
                 aria-label="${escape(title)}">
                ${grid.join('')}
                <line class="lcars-line-axis" x1="${margin.left}" x2="${margin.left + plotW}"
                      y1="${margin.top + plotH}" y2="${margin.top + plotH}"></line>
                ${xTicks.join('')}
                <text class="lcars-line-axis-title" x="${margin.left + plotW}" y="${margin.top + plotH - 8}"
                      text-anchor="end">${xTitle}</text>
                <path class="lcars-line-path" d="${path}"></path>
                ${dots}
            </svg>
        </section>`;
}

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
    const stack = stackRows(rows, 'country', 'launches');
    const total = rows.reduce((sum, row) => sum + row.launches, 0);
    slot.innerHTML = stackedBarChartHtml({
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
    const stack = stackRows(rows, 'series', 'payloads');
    const total = rows.reduce((sum, row) => sum + row.payloads, 0);
    slot.innerHTML = stackedAreaChartHtml({
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
    const stack = stackRows(rows, 'kind', 'objects');
    const total = rows.reduce((sum, row) => sum + row.objects, 0);
    slot.innerHTML = stackedBarChartHtml({
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
