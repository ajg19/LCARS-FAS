/* ==========================================================================
   EO PANEL

   Thin wrapper around registerLocationMapPanel() (assets/locationMapPanel.js)
   -- see that file for the shared base map + graticule + day/night
   terminator + user-location behaviour. Lazily loaded the first time EO
   is opened; openEoSection() in lcars.js loads mapCore.js, grdTrackPanel.js
   and locationMapPanel.js first.

   Payload: the shared map, opened zoomed in on the user's location.
   Control panel buttons, as a 2 x 2 grid: SELECT (top left) copies the six filters and the
   highlighted source into the parameters table at the left of the map (see selectEoParameters());
   TGT LOCN (top right) opens the shared LAT/LON/PLACE form; CITY LBL (bottom left) toggles
   city names; TGT FOCUS (bottom right) outlines the AREA chosen in the TGT LOCN form round the
   target and downloads enough imagery to cover it (see focusEoTarget()).
   The left of the control panel (#default) holds eight drop-downs in two columns of four (LEVEL,
   FREQUENCY, RESOLUTION, SATELLITE; ORGANISATION, USE CASE, then the image-search settings MAX CLOUD
   COVER and MAX LOOKBACK, which do not filter the SOURCE table) and, in a third
   column, the SOURCE table: a scrollable table with one line for each real source in the EO source
   table that matches every filter set to something other than ALL. Click a line to highlight it
   (click it again to clear); the arrow keys move the highlight. The choices are only recorded in
   eoQuery for now; no EO data is wired to them yet. The vocabularies follow the consolidated EO source table
   (enterpriseCrewOutput/uhura_eoConsolidatedApiTable_2026-10-25.xlsx): LEVEL, FREQUENCY
   and RESOLUTION are fixed lists below; the other three lists are generated from the table
   into assets/eoOptions.js by 0_tools/buildEoOptions.py (loaded before this file).
   TGT LOCN replaces the selectors while its form is open.
   ========================================================================== */

// The current choice in each selector; 'ALL' means no filter. Read by whatever
// layer is later wired to these selectors.
const eoQuery = { level: 'ALL', band: 'ALL', resolution: 'ALL', organisation: 'ALL', satellite: 'ALL', useCase: 'ALL', source: 'ALL', maxCloud: '25', lookback: '90', area: '10' };

// [value, label]. LEVEL, FREQUENCY and RESOLUTION use the table's own terms. RESOLUTION is
// one of five ranges of spatial resolution, in metres.
const EO_LEVELS = ['0', 'L1A', 'L1B', 'L1C', '2', '3', '4'];
const EO_BANDS = ['UV', 'VIS', 'NIR', 'SWIR', 'TIR', 'SAR', 'MICROWAVE', 'LIDAR', 'RADAR', 'MULTISPECTRAL', 'HYPERSPECTRAL', 'GRAVITY', 'B-FIELD'];
const EO_RESOLUTION_RANGES = [
    ['0-20', '0-20 M'], ['20-100', '20-100 M'], ['100-1000', '100 M-1 KM'], ['1000-10000', '1-10 KM'], ['10000+', '10 KM+'],
];

const withAll = (values) => [['ALL', 'ALL'], ...values.map((value) => [value, value])];

// SOURCE table: one line for each real source in the EO source table (EO_SOURCES, about 54), listing
// only the sources that match every filter set to something other than ALL. A source matches a filter
// when the value is in the list the source offers for it (RESOLUTION: when the source offers that range or a finer one). Nothing is invented: every line is a source
// that exists, with its own lists of levels, frequencies, resolution ranges, organisations, satellites
// and use cases.
const EO_FILTER_KEYS = ['level', 'band', 'resolution', 'organisation', 'satellite', 'useCase'];
// Which list of a source in EO_SOURCES feeds which filter.
const EO_FILTER_FIELDS = { level: 'levels', band: 'bands', resolution: 'resolutions', organisation: 'organisations', satellite: 'satellites', useCase: 'useCases' };

