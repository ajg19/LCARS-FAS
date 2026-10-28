/* ==========================================================================
   WEATHER MAP -- the reusable world map of the WEATHER views (first used by HF COMMS: D-RAP
   absorption; AURORAE and SAT COMMS will reuse it).

   weatherMapSvg(options) returns the markup of one equirectangular map (longitude across, latitude
   up, the whole world by default or a window of it):
     id            unique per map on the page (the hover readout is found by it)
     width         pixels, as the other charts (chartWidth); the SVG itself scales to its slot
     view          { lonMin, lonMax, latMin, latMax }, default the whole world
     layers        [{ values, latFirst (or latMax), latStep, lonMin, lonStep, colourAt(v), stretchPoles }]: grids
                   of numbers, rows run latFirst, latFirst + latStep, ... (latStep negative going south, as the
                   D-RAP map; positive going north, as GloTEC) and columns lonMin, lonMin + lonStep, ... (cell
                   centres or grid nodes). colourAt returns a colour (a CSS colour, or 'url(#weather-map-hatch)'
                   for the grey hatching of "no observations") or null (nothing drawn); it is given null for a
                   missing value. Equal neighbours in a row are merged into one rectangle. stretchPoles: the
                   northernmost and southernmost rows are drawn out to the pole (CODE's rows stop at 87.5).
     coast         the rings from weatherCoastRings(), or null
     terminatorMs  draws the night side for that time (UTC, computed here: nothing is fetched)
     markers       [{ lat, lon, label, color }]
     hoverText     (lat, lon) -> text for the readout under the map
   plus weatherMapLegend(levels) for a chartTipFrameHtml legend, weatherGridValueAt(grid, lat, lon),
   weatherSubsolarPoint(ms) and weatherCoastRings() (lazy: the outline is fetched on first use).
   Round maps (the polar projections and the globe: weatherProjection, weatherSphereSvg, weatherContours, with a drag
   handler for the globe) are further down; AURORAE uses them. Pure functions apart from the fetch; tests in 0_tests/chartTimeTest.js.
   Needs chartCore.js (escapeChartText) and weatherCharts.js (the request cache). Loaded by weatherPanel.js when a view with a map is opened.
   ========================================================================== */

const WEATHER_MAP_MARGIN = { left: 34, right: 6, top: 6, bottom: 20 };
const WEATHER_MAP_WORLD = { lonMin: -180, lonMax: 180, latMin: -90, latMax: 90 };
const WEATHER_MAP_GRATICULE_DEG = 30;
const WEATHER_MAP_REGISTRY = {};   // id -> what the hover handler needs; replaced each time a map is drawn

/* --- the outline: country boundaries simplified to 32 KB (11.7 KB gzipped), built from the world file the
   site already ships by 0_tools/buildWeatherCoast.py; fetched once, when the first map is drawn --------------- */

let weatherCoastPromise = null;

// [[ [lon, lat], ... ], ...]; empty if the file cannot be had (the map is then drawn without an outline).
function weatherCoastRings() {
    if (!weatherCoastPromise) {
        weatherCoastPromise = (async () => {
            try {
                const response = await fetch('assets/weatherCoast.json');
                if (!response.ok) {
                    weatherCoastPromise = null;
                    return [];
                }
                const data = await response.json();
                return data.rings.map((flat) => {
                    const ring = [];
                    let x = 0;
                    let y = 0;
                    for (let i = 0; i < flat.length; i += 2) {
                        x += flat[i];
                        y += flat[i + 1];
                        ring.push([x * data.unit, y * data.unit]);
                    }
                    return ring;
                });
            } catch (error) {
                console.error('Error loading the map outline:', error);
                weatherCoastPromise = null;
                return [];
            }
        })();
    }
    return weatherCoastPromise;
}

// A stored map of the site ({tsUtc, map}) by name, from /api/weather/map; null if it is not held. Remembered per view
// opening with the other requests (weatherCharts.js).
function weatherMapData(name) {
    const key = `map|${name}`;
    if (!weatherFetchCache.has(key)) {
        weatherFetchCache.set(key, (async () => {
            try {
                const response = await fetch(`api/weather/map?name=${name}`);
                return response.ok ? await response.json() : null;
            } catch (error) {
                console.error(`Error loading weather map ${name}:`, error);
                return null;
            }
        })());
    }
    return weatherFetchCache.get(key);
}

