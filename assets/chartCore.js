/* ==========================================================================
   CHART CORE -- the one copy of the LCARS chart code shared by the panels
   (LAUNCHES and ON-ORBIT now; WEATHER follows). Plain functions that return
   HTML / SVG strings: a panel puts the string in a slot's innerHTML. No
   state, no DOM access except chartWidth().

   Loaded before the panel that uses it: each panel opener in lcars.js does
   `await loadScriptOnce('assets/chartCore.js')` first. The markup and the
   CSS classes (.orbit-chart, .lcars-line-chart, .lcars-chart-legend, ...
   in classic.css) are exactly those the panels always produced.

   Every chart takes ONE config object. Common keys:
     title, yTitle         pill title bar: "title · yTitle" (yTitle optional)
     totalText             text at the right-hand end of the title bar
     totalTooltip          hover text for the total (optional)
     width                 pixels (chartWidth(...) of the panel's area)
     height                pixels (default LCARS_CHART_HEIGHT)
   The charts:
     lineChartHtml({ points: [{x, y}], xTitle, pointTooltip(p), detachLast })
     dualAxisLineChartHtml({ years, left: [{label, color, values}],
                             right: {label, color, values}, tooltipOf(i), detachLast })
     stackedAreaChartHtml / stackedBarChartHtml({ stack, colours, labels, unit, xTitle })
         stack = chartStackRows(rows, keyField, valueField)
     pieChartHtml({ slices: [{label, value, color}] })
     logBarChartHtml({ rows: [{label, value, muted}], axisTitle })     log-scale horizontal bars
     rankedColumnChartHtml({ rows, tooltipOf(row) })                   log-scale ranked columns
     columnHistogramHtml({ buckets: [{from, to, value}], xTitle, yTitle, xTickEvery, unit })
     barsAndLineSvg({ width, years, bars, line, tooltipOf(i) })        <svg> only: give it to chartFrameHtml's `svg`
   Building blocks for the panels' own charts: chartFrameHtml, chartAxesSvg,
   chartRightTicksSvg, chartSvgHtml, chartLinearAxis, niceAxisStep, yearTickStep,
   logAxisTop, logAxisPercent, logAxisTicks, escapeChartText, chartWidth.
   ========================================================================== */

const LCARS_CHART_HEIGHT = 360;
const LCARS_CHART_MARGIN = { top: 24, right: 48, bottom: 34, left: 60 };

// Width available to a chart: the container's (element or id), at least
// minWidth; 900 when there is no container (e.g. not yet in the page).
function chartWidth(container, minWidth = 480) {
    const element = typeof container === 'string' ? document.getElementById(container) : container;
    return Math.max(minWidth, element ? element.clientWidth : 900);
}

function escapeChartText(text) {
    return String(text).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/"/g, '&quot;');
}

// Rounded step for a linear axis: about `targetTicks` ticks up to maxValue.
function niceAxisStep(maxValue, targetTicks = 6) {
    const rough = Math.max(maxValue, 1) / targetTicks;
    const power = 10 ** Math.floor(Math.log10(rough));
    const step = [1, 2, 2.5, 5, 10].map((m) => m * power).find((s) => s >= rough);
    return step;
}

