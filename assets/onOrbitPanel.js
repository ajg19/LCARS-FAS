/* ==========================================================================
   ON-ORBIT PANEL

   Split out of lcars.js. Lazily loaded (alongside assets/mapCore.js) the
   first time ON-ORBIT is opened -- see openOnOrbitSection() in lcars.js
   for the load sequence. Registers this panel's control-area buttons with
   lcars.js's registerPanelControls() at the bottom of this file rather
   than lcars.js's updateControlArea() knowing about on-orbit's specifics
   directly.

   Includes: on-orbit map init (terminator, graticule), observer location
   (Section 5, minus renderUtcClock() which stays in lcars.js -- it runs
   unconditionally from page load, not just while this panel is open),
   the plotted-objects list (Section 6), and add-object search / ground
   track / live position / footprints (Section 6b).
   ========================================================================== */

// renderLatLonGraticule() now lives in assets/mapCore.js -- shared with
// the infrastructure panel, which renders it too (see
// initInfrastructureMap() in groundSegmentPanel.js).

// terminatorLayer/terminatorUpdateInterval -- moved verbatim from
// lcars.js's old Section 4.
let terminatorLayer = null;
let terminatorUpdateInterval = null;

// Wired to the ON-ORBIT left-menu button, alongside showSection() -- same
// once-only/visible-before-init pattern as initInfrastructureMap(). Base
// map only for now; satellite markers land here once the /api/orbital-
// objects endpoint and client-side SGP4 propagation (satellite.js) are
// built (see the ground-track decision from the TLE ingestion session).
async function initOnOrbitMap() {
    // onOrbitMap/currentMap/initBaseMap() are assets/mapCore.js globals --
    // openOnOrbitSection() (lcars.js) guarantees mapCore.js is already
    // loaded before this runs; the extra loadScriptOnce() here is just
    // defence in depth if this is ever called some other way.
    await loadScriptOnce('assets/mapCore.js');

    if (onOrbitMap) {
        currentMap = onOrbitMap;
        // Leaflet caches its container's size and doesn't recheck it on
        // its own. showSection() just set this container back to
        // display:block after it was display:none while a different
        // section was open -- without this, the map can render blank or
        // stale on every re-entry after the first.
        onOrbitMap.invalidateSize();
        return;
    }

    try {
        onOrbitMap = await initBaseMap('on-orbit-map');
        currentMap = onOrbitMap;
        // The ON-ORBIT button fires this and detectObserverLocation()
        // together without awaiting either -- whichever finishes first
        // can't place the marker if the other isn't ready yet
        // (renderUserLocationMarker() no-ops without a map, and without a
        // known location there's nothing to place). Calling it again here
        // covers the case where the location was already known before the
        // map finished loading; detectObserverLocation()'s own call
        // covers the reverse ordering. Both are safe no-ops if their half
        // isn't ready.
        renderUserLocationMarker();

        // Day/night terminator overlay -- vendored plugin (see
        // assets/leaflet/L.Terminator.js), loaded only after leaflet.js
        // itself since it extends L.Polygon. Styled dark/translucent to
        // read as night shading against the map's own colours rather than
        // the plugin's stock near-black default. Refreshed once a minute
        // -- pure client-side recomputation, no network call -- since the
        // terminator only moves ~0.25 degrees of longitude per minute, not
        // worth recomputing on every animation frame.
        await loadScriptOnce('assets/leaflet/L.Terminator.js');
        terminatorLayer = L.terminator({
            color: '#3a5a7a',
            weight: 1,
            opacity: 0.6,
            fillColor: '#050a12',
            fillOpacity: 0.45,
            // Plugin default is 720 (-360..360, two world-widths), sized
            // for maps whose other layers auto-repeat into neighbouring
            // worldCopyJump copies. Ours don't -- the boundaries and
            // graticule are vector layers that only exist in the single
            // -180..180 copy -- so match that instead of overshooting it.
            longitudeRange: 360,
        }).addTo(onOrbitMap);
        clearInterval(terminatorUpdateInterval);
        terminatorUpdateInterval = setInterval(() => {
            if (terminatorLayer) {
                terminatorLayer.setTime(new Date());
            }
        }, 60000);

        renderLatLonGraticule(onOrbitMap);
    } catch (error) {
        console.error('Error initialising on-orbit map:', error);
    }
}

/* ==========================================================================
   SECTION 5: OBSERVER LOCATION (IP geolocation + manual override)

   Deliberately IP-based (geojs.io, no key required, confirmed live) rather
   than the browser Geolocation API. The browser API is more accurate, but
   its native permission prompt firing the instant ON-ORBIT opens reads as
   an intrusive, unexplained interruption for a rough-location feature --
   not worth it here. IP geolocation trades that away for a rougher
   (city-level) reading with no prompt at all.

   It inherits a known mismatch: IP geolocation resolves to wherever a
   user's traffic egresses to the internet, not their physical position --
   for someone on the ISS that's a NASA ground relay in Houston or
   Huntsville, off by however far the station actually is from there at
   that moment. The USR LOCN control-panel button (LAT/LON/PLACE entry,
   further down this section) exists specifically to cover that case (and
   the Moon/deep-space case, where no terrestrial IP geolocation applies
   at all) -- the readout itself lives as a fixed overlay on the map, but
   the override is set from the control panel.
   ========================================================================== */

const OBSERVER_LOCATION_STORAGE_KEY = 'observerLocation';

function loadObserverLocation() {
    try {
        const raw = localStorage.getItem(OBSERVER_LOCATION_STORAGE_KEY);
        return raw ? JSON.parse(raw) : null;
    } catch (error) {
        console.error('Could not read observer location from localStorage:', error);
        return null;
    }
}

function saveObserverLocation(location) {
    try {
        localStorage.setItem(OBSERVER_LOCATION_STORAGE_KEY, JSON.stringify(location));
    } catch (error) {
        console.error('Could not save observer location to localStorage:', error);
    }
}

// Loaded once at script startup, same pattern as assetTypeVisibility --
// a manually-set location (source: 'manual') persists across reloads and
// is never silently overwritten by a later auto-detect (see
// detectObserverLocation() below).
let observerLocation = loadObserverLocation();

// Explicit +/- sign (space either side), integer part zero-padded to at
// least 2 digits, 2 decimal places -- e.g. "+ 51.63", "- 00.09". Always at
// least 4 digits total; longitudes of 100 degrees or more grow past that
// rather than truncating (e.g. "+ 180.00").
function formatSignedCoordinate(value) {
    const sign = value >= 0 ? '+' : '-';
    const [intPart, fracPart] = Math.abs(value).toFixed(2).split('.');
    return `${sign} ${intPart.padStart(2, '0')}.${fracPart}`;
}

// Inverse of formatSignedCoordinate() -- strips the space(s) a formatted
// value like "+ 51.63" contains so parseFloat can read the sign and
// digits as one contiguous number. Also handles plain unformatted input
// (a user typing "51.63" or "-0.09" directly), since parseFloat already
// copes with those unaided.
function parseCoordinateInput(rawValue) {
    return parseFloat(rawValue.replace(/\s+/g, ''));
}

// Writes a formatted value into a LAT/LON input and clears any stale
// .invalid flag. Needed anywhere a value is set from JS rather than
// typed -- assigning .value directly doesn't fire the oninput/onblur
// handlers that normally set/clear that class, so a box left red from an
// earlier bad manual entry would otherwise stay red even after being
// overwritten with a perfectly valid one (a city selection, a pre-fill
// from the saved location, etc).
function setCoordinateInputValue(input, value) {
    input.value = formatSignedCoordinate(value);
    input.classList.remove('invalid');
}

// Wired to the LAT/LON inputs' onblur -- flags an out-of-range or
// unparseable value red as soon as the user leaves the field, rather than
// only surfacing via selectUserLocation()'s status message at submit
// time. An empty field isn't flagged -- that's "not filled in yet", not
// "filled in wrong" -- oninput clears the flag immediately once they start
// correcting it, re-checked on the next blur. A valid value also gets
// reformatted to the canonical "+ xx.xx" display here -- someone typing
// a plain "79.3" should see it become "+ 79.30" once they're done typing,
// not just have it silently accepted in whatever form they left it.
function validateCoordinateField(input, min, max) {
    const trimmed = input.value.trim();
    if (trimmed === '') {
        input.classList.remove('invalid');
        return;
    }
    const value = parseCoordinateInput(trimmed);
    const valid = Number.isFinite(value) && value >= min && value <= max;
    input.classList.toggle('invalid', !valid);
    if (valid) {
        input.value = formatSignedCoordinate(value);
    }
}

// Wired to all three USR LOCN inputs' oninput -- forces whatever's typed
// to uppercase as it's typed, not just displayed that way via CSS.
// Reassigning .value to an equal-length string (toUpperCase() never
// changes character count) is safe to do inside an input handler without
// the cursor jumping to the end, which is what makes this pattern usable
// live rather than only on blur.
function forceUppercaseInput(input) {
    input.value = input.value.toUpperCase();
}

// Renders as a 2-column grid (label, value) rather than plain text so
// LAT/LON line up vertically like a tabulated readout regardless of font
// metrics -- .loc-value additionally uses tabular-nums so the digits
// themselves are consistent-width, keeping the decimal points aligned in
// the common case (both values 2-digit integer parts).
function renderLocationReadout() {
    const readout = document.getElementById('location-readout');
    if (!readout) {
        return;
    }
    if (!observerLocation) {
        readout.textContent = 'LOCATION: UNAVAILABLE';
        return;
    }
    const { latitude, longitude } = observerLocation;
    readout.innerHTML = `
        <span class="loc-label">LAT:</span><span class="loc-value">${formatSignedCoordinate(latitude)}</span>
        <span class="loc-label">LON:</span><span class="loc-value">${formatSignedCoordinate(longitude)}</span>`;
}

// Marker for the observer's own location on the on-orbit map -- a plain
// white dot, not part of the shape/colour key used for ground-segment
// asset types (this isn't a category, just "you are here"). Tracked in a
// module-level variable so the old one can be removed before a new one is
// added -- Leaflet has no "replace this marker" operation, and skipping
// the removal step would leave a stale dot on screen after the user
// changes location rather than moving it.
let userLocationMarker = null;

function renderUserLocationMarker() {
    // typeof-guarded (not just !onOrbitMap) because onOrbitMap is now an
    // assets/mapCore.js global: the ON-ORBIT button fires this function's
    // caller (detectObserverLocation()) in parallel with initOnOrbitMap(),
    // which is what loads mapCore.js in the first place -- a bare
    // reference to an as-yet-undeclared onOrbitMap would throw
    // ReferenceError, not just read as falsy, if detectObserverLocation()'s
    // external geolocation fetch ever resolved before mapCore.js finished
    // loading.
    if (typeof onOrbitMap === 'undefined' || !onOrbitMap || typeof L === 'undefined') {
        return;
    }
    if (userLocationMarker) {
        onOrbitMap.removeLayer(userLocationMarker);
        userLocationMarker = null;
    }
    if (!observerLocation) {
        return;
    }
    userLocationMarker = L.circleMarker(
        [observerLocation.latitude, observerLocation.longitude],
        { radius: 4, color: '#fff', weight: 1, fillColor: '#fff', fillOpacity: 1 }
    ).addTo(onOrbitMap);
}

// Keeps the map overlay readout and the map marker in sync -- every place
// observerLocation changes calls this instead of renderLocationReadout()
// directly, so the two can never drift out of step with each other.
function updateObserverLocationDisplay() {
    renderLocationReadout();
    renderUserLocationMarker();
}

