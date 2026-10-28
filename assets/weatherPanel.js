/* ==========================================================================
   WEATHER PANEL

   Space weather as it matters to this site: the Sun's output, conditions at
   Earth, aurora, radio links (satellite and HF) and drag on LEO satellites.
   Design and sources: enterpriseCrewOutput/spock_spaceWeatherReport_*.md.

   Control panel: USR LOCN opens the shared LAT/LON/PLACE form
   (toggleUserLocationForm(), grdTrackPanel.js); the other nine buttons each
   select a view in the payload area. Only the buttons, the view
   skeletons and the DEFS page exist so far -- WEATHER_VIEWS lists what each
   view will show. SOL DRVR has its first chart (the L1 solar wind, K1 in
   assets/weatherCharts.js) and the rest of the page: flares, F10.7, the solar cycle, CMEs, the outlook.
   The other views are not yet connected to data.

   The section id stays 'sw-drivers' (the id the left-menu button and
   index.html already use). Lazily loaded the first time WEATHER is opened;
   openWeatherSection() in lcars.js loads mapCore.js and grdTrackPanel.js
   (the shared location form and store) first.
   ========================================================================== */

const WEATHER_VIEWS = {
    drivers: {
        title: 'SOLAR DRIVERS',
        lead: 'What the Sun is sending: the cause of everything below.',
        // Drawn by renderDriversView() with the charts of assets/weatherCharts.js.
    },
    earth: {
        title: 'EARTH NOW',
        lead: 'Current conditions at Earth.',
        // Drawn by renderEarthView() with the charts of assets/weatherEarth.js.
    },
    aurora: {
        title: 'AURORAE',
        lead: 'Where the aurora is and whether it can be seen from your location.',
        // Drawn by renderAuroraView() with the charts of assets/weatherAurora.js.
    },
    satComms: {
        title: 'SAT COMMS',
        lead: 'Ionospheric effects on satellite-to-ground radio links.',
        // Drawn by renderSatView() with the charts of assets/weatherSat.js.
    },
    hfComms: {
        title: 'HF COMMS',
        lead: 'Conditions for shortwave radio.',
        // Drawn by renderHfView() with the charts of assets/weatherHf.js (foF2, YOUR PATH and the GNSS TEC lamp are not yet built).
    },
    drag: {
        title: 'LEO DRAG',
        lead: 'The upper atmosphere and satellites in low orbit.',
        // Drawn by renderDragView() with the charts of assets/weatherDrag.js (the drag index and the decay-rate chart wait for the element-set history).
    },
    gcr: {
        title: 'GALACTIC COSMIC RAYS',
        lead: 'Particles from outside the solar system: a busy Sun pushes them away.',
        // Drawn by renderGcrView() with the charts of assets/weatherGcr.js.
    },
};

