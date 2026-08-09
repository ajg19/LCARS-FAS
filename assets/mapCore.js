/* ==========================================================================
   MAP CORE -- shared Leaflet base map + antimeridian clipping

   Split out of lcars.js so it's loaded once, lazily, by whichever of
   on-orbit / infrastructure opens first, and reused (not re-fetched) by
   the other. Both are the only two panels that use a Leaflet map --
   nothing else in the app should come to depend on this file.

   Leaflet, its CSS, and the world boundary file are all self-hosted under
   assets/leaflet/ and loaded lazily -- none of it is fetched until a panel
   that uses it (Infrastructure, On-Orbit) is actually opened, so it never
   counts against the initial-page-load budget. initBaseMap() draws the
   shared boundary layer for any container; initInfrastructureMap() and
   initOnOrbitMap() (in their own panel files) each call it once and then
   add their own section-specific markers on top. Boundary data is
   world.json (plain GeoJSON, github.com/datasets/geo-countries, ~14MB) --
   a real jump against the low-bandwidth target this project otherwise
   holds to, kept for now while sorting out correct antimeridian handling;
   worth revisiting (simplifying vertex count, or a smaller source) once
   that's settled.
   ========================================================================== */

let infrastructureMap = null;
let onOrbitMap = null;

// Whichever of the maps above is on screen right now -- kept in sync by
// initInfrastructureMap()/initOnOrbitMap() so the single shared pair of
// zoom buttons (bar-7/bar-8a) always zooms the map the user is looking at.
let currentMap = null;

// A handful of countries (Russia, Fiji, Antarctica in this dataset) have
// rings that cross the antimeridian -- consecutive stored points that jump
// from ~180 to ~-180 longitude, which Leaflet renders as a straight line
// spanning the entire map rather than recognising them as adjacent.
//
// Fixed by real polygon clipping (Sutherland-Hodgman) against two fixed
// vertical lines, longitude -179 and +179, rather than trying to detect
// and patch individual bad edges (several earlier attempts at that each
// found a new way to still draw a spurious line -- naive closing, closing
// via the pole, etc). Clipping against a fixed line only ever introduces
// new edges that run ALONG that line -- vertical, at a constant longitude
// -- never a horizontal edge spanning the map width, so it can't reproduce
// the bug no matter how a ring is shaped. It's also guaranteed to yield
// exactly one valid closed polygon per input ring (Sutherland-Hodgman's
// defining property when clipping a simple polygon against a convex
// window), so there's no multi-piece bookkeeping and nothing gets dropped.
// The cost is a deliberately small one: any real coastline within a degree
// of the actual dateline gets flattened to a straight vertical edge
// instead of its true shape -- acceptable for a decorative background layer.
const ANTIMERIDIAN_CLIP_MIN = -179;
const ANTIMERIDIAN_CLIP_MAX = 179;

function unwrapRing(ring) {
    const isClosed = ring[0][0] === ring[ring.length - 1][0] && ring[0][1] === ring[ring.length - 1][1];
    const pts = isClosed ? ring.slice(0, -1) : ring.slice();
    const unwrapped = [pts[0]];
    let offset = 0;
    for (let i = 1; i < pts.length; i++) {
        const delta = pts[i][0] - pts[i - 1][0];
        // A ring that closes across a pole (e.g. Antarctica) can contain a
        // literal [180, -90] -> [-180, -90] edge -- every longitude is the
        // same point at the pole, so this isn't a real antimeridian
        // crossing. Treating it as one would shift every following point
        // into a neighbouring band, which then gets clipped away entirely.
        const isPoleEdge = Math.abs(pts[i][1]) === 90 && Math.abs(pts[i - 1][1]) === 90;
        if (!isPoleEdge) {
            if (delta > 180) offset -= 360;
            else if (delta < -180) offset += 360;
        }
        unwrapped.push([pts[i][0] + offset, pts[i][1]]);
    }
    return unwrapped;
}

