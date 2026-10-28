/* ==========================================================================
   CHART TIME -- the time-series half of the chart core, for the WEATHER
   charts. Loaded after assets/chartCore.js (it uses escapeChartText() and
   chartSvgHtml()) and only by the views that draw time charts, so LAUNCHES
   and ON-ORBIT do not carry it. Plain functions that return strings; no
   state beyond a counter for unique ids; no DOM access.

   Times are milliseconds since 1970 (UTC), as Date.parse() gives them.

   timePanelsSvg({ width, t0, t1, panels, events, hoverText, forecastFrom, idPrefix })
     One <svg>: the panels stacked on ONE shared UTC time axis (ticks and
     faint day lines run through every panel; labels once, at the bottom).
       panel   = { height, left: axis, right: axis, marks: [mark], lines: [line], title }
       axis    = { min, max, step | ticks, log, invert, format, label, color, classes }
                 log: decades; invert: larger values lower down (Dst);
                 classes: [{ from, to, label }] letters in faint bands (A-X, S1-S5);
                 color: the axis numbers and title in the colour of their line.
       mark    = { type: 'line' | 'area' | 'bars' | 'shade', axis: 'left' | 'right',
                   points: [[ms, value]] (null value = gap), color, width, dash,
                   gapMs (a longer gap between points is drawn as a gap),
                   step (+ stepMs) for hourly values stamped at the start of the hour,
                   forecastFrom (ms): from there the line is dashed and the panel hatched,
                   area: base, colourPos, colourNeg (a signed area with a zero line),
                   shade: runs [[ms, ms]] and color (a pale band behind the data) }
       line    = { axis, value, label, color, dash }   a threshold line (R1, S1, G1 ...)
       events  = [{ t, label, color, hollow }]   vertical markers through every panel
       hoverText(ms) -> string   the tooltip of the time under the pointer
   chartTipFrameHtml / chartSectionBarHtml   the pill with a detailed tooltip and
   the full-width section bar (NOW, PREDICTIVE).
   ========================================================================== */

const CHART_MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const CHART_TIME_STEPS = [1, 2, 5, 10, 15, 30, 60, 120, 180, 360, 720, 1440, 2880, 10080].map((minutes) => minutes * 60000);
const TIME_PANEL_MARGIN = { top: 16, right: 64, bottom: 36, left: 64, gap: 14 };
let chartTimeSeq = 0;

// Ticks on round UTC times, about `target` of them over t0..t1.
function chartTimeTicks(t0, t1, target = 7) {
    if (t1 - t0 > 100 * 86400000) {
        return chartCalendarTicks(t0, t1, target);
    }
    const rough = (t1 - t0) / target;
    const step = CHART_TIME_STEPS.find((s) => s >= rough) || CHART_TIME_STEPS[CHART_TIME_STEPS.length - 1];
    const ticks = [];
    for (let t = Math.ceil(t0 / step) * step; t <= t1; t += step) {
        ticks.push(t);
    }
    return { step, ticks };
}

// Long spans: ticks on the 1st of a month (every 1, 2, 3 or 6 months) or on 1 January (every 1, 2, 5, 10 or 20 years).
function chartCalendarTicks(t0, t1, target) {
    const ticks = [];
    const years = (t1 - t0) / (365.25 * 86400000);
    if (years > 3) {
        const stepYears = [1, 2, 5, 10, 20].find((y) => y >= years / target) || 20;
        for (let y = Math.ceil(new Date(t0).getUTCFullYear() / stepYears) * stepYears; Date.UTC(y, 0, 1) <= t1; y += stepYears) {
            if (Date.UTC(y, 0, 1) >= t0) { ticks.push(Date.UTC(y, 0, 1)); }
        }
        return { step: 'year', ticks };
    }
    const stepMonths = [1, 2, 3, 6].find((m) => m >= (t1 - t0) / (30.44 * 86400000) / target) || 6;
    for (let i = new Date(t0).getUTCFullYear() * 12 + new Date(t0).getUTCMonth(); Date.UTC(Math.floor(i / 12), i % 12, 1) <= t1; i += 1) {
        const t = Date.UTC(Math.floor(i / 12), i % 12, 1);
        if (i % stepMonths === 0 && t >= t0) { ticks.push(t); }
    }
    return { step: 'month', ticks };
}