// SUN NOW: live pictures of the Sun, fetched by the visitor's browser straight
// from NASA and NOAA each time the view is opened (nothing is copied to our
// server). Each is about 45 to 155 KB, about 400 KB in all. NASA's SDO images
// are served no-cache, so the loaded pictures are kept in memory for
// SUN_IMAGES_KEEP_MS (30 minutes) and re-shown, not fetched again, when the
// visitor switches views and comes back. Each title bar has a tooltip (shown
// on hover, keyboard focus or tap) saying what the picture is, where it came
// from, when it was made, and (About) the science in a sentence or two.
const SUN_IMAGES = [
    // Pairs, in reading order: sunspots, then corona and flares, then CMEs.
    { key: 'hmiIntensity', group: 'SUNSPOTS', title: 'Visible light', src: 'https://sdo.gsfc.nasa.gov/assets/img/latest/latest_512_HMIIC.jpg',
      what: 'The Sun in visible light (a colourised HMI continuum image, 512 pixels).',
      from: 'NASA Solar Dynamics Observatory (SDO), sdo.gsfc.nasa.gov.',
      science: 'This is the Sun\'s visible surface as the eye would see it. Sunspots are cooler, darker patches where intense magnetic fields hold back the heat rising from below; flares start above them.',
      credit: 'NASA/SDO and the HMI science team' },
    { key: 'hmiMagnetogram', group: 'SUNSPOTS', title: 'Magnetic polarity', src: 'https://sdo.gsfc.nasa.gov/assets/img/latest/latest_512_HMIB.jpg',
      what: 'The same view as a magnetogram: the magnetic field along our line of sight (HMI, 512 pixels).',
      from: 'NASA Solar Dynamics Observatory (SDO), sdo.gsfc.nasa.gov.',
      science: 'White is magnetic field pointing towards us and black is field pointing away. Groups with both polarities packed close together are magnetically complex, and are the ones most likely to flare.',
      credit: 'NASA/SDO and the HMI science team' },
    { key: 'aia193', group: 'THE CORONA', title: 'Extreme ultraviolet, 193 Å', src: 'https://sdo.gsfc.nasa.gov/assets/img/latest/latest_512_0193.jpg',
      what: 'The corona in extreme ultraviolet light at 193 ångströms (a colourised AIA image, 512 pixels).',
      from: 'NASA Solar Dynamics Observatory (SDO), sdo.gsfc.nasa.gov.',
      science: 'It shows plasma at over a million degrees in the Sun\'s outer atmosphere. Dark areas are coronal holes, where open magnetic field lets fast solar wind stream out towards Earth.',
      credit: 'NASA/SDO and the AIA science team' },
    { key: 'aia131', group: 'FLARES', title: 'Extreme ultraviolet, 131 Å', src: 'https://sdo.gsfc.nasa.gov/assets/img/latest/latest_512_0131.jpg',
      what: 'The hottest solar plasma in extreme ultraviolet light at 131 ångströms (a colourised AIA image, 512 pixels).',
      from: 'NASA Solar Dynamics Observatory (SDO), sdo.gsfc.nasa.gov.',
      science: 'This wavelength picks out plasma at around ten million degrees, so a flare shows as a sudden bright patch. The X-rays and ultraviolet from a flare reach Earth in about eight minutes and can black out HF radio.',
      credit: 'NASA/SDO and the AIA science team' },
    { key: 'lascoC2', group: 'CMEs', title: 'Coronagraph, close (C2)', src: 'https://services.swpc.noaa.gov/images/animations/lasco-c2/latest.jpg',
      what: 'A white-light coronagraph view of the corona close to the Sun, from about 2 to 6 solar radii (SOHO/LASCO C2).',
      from: 'The ESA/NASA SOHO spacecraft at L1, as published by NOAA SWPC, services.swpc.noaa.gov.',
      science: 'A disc blocks the Sun so that the faint corona shows. A coronal mass ejection appears as a bright cloud moving outward, and one aimed at Earth can trigger a geomagnetic storm one to four days later.',
      credit: 'ESA and NASA SOHO/LASCO, via NOAA SWPC' },
    { key: 'lascoC3', group: 'CMEs', title: 'Coronagraph, wide (C3)', src: 'https://services.swpc.noaa.gov/images/animations/lasco-c3/latest.jpg',
      what: 'A wider white-light coronagraph view, from about 4 to 30 solar radii (SOHO/LASCO C3).',
      from: 'The ESA/NASA SOHO spacecraft at L1, as published by NOAA SWPC, services.swpc.noaa.gov.',
      science: 'It follows the same material much further out. How fast a CME crosses the field, and whether it surrounds the Sun in a halo, helps forecasters judge whether and when it will reach Earth.',
      credit: 'ESA and NASA SOHO/LASCO, via NOAA SWPC' },
];
const SUN_IMAGES_KEEP_MS = 30 * 60 * 1000;
let sunViewElement = null;
let sunViewBuiltAt = 0;

function sunTooltip(image) {
    return `<div class="weather-sun-tip" role="tooltip">
        <p><b>What:</b> ${image.what}</p>
        <p><b>From:</b> ${image.from}</p>
        <p><b>Image made:</b> <span class="weather-sun-made" data-key="${image.key}">checking...</span></p>
        <p><b>About:</b> ${image.science}</p>
    </div>`;
}