function clipHalfPlane(points, keep, intersect) {
    const output = [];
    const n = points.length;
    for (let i = 0; i < n; i++) {
        const current = points[i];
        const prev = points[(i - 1 + n) % n];
        const currentIn = keep(current);
        const prevIn = keep(prev);
        if (currentIn) {
            if (!prevIn) output.push(intersect(prev, current));
            output.push(current);
        } else if (prevIn) {
            output.push(intersect(prev, current));
        }
    }
    return output;
}

function lerpAtLongitude(a, b, lon) {
    const t = (lon - a[0]) / (b[0] - a[0]);
    return [lon, a[1] + t * (b[1] - a[1])];
}

function clipRingToAntimeridianSafeBounds(ring) {
    let points = unwrapRing(ring);

    // The ring may sit in any 360-degree band once unwrapped (e.g. one
    // starting near +130 that dips past +180 unwraps to values like
    // 130..190, not -230..-170) -- clip against whichever band its own
    // first point falls in, not always band 0.
    const band = Math.round(points[0][0] / 360);
    const min = band * 360 + ANTIMERIDIAN_CLIP_MIN;
    const max = band * 360 + ANTIMERIDIAN_CLIP_MAX;

    points = clipHalfPlane(points, (p) => p[0] >= min, (a, b) => lerpAtLongitude(a, b, min));
    if (points.length === 0) return null;
    points = clipHalfPlane(points, (p) => p[0] <= max, (a, b) => lerpAtLongitude(a, b, max));
    if (points.length < 3) return null;

    const shift = -band * 360;
    const normalized = points.map(([lon, lat]) => [
        Math.round((lon + shift) * 1e6) / 1e6,
        Math.round(lat * 1e6) / 1e6,
    ]);
    normalized.push(normalized[0]);
    return normalized;
}

// Runs every ring (outer and holes) in a boundaries FeatureCollection
// through clipRingToAntimeridianSafeBounds(), rebuilding each feature's
// geometry as a MultiPolygon uniformly (Leaflet renders a single-polygon
// MultiPolygon identically to a Polygon). A ring that clips away entirely
// (null) is simply omitted -- shouldn't happen for any real country given
// a 1-degree-inset clip window, but guarded rather than assumed.
function fixAntimeridianCrossings(geojson) {
    geojson.features.forEach((feature) => {
        const geom = feature.geometry;
        const polys = geom.type === 'Polygon' ? [geom.coordinates] : geom.coordinates;
        const newPolys = polys
            .map((poly) => poly.map(clipRingToAntimeridianSafeBounds).filter(Boolean))
            .filter((poly) => poly.length > 0);
        geom.type = 'MultiPolygon';
        geom.coordinates = newPolys;
    });
    return geojson;
}

// Shared by every section that shows a Leaflet world map: loads Leaflet
// (self-hosted, lazy) and draws the base boundary layer into `containerId`.
// Callers add whatever markers/layers are specific to them on top of the
// returned map. Split out of what used to be initInfrastructureMap() so
// initOnOrbitMap() (and any future map panel) gets the identical base map
// without duplicating the Leaflet setup or antimeridian handling.
async function initBaseMap(containerId) {
    await Promise.all([
        loadStylesheetOnce('assets/leaflet/leaflet.css'),
        loadScriptOnce('assets/leaflet/leaflet.js'),
    ]);

    const map = L.map(containerId, {
        worldCopyJump: true,
        attributionControl: false,
        zoomControl: false,
        zoomSnap: 0.05,
        zoomDelta: 0.05,
    }).setView([20, 0], 2);

    const response = await fetch('assets/leaflet/world.json');
    if (!response.ok) {
        throw new Error(`HTTP error ${response.status}`);
    }
    // Already plain GeoJSON (not TopoJSON), so no decoding step needed
    // here -- fixAntimeridianCrossings() is still run as a safety net,
    // but is a no-op for any ring that doesn't actually cross the seam.
    const boundaries = fixAntimeridianCrossings(await response.json());

    L.geoJSON(boundaries, {
        style: {
            color: '#89f', // --bluey
            weight: 1,
            fillColor: '#1c3a4d',
            fillOpacity: 1,
        },
        onEachFeature: (feature, layer) => {
            layer.on('mouseover', () => layer.setStyle({ fillColor: '#2a5470' }));
            layer.on('mouseout', () => layer.setStyle({ fillColor: '#1c3a4d' }));
        },
    }).addTo(map);

    return map;
}