// Resolves to the current observerLocation, running one IP-geolocation
// fetch first if it isn't set yet (and persisting the result, tagged
// source: 'auto', so a later manual override is still never silently
// replaced -- see loadObserverLocation()). Shared by the on-orbit
// panel's detectObserverLocation() and the EO panel's map init: both
// want "the user's location, geolocating if we must", differing only in
// what they do with it afterwards. Never rejects -- a failed fetch
// resolves to whatever observerLocation currently is (null on first
// run), so every caller can treat "no location" the same way.
async function ensureObserverLocation() {
    if (observerLocation) {
        return observerLocation;
    }
    try {
        const response = await fetch('https://get.geojs.io/v1/ip/geo.json');
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }
        const data = await response.json();
        const latitude = parseFloat(data.latitude);
        const longitude = parseFloat(data.longitude);
        if (!Number.isFinite(latitude) || !Number.isFinite(longitude)) {
            throw new Error('response had no usable coordinates');
        }
        observerLocation = { latitude, longitude, source: 'auto' };
        saveObserverLocation(observerLocation);
    } catch (error) {
        console.error('IP geolocation failed:', error.message);
    }
    return observerLocation;
}

// Wired to the ON-ORBIT left-menu button, alongside showSection() and
// initOnOrbitMap(). Guarded (via ensureObserverLocation()) so it only
// ever re-fetches once per session, or not at all if a manual override is
// already set -- same once-only pattern as the map init functions. The
// "DETECTING…" readout text and the updateObserverLocationDisplay() call
// on completion are on-orbit-specific, which is why this stays a thin
// wrapper around the shared helper rather than folding into it.
function detectObserverLocation() {
    if (observerLocation) {
        updateObserverLocationDisplay();
        return;
    }

    const readout = document.getElementById('location-readout');
    if (readout) {
        readout.textContent = 'LOCATION: DETECTING…';
    }

    ensureObserverLocation().then(updateObserverLocationDisplay);
}

// Lazy-loaded once, same pattern as youtubeFeeds.json -- only fetched the
// first time the USR LOCN form is opened, not on page load. A small,
// hand-curated set of major world cities/capitals (plus a few space-
// programme sites -- Houston, Huntsville, Cape Canaveral, Baikonur,
// Kourou) for the PLACE autocomplete and FIND lookup. Not a full
// geocoder -- rough-location matching against a few hundred entries, in
// keeping with this feature's "rough location" scope.
let cityDataset = null;

async function loadCityDataset() {
    if (cityDataset) {
        return cityDataset;
    }
    try {
        const response = await fetch('assets/cities.json');
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }
        cityDataset = await response.json();
    } catch (error) {
        console.error('Could not load city dataset:', error.message);
        cityDataset = [];
    }
    return cityDataset;
}

// Custom PLACE autocomplete dropdown, replacing what used to be a native
// <datalist>. A <datalist> popup is browser chrome, not page content --
// it can't be restyled at all (no font, no colour, no dark background),
// so it looked like stock OS UI dropped into an otherwise fully custom
// LCARS interface. This renders the same kind of live suggestions as a
// plain styled <div>, filtered against cityDataset on every keystroke.
const MAX_PLACE_SUGGESTIONS = 8;

// The currently-rendered suggestion list, so selectPlaceSuggestion() can
// look an entry back up by index without re-filtering or embedding
// lat/lon values inside the onmousedown attribute string.
let currentPlaceSuggestions = [];

// Wired to the PLACE input's oninput/onfocus. Prefix matches sort before
// substring matches; capped at MAX_PLACE_SUGGESTIONS so typing a common
// letter doesn't dump a huge chunk of the dataset into view.
async function renderPlaceSuggestions(typedValue) {
    const box = document.getElementById('usrloc-place-suggestions');
    if (!box) {
        return;
    }
    const typed = typedValue.trim().toLowerCase();
    if (!typed) {
        hidePlaceSuggestions();
        return;
    }

    const cities = await loadCityDataset();
    const startsWithTyped = cities.filter((c) => c.name.toLowerCase().startsWith(typed));
    const containsTyped = cities.filter((c) =>
        !c.name.toLowerCase().startsWith(typed) && c.name.toLowerCase().includes(typed));
    currentPlaceSuggestions = startsWithTyped.concat(containsTyped).slice(0, MAX_PLACE_SUGGESTIONS);

    if (currentPlaceSuggestions.length === 0) {
        hidePlaceSuggestions();
        return;
    }

    box.innerHTML = currentPlaceSuggestions
        .map((c, i) => `<div class="place-suggestion" onmousedown="event.preventDefault(); selectPlaceSuggestion(${i})">${c.name}, ${c.country}</div>`)
        .join('');
    box.classList.remove('is-hidden');

    // .place-suggestions is position: fixed, not absolute -- #default (the
    // PLACE input's ancestor) has a fixed height and overflow: hidden for
    // the news ticker, which clips ANY descendant that extends past its
    // box, in any direction, regardless of position. Fixed positioning
    // escapes that clipping (its containing block is the viewport, not
    // #default), at the cost of needing coordinates computed here rather
    // than plain CSS -- placed just right of the SELECT/FIND button
    // stack, vertically level with the PLACE input.
    const actions = document.querySelector('.user-location-actions');
    const input = document.getElementById('usrloc-place-input');
    if (actions && input) {
        const actionsRect = actions.getBoundingClientRect();
        const inputRect = input.getBoundingClientRect();
        box.style.left = `${actionsRect.right + 12}px`;
        box.style.top = `${inputRect.top}px`;
    }
}

// Wired to each suggestion's onmousedown -- deliberately mousedown, not
// click, with preventDefault() at the call site. Without that, clicking a
// suggestion would blur the PLACE input first (the default mousedown
// behaviour on a text input losing focus), which hides this dropdown
// before the click ever reaches it. Preventing that default keeps focus
// on the input and lets the click land normally.
function selectPlaceSuggestion(index) {
    const match = currentPlaceSuggestions[index];
    if (!match) {
        return;
    }
    document.getElementById('usrloc-place-input').value = `${match.name}, ${match.country}`.toUpperCase();
    setCoordinateInputValue(document.getElementById('usrloc-lat-input'), match.lat);
    setCoordinateInputValue(document.getElementById('usrloc-lon-input'), match.lon);
    hidePlaceSuggestions();
}

function hidePlaceSuggestions() {
    const box = document.getElementById('usrloc-place-suggestions');
    if (box) {
        box.innerHTML = '';
        box.classList.add('is-hidden');
    }
}

// Registered once at script load rather than per form-render -- closes
// the dropdown on a click anywhere outside it. hidePlaceSuggestions() is
// a safe no-op when the USR LOCN form (and this dropdown) isn't even in
// the DOM, so this doesn't need to be torn down when the form closes.
document.addEventListener('click', (event) => {
    if (!event.target.closest('.place-input-wrapper')) {
        hidePlaceSuggestions();
    }
});

let userLocationStatusTimeout = null;

// Replaces alert() for USR LOCN form errors (invalid LAT/LON on SELECT,
// no match on FIND) -- alert() is a blocking native dialog with zero
// styling control, the same problem the old <datalist> had. This is a
// small inline message instead: non-blocking (doesn't halt JS or demand
// a click to dismiss) and styled to match the rest of the console.
// position: fixed for the same reason as .place-suggestions -- #default
// clips any descendant that extends past its fixed-height box, so this
// can't be positioned with plain CSS relative to its actual parent.
function showUserLocationStatus(message) {
    const status = document.getElementById('usrloc-status');
    const fields = document.querySelector('.user-location-fields');
    if (!status || !fields) {
        return;
    }
    status.textContent = message;
    status.classList.remove('is-hidden');

    const fieldsRect = fields.getBoundingClientRect();
    status.style.left = `${fieldsRect.left}px`;
    status.style.top = `${fieldsRect.bottom + 8}px`;

    clearTimeout(userLocationStatusTimeout);
    userLocationStatusTimeout = setTimeout(() => {
        status.classList.add('is-hidden');
    }, 4000);
}

// Markup injected into #default (the cascade wrapper, left of the nav
// buttons) when USR LOCN is clicked -- LAT/LON/PLACE label+input pairs in
// a 2-column grid so they line up vertically, with SELECT/FIND stacked to
// the right of the whole block. LAT/LON are type="text", not "number" --
// the "+ xx.xx" format (leading sign, space, zero-padded) that matches
// the map overlay readout isn't valid input[type=number] syntax (a
// leading "+" and an embedded space are both rejected by the browser's
// own number parser), so free-text with manual parsing/validation in
// selectUserLocation() is the only way to display that same format here.
function renderUserLocationFormMarkup() {
    return `
        <div id="user-location-form" class="user-location-form">
            <div class="user-location-fields">
                <label for="usrloc-lat-input">LAT</label>
                <input type="text" inputmode="decimal" id="usrloc-lat-input" class="location-input" placeholder="+ 00.00" onblur="validateCoordinateField(this, -90, 90)" oninput="forceUppercaseInput(this); this.classList.remove('invalid')" onkeydown="if (event.key === 'Enter') this.blur()">
                <label for="usrloc-lon-input">LON</label>
                <input type="text" inputmode="decimal" id="usrloc-lon-input" class="location-input" placeholder="+ 000.00" onblur="validateCoordinateField(this, -180, 180)" oninput="forceUppercaseInput(this); this.classList.remove('invalid')" onkeydown="if (event.key === 'Enter') this.blur()">
                <label for="usrloc-place-input">PLACE</label>
                <div class="place-input-wrapper">
                    <input type="text" id="usrloc-place-input" class="location-input" autocomplete="off"
                        oninput="forceUppercaseInput(this); renderPlaceSuggestions(this.value)"
                        onfocus="renderPlaceSuggestions(this.value)"
                        onkeydown="if (event.key === 'Escape') hidePlaceSuggestions()"
                        onchange="autofillFromPlaceSelection(this)">
                    <div id="usrloc-place-suggestions" class="place-suggestions is-hidden"></div>
                </div>
            </div>
            <div class="user-location-actions">
                <button class="location-btn" onclick="selectUserLocation()">SELECT</button>
                <button class="location-btn" onclick="findUserLocationPlace()">FIND</button>
            </div>
        </div>
        <div id="usrloc-status" class="usrloc-status is-hidden"></div>`;
}

// Which renderer repopulates #default when the shared location form
// closes. On-orbit wants its plotted-objects list back; the EO panel --
// which opens this very same form via its TGT LOCN button -- wants its own
// plain label instead. Each panel's button passes its choice into
// toggleUserLocationForm() on open; the internal close paths
// (selectUserLocation(), the toggle-shut branch below) reuse whatever was
// last set. Defaults to the on-orbit behaviour so that path is unchanged
// even when a caller passes nothing. Referencing
// fetchAndRenderOrbitalObjectsList (declared in Section 6) up here is safe
// -- function declarations are hoisted.
let locationFormRestingRenderer = fetchAndRenderOrbitalObjectsList;

// Wired to the USR LOCN control-panel button (see the on-orbit
// registerPanelControls() call) and, with a different resting renderer
// passed in, to the EO panel's TGT LOCN button. Toggles #default between
// empty and the entry form -- checking for the form's own presence rather
// than tracking a separate open/closed flag, since #default's content is
// otherwise fully owned by updateControlArea().
function toggleUserLocationForm(restingRenderer) {
    const wrapper = document.getElementById('default');
    if (!wrapper) {
        return;
    }
    if (restingRenderer) {
        locationFormRestingRenderer = restingRenderer;
    }
    if (document.getElementById('user-location-form')) {
        locationFormRestingRenderer();
        return;
    }
    wrapper.innerHTML = renderUserLocationFormMarkup();
    loadCityDataset();
    if (observerLocation) {
        setCoordinateInputValue(document.getElementById('usrloc-lat-input'), observerLocation.latitude);
        setCoordinateInputValue(document.getElementById('usrloc-lon-input'), observerLocation.longitude);
    }
}

