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

// Zoom level a location map opens at, centred on the user -- a wide
// regional / hemisphere view rather than initBaseMap()'s whole-world
// default, so the surrounding area (and, on GS OPS, the spread of
// visible satellites) is all in frame without panning.
const LOCATION_MAP_DEFAULT_ZOOM = 3;

// CITY LBL toggle: don't draw any city names below this zoom (a zoomed-out
// view would just fill with overlapping labels), and never draw more than
// this many at once even when zoomed in.
const LOCATION_MAP_CITY_LABEL_MIN_ZOOM = 3;
const LOCATION_MAP_CITY_LABEL_MAX = 60;

function registerLocationMapPanel({ sectionId, containerId, buttonLabel, extraButtons = [] }) {
    // One closure set of per-panel state per call -- the maps and their
    // terminator layers/intervals are independent between sections.
    let map = null;
    let userLocationMarker = null;
    let terminatorLayer = null;
    let terminatorUpdateInterval = null;
    let cityLabelLayer = null;
    let cityLabelsVisible = false;

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

    // City-name labels from assets/cities.json -- the curated ~360-entry
    // set the TGT/GS LOCN place autocomplete also uses (loadCityDataset()
    // lives in onOrbitPanel.js, guaranteed loaded before any of this runs
    // via the section's open* function). Only the cities inside the
    // current viewport are drawn, capped at LOCATION_MAP_CITY_LABEL_MAX,
    // and nothing at all below LOCATION_MAP_CITY_LABEL_MIN_ZOOM. Rebuilt
    // on every moveend while the CITY LBL toggle is on (see initMap).
    async function renderCityLabels() {
        if (!map || typeof L === 'undefined') {
            return;
        }
        if (cityLabelLayer) {
            map.removeLayer(cityLabelLayer);
            cityLabelLayer = null;
        }
        if (!cityLabelsVisible || map.getZoom() < LOCATION_MAP_CITY_LABEL_MIN_ZOOM) {
            return;
        }
        const cities = await loadCityDataset();
        // Re-checked after the await: the toggle may have been switched off
        // (or the view moved out of range) while the dataset was loading.
        if (!map || !cityLabelsVisible || map.getZoom() < LOCATION_MAP_CITY_LABEL_MIN_ZOOM) {
            return;
        }
        const bounds = map.getBounds();
        const markers = cities
            .filter((c) => bounds.contains([c.lat, c.lon]))
            .slice(0, LOCATION_MAP_CITY_LABEL_MAX)
            .map((c) => {
                const dot = L.circleMarker([c.lat, c.lon], {
                    radius: 2, color: '#fc9', weight: 1, fillColor: '#fc9', fillOpacity: 0.9, interactive: false,
                });
                dot.bindTooltip(c.name.toUpperCase(), {
                    permanent: true, direction: 'right', offset: [4, 0],
                    className: 'city-label', interactive: false,
                });
                return dot;
            });
        cityLabelLayer = L.layerGroup(markers).addTo(map);
    }

    function toggleCityLabels() {
        cityLabelsVisible = !cityLabelsVisible;
        renderCityLabels();
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

            // Rebuild the city-label layer (only if CITY LBL is on)
            // whenever the view settles -- moveend covers both pan and
            // zoom -- so just the cities currently in frame are drawn.
            map.on('moveend', () => {
                if (cityLabelsVisible) {
                    renderCityLabels();
                }
            });

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
    // on-orbit USR LOCN button it mirrors). Button 2 is the CITY LBL
    // toggle (--bluey, the on-orbit convention for a data/view-state
    // toggle, with a dynamic ON/OFF label like GRD TRCK). Anything the
    // section passes in `extraButtons` fills slot 3 onward; with 2 base +
    // 2 extra (GS OPS: GRND STN, VIS NOW) the grid is a tidy 2x2, each
    // extra button directly below button 1 / button 2. The set is padded
    // to exactly four with inert numbered placeholders (a button with no
    // onClick renders inert -- see renderControlAreaButtons() in lcars.js).
    const buttons = [
        {
            label: buttonLabel,
            color: 'var(--peach)',
            onClick: () => toggleUserLocationForm(renderDefaultArea),
        },
        {
            label: 'CITY LBL',
            color: 'var(--bluey)',
            getText: () => `CITY LBL - ${cityLabelsVisible ? 'ON' : 'OFF'}`,
            onClick: toggleCityLabels,
        },
        ...extraButtons,
    ];
    while (buttons.length < 4) {
        buttons.push({ label: String(buttons.length + 1) });
    }
    buttons.length = 4;

    registerPanelControls(sectionId, {
        defaultAreaMode: 'custom',
        renderDefaultArea,
        buttons,
    });

    // getMap() lets a wrapper panel (e.g. GS OPS's VISIBLE NOW) add its
    // own layers to this map without the map being a named global.
    return { initMap, renderDefaultArea, getMap: () => map };
}