/* --- geometry --------------------------------------------------------------------------------------------- */

// The point of the Earth directly under the Sun at a time (UTC, ms): {lat, lon} in degrees, good to about 0.1 degree
// (the low-precision formulas of the Astronomical Almanac).
function weatherSubsolarPoint(ms) {
    const rad = Math.PI / 180;
    const n = (ms - Date.UTC(2000, 0, 1, 12)) / 86400000;
    const meanLongitude = 280.460 + 0.9856474 * n;
    const anomaly = (357.528 + 0.9856003 * n) * rad;
    const eclipticLongitude = (meanLongitude + 1.915 * Math.sin(anomaly) + 0.020 * Math.sin(2 * anomaly)) * rad;
    const obliquity = (23.439 - 0.0000004 * n) * rad;
    const declination = Math.asin(Math.sin(obliquity) * Math.sin(eclipticLongitude));
    const rightAscension = Math.atan2(Math.cos(obliquity) * Math.sin(eclipticLongitude), Math.cos(eclipticLongitude));
    const siderealDeg = 280.46061837 + 360.98564736629 * n;
    const lon = ((rightAscension / rad - siderealDeg) % 360 + 540) % 360 - 180;
    return { lat: declination / rad, lon };
}

// The day-night line as latitude against longitude, every `stepDeg`: [[lon, lat]], and which pole is in the dark
// ('S' when the Sun is north of the equator, else 'N').
function weatherTerminator(ms, lonMin = -180, lonMax = 180, stepDeg = 2) {
    const sun = weatherSubsolarPoint(ms);
    const rad = Math.PI / 180;
    const tanDeclination = Math.tan(Math.max(Math.abs(sun.lat), 0.01) * rad) * (sun.lat < 0 ? -1 : 1);
    const line = [];
    for (let lon = lonMin; lon <= lonMax + 1e-9; lon += stepDeg) {
        line.push([lon, Math.atan(-Math.cos((lon - sun.lon) * rad) / tanDeclination) / rad]);
    }
    return { line, darkPole: sun.lat >= 0 ? 'S' : 'N', sun };
}

// The value of a grid at a place (nearest cell); null outside it. Longitude may be given as -180..360.
function weatherGridValueAt(grid, lat, lon) {
    const lat0 = grid.latFirst !== undefined ? grid.latFirst : grid.latMax;
    let row = Math.round((lat - lat0) / grid.latStep);
    if (grid.stretchPoles) {
        row = Math.min(grid.values.length - 1, Math.max(0, row));
    }
    if (row < 0 || row >= grid.values.length) {
        return null;
    }
    const cols = grid.values[0].length;
    const wrapped = (((lon + 180) % 360) + 360) % 360 - 180;
    const col = ((Math.round((wrapped - grid.lonMin) / grid.lonStep) % cols) + cols) % cols;
    const value = grid.values[row][col];
    return value === undefined ? null : value;
}

function weatherMapFrame(width, view) {
    const margin = WEATHER_MAP_MARGIN;
    const plotW = Math.max(200, width - margin.left - margin.right);
    const plotH = Math.round(plotW * (view.latMax - view.latMin) / (view.lonMax - view.lonMin));
    return {
        margin, plotW, plotH, width: margin.left + plotW + margin.right, height: margin.top + plotH + margin.bottom,
        x: (lon) => margin.left + (lon - view.lonMin) / (view.lonMax - view.lonMin) * plotW,
        y: (lat) => margin.top + (view.latMax - lat) / (view.latMax - view.latMin) * plotH,
        lon: (px) => view.lonMin + (px - margin.left) / plotW * (view.lonMax - view.lonMin),
        lat: (py) => view.latMax - (py - margin.top) / plotH * (view.latMax - view.latMin),
    };
}

/* --- layers -------------------------------------------------------------------------------------------------- */