// Wired to the PLACE input's onchange -- a fallback for typing a full,
// exact city name and tabbing/clicking away without ever opening the
// suggestion dropdown (selectPlaceSuggestion() already handles the normal
// case of actually picking a suggestion, and doesn't go through this
// path at all -- see the mousedown/preventDefault note there). Exact
// match only ("name" or "name, country") and silent on no match -- this
// fires on every blur, not just a deliberate "look this up" click, so it
// must never alert() over free-typed text that doesn't resolve to
// anything. FIND (below) is the deliberate, broader-matching,
// alert-on-failure action.
async function autofillFromPlaceSelection(input) {
    const typed = input.value.trim().toLowerCase();
    if (!typed) {
        return;
    }
    const cities = await loadCityDataset();
    const match =
        cities.find((c) => c.name.toLowerCase() === typed) ||
        cities.find((c) => `${c.name}, ${c.country}`.toLowerCase() === typed);
    if (!match) {
        return;
    }
    setCoordinateInputValue(document.getElementById('usrloc-lat-input'), match.lat);
    setCoordinateInputValue(document.getElementById('usrloc-lon-input'), match.lon);
}

// Wired to the FIND button -- matches the PLACE input's typed text against
// the city dataset and fills LAT/LON with the result, so the user can
// review (or hand-adjust) before SELECT commits it. Not fuzzy matching:
// exact name, then exact "name, country", then prefix, then substring --
// first hit wins.
async function findUserLocationPlace() {
    const placeInput = document.getElementById('usrloc-place-input');
    if (!placeInput) {
        return;
    }
    const typed = placeInput.value.trim().toLowerCase();
    if (!typed) {
        return;
    }

    const cities = await loadCityDataset();
    const match =
        cities.find((c) => c.name.toLowerCase() === typed) ||
        cities.find((c) => `${c.name}, ${c.country}`.toLowerCase() === typed) ||
        cities.find((c) => c.name.toLowerCase().startsWith(typed)) ||
        cities.find((c) => c.name.toLowerCase().includes(typed));

    if (!match) {
        showUserLocationStatus(`No match found for "${placeInput.value}".`);
        return;
    }

    setCoordinateInputValue(document.getElementById('usrloc-lat-input'), match.lat);
    setCoordinateInputValue(document.getElementById('usrloc-lon-input'), match.lon);
    // Completes the PLACE box to the matched city's full name -- without
    // this, a partial match (e.g. "ber") silently fills LAT/LON but
    // leaves the box showing the partial text, giving no visible
    // confirmation of which city it actually matched. Uppercased to stay
    // consistent with forceUppercaseInput()'s handling of manual typing.
    placeInput.value = `${match.name}, ${match.country}`.toUpperCase();
}

// Wired to the SELECT button -- writes the entered coordinates into the
// map overlay readout and persists them as a manual override (same
// validation/storage/never-auto-overwritten behaviour as before), then
// closes the form.
function selectUserLocation() {
    const latitude = parseCoordinateInput(document.getElementById('usrloc-lat-input').value);
    const longitude = parseCoordinateInput(document.getElementById('usrloc-lon-input').value);
    if (!Number.isFinite(latitude) || latitude < -90 || latitude > 90 ||
        !Number.isFinite(longitude) || longitude < -180 || longitude > 180) {
        showUserLocationStatus('Enter a valid latitude (-90 to 90) and longitude (-180 to 180).');
        return;
    }
    observerLocation = { latitude, longitude, source: 'manual' };
    saveObserverLocation(observerLocation);
    updateObserverLocationDisplay();
    toggleUserLocationForm();
}

/* ==========================================================================
   SECTION 6: PLOTTED ORBITAL OBJECTS LIST

   The on-orbit control panel's default left-hand display (#default),
   shown whenever USR LOCN's entry form isn't open -- same wrapper the
   news ticker occupies on the home section, same "small stylised LCARS
   table" idea, different columns. Client-side storage holds only the
   noradID list (plottedNoradIds); actual object data (name, owner, TLE)
   is always fetched fresh from /api/orbital-objects rather than cached
   here, since TLEs go stale and this project already treats "cache the
   ID, not the data" as the right split for exactly that reason.
   ========================================================================== */

const PLOTTED_NORAD_IDS_STORAGE_KEY = 'plottedNoradIds';

// Seeded on first-ever run only (or if storage is corrupted) so the panel
// isn't blank before any search/add UI exists to populate it deliberately.
// ISS (Zarya, the module conventionally used as "the ISS" NORAD entry --
// the station is actually 6 separately-catalogued modules), the Chinese
// Space Station (Tianhe, its core module), Hubble, and Vanguard 1 (the
// oldest object still in orbit, launched 1958).
const DEFAULT_PLOTTED_NORAD_IDS = [25544, 48274, 20580, 5];

function loadPlottedNoradIds() {
    try {
        const raw = localStorage.getItem(PLOTTED_NORAD_IDS_STORAGE_KEY);
        if (raw) {
            return JSON.parse(raw);
        }
    } catch (error) {
        console.error('Could not read plotted object list from localStorage:', error);
    }
    savePlottedNoradIds(DEFAULT_PLOTTED_NORAD_IDS);
    return DEFAULT_PLOTTED_NORAD_IDS.slice();
}

function savePlottedNoradIds(ids) {
    try {
        localStorage.setItem(PLOTTED_NORAD_IDS_STORAGE_KEY, JSON.stringify(ids));
    } catch (error) {
        console.error('Could not save plotted object list to localStorage:', error);
    }
}

let plottedNoradIds = loadPlottedNoradIds();

// Wired to the ON-ORBIT branch of updateControlArea() and to
// toggleUserLocationForm()'s/toggleAddObjectForm()'s close paths -- all
// three cases want this same table as the "resting state" of #default.
async function fetchAndRenderOrbitalObjectsList() {
    const wrapper = document.getElementById('default');
    if (!wrapper) {
        return;
    }

    // Undo whatever ADD OBJ search state might be active -- this is the
    // control panel's normal resting state, reached both by closing the
    // search form directly and by leaving/re-entering the on-orbit
    // section while it was still open (updateControlArea() calls this
    // unconditionally on every fresh on-orbit entry, so this is the one
    // place that's guaranteed to run either way).
    const resultsPanel = document.getElementById('add-object-results-panel');
    const mapEl = document.getElementById('on-orbit-map');
    const overlayEl = document.querySelector('.location-overlay');
    if (resultsPanel) {
        resultsPanel.classList.add('is-hidden');
    }
    if (mapEl) {
        mapEl.style.display = '';
    }
    if (overlayEl) {
        overlayEl.style.display = '';
    }
    // showSection() (lcars.js) only sets zoom-button visibility once per
    // section-entry, based on sectionId alone -- it has no way to know
    // on-orbit's own payload area toggles between the map and a results
    // table internally, so this (the shared "back to map" path, reached
    // from both ADD OBJ's and DEL OBJ's close paths and section
    // re-entry) is what actually restores them.
    ['map-zoom-in-btn', 'map-zoom-out-btn'].forEach((id) => {
        const btn = document.getElementById(id);
        if (btn) {
            btn.classList.remove('is-hidden');
        }
    });
    addObjectSelectedIds.clear();
    delObjViewActive = false;

    if (plottedNoradIds.length === 0) {
        wrapper.innerHTML = '';
        return;
    }
    try {
        const response = await fetch(`api/orbital-objects?ids=${plottedNoradIds.join(',')}`);
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }
        const objects = await response.json();
        renderOrbitalObjectsList(objects);
    } catch (error) {
        console.error('Could not load plotted orbital objects:', error);
        wrapper.textContent = 'ERR: COULD NOT LOAD OBJECT LIST';
    }
}

// Distinct LCARS palette colours for multi-object ground tracks and the
// table's KEY column -- reused from classic.css's :root custom
// properties rather than inventing new ones, picked for maximum hue
// separation from each other and from colours already used elsewhere on
// this map (bluey/#89f for country borders, white for the observer-
// location dot). Dash patterns are a secondary differentiator, only
// engaged once the object count exceeds the number of distinct colours --
// solid lines first, so colour alone distinguishes objects for as long as
// it can.
const TRACK_COLORS = ['#fa0', '#c44', '#9cf', '#96f', '#c59', '#993', '#f55', '#fc9', '#dbf', '#56f'];
const TRACK_DASH_PATTERNS = [null, '8,6', '2,6'];

function getTrackStyle(index) {
    const color = TRACK_COLORS[index % TRACK_COLORS.length];
    const dashIndex = Math.floor(index / TRACK_COLORS.length) % TRACK_DASH_PATTERNS.length;
    return { color, dashArray: TRACK_DASH_PATTERNS[dashIndex] };
}

// plottedNoradIds is the authoritative order; /api/orbital-objects' IN
// (...) query doesn't guarantee rows come back in that order (SQLite
// tends to return primary-key order instead). Every renderer that needs
// a stable, watchlist-matching order -- the table, the ground tracks --
// goes through this rather than trusting response order, which also
// keeps each object's assigned colour/dash style consistent between the
// table's KEY column and its actual track on the map.
function orderObjectsByPlottedList(objects) {
    const byId = new Map(objects.map((obj) => [obj.noradID, obj]));
    return plottedNoradIds.map((id) => byId.get(id)).filter(Boolean);
}

// Static LCARS table -- deliberately not the news ticker's animated
// per-row colour cycling (dc-row-1..7 in classic.css); a denser
// multi-column technical readout reads more easily with colour used to
// distinguish label vs. data (same gold/bluey split as the map overlay's
// LAT/LON/UTC) than with rows cycling through the whole palette.
function renderOrbitalObjectsList(objects) {
    const wrapper = document.getElementById('default');
    if (!wrapper) {
        return;
    }
    wrapper.innerHTML = '';

    const table = document.createElement('table');
    // No forced width -- the table sizes to its own content (every column,
    // NAME included, only as wide as its longest value) rather than
    // stretching to fill the wrapper.
    //
    // #default is a flex container (justify-content: flex-end by default,
    // align-items: stretch), which was both pushing this table to the
    // right edge and stretching it to fill the full 204px wrapper height
    // regardless of actual row count -- the latter is what showed up as a
    // blank gap under the headers, since the header row (the only one
    // without an explicit height) absorbed the extra stretched space.
    // marginRight: auto overrides the container's own justify-content for
    // just this item (the standard flexbox left-align trick); alignSelf:
    // flex-start keeps it at natural content height instead of stretched.
    table.style.marginRight = 'auto';
    table.style.alignSelf = 'flex-start';
    table.style.borderCollapse = 'collapse';
    table.style.fontFamily = 'Arial, Helvetica, sans-serif';
    table.style.fontSize = '15px';
    table.style.textTransform = 'uppercase';

    const COLUMNS = ['NORAD ID', 'NAME', 'COUNTRY', 'INCL', 'PERIGEE', 'APOGEE', 'PERIOD', 'MMOTION', 'KEY'];

    const headerRow = document.createElement('tr');
    headerRow.style.height = '22px';
    COLUMNS.forEach((label, i) => {
        const th = document.createElement('td');
        th.textContent = label;
        th.style.color = 'var(--gold)';
        th.style.padding = '2px 10px 4px 4px';
        th.style.whiteSpace = 'nowrap';
        // Right-justified for every column except NORAD ID and NAME
        // (indices 0/1).
        if (i >= 2) {
            th.style.textAlign = 'right';
        }
        headerRow.appendChild(th);
    });
    table.appendChild(headerRow);

    // header(22px) + maxRows*rowHeight stays under the 204px wrapper (#default
    // clips anything taller via overflow: hidden), same budgeting approach
    // as the news ticker's own row cap.
    const rowHeight = 26;
    const maxRows = 6;
    const orderedObjects = orderObjectsByPlottedList(objects);
    orderedObjects.slice(0, maxRows).forEach((obj, index) => {
        const tr = document.createElement('tr');
        tr.style.height = `${rowHeight}px`;

        const inclination = obj.inclination;
        const meanMotion = obj.meanMotion;
        const cells = [
            obj.noradID,
            obj.name || '--',
            obj.owner || '--',
            Number.isFinite(inclination) ? `${inclination.toFixed(1)}°` : '--',
            // perigee/apogee are already km altitude from the source
            // (confirmed live against both CelesTrak's satcat.csv and
            // Space-Track's gp class), so no unit conversion needed here.
            Number.isFinite(obj.perigee) ? `${Math.round(obj.perigee)} KM` : '--',
            Number.isFinite(obj.apogee) ? `${Math.round(obj.apogee)} KM` : '--',
            // Likewise already decimal minutes as stored.
            Number.isFinite(obj.period) ? `${obj.period.toFixed(1)} MIN` : '--',
            Number.isFinite(meanMotion) ? meanMotion.toFixed(1) : '--',
        ];
        cells.forEach((value, i) => {
            const td = document.createElement('td');
            td.textContent = value;
            td.style.color = 'var(--data-value-color)';
            td.style.padding = '2px 10px 2px 4px';
            td.style.whiteSpace = 'nowrap';
            if (i >= 2) {
                td.style.textAlign = 'right';
            }
            tr.appendChild(td);
        });

        // KEY column -- a short coloured (and, once styles start
        // repeating, dashed) line sample matching this row's ground
        // track. Uses the exact same getTrackStyle(index) lookup
        // toggleGroundTrack() uses for the actual map layer, so the
        // swatch and the track it represents can never fall out of sync.
        const keyTd = document.createElement('td');
        keyTd.style.padding = '2px 10px 2px 4px';
        keyTd.style.textAlign = 'right';
        const style = getTrackStyle(index);
        const dashAttr = style.dashArray ? ` stroke-dasharray="${style.dashArray}"` : '';
        keyTd.innerHTML = `<svg width="28" height="10" style="display:inline-block;vertical-align:middle;"><line x1="0" y1="5" x2="28" y2="5" stroke="${style.color}" stroke-width="3"${dashAttr}/></svg>`;
        tr.appendChild(keyTd);

        table.appendChild(tr);
    });

    wrapper.appendChild(table);
}