// {step, max}: a linear axis from 0 up to the first multiple of step at or
// above maxValue.
function chartLinearAxis(maxValue, targetTicks = 6) {
    const step = niceAxisStep(maxValue, targetTicks);
    return { step, max: Math.ceil(maxValue / step) * step };
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

// Shared frame: the pill title bar (title · yTitle, total with an optional
// tooltip at the right-hand end), an optional legend of {label, color}, then
// the body (`svg`, or any HTML such as the pie).
function chartFrameHtml({ title, yTitle, totalText, totalTooltip, legend, svg }) {
    const legendHtml = legend && legend.length ? `
            <div class="lcars-chart-legend">${legend.map((item) => `
                <span class="lcars-chart-legend-item"><span class="lcars-chart-swatch" style="background:${item.color}"></span>${escapeChartText(item.label)}</span>`).join('')}
            </div>` : '';
    return `
        <section class="orbit-chart">
            <header class="orbit-chart-header"><span>${title}${yTitle ? ` · ${yTitle}` : ''}</span><span${totalTooltip
                ? ` class="orbit-chart-total-tip" title="${escapeChartText(totalTooltip)}"` : ''}>${totalText}</span></header>
            ${legendHtml}
            ${svg}
        </section>`;
}

// The <svg> element around a chart's parts (strings), with its accessible
// label (none when title is undefined).
function chartSvgHtml(width, height, title, parts) {
    const label = title === undefined ? '' : ` aria-label="${escapeChartText(title)}"`;
    return `
        <svg class="lcars-line-chart" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" role="img"${label}>
            ${parts.join('\n            ')}
        </svg>`;
}

// Linear y grid (faint lines, blue numbers on the left) and the year axis
// along the bottom with its title just above it at the right-hand end.
// margin: the chart's own margin (default LCARS_CHART_MARGIN). xTicks: the
// x values to label (default: round years, every yearTickStep).
function chartAxesSvg({ width, plotW, plotH, yMax, step, sy, sx, xMin, xMax, xTitle, xTicks, margin = LCARS_CHART_MARGIN }) {
    const format = (n) => n.toLocaleString('en-GB');
    let svg = '';
    for (let y = 0; y <= yMax + 1e-9; y += step) {
        svg += `
            <line class="lcars-line-grid" x1="${margin.left}" x2="${margin.left + plotW}" y1="${sy(y)}" y2="${sy(y)}"></line>
            <text class="lcars-line-ytick" x="${margin.left - 8}" y="${sy(y)}" dy="0.35em" text-anchor="end">${format(y)}</text>`;
    }
    svg += `<line class="lcars-line-axis" x1="${margin.left}" x2="${margin.left + plotW}" y1="${margin.top + plotH}" y2="${margin.top + plotH}"></line>`;
    let ticks = xTicks;
    if (!ticks) {
        const xStep = yearTickStep(xMax - xMin);
        ticks = [];
        for (let x = Math.ceil(xMin / xStep) * xStep; x <= xMax; x += xStep) {
            ticks.push(x);
        }
    }
    ticks.forEach((x) => {
        svg += `
            <line class="lcars-line-xtick-mark" x1="${sx(x)}" x2="${sx(x)}" y1="${margin.top + plotH}" y2="${margin.top + plotH + 5}"></line>
            <text class="lcars-line-xtick" x="${sx(x)}" y="${margin.top + plotH + 20}" text-anchor="middle">${x}</text>`;
    });
    if (xTitle) {
        svg += `<text class="lcars-line-axis-title" x="${margin.left + plotW}" y="${margin.top + plotH - 8}" text-anchor="end">${xTitle}</text>`;
    }
    return svg;
}

// Numbers for a right-hand axis, at x, one per step up to yMax. extraClass
// (optional) is added to the text's class.
function chartRightTicksSvg({ x, yMax, step, sy, format, extraClass = '' }) {
    let svg = '';
    for (let y = 0; y <= yMax + 1e-9; y += step) {
        svg += `<text class="lcars-line-ytick${extraClass ? ` ${extraClass}` : ''}" x="${x}" y="${sy(y)}" dy="0.35em" text-anchor="start">${format(y)}</text>`;
    }
    return svg;
}

// Rows of {year, key, value} -> {years, keys (in first-seen order), byYear}.
function chartStackRows(rows, keyField, valueField) {
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
function stackedAreaChartHtml({ title, yTitle, xTitle, totalText, totalTooltip, stack, colours, labels, unit,
    width = chartWidth(null), height = LCARS_CHART_HEIGHT }) {
    const { years, keys, byYear } = stack;
    const margin = LCARS_CHART_MARGIN;
    const plotW = width - margin.left - margin.right;
    const plotH = height - margin.top - margin.bottom;
    const totals = years.map((y) => keys.reduce((sum, k) => sum + (byYear[y][k] || 0), 0));
    const { step, max: yMax } = chartLinearAxis(Math.max(...totals));
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
    const svg = chartSvgHtml(width, height, title,
        [chartAxesSvg({ width, plotW, plotH, yMax, step, sy, sx, xMin, xMax, xTitle }), bands, strips]);
    return chartFrameHtml({ title, yTitle, totalText, totalTooltip, svg,
        legend: keys.map((k) => ({ label: labels[k], color: colours[k] })) });
}

// Stacked bar chart: one bar per year, segments stacked bottom-up in key
// order; hover a bar for its figures.
function stackedBarChartHtml({ title, yTitle, xTitle, totalText, totalTooltip, stack, colours, labels, unit,
    width = chartWidth(null), height = LCARS_CHART_HEIGHT }) {
    const { years, keys, byYear } = stack;
    const margin = LCARS_CHART_MARGIN;
    const plotW = width - margin.left - margin.right;
    const plotH = height - margin.top - margin.bottom;
    const totals = years.map((y) => keys.reduce((sum, k) => sum + (byYear[y][k] || 0), 0));
    const { step, max: yMax } = chartLinearAxis(Math.max(...totals));
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
    const svg = chartSvgHtml(width, height, title,
        [chartAxesSvg({ width, plotW, plotH, yMax, step, sy, sx, xMin, xMax, xTitle }), bars]);
    return chartFrameHtml({ title, yTitle, totalText, totalTooltip, svg,
        legend: keys.map((k) => ({ label: labels[k], color: colours[k] })) });
}

// Two-axis line chart: series counted on the left axis (with gridlines) and
// one series on its own scale on a right-hand axis. A legend under the
// title bar names each line (the right-axis one says so). Hover a year for
// every figure. With detachLast, the last year (still in progress) is shown
// as dots only, not joined to the lines.
function dualAxisLineChartHtml({ title, yTitle, totalText, totalTooltip, years, left, right, tooltipOf, detachLast,
    width = chartWidth(null), height = LCARS_CHART_HEIGHT }) {
    const margin = { ...LCARS_CHART_MARGIN, right: 60 };
    const plotW = width - margin.left - margin.right;
    const plotH = height - margin.top - margin.bottom;
    const xMin = years[0];
    const xMax = years[years.length - 1];
    const sx = (x) => margin.left + ((x - xMin) / (xMax - xMin || 1)) * plotW;
    const { step: leftStep, max: leftMax } = chartLinearAxis(Math.max(...left.flatMap((s) => s.values)));
    const { step: rightStep, max: rightMax } = chartLinearAxis(Math.max(...right.values), 5);
    const syL = (y) => margin.top + plotH - (y / (leftMax || 1)) * plotH;
    const syR = (y) => margin.top + plotH - (y / (rightMax || 1)) * plotH;
    const format = (n) => n.toLocaleString('en-GB');
    const formatR = (n) => (rightStep < 1 ? n.toFixed(1) : format(n));

    // Left axis, gridlines and year axis (shared helper); right axis numbers.
    let svg = chartAxesSvg({ width, plotW, plotH, yMax: leftMax, step: leftStep, sy: syL, sx, xMin, xMax, xTitle: '' });
    svg += chartRightTicksSvg({ x: margin.left + plotW + 8, yMax: rightMax, step: rightStep, sy: syR, format: formatR,
        extraClass: 'lcars-line-ytick-right' });
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
    return chartFrameHtml({ title, yTitle, totalText, totalTooltip, legend, svg: chartSvgHtml(width, height, title, [svg]) });
}

// LCARS line chart: a pill title bar, faint horizontal gridlines with blue
// numbers on the left, a line with a dot per point (hover a dot for its
// figure), years along the bottom, and the x-axis title just above the axis
// at the right-hand end. With detachLast, the last point (e.g. a year still
// in progress) is a dot only, not joined to the line.
function lineChartHtml({ title, totalText, totalTooltip, points, xTitle, yTitle, pointTooltip, detachLast,
    width = chartWidth(null), height = LCARS_CHART_HEIGHT }) {
    const margin = LCARS_CHART_MARGIN;
    const plotW = width - margin.left - margin.right;
    const plotH = height - margin.top - margin.bottom;
    const xs = points.map((p) => p.x);
    const xMin = Math.min(...xs);
    const xMax = Math.max(...xs);
    const { step, max: yMax } = chartLinearAxis(Math.max(...points.map((p) => p.y)));
    const sx = (x) => margin.left + ((x - xMin) / (xMax - xMin || 1)) * plotW;
    const sy = (y) => margin.top + plotH - (y / (yMax || 1)) * plotH;
    const joined = detachLast ? points.slice(0, -1) : points;
    const path = joined.map((p, i) => `${i ? 'L' : 'M'}${sx(p.x).toFixed(1)},${sy(p.y).toFixed(1)}`).join(' ');
    const dots = points.map((p) => `
            <circle class="lcars-line-dot" cx="${sx(p.x)}" cy="${sy(p.y)}" r="3"><title>${escapeChartText(pointTooltip(p))}</title></circle>`).join('');
    const svg = chartSvgHtml(width, height, title, [
        chartAxesSvg({ width, plotW, plotH, yMax, step, sy, sx, xMin, xMax, xTitle }),
        `<path class="lcars-line-path" d="${path}"></path>`,
        dots]);
    return chartFrameHtml({ title, yTitle, totalText, totalTooltip, svg });
}

// Pie chart: a disc (conic gradient, slices clockwise from 12 o'clock in
// row order) beside a legend -- swatch, label, count and share for every
// slice, including those too thin to see.
function pieChartHtml({ title, totalText, totalTooltip, slices }) {
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
    return chartFrameHtml({ title, totalText, totalTooltip, svg: `<div class="orbit-pie">
                <div class="orbit-pie-disc" style="background: conic-gradient(${stops})"></div>
                <div class="orbit-pie-legend">${legend}</div>
            </div>` });
}

/* --- Log-scale charts (HTML, sized by CSS) ---------------------------------- */

// Log-scale axis: from 1 up to the next power of ten above the largest
// value, one tick per power of ten (1, 10, 100 ...). Bars start at 1, so a
// count of 1 is a stub, not a missing bar.
function logAxisTop(maxValue) {
    return 10 ** Math.max(1, Math.ceil(Math.log10(Math.max(maxValue, 1))));
}

function logAxisPercent(value, top) {
    return value <= 1 ? 0 : (Math.log10(value) / Math.log10(top)) * 100;
}

// The ticks of a log axis: 1, 10, 100 ... top.
function logAxisTicks(top) {
    const ticks = [];
    for (let value = 1; value <= top; value *= 10) {
        ticks.push(value);
    }
    return ticks;
}

// Horizontal bars on a log axis: a row per item -- label, bar and the exact
// count just past the bar's end -- and a numbered axis under the bars, its
// title (axisTitle) just above the axis at the right-hand end. A row with
// `muted` is drawn in the muted colour (e.g. "Other").
function logBarChartHtml({ title, totalText, totalTooltip, rows, axisTitle }) {
    const top = logAxisTop(Math.max(...rows.map((row) => row.value)));
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
            <span class="orbit-chart-axis-title">${axisTitle}</span>${logAxisTicks(top).map((value) => `
            <span class="orbit-chart-tick" style="left:${logAxisPercent(value, top)}%">${format(value)}</span>`).join('')}
        </div>`;
    return chartFrameHtml({ title, totalText, totalTooltip, svg: `<div class="orbit-chart-grid">${barRows}${axis}</div>` });
}

// The part shared by the two vertical-bar charts: log count axis on the
// left with faint gridlines, the columns, and lowerHtml under the plot.
function logColumnsHtml({ top, columns, lowerHtml, modifier = '' }) {
    const format = (n) => n.toLocaleString('en-GB');
    const yTicks = logAxisTicks(top);
    return `<div class="orbit-histogram${modifier}">
                <div class="orbit-histogram-yaxis">${yTicks.map((value) => `
                    <span class="orbit-histogram-ytick" style="bottom:${logAxisPercent(value, top)}%">${format(value)}</span>`).join('')}
                </div>
                <div class="orbit-histogram-plot">${yTicks.map((value) => `
                    <div class="orbit-histogram-grid" style="bottom:${logAxisPercent(value, top)}%"></div>`).join('')}
                    ${columns}
                </div>
                <div></div>
                ${lowerHtml}
            </div>`;
}

// Ranked vertical-bar chart (owners): log count axis on the left with
// faint gridlines, one bar per item, largest first, its count above it, and
// the item's name turned 90 degrees under the x axis (reading upwards).
// Each bar's tooltip gives tooltipOf(row); a row's percentText, if given,
// is written up the inside of its bar. Shares the histogram's styles.
function rankedColumnChartHtml({ title, yTitle, totalText, totalTooltip, rows, tooltipOf }) {
    const top = logAxisTop(Math.max(...rows.map((row) => row.value)));
    const format = (n) => n.toLocaleString('en-GB');
    const columns = rows.map((row) => {
        const height = logAxisPercent(row.value, top);
        return `
            <div class="orbit-histogram-col" title="${escapeChartText(tooltipOf(row))}">
                <div class="orbit-histogram-bar${row.muted ? ' orbit-chart-bar-muted' : ''}" style="height:${height}%">${row.percentText
                    ? `<span class="orbit-bar-percent">${row.percentText}</span>` : ''}</div>
                <span class="orbit-histogram-value" style="bottom:${height}%">${format(row.value)}</span>
            </div>`;
    }).join('');
    const labels = rows.map((row) => `
            <div class="orbit-ranked-label" title="${escapeChartText(tooltipOf(row))}"><span>${escapeChartText(row.label)}</span></div>`).join('');
    return chartFrameHtml({ title, yTitle, totalText, totalTooltip, svg: logColumnsHtml({
        top, columns, modifier: ' orbit-ranked', lowerHtml: `<div class="orbit-ranked-labels">${labels}</div>` }) });
}

// Vertical-bar histogram (flat bars, pill-rounded tops): log count axis on
// the left with faint gridlines (its title, yTitle, in the header bar after
// the chart title), one column per bucket {from, to, value} with its count
// just above the bar (blank when zero), and an x axis numbered every
// xTickEvery units under the bucket edges, its title (xTitle) just above
// the axis at the right-hand end. unit is written after a bucket's range in
// its tooltip ("15–20°: 12").
function columnHistogramHtml({ title, yTitle, xTitle, totalText, totalTooltip, buckets, xTickEvery, unit = '' }) {
    const top = logAxisTop(Math.max(...buckets.map((bucket) => bucket.value)));
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
            <div class="orbit-histogram-col" title="${escapeChartText(`${bucket.from}–${bucket.to}${unit}: ${format(bucket.value)}`)}">
                ${bucket.value ? `
                <div class="orbit-histogram-bar" style="height:${height}%"></div>
                <span class="orbit-histogram-value" style="bottom:${height}%">${format(bucket.value)}</span>` : ''}
            </div>`;
    }).join('');
    const lowerHtml = `<div class="orbit-chart-axis">
                    <span class="orbit-chart-axis-title">${xTitle}</span>${xTicks.map((value) => `
                    <span class="orbit-chart-tick" style="left:${xPercent(value)}%">${value}</span>`).join('')}
                </div>`;
    return chartFrameHtml({ title, yTitle, totalText, totalTooltip, svg: logColumnsHtml({ top, columns, lowerHtml }) });
}