// One rectangle per run of equal colour along a row.
function weatherMapGridSvg(layer, frame, view) {
    const cols = layer.values[0] ? layer.values[0].length : 0;
    const halfLat = Math.abs(layer.latStep) / 2;
    const halfLon = layer.lonStep / 2;
    const lat0 = layer.latFirst !== undefined ? layer.latFirst : layer.latMax;
    const lastLat = lat0 + (layer.values.length - 1) * layer.latStep;
    const northEdge = Math.max(lat0, lastLat) + halfLat;
    const southEdge = Math.min(lat0, lastLat) - halfLat;
    const clampX = (lon) => frame.x(Math.min(view.lonMax, Math.max(view.lonMin, lon)));
    const clampY = (lat) => frame.y(Math.min(view.latMax, Math.max(view.latMin, lat)));
    const pieces = [];
    layer.values.forEach((row, i) => {
        const lat = lat0 + i * layer.latStep;
        if (lat + halfLat < view.latMin || lat - halfLat > view.latMax) {
            return;
        }
        const rowTop = layer.stretchPoles && lat + halfLat >= northEdge - 1e-9 ? view.latMax : lat + halfLat;
        const rowBottom = layer.stretchPoles && lat - halfLat <= southEdge + 1e-9 ? view.latMin : lat - halfLat;
        const top = clampY(rowTop);
        const height = clampY(rowBottom) - top;
        let start = 0;
        let colour = null;
        for (let j = 0; j <= cols; j += 1) {
            const here = j < cols ? layer.colourAt(row[j]) : null;
            if (here !== colour) {
                if (colour) {
                    const left = clampX(layer.lonMin + start * layer.lonStep - halfLon);
                    const right = clampX(layer.lonMin + (j - 1) * layer.lonStep + halfLon);
                    if (right > left) {
                        pieces.push(`<rect x="${left.toFixed(1)}" y="${top.toFixed(1)}" width="${(right - left).toFixed(1)}" height="${height.toFixed(1)}" fill="${colour}"/>`);
                    }
                }
                colour = here;
                start = j;
            }
        }
    });
    return `<g class="weather-map-cells">${pieces.join('')}</g>`;
}

// Rings as one path of outlines; a step of more than 180 degrees of longitude is the edge of the map being crossed
// (Russia, Fiji, Antarctica): the pen is lifted there, so no line is drawn across the world.
function weatherMapCoastSvg(rings, frame, view) {
    const parts = [];
    for (const ring of rings) {
        let pen = false;
        let before = null;
        for (const [lon, lat] of ring) {
            const jump = before !== null && Math.abs(lon - before) > 180;
            parts.push(`${pen && !jump ? 'L' : 'M'}${frame.x(lon).toFixed(1)} ${frame.y(Math.min(view.latMax, Math.max(view.latMin, lat))).toFixed(1)}`);
            pen = true;
            before = lon;
        }
    }
    return `<path class="weather-map-coast" d="${parts.join('')}" fill="none" stroke="var(--tng-periwinkle)" stroke-width="0.8" opacity=".55"/>`;
}

function weatherMapNightSvg(ms, frame, view) {
    const { line, darkPole } = weatherTerminator(ms, view.lonMin, view.lonMax);
    const poleLat = darkPole === 'S' ? view.latMin : view.latMax;
    const edge = line.map(([lon, lat]) => `${frame.x(lon).toFixed(1)},${frame.y(Math.min(view.latMax, Math.max(view.latMin, lat))).toFixed(1)}`);
    edge.push(`${frame.x(view.lonMax).toFixed(1)},${frame.y(poleLat).toFixed(1)}`, `${frame.x(view.lonMin).toFixed(1)},${frame.y(poleLat).toFixed(1)}`);
    return `<polygon class="weather-map-night" points="${edge.join(' ')}" fill="#000" fill-opacity=".5"/>`;
}

function weatherMapGraticuleSvg(frame, view) {
    let svg = '';
    const step = WEATHER_MAP_GRATICULE_DEG;
    for (let lon = Math.ceil(view.lonMin / step) * step; lon <= view.lonMax; lon += step) {
        const x = frame.x(lon).toFixed(1);
        svg += `<line class="weather-map-graticule" x1="${x}" y1="${frame.margin.top}" x2="${x}" y2="${frame.margin.top + frame.plotH}"/>`
            + `<text class="lcars-line-xtick" x="${x}" y="${frame.height - 5}" text-anchor="middle">${lon}</text>`;
    }
    for (let lat = Math.ceil(view.latMin / step) * step; lat <= view.latMax; lat += step) {
        const y = frame.y(lat).toFixed(1);
        svg += `<line class="weather-map-graticule" x1="${frame.margin.left}" y1="${y}" x2="${frame.margin.left + frame.plotW}" y2="${y}"/>`
            + `<text class="lcars-line-ytick" x="${frame.margin.left - 4}" y="${(Number(y) + 4).toFixed(1)}" text-anchor="end">${lat}</text>`;
    }
    return svg;
}

