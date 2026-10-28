/* EO imagery: enough of one source's imagery to cover the AREA chosen in the TGT LOCN form, drawn on the EO map.
   Loaded on demand by TGT FOCUS in assets/eoPanel.js (with assets/geotiff/geotiff.js, which reads
   part of a cloud-optimised GeoTIFF with HTTP range requests). For now the source is always Sentinel-2
   from Element 84 Earth Search, whichever source is highlighted.

   Steps, all from the visitor's browser (nothing passes through this site's server):
     1. One STAC search on Earth Search for the newest Sentinel-2 L2A scene covering the target with cloud
        under the MAX CLOUD COVER setting, within the MAX LOOKBACK setting (eoQuery.maxCloud, eoQuery.lookback).
     2. One range read of that scene's true-colour (TCI) file covering the square area, never the whole scene
        (the file is about 320 MB). The file holds coarser copies of itself (overviews at 2, 4, 8 times the
        pixel size), so a bigger area is read from a coarser copy and the picture stays at most
        EO_AREA_MAX_PIXELS pixels across: 5-10 km at the native 10 m, 25 km at 20 m, 50 km at 40 m,
        100 km at 80 m.
     3. The area is resampled from the scene's UTM grid onto a latitude/longitude-aligned square (the
        shape the map overlay needs) and added to the map as one image layer.
   Pressing TGT FOCUS again at the same target and area does not fetch again. An area that runs past the
   edge of the scene shows the part that has data; joining neighbouring scenes is not done yet. */

const EO_STAC_SEARCH_URL = 'https://earth-search.aws.element84.com/v1/search';
const EO_TILE_COLLECTION = 'sentinel-2-l2a';
const EO_NATIVE_PIXEL_M = 10;
const EO_AREA_MAX_PIXELS = 1250;
const EO_OVERVIEW_FACTORS = [1, 2, 4, 8];
const EO_LATTICE = 16;
const EO_TILE_CREDIT = 'Contains modified Copernicus Sentinel data';

// WGS84 forward UTM (Krueger series): latitude and longitude in degrees, to easting and northing in
// metres for the given zone (the EPSG 326zz / 327zz code gives the zone and hemisphere).
function eoUtmForward(latitude, longitude, zone, south) {
    const a = 6378137;
    const f = 1 / 298.257223563;
    const k0 = 0.9996;
    const n = f / (2 - f);
    const e = Math.sqrt(f * (2 - f));
    const bigA = a / (1 + n) * (1 + n * n / 4 + n ** 4 / 64);
    const alpha = [n / 2 - 2 * n * n / 3 + 5 * n ** 3 / 16, 13 * n * n / 48 - 3 * n ** 3 / 5, 61 * n ** 3 / 240];
    const radians = Math.PI / 180;
    const phi = latitude * radians;
    const dLambda = (longitude - (zone * 6 - 183)) * radians;
    const t = Math.sinh(Math.atanh(Math.sin(phi)) - e * Math.atanh(e * Math.sin(phi)));
    const xi0 = Math.atan2(t, Math.cos(dLambda));
    const eta0 = Math.atanh(Math.sin(dLambda) / Math.sqrt(1 + t * t));
    let xi = xi0;
    let eta = eta0;
    alpha.forEach((value, index) => {
        const j = 2 * (index + 1);
        xi += value * Math.sin(j * xi0) * Math.cosh(j * eta0);
        eta += value * Math.cos(j * xi0) * Math.sinh(j * eta0);
    });
    return { easting: 500000 + k0 * bigA * eta, northing: (south ? 10000000 : 0) + k0 * bigA * xi };
}

// How the file is read for a square area of this side (metres): the smallest overview factor that keeps
// the picture within EO_AREA_MAX_PIXELS across, the pixel size that gives, and the picture's width in pixels.
function eoAreaPlan(areaMetres) {
    const factor = EO_OVERVIEW_FACTORS.find((candidate) => areaMetres / (EO_NATIVE_PIXEL_M * candidate) <= EO_AREA_MAX_PIXELS)
        || EO_OVERVIEW_FACTORS[EO_OVERVIEW_FACTORS.length - 1];
    const pixelMetres = EO_NATIVE_PIXEL_M * factor;
    return { factor, pixelMetres, pixels: Math.round(areaMetres / pixelMetres) };
}