/* --- Bars and a line over years (SVG) --------------------------------------- */

// Bars for one series on the left axis, a line for another on its own
// right-hand axis (dots at each point), over a run of years -- one slot per
// entry of `years`, in order. Hover a year for tooltipOf(i). Linear scales.
// Returns the <svg> string, for chartFrameHtml's `svg`.
function barsAndLineSvg({ width, height = 340, years, bars, line, tooltipOf }) {
    const margin = { top: 16, right: 64, bottom: 34, left: 60 };
    const plotW = width - margin.left - margin.right;
    const plotH = height - margin.top - margin.bottom;
    const left = chartLinearAxis(Math.max(...bars.values, 1), 5);
    const right = chartLinearAxis(Math.max(...line.values, 1), 5);
    const slot = plotW / years.length;
    const barW = Math.max(1, slot * 0.75);
    const cx = (i) => margin.left + (i + 0.5) * slot;
    const sx = (year) => cx(years.indexOf(year));
    const syL = (v) => margin.top + plotH - (v / left.max) * plotH;
    const syR = (v) => margin.top + plotH - (v / right.max) * plotH;
    const format = (n) => Number(n).toLocaleString('en-GB');
    // Left axis and gridlines, years that are multiples of ten along the bottom.
    let svg = chartAxesSvg({ width, plotW, plotH, yMax: left.max, step: left.step, sy: syL, sx, margin,
        xMin: years[0], xMax: years[years.length - 1], xTicks: years.filter((y) => y % 10 === 0) });
    svg += chartRightTicksSvg({ x: margin.left + plotW + 8, yMax: right.max, step: right.step, sy: syR, format });
    years.forEach((y, i) => {
        const v = bars.values[i];
        if (v) {
            svg += `<rect x="${cx(i) - barW / 2}" y="${syL(v)}" width="${barW}" height="${margin.top + plotH - syL(v)}" fill="${bars.color}"></rect>`;
        }
    });
    const path = years.map((y, i) => `${i ? 'L' : 'M'}${cx(i).toFixed(1)},${syR(line.values[i]).toFixed(1)}`).join(' ');
    svg += `<path class="lcars-dual-line" d="${path}" stroke="${line.color}"></path>`;
    svg += years.map((y, i) => `<rect class="lcars-hover-strip" x="${cx(i) - slot / 2}" y="${margin.top}" width="${slot}" height="${plotH}">`
        + `<title>${escapeChartText(tooltipOf(i))}</title></rect>`).join('');
    return chartSvgHtml(width, height, undefined, [svg]);
}