function weatherMapMarkersSvg(markers, frame, view) {
    return markers.filter((m) => m.lat >= view.latMin && m.lat <= view.latMax && m.lon >= view.lonMin && m.lon <= view.lonMax).map((m) => {
        const x = frame.x(m.lon);
        const y = frame.y(m.lat);
        const labelLeft = x > frame.margin.left + frame.plotW * 0.8;
        return `<g class="weather-map-marker"><circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="4.5" fill="none" stroke="${m.color || 'var(--space-white)'}" stroke-width="2"/>`
            + `<text x="${(labelLeft ? x - 8 : x + 8).toFixed(1)}" y="${(y + 4).toFixed(1)}" text-anchor="${labelLeft ? 'end' : 'start'}" fill="${m.color || 'var(--space-white)'}" font-size="11">${escapeChartText(m.label)}</text></g>`;
    }).join('');
}

/* --- the map ------------------------------------------------------------------------------------------------- */

function weatherMapSvg({ id, width, view = WEATHER_MAP_WORLD, layers = [], coast = null, terminatorMs = null, markers = [], hoverText = null, title = 'World map' }) {
    const frame = weatherMapFrame(width, view);
    WEATHER_MAP_REGISTRY[id] = { frame, view, hoverText };
    const parts = [`<defs><pattern id="weather-map-hatch" patternUnits="userSpaceOnUse" width="6" height="6" patternTransform="rotate(45)"><line x1="0" y1="0" x2="0" y2="6" stroke="var(--tng-mauve)" stroke-width="1.2" stroke-opacity=".7"/></pattern></defs>`,
        `<rect x="${frame.margin.left}" y="${frame.margin.top}" width="${frame.plotW}" height="${frame.plotH}" fill="#000"/>`];
    for (const layer of layers) {
        parts.push(weatherMapGridSvg(layer, frame, view));
    }
    if (terminatorMs !== null) {
        parts.push(weatherMapNightSvg(terminatorMs, frame, view));
    }
    parts.push(weatherMapGraticuleSvg(frame, view));
    if (coast && coast.length) {
        parts.push(weatherMapCoastSvg(coast, frame, view));
    }
    parts.push(weatherMapMarkersSvg(markers, frame, view));
    const handlers = hoverText ? ` onpointermove="weatherMapHover(event, '${id}')" onpointerdown="weatherMapHover(event, '${id}')"` : '';
    return `
        <svg class="weather-map" viewBox="0 0 ${frame.width} ${frame.height}" role="img" aria-label="${escapeChartText(title)}"${handlers}>
            ${parts.join('\n            ')}
        </svg>
        <div class="weather-map-readout" id="${id}-readout">${hoverText ? 'Move the pointer (or touch the map) for the value at that place.' : ''}</div>`;
}

// The pointer's place on the map, into the readout under it.
function weatherMapHover(event, id) {
    const entry = WEATHER_MAP_REGISTRY[id];
    const readout = document.getElementById(`${id}-readout`);
    if (!entry || !readout) {
        return;
    }
    const box = event.currentTarget.getBoundingClientRect();
    const px = (event.clientX - box.left) * entry.frame.width / box.width;
    const py = (event.clientY - box.top) * entry.frame.height / box.height;
    if (entry.invert) {      // a round map (polar or globe)
        const place = entry.invert(px, py);
        if (place) {
            readout.textContent = entry.hoverText(place.lat, place.lon);
        }
        return;
    }
    const lon = entry.frame.lon(px);
    const lat = entry.frame.lat(py);
    if (lon < entry.view.lonMin || lon > entry.view.lonMax || lat < entry.view.latMin || lat > entry.view.latMax) {
        return;
    }
    readout.textContent = entry.hoverText(lat, lon);
}

// Legend items for chartTipFrameHtml from a list of { colour, label }.
function weatherMapLegend(levels) {
    return levels.map((level) => ({ color: level.colour, label: level.label }));
}