// Maps a position in the area (x from the west edge, y from the north edge, both 0 to 1) to a pixel position
// in the scene, from a lattice of exactly projected points with bilinear interpolation between them: the
// projection is smooth, so over a 100 km area this is within a fraction of a metre of the exact answer
// and costs a few hundred projections instead of one for every output pixel.
// bounds is [[south, west], [north, east]]; project(latitude, longitude) gives { col, row }.
function eoLatticeMapper(bounds, project) {
    const [[south, west], [north, east]] = bounds;
    const grid = [];
    for (let i = 0; i <= EO_LATTICE; i++) {
        const row = [];
        for (let j = 0; j <= EO_LATTICE; j++) {
            row.push(project(north - (i / EO_LATTICE) * (north - south), west + (j / EO_LATTICE) * (east - west)));
        }
        grid.push(row);
    }
    const mapper = (x, y) => {
        const gy = Math.min(Math.max(y, 0), 1) * EO_LATTICE;
        const gx = Math.min(Math.max(x, 0), 1) * EO_LATTICE;
        const i = Math.min(EO_LATTICE - 1, Math.floor(gy));
        const j = Math.min(EO_LATTICE - 1, Math.floor(gx));
        const fy = gy - i;
        const fx = gx - j;
        const mix = (key) => (grid[i][j][key] * (1 - fx) + grid[i][j + 1][key] * fx) * (1 - fy)
            + (grid[i + 1][j][key] * (1 - fx) + grid[i + 1][j + 1][key] * fx) * fy;
        return { col: mix('col'), row: mix('row') };
    };
    mapper.grid = grid;
    return mapper;
}

// The newest Sentinel-2 L2A scene covering the point with little cloud, or null.
async function eoFindSentinel2Scene(latitude, longitude) {
    const end = new Date();
    const start = new Date(end.getTime() - Number(eoQuery.lookback) * 24 * 3600 * 1000);
    const response = await fetch(EO_STAC_SEARCH_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            collections: [EO_TILE_COLLECTION],
            intersects: { type: 'Point', coordinates: [longitude, latitude] },
            datetime: `${start.toISOString().slice(0, 19)}Z/${end.toISOString().slice(0, 19)}Z`,
            query: { 'eo:cloud_cover': { lt: Number(eoQuery.maxCloud) } },
            sortby: [{ field: 'properties.datetime', direction: 'desc' }],
            limit: 1,
        }),
    });
    if (!response.ok) {
        throw new Error(`Earth Search answered ${response.status}`);
    }
    const found = await response.json();
    return (found.features && found.features[0]) || null;
}

// The copy of the file (full size or an overview) whose pixels are `wantedFactor` times the native size.
async function eoPickImage(tiff, wantedFactor) {
    const full = await tiff.getImage(0);
    if (wantedFactor === 1) {
        return full;
    }
    const count = await tiff.getImageCount();
    for (let i = 1; i < count; i++) {
        const image = await tiff.getImage(i);
        const factor = Math.round(full.getWidth() / image.getWidth());
        if (factor === wantedFactor) {
            return image;
        }
        if (factor > wantedFactor) {
            break;
        }
    }
    throw new Error(`The file has no ${wantedFactor}x overview`);
}

// Reads the area (bounds = [[south, west], [north, east]]) from the scene's true-colour file and returns it
// as a canvas aligned to latitude/longitude, with the share of it that has data.
async function eoReadSceneArea(scene, bounds, areaMetres) {
    const asset = scene.assets.visual;
    const epsg = scene.properties['proj:epsg'];
    const transform = asset['proj:transform'];
    const zone = epsg % 100;
    const south = epsg >= 32700;
    const plan = eoAreaPlan(areaMetres);

    const tiff = await GeoTIFF.fromUrl(asset.href);
    const image = await eoPickImage(tiff, plan.factor);
    const width = image.getWidth();
    const height = image.getHeight();
    // Pixel position, in the chosen copy of the file, of a latitude/longitude.
    const project = (lat, lon) => {
        const { easting, northing } = eoUtmForward(lat, lon, zone, south);
        return { col: (easting - transform[2]) / (transform[0] * plan.factor), row: (northing - transform[5]) / (transform[4] * plan.factor) };
    };
    const mapper = eoLatticeMapper(bounds, project);
    const points = mapper.grid.flat();
    const left = Math.max(0, Math.floor(Math.min(...points.map((p) => p.col))) - 1);
    const right = Math.min(width, Math.ceil(Math.max(...points.map((p) => p.col))) + 1);
    const top = Math.max(0, Math.floor(Math.min(...points.map((p) => p.row))) - 1);
    const bottom = Math.min(height, Math.ceil(Math.max(...points.map((p) => p.row))) + 1);
    if (right <= left || bottom <= top) {
        throw new Error('The target is outside the scene');
    }

    const pixels = await image.readRasters({ window: [left, top, right, bottom], interleave: true, samples: [0, 1, 2] });
    const sourceWidth = right - left;
    const sourceHeight = bottom - top;

    const size = plan.pixels;
    const canvas = document.createElement('canvas');
    canvas.width = size;
    canvas.height = size;
    const context = canvas.getContext('2d');
    const output = context.createImageData(size, size);
    let covered = 0;
    for (let y = 0; y < size; y++) {
        for (let x = 0; x < size; x++) {
            const source = mapper((x + 0.5) / size, (y + 0.5) / size);
            const col = Math.floor(source.col) - left;
            const row = Math.floor(source.row) - top;
            if (col < 0 || row < 0 || col >= sourceWidth || row >= sourceHeight) {
                continue;
            }
            const from = (row * sourceWidth + col) * 3;
            const to = (y * size + x) * 4;
            const [red, green, blue] = [pixels[from], pixels[from + 1], pixels[from + 2]];
            if (red || green || blue) {   // all zero is "no data" (outside the scene's swath)
                output.data[to] = red;
                output.data[to + 1] = green;
                output.data[to + 2] = blue;
                output.data[to + 3] = 255;
                covered++;
            }
        }
    }
    context.putImageData(output, 0, 0);
    return { canvas, plan, coverage: covered / (size * size) };
}