/* --- Stacked columns over categories (SVG) ---------------------------------- */

// Stacked vertical bars over categories (bands), one segment per series
// {color}, linear scale -- or, with a single series, optionally log. Hover a
// bar for tooltipOf(category, i, total). labelOf(category, i) gives the
// x-axis label ('' for none). centreLabels: each label under the middle of
// its bar -- for categories (VLEO, Ku ...) and whole units (ages); otherwise
// at the bar's left edge, as a band boundary (0°, 15°, 250 km ...).
// valueOf(category, series) gives a segment's value. Returns the <svg> string,
// for chartFrameHtml's `svg`.
function stackedColumnsSvg({ width, height = 300, categories, series, valueOf, labelOf, log = false,
    tooltipOf, xTitle, centreLabels = false }) {
    const m = { top: 16, right: 24, bottom: 34, left: 60 };
    const plotW = width - m.left - m.right;
    const plotH = height - m.top - m.bottom;
    const totals = categories.map((c) => series.reduce((sum, s) => sum + (valueOf(c, s) || 0), 0));
    const maxTotal = Math.max(...totals, 1);
    let sy;
    let ticks;
    if (log) {
        const top = logAxisTop(maxTotal);
        sy = (v) => m.top + plotH - (v <= 1 ? 0 : (Math.log10(v) / Math.log10(top)) * plotH);
        ticks = logAxisTicks(top);
    } else {
        const { step, max: top } = chartLinearAxis(maxTotal, 5);
        sy = (v) => m.top + plotH - (v / top) * plotH;
        ticks = [];
        for (let v = 0; v <= top + 1e-9; v += step) {
            ticks.push(v);
        }
    }
    const format = (n) => n.toLocaleString('en-GB');
    const slot = plotW / categories.length;
    const barW = Math.max(1, slot * 0.8);
    let svg = ticks.map((v) => `
        <line class="lcars-line-grid" x1="${m.left}" x2="${m.left + plotW}" y1="${sy(v)}" y2="${sy(v)}"></line>
        <text class="lcars-line-ytick" x="${m.left - 8}" y="${sy(v)}" dy="0.35em" text-anchor="end">${format(v)}</text>`).join('');
    svg += `<line class="lcars-line-axis" x1="${m.left}" x2="${m.left + plotW}" y1="${m.top + plotH}" y2="${m.top + plotH}"></line>`;
    categories.forEach((c, i) => {
        const x = m.left + i * slot + (slot - barW) / 2;
        let base = 0;
        let segments = '';
        series.forEach((s) => {
            const v = valueOf(c, s) || 0;
            if (!v) {
                return;
            }
            const y0 = log ? sy(Math.max(base, 1)) : sy(base);
            const y1 = sy(base + v);
            segments += `<rect x="${x}" y="${Math.min(y0, y1)}" width="${barW}" height="${Math.max(Math.abs(y0 - y1), log ? 2 : 0)}" fill="${s.color}"></rect>`;
            base += v;
        });
        svg += `<g class="lcars-bar">${segments}<title>${escapeChartText(tooltipOf(c, i, totals[i]))}</title></g>`;
        const label = labelOf(c, i);
        if (label) {
            const lx = m.left + (centreLabels ? (i + 0.5) * slot : i * slot);
            svg += `<line class="lcars-line-xtick-mark" x1="${lx}" x2="${lx}" y1="${m.top + plotH}" y2="${m.top + plotH + 5}"></line>
                <text class="lcars-line-xtick" x="${lx}" y="${m.top + plotH + 20}" text-anchor="middle">${label}</text>`;
        }
    });
    if (xTitle) {
        svg += `<text class="lcars-line-axis-title" x="${m.left + plotW}" y="${m.top + plotH - 8}" text-anchor="end">${xTitle}</text>`;
    }
    return chartSvgHtml(width, height, undefined, [svg]);
}