// RESOLUTION is "this fine or better": a source matches when any of its resolution ranges is the chosen
// range or a finer one. EO_RESOLUTION_RANGES runs from finest to coarsest.
const eoRangeRank = (range) => EO_RESOLUTION_RANGES.findIndex(([value]) => value === range);

// True when the source satisfies every filter that is not ALL.
function eoSourceMatches(source, query) {
    return EO_FILTER_KEYS.every((key) => {
        if (query[key] === 'ALL') {
            return true;
        }
        if (key === 'resolution') {
            return source.resolutions.some((range) => eoRangeRank(range) <= eoRangeRank(query.resolution));
        }
        return source[EO_FILTER_FIELDS[key]].includes(query[key]);
    });
}

// The sources matching every filter, as [value, source]; the value is the position in EO_SOURCES.
function eoMatchingSources() {
    const matches = [];
    EO_SOURCES.forEach((source, index) => {
        if (eoSourceMatches(source, eoQuery)) {
            matches.push([String(index), source]);
        }
    });
    // Alphabetical by the line the SOURCE table shows (satellites first, then archive, and so on).
    const lineOf = ([, source]) => eoSourceLine(source);
    return matches.sort((a, b) => lineOf(a).localeCompare(lineOf(b), 'en', { sensitivity: 'base', numeric: true }));
}

const eoSourceCountText = (count) => (count ? `${count} MATCH` : 'NO MATCH');
// The label in the SOURCE table's title bar (a black gap at its right end).
const eoMatchesLabel = (count) => `MATCHES: ${count}`;

// The six source filters: the first four are the left column, the last two the top of the right column;
// each is drawn top to bottom.
const EO_SELECTORS = [
    { key: 'level', label: 'LEVEL', options: () => withAll(EO_LEVELS) },
    { key: 'band', label: 'FREQUENCY', options: () => withAll(EO_BANDS) },
    { key: 'resolution', label: 'RESOLUTION', options: () => [['ALL', 'ALL'], ...EO_RESOLUTION_RANGES] },
    { key: 'satellite', label: 'SATELLITE', options: () => withAll(EO_SATELLITES) },
    { key: 'organisation', label: 'ORGANISATION', options: () => withAll(EO_ORGANISATIONS) },
    { key: 'useCase', label: 'USE CASE', options: () => withAll(EO_USE_CASES) },
];

// The two image-search settings, under the source filters in the right column. They do not filter the
// SOURCE table; they tell the image search how clear and how recent a scene must be. MAX CLOUD COVER is a
// percentage (10 very clear, 25 the default, i.e. over 75% clear, 50 half cloud); MAX LOOKBACK is in days.
const EO_IMAGE_SELECTORS = [
    { key: 'maxCloud', label: 'MAX CLOUD COVER', options: () => [['10', '10%'], ['25', '25%'], ['50', '50%']] },
    { key: 'lookback', label: 'MAX LOOKBACK', options: () => [['1', '24 HRS'], ['7', '1 WEEK'], ['30', '1 MONTH'], ['90', '3 MONTHS'], ['365', '1 YEAR']] },
];

const eoEscape = (text) => text.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;');

function eoOptionsHtml(selector) {
    return selector.options().map(([value, text]) =>
        `<option value="${eoEscape(value)}"${eoQuery[selector.key] === value ? ' selected' : ''}>${eoEscape(text)}</option>`).join('');
}

// The text shown for a filter value: the range's label for RESOLUTION, the value itself otherwise.
function eoValueText(key, value) {
    const selector = [...EO_SELECTORS, ...EO_IMAGE_SELECTORS].find((candidate) => candidate.key === key);
    const option = selector.options().find(([optionValue]) => optionValue === value);
    return option ? option[1] : value;
}

const eoListText = (key, values) => values.map((value) => eoValueText(key, value)).join(', ');