// "HH:MM" within a day, "24 Oct" at midnight and whenever the step is a day or more.
function chartTimeLabel(ms, step) {
    const d = new Date(ms);
    if (step === 'year') {
        return String(d.getUTCFullYear());
    }
    if (step === 'month') {
        return `${CHART_MONTHS[d.getUTCMonth()]} ${d.getUTCFullYear()}`;
    }
    if (step >= 86400000 || (d.getUTCHours() === 0 && d.getUTCMinutes() === 0)) {
        return `${d.getUTCDate()} ${CHART_MONTHS[d.getUTCMonth()]}`;
    }
    const two = (n) => String(n).padStart(2, '0');
    return `${two(d.getUTCHours())}:${two(d.getUTCMinutes())}`;
}

// "2026-10-24 19:07 UTC" for tooltips.
function chartTimeText(ms) {
    return `${new Date(ms).toISOString().slice(0, 16).replace('T', ' ')} UTC`;
}

// Index of the sample nearest in time to ms (times sorted), or -1 if none.
function chartNearest(times, ms) {
    if (!times.length) {
        return -1;
    }
    let lo = 0;
    let hi = times.length - 1;
    while (lo < hi) {
        const mid = (lo + hi) >> 1;
        if (times[mid] < ms) {
            lo = mid + 1;
        } else {
            hi = mid;
        }
    }
    return lo > 0 && ms - times[lo - 1] < times[lo] - ms ? lo - 1 : lo;
}

// Points split into runs wherever the value is missing or the gap between
// neighbours is longer than gapMs: a gap is drawn as a gap.
function chartRuns(points, gapMs) {
    const runs = [];
    let run = [];
    let last = null;
    points.forEach((p) => {
        if (p[1] === null || p[1] === undefined || Number.isNaN(p[1])) {
            last = null;
            if (run.length) { runs.push(run); }
            run = [];
            return;
        }
        if (last !== null && gapMs && p[0] - last > gapMs && run.length) {
            runs.push(run);
            run = [];
        }
        run.push(p);
        last = p[0];
    });
    if (run.length) { runs.push(run); }
    return runs;
}

// ms-to-pixel and value-to-pixel functions; values outside the axis are held at its ends.
function chartValueScale(axis, top, bottom) {
    const lo = axis.log ? Math.log10(axis.min) : axis.min;
    const hi = axis.log ? Math.log10(axis.max) : axis.max;
    return (value) => {
        const v = axis.log ? Math.log10(Math.max(value, axis.min)) : value;
        let f = Math.min(1, Math.max(0, (v - lo) / (hi - lo)));
        if (axis.invert) { f = 1 - f; }
        return bottom - f * (bottom - top);
    };
}

function chartAxisTicks(axis) {
    if (axis.ticks) { return axis.ticks; }
    const ticks = [];
    if (axis.log) {
        for (let e = Math.ceil(Math.log10(axis.min) - 1e-9); e <= Math.log10(axis.max) + 1e-9; e += 1) {
            ticks.push(10 ** e);
        }
    } else {
        for (let v = axis.min; v <= axis.max + 1e-9; v += axis.step) { ticks.push(v); }
    }
    return ticks;
}

const chartPoint = (x, y) => `${x.toFixed(1)},${y.toFixed(1)}`;