/* ==========================================================================
   SECTION 6b: ADD OBJECT SEARCH (ADD OBJ button)

   Opens a filter form in the control panel (#default, same slot USR LOCN
   uses) and, while open, replaces the on-orbit map with a results table
   (#add-object-results-panel) showing whatever currently matches the
   filters -- see toggleAddObjectForm() below for the open/close mechanics,
   which follow the exact same "check for the form's own presence" pattern
   toggleUserLocationForm() uses.

   Every filter maps to a query param on GET /api/orbital-objects/search
   (server.js). COUNTRY, CELESTRAK GROUP, and SPACE PORT are populated
   from /api/orbital-objects/filter-options (live DB values -- dozens of
   owner/launch-site codes and 47 possible groups -- not practical to
   hardcode); OBJECT TYPE/ALTITUDE/INCLINATION are fixed option sets since
   these are curated categories, not raw DB values (objectType's real
   stored codes are PAY/DEB/R-B; altitude regime and inclination band
   aren't stored at all, just derived server-side). LAUNCH FROM/LAUNCH TO
   are free-text year bounds (launchYearFrom/launchYearTo), not a
   dropdown -- a range filter over launchDate's year prefix.

   Clicking a result row highlights it (addObjectSelectedIds) rather than
   showing a KEY-column colour swatch -- these aren't plotted/tracked
   objects yet, so there's no track colour to show one of.
   ========================================================================== */

const OBJECT_TYPE_FILTER_OPTIONS = [
    { label: 'PAYLOAD', value: 'PAY' },
    { label: 'ROCKET BODY', value: 'R/B' },
    { label: 'DEBRIS', value: 'DEB' },
];

const ALTITUDE_REGIME_FILTER_OPTIONS = [
    { label: 'LEO', value: 'LEO' },
    { label: 'MEO', value: 'MEO' },
    { label: 'GEO', value: 'GEO' },
    { label: 'OTHER', value: 'OTHER' },
];

const INCLINATION_BAND_FILTER_OPTIONS = [
    { label: 'EQUATORIAL', value: 'EQUATORIAL' },
    { label: 'MID-INCLINATION', value: 'MID' },
    { label: 'POLAR / SSO', value: 'POLAR_SSO' },
];

let addObjectFilterOptionsCache = null; // { owners, groups, launchSites } -- fetched once per page load, not once per form open
let addObjectSelectedIds = new Set(); // noradIDs highlighted in the current results table

// Wired to the DEL OBJ button -- true while its read-only plotted-objects
// view (shares #add-object-results-panel with ADD OBJ) is showing. No DOM
// element to check for presence the way ADD OBJ checks for #add-object-form,
// since DEL OBJ's view has no form -- this flag is that signal instead.
// Reset to false wherever the shared results panel gets handed back to
// ADD OBJ or the resting state (fetchAndRenderOrbitalObjectsList(),
// toggleAddObjectForm()'s open path), so the two views can never think
// they're both/neither active at once.
let delObjViewActive = false;

async function fetchAddObjectFilterOptions() {
    if (addObjectFilterOptionsCache) {
        return addObjectFilterOptionsCache;
    }
    const response = await fetch('api/orbital-objects/filter-options');
    addObjectFilterOptionsCache = await response.json();
    return addObjectFilterOptionsCache;
}

function stringOptionTags(values) {
    return values.map((v) => `<option value="${v}">${v.toUpperCase()}</option>`).join('');
}

// SATCAT owner/source codes -> display names, per CelesTrak's own
// reference (https://celestrak.org/satcat/sources.php, checked live). Not
// all of these are sovereign countries (ESA, NATO, ISS, CIS, ITSO, etc.
// are organisations/consortiums) -- the COUNTRY dropdown shows whatever
// the DB's owner column actually contains, so those stay in, just as
// names instead of codes like everything else here.
//
// JOR, KWT, SVK aren't on that reference page (Space-Track's own SATCAT
// evidently uses a couple of codes CelesTrak's page doesn't list) --
// mapped here by the same alpha-code convention as their already-confirmed
// neighbours (Jordan, Kuwait, Slovakia). COUNTRY_CODE_NAMES only needs to
// cover codes actually seen in orbital_objects.owner; any future code not
// in this table just falls back to displaying its raw form (see
// countryOptionTags() below), never a blank or broken option.
const COUNTRY_CODE_NAMES = {
    AB: 'Arab Satellite Communications Organization',
    ABS: 'Asia Broadcast Satellite',
    AC: 'AsiaSat',
    ALG: 'Algeria',
    ANG: 'Angola',
    ARGN: 'Argentina',
    ASRA: 'Austria',
    AUS: 'Australia',
    AZER: 'Azerbaijan',
    BEL: 'Belgium',
    BELA: 'Belarus',
    BGD: 'Bangladesh',
    BHR: 'Bahrain',
    BOL: 'Bolivia',
    BRAZ: 'Brazil',
    BUL: 'Bulgaria',
    BWA: 'Botswana',
    CA: 'Canada',
    CHBZ: 'China / Brazil',
    CHLE: 'Chile',
    CIS: 'Commonwealth of Independent States',
    COL: 'Colombia',
    CZCH: 'Czech Republic',
    DEN: 'Denmark',
    DJI: 'Djibouti',
    ECU: 'Ecuador',
    EGYP: 'Egypt',
    ESA: 'European Space Agency',
    EST: 'Estonia',
    ETH: 'Ethiopia',
    EUME: 'EUMETSAT',
    EUTE: 'EUTELSAT',
    FGER: 'France / Germany',
    FIN: 'Finland',
    FR: 'France',
    FRIT: 'France / Italy',
    GER: 'Germany',
    GLOB: 'Globalstar',
    GREC: 'Greece',
    GRSA: 'Greece / Saudi Arabia',
    HRV: 'Croatia',
    HUN: 'Hungary',
    IM: 'INMARSAT',
    IND: 'India',
    INDO: 'Indonesia',
    IRAN: 'Iran',
    IRAQ: 'Iraq',
    ISRA: 'Israel',
    ISS: 'International Space Station',
    IT: 'Italy',
    ITSO: 'ITSO (INTELSAT)',
    JOR: 'Jordan',
    JPN: 'Japan',
    KAZ: 'Kazakhstan',
    KWT: 'Kuwait',
    LAOS: 'Laos',
    LTU: 'Lithuania',
    LUXE: 'Luxembourg',
    MA: 'Morocco',
    MALA: 'Malaysia',
    MEX: 'Mexico',
    MNE: 'Montenegro',
    NATO: 'NATO',
    NETH: 'Netherlands',
    NICO: 'New ICO',
    NIG: 'Nigeria',
    NKOR: 'North Korea',
    NOR: 'Norway',
    NZ: 'New Zealand',
    O3B: 'O3b Networks',
    ORB: 'ORBCOMM',
    PAKI: 'Pakistan',
    PERU: 'Peru',
    POL: 'Poland',
    POR: 'Portugal',
    PRC: 'China',
    RASC: 'RascomStar-QAF',
    ROC: 'Taiwan',
    ROM: 'Romania',
    RP: 'Philippines',
    RWA: 'Rwanda',
    SAFR: 'South Africa',
    SAUD: 'Saudi Arabia',
    SEAL: 'Sea Launch',
    SES: 'SES',
    SING: 'Singapore',
    SKOR: 'South Korea',
    SLB: 'Solomon Islands',
    SPN: 'Spain',
    STCT: 'Singapore / Taiwan',
    SVK: 'Slovakia',
    SVN: 'Slovenia',
    SWED: 'Sweden',
    SWTZ: 'Switzerland',
    TBD: 'To Be Determined',
    THAI: 'Thailand',
    TMMC: 'Turkmenistan / Monaco',
    TURK: 'Türkiye',
    UAE: 'United Arab Emirates',
    UK: 'United Kingdom',
    UKR: 'Ukraine',
    URY: 'Uruguay',
    US: 'United States',
    USBZ: 'United States / Brazil',
    VENZ: 'Venezuela',
    VTNM: 'Vietnam',
};

// COUNTRY dropdown only, distinct from stringOptionTags() -- shows a
// looked-up display name (falling back to the raw code for anything not
// in COUNTRY_CODE_NAMES) while keeping the option's value as the raw code,
// since that's what the server's owner = ? filter matches against. Sorted
// by display name so the list reads alphabetically by name, not by the
// underlying code.
function countryOptionTags(codes) {
    return codes
        .map((code) => ({ code, name: COUNTRY_CODE_NAMES[code] || code }))
        .sort((a, b) => a.name.localeCompare(b.name))
        .map(({ code, name }) => `<option value="${code}">${name.toUpperCase()}</option>`)
        .join('');
}

function labelledOptionTags(items) {
    return items.map((item) => `<option value="${item.value}">${item.label}</option>`).join('');
}

