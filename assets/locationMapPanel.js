/* ==========================================================================
   LOCATION MAP PANEL -- shared factory

   Some sections want the identical payload: the shared Leaflet base map
   (assets/mapCore.js) + lat/lon graticule + day/night terminator, opened
   zoomed in on the user's location, with an otherwise-empty control-panel
   default area and a six-button set whose first button opens the shared
   LAT/LON/PLACE entry form (toggleUserLocationForm(), onOrbitPanel.js).
   Location comes from the persisted observerLocation if set, otherwise an
   IP geolocation via ensureObserverLocation() (onOrbitPanel.js) -- the
   same source and store the on-orbit section uses.

   registerLocationMapPanel() builds one such panel and returns its
   initMap(). EO (assets/eoPanel.js) and GS OPS (assets/gsOpsPanel.js) are
   each a one-call wrapper. mapCore.js and onOrbitPanel.js are loaded by
   the section's open* function in lcars.js before any of this runs; this
   file must load before the wrapper that calls registerLocationMapPanel().
   ========================================================================== */

// Zoom level a location map opens at, centred on the user -- country /
// large-region scale: enough context around the point rather than
// initBaseMap()'s whole-world default, without diving all the way in.
const LOCATION_MAP_DEFAULT_ZOOM = 5;

function registerLocationMapPanel({ sectionId, containerId, buttonLabel }) {
    // One closure set of per-panel state per call -- the maps and their
    // terminator layers/intervals are independent between sections.
    let map = null;
    let userLocationMarker = null;
    let terminatorLayer = null;
    let terminatorUpdateInterval = null;

    // "You are here" dot -- plain white circle marker, same styling as the
    // on-orbit panel's own observer marker. Old one removed before a new
    // one is added (Leaflet has no in-place "move marker").
    function renderUserLocationMarker() {
        if (!map || typeof L === 'undefined') {
            return;
        }
        if (userLocationMarker) {
            map.removeLayer(userLocationMarker);
            userLocationMarker = null;
        }
        if (!observerLocation) {
            return;
        }
        userLocationMarker = L.circleMarker(
            [observerLocation.latitude, observerLocation.longitude],
            { radius: 4, color: '#fff', weight: 1, fillColor: '#fff', fillOpacity: 1 }
        ).addTo(map);
    }

    // Centres on the user's location, IP-geolocating first if it isn't set
    // yet (ensureObserverLocation() never rejects -- resolves to null if
    // that also fails, in which case the map is left on initBaseMap()'s
    // default world view). resetZoom snaps back to
    // LOCATION_MAP_DEFAULT_ZOOM (first init); without it the current zoom
    // is kept and the map just pans (a TGT/GS LOCN commit while the
    // section is already open).
    async function centreOnObserver(resetZoom) {
        const location = await ensureObserverLocation();
        if (!map || !location) {
            return;
        }
        if (resetZoom) {
            map.setView([location.latitude, location.longitude], LOCATION_MAP_DEFAULT_ZOOM, { animate: false });
        } else {
            map.panTo([location.latitude, location.longitude], { animate: false });
        }
        renderUserLocationMarker();
    }

    // Wired to the section's left-menu button via its open* function
    // (lcars.js), alongside showSection(). Runs once (guarded by `map`);
    // showSection() has already made the section visible by the time this
    // runs, which matters because Leaflet can't size itself inside a
    // display:none container. Same shape as initOnOrbitMap() /
    // initInfrastructureMap().
    async function initMap() {
        await loadScriptOnce('assets/mapCore.js');

        if (map) {
            currentMap = map;
            // Leaflet caches its container's size and doesn't recheck it
            // on its own -- the container was display:none while another
            // section was open, so re-entry needs this or it renders stale.
            map.invalidateSize();
            // Keep the marker in step with any location change made
            // elsewhere since the last visit, but leave the user's own
            // pan/zoom alone -- matches initOnOrbitMap()'s "preserve the
            // view on re-entry" behaviour.
            renderUserLocationMarker();
            return;
        }

        try {
            map = await initBaseMap(containerId);
            currentMap = map;
            // So mapCore.js's shared resize handler can invalidate this
            // map too, without knowing it by name.
            registerResizableMap(() => map);

            // Day/night terminator -- vendored plugin (assets/leaflet/
            // L.Terminator.js), loaded after leaflet.js since it extends
            // L.Polygon; initBaseMap() above has already awaited it.
            // Styling and the 360-degree longitudeRange (matched to this
            // app's single non-repeating world copy) are copied from
            // initOnOrbitMap() so every map shades night identically.
            // Added before the graticule so the grid stays legible on top
            // of the shading. Refreshed once a minute -- pure client-side
            // recompute, no network -- the terminator only moves ~0.25 deg
            // of longitude per minute.
            await loadScriptOnce('assets/leaflet/L.Terminator.js');
            terminatorLayer = L.terminator({
                color: '#3a5a7a',
                weight: 1,
                opacity: 0.6,
                fillColor: '#050a12',
                fillOpacity: 0.45,
                longitudeRange: 360,
            }).addTo(map);
            clearInterval(terminatorUpdateInterval);
            terminatorUpdateInterval = setInterval(() => {
                if (terminatorLayer) {
                    terminatorLayer.setTime(new Date());
                }
            }, 60000);

            renderLatLonGraticule(map);
            await centreOnObserver(true);
        } catch (error) {
            console.error(`Error initialising ${sectionId} map:`, error);
        }
    }

    // #default has no resting content for these sections -- the UI is the
    // map in the payload area. Registered as renderDefaultArea (so
    // updateControlArea() clears the wrapper instead of dropping in a
    // plain section-label div) and reused as the shared location form's
    // on-close renderer: closing the form empties #default and, if the map
    // is up, pans it to whatever location was just picked.
    function renderDefaultArea() {
        const wrapper = document.getElementById('default');
        if (wrapper) {
            wrapper.innerHTML = '';
        }
        if (map) {
            centreOnObserver(false);
        }
    }

    // Button 1 opens the shared location form (--peach, matching the
    // on-orbit USR LOCN button it mirrors); slots 2-6 are inert
    // placeholders keeping the six-button two-row grid (a button with no
    // onClick renders inert -- see renderControlAreaButtons() in lcars.js).
    registerPanelControls(sectionId, {
        defaultAreaMode: 'custom',
        renderDefaultArea,
        buttons: [
            {
                label: buttonLabel,
                color: 'var(--peach)',
                onClick: () => toggleUserLocationForm(renderDefaultArea),
            },
            { label: '2' },
            { label: '3' },
            { label: '4' },
            { label: '5' },
            { label: '6' },
        ],
    });

    return { initMap };
}