// A signed area between the values and a base line: polygons above it
// (pos) and below it (neg), split exactly where the line crosses the base.
function chartSignedAreas(run, sx, sy, base) {
    const out = { pos: [], neg: [] };
    const yBase = sy(base);
    let current = null;
    const close = () => {
        if (current && current.pts.length > 1) {
            const p = current.pts;
            out[current.sign > 0 ? 'pos' : 'neg'].push([[p[0][0], yBase], ...p, [p[p.length - 1][0], yBase]]
                .map((q) => chartPoint(q[0], q[1])).join(' '));
        }
        current = null;
    };
    let previous = null;
    run.forEach((p) => {
        const sign = p[1] > base ? 1 : p[1] < base ? -1 : (current ? current.sign : 1);
        if (previous && current && sign !== current.sign) {
            const f = (base - previous[1]) / (p[1] - previous[1]);
            const xc = sx(previous[0] + f * (p[0] - previous[0]));
            current.pts.push([xc, yBase]);
            close();
            current = { sign, pts: [[xc, yBase]] };
        }
        if (!current) { current = { sign, pts: [] }; }
        current.pts.push([sx(p[0]), sy(p[1])]);
        previous = p;
    });
    close();
    return out;
}

// One mark of a panel, as SVG.
function chartMarkSvg(mark, ctx) {
    const { sx, scales, t0, t1 } = ctx;
    const sy = scales[mark.axis || 'left'];
    const points = (mark.points || []).filter((p) => p[0] >= t0 && p[0] <= t1);
    if (mark.type === 'shade') {
        return (mark.runs || []).map(([a, b]) => `<rect class="chart-shade" x="${sx(Math.max(a, t0)).toFixed(1)}" y="${ctx.top}" `
            + `width="${Math.max(1, sx(Math.min(b, t1)) - sx(Math.max(a, t0))).toFixed(1)}" height="${ctx.bottom - ctx.top}" fill="${mark.color}"></rect>`).join('');
    }
    const runs = chartRuns(points, mark.gapMs);
    if (mark.type === 'dots') {
        // a dot per point; a point's third element {r, color, hollow, tip} overrides the mark's (hollow = open ring)
        return points.filter((p) => p[1] !== null).map((p) => {
            const o = p[2] || {};
            const colour = o.color || mark.color;
            return `<circle${o.tip ? ' class="chart-hit"' : ''} cx="${sx(p[0]).toFixed(1)}" cy="${sy(p[1]).toFixed(1)}" r="${o.r || mark.r || 2.5}" `
                + `fill="${o.hollow ? '#000' : colour}" stroke="${colour}" stroke-width="${o.hollow ? 1.5 : 0}">${o.tip ? `<title>${escapeChartText(o.tip)}</title>` : ''}</circle>`;
        }).join('');
    }
    if (mark.type === 'spans') {
        // thick horizontal bars from one time to another at a value: {from, to, v, color, width, dash, opacity, tip}
        return (mark.items || []).filter((i) => i.to >= t0 && i.from <= t1).map((i) => {
            const y = sy(i.v).toFixed(1);
            return `<line class="chart-span chart-hit" x1="${sx(Math.max(i.from, t0)).toFixed(1)}" x2="${sx(Math.min(i.to, t1)).toFixed(1)}" y1="${y}" y2="${y}" `
                + `stroke="${i.color || mark.color}" stroke-width="${i.width || 4}" stroke-linecap="round" opacity="${i.opacity || 1}"`
                + `${i.dash ? ` stroke-dasharray="${i.dash}"` : ''}>${i.tip ? `<title>${escapeChartText(i.tip)}</title>` : ''}</line>`;
        }).join('');
    }
    if (mark.type === 'bars') {
        const half = Math.max(1, ((mark.barMs || 3 * 3600000) * (sx(t1) - sx(t0)) / (t1 - t0)) / 2 - 1);
        const shift = mark.offsetMs || 0;
        return points.filter((p) => p[1] !== null).map((p) => {
            const x = sx(p[0] + shift);
            const top = Math.min(sy(p[1]), sy(mark.base || 0));
            const label = mark.label ? mark.label(p) : '';
            return `<rect${mark.tipOf ? ' class="chart-hit"' : ''} x="${(x - half).toFixed(1)}" y="${top.toFixed(1)}" width="${(half * 2).toFixed(1)}" `
                + `height="${Math.abs(sy(p[1]) - sy(mark.base || 0)).toFixed(1)}" fill="${mark.colorOf ? mark.colorOf(p[1], p[0]) : mark.color}">`
                + `${mark.tipOf ? `<title>${escapeChartText(mark.tipOf(p))}</title>` : ''}</rect>`
                + (label ? `<text class="lcars-line-xtick chart-bar-label" x="${x.toFixed(1)}" y="${(top - 3).toFixed(1)}" text-anchor="middle">${label}</text>` : '');
        }).join('');
    }
    if (mark.type === 'area') {
        const base = mark.base || 0;
        let svg = '';
        runs.forEach((run) => {
            const { pos, neg } = chartSignedAreas(run, sx, sy, base);
            svg += pos.map((pts) => `<polygon class="lcars-area-band" points="${pts}" fill="${mark.colourPos}"></polygon>`).join('')
                + neg.map((pts) => `<polygon class="lcars-area-band" points="${pts}" fill="${mark.colourNeg}"></polygon>`).join('');
        });
        return svg + `<line class="chart-zero" x1="${sx(t0)}" x2="${sx(t1)}" y1="${sy(base).toFixed(1)}" y2="${sy(base).toFixed(1)}"></line>`;
    }
    // line: observed part solid, forecast part dashed
    const pathOf = (pts) => {
        if (mark.step) {
            const stepMs = mark.stepMs || 3600000;
            return pts.map((p, i) => `${i ? 'L' : 'M'}${chartPoint(sx(p[0]), sy(p[1]))} L${chartPoint(sx(Math.min(p[0] + stepMs, t1)), sy(p[1]))}`).join(' ');
        }
        return pts.map((p, i) => `${i ? 'L' : 'M'}${chartPoint(sx(p[0]), sy(p[1]))}`).join(' ');
    };
    const dash = mark.dash ? ` stroke-dasharray="${mark.dash}"` : '';
    const width = mark.width ? ` stroke-width="${mark.width}"` : '';
    let svg = '';
    runs.forEach((run) => {
        const cut = mark.forecastFrom;
        const observed = cut ? run.filter((p) => p[0] < cut) : run;
        const forecast = cut ? run.filter((p) => p[0] >= cut) : [];
        if (observed.length && forecast.length) { forecast.unshift(observed[observed.length - 1]); }
        if (observed.length) {
            svg += observed.length === 1
                ? `<circle cx="${sx(observed[0][0]).toFixed(1)}" cy="${sy(observed[0][1]).toFixed(1)}" r="2" fill="${mark.color}"></circle>`
                : `<path class="lcars-dual-line" d="${pathOf(observed)}" stroke="${mark.color}"${dash}${width}></path>`;
        }
        if (forecast.length > 1) {
            svg += `<path class="lcars-dual-line chart-forecast-line" d="${pathOf(forecast)}" stroke="${mark.color}"${width}></path>`;
        }
    });
    return svg;
}