// Action-button colours follow this project's LCARS convention (see the
// on-orbit nav buttons' own registerPanelControls() call below): warm =
// action/commit, blue = data/view-state. ADD SELECTION reuses ADD OBJ's
// own --golden-orange, tying the form's commit action back to the nav
// button that opened it. SEARCH gets its own, different blue (--ice)
// since it's a distinct function (a data query, not a selection toggle).
// SELECT ALL/CLEAR were dropped from this form -- the wider 3-column
// field grid left no room for a 4-button row; rows stay selectable one
// at a time by clicking them (toggleAddObjectRowSelection()).
// clearAddObjectSelection() itself is still here, just no longer wired
// to a button here -- DEL OBJ's own CLEAR button (registerPanelControls()
// below) still calls it.
function renderAddObjectFormMarkup(options) {
    return `
        <div id="add-object-form" class="add-object-form">
            <div class="add-object-fields">
                <div class="add-object-fields-col">
                    <label for="addobj-name-input">NAME</label>
                    <input type="text" id="addobj-name-input" class="location-input" placeholder="e.g. STARLINK" oninput="forceUppercaseInput(this)" onkeydown="if (event.key === 'Enter') runAddObjectSearch()">
                    <label for="addobj-noradid-input">NORAD ID</label>
                    <input type="text" inputmode="numeric" id="addobj-noradid-input" class="location-input" placeholder="e.g. 25544" onkeydown="if (event.key === 'Enter') runAddObjectSearch()">
                    <label for="addobj-objecttype-select">OBJ TYPE</label>
                    <select id="addobj-objecttype-select" class="location-input" onchange="runAddObjectSearch()">
                        <option value="">ANY</option>
                        ${labelledOptionTags(OBJECT_TYPE_FILTER_OPTIONS)}
                    </select>
                    <label for="addobj-group-select">CTRAK GRP</label>
                    <select id="addobj-group-select" class="location-input" onchange="runAddObjectSearch()">
                        <option value="">ANY</option>
                        ${stringOptionTags(options.groups)}
                    </select>
                </div>
                <div class="add-object-fields-col">
                    <label for="addobj-country-select">COUNTRY</label>
                    <select id="addobj-country-select" class="location-input" onchange="runAddObjectSearch()">
                        <option value="">ANY</option>
                        ${countryOptionTags(options.owners)}
                    </select>
                    <label for="addobj-spaceport-select">SPACE PORT</label>
                    <select id="addobj-spaceport-select" class="location-input" onchange="runAddObjectSearch()">
                        <option value="">ANY</option>
                        ${stringOptionTags(options.launchSites)}
                    </select>
                    <label for="addobj-launchfrom-input">LAUNCH FROM</label>
                    <input type="text" inputmode="numeric" id="addobj-launchfrom-input" class="location-input" placeholder="e.g. 2020" onkeydown="if (event.key === 'Enter') runAddObjectSearch()">
                    <label for="addobj-launchto-input">LAUNCH TO</label>
                    <input type="text" inputmode="numeric" id="addobj-launchto-input" class="location-input" placeholder="e.g. 2026" onkeydown="if (event.key === 'Enter') runAddObjectSearch()">
                </div>
                <div class="add-object-fields-col">
                    <label for="addobj-altitude-select">ALTITUDE</label>
                    <select id="addobj-altitude-select" class="location-input" onchange="runAddObjectSearch()">
                        <option value="">ANY</option>
                        ${labelledOptionTags(ALTITUDE_REGIME_FILTER_OPTIONS)}
                    </select>
                    <label for="addobj-inclination-select">INCL</label>
                    <select id="addobj-inclination-select" class="location-input" onchange="runAddObjectSearch()">
                        <option value="">ANY</option>
                        ${labelledOptionTags(INCLINATION_BAND_FILTER_OPTIONS)}
                    </select>
                    <label for="addobj-mmotionfrom-input">MMOTION FROM</label>
                    <input type="text" inputmode="decimal" id="addobj-mmotionfrom-input" class="location-input" placeholder="e.g. 14.0" onkeydown="if (event.key === 'Enter') runAddObjectSearch()">
                    <label for="addobj-mmotionto-input">MMOTION TO</label>
                    <input type="text" inputmode="decimal" id="addobj-mmotionto-input" class="location-input" placeholder="e.g. 16.0" onkeydown="if (event.key === 'Enter') runAddObjectSearch()">
                </div>
            </div>
            <div class="add-object-actions">
                <button class="location-btn" style="background-color: var(--ice);" onclick="runAddObjectSearch()">SEARCH</button>
                <button class="location-btn" style="background-color: var(--golden-orange);" onclick="addSelectedResultsToPlottedList()">ADD SELECTION</button>
            </div>
        </div>`;
}

// Wired to the ADD OBJ control-panel button. Toggles #default between the
// plotted-objects list and the filter form, exactly like
// toggleUserLocationForm() does for USR LOCN -- checking for the form's
// own presence rather than a separate open/closed flag. Also swaps the
// main payload area between the map and the results table, since ADD OBJ
// replaces the map while open (closing goes back through
// fetchAndRenderOrbitalObjectsList(), which is what actually restores it).
// Runs an unfiltered search as soon as the filter form itself has
// rendered, so the results table isn't left blank until the user sets a
// filter or presses SEARCH themselves -- matches the status text set
// above ("...OR SEARCH WITH NONE SET FOR ALL OBJECTS"), which already
// promised an empty-filter search returns every object.
async function toggleAddObjectForm() {
    const wrapper = document.getElementById('default');
    const resultsPanel = document.getElementById('add-object-results-panel');
    if (!wrapper || !resultsPanel) {
        return;
    }

    if (document.getElementById('add-object-form')) {
        fetchAndRenderOrbitalObjectsList();
        return;
    }

    const mapEl = document.getElementById('on-orbit-map');
    const overlayEl = document.querySelector('.location-overlay');
    if (mapEl) {
        mapEl.style.display = 'none';
    }
    if (overlayEl) {
        overlayEl.style.display = 'none';
    }
    // See the matching restore in fetchAndRenderOrbitalObjectsList() --
    // showSection() only sets zoom-button visibility once per section
    // entry, not per payload-area change within on-orbit.
    ['map-zoom-in-btn', 'map-zoom-out-btn'].forEach((id) => {
        const btn = document.getElementById(id);
        if (btn) {
            btn.classList.add('is-hidden');
        }
    });
    resultsPanel.classList.remove('is-hidden');
    document.getElementById('add-object-status').textContent = 'SET FILTERS AND SEARCH, OR SEARCH WITH NONE SET FOR ALL OBJECTS.';
    document.getElementById('add-object-results-table').innerHTML = '';
    addObjectSelectedIds.clear();
    // In case DEL OBJ's view (which shares this same results panel) was
    // open -- switching straight to ADD OBJ needs to clear its flag too,
    // not just DEL OBJ's own toggle-off path.
    delObjViewActive = false;

    const options = await fetchAddObjectFilterOptions();
    wrapper.innerHTML = renderAddObjectFormMarkup(options);
    runAddObjectSearch();
}

// Wired to the DEL OBJ button. Toggle, same shape as toggleAddObjectForm()
// -- shows every currently-plotted object (plottedNoradIds) in the main
// payload area, reusing ADD OBJ's own sortable results-table rendering
// (renderAddObjectResultsTable()/...FromState()) rather than a separate
// display format. While open, two extra buttons (DEL SELECTION, CLEAR --
// see the on-orbit registerPanelControls() call below) appear in the
// control panel; renderControlAreaButtons() is called on both the open
// and close paths here specifically to rebuild that button *set*, not
// just refresh existing buttons' labels -- the generic per-click
// refreshAllLabels() in lcars.js can't add/remove buttons, only relabel
// ones already on screen.
async function toggleDelObjView() {
    const resultsPanel = document.getElementById('add-object-results-panel');
    if (!resultsPanel) {
        return;
    }

    if (delObjViewActive) {
        delObjViewActive = false;
        fetchAndRenderOrbitalObjectsList();
        renderControlAreaButtons('on-orbit');
        return;
    }

    const mapEl = document.getElementById('on-orbit-map');
    const overlayEl = document.querySelector('.location-overlay');
    if (mapEl) {
        mapEl.style.display = 'none';
    }
    if (overlayEl) {
        overlayEl.style.display = 'none';
    }
    // See the matching restore in fetchAndRenderOrbitalObjectsList() --
    // showSection() only sets zoom-button visibility once per section
    // entry, not per payload-area change within on-orbit.
    ['map-zoom-in-btn', 'map-zoom-out-btn'].forEach((id) => {
        const btn = document.getElementById(id);
        if (btn) {
            btn.classList.add('is-hidden');
        }
    });
    resultsPanel.classList.remove('is-hidden');
    document.getElementById('add-object-results-table').innerHTML = '';
    addObjectSelectedIds.clear();
    delObjViewActive = true;
    renderControlAreaButtons('on-orbit');

    await renderDelObjResults();
}

// Fetches and displays the current plottedNoradIds in DEL OBJ's results
// table -- split out of toggleDelObjView() so DEL SELECTION can also call
// this to refresh the table after removing objects, without re-running
// (and thereby re-toggling off) the rest of the view-opening logic.
//
// Also refreshes #default's own plotted-objects list (renderOrbitalObjectsList())
// on every call, not just the results table -- that list lives in the top
// banner area, a completely different part of the page from the main
// payload's results table, so it stays visible and needs to stay in sync
// too, especially after a delete removes rows from it.
//
// showStatusMessages suppresses the routine LOADING/NO OBJECTS PLOTTED
// text -- deleteSelectedPlottedObjects() passes false, since a delete
// should read as quiet/immediate, not flash a loading message for what's
// already a near-instant local operation. Errors always show regardless
// of this flag; that's real diagnostic information, not routine status.
async function renderDelObjResults(showStatusMessages = true) {
    const status = document.getElementById('add-object-status');

    if (plottedNoradIds.length === 0) {
        if (status) {
            status.textContent = showStatusMessages ? 'NO OBJECTS PLOTTED.' : '';
        }
        renderAddObjectResultsTable([], false);
        const wrapper = document.getElementById('default');
        if (wrapper) {
            wrapper.innerHTML = '';
        }
        return;
    }

    if (status && showStatusMessages) {
        status.textContent = 'LOADING PLOTTED OBJECTS...';
    }
    try {
        const response = await fetch(`api/orbital-objects?ids=${plottedNoradIds.join(',')}`);
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }
        const objects = await response.json();
        renderAddObjectResultsTable(objects, false);
        renderOrbitalObjectsList(objects);
        if (status && !showStatusMessages) {
            status.textContent = '';
        }
    } catch (error) {
        console.error('Could not load plotted objects for DEL OBJ view:', error);
        if (status) {
            status.textContent = 'ERR: COULD NOT LOAD PLOTTED OBJECTS.';
        }
    }
}

// Wired to the DEL SELECTION button (only shown while DEL OBJ's view is
// open -- see registerPanelControls() below). Removes every currently-
// highlighted object from plottedNoradIds, persists it, and redraws the
// table with whatever's left. Also refreshes an already-visible ground
// track, mirroring addSelectedResultsToPlottedList()'s own pattern --
// a deleted object's track/live marker needs to disappear immediately
// too, not just its row here.
async function deleteSelectedPlottedObjects() {
    if (addObjectSelectedIds.size === 0) {
        return;
    }

    plottedNoradIds = plottedNoradIds.filter((id) => !addObjectSelectedIds.has(id));
    savePlottedNoradIds(plottedNoradIds);
    addObjectSelectedIds.clear();

    if (groundTrackVisible) {
        await renderGroundTracksForPlottedList();
    }

    await renderDelObjResults(false);
}

// Wired to the ADD SELECTION button. Adds every currently-highlighted
// search result (addObjectSelectedIds -- see toggleAddObjectRowSelection())
// to plottedNoradIds, the persistent (localStorage-backed, see Section 6
// above) list that drives the plotted-objects list, ground track and
// footprint rendering elsewhere in this file. Already-plotted objects are
// left alone rather than duplicated, so re-clicking after some selected
// rows are already in the list is a harmless no-op for those rows.
async function addSelectedResultsToPlottedList() {
    if (addObjectSelectedIds.size === 0) {
        return;
    }

    let addedCount = 0;
    addObjectSelectedIds.forEach((noradId) => {
        if (!plottedNoradIds.includes(noradId)) {
            plottedNoradIds.push(noradId);
            addedCount += 1;
        }
    });
    savePlottedNoradIds(plottedNoradIds);

    // Ground tracks are only computed when GRD TRCK is toggled on
    // (toggleGroundTrack(), Section 6b below) -- plottedNoradIds changing
    // underneath an already-visible track doesn't redraw it on its own,
    // so without this, a newly-added object would silently not appear on
    // the map until the user manually toggled GRD TRCK off and back on.
    if (addedCount > 0 && groundTrackVisible) {
        await renderGroundTracksForPlottedList();
    }

    addObjectSelectedIds.clear();
    renderAddObjectResultsTableFromState();
}