// Faint lat/lon reference grid -- plain L.polylines, no plugin needed
// (unlike the terminator, there's no astronomical computation here, just
// fixed-interval lines of constant latitude/longitude, and no
// antimeridian handling either since meridians/parallels are already
// well-behaved lines that don't wrap). 30-degree spacing is a whole
// divisor of 360, so meridians land on nice round longitudes on both
// axes. Static and drawn once -- unlike the terminator, none of this
// moves, so there's no update interval to maintain. Shared by both
// on-orbit and infrastructure, called once each from their own init
// functions right after initBaseMap() returns.
const GRATICULE_SPACING_DEG = 30;

// Parallels stop one spacing-step short of each pole rather than at the
// poles themselves, since a "line of latitude" at exactly +/-90 is a
// single point, not a line -- computed from the spacing (not a fixed
// constant like the old +/-75 was) so both this bound and the equator
// line stay aligned to the same lattice if the spacing is ever changed
// again: it must be a multiple of GRATICULE_SPACING_DEG for the loop
// below to actually land on 0 rather than straddling it.
const GRATICULE_LAT_BOUND = 90 - GRATICULE_SPACING_DEG;

function renderLatLonGraticule(map) {
    const lines = [];
    const style = { color: '#fff', weight: 1, opacity: 0.2, dashArray: '4,6', interactive: false };

    for (let lon = -180; lon <= 180; lon += GRATICULE_SPACING_DEG) {
        lines.push(L.polyline([[-85, lon], [85, lon]], style));
    }
    for (let lat = -GRATICULE_LAT_BOUND; lat <= GRATICULE_LAT_BOUND; lat += GRATICULE_SPACING_DEG) {
        lines.push(L.polyline([[lat, -180], [lat, 180]], style));
    }

    L.layerGroup(lines).addTo(map);
    renderGraticuleLatitudeLabels(map);
    renderGraticuleLongitudeLabels(map);
}

// Longitude just outside the map's single -180..180 world copy (see the
// terminator's longitudeRange fix above, same reasoning) -- close enough
// to read as part of the graticule's own frame, far enough to sit clear
// of the boundary layer and the graticule's own meridian lines rather
// than overlapping them.
const GRATICULE_LAT_LABEL_LON = 185;

// Standard N/S notation, degrees only -- longitude direction letters
// aren't needed here since only latitude gets labelled.
function formatLatitudeLabel(lat) {
    if (lat === 0) return '0°';
    return `${Math.abs(lat)}°${lat > 0 ? 'N' : 'S'}`;
}

// Latitude labels for the graticule's parallels, one pair per parallel at
// lon +/-185. Real map layers at fixed geographic coordinates, not
// screen-space DOM elements (see the removed setupGraticuleEdgeLabels()
// experiment this replaces) -- being real layers, Leaflet positions,
// pans and zooms them automatically along with the grid lines, so there's
// no manual moveend recomputation to maintain.
//
// Each label is an invisible zero-radius circleMarker with a permanent,
// centered tooltip bound to it: direction: 'center' makes Leaflet centre
// the tooltip on its anchor point and skip its usual directional arrow,
// so no hand-rolled CSS transform is needed to position the text (a
// divIcon would have needed one, since Leaflet's own inline positioning
// transform on the icon element can't be overridden from a stylesheet).
// Box chrome/text styling is in classic.css, following the same
// restyle-off-Leaflet's-default-white-box pattern already used for the
// on-orbit live-position labels (.orbit-marker-label).
function renderGraticuleLatitudeLabels(map) {
    const labels = [];
    for (let lat = -GRATICULE_LAT_BOUND; lat <= GRATICULE_LAT_BOUND; lat += GRATICULE_SPACING_DEG) {
        const text = formatLatitudeLabel(lat);
        [-GRATICULE_LAT_LABEL_LON, GRATICULE_LAT_LABEL_LON].forEach((lon) => {
            const anchor = L.circleMarker([lat, lon], {
                radius: 0,
                opacity: 0,
                fillOpacity: 0,
                interactive: false,
            });
            anchor.bindTooltip(text, {
                permanent: true,
                direction: 'center',
                className: 'graticule-label',
                interactive: false,
            });
            labels.push(anchor);
        });
    }
    L.layerGroup(labels).addTo(map);
}