function attr(text) {
    return text.replace(/&/g, '&amp;').replace(/"/g, '&quot;');
}

function buildSunView() {
    const view = document.createElement('div');
    view.innerHTML = `<div class="weather-sun-grid">${SUN_IMAGES.map((image) => `<figure>
            <header class="orbit-chart-header weather-sun-pill" tabindex="0"><span>${image.group}: ${image.title}</span><span class="weather-sun-dtg" data-key="${image.key}" hidden></span>${sunTooltip(image)}</header>
            <img src="${image.src}" alt="${attr(image.group + ': ' + image.title)}"
                 onerror="this.replaceWith(Object.assign(document.createElement('p'), {className: 'weather-status', textContent: 'Image unavailable from the source.'}))">
            <div class="weather-sun-credit">${image.credit}</div>
        </figure>`).join('')}</div>`;
    showSunImageTimes(view);
    return view;
}

// When each picture was made (a DTG, UTC), from the server's cached header
// check (/api/weather/sun-times), in the title bar and the tooltip. A picture
// whose time is unknown shows none in the bar and "not available" in the tooltip.
async function showSunImageTimes(view) {
    let times = {};
    try {
        const response = await fetch('api/weather/sun-times');
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }
        times = (await response.json()).times;
    } catch (error) {
        console.error('Error loading sun image times:', error);
    }
    view.querySelectorAll('.weather-sun-dtg').forEach((gap) => {
        const dtg = times[gap.dataset.key];
        if (dtg) {
            gap.textContent = dtg;
            gap.hidden = false;
        }
    });
    view.querySelectorAll('.weather-sun-made').forEach((span) => {
        span.textContent = times[span.dataset.key] || 'not available';
    });
}

function renderSunImages(container) {
    if (!sunViewElement || Date.now() - sunViewBuiltAt > SUN_IMAGES_KEEP_MS) {
        sunViewElement = buildSunView();
        sunViewBuiltAt = Date.now();
    }
    container.replaceChildren(sunViewElement);
}

let weatherView = 'sun';   // opens on SUN NOW

// LAT/LON of the user's location in the control area, with the same markup
// as GRD VIEW's. Also the shared location form's on-close renderer, so the
// view below refreshes when a new location has just been picked.
function renderWeatherDefaultArea() {
    const wrapper = document.getElementById('default');
    if (wrapper) {
        const coordinate = (value) => (observerLocation ? formatSignedCoordinate(value) : '—');
        wrapper.innerHTML = `<div class="grd-view-table">
            <span class="loc-label">LAT</span><span class="loc-value">${coordinate(observerLocation && observerLocation.latitude)}</span>
            <span class="loc-label">LON</span><span class="loc-value">${coordinate(observerLocation && observerLocation.longitude)}</span>
        </div>`;
    }
    renderWeatherView();
}

// DEFS: terms and thresholds, a static HTML fragment in the definitions
// pages' format (assets/weatherDefs.html, converted from the primer in
// enterpriseCrewOutput/), fetched on first use.
async function renderWeatherDefinitions(container) {
    container.innerHTML = '<div id="weather-defs-body"><p class="weather-status">Loading definitions...</p></div>';
    await loadHelperHtml('assets/weatherDefs.html', 'weather-defs-body');
}

function renderWeatherView() {
    const container = document.getElementById('weather-view');
    if (!container) {
        return;
    }
    if (weatherView === 'defs') {
        renderWeatherDefinitions(container);
        return;
    }
    if (weatherView === 'sun') {
        renderSunImages(container);
        return;
    }
    if (weatherView === 'drivers') {
        renderDriversView(container);
        return;
    }
    if (weatherView === 'earth') {
        renderEarthView(container);
        return;
    }
    if (weatherView === 'gcr') {
        renderGcrView(container);
        return;
    }
    if (weatherView === 'hfComms') {
        renderHfView(container);
        return;
    }
    if (weatherView === 'satComms') {
        renderSatView(container);
        return;
    }
    if (weatherView === 'aurora') {
        renderAuroraView(container);
        return;
    }
    if (weatherView === 'drag') {
        renderDragView(container);
        return;
    }
    const view = WEATHER_VIEWS[weatherView];
    container.innerHTML = `<h2>${view.title}</h2>
        <p class="go-big">${view.lead}</p>
        <p class="weather-status">Planned. Not yet connected to data.</p>
        <ul class="weather-shows">${view.shows.map((line) => `<li>${line}</li>`).join('')}</ul>`;
}