// Panels stacked on one shared UTC time axis, with event markers through all of them.
function timePanelsSvg({ width, t0, t1, panels, events = [], hoverText, forecastFrom, title, idPrefix }) {
    const m = TIME_PANEL_MARGIN;
    const id = idPrefix || `ct${chartTimeSeq += 1}`;
    const plotW = width - m.left - m.right;
    const sx = (t) => m.left + ((t - t0) / (t1 - t0)) * plotW;
    const total = panels.reduce((sum, p) => sum + p.height, 0) + m.gap * (panels.length - 1);
    const height = m.top + total + m.bottom;
    const plotBottom = m.top + total;
    const { step, ticks } = chartTimeTicks(t0, t1, Math.max(3, Math.round(plotW / 90)));
    let defs = '';
    let svg = '';
    // The shared time axis: faint lines through every panel, labels at the bottom.
    ticks.forEach((t) => {
        let y = m.top;
        panels.forEach((p) => {
            svg += `<line class="lcars-line-grid" x1="${sx(t).toFixed(1)}" x2="${sx(t).toFixed(1)}" y1="${y}" y2="${y + p.height}"></line>`;
            y += p.height + m.gap;
        });
        svg += `<line class="lcars-line-xtick-mark" x1="${sx(t).toFixed(1)}" x2="${sx(t).toFixed(1)}" y1="${plotBottom}" y2="${plotBottom + 5}"></line>`
            + `<text class="lcars-line-xtick" x="${sx(t).toFixed(1)}" y="${plotBottom + 20}" text-anchor="middle">${chartTimeLabel(t, step)}</text>`;
    });
    svg += `<text class="lcars-line-axis-title" x="${m.left + plotW}" y="${plotBottom + 32}" text-anchor="end">UTC</text>`;
    // hover: strips across all panels, each carrying the readings at its time -- drawn first, so the marks
    // that have a tooltip of their own (dots, spans, event markers: class chart-hit) sit above them
    if (hoverText) {
        const count = Math.min(160, Math.max(10, Math.floor(plotW / 5)));
        const w = plotW / count;
        for (let i = 0; i < count; i += 1) {
            const t = t0 + ((i + 0.5) / count) * (t1 - t0);
            svg += `<rect class="lcars-hover-strip" x="${(m.left + i * w).toFixed(1)}" y="${m.top}" width="${w.toFixed(1)}" height="${total}">`
                + `<title>${escapeChartText(hoverText(t))}</title></rect>`;
        }
    }
    let top = m.top;
    panels.forEach((panel) => {
        const bottom = top + panel.height;
        const scales = {};
        ['left', 'right'].forEach((side) => {
            if (panel[side]) { scales[side] = chartValueScale(panel[side], top, bottom); }
        });
        const ctx = { sx, scales, t0, t1, top, bottom };
        // hatched forecast region, then shaded bands, class bands and grid
        const cut = forecastFrom || (panel.marks || []).filter((k) => !k.noHatch).map((k) => k.forecastFrom).find(Boolean);
        if (cut && cut < t1) {
            defs = defs || `<pattern id="${id}-hatch" patternUnits="userSpaceOnUse" width="7" height="7" patternTransform="rotate(45)">`
                + '<line x1="0" y1="0" x2="0" y2="7" stroke="var(--tng-lavender)" stroke-width="1.2" stroke-opacity=".5"></line></pattern>';
            svg += `<rect class="chart-forecast-band" x="${sx(Math.max(cut, t0)).toFixed(1)}" y="${top}" width="${(sx(t1) - sx(Math.max(cut, t0))).toFixed(1)}" height="${panel.height}" fill="url(#${id}-hatch)"></rect>`;
        }
        (panel.marks || []).filter((k) => k.type === 'shade').forEach((k) => { svg += chartMarkSvg(k, ctx); });
        const left = panel.left;
        if (left && left.classes) {
            left.classes.forEach((c, i) => {
                const yTop = scales.left(c.to);
                const yBottom = scales.left(c.from);
                if (i % 2 === 0) {
                    svg += `<rect class="chart-class-band" x="${m.left}" y="${Math.min(yTop, yBottom).toFixed(1)}" width="${plotW}" height="${Math.abs(yBottom - yTop).toFixed(1)}"></rect>`;
                }
                svg += `<text class="lcars-line-ytick chart-class-letter" x="${m.left + plotW - 6}" y="${((yTop + yBottom) / 2).toFixed(1)}" dy="0.35em" text-anchor="end">${c.label}</text>`;
            });
        }
        // y grid and numbers on each side, in the colour of the line they belong to
        ['left', 'right'].forEach((side) => {
            const axis = panel[side];
            if (!axis) { return; }
            const format = axis.format || ((n) => n.toLocaleString('en-GB'));
            const style = axis.color ? ` style="fill:${axis.color}"` : '';
            chartAxisTicks(axis).forEach((v) => {
                const y = scales[side](v).toFixed(1);
                if (side === 'left' || !panel.left) {
                    svg += `<line class="lcars-line-grid" x1="${m.left}" x2="${m.left + plotW}" y1="${y}" y2="${y}"></line>`;
                }
                svg += side === 'left'
                    ? `<text class="lcars-line-ytick"${style} x="${m.left - 8}" y="${y}" dy="0.35em" text-anchor="end">${format(v)}</text>`
                    : `<text class="lcars-line-ytick"${style} x="${m.left + plotW + 8}" y="${y}" dy="0.35em" text-anchor="start">${format(v)}</text>`;
            });
            if (axis.label) {
                svg += side === 'left'
                    ? `<text class="lcars-line-axis-title"${style} x="${m.left + 6}" y="${top + 13}" text-anchor="start">${axis.label}</text>`
                    : `<text class="lcars-line-axis-title"${style} x="${m.left + plotW - 6}" y="${top + 13}" text-anchor="end">${axis.label}</text>`;
            }
        });
        svg += `<line class="lcars-line-axis" x1="${m.left}" x2="${m.left + plotW}" y1="${bottom}" y2="${bottom}"></line>`;
        (panel.lines || []).forEach((line) => {
            const y = scales[line.axis || 'left'](line.value).toFixed(1);
            svg += `<line class="chart-threshold" x1="${m.left}" x2="${m.left + plotW}" y1="${y}" y2="${y}" stroke="${line.color || 'var(--tng-salmon)'}"${line.dash === false ? '' : ' stroke-dasharray="5 4"'}></line>`;
            if (line.label) {
                svg += `<text class="lcars-line-ytick chart-threshold-label" x="${m.left + 4}" y="${(y - 3)}" text-anchor="start">${line.label}</text>`;
            }
        });
        (panel.marks || []).filter((k) => k.type !== 'shade').forEach((k) => { svg += chartMarkSvg(k, ctx); });
        if (panel.title) {
            svg += `<text class="lcars-line-axis-title chart-panel-title" x="${m.left + plotW / 2}" y="${top + 13}" text-anchor="middle">${panel.title}</text>`;
        }
        top = bottom + m.gap;
    });
    // events: a dashed line through every panel and a marker above the first (hollow = reported, not confirmed)
    events.filter((e) => e.t >= t0 && e.t <= t1).forEach((e) => {
        const x = sx(e.t).toFixed(1);
        const colour = e.color || 'var(--tng-salmon)';
        svg += `<g class="chart-event"><line x1="${x}" x2="${x}" y1="${m.top - 4}" y2="${plotBottom}" stroke="${colour}"></line>`
            + `<circle class="chart-hit" cx="${x}" cy="${m.top - 8}" r="5" stroke="${colour}" fill="${e.hollow ? '#000' : colour}"></circle>`
            + `<title>${escapeChartText(e.label)}</title></g>`;
    });
    svg = `<g class="chart-time-body">${svg}</g>`;
    const parts = defs ? [`<defs>${defs}</defs>`, svg] : [svg];
    return chartSvgHtml(width, height, title, parts);
}