let eoTileLayer = null;
let eoTileKey = '';
let eoTileInfo = '';   // the text of the IMAGERY block shown under the parameters table

const eoTileInfoHtml = () => (eoTileInfo
    ? `<div class="eo-desc"><div class="eo-desc-title">IMAGERY</div><p class="eo-desc-text">${eoEscape(eoTileInfo)}</p></div>`
    : '');

function setEoTileInfo(text) {
    eoTileInfo = text;
    const container = document.getElementById('eo-params');
    if (!container) {
        return;
    }
    const block = container.querySelector('.eo-tile-info');
    if (block) {
        block.remove();
    }
    container.insertAdjacentHTML('beforeend', `<div class="eo-tile-info">${eoTileInfoHtml()}</div>`);
}

// Fetches and shows the imagery covering the area (bounds) round the target; the layer sits on top of the
// map's base layers. The caller has already fitted the map to the area.
async function showEoTile(map, latitude, longitude, bounds, areaMetres) {
    const key = `${latitude.toFixed(5)},${longitude.toFixed(5)},${areaMetres},${eoQuery.maxCloud},${eoQuery.lookback}`;
    if (key === eoTileKey && eoTileLayer) {
        return;
    }
    const areaText = `${areaMetres / 1000} km`;
    setEoMapError('');
    setEoTileInfo('Searching Earth Search for the newest clear Sentinel-2 scene over the target...');
    try {
        const scene = await eoFindSentinel2Scene(latitude, longitude);
        if (!scene) {
            setEoMapError('NO CLEAR SCENE');
            setEoTileInfo(`No Sentinel-2 scene with under ${eoQuery.maxCloud}% cloud covers the target in the last ${eoValueText('lookback', eoQuery.lookback)}.`);
            return;
        }
        setEoTileInfo(`Reading a ${areaText} square from scene ${scene.id}...`);
        const started = Date.now();
        const { canvas, plan, coverage } = await eoReadSceneArea(scene, bounds, areaMetres);
        if (eoTileLayer) {
            map.removeLayer(eoTileLayer);
        }
        // Own pane above the map's vector layer (the country shapes, z-index 200 and opaque, would hide the picture)
        // and below the area outline (eoPanel.js, pane 'eoOutline').
        if (!map.getPane('eoImagery')) {
            map.createPane('eoImagery').style.zIndex = 450;
        }
        eoTileLayer = L.imageOverlay(canvas.toDataURL('image/png'), bounds, { interactive: false, attribution: EO_TILE_CREDIT, pane: 'eoImagery' }).addTo(map);
        eoTileKey = key;
        const date = scene.properties.datetime.slice(0, 10);
        const cloud = Math.round(scene.properties['eo:cloud_cover']);
        const share = Math.round(coverage * 100);
        setEoTileInfo(`Sentinel-2 L2A true colour, ${date} UTC, ${cloud}% cloud over the whole scene, scene ${scene.id}. ${areaText} square, ${plan.pixels} x ${plan.pixels} pixels at ${plan.pixelMetres} m; ${share}% of the area has data${share < 98 ? ' (the rest lies outside this scene)' : ''}. Read in ${((Date.now() - started) / 1000).toFixed(1)} s. ${EO_TILE_CREDIT}, via Element 84 Earth Search.`);
    } catch (error) {
        setEoMapError('IMAGE FETCH FAILED');
        setEoTileInfo(`The imagery could not be fetched: ${error.message}`);
    }
}

// Removes the imagery and its IMAGERY text (used when a source that cannot be drawn is chosen).
function clearEoTile(map) {
    if (eoTileLayer) {
        map.removeLayer(eoTileLayer);
    }
    eoTileLayer = null;
    eoTileKey = '';
    setEoTileInfo('');
}
