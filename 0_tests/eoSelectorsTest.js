/* Tests of the EO control panel's selectors (no dependencies; run: node 0_tests/eoSelectorsTest.js).
   Loads assets/eoOptions.js and assets/eoPanel.js into a bare context (the map and DOM are stubbed) and checks
   the SOURCE table (one line per real source, listing only those that match every filter), the filter lists,
   the highlight, SELECT and its SOURCE SELECTED table, and the order of the control buttons. */

const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ROOT = path.resolve(__dirname, '..');
const read = (...parts) => fs.readFileSync(path.join(ROOT, ...parts), 'utf8');

// Stand-ins for the elements the code writes into.
const fakeList = { innerHTML: '', querySelector: () => null };
const fakeCount = { textContent: '' };
const fakeParams = { innerHTML: '' };
let panelConfig = null;
const sandbox = {
    console,
    document: { getElementById: (id) => (id === 'eo-source-list' ? fakeList : id === 'eo-source-count' ? fakeCount : id === 'eo-params' ? fakeParams : null) },
    registerLocationMapPanel: (config) => { panelConfig = config; return { getMap: () => null, initMap: () => null }; },
};
vm.createContext(sandbox);
for (const file of ['eoOptions.js', 'eoPanel.js']) {
    vm.runInContext(read('assets', file), sandbox, { filename: file });
}
const run = (code) => vm.runInContext(code, sandbox);

let failed = 0;
let passed = 0;
function check(name, ok, detail) {
    if (ok) {
        passed += 1;
    } else {
        failed += 1;
        console.log(`FAIL ${name}${detail ? `: ${detail}` : ''}`);
    }
}

const ALL = { level: 'ALL', band: 'ALL', resolution: 'ALL', organisation: 'ALL', satellite: 'ALL', useCase: 'ALL', source: 'ALL' };
const sources = run('EO_SOURCES');
const setQuery = (query) => run(`Object.assign(eoQuery, ${JSON.stringify({ ...ALL, ...query })})`);
const matches = (query) => {
    setQuery(query);
    return run('eoMatchingSources()');
};
const labels = (list) => list.map(([, source]) => source.label);
const esc = (text) => text.replace(/&/g, '&amp;');

// 1. the table and the fixed vocabularies agree
const LEVELS = run('EO_LEVELS');
const BANDS = run('EO_BANDS');
const RANGES = run('EO_RESOLUTION_RANGES').map(([value]) => value);
check('the table has 54 sources', sources.length === 54, `${sources.length}`);
check('every source has a label and an archive', sources.every((s) => s.label.length > 0 && s.archive.length > 0));
check('labels are unique', new Set(sources.map((s) => s.label)).size === sources.length);
check('levels are from the allowed list', sources.every((s) => s.levels.every((v) => LEVELS.includes(v))));
check('bands are from the allowed list', sources.every((s) => s.bands.every((v) => BANDS.includes(v))));
check('resolution ranges are from the five ranges', sources.every((s) => s.resolutions.every((v) => RANGES.includes(v))));
check('no source has a stray bracket from a split CSV cell', sources.every((s) => [...s.satellites, ...s.organisations, ...s.useCases].every((v) => (v.match(/\(/g) || []).length === (v.match(/\)/g) || []).length)));

// 2. with every filter on ALL, the table lists every real source (and nothing else)
let m = matches({});
check('no filter: all sources listed', m.length === sources.length);
check('count text', run('eoSourceCountText(54)') === '54 MATCH' && run('eoSourceCountText(0)') === 'NO MATCH');

// 3. the table agrees with a plain filter of the source list, for single filters and for combinations
const FIELDS = { level: 'levels', band: 'bands', resolution: 'resolutions', organisation: 'organisations', satellite: 'satellites', useCase: 'useCases' };
const expected = (query) => sources.map((s, i) => [s, i]).filter(([s]) => Object.entries(FIELDS)
    .every(([key, field]) => !query[key] || query[key] === 'ALL'
        // RESOLUTION is "this fine or better": some range of the source is the chosen one or finer (RANGES runs finest first)
        || (key === 'resolution' ? s[field].some((range) => RANGES.indexOf(range) <= RANGES.indexOf(query[key])) : s[field].includes(query[key])))).map(([, i]) => String(i));