// A line of the SOURCE table: the five parts that specify an option, in this order, each separated by
// ' - ': satellites, archive, levels, frequencies, resolution ranges.
const EO_LINE_SEPARATOR = ' - ';
const eoSourceLine = (source) => [source.satellites.join(', '), source.archive, source.levels.join(', '), source.bands.join(', '), eoListText('resolution', source.resolutions)].join(EO_LINE_SEPARATOR);

// "a", "a and b", "a, b and c"
const eoJoin = (items) => (items.length < 2 ? items.join('') : `${items.slice(0, -1).join(', ')} and ${items[items.length - 1]}`);

// The DATA ATTRIBUTION text: the credit line for the source, built from its organisations, satellites and
// archive (the EO source table holds no credit wording of its own). The wording follows each provider's
// usual request: Copernicus Sentinel data carries the legal notice's line; NASA, USGS and NOAA data are
// credited by name; anything else names its organisations and archive, and points to the licence.
// A source whose licence is not yet confirmed says so. This is not legal advice: check the provider's terms.
function eoSourceAttribution(source) {
    const has = (name) => source.organisations.includes(name);
    const lines = [];
    if (source.satellites.some((name) => /^Sentinel/.test(name)) && (has('ESA') || has('European Commission'))) {
        lines.push(`Contains modified Copernicus Sentinel data ${new Date().getUTCFullYear()}.`);
    } else if (has('European Commission')) {
        lines.push('Contains modified Copernicus data.');
    }
    if (has('NASA')) {
        lines.push('Data courtesy of NASA.');
    }
    if (has('USGS')) {
        lines.push('Data courtesy of the U.S. Geological Survey.');
    }
    if (has('NOAA')) {
        lines.push('Data courtesy of NOAA.');
    }
    if (!lines.length) {
        lines.push(`Data: ${eoJoin(source.organisations)}.`);
    }
    lines.push(`Satellites: ${eoJoin(source.satellites)}. Accessed via ${source.archive}.`);
    lines.push(source.licenceOk ? 'Please also follow the licence terms of the provider.' : 'Licence not yet confirmed: check the provider terms before reuse.');
    return lines.join(' ');
}

// The SOURCE DESCRIPTION text: what the source provides, what it is intended for, and its licence.
// Built from the source's entry in the EO source table (assets/eoOptions.js); the licence sentence
// is the table's own note, and says so when the licence is not yet confirmed.
function eoSourceDescription(source) {
    const parts = [`${eoJoin(source.satellites)} from ${source.archive}.`];
    const provides = [`Provides ${source.modality}`];
    if (source.levels.length) {
        provides.push(`at level${source.levels.length > 1 ? 's' : ''} ${eoJoin(source.levels)}`);
    }
    if (source.resolutions.length) {
        provides.push(`in resolution range${source.resolutions.length > 1 ? 's' : ''} ${eoJoin(source.resolutions.map((range) => eoValueText('resolution', range)))}`);
    }
    parts.push(`${provides.join(', ')}.`);
    if (source.useCases.length) {
        parts.push(`Intended uses: ${eoJoin(source.useCases)}.`);
    }
    const licence = source.licence.replace(/^Licence\s+/i, '').replace(/\.$/, '');   // the sentence below already starts "Licence"
    parts.push(source.licenceOk ? `Licence: ${licence}.` : `Licence not yet confirmed: ${licence}.`);
    return parts.join(' ');
}

// Redraws the SOURCE table after a filter changes. A highlighted source that no longer matches goes
// back to none (ALL).
function refreshEoSourceList() {
    const list = document.getElementById('eo-source-list');
    const count = document.getElementById('eo-source-count');
    if (!list || !count) {
        return;
    }
    const matches = eoMatchingSources();
    if (!matches.some(([value]) => value === eoQuery.source)) {
        eoQuery.source = 'ALL';
    }
    count.textContent = eoMatchesLabel(matches.length);
    list.innerHTML = matches.map(([value, source]) => {
        const selected = eoQuery.source === value;
        return `<div class="eo-source-row${selected ? ' is-selected' : ''}" role="option" aria-selected="${selected}" data-source="${value}" title="${eoEscape(source.label)}">${eoEscape(eoSourceLine(source))}</div>`;
    }).join('');
    const chosen = list.querySelector('.is-selected');
    if (chosen && chosen.scrollIntoView) {
        chosen.scrollIntoView({ block: 'nearest' });
    }
}