// Wired to DEL OBJ's own CLEAR button (registerPanelControls() below) --
// drops all current row highlighting without touching the search results
// themselves or plottedNoradIds. No longer has a button of its own in the
// ADD OBJ form (see renderAddObjectFormMarkup()'s own comment for why).
function clearAddObjectSelection() {
    addObjectSelectedIds.clear();
    renderAddObjectResultsTableFromState();
}

async function runAddObjectSearch() {
    const fieldsByParam = {
        name: 'addobj-name-input',
        noradId: 'addobj-noradid-input',
        owner: 'addobj-country-select',
        altitudeRegime: 'addobj-altitude-select',
        objectType: 'addobj-objecttype-select',
        inclinationBand: 'addobj-inclination-select',
        meanMotionFrom: 'addobj-mmotionfrom-input',
        meanMotionTo: 'addobj-mmotionto-input',
        launchSite: 'addobj-spaceport-select',
        launchYearFrom: 'addobj-launchfrom-input',
        launchYearTo: 'addobj-launchto-input',
        group: 'addobj-group-select',
    };
    const params = new URLSearchParams();
    Object.entries(fieldsByParam).forEach(([param, id]) => {
        const value = document.getElementById(id)?.value.trim();
        if (value) {
            params.set(param, value);
        }
    });

    const status = document.getElementById('add-object-status');
    if (status) {
        status.textContent = 'SEARCHING...';
    }

    try {
        const response = await fetch(`api/orbital-objects/search?${params.toString()}`);
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }
        const { objects, truncated } = await response.json();
        renderAddObjectResultsTable(objects, truncated);
    } catch (error) {
        console.error('Could not run object search:', error);
        if (status) {
            status.textContent = 'ERR: SEARCH FAILED.';
        }
    }
}

// One descriptor per results-table column, shared between header
// rendering, cell rendering, and sorting -- getValue() returns the raw
// sortable value (a number for numeric columns, so numeric sort doesn't
// need to parse formatted text back out), format() turns that into the
// displayed string. INCL/MMOTION are real OMM-element columns from the API
// (inclination/meanMotion) since the TLE->OMM migration -- no more parsing
// them out of a raw TLE line2 on every render.
const ADD_OBJECT_COLUMNS = [
    { label: 'NORAD ID', numeric: true, getValue: (obj) => obj.noradID, format: (v) => v },
    { label: 'NAME', numeric: false, getValue: (obj) => obj.name || '', format: (v) => v || '--' },
    { label: 'OBJ TYPE', numeric: false, getValue: (obj) => obj.objectType || '', format: (v) => v || '--' },
    { label: 'LAUNCH DATE', numeric: false, getValue: (obj) => obj.launchDate || '', format: (v) => v || '--' },
    { label: 'SPACE PORT', numeric: false, getValue: (obj) => obj.launchSite || '', format: (v) => v || '--' },
    { label: 'COUNTRY', numeric: false, getValue: (obj) => obj.owner || '', format: (v) => v || '--' },
    { label: 'INCL', numeric: true, getValue: (obj) => obj.inclination, format: (v) => Number.isFinite(v) ? `${v.toFixed(1)}°` : '--' },
    { label: 'PERIGEE', numeric: true, getValue: (obj) => obj.perigee, format: (v) => Number.isFinite(v) ? `${Math.round(v).toLocaleString('en-US')} KM` : '--' },
    { label: 'APOGEE', numeric: true, getValue: (obj) => obj.apogee, format: (v) => Number.isFinite(v) ? `${Math.round(v).toLocaleString('en-US')} KM` : '--' },
    { label: 'PERIOD', numeric: true, getValue: (obj) => obj.period, format: (v) => Number.isFinite(v) ? `${v.toLocaleString('en-US', { minimumFractionDigits: 1, maximumFractionDigits: 1 })} MIN` : '--' },
    { label: 'MMOTION', numeric: true, getValue: (obj) => obj.meanMotion, format: (v) => Number.isFinite(v) ? v.toFixed(1) : '--' },
];

// Last-rendered search results, kept around so clicking a column header
// can re-sort and redraw without re-running the search itself. Sort
// state persists across searches (not reset per-search) so re-filtering
// keeps whatever column ordering the user already picked.
let addObjectSearchResults = [];
let addObjectSortColumnIndex = null;
let addObjectSortDirection = 'asc';

function renderAddObjectResultsTable(objects, truncated) {
    const status = document.getElementById('add-object-status');
    if (status) {
        status.textContent = objects.length === 0 ? 'NO MATCHES.' : '';
    }
    addObjectSearchResults = objects;
    renderAddObjectResultsTableFromState();
}

// Wired to each sortable <th>. Clicking the already-active column flips
// its direction; clicking a different column switches to it, ascending.
function sortAddObjectResultsBy(columnIndex) {
    if (addObjectSortColumnIndex === columnIndex) {
        addObjectSortDirection = addObjectSortDirection === 'asc' ? 'desc' : 'asc';
    } else {
        addObjectSortColumnIndex = columnIndex;
        addObjectSortDirection = 'asc';
    }
    renderAddObjectResultsTableFromState();
}

// Rebuilds the table (header + rows) from addObjectSearchResults and the
// current sort state -- the one place that actually touches the DOM,
// called both after a fresh search and after a header click, so the
// header's arrow indicator and the row order never fall out of sync.
function renderAddObjectResultsTableFromState() {
    const table = document.getElementById('add-object-results-table');
    if (!table) {
        return;
    }

    table.innerHTML = '';

    const rows = addObjectSearchResults.slice();
    if (addObjectSortColumnIndex !== null) {
        const column = ADD_OBJECT_COLUMNS[addObjectSortColumnIndex];
        const dir = addObjectSortDirection === 'asc' ? 1 : -1;
        rows.sort((a, b) => {
            const va = column.getValue(a);
            const vb = column.getValue(b);
            if (column.numeric) {
                // Missing/unparseable values sort to the bottom
                // regardless of direction, rather than flipping to the
                // top on a descending sort.
                const na = Number.isFinite(va) ? va : -Infinity;
                const nb = Number.isFinite(vb) ? vb : -Infinity;
                return (na - nb) * dir;
            }
            return String(va).localeCompare(String(vb)) * dir;
        });
    }

    const thead = document.createElement('thead');
    const headerRow = document.createElement('tr');
    ADD_OBJECT_COLUMNS.forEach((column, i) => {
        const th = document.createElement('th');
        th.className = 'add-object-sortable-header';
        // Right-justified for every column except NORAD ID and NAME
        // (indices 0/1), matching the data cells below.
        if (i >= 2) {
            th.style.textAlign = 'right';
        }
        th.appendChild(document.createTextNode(`${column.label} `));
        // Every sortable header shows an arrow from the first render, not
        // just once a column's been clicked -- a neutral up/down glyph
        // (dimmed via CSS) marks "sortable, not yet sorted this way",
        // replaced by a solid directional one for whichever column is
        // actually active. Standard sortable-table convention.
        const isActive = addObjectSortColumnIndex === i;
        const arrowSpan = document.createElement('span');
        arrowSpan.className = isActive ? 'add-object-sort-arrow' : 'add-object-sort-arrow add-object-sort-arrow-inactive';
        arrowSpan.textContent = isActive ? (addObjectSortDirection === 'asc' ? '▲' : '▼') : '⇅';
        th.appendChild(arrowSpan);
        th.addEventListener('click', () => sortAddObjectResultsBy(i));
        headerRow.appendChild(th);
    });
    thead.appendChild(headerRow);
    table.appendChild(thead);

    const tbody = document.createElement('tbody');
    rows.forEach((obj) => {
        const tr = document.createElement('tr');
        tr.className = 'add-object-row';
        if (addObjectSelectedIds.has(obj.noradID)) {
            tr.classList.add('add-object-row-selected');
        }
        tr.addEventListener('click', () => toggleAddObjectRowSelection(obj.noradID, tr));

        ADD_OBJECT_COLUMNS.forEach((column, i) => {
            const td = document.createElement('td');
            td.textContent = column.format(column.getValue(obj));
            if (i >= 2) {
                td.style.textAlign = 'right';
            }
            tr.appendChild(td);
        });
        tbody.appendChild(tr);
    });
    table.appendChild(tbody);
}

function toggleAddObjectRowSelection(noradId, rowEl) {
    if (addObjectSelectedIds.has(noradId)) {
        addObjectSelectedIds.delete(noradId);
    } else {
        addObjectSelectedIds.add(noradId);
    }
    rowEl.classList.toggle('add-object-row-selected', addObjectSelectedIds.has(noradId));
}

// Ground tracks for every object in plottedNoradIds, one full orbital
// period each, each in its own colour/dash style (see getTrackStyle()
// above) so multiple objects stay visually distinguishable, plus a
// separate live-updating marker per object. Layers live in module-level
// collections (not single variables, now that there can be several) so
// each fresh render clears everything from the previous one first --
// same remove-before-add pattern used throughout this file, just applied
// per-object now.
let groundTrackLayerGroup = null;

// Tracks GRD TRCK's own on/off state -- see toggleGroundTrack() below.
let groundTrackVisible = false;

// Linearly interpolates the latitude at the exact +/-180 crossing point
// between two consecutive track points, rather than just letting each
// segment stop at its last real sample short of the boundary -- without
// this, the track visibly falls short of the map edge on both sides of
// every crossing, showing as a gap even though the real ground track is
// continuous there. Unwraps the far point across the boundary (e.g. -179
// becomes 181 when prev is at +179) so the interpolation fraction is a
// normal linear one, same idea as lerpAtLongitude() in Section 4's
// antimeridian-safe polygon clipping, just applied to a two-point segment
// instead of a polygon ring.
function interpolateAntimeridianCrossing(prev, curr) {
    const crossingToNegative = curr[1] < prev[1]; // e.g. prev=+179 -> curr=-179
    const boundaryLon = crossingToNegative ? 180 : -180;
    const unwrappedCurrLon = crossingToNegative ? curr[1] + 360 : curr[1] - 360;
    const t = (boundaryLon - prev[1]) / (unwrappedCurrLon - prev[1]);
    const boundaryLat = prev[0] + t * (curr[0] - prev[0]);
    return {
        endOfThisSegment: [boundaryLat, boundaryLon],
        startOfNextSegment: [boundaryLat, crossingToNegative ? -180 : 180],
    };
}

// A ground track crossing +/-180 degrees longitude needs the polyline
// broken into separate segments at each crossing, or Leaflet draws a
// spurious straight line all the way across the map connecting the two
// sides of the jump. Simpler than the Sutherland-Hodgman clipping used
// for the world-boundary polygons (see fixAntimeridianCrossings() in
// Section 4) -- a track isn't a closed shape that needs to stay valid
// after clipping, so splitting into pieces (each extended to the
// interpolated boundary point) is sufficient here.
function splitTrackAtAntimeridian(points) {
    const segments = [[]];
    for (const point of points) {
        const currentSegment = segments[segments.length - 1];
        const previous = currentSegment[currentSegment.length - 1];
        if (previous && Math.abs(point[1] - previous[1]) > 180) {
            const crossing = interpolateAntimeridianCrossing(previous, point);
            currentSegment.push(crossing.endOfThisSegment);
            segments.push([crossing.startOfNextSegment]);
        }
        segments[segments.length - 1].push(point);
    }
    return segments.filter((segment) => segment.length > 1);
}