const cases = [
    { band: 'SAR' }, { level: 'L1C' }, { resolution: '0-20' }, { organisation: 'NASA' }, { satellite: 'Sentinel-1A' }, { useCase: 'sea ice' },
    { level: 'L1B', band: 'SAR' }, { band: 'LIDAR', resolution: '20-100' }, { organisation: 'ESA', level: '2', band: 'RADAR' },
    { band: 'B-FIELD', level: 'L1B' }, { band: 'GRAVITY' }, { level: '0' }, { level: 'L1A' },
];
for (const c of cases) {
    const got = matches(c).map(([value]) => value);
    const want = expected(c);
    check(`filter ${JSON.stringify(c)}`, JSON.stringify([...got].sort()) === JSON.stringify([...want].sort()), `${got.length} vs ${want.length}`);
    const lines = got.map((value) => run(`eoSourceLine(EO_SOURCES[${value}])`));
    check(`filter ${JSON.stringify(c)} lists alphabetically`, lines.every((line, i) => i === 0 || lines[i - 1].localeCompare(line, 'en', { sensitivity: 'base', numeric: true }) <= 0));
}

// 4. anchored cases
m = matches({ band: 'GRAVITY' });
check('GRAVITY: only GRACE-FO', m.length === 1 && /GRACE-FO/.test(labels(m)[0]), JSON.stringify(labels(m)));
m = matches({ band: 'B-FIELD' });
check('B-FIELD: only Swarm', m.length === 1 && /Swarm/.test(labels(m)[0]), JSON.stringify(labels(m)));
m = matches({ band: 'B-FIELD', useCase: 'rainfall' });
check('an impossible combination lists nothing', m.length === 0, JSON.stringify(labels(m)));

// 5. every option a filter offers matches at least one source (nothing leads to an empty list on its own)
const lists = { level: LEVELS, band: BANDS, resolution: RANGES, organisation: run('EO_ORGANISATIONS'), satellite: run('EO_SATELLITES'), useCase: run('EO_USE_CASES') };
const empty = [];
for (const [key, values] of Object.entries(lists)) {
    for (const v of values) {
        if (matches({ [key]: v }).length === 0) {
            empty.push(`${key}=${v}`);
        }
    }
}
// L1A is in the allowed list but no source offers it (none of the table's level texts maps to it); that is expected.
const unexpected = empty.filter((e) => e !== 'level=L1A');
check('every filter option matches a source (except L1A)', unexpected.length === 0, unexpected.join(', '));

