/* ==========================================================================
   USAGE (ABOUT section)

   Where the site is used from: the usual Leaflet map with a circle for each
   city, its AREA proportional to that city's total logins, and in the control
   area a table of total logins and a graph of logins by week. The data is
   /api/usage (server.py), read from databases/inboxUsage.db; until anything
   is recorded the view says so. Lazily loaded the first time the USAGE tab
   is clicked (showAcknowledgmentsTabExtras() in lcars.js loads mapCore.js and
   this file first).
   ========================================================================== */

let usageMap = null;
let usageLayer = null;
let usageData = null;

const USAGE_MAX_RADIUS = 28;   // pixels, for the busiest city; the others scale by area
const USAGE_TABLE_ROWS = 5;    // busiest cities listed; the rest are summed as "other"
const USAGE_WEEKS_SHOWN = 26;

function usageEscape(text) {
    return String(text).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

async function loadUsageData() {
    try {
        const response = await fetch('api/usage');
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }
        usageData = await response.json();
    } catch (error) {
        console.error('Error loading usage data:', error);
        usageData = null;
    }
    return usageData;
}

// Bars, one per week (the most recent USAGE_WEEKS_SHOWN), with the first and
// last week's start date underneath.
function usageWeekGraph(weeks) {
    const shown = weeks.slice(-USAGE_WEEKS_SHOWN);
    const width = 220;
    const height = 64;
    const labelHeight = 14;
    const gap = 2;
    const max = Math.max(...shown.map((week) => week.logins), 1);
    const barWidth = Math.max(2, (width - gap * (shown.length - 1)) / shown.length);
    const amber = lcarsColour('--tng-amber');
    const label = lcarsColour('--status-label-color');
    const bars = shown.map((week, index) => {
        const barHeight = Math.max(1, Math.round((week.logins / max) * (height - labelHeight)));
        return `<rect x="${(index * (barWidth + gap)).toFixed(1)}" y="${height - labelHeight - barHeight}" width="${barWidth.toFixed(1)}" height="${barHeight}" fill="${amber}"><title>Week of ${usageEscape(week.weekStart)}: ${week.logins}</title></rect>`;
    }).join('');
    return `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Logins by week">${bars}
        <text x="0" y="${height - 2}" font-size="9" fill="${label}">${usageEscape(shown[0].weekStart)}</text>
        <text x="${width}" y="${height - 2}" font-size="9" fill="${label}" text-anchor="end">${usageEscape(shown[shown.length - 1].weekStart)}</text>
    </svg>`;
}

// Control area: the table of total logins (busiest cities, the rest summed,
// then the total) beside the weekly graph.
function renderUsageControlArea() {
    const wrapper = document.getElementById('default');
    if (!wrapper) {
        return;
    }
    if (!usageData || !usageData.total) {
        wrapper.innerHTML = '<div class="usage-summary"><p>No logins recorded yet.</p></div>';
        return;
    }
    const top = usageData.cities.slice(0, USAGE_TABLE_ROWS);
    const rest = usageData.cities.slice(USAGE_TABLE_ROWS).reduce((sum, city) => sum + city.logins, 0);
    const rows = top.map((city) => `<tr><td>${usageEscape(city.city)}, ${usageEscape(city.country)}</td><td>${city.logins}</td></tr>`).join('')
        + (rest ? `<tr><td>Other</td><td>${rest}</td></tr>` : '');
    wrapper.innerHTML = `<div class="usage-summary">
        <table class="usage-table">
            <thead><tr><th>CITY</th><th>TOTAL LOGINS</th></tr></thead>
            <tbody>${rows}<tr class="usage-total"><td>TOTAL</td><td>${usageData.total}</td></tr></tbody>
        </table>
        <div class="usage-graph"><div class="usage-graph-title">LOGINS BY WEEK</div>${usageData.weeks.length ? usageWeekGraph(usageData.weeks) : ''}</div>
    </div>`;
}

async function initUsageMap() {
    await loadScriptOnce('assets/mapCore.js');
    if (usageMap) {
        currentMap = usageMap;
        usageMap.invalidateSize();   // the tab was display:none until now
        return;
    }
    usageMap = await initBaseMap('usage-map');
    currentMap = usageMap;
    renderLatLonGraticule(usageMap);
}

// One circle per city; radius is the square root of the logins, so the AREA
// stands for the number.
function drawUsageCircles() {
    if (!usageMap) {
        return;
    }
    if (usageLayer) {
        usageLayer.remove();
    }
    usageLayer = L.layerGroup().addTo(usageMap);
    const cities = (usageData && usageData.cities) || [];
    const max = Math.max(...cities.map((city) => city.logins), 1);
    const colour = lcarsColour('--tng-amber');
    cities.forEach((city) => {
        if (!Number.isFinite(city.latitude) || !Number.isFinite(city.longitude)) {
            return;
        }
        L.circleMarker([city.latitude, city.longitude], {
            radius: Math.max(3, USAGE_MAX_RADIUS * Math.sqrt(city.logins / max)),
            color: colour, weight: 1, fillColor: colour, fillOpacity: 0.5,
        }).bindTooltip(`${city.city}, ${city.country}: ${city.logins} login${city.logins === 1 ? '' : 's'}`).addTo(usageLayer);
    });
}

async function showUsage() {
    await loadUsageData();
    renderUsageControlArea();
    try {
        await initUsageMap();
        drawUsageCircles();
    } catch (error) {
        console.error('Error showing the usage map:', error);
    }
}
