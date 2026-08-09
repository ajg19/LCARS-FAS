/* ==========================================================================
   GROUND SEGMENT / INFRASTRUCTURE PANEL

   Split out of lcars.js. Lazily loaded (alongside assets/mapCore.js) the
   first time GRND SGMNT is opened -- see openInfrastructureSection() in
   lcars.js for the load sequence. Registers this panel's control-area
   buttons with lcars.js's registerPanelControls() at the bottom of this
   file rather than lcars.js's updateControlArea() knowing about
   infrastructure's specifics directly.
   ========================================================================== */

// Which ground segment asset types are toggled on for map plotting,
// persisted across reloads via localStorage rather than reset every visit.
// The 12 values here match the `type` column in the ground_segment_assets
// table exactly (see rschGrdSgmt/build_ground_segment_db.py) -- these are
// the strings map-filtering code will eventually match against, not just
// display labels.
const ASSET_TYPES = [
    'Launch Site', 'MCC', 'Downrange Infrastructure', 'DSN', 'Space Park',
    'Space Test Facility', 'GSaaS', 'TT&C', 'Constellation Gateway', 'Teleport',
    'SSA', 'SLR',
];
const ASSET_TYPE_VISIBILITY_STORAGE_KEY = 'grndSgmntAssetTypeVisibility';

// On a genuinely first visit (nothing saved yet), only Launch Site starts
// toggled on -- every other type defaults to off until the user turns it
// on themselves.
function defaultAssetTypeVisibility() {
    const visibility = {};
    ASSET_TYPES.forEach((type) => {
        visibility[type] = (type === 'Launch Site');
    });
    return visibility;
}

// Reads the saved on/off state for each asset type, writing the default
// back to localStorage the first time this ever runs so subsequent reads
// (and the browser's storage inspector, if anyone looks) see an explicit
// saved value rather than an absent key. Falls back to the default per
// key if a saved object is missing one -- e.g. after ASSET_TYPES gains a
// new entry that an older saved blob predates.
function loadAssetTypeVisibility() {
    const defaults = defaultAssetTypeVisibility();
    let saved = null;
    try {
        const raw = localStorage.getItem(ASSET_TYPE_VISIBILITY_STORAGE_KEY);
        saved = raw ? JSON.parse(raw) : null;
    } catch (error) {
        console.error('Could not read asset type visibility from localStorage:', error);
    }

    if (!saved) {
        saveAssetTypeVisibility(defaults);
        return defaults;
    }

    const merged = { ...defaults, ...saved };
    return merged;
}

function saveAssetTypeVisibility(visibility) {
    try {
        localStorage.setItem(ASSET_TYPE_VISIBILITY_STORAGE_KEY, JSON.stringify(visibility));
    } catch (error) {
        console.error('Could not save asset type visibility to localStorage:', error);
    }
}

// Loaded once when this file first loads (i.e. the first time GRND SGMNT
// is opened) so the correct state, default or saved, is available as soon
// as anything needs it.
let assetTypeVisibility = loadAssetTypeVisibility();

// One Leaflet layer group per asset type (the 12 categories in
// INFRASTRUCTURE_ASSET_KEY below), built once when the ground segment data
// loads. Keyed by the same canonical `type` string as assetTypeVisibility,
// so toggling a category is just adding/removing its one layer group
// rather than looping over every marker.
let assetTypeLayers = {};

// Shape/colour/label/type for each of the 12 categories -- the single
// source both the control-area key/buttons AND the map markers derive
// from, so a category can never show a different colour in one place than
// the other the way the old CONTROL_AREA_ASSET_KEYS/CONTROL_AREA_BUTTON_LABELS
// (two parallel structures matched only by label-text equality) allowed.
// Column-major order -- LAUNCH/MCC/DWN RNGE/DSN fill column 1 top-to-
// bottom, GSaaS/TT&C/CONST GS/TELEPORT fill column 2, and SPCE PARK/TST
// FACILITY/SSA/SLR fill column 3 -- to match .control-area-key's
// grid-auto-flow: column.
//
// Colour and shape both encode category here (not colour alone, since 12
// categories can't be told apart by hue alone at a glance, particularly
// for colourblind users): each family of related categories shares a hue,
// with shape distinguishing members within that family, and shade
// distinguishing hue depth within the family.
const INFRASTRUCTURE_ASSET_KEY = [
    { label: 'LAUNCH', color: '#ffd27a', shape: 'circle', type: 'Launch Site' },
    { label: 'MCC', color: '#ffb347', shape: 'square', type: 'MCC' },
    { label: 'DWN RNGE', color: '#e8912a', shape: 'triangle', type: 'Downrange Infrastructure' },
    { label: 'DSN', color: '#b8651a', shape: 'asterisk', type: 'DSN' },
    { label: 'GSaaS', color: '#8ecbff', shape: 'circle', type: 'GSaaS' },
    { label: 'TT&C', color: '#5b9bd8', shape: 'square', type: 'TT&C' },
    { label: 'CONST GS', color: '#3a6fb0', shape: 'triangle', type: 'Constellation Gateway' },
    { label: 'TELEPORT', color: '#1f4e8c', shape: 'asterisk', type: 'Teleport' },
    { label: 'SPCE PARK', color: '#8fd19e', shape: 'circle', type: 'Space Park' },
    { label: 'TST FACILITY', color: '#3f9e5c', shape: 'square', type: 'Space Test Facility' },
    { label: 'SSA', color: '#c9a6e8', shape: 'triangle', type: 'SSA' },
    { label: 'SLR', color: '#8654b0', shape: 'triangle-down', type: 'SLR' },
];