// 6. the table's lines and the highlight
setQuery({});
run('refreshEoSourceList()');
check('the table has one line per source', (fakeList.innerHTML.match(/class="eo-source-row/g) || []).length === sources.length);
check('each line is five parts joined by " - " (satellites, archive, levels, frequencies, resolutions), with no header row', sources.every((source) => run(`eoSourceLine(${JSON.stringify(source)})`).split(' - ').length === 5) && !/eo-source-columns/.test(read('assets', 'eoPanel.js')));
check('a line reads as expected', /eo-source-row[^>]*>Sentinel-2A, Sentinel-2B, Sentinel-2C - Copernicus Data Space Ecosystem \(CDSE\) - L1B, L1C, 2 - VIS, NIR, SWIR, MULTISPECTRAL - 0-20 M, 20-100 M</.test(fakeList.innerHTML));
check('the count is written', fakeCount.textContent === 'MATCHES: 54', fakeCount.textContent);
check('no line is highlighted at first', !/is-selected/.test(fakeList.innerHTML) && run('eoQuery.source') === 'ALL');

run("chooseEoSource('11')");
check('choosing a line highlights it', run('eoQuery.source') === '11' && /is-selected[^>]*data-source="11"/.test(fakeList.innerHTML));
check('only that line is highlighted', (fakeList.innerHTML.match(/is-selected/g) || []).length === 1);
run("chooseEoSource('11')");
check('choosing it again clears the highlight', run('eoQuery.source') === 'ALL' && !/is-selected/.test(fakeList.innerHTML));

run("chooseEoSource('11')");
setQuery({ band: 'GRAVITY', source: '11' });
run('refreshEoSourceList()');
check('a highlighted source that stops matching is cleared', run('eoQuery.source') === 'ALL');
check('the table is rewritten for the new filters', /GRACE-FO/.test(fakeList.innerHTML) && !/Sentinel-2A/.test(fakeList.innerHTML) && fakeCount.textContent === 'MATCHES: 1', fakeCount.textContent);
setQuery({ band: 'B-FIELD', useCase: 'rainfall' });
run('refreshEoSourceList()');
check('no match: empty table and MATCHES: 0', fakeList.innerHTML === '' && fakeCount.textContent === 'MATCHES: 0');
setQuery({});
run('refreshEoSourceList()');
check('text is HTML-escaped in lines', !/<script|&(?!amp;|quot;|lt;)/.test(fakeList.innerHTML));

// 7. SELECT: the SOURCE SELECTED table is empty until SELECT is pressed, then shows what was chosen at that moment
check('the table starts empty', fakeParams.innerHTML === '');
setQuery({ level: 'L1B', band: 'SAR', resolution: '0-20', satellite: 'Sentinel-1A' });
run('selectEoParameters()');
let html = fakeParams.innerHTML;
check('the title is SOURCE SELECTED', html.includes('<th colspan="2">SOURCE SELECTED</th>'));
check('SELECT writes a row for every parameter and the source', ['LEVEL', 'FREQUENCY', 'RESOLUTION', 'ORGANISATION', 'SATELLITE', 'USE CASE', 'SOURCE'].every((label) => html.includes(`<th scope="row">${label}</th>`)));
check('with no source highlighted, the chosen filters are shown', html.includes('<td>L1B</td>') && html.includes('<td>SAR</td>') && html.includes('<td>0-20 M</td>') && html.includes('<td>Sentinel-1A</td>'));
check('filters left on ALL show ALL', html.includes('<th scope="row">ORGANISATION</th><td>ALL</td>') && html.includes('<th scope="row">USE CASE</th><td>ALL</td>'));
check('with no source highlighted, SOURCE shows ALL and the match count', /<th scope="row">SOURCE<\/th><td>ALL \(\d+ MATCH\)<\/td>/.test(html), html.slice(-120));
const idx = run('eoMatchingSources()')[0][0];
setQuery({ level: 'L1B', band: 'SAR', source: idx });
run('selectEoParameters()');
html = fakeParams.innerHTML;
const chosen = sources[Number(idx)];
check('with a source highlighted, SOURCE shows its label', html.includes(`<th scope="row">SOURCE</th><td>${esc(chosen.label)}</td>`), chosen.label);
check('with a source highlighted, each parameter shows the source\'s own values', html.includes(`<th scope="row">LEVEL</th><td>${chosen.levels.join(', ')}</td>`) && html.includes(`<th scope="row">SATELLITE</th><td>${esc(chosen.satellites.join(', '))}</td>`));
setQuery({});
check('the table keeps what was chosen at the press, not later choices', fakeParams.innerHTML.includes(esc(chosen.label)));

// 7b. SOURCE DESCRIPTION: what the source provides, its intended uses and a sentence on the licence
const descriptions = sources.map((source) => run(`eoSourceDescription(${JSON.stringify(source)})`));
check('every source has a description', descriptions.every((d) => d.length > 60 && !/undefined|null|NaN/.test(d)));
check('each description names the satellites and the archive', sources.every((source, i) => descriptions[i].includes(source.archive) && source.satellites.every((name) => descriptions[i].includes(name))));
check('each description gives the intended uses', sources.every((source, i) => source.useCases.every((useCase) => descriptions[i].includes(useCase)) && /Intended uses: /.test(descriptions[i])));
check('each description has one licence sentence, saying when it is not yet confirmed', sources.every((source, i) => (descriptions[i].match(/Licence/g) || []).length === 1 && descriptions[i].includes(source.licenceOk ? 'Licence: ' : 'Licence not yet confirmed: ')));
check('each description says what it provides, with the modality and levels', sources.every((source, i) => descriptions[i].includes(`Provides ${source.modality}`) && source.levels.every((level) => descriptions[i].includes(level))));
check('descriptions end with a full stop', descriptions.every((d) => d.endsWith('.')));
check('descriptions are distinct', new Set(descriptions).size === descriptions.length);
const gedi = sources.findIndex((x) => /GEDI/.test(x.label));
check('a worked example reads sensibly', /^GEDI and International Space Station from NASA LP DAAC\. Provides Waveform lidar.*Intended uses: forest biomass, canopy height, carbon and ecosystem structure\. Licence: /.test(descriptions[gedi]), descriptions[gedi]);
setQuery({ source: String(gedi) });
run('selectEoParameters()');
check('SELECT writes the SOURCE DESCRIPTION block under the table', /SOURCE SELECTED<\/th>[\s\S]*<div class="eo-desc-title">SOURCE DESCRIPTION<\/div><p class="eo-desc-text">GEDI and International/.test(fakeParams.innerHTML));
setQuery({});
run('selectEoParameters()');
check('with no source highlighted the description says so', /eo-desc-text">No source is highlighted\./.test(fakeParams.innerHTML));

// DATA ATTRIBUTION: under SOURCE DESCRIPTION, a credit line for the selected source
const credit = (i) => run(`eoSourceAttribution(EO_SOURCES[${i}])`);
const s2 = sources.findIndex((x) => /Sentinel-2A/.test(x.label));
check('a Sentinel source gets the Copernicus Sentinel data line', /^Contains modified Copernicus Sentinel data \d{4}\./.test(credit(s2)), credit(s2));
check('a USGS source is credited to the U.S. Geological Survey', sources.every((x, i) => !x.organisations.includes('USGS') || credit(i).includes('U.S. Geological Survey')));
check('every credit names the archive and ends with a licence sentence', sources.every((x, i) => credit(i).includes(`Accessed via ${x.archive}.`) && /(provider|reuse)\.$/.test(credit(i))));
check('an unconfirmed licence is flagged', sources.every((x, i) => x.licenceOk || credit(i).includes('Licence not yet confirmed')));
setQuery({ source: String(s2) });
run('selectEoParameters()');
check('SELECT writes DATA ATTRIBUTION after the description', /SOURCE DESCRIPTION[\s\S]*<div class="eo-desc-title">DATA ATTRIBUTION<\/div><p class="eo-desc-text">Contains modified Copernicus/.test(fakeParams.innerHTML));
setQuery({});

// 8. the buttons: SELECT, TGT LOCN / CITY LBL, TGT FOCUS (top left, top right / bottom left, bottom right)
check('EO passes SELECT as the leading button and TGT FOCUS as the extra one', panelConfig.leadingButtons.length === 1 && panelConfig.leadingButtons[0].label === 'SELECT' && panelConfig.extraButtons.length === 1 && panelConfig.extraButtons[0].label === 'TGT FOCUS' && panelConfig.buttonLabel === 'TGT LOCN');
let registered = null;
const panelSandbox = { console, registerPanelControls: (id, config) => { registered = config; }, lcarsColour: () => '#000' };
vm.createContext(panelSandbox);
vm.runInContext(read('assets', 'locationMapPanel.js'), panelSandbox, { filename: 'locationMapPanel.js' });
const labelsOf = (config) => { vm.runInContext(`registerLocationMapPanel(${JSON.stringify(config)})`, panelSandbox); return registered.buttons.map((b) => b.label); };
check('the 2 x 2 order is SELECT, TGT LOCN, CITY LBL, TGT FOCUS', JSON.stringify(labelsOf({ sectionId: 'eo', containerId: 'x', buttonLabel: 'TGT LOCN', leadingButtons: [{ label: 'SELECT' }], extraButtons: [{ label: 'TGT FOCUS' }] })) === JSON.stringify(['SELECT', 'TGT LOCN', 'CITY LBL', 'TGT FOCUS']));
check('a panel with no leading button keeps its old order (GS OPS)', JSON.stringify(labelsOf({ sectionId: 'gs-ops', containerId: 'y', buttonLabel: 'GS LOCN', extraButtons: [{ label: 'GRND STN' }, { label: 'VIS NOW' }] })) === JSON.stringify(['GS LOCN', 'CITY LBL', 'GRND STN', 'VIS NOW']));

// 9. EO imagery (assets/eoImagery.js): the WGS84 UTM conversion used to cut the chip out of the scene
const imagery = { console, document: { getElementById: () => null }, EO_METRES_PER_DEGREE: 111320, eoEscape: (t) => t };
vm.createContext(imagery);
vm.runInContext(read('assets', 'eoImagery.js').replace(/^const /gm, 'var '), imagery, { filename: 'eoImagery.js' });
const utm = (lat, lon, zone, south) => vm.runInContext(`eoUtmForward(${lat}, ${lon}, ${zone}, ${!!south})`, imagery);
const equator = utm(0, -2, 30, false);
check('UTM: 1 degree east of the central meridian on the equator', Math.abs(equator.easting - 611280.65) < 1 && Math.abs(equator.northing) < 1, JSON.stringify(equator));
const centre = utm(51.5, -3, 30, false);
check('UTM: on the central meridian the easting is 500000 and the northing 0.9996 x the meridian arc', Math.abs(centre.easting - 500000) < 0.01 && Math.abs(centre.northing - 5705429.167) < 0.01, JSON.stringify(centre));
const southern = utm(-33.9, 151.2, 56, true);
check('UTM: Sydney (zone 56 south) lands where its Sentinel-2 tiles are', Math.abs(southern.easting - 334000) < 3000 && Math.abs(southern.northing - 6247000) < 3000, JSON.stringify(southern));

// 6. only IMAGE OVERLAY sources can be drawn on the map; every other source gets the NOT YET AVAILABLE notice
const overlayable = sources.filter((x) => x.visualisation === 'IMAGE OVERLAY');
check('every source has a visualisation class', sources.every((x) => x.visualisation.length > 0));
check('21 sources are image overlays', overlayable.length === 21, `${overlayable.length}`);
check('Google Earth Engine is excluded', sources.filter((x) => x.visualisation === 'EXCLUDED').length === 1 && sources.find((x) => x.archive === 'Google Earth Engine').visualisation === 'EXCLUDED');
const elementIndex = sources.findIndex((x) => x.archive === 'Element 84 Earth Search on AWS');
const profileIndex = sources.findIndex((x) => x.visualisation === 'PROFILE PLOT');
check('the Element 84 source is an image overlay', sources[elementIndex].visualisation === 'IMAGE OVERLAY');
setQuery({ source: String(elementIndex) });
check('an image-overlay source is drawn', run('eoSourceIsOverlayable(eoHighlightedSource())') === true);
setQuery({ source: String(profileIndex) });
check('a profile-plot source gets the notice', run('eoSourceIsOverlayable(eoHighlightedSource())') === false);
setQuery({});
check('no highlighted source keeps the default (drawn)', run('eoSourceIsOverlayable(eoHighlightedSource())') === true);

// 7. the image-search settings: MAX CLOUD COVER and MAX LOOKBACK
const imageSelectors = run('EO_IMAGE_SELECTORS');
const optionValues = (key) => imageSelectors.find((x) => x.key === key) && run(`EO_IMAGE_SELECTORS.find((x) => x.key === '${key}').options()`);
check('MAX CLOUD COVER offers 10, 25 and 50 per cent', JSON.stringify(optionValues('maxCloud').map(([v]) => v)) === '["10","25","50"]');
check('MAX LOOKBACK offers 24 hrs, 1 week, 1 month, 3 months, 1 year', JSON.stringify(optionValues('lookback').map(([, t]) => t)) === '["24 HRS","1 WEEK","1 MONTH","3 MONTHS","1 YEAR"]');
check('the defaults are 25% cloud and 3 months', run('eoQuery.maxCloud') === '25' && run('eoQuery.lookback') === '90');
check('left column order is LEVEL, FREQUENCY, RESOLUTION, SATELLITE', JSON.stringify(run('EO_SELECTORS.slice(0, 4).map((x) => x.label)')) === '["LEVEL","FREQUENCY","RESOLUTION","SATELLITE"]');
check('right column order is ORGANISATION, USE CASE, MAX CLOUD COVER, MAX LOOKBACK', JSON.stringify(run('[...EO_SELECTORS.slice(4), ...EO_IMAGE_SELECTORS].map((x) => x.label)')) === '["ORGANISATION","USE CASE","MAX CLOUD COVER","MAX LOOKBACK"]');
const before = matches({}).length;
setQuery({ maxCloud: '10', lookback: '1' });
check('the image-search settings do not filter the SOURCE table', run('eoMatchingSources().length') === before);
setQuery({});
check('the error notice reports shown / hidden', run("setEoMapError('NO CLEAR SCENE')") === true && run("setEoMapError('')") === false);

// 8. the AREA setting (TGT LOCN form) and the area imagery plan
check('AREA offers 5, 10, 25, 50 and 100 km', JSON.stringify(run('EO_AREAS.map(([, t]) => t)')) === '["5 KM","10 KM","25 KM","50 KM","100 KM"]');
check('the default area is 10 km', run('eoQuery.area') === '10');
const areaRow = run('eoAreaRowHtml()');
check('the TGT LOCN form row has an AREA label, five options and 10 KM selected', /for="eo-area-select">AREA</.test(areaRow) && (areaRow.match(/<option /g) || []).length === 5 && /value="10" selected/.test(areaRow), areaRow);
const bounds0 = run('eoAreaBounds(0, 10, 10000)');
check('area bounds: 10 km at the equator is about 0.09 degrees a side, centred', Math.abs((bounds0[1][0] - bounds0[0][0]) - 10000 / 111320) < 1e-9 && Math.abs((bounds0[0][1] + bounds0[1][1]) / 2 - 10) < 1e-9);
const bounds60 = run('eoAreaBounds(60, 10, 10000)');
check('area bounds: at 60 degrees north the longitude span is twice the latitude span', Math.abs((bounds60[1][1] - bounds60[0][1]) / (bounds60[1][0] - bounds60[0][0]) - 2) < 0.01);
const plan = (km) => vm.runInContext(`eoAreaPlan(${km * 1000})`, imagery);
const planText = [5, 10, 25, 50, 100].map((km) => { const x = plan(km); return `${x.factor}:${x.pixels}`; }).join(' ');
check('area plan: native pixels to 10 km, then overviews x2, x4, x8 keeping 1250 pixels', planText === '1:500 1:1000 2:1250 4:1250 8:1250', planText);
check('area plan: pixel size follows the factor', plan(100).pixelMetres === 80 && plan(10).pixelMetres === 10);
// The lattice mapper agrees with exact projection over a 100 km area
vm.runInContext('globalThis.testProject = (lat, lon) => { const u = eoUtmForward(lat, lon, 30, false); return { col: (u.easting - 600000) / 80, row: (u.northing - 5800020) / -80 }; }', imagery);
vm.runInContext('globalThis.testMapper = eoLatticeMapper([[51.05, -0.8], [51.95, 0.6]], testProject)', imagery);
let worst = 0;
for (const [x, y] of [[0.03, 0.04], [0.5, 0.5], [0.97, 0.02], [0.2, 0.9], [0.77, 0.61], [0.999, 0.999]]) {
    const got = vm.runInContext(`testMapper(${x}, ${y})`, imagery);
    const lat = 51.95 - y * 0.9;
    const lon = -0.8 + x * 1.4;
    const exact = vm.runInContext(`testProject(${lat}, ${lon})`, imagery);
    worst = Math.max(worst, Math.abs(got.col - exact.col), Math.abs(got.row - exact.row));
}
check('lattice mapper is within 0.1 pixel of exact projection over about 100 km', worst < 0.1, `${worst}`);
setQuery({ source: String(elementIndex) });
run('selectEoParameters()');
check('SELECT lists the AREA', /<th scope="row">AREA<\/th><td>10 KM SQUARE<\/td>/.test(fakeParams.innerHTML));
setQuery({});

// RESOLUTION selects sources that are this fine or better: each coarser choice keeps everything the finer one had
const byRange = RANGES.map((range) => new Set(matches({ resolution: range }).map(([value]) => value)));
check('RESOLUTION: each coarser choice includes every source of the finer one', byRange.every((set, i) => i === 0 || [...byRange[i - 1]].every((value) => set.has(value))));
const withRange = sources.filter((x) => x.resolutions.length > 0).length;
check('RESOLUTION: the coarsest choice lists every source that states a resolution', byRange[byRange.length - 1].size === withRange, `${byRange[byRange.length - 1].size} vs ${withRange}`);
check('RESOLUTION: 0-20 M lists only sources that offer 0-20 M', [...byRange[0]].every((value) => sources[Number(value)].resolutions.includes('0-20')));
setQuery({});

console.log(`${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