/* ==========================================================================
   ROUND MAPS: the polar and globe projections, for AURORAE (and anything that needs the poles).

   weatherProjection({ kind, size, centreLat, centreLon, rotateLon, latLimit }) -> a projection:
     kind 'north' | 'south': azimuthal equidistant about the pole, down to latLimit (default 30 degrees), longitude rotateLon at the bottom
                  (viewed from above the pole: east is anticlockwise in the north, clockwise in the south);
     kind 'globe': orthographic, centred on centreLat, centreLon.
     project(lat, lon) -> { x, y, visible }, invert(px, py) -> { lat, lon } or null outside the disc, plus size, cx, cy, R.
   weatherSphereSvg({ id, size, projection, layers, coast, lines, markers, hoverText, drag, title }) draws one round map:
     layers  [{ values, latFirst, latStep, lonMin, lonStep, colourAt(v) }]: grids as for weatherMapSvg, rows may be null (skipped),
             columns wrap round the world. colourAt returns a colour, [colour, opacity] or null. Cells of one colour are drawn as annular
             sectors in ONE path per colour, so a crowded map is a handful of elements.
     coast   rings as from weatherCoastRings();  lines [{ polylines: [[[lat, lon], ...]], stroke, width, dash, opacity }]
     markers [{ lat, lon, label, color }];  hoverText(lat, lon);  drag(dxPx, dyPx): called while the pointer drags (the globe).
   weatherContours(grid, level) -> polylines [[lat, lon], ...] of the line where the grid crosses a level (marching squares; columns wrap).
   ========================================================================== */

const WEATHER_SPHERE_PAD = 10;

function weatherProjection({ kind, size, centreLat = 0, centreLon = 0, rotateLon = 0, latLimit = 30 }) {
    const rad = Math.PI / 180;
    const R = size / 2 - WEATHER_SPHERE_PAD;
    const cx = size / 2;
    const cy = size / 2;
    if (kind === 'globe') {
        const sin0 = Math.sin(centreLat * rad);
        const cos0 = Math.cos(centreLat * rad);
        return {
            kind, size, cx, cy, R, centreLat, centreLon, latLimit: -90,
            project(lat, lon) {
                const phi = lat * rad;
                const dl = (lon - centreLon) * rad;
                const cosC = sin0 * Math.sin(phi) + cos0 * Math.cos(phi) * Math.cos(dl);
                return { x: cx + R * Math.cos(phi) * Math.sin(dl), y: cy - R * (cos0 * Math.sin(phi) - sin0 * Math.cos(phi) * Math.cos(dl)), visible: cosC >= 0 };
            },
            invert(px, py) {
                const x = (px - cx) / R;
                const y = (cy - py) / R;
                const rho = Math.hypot(x, y);
                if (rho > 1) {
                    return null;
                }
                if (rho === 0) {
                    return { lat: centreLat, lon: centreLon };
                }
                const c = Math.asin(rho);
                const lat = Math.asin(Math.cos(c) * sin0 + y * Math.sin(c) * cos0 / rho) / rad;
                const lon = centreLon + Math.atan2(x * Math.sin(c), rho * cos0 * Math.cos(c) - y * sin0 * Math.sin(c)) / rad;
                return { lat, lon: ((lon + 540) % 360) - 180 };
            },
        };
    }
    const sign = kind === 'south' ? -1 : 1;
    const span = 90 - latLimit;
    return {
        kind, size, cx, cy, R, rotateLon, latLimit,
        project(lat, lon) {
            const colat = sign > 0 ? 90 - lat : 90 + lat;
            const r = R * colat / span;
            const a = (lon - rotateLon) * rad;
            return { x: cx + sign * r * Math.sin(a), y: cy + r * Math.cos(a), visible: colat <= span + 1e-9 };
        },
        invert(px, py) {
            const dx = px - cx;
            const dy = py - cy;
            const r = Math.hypot(dx, dy);
            if (r > R) {
                return null;
            }
            const colat = r / R * span;
            const a = r === 0 ? 0 : Math.atan2(sign * dx, dy);
            return { lat: sign * (90 - colat), lon: ((rotateLon + a / rad + 540) % 360) - 180 };
        },
    };
}

// Path text for polylines [[lat, lon]] with the pen lifted wherever a point is out of sight (behind the globe, beyond the polar limit).
function weatherSpherePath(proj, polylines, close = false) {
    let d = '';
    for (const line of polylines) {
        let pen = false;
        for (const [lat, lon] of line) {
            const p = proj.project(lat, lon);
            if (!p.visible) {
                pen = false;
                continue;
            }
            d += `${pen ? 'L' : 'M'}${p.x.toFixed(1)} ${p.y.toFixed(1)}`;
            pen = true;
        }
        if (close && pen) {
            d += 'Z';
        }
    }
    return d;
}