// Latitude just inside the poles, past where the meridian lines
// themselves stop (+/-85, see renderLatLonGraticule() above) -- close
// enough to read as part of the graticule's own frame, far enough to sit
// clear of the meridian lines rather than overlapping them.
const GRATICULE_LON_LABEL_LAT = 87;

// Standard E/W notation, mirroring formatLatitudeLabel() above -- 0° is
// the prime meridian (no letter), and +/-180 is just "180°" since it's
// the antimeridian, not meaningfully E or W.
function formatLongitudeLabel(lon) {
    if (lon === 0) return '0°';
    if (Math.abs(lon) === 180) return '180°';
    return `${Math.abs(lon)}°${lon > 0 ? 'E' : 'W'}`;
}

// Longitude labels for the graticule's meridians, one pair per meridian
// at lat +/-87 -- same construction as renderGraticuleLatitudeLabels()
// above (invisible anchor circleMarker + centered permanent tooltip,
// same 'graticule-label' class/font), see that function's comment for
// why this shape was chosen over a screen-space DOM approach.
function renderGraticuleLongitudeLabels(map) {
    const labels = [];
    for (let lon = -180; lon <= 180; lon += GRATICULE_SPACING_DEG) {
        const text = formatLongitudeLabel(lon);
        [-GRATICULE_LON_LABEL_LAT, GRATICULE_LON_LABEL_LAT].forEach((lat) => {
            const anchor = L.circleMarker([lat, lon], {
                radius: 0,
                opacity: 0,
                fillOpacity: 0,
                interactive: false,
            });
            anchor.bindTooltip(text, {
                permanent: true,
                direction: 'center',
                className: 'graticule-label',
                interactive: false,
            });
            labels.push(anchor);
        });
    }
    L.layerGroup(labels).addTo(map);
}

// Wired to the bar-7/bar-8a zoom buttons, which stand in for Leaflet's
// built-in zoom control (disabled via zoomControl: false above) so the
// controls live in the console chrome instead of floating on the map. Step
// size comes from zoomDelta (set alongside zoomSnap in the map options
// above) rather than being hardcoded here, so there's one place to retune
// it. animate:false sidesteps a CSS-transition zoom animation that doesn't
// complete on this page (a small zoom step otherwise gets stuck
// mid-animation instead of settling on the new level) -- an instant zoom
// step reads fine for a console button anyway. Operates on `currentMap`
// rather than a specific section's map, since one shared pair of buttons
// now serves every Leaflet panel.
function zoomMapIn() {
    if (currentMap) {
        currentMap.zoomIn(undefined, { animate: false });
    }
}

function zoomMapOut() {
    if (currentMap) {
        currentMap.zoomOut(undefined, { animate: false });
    }
}

// Leaflet caches its container's pixel size and has no way to notice on
// its own when that size changes -- confirmed live: shrinking
// .leaflet-map's own width via CSS alone left map.getSize() completely
// stale until invalidateSize() was called explicitly. A window resize
// (or the responsive main{padding} clamp() recalculating at a different
// viewport width) is exactly that case, and previously had nothing
// wired up to handle it at all -- the map would silently drift out of
// sync with its container's real rendered size.
//
// Debounced (150ms) rather than firing on every intermediate resize
// event -- a window drag-resize can fire dozens of these a second, and
// invalidateSize()'s own DOM measurement/redraw work is wasted effort
// on any but the settled final size.
let mapResizeDebounceTimer = null;
window.addEventListener('resize', () => {
    clearTimeout(mapResizeDebounceTimer);
    mapResizeDebounceTimer = setTimeout(() => {
        if (onOrbitMap) {
            onOrbitMap.invalidateSize();
        }
        if (infrastructureMap) {
            infrastructureMap.invalidateSize();
        }
    }, 150);
});