// Highlights the line for `value` (clearing the highlight when it is already chosen).
function chooseEoSource(value) {
    eoQuery.source = eoQuery.source === value ? 'ALL' : value;
    refreshEoSourceList();
}

// Draws the filters and the SOURCE table into #default. Called by locationMapPanel.js when the
// section opens and whenever the location form closes; the chosen values survive because they
// live in eoQuery, not in the elements.
function renderEoSelectors(wrapper) {
    const pair = (selector) => `
        <label for="eo-select-${selector.key}">${selector.label}</label>
        <select id="eo-select-${selector.key}" class="location-input" data-eo-key="${selector.key}">${eoOptionsHtml(selector)}</select>`;
    wrapper.innerHTML = `<div class="eo-selector-form">
        <div class="eo-selector-fields">${EO_SELECTORS.slice(0, 4).map(pair).join('')}</div>
        <div class="eo-selector-fields">${[...EO_SELECTORS.slice(4), ...EO_IMAGE_SELECTORS].map(pair).join('')}</div>
        <div class="eo-source">
            <div class="eo-source-title"><span>SOURCE</span><span id="eo-source-count"></span></div>
            <div id="eo-source-list" class="eo-source-list" role="listbox" tabindex="0" aria-label="Matching sources"></div>
        </div>
    </div>`;
    wrapper.querySelectorAll('select[data-eo-key]').forEach((select) => {
        select.addEventListener('change', () => {
            eoQuery[select.dataset.eoKey] = select.value;
            refreshEoSourceList();
        });
    });
    const list = document.getElementById('eo-source-list');
    list.addEventListener('click', (event) => {
        const row = event.target.closest('.eo-source-row');
        if (row) {
            chooseEoSource(row.dataset.source);
        }
    });
    list.addEventListener('keydown', (event) => {
        const values = eoMatchingSources().map(([value]) => value);
        const at = values.indexOf(eoQuery.source);
        let next = null;
        if (event.key === 'ArrowDown') {
            next = values[Math.min(at + 1, values.length - 1)];
        } else if (event.key === 'ArrowUp') {
            next = values[at < 0 ? 0 : Math.max(at - 1, 0)];
        } else if (event.key === 'Home') {
            next = values[0];
        } else if (event.key === 'End') {
            next = values[values.length - 1];
        }
        if (next !== undefined && next !== null) {
            event.preventDefault();
            eoQuery.source = next;
            refreshEoSourceList();
        }
    });
    refreshEoSourceList();
}

// SELECT: copies the current choices into the table to the left of the map (titled SOURCE SELECTED), with
// a SOURCE DESCRIPTION block under it.
// The table is empty until SELECT is first pressed, and shows what was chosen at the moment of each
// press (it does not follow the drop-downs afterwards). With a source highlighted in the SOURCE table
// it shows that source's own values for every parameter; with none, the six filters (ALL where left
// alone) and how many sources match. Nothing else happens yet: no EO data is wired in.
// Only sources whose visualisation class is IMAGE OVERLAY can be drawn as picture tiles on the map so far
// (the class comes from the workbook's "Suggested visualisation" column). For any other highlighted source
// the map shows the error NOT YET AVAILABLE in its middle. No highlighted source keeps the Sentinel-2 default.
const EO_OVERLAY_CLASS = 'IMAGE OVERLAY';

function eoSourceIsOverlayable(source) {
    return !source || source.visualisation === EO_OVERLAY_CLASS;
}