// The chart files (chartCore.js, chartTime.js, weatherCharts.js) load the first time a view with
// charts is opened, not with the panel, so SUN NOW stays as light as it was.
async function loadWeatherCharts(extra = []) {
    await loadScriptOnce('assets/chartCore.js');
    await loadScriptOnce('assets/chartTime.js');
    await loadScriptOnce('assets/weatherCharts.js');
    for (const file of extra) {
        await loadScriptOnce(file);
    }
}

// SOL DRVR: a NOW band (L1 solar wind; flares and particles beside the flare record; the Sun's long view beside the
// solar cycle) and a PREDICTIVE band (CMEs on the way; the outlook), each opened by a full-width pill bar in the band's
// colour. A chart far down the page is not fetched until the visitor scrolls towards it.
async function renderDriversView(container) {
    const view = WEATHER_VIEWS.drivers;
    container.innerHTML = `<h2>${view.title}</h2><p class="go-big">${view.lead}</p><p class="weather-status">Loading charts...</p>`;
    await loadWeatherCharts();
    if (weatherView !== 'drivers') {
        return;   // the visitor has moved on
    }
    weatherForgetData();
    container.innerHTML = `<h2>${view.title}</h2>
        <p class="go-big">${view.lead}</p>
        ${chartSectionBarHtml({ title: 'NOW: WHAT IS GOING ON', tag: 'NOW', color: WEATHER_BAND_COLOURS.now })}
        <div id="weather-l1"></div>
        <div class="chart-row"><div id="weather-k2"></div><div id="weather-flares"></div></div>
        <div class="chart-row"><div id="weather-long"></div><div id="weather-cycle"></div></div>
        ${chartSectionBarHtml({ title: 'PREDICTIVE: WHAT IS COMING', tag: 'FORECAST', color: WEATHER_BAND_COLOURS.predictive })}
        <div id="weather-cmes"></div>
        <div id="weather-outlook"></div>`;
    const slot = (id) => document.getElementById(id);
    weatherDrawWhenNear(slot('weather-l1'), loadL1Data, weatherGuard((d) => d.speed.length || d.bz.length, l1SolarWindHtml));
    weatherDrawWhenNear(slot('weather-k2'), loadK2, weatherGuard((d) => d.xray.length, k2Html), 360);
    weatherDrawWhenNear(slot('weather-flares'), loadFlareRecord, weatherGuard((d) => d.points.length, flareRecordHtml), 300);
    weatherDrawWhenNear(slot('weather-long'), loadLongView, weatherGuard((d) => d.obs.points.length || d.mean.points.length, longViewHtml), 360);
    weatherDrawWhenNear(slot('weather-cycle'), loadSolarCycle, weatherGuard((d) => d.monthly.points.length, solarCycleHtml), 300);
    weatherDrawWhenNear(slot('weather-cmes'), loadCmeTimeline, cmeTimelineHtml);
    weatherDrawWhenNear(slot('weather-outlook'), loadOutlook, weatherGuard((d) => d.fcF107.length || d.fcAp.length || d.obs.points.length, outlookHtml));
}