// Footprint = the patch of Earth a satellite can see from orbit, modelled
// as a circle on the ground centred on the satellite's nadir point (the
// point directly below it, already computed each tick for the live-position
// marker). Uses a minimum-elevation mask rather than the pure geometric
// (0-degree) horizon -- contacts right at the horizon are unusable in
// practice (terrain, buildings, atmosphere), so a modest real-world mask
// gives a more honest "usable" footprint. 5 degrees is a common baseline.
const EARTH_RADIUS_KM = 6371;
const FOOTPRINT_MIN_ELEVATION_DEG = 5;
const FOOTPRINT_RING_POINTS = 72; // 5-degree bearing steps -- smooth enough at any zoom used here

// Earth-centre angle (radians) from nadir to the edge of visibility, given
// satellite height above the surface and the elevation mask -- derived from
// the right triangle formed by Earth's centre, the satellite, and the point
// on the horizon at the mask's elevation angle.
function computeFootprintAngularRadiusRad(heightKm, minElevationDeg) {
    const elRad = minElevationDeg * Math.PI / 180;
    const ratio = (EARTH_RADIUS_KM / (EARTH_RADIUS_KM + heightKm)) * Math.cos(elRad);
    return Math.acos(ratio) - elRad;
}

// Standard great-circle destination-point formula: given a start point, an
// angular distance (radians, as a fraction of Earth's radius) and a
// bearing, returns the resulting [lat, lon] in degrees.
function destinationPoint(latDeg, lonDeg, angularDistanceRad, bearingRad) {
    const lat1 = latDeg * Math.PI / 180;
    const lon1 = lonDeg * Math.PI / 180;
    const lat2 = Math.asin(
        Math.sin(lat1) * Math.cos(angularDistanceRad) +
        Math.cos(lat1) * Math.sin(angularDistanceRad) * Math.cos(bearingRad)
    );
    const lon2 = lon1 + Math.atan2(
        Math.sin(bearingRad) * Math.sin(angularDistanceRad) * Math.cos(lat1),
        Math.cos(angularDistanceRad) - Math.sin(lat1) * Math.sin(lat2)
    );
    return [lat2 * 180 / Math.PI, ((lon2 * 180 / Math.PI + 540) % 360) - 180];
}

// Builds the footprint ring in [lon, lat] order -- matching the GeoJSON
// convention clipRingToAntimeridianSafeBounds() already expects (see
// Section 4) -- so a footprint that happens to straddle +/-180 longitude
// gets exactly the same antimeridian handling as the world-boundary
// polygons rather than a fresh implementation.
function buildFootprintRing(latDeg, lonDeg, angularRadiusRad) {
    const ring = [];
    for (let i = 0; i <= FOOTPRINT_RING_POINTS; i++) {
        const bearing = (i / FOOTPRINT_RING_POINTS) * 2 * Math.PI;
        const [lat, lon] = destinationPoint(latDeg, lonDeg, angularRadiusRad, bearing);
        ring.push([lon, lat]);
    }
    return ring;
}

function renderGroundTrackLayer(tracksByObject) {
    if (groundTrackLayerGroup) {
        onOrbitMap.removeLayer(groundTrackLayerGroup);
        groundTrackLayerGroup = null;
    }
    const polylines = [];
    tracksByObject.forEach(({ points, style }) => {
        // Each object's own segments (already split at any antimeridian
        // crossings) share that object's colour/dash style, matching its
        // KEY column swatch in the table.
        splitTrackAtAntimeridian(points).forEach((segment) => {
            polylines.push(L.polyline(segment, {
                color: style.color, dashArray: style.dashArray, weight: 2, opacity: 0.85,
            }));
        });
    });
    if (polylines.length === 0) {
        return;
    }
    groundTrackLayerGroup = L.layerGroup(polylines).addTo(onOrbitMap);
}

// Fetches the plotted objects and builds one satrec per object, keyed by
// noradID -- shared by GRD TRCK (which also samples a full orbit's worth
// of points for the polyline) and SHW FOOT (which only needs each
// object's current position/height, recomputed every tick). Resets and
// repopulates livePositionSatrecs/Markers/footprintLayers every call, same
// "replace rather than accumulate" pattern as re-clicking GRD TRCK.
async function loadTrackedSatrecs() {
    const response = await fetch(`api/orbital-objects?ids=${plottedNoradIds.join(',')}`);
    if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
    }
    const orderedObjects = orderObjectsByPlottedList(await response.json());
    if (orderedObjects.length === 0) {
        throw new Error('no orbital elements on file for any plotted object');
    }

    await loadScriptOnce('assets/satellite/satellite.min.js');

    // Full reset before rebuilding -- stopping the old interval first so
    // it can't fire mid-rebuild against markers/footprints that are about
    // to be replaced.
    clearInterval(livePositionInterval);
    livePositionSatrecs.clear();
    livePositionMarkers.forEach((marker) => onOrbitMap.removeLayer(marker));
    livePositionMarkers.clear();
    clearFootprintLayers();

    orderedObjects.forEach((obj, index) => {
        if (!Number.isFinite(obj.meanMotion)) {
            console.error(`Skipping noradID ${obj.noradID}: no orbital elements on file`);
            return;
        }
        // satellite.js's json2satrec() expects OMM's own UPPER_SNAKE keys --
        // the API returns this project's usual camelCase, so map the fields
        // over at this one call site rather than changing that convention.
        const satrec = satellite.json2satrec({
            NORAD_CAT_ID: obj.noradID,
            EPOCH: obj.epoch,
            MEAN_MOTION: obj.meanMotion,
            ECCENTRICITY: obj.eccentricity,
            INCLINATION: obj.inclination,
            RA_OF_ASC_NODE: obj.raOfAscNode,
            ARG_OF_PERICENTER: obj.argOfPericenter,
            MEAN_ANOMALY: obj.meanAnomaly,
            BSTAR: obj.bstar,
            MEAN_MOTION_DOT: obj.meanMotionDot,
            MEAN_MOTION_DDOT: obj.meanMotionDdot,
        });
        const style = getTrackStyle(index);
        // meta is the SATCAT / EIRP-enrichment metadata for the click
        // popup (see livePositionPopupHtml() / updateLivePositions()).
        // Kept alongside the satrec so the popup doesn't need its own fetch.
        livePositionSatrecs.set(obj.noradID, {
            satrec,
            style,
            name: obj.name || String(obj.noradID),
            meta: {
                owner: obj.owner || null,
                launchYear: obj.launchDate ? String(obj.launchDate).slice(0, 4) : null,
                launchSite: obj.launchSite || null,
                objectType: obj.objectType || null,
                downlinkBand: obj.downlinkBand || null,
                eirpDbw: obj.eirpDbw,
                eirpSource: obj.eirpSource || null,
                periodMin: obj.period,
                apogeeKm: obj.apogee,
                perigeeKm: obj.perigee,
                rcsM2: obj.rcsSize,
            },
        });
    });

    return orderedObjects;
}

// Wired to the GRD TRCK button. Toggle, not a plain re-render: a second
// click while tracks are showing turns everything GRD TRCK brought with
// it back off -- same on/off pattern as toggleFootprints(), but GRD TRCK
// is the one that owns the shared live-tracking state (it's what starts
// startLivePositionUpdates() in the first place), so turning it off tears
// that whole state down rather than leaving orphaned markers/footprints
// on screen with nothing driving them: the polyline layer, the live
// moving markers (and their labels), and any footprints, all come down
// together, and SHW FOOT resets to OFF since its footprints can't
// meaningfully stay "on" once the position updates they depend on have
// stopped. refreshAllLabels() in updateControlArea() (lcars.js) is what
// makes SHW FOOT's own button label pick up that reset immediately,
// rather than only on SHW FOOT's next click.
//
// The "on" path draws every object in plottedNoradIds at once, one fetch
// for the whole list (batched, not one request per object) rather than
// looping fetches per satellite.
async function toggleGroundTrack() {
    groundTrackVisible = !groundTrackVisible;
    if (!groundTrackVisible) {
        if (groundTrackLayerGroup) {
            onOrbitMap.removeLayer(groundTrackLayerGroup);
            groundTrackLayerGroup = null;
        }
        clearInterval(livePositionInterval);
        livePositionMarkers.forEach((marker) => onOrbitMap.removeLayer(marker));
        livePositionMarkers.clear();
        clearFootprintLayers();
        footprintsVisible = false;
        return;
    }

    // Same typeof guard as toggleFootprints()/renderUserLocationMarker()
    // -- onOrbitMap is an assets/mapCore.js global.
    if (typeof onOrbitMap === 'undefined' || !onOrbitMap || plottedNoradIds.length === 0) {
        groundTrackVisible = false;
        return;
    }

    await renderGroundTracksForPlottedList();
}

// The actual "on" rendering work -- recomputes and (re)draws ground
// tracks + live position markers for the current plottedNoradIds.
// Factored out of toggleGroundTrack() so it can also be re-run to refresh
// an already-visible ground track after the plotted list changes
// elsewhere (see addSelectedResultsToPlottedList() below) without going
// through the toggle itself, which would just turn tracking back off.
async function renderGroundTracksForPlottedList() {
    try {
        const orderedObjects = await loadTrackedSatrecs();

        const tracksByObject = [];
        orderedObjects.forEach((obj) => {
            const tracked = livePositionSatrecs.get(obj.noradID);
            if (!tracked) {
                return; // no orbital elements on file -- already logged in loadTrackedSatrecs()
            }
            const { satrec, style } = tracked;

            // Prefer the SATCAT-derived period -- already decimal
            // minutes, no computation needed (see the table's PERIOD
            // column). Falls back to deriving it from the TLE's own mean
            // motion (rev/day) for objects SATCAT hasn't enriched yet.
            const meanMotion = obj.meanMotion;
            const periodMinutes = Number.isFinite(obj.period)
                ? obj.period
                : (Number.isFinite(meanMotion) && meanMotion > 0 ? 1440 / meanMotion : null);
            if (!periodMinutes) {
                console.error(`Skipping noradID ${obj.noradID}: could not determine orbital period`);
                return;
            }

            const SAMPLE_COUNT = 180;
            const startTime = Date.now();
            const points = [];
            for (let i = 0; i <= SAMPLE_COUNT; i++) {
                const time = new Date(startTime + (i / SAMPLE_COUNT) * periodMinutes * 60000);
                const { position: positionEci } = satellite.propagate(satrec, time);
                if (!positionEci) {
                    continue;
                }
                const geodetic = satellite.eciToGeodetic(positionEci, satellite.gstime(time));
                points.push([satellite.degreesLat(geodetic.latitude), satellite.degreesLong(geodetic.longitude)]);
            }

            tracksByObject.push({ points, style });
        });

        renderGroundTrackLayer(tracksByObject);
        startLivePositionUpdates();
    } catch (error) {
        console.error('Could not render ground tracks:', error.message);
        groundTrackVisible = false;
    }
}

let livePositionMarkers = new Map(); // noradID -> L.CircleMarker
let livePositionSatrecs = new Map(); // noradID -> { satrec, style }, read by the shared interval below
let livePositionInterval = null;
let footprintLayers = new Map(); // noradID -> L.Polygon
let footprintsVisible = false;

// Wired to the SHW ALT button -- toggles the altitude line under each
// object's name in its ground-track label. Defaults off.
let showAltitude = false;

// Wired to the SHW ALT button. updateLivePositions() reads showAltitude
// directly on its next tick (it already refreshes every label's content
// every second via setTooltipContent()), so there's nothing else to
// force here -- flipping the flag is enough.
function toggleAltitudeDisplay() {
    showAltitude = !showAltitude;
}

function clearFootprintLayers() {
    footprintLayers.forEach((layer) => onOrbitMap.removeLayer(layer));
    footprintLayers.clear();
}