function eoHighlightedSource() {
    return eoQuery.source === 'ALL' ? null : EO_SOURCES[Number(eoQuery.source)];
}

// Shows an error message over the middle of the map (red, LCARS pill, three times the button text), or
// removes it when text is empty. Returns true when a message is shown. Used for NOT YET AVAILABLE,
// NO CLEAR SCENE and IMAGE FETCH FAILED.
function setEoMapError(text) {
    const mapElement = document.getElementById('eo-map');
    if (!mapElement) {
        return Boolean(text);
    }
    let notice = mapElement.querySelector('.eo-map-error');
    if (text && !notice) {
        notice = document.createElement('div');
        notice.className = 'eo-map-error';
        mapElement.appendChild(notice);
    }
    if (text) {
        notice.textContent = text;
    } else if (notice) {
        notice.remove();
    }
    return Boolean(text);
}

// Clears what an earlier TGT FOCUS drew (the 3 x 3 outlines and the image chip) so nothing stale
// sits behind the notice.
function clearEoFocus() {
    const map = eoLocationPanel.getMap();
    if (map && eoFocusLayer) {
        map.removeLayer(eoFocusLayer);
        eoFocusLayer = null;
    }
    if (map && typeof clearEoTile === 'function') {
        clearEoTile(map);
    }
}

function selectEoParameters() {
    const container = document.getElementById('eo-params');
    if (!container) {
        return;
    }
    const source = eoQuery.source === 'ALL' ? null : EO_SOURCES[Number(eoQuery.source)];
    const rows = EO_SELECTORS.map((selector) => [selector.label, source ? eoListText(selector.key, source[EO_FILTER_FIELDS[selector.key]]) : eoValueText(selector.key, eoQuery[selector.key])]);
    rows.push(['SOURCE', source ? source.label : `ALL (${eoSourceCountText(eoMatchingSources().length)})`]);
    EO_IMAGE_SELECTORS.forEach((selector) => rows.push([selector.label, eoValueText(selector.key, eoQuery[selector.key])]));
    rows.push(['AREA', `${eoQuery.area} KM SQUARE`]);
    const attribution = source ? eoSourceAttribution(source) : 'No source is highlighted, so there is nothing to credit yet.';
    const description = source ? eoSourceDescription(source) : 'No source is highlighted. Highlight one in the SOURCE table, then press SELECT.';
    container.innerHTML = `<table class="eo-params-table"><thead><tr><th colspan="2">SOURCE SELECTED</th></tr></thead><tbody>${rows.map(([label, text]) =>
        `<tr><th scope="row">${label}</th><td>${eoEscape(text)}</td></tr>`).join('')}</tbody></table>
        <div class="eo-desc"><div class="eo-desc-title">SOURCE DESCRIPTION</div><p class="eo-desc-text">${eoEscape(description)}</p></div>
        <div class="eo-desc"><div class="eo-desc-title">DATA ATTRIBUTION</div><p class="eo-desc-text">${eoEscape(attribution)}</p></div>
        <div class="eo-tile-info">${typeof eoTileInfoHtml === 'function' ? eoTileInfoHtml() : ''}</div>`;
    if (setEoMapError(eoSourceIsOverlayable(source) ? '' : 'NOT YET AVAILABLE')) {
        clearEoFocus();
    }
}

// TGT FOCUS (bottom right): outlines the AREA chosen in the TGT LOCN form (a square, centred on the target),
// fits the map to it, then downloads enough of the source's imagery to cover it (assets/eoImagery.js;
// Sentinel-2 from Element 84 Earth Search for now, whichever source is highlighted). RESOLUTION only
// filters the SOURCE table: it sizes nothing here. Pressing it again redraws at the current target and
// area; a new TGT LOCN does not move the outline until TGT FOCUS is pressed again.
// AREA is the side of the square, in km. 5 and 10 km are a neighbourhood and a small town at the native
// 10 m; 25, 50 and 100 km are a city, a county and (nearly) a whole scene, read from coarser copies of
// the file so the download stays a few megabytes. Larger is not offered: a scene is only about 110 km.
const EO_AREAS = [['5', '5 KM'], ['10', '10 KM'], ['25', '25 KM'], ['50', '50 KM'], ['100', '100 KM']];
const EO_METRES_PER_DEGREE = 111320;
const EO_MAX_LATITUDE = 85;   // the map's Web Mercator limit
let eoFocusLayer = null;