// ERTH NOW: a strip of the latest values, then the NOW band (the NOAA scales; the storm strip, the main chart;
// Kp with Dst beside the Kp comparison; auroral power) and the PREDICTIVE band (the Kp forecast grid beside the
// forecast chances; what is arriving). Charts fetch as they come near the screen.
async function renderEarthView(container) {
    const view = WEATHER_VIEWS.earth;
    container.innerHTML = `<h2>${view.title}</h2><p class="go-big">${view.lead}</p><p class="weather-status">Loading charts...</p>`;
    await loadWeatherCharts(['assets/weatherEarth.js']);
    if (weatherView !== 'earth') {
        return;   // the visitor has moved on
    }
    weatherForgetData();
    container.innerHTML = `<h2>${view.title}</h2>
        <p class="go-big">${view.lead}</p>
        <div id="weather-earth-now"></div>
        ${chartSectionBarHtml({ title: 'NOW: WHAT IS GOING ON', tag: 'NOW', color: WEATHER_BAND_COLOURS.now })}
        <div id="weather-scales"></div>
        <div id="weather-storm"></div>
        <div class="chart-row"><div id="weather-kpdst"></div><div id="weather-kpcompare"></div></div>
        <div id="weather-hemi"></div>
        ${chartSectionBarHtml({ title: 'PREDICTIVE: WHAT IS COMING', tag: 'FORECAST', color: WEATHER_BAND_COLOURS.predictive })}
        <div class="chart-row"><div id="weather-kpgrid"></div><div id="weather-chances"></div></div>
        <div id="weather-arriving"></div>`;
    const slot = (id) => document.getElementById(id);
    weatherDrawWhenNear(slot('weather-earth-now'), weatherNow, nowStripFrame, 300);
    weatherDrawWhenNear(slot('weather-scales'), loadScales, scalesHtml, 300);
    weatherDrawWhenNear(slot('weather-storm'), loadStormStrip, weatherGuard((d) => d.xray.length || d.speed.length || d.kp.length, stormStripHtml));
    weatherDrawWhenNear(slot('weather-kpdst'), loadKpDst, weatherGuard((d) => d.kp.points.length, kpDstHtml), 360);
    weatherDrawWhenNear(slot('weather-kpcompare'), loadKpCompare, weatherGuard((d) => d.gfz.points.length, kpCompareHtml), 300);
    weatherDrawWhenNear(slot('weather-hemi'), loadHemiPower, weatherGuard((d) => d.north.length || d.south.length, hemiPowerHtml));
    weatherDrawWhenNear(slot('weather-kpgrid'), loadKpGrid, weatherGuard((d) => d.kp.length, (d, w) => kpGridHtml(d, w, { requiredKp: requiredKpHere() })), 360);
    weatherDrawWhenNear(slot('weather-chances'), loadForecastProbabilities, weatherGuard((d) => d.minor.length || d.proton.length, forecastProbabilitiesHtml), 300);
    weatherDrawWhenNear(slot('weather-arriving'), loadCmeTimeline, (d, w) => cmeTimelineHtml(d, w, {
        title: 'WHAT IS ARRIVING',
        credit: ` <a href="#" onclick="selectWeatherView('drivers'); return false;">The full timeline is under SOL DRVR.</a>` }));
}

// GCR: the NOW band (cosmic rays now, the solar cycle) and a PREDICTIVE bar that says why there is nothing in it.
async function renderGcrView(container) {
    const view = WEATHER_VIEWS.gcr;
    container.innerHTML = `<h2>${view.title}</h2><p class="go-big">${view.lead}</p><p class="weather-status">Loading charts...</p>`;
    await loadWeatherCharts(['assets/weatherGcr.js']);
    if (weatherView !== 'gcr') {
        return;   // the visitor has moved on
    }
    weatherForgetData();
    container.innerHTML = `<h2>${view.title}</h2>
        <p class="go-big">${view.lead}</p>
        ${chartSectionBarHtml({ title: 'NOW: WHAT IS GOING ON', tag: 'NOW', color: WEATHER_BAND_COLOURS.now })}
        <div id="weather-gcr-now"></div>
        <div id="weather-gcr-cycle"></div>
        ${chartSectionBarHtml({ title: 'PREDICTIVE: WHAT IS COMING', tag: 'NONE', color: WEATHER_BAND_COLOURS.predictive })}
        <p class="weather-status">Nothing open forecasts cosmic rays. What does change them is a coronal mass ejection: a dip (a Forbush decrease) follows its shock.
            See <a href="#" onclick="selectWeatherView('drivers'); return false;">CMES ON THE WAY under SOL DRVR</a> for the arrivals expected.</p>`;
    const slot = (id) => document.getElementById(id);
    weatherDrawWhenNear(slot('weather-gcr-now'), loadCosmicRaysNow, weatherGuard((d) => d.oulu.length, cosmicRaysNowHtml));
    weatherDrawWhenNear(slot('weather-gcr-cycle'), loadGcrCycle, weatherGuard((d) => d.neutrons.length, gcrCycleHtml));
}