// Shape/colour lookup by canonical type, derived from
// INFRASTRUCTURE_ASSET_KEY so map markers use the exact same shape+colour
// language as the key and buttons.
const ASSET_TYPE_STYLE = new Map(INFRASTRUCTURE_ASSET_KEY.map((entry) => [entry.type, entry]));

// Wired to the INFRASTRUCTURE left-menu button, alongside showSection() --
// runs once (guarded by infrastructureMap); showSection() has already made
// the section visible by the time this runs, which matters because Leaflet
// can't size itself correctly inside a display:none container.
async function initInfrastructureMap() {
    // infrastructureMap/currentMap/initBaseMap() are assets/mapCore.js
    // globals -- openInfrastructureSection() (lcars.js) guarantees
    // mapCore.js is already loaded before this runs; the extra
    // loadScriptOnce() here is just defence in depth if this is ever
    // called some other way.
    await loadScriptOnce('assets/mapCore.js');

    if (infrastructureMap) {
        currentMap = infrastructureMap;
        // Leaflet caches its container's size and doesn't recheck it on
        // its own. showSection() just set this container back to
        // display:block after it was display:none while a different
        // section was open -- without this, the map can render blank or
        // stale on every re-entry after the first.
        infrastructureMap.invalidateSize();
        return;
    }

    try {
        infrastructureMap = await initBaseMap('infrastructure-map');
        currentMap = infrastructureMap;
        renderLatLonGraticule(infrastructureMap);

        const assetsResponse = await fetch('api/ground-segment-assets');
        if (!assetsResponse.ok) {
            throw new Error(`HTTP error ${assetsResponse.status}`);
        }
        buildAssetTypeLayers(await assetsResponse.json());
    } catch (error) {
        console.error('Error initialising infrastructure map:', error);
    }
}

// Groups every ground_segment_assets row into one L.layerGroup per type
// (12 total) and adds only the ones currently toggled on in
// assetTypeVisibility -- the rest are built but held back, ready to be
// added the moment their button is switched on (see the onClick handler
// in the registerPanelControls() call below).
function buildAssetTypeLayers(assets) {
    assetTypeLayers = {};

    const markersByType = new Map();
    assets.forEach((asset) => {
        if (!markersByType.has(asset.type)) {
            markersByType.set(asset.type, []);
        }
        markersByType.get(asset.type).push(asset);
    });

    markersByType.forEach((assetsOfType, type) => {
        const style = ASSET_TYPE_STYLE.get(type);
        const markers = assetsOfType.map((asset) => {
            const icon = style
                ? L.divIcon({
                    className: 'map-marker-icon',
                    html: renderKeyShape(style.shape, style.color),
                    iconSize: [14, 14],
                    iconAnchor: [7, 7],
                })
                : undefined;
            // Hover shows the brief summary; clicking (while hovering)
            // upgrades the same popup's content to include the full
            // database description, rather than opening a second box.
            // Popup resets back to the brief version next time it opens.
            const briefContent = `<span class="popup-name">${asset.name}</span><br><span class="popup-meta">${asset.type} &middot; ${asset.operators}</span>`;
            const fullContent = `${briefContent}<br><br><span class="popup-desc">${asset.description}</span>`;
            const marker = L.marker([asset.latitude, asset.longitude], icon ? { icon } : {})
                .bindPopup(briefContent);
            marker.on('mouseover', () => {
                marker.setPopupContent(briefContent);
                marker.openPopup();
            });
            marker.on('mouseout', () => marker.closePopup());
            marker.on('click', () => {
                marker.setPopupContent(fullContent);
                marker.openPopup();
            });
            return marker;
        });

        const layer = L.layerGroup(markers);
        assetTypeLayers[type] = layer;
        if (assetTypeVisibility[type]) {
            layer.addTo(infrastructureMap);
        }
    });
}

// Wired to each infrastructure control-area button's click handler --
// adds or removes that category's whole layer group in one call, rather
// than looping over every marker to check its type.
function setAssetTypeLayerVisible(type, visible) {
    const layer = assetTypeLayers[type];
    if (!layer || !infrastructureMap) {
        return;
    }
    if (visible) {
        layer.addTo(infrastructureMap);
    } else {
        infrastructureMap.removeLayer(layer);
    }
}

// Registers this panel's control-area buttons with lcars.js's generic
// updateControlArea() dispatcher -- one button per asset type, rendering
// as the shape/colour key grid in #default (defaultAreaMode: 'key') plus
// the matching nav buttons, each toggling its own type's layer group on
// click. Reproduces the old CONTROL_AREA_ASSET_KEYS-driven branch's
// behaviour exactly, just driven by one array instead of two.
registerPanelControls('infrastructure', {
    defaultAreaMode: 'key',
    buttons: INFRASTRUCTURE_ASSET_KEY.map((entry) => ({
        label: entry.label,
        color: entry.color,
        shape: entry.shape,
        getText: () => `${entry.label} - ${assetTypeVisibility[entry.type] ? 'ON' : 'OFF'}`,
        onClick: () => {
            assetTypeVisibility[entry.type] = !assetTypeVisibility[entry.type];
            saveAssetTypeVisibility(assetTypeVisibility);
            setAssetTypeLayerVisible(entry.type, assetTypeVisibility[entry.type]);
        },
    })),
});