// The extra row of the TGT LOCN form (locationMapPanel.js passes it to the shared form): AREA.
const eoAreaRowHtml = () => `<label for="eo-area-select">AREA</label>
                <select id="eo-area-select" class="location-input" onchange="setEoArea(this.value)">${EO_AREAS.map(([value, text]) =>
        `<option value="${value}"${eoQuery.area === value ? ' selected' : ''}>${text}</option>`).join('')}</select>`;

function setEoArea(value) {
    eoQuery.area = value;
}

// [[south, west], [north, east]] of the square of this side (metres) centred on the target.
function eoAreaBounds(latitude, longitude, areaMetres) {
    const clampLat = (lat) => Math.max(-EO_MAX_LATITUDE, Math.min(EO_MAX_LATITUDE, lat));
    const halfLat = areaMetres / EO_METRES_PER_DEGREE / 2;
    const halfLon = areaMetres / (EO_METRES_PER_DEGREE * Math.max(Math.cos(latitude * Math.PI / 180), 0.01)) / 2;
    return [[clampLat(latitude - halfLat), longitude - halfLon], [clampLat(latitude + halfLat), longitude + halfLon]];
}

async function focusEoTarget() {
    const map = eoLocationPanel.getMap();
    if (setEoMapError(eoSourceIsOverlayable(eoHighlightedSource()) ? '' : 'NOT YET AVAILABLE')) {
        clearEoFocus();
        return;
    }
    const location = await ensureObserverLocation();
    if (!map || !location) {
        return;
    }
    const { latitude, longitude } = location;
    const areaMetres = Number(eoQuery.area) * 1000;
    const bounds = eoAreaBounds(latitude, longitude, areaMetres);
    if (!map.getPane('eoOutline')) {
        map.createPane('eoOutline').style.zIndex = 460;   // above the imagery pane (eoImagery.js, 450)
    }
    const outline = L.rectangle(bounds, {
        pane: 'eoOutline',
        color: lcarsColour('--tng-amber'),
        weight: 2,
        fillColor: lcarsColour('--tng-amber'),
        fillOpacity: 0.05,
    });
    outline.bindTooltip(`TARGET AREA - ${eoQuery.area} KM SQUARE`, { className: 'city-label' });
    if (eoFocusLayer) {
        map.removeLayer(eoFocusLayer);
    }
    eoFocusLayer = L.layerGroup([outline]).addTo(map);
    map.fitBounds(bounds, { padding: [24, 24], animate: false });
    // Download the imagery covering the area (assets/eoImagery.js), loaded on first use.
    await Promise.all([loadScriptOnce('assets/geotiff/geotiff.js'), loadScriptOnce('assets/eoImagery.js')]);
    await showEoTile(map, latitude, longitude, bounds, areaMetres);
}

const eoLocationPanel = registerLocationMapPanel({
    sectionId: 'eo',
    containerId: 'eo-map',
    buttonLabel: 'TGT LOCN',
    leadingButtons: [{ label: 'SELECT', color: 'var(--tng-amber)', onClick: selectEoParameters }],
    locationFormRows: eoAreaRowHtml,
    extraButtons: [{ label: 'TGT FOCUS', color: 'var(--lilac)', onClick: focusEoTarget }],
    renderRestingArea: renderEoSelectors,
});

// Global alias so openEoSection() (lcars.js) can call it the same way the
// other sections call initGrdTrackMap() / initInfrastructureMap().
function initEoMap() {
    return eoLocationPanel.initMap();
}