// HF COMMS: flares and protons with the radio-blackout reading; the absorption status (with the D-RAP world map when it
// matters); your path (foF2 and D-RAP at the visitor's place); the aviation board; the radio outlook (chances beside the
// last hour of the solar wind).
async function renderHfView(container) {
    const view = WEATHER_VIEWS.hfComms;
    container.innerHTML = `<h2>${view.title}</h2><p class="go-big">${view.lead}</p><p class="weather-status">Loading charts...</p>`;
    await loadWeatherCharts(['assets/weatherEarth.js', 'assets/weatherMap.js', 'assets/weatherTec.js', 'assets/weatherHf.js']);
    if (weatherView !== 'hfComms') {
        return;   // the visitor has moved on
    }
    weatherForgetData();
    container.innerHTML = `<h2>${view.title}</h2>
        <p class="go-big">${view.lead}</p>
        ${chartSectionBarHtml({ title: 'NOW: WHAT IS GOING ON', tag: 'NOW', color: WEATHER_BAND_COLOURS.now })}
        <div id="weather-hf-flares"></div>
        <div id="weather-hf-absorption"></div>
        <div id="weather-hf-path"></div>
        <div id="weather-hf-board"></div>
        ${chartSectionBarHtml({ title: 'PREDICTIVE: WHAT IS COMING', tag: 'FORECAST', color: WEATHER_BAND_COLOURS.predictive })}
        <div class="chart-row chart-row-even"><div id="weather-hf-chances"></div><div id="weather-hf-strip"></div></div>`;
    const slot = (id) => document.getElementById(id);
    weatherDrawWhenNear(slot('weather-hf-flares'), loadK2, weatherGuard((d) => d.xray.length,
        (d, w) => k2Html(d, w, { title: 'FLARE FADE-OUT AND RADIATION', tipExtra: hfFlareTip })));
    weatherDrawWhenNear(slot('weather-hf-absorption'), loadAbsorption, hfAbsorptionHtml);
    weatherDrawWhenNear(slot('weather-hf-path'), loadPath, hfPathHtml);
    weatherDrawWhenNear(slot('weather-hf-board'), loadBoard, hfBoardHtml, 300);
    weatherDrawWhenNear(slot('weather-hf-chances'), loadForecastProbabilities, weatherGuard((d) => d.minor.length || d.proton.length,
        (d, w) => forecastProbabilitiesHtml(d, w, { title: 'RADIO OUTLOOK', noG: true })), 300);
    weatherDrawWhenNear(slot('weather-hf-strip'), loadL1Strip, weatherGuard((d) => d.speed.length || d.bz.length, l1StripHtml), 300);
}

// SAT COMMS: the NOW band (the TEC map, the effect by band, TEC at your location) and the PREDICTIVE band (the TEC forecast
// map with your place for five days beneath, the storm-risk light). The maps fetch as they near the screen.
async function renderSatView(container) {
    const view = WEATHER_VIEWS.satComms;
    container.innerHTML = `<h2>${view.title}</h2><p class="go-big">${view.lead}</p><p class="weather-status">Loading charts...</p>`;
    await loadWeatherCharts(['assets/weatherEarth.js', 'assets/weatherMap.js', 'assets/weatherTec.js', 'assets/weatherSat.js']);
    if (weatherView !== 'satComms') {
        return;   // the visitor has moved on
    }
    weatherForgetData();
    container.innerHTML = `<h2>${view.title}</h2>
        <p class="go-big">${view.lead}</p>
        ${chartSectionBarHtml({ title: 'NOW: WHAT IS GOING ON', tag: 'NOW', color: WEATHER_BAND_COLOURS.now })}
        <div id="weather-sat-map"></div>
        <div id="weather-sat-bands"></div>
        <div id="weather-sat-here"></div>
        ${chartSectionBarHtml({ title: 'PREDICTIVE: WHAT IS COMING', tag: 'FORECAST', color: WEATHER_BAND_COLOURS.predictive })}
        <div id="weather-sat-outlook-map"></div>
        <div id="weather-sat-outlook-here"></div>
        <div id="weather-sat-risk"></div>`;
    const slot = (id) => document.getElementById(id);
    weatherDrawWhenNear(slot('weather-sat-map'), loadTecNow, tecNowHtml);
    weatherDrawWhenNear(slot('weather-sat-bands'), loadBandTable, bandTableHtml, 400);
    weatherDrawWhenNear(slot('weather-sat-here'), loadTecLocation, tecLocationHtml);
    weatherDrawWhenNear(slot('weather-sat-outlook-map'), loadTecOutlook, tecOutlookHtml);
    weatherDrawWhenNear(slot('weather-sat-outlook-here'), loadTecOutlookLocation, tecOutlookLocationHtml);
    weatherDrawWhenNear(slot('weather-sat-risk'), loadKpGrid, stormRiskHtml, 300);
}