// The cells of a grid layer as annular sectors, one path per colour.
function weatherSphereCellsSvg(layer, proj) {
    const groups = new Map();
    const lat0 = layer.latFirst !== undefined ? layer.latFirst : layer.latMax;
    const half = Math.abs(layer.latStep) / 2;
    const cols = layer.values.find((r) => r)?.length || 0;
    const step = layer.lonStep;
    const push = (colour, d) => { groups.set(colour, (groups.get(colour) || '') + d); };
    layer.values.forEach((row, i) => {
        if (!row) {
            return;
        }
        const lat = lat0 + i * layer.latStep;
        const north = Math.min(90, lat + half);
        const south = Math.max(-90, lat - half);
        if (proj.kind !== 'globe' && (proj.kind === 'north' ? south < proj.latLimit : north > -proj.latLimit)) {
            return;
        }
        const colourOf = (j) => {
            const c = layer.colourAt(row[j]);
            if (!c) {
                return null;
            }
            if (proj.kind === 'globe' && !proj.project(lat, layer.lonMin + j * step).visible) {
                return null;
            }
            return Array.isArray(c) ? `${c[0]}|${c[1]}` : c;
        };
        let start = 0;
        let colour = colourOf(0);
        for (let j = 1; j <= cols; j += 1) {
            const here = j < cols ? colourOf(j) : null;
            if (here !== colour) {
                if (colour) {
                    const a = layer.lonMin + start * step - step / 2;
                    const b = layer.lonMin + (j - 1) * step + step / 2;
                    const lons = [];
                    for (let lon = a; lon < b - 1e-9; lon += step) {
                        lons.push(lon);
                    }
                    lons.push(b);
                    const outer = lons.map((lon) => proj.project(north, lon));
                    const inner = lons.map((lon) => proj.project(south, lon));
                    const ring = outer.concat(inner.reverse());
                    push(colour, `M${ring.map((p) => `${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join('L')}Z`);
                }
                colour = here;
                start = j;
            }
        }
    });
    return [...groups].map(([key, d]) => {
        const [fill, opacity] = key.split('|');
        return `<path class="weather-sphere-cells" d="${d}" fill="${fill}"${opacity ? ` fill-opacity="${opacity}"` : ''}/>`;
    }).join('');
}

// Marching squares on a grid of rows [latFirst + i * latStep] by columns [lonMin + j * lonStep] (columns wrap): the polylines of value = level.
function weatherContours(grid, level) {
    const rows = grid.values;
    const nRows = rows.length;
    const cols = rows[0].length;
    const lat0 = grid.latFirst !== undefined ? grid.latFirst : grid.latMax;
    const high = (i, j) => rows[i][((j % cols) + cols) % cols] >= level;
    const value = (i, j) => rows[i][((j % cols) + cols) % cols];
    // edge ids: horizontal edge from (i, j) to (i, j + 1) is 2 * (i * cols + j); vertical edge from (i, j) to (i + 1, j) is 2 * (i * cols + j) + 1
    const hId = (i, j) => 2 * (i * cols + (((j % cols) + cols) % cols));
    const vId = (i, j) => 2 * (i * cols + (((j % cols) + cols) % cols)) + 1;
    const pointOf = new Map();
    const at = (p, q, t) => (q === p ? 0.5 : (t - p) / (q - p));
    const segments = [];
    const link = (idA, idB) => segments.push([idA, idB]);
    for (let i = 0; i < nRows - 1; i += 1) {
        for (let j = 0; j < cols; j += 1) {
            const a = value(i, j);
            const b = value(i, j + 1);
            const c = value(i + 1, j + 1);
            const d = value(i + 1, j);
            const index = (a >= level ? 1 : 0) | (b >= level ? 2 : 0) | (c >= level ? 4 : 0) | (d >= level ? 8 : 0);
            if (index === 0 || index === 15) {
                continue;
            }
            const edge = [
                () => { const id = hId(i, j); pointOf.set(id, [lat0 + i * grid.latStep, grid.lonMin + (j + at(a, b, level)) * grid.lonStep]); return id; },
                () => { const id = vId(i, j + 1); pointOf.set(id, [lat0 + (i + at(b, c, level)) * grid.latStep, grid.lonMin + (j + 1) * grid.lonStep]); return id; },
                () => { const id = hId(i + 1, j); pointOf.set(id, [lat0 + (i + 1) * grid.latStep, grid.lonMin + (j + at(d, c, level)) * grid.lonStep]); return id; },
                () => { const id = vId(i, j); pointOf.set(id, [lat0 + (i + at(a, d, level)) * grid.latStep, grid.lonMin + j * grid.lonStep]); return id; },
            ];
            const pairs = { 1: [[0, 3]], 2: [[0, 1]], 3: [[3, 1]], 4: [[1, 2]], 5: [[0, 3], [1, 2]], 6: [[0, 2]], 7: [[3, 2]], 8: [[2, 3]], 9: [[0, 2]], 10: [[0, 1], [2, 3]],
                11: [[2, 1]], 12: [[3, 1]], 13: [[0, 1]], 14: [[0, 3]] }[index];
            pairs.forEach(([e1, e2]) => link(edge[e1](), edge[e2]()));
        }
    }
    const byEdge = new Map();
    segments.forEach((s, k) => s.forEach((id) => { if (!byEdge.has(id)) { byEdge.set(id, []); } byEdge.get(id).push(k); }));
    const used = new Array(segments.length).fill(false);
    const lines = [];
    const follow = (line, from) => {
        let end = from;
        for (;;) {
            const next = (byEdge.get(end) || []).find((k) => !used[k]);
            if (next === undefined) {
                return end;
            }
            used[next] = true;
            const other = segments[next][0] === end ? segments[next][1] : segments[next][0];
            line.push(pointOf.get(other));
            end = other;
        }
    };
    segments.forEach((s, k) => {
        if (used[k]) {
            return;
        }
        used[k] = true;
        const line = [pointOf.get(s[0]), pointOf.get(s[1])];
        follow(line, s[1]);
        const back = [];
        follow(back, s[0]);
        lines.push(back.reverse().concat(line));
    });
    return lines;
}

function weatherSphereGraticule(proj, stepDeg) {
    const lines = [];
    const span = proj.kind === 'globe' ? [-90, 90] : proj.kind === 'north' ? [proj.latLimit, 90] : [-90, -proj.latLimit];
    for (let lat = Math.ceil(span[0] / stepDeg) * stepDeg; lat <= span[1]; lat += stepDeg) {
        if (Math.abs(lat) === 90) {
            continue;
        }
        const line = [];
        for (let lon = -180; lon <= 180; lon += 3) {
            line.push([lat, lon]);
        }
        lines.push(line);
    }
    for (let lon = -180; lon < 180; lon += 2 * stepDeg) {
        const line = [];
        for (let lat = span[0]; lat <= span[1]; lat += 3) {
            line.push([lat, lon]);
        }
        line.push([span[1], lon]);
        lines.push(line);
    }
    return lines;
}

function weatherSphereLabels(proj) {
    if (proj.kind === 'globe') {
        return '';
    }
    const sign = proj.kind === 'south' ? -1 : 1;
    let svg = '';
    for (let lat = Math.ceil(proj.latLimit / 15) * 15; lat < 90; lat += 15) {
        const p = proj.project(sign * lat, proj.rotateLon);
        svg += `<text class="lcars-line-ytick" x="${(p.x + 4).toFixed(1)}" y="${(p.y - 2).toFixed(1)}">${lat}${sign > 0 ? 'N' : 'S'}</text>`;
    }
    for (let lon = -180; lon < 180; lon += 30) {
        const p = proj.project(sign * (proj.latLimit - 4.5), lon);
        svg += `<text class="lcars-line-xtick" x="${p.x.toFixed(1)}" y="${(p.y + 4).toFixed(1)}" text-anchor="middle">${Math.abs(lon)}${lon === 0 || Math.abs(lon) === 180 ? '' : lon > 0 ? 'E' : 'W'}</text>`;
    }
    return svg;
}

function weatherSphereSvg({ id, size, projection, layers = [], coast = null, lines = [], markers = [], hoverText = null, drag = null, title = 'Map', graticuleDeg = 15, labels = true }) {
    const proj = projection;
    WEATHER_MAP_REGISTRY[id] = { frame: { width: size, height: size }, invert: proj.invert, hoverText, drag };
    const clip = `${id}-clip`;
    const parts = [`<defs><clipPath id="${clip}"><circle cx="${proj.cx}" cy="${proj.cy}" r="${proj.R}"/></clipPath></defs>`,
        `<circle cx="${proj.cx}" cy="${proj.cy}" r="${proj.R}" fill="#000" stroke="var(--tng-periwinkle)" stroke-width="1.5"/>`];
    const inner = [];
    layers.forEach((layer) => inner.push(weatherSphereCellsSvg(layer, proj)));
    inner.push(`<path class="weather-map-graticule" d="${weatherSpherePath(proj, weatherSphereGraticule(proj, graticuleDeg))}" fill="none"/>`);
    if (coast && coast.length) {
        inner.push(`<path class="weather-map-coast" d="${weatherSpherePath(proj, coast.map((ring) => ring.map(([lon, lat]) => [lat, lon])))}" fill="none" stroke="var(--tng-periwinkle)" stroke-width="0.8" opacity=".6"/>`);
    }
    lines.forEach((line) => inner.push(`<path d="${weatherSpherePath(proj, line.polylines)}" fill="none" stroke="${line.stroke}" stroke-width="${line.width || 1}"${line.dash ? ` stroke-dasharray="${line.dash}"` : ''}${line.opacity ? ` opacity="${line.opacity}"` : ''}/>`));
    parts.push(`<g clip-path="url(#${clip})">${inner.join('')}</g>`);
    if (labels) {
        parts.push(weatherSphereLabels(proj));
    }
    markers.forEach((m) => {
        const p = proj.project(m.lat, m.lon);
        if (!p.visible) {
            return;
        }
        const colour = m.color || 'var(--space-white)';
        const left = p.x > proj.cx + proj.R * 0.55;
        parts.push(`<g class="weather-map-marker"><circle cx="${p.x.toFixed(1)}" cy="${p.y.toFixed(1)}" r="4.5" fill="none" stroke="${colour}" stroke-width="2"/>`
            + `<text x="${(left ? p.x - 8 : p.x + 8).toFixed(1)}" y="${(p.y + 4).toFixed(1)}" text-anchor="${left ? 'end' : 'start'}" fill="${colour}" font-size="11">${escapeChartText(m.label)}</text></g>`);
    });
    const handlers = `${hoverText ? ` onpointermove="weatherMapHover(event, '${id}')"` : ''}${drag ? ` onpointerdown="weatherMapDragStart(event, '${id}')"` : (hoverText ? ` onpointerdown="weatherMapHover(event, '${id}')"` : '')}`;
    return `
        <svg class="weather-map weather-sphere${drag ? ' is-draggable' : ''}" viewBox="0 0 ${size} ${size}" role="img" aria-label="${escapeChartText(title)}"${handlers}>
            ${parts.join('\n            ')}
        </svg>
        <div class="weather-map-readout" id="${id}-readout">${hoverText ? `${drag ? 'Drag to turn the globe. ' : ''}Move the pointer (or touch the map) for the value at that place.` : ''}</div>`;
}

// Drag on a map: calls the map's drag(dx, dy) with the movement in map units since the last call; document-level listeners, so the map
// can be redrawn (replaced) under the pointer while dragging.
function weatherMapDragStart(event, id) {
    const entry = WEATHER_MAP_REGISTRY[id];
    if (!entry || !entry.drag || event.button > 0) {
        return;
    }
    const box = event.currentTarget.getBoundingClientRect();
    const scale = entry.frame.width / box.width;
    let last = { x: event.clientX, y: event.clientY };
    let pending = null;
    event.preventDefault();
    const move = (e) => {
        pending = { dx: (e.clientX - last.x) * scale, dy: (e.clientY - last.y) * scale };
        last = { x: e.clientX, y: e.clientY };
        const fresh = WEATHER_MAP_REGISTRY[id];
        if (fresh && fresh.drag && pending) {
            const p = pending;
            pending = null;
            fresh.drag(p.dx, p.dy);
        }
    };
    const up = () => {
        window.removeEventListener('pointermove', move);
        window.removeEventListener('pointerup', up);
        window.removeEventListener('pointercancel', up);
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
    window.addEventListener('pointercancel', up);
}