// The frame with a detailed tooltip on the pill (hover, keyboard focus or a tap):
// tip = [[label, html], ...] -- what, from, units, formula, science, cite. credit: the
// small line under the chart.
function chartTipFrameHtml({ title, tag, tip, legend, svg, credit }) {
    const legendHtml = legend && legend.length ? `
            <div class="lcars-chart-legend">${legend.map((item) => `
                <span class="lcars-chart-legend-item"><span class="lcars-chart-swatch" style="background:${item.color}"></span>${escapeChartText(item.label)}</span>`).join('')}
            </div>` : '';
    const tipHtml = tip && tip.length ? `<div class="chart-tip" role="tooltip">${tip.map(([label, html]) => `<p><b>${label}:</b> ${html}</p>`).join('')}</div>` : '';
    return `
        <section class="orbit-chart">
            <header class="orbit-chart-header chart-pill" tabindex="0"><span>${title}</span><span>${tag || ''}</span>${tipHtml}</header>
            ${legendHtml}
            ${svg}
            ${credit ? `<div class="chart-credit">${credit}</div>` : ''}
        </section>`;
}

// A full-width pill bar that opens a band of a view ("NOW: WHAT IS GOING ON"), with a black gap above.
function chartSectionBarHtml({ title, tag, color }) {
    return `
        <header class="orbit-chart-header chart-section-bar" style="background-color:${color}"><span>${title}</span><span>${tag || ''}</span></header>`;
}