// AURORAE: the NOW band (the oval on a polar map or globe, your sky tonight, activity) and the PREDICTIVE band (the next hour, the next
// nights: the Kp forecast with the Kp you need outlined, the 27-day recurrence, the Earth-directed CMEs). The GLOBE, N POLE and S POLE
// buttons sit under the text beside the oval map (ovalHtml) and redraw the oval; the globe turns by dragging.
async function renderAuroraView(container) {
    const view = WEATHER_VIEWS.aurora;
    container.innerHTML = `<h2>${view.title}</h2><p class="go-big">${view.lead}</p><p class="weather-status">Loading charts...</p>`;
    await loadWeatherCharts(['assets/weatherEarth.js', 'assets/weatherMap.js', 'assets/weatherAurora.js']);
    if (weatherView !== 'aurora') {
        return;   // the visitor has moved on
    }
    weatherForgetData();
    container.innerHTML = `<h2>${view.title}</h2>
        <p class="go-big">${view.lead}</p>
        ${chartSectionBarHtml({ title: 'NOW: WHAT IS GOING ON', tag: 'NOW', color: WEATHER_BAND_COLOURS.now })}
        <div id="weather-au-oval"></div>
        <div id="weather-au-sky"></div>
        <div id="weather-au-activity"></div>
        ${chartSectionBarHtml({ title: 'PREDICTIVE: WHAT IS COMING', tag: 'FORECAST', color: WEATHER_BAND_COLOURS.predictive })}
        <div id="weather-au-hour"></div>
        <div id="weather-au-grid"></div>
        <div class="chart-row chart-row-even"><div id="weather-au-recur"></div><div id="weather-au-cmes"></div></div>`;
    const slot = (id) => document.getElementById(id);
    weatherDrawWhenNear(slot('weather-au-oval'), loadOval, ovalHtml);
    weatherDrawWhenNear(slot('weather-au-sky'), loadSky, skyHtml);
    weatherDrawWhenNear(slot('weather-au-activity'), loadActivity, weatherGuard((d) => d.north.length || d.south.length || d.kp.points.length, activityHtml));
    weatherDrawWhenNear(slot('weather-au-hour'), loadNextHour, weatherGuard((d) => d.speed.length || d.bz.length, nextHourHtml));
    weatherDrawWhenNear(slot('weather-au-grid'), loadKpGrid, weatherGuard((d) => d.kp.length, (d, w) => kpGridHtml(d, w, { title: 'THE NEXT NIGHTS: KP FORECAST', requiredKp: requiredKpHere() })), 360);
    weatherDrawWhenNear(slot('weather-au-recur'), loadRecurrence, weatherGuard((d) => d.ap.length, recurrenceHtml), 360);
    weatherDrawWhenNear(slot('weather-au-cmes'), loadCmeTimeline, (d, w) => cmeTimelineHtml(d, w, { title: 'EARTH-DIRECTED CMES', earthOnly: true,
        credit: ' <a href="#" onclick="selectWeatherView(\'drivers\'); return false;">The full timeline is under SOL DRVR.</a>' }), 360);
}