// Wired to the SHW FOOT button. Doesn't draw anything itself -- just
// ensures satrecs are loaded (reusing the GRD TRCK ones if already
// present, so toggling footprint on after ground tracks doesn't refetch)
// and (re)starts the shared per-tick interval, which is what actually
// draws/updates the footprint rings once footprintsVisible is true (see
// updateLivePositions() below).
//
// The shared live-position interval/markers/labels are jointly owned by
// GRD TRCK and SHW FOOT -- whichever turns on first starts them, and they
// only come down when BOTH are off, not whichever turns off second. If
// GRD TRCK is still showing tracks, its own moving dots still need them,
// so turning footprints off alone must leave markers/labels running; if
// GRD TRCK is already off, SHW FOOT was the only thing still using them,
// so this is the point they should actually disappear (matching
// toggleGroundTrack()'s own teardown when it's the one turning off last).
async function toggleFootprints() {
    footprintsVisible = !footprintsVisible;
    if (!footprintsVisible) {
        clearFootprintLayers();
        if (!groundTrackVisible) {
            clearInterval(livePositionInterval);
            livePositionMarkers.forEach((marker) => onOrbitMap.removeLayer(marker));
            livePositionMarkers.clear();
        }
        return;
    }
    // Same typeof guard as renderUserLocationMarker() -- onOrbitMap is an
    // assets/mapCore.js global, so a bare reference could theoretically
    // throw ReferenceError rather than read as falsy if this ever fired
    // before mapCore.js finished loading.
    if (typeof onOrbitMap === 'undefined' || !onOrbitMap || plottedNoradIds.length === 0) {
        footprintsVisible = false;
        return;
    }
    try {
        if (livePositionSatrecs.size === 0) {
            await loadTrackedSatrecs();
        }
        startLivePositionUpdates();
    } catch (error) {
        console.error('Could not show footprints:', error.message);
        footprintsVisible = false;
    }
}

// SGP4 propagation benchmarked at ~1.7 microseconds/object (measured
// across 12 real objects at once), so recomputing every tracked object's
// true position every tick -- rather than interpolating between sparser
// samples -- costs nothing measurable even at a dozen-plus objects. One
// shared interval for every object rather than one per object: simpler
// to manage, and there's no per-object overhead worth avoiding.
//
// 1-second interval: ISS's own ground-track speed (how fast the
// sub-satellite point moves across Earth's surface) works out to about
// 7 km/s from its own real figures already in the DB. That's ~7 km per
// 1-second step -- small enough to read as continuous motion at any
// reasonable map zoom, without the overhead of a 60fps redraw loop for
// something moving this slowly on a world-scale map.
const LIVE_POSITION_UPDATE_MS = 1000;

// Reuses the satrecs toggleGroundTrack() already parsed -- no need to
// re-fetch or re-parse any TLE just to also track current positions.
// Restarting (re-clicking GRD TRCK) replaces the previous interval rather
// than accumulating a second one running alongside it.
function startLivePositionUpdates() {
    clearInterval(livePositionInterval);
    updateLivePositions();
    livePositionInterval = setInterval(updateLivePositions, LIVE_POSITION_UPDATE_MS);
}

// Shared catalogue / EIRP-enrichment rows for the satellite-info popups on
// both the on-orbit map (GRD TRCK, below) and the GS OPS map (VISIBLE NOW,
// gsOpsPanel.js). `m` carries: noradID, owner, launchYear, launchSite,
// objectType, rcsM2, periodMin, perigeeKm, apogeeKm, eirpDbw, eirpSource,
// downlinkBand. Returns [label, value] pairs; each caller wraps its own
// title and any live/station-relative rows around these.
function satelliteCatalogRows(m) {
    m = m || {};
    const typeLabel = (OBJECT_TYPE_FILTER_OPTIONS.find((o) => o.value === m.objectType) || {}).label
        || m.objectType || '—';
    const owner = m.owner ? (COUNTRY_CODE_NAMES[m.owner] || m.owner) : '—';
    const eirp = Number.isFinite(m.eirpDbw)
        ? `${m.eirpSource === 'estimated' ? '≈ ' : ''}${m.eirpDbw} dBW`
        : '—';
    const km = (v) => (Number.isFinite(v) ? `${Math.round(v).toLocaleString('en-GB')} km` : '—');
    return [
        ['NORAD', m.noradID != null ? m.noradID : '—'],
        ['OWNER', owner],
        ['LAUNCH YEAR', m.launchYear || '—'],
        ['LAUNCH SITE', m.launchSite || '—'],
        ['TYPE', typeLabel],
        ['EST. SIZE', Number.isFinite(m.rcsM2) ? `${parseFloat(m.rcsM2.toPrecision(1))} m²` : '—'],
        ['PERIOD', Number.isFinite(m.periodMin) ? `${m.periodMin.toFixed(1)} min` : '—'],
        ['PERIGEE', km(m.perigeeKm)],
        ['APOGEE', km(m.apogeeKm)],
        ['EST. EIRP', eirp],
        ['INFERRED BAND', m.downlinkBand || '—'],
    ];
}

// Click popup for a live-position marker (shown while GRD TRCK is on).
// All the SATCAT / EIRP-enrichment metadata the API returned for this
// object, carried on its livePositionSatrecs entry so there's no extra
// fetch. Uses the shared .popup-name/.popup-meta/.popup-value classes --
// #on-orbit-map popup styling in classic.css matches the GS OPS
// VISIBLE NOW popups.
function livePositionPopupHtml(name, noradID, meta) {
    const rows = satelliteCatalogRows({ ...(meta || {}), noradID });
    const body = rows
        .map(([k, v]) => `<span class="popup-meta">${k}:</span> <span class="popup-value">${v}</span>`)
        .join('<br>');
    return `<span class="popup-name">${name}</span><br>${body}`;
}

function updateLivePositions() {
    if (!onOrbitMap) {
        return;
    }
    const now = new Date();
    livePositionSatrecs.forEach(({ satrec, style, name, meta }, noradID) => {
        const { position: positionEci } = satellite.propagate(satrec, now);
        if (!positionEci) {
            return;
        }
        const geodetic = satellite.eciToGeodetic(positionEci, satellite.gstime(now));
        const latDeg = satellite.degreesLat(geodetic.latitude);
        const lonDeg = satellite.degreesLong(geodetic.longitude);
        const latlng = [latDeg, lonDeg];

        // Altitude changes continuously (especially on elliptical orbits),
        // so unlike the name, this has to be refreshed every tick, not
        // just set once at marker creation. showAltitude (SHW ALT button)
        // just omits the second line -- no separate re-render path needed,
        // since this whole block already runs every tick regardless.
        const altitudeLine = showAltitude ? `<br>${Math.round(geodetic.height)} KM` : '';
        const labelContent = `<span style="color:${style.color}">${name}${altitudeLine}</span>`;

        const existingMarker = livePositionMarkers.get(noradID);
        if (existingMarker) {
            existingMarker.setLatLng(latlng);
            existingMarker.setTooltipContent(labelContent);
        } else {
            // Same colour as this object's track line, so each moving
            // dot (and its label) reads as belonging to its own track
            // rather than an unrelated marker.
            const marker = L.circleMarker(latlng, {
                radius: 5, color: style.color, weight: 1, fillColor: style.color, fillOpacity: 1,
            }).addTo(onOrbitMap);
            marker.bindTooltip(labelContent, {
                permanent: true, direction: 'right', offset: [8, 0], className: 'orbit-marker-label',
            });
            marker.bindPopup(() => livePositionPopupHtml(name, noradID, meta));
            livePositionMarkers.set(noradID, marker);
        }

        if (footprintsVisible) {
            // geodetic.height is already computed above for the marker
            // position -- no extra propagation needed to also update the
            // footprint each tick.
            const angularRadiusRad = computeFootprintAngularRadiusRad(geodetic.height, FOOTPRINT_MIN_ELEVATION_DEG);
            const ring = buildFootprintRing(latDeg, lonDeg, angularRadiusRad);
            const clippedRing = clipRingToAntimeridianSafeBounds(ring) || ring;
            const footprintLatLngs = clippedRing.map(([lon, lat]) => [lat, lon]);
            const existingFootprint = footprintLayers.get(noradID);
            if (existingFootprint) {
                existingFootprint.setLatLngs(footprintLatLngs);
            } else {
                const footprint = L.polygon(footprintLatLngs, {
                    color: style.color, weight: 1, dashArray: '4,4', fillColor: style.color, fillOpacity: 0.08, interactive: false,
                }).addTo(onOrbitMap);
                footprintLayers.set(noradID, footprint);
            }
        }
    });
}

// Registers this panel's control-area buttons with lcars.js's generic
// updateControlArea() dispatcher. Reproduces the old hardcoded
// CONTROL_AREA_BUTTON_LABELS['on-orbit']/ON_ORBIT_BUTTON_COLORS-driven
// branch's behaviour exactly, aside from these fixes: ADD OBJ/USR LOCN/GRD
// TRCK/SHW FOOT/SHW ALT/DEL OBJ wired to their handlers, GRD TRCK/SHW
// FOOT/SHW ALT all with a dynamic ON/OFF label now that GRD TRCK is a
// real toggle (BUG-001 -- it previously just re-rendered on every click,
// never turning off). defaultAreaMode: 'custom' reproduces the old
// sectionId === 'on-orbit' branch in updateControlArea() that called
// fetchAndRenderOrbitalObjectsList() instead of a label or key grid.
//
// buttons is a function, not a plain array, specifically so DEL
// SELECTION/CLEAR can appear only while DEL OBJ's view is open
// (delObjViewActive) -- lcars.js's renderControlAreaButtons() evaluates
// this fresh every time it's called, including the extra calls
// toggleDelObjView() makes itself on open/close, so the button set never
// goes stale.
registerPanelControls('on-orbit', {
    defaultAreaMode: 'custom',
    renderDefaultArea: fetchAndRenderOrbitalObjectsList,
    buttons: () => {
        const buttons = [
            { label: 'ADD OBJ', color: 'var(--golden-orange)', onClick: toggleAddObjectForm },
            {
                label: 'GRD TRCK',
                color: 'var(--bluey)',
                getText: () => `GRD TRCK - ${groundTrackVisible ? 'ON' : 'OFF'}`,
                onClick: toggleGroundTrack,
            },
            {
                label: 'SHW FOOT',
                color: 'var(--sky)',
                getText: () => `SHW FOOT - ${footprintsVisible ? 'ON' : 'OFF'}`,
                onClick: toggleFootprints,
            },
            { label: 'DEL OBJ', color: 'var(--orange)', onClick: toggleDelObjView },
            { label: 'USR LOCN', color: 'var(--peach)', onClick: () => toggleUserLocationForm(fetchAndRenderOrbitalObjectsList) },
            {
                label: 'SHW ALT',
                color: 'var(--butterscotch)',
                getText: () => `SHW ALT - ${showAltitude ? 'ON' : 'OFF'}`,
                onClick: toggleAltitudeDisplay,
            },
        ];

        if (delObjViewActive) {
            // Warm/destructive red for the actual delete action, matching
            // LCARS convention elsewhere in this app; blue for CLEAR since
            // it's a non-destructive selection-utility action.
            // Shared group -- renderControlAreaButtons() (lcars.js) stacks
            // same-group buttons vertically in one shared div rather than
            // each taking its own slot in nav's row, and unshifting the
            // pair (in this order, so DEL SELECTION ends up on top) puts
            // that div at the left of the row.
            buttons.unshift(
                { label: 'DEL SELECTION', color: 'var(--red)', group: 'del-obj-actions', onClick: deleteSelectedPlottedObjects },
                { label: 'CLEAR', color: 'var(--sky)', group: 'del-obj-actions', onClick: clearAddObjectSelection },
            );
        }

        return buttons;
    },
});