// LEO DRAG: the drivers of the upper atmosphere and who is exposed (NOW); what the outlook and the Kp forecast say about the next days
// (PREDICTIVE). The drag index and the decay-rate chart wait for the Space-Track element-set history.
async function renderDragView(container) {
    const view = WEATHER_VIEWS.drag;
    container.innerHTML = `<h2>${view.title}</h2><p class="go-big">${view.lead}</p><p class="weather-status">Loading charts...</p>`;
    await loadWeatherCharts(['assets/weatherEarth.js', 'assets/weatherDrag.js']);
    if (weatherView !== 'drag') {
        return;   // the visitor has moved on
    }
    weatherForgetData();
    container.innerHTML = `<h2>${view.title}</h2>
        <p class="go-big">${view.lead}</p>
        ${chartSectionBarHtml({ title: 'NOW: WHAT IS GOING ON', tag: 'NOW', color: WEATHER_BAND_COLOURS.now })}
        <div id="weather-drag-air"></div>
        <div id="weather-drag-exposed"></div>
        ${chartSectionBarHtml({ title: 'PREDICTIVE: WHAT IS COMING', tag: 'FORECAST', color: WEATHER_BAND_COLOURS.predictive })}
        <div class="chart-row"><div id="weather-drag-outlook"></div><div id="weather-drag-kp"></div></div>`;
    const slot = (id) => document.getElementById(id);
    weatherDrawWhenNear(slot('weather-drag-air'), loadAtmosphere, weatherGuard((d) => d.obs.points.length || d.kp.length, atmosphereHtml));
    weatherDrawWhenNear(slot('weather-drag-exposed'), loadExposure, weatherGuard((d) => d.rows.length, exposureHtml));
    weatherDrawWhenNear(slot('weather-drag-outlook'), loadOutlook, weatherGuard((d) => d.fcF107.length || d.fcAp.length || d.obs.points.length,
        (d, w) => outlookHtml(d, w, { title: 'WHAT DRAG DOES NEXT' })), 360);
    weatherDrawWhenNear(slot('weather-drag-kp'), loadKpGrid, weatherGuard((d) => d.kp.length, (d, w) => kpGridHtml(d, w, { title: 'THE KP FORECAST' })), 300);
}

// The SVG charts are drawn to the width of their slot: redraw when the window is resized (debounced).
let weatherResizeTimer = null;
window.addEventListener('resize', () => {
    clearTimeout(weatherResizeTimer);
    weatherResizeTimer = setTimeout(() => {
        const view = document.getElementById('weather-view');
        if (view && typeof weatherRedrawAll === 'function') {
            weatherRedrawAll(view);
        }
    }, 300);
});

function selectWeatherView(key) {
    weatherView = key;
    renderWeatherView();
}

function weatherViewButton(key, label, color) {
    return { label, color, isSelected: () => weatherView === key, onClick: () => selectWeatherView(key) };
}

registerPanelControls('sw-drivers', {
    defaultAreaMode: 'custom',
    renderDefaultArea: renderWeatherDefaultArea,
    buttons: weatherViewButtons(),
});

function weatherViewButtons() {
    return [
        // Two rows of five, filled row by row.
        weatherViewButton('sun', 'SUN NOW', 'var(--sunflower)'),
        weatherViewButton('drivers', 'SOL DRVR', 'var(--golden-orange)'),
        weatherViewButton('earth', 'ERTH NOW', 'var(--bluey)'),
        weatherViewButton('gcr', 'GCR', 'var(--magenta)'),
        { label: 'USR LOCN', color: 'var(--peach)', onClick: () => toggleUserLocationForm(renderWeatherDefaultArea) },
        weatherViewButton('drag', 'LEO DRAG', 'var(--lilac)'),
        weatherViewButton('satComms', 'SAT COMM', 'var(--ice)'),
        weatherViewButton('hfComms', 'HF COMM', 'var(--almond)'),
        weatherViewButton('aurora', 'AURORAE', 'var(--african-violet)'),
        weatherViewButton('defs', 'DEFS', 'var(--violet-creme)'),
    ];
}
