/**
 * LCARS SYSTEM CORE & SPACE NEWS ENGINE
 * Consolidates layout interactions, navigation subsystems, and automated SQLite reporting.
 */

/* ==========================================================================
   SECTION 1: LAYOUT & INTERACTION CORE (Original Template Logic)
   ========================================================================== */

document.addEventListener("touchstart", function() {}, false);

// .bottom-fixed-group (holding #topBtn and the ACKNOWLEDGMENTS button,
// .panel-ack) is always visible via CSS now, rather than scroll-triggered --
// the sidebar's section-button list is short enough that the page often has
// no scrollable overflow at all, which would leave a scroll-triggered group
// permanently stuck hidden.

function topFunction() {
    document.body.scrollTop = 0;
    document.documentElement.scrollTop = 0;
}

function playSoundAndRedirect(audioId, url) {
    // Audio elements disabled by default in template framework
    window.location.href = url;
}

function goToAnchor(anchorId) {
    window.location.hash = anchorId;
}

// Accordion drop-down logic
var acc = document.getElementsByClassName("accordion");
for (var i = 0; i < acc.length; i++) {
    acc[i].addEventListener("click", function() {
        this.classList.toggle("active");
        var accordionContent = this.nextElementSibling;
        if (accordionContent.style.maxHeight){
            accordionContent.style.maxHeight = null;
        } else {
            accordionContent.style.maxHeight = accordionContent.scrollHeight + "px";
        } 
    });
}

// panel-11 (EO, the last nav button) has its own border-bottom and
// .panel-ack has its own border-top, so that a tall payload -- which
// pushes .bottom-fixed-group away from the button list via
// margin-top:auto -- shows two independent separator lines with the
// sidebar's red background between them. When there's no leftover space
// (a short payload), those two elements end up directly touching, which
// would stack both borders into a doubled ~8px line instead of a
// standard single one. CSS can't detect "these two happen to be
// adjacent," so this measures the actual gap and toggles panel-11's
// border-bottom off for exactly that case.
function updateEoAckGap() {
    const lastNav = document.querySelector('.panel-11');
    const group = document.querySelector('.bottom-fixed-group');
    if (!lastNav || !group) return;
    const gap = group.getBoundingClientRect().top - lastNav.getBoundingClientRect().bottom;
    lastNav.classList.toggle('no-gap-border', gap < 1);
}

window.addEventListener('load', updateEoAckGap);
window.addEventListener('resize', updateEoAckGap);

// Tracks whether the top control area (.data-cascade-button-group) is
// currently showing a section's label/buttons rather than the default news
// ticker, so the resize handler in Section 6 knows not to overwrite it.
let controlAreaSectionActive = false;

// URL of the article currently shown in the news detail view, read by the
// bar-9 "READ IN FULL" button. Only meaningful while that button is visible.
let currentNewsArticleUrl = null;

// ASSET_TYPES/asset-type-visibility storage/assetTypeVisibility now live
// in assets/groundSegmentPanel.js, alongside the rest of the
// infrastructure panel's own code.

// sectionId -> { buttons, defaultAreaMode, renderDefaultArea? }, filled by
// each panel module at load time via registerPanelControls() below. Every
// panel (infrastructure, on-orbit, and any future one) is now handled
// generically by updateControlArea() -- see that function -- driven
// entirely by what's registered here, with no per-section knowledge
// baked into lcars.js itself.
const panelControlRegistry = {};

// Panels call this once, at load time, to declare their own control-area
// buttons instead of updateControlArea() needing a hardcoded branch per
// section (the pattern the old CONTROL_AREA_BUTTON_LABELS/
// ON_ORBIT_BUTTON_COLORS/CONTROL_AREA_ASSET_KEYS used, before every panel
// migrated to this).
//
// config.buttons: [{ label, color, shape?, getText?, onClick? }]
//   - shape is only set by panels whose #default area also renders as a
//     colour/shape key grid (defaultAreaMode: 'key') -- carried on the
//     same descriptor as the nav button so a label/colour/shape entry can
//     never drift apart the way the old two-parallel-structures approach
//     (matched only by label-text equality) could.
//   - getText(): () => string, re-run after every click for dynamic
//     ON/OFF-style labels; falls back to the static `label`.
//   - onClick(): may be async; buttons with none render inert.
// config.defaultAreaMode: 'key' (renders #default as the shape/colour key
//   grid from `buttons`) | 'custom' (calls config.renderDefaultArea()) |
//   undefined (plain label div).
function registerPanelControls(sectionId, config) {
    panelControlRegistry[sectionId] = config;
}

// Builds the small shape glyph next to each key label. Circle/square/
// triangle/triangle-down are plain CSS shapes coloured via background (or
// border, for the triangles); asterisk is a text glyph since there's no
// clean pure-CSS asterisk shape.
function renderKeyShape(shape, color) {
    if (shape === 'asterisk') {
        return `<span class="key-shape key-shape-asterisk" style="color:${color}">&#10038;</span>`;
    }
    if (shape === 'triangle') {
        return `<span class="key-shape key-shape-triangle" style="border-bottom-color:${color}"></span>`;
    }
    if (shape === 'triangle-down') {
        return `<span class="key-shape key-shape-triangle-down" style="border-top-color:${color}"></span>`;
    }
    return `<span class="key-shape key-shape-${shape}" style="background-color:${color}"></span>`;
}

// Major navigation section toggle (SW-DRIVERS, SW-FCST, etc.)
function showSection(sectionId, label) {
    const sections = document.querySelectorAll('main [data-section]');
    sections.forEach(function (section) {
        section.style.display = (section.dataset.section === sectionId) ? 'block' : 'none';
    });

    const defaultContent = document.getElementById('default-content');
    if (defaultContent) {
        defaultContent.style.display = 'none';
    }

    const bannerSection = document.getElementById('banner-section');
    if (bannerSection && label) {
        bannerSection.textContent = label;
    }

    if (label) {
        updateControlArea(sectionId, label);
    }

    // The news detail-view back/read-full buttons (bar-8/bar-9) are only
    // meaningful while viewing a news article; hide them on every section
    // switch and let showNewsArticleDetail() re-show them when relevant.
    const newsBackBtn = document.getElementById('news-back-btn');
    if (newsBackBtn) {
        newsBackBtn.classList.add('is-hidden');
    }
    const newsReadFullBtn = document.getElementById('news-read-full-btn');
    if (newsReadFullBtn) {
        newsReadFullBtn.classList.add('is-hidden');
    }

    // The map zoom buttons (bar-7/bar-8a) are only meaningful while a
    // Leaflet map is showing; shown for those sections, hidden everywhere
    // else. zoomMapIn()/zoomMapOut() operate on `currentMap`, kept in sync
    // with whichever section's map is on screen by initInfrastructureMap()/
    // initOnOrbitMap().
    ['map-zoom-in-btn', 'map-zoom-out-btn'].forEach((id) => {
        const btn = document.getElementById(id);
        if (btn) {
            btn.classList.toggle('is-hidden', !['infrastructure', 'on-orbit', 'eo', 'gs-ops'].includes(sectionId));
        }
    });

    updateEoAckGap();
}

// Repopulates the top control area to match the section just opened: the
// cascade wrapper (normally the news ticker) becomes either a key grid, a
// panel-specific custom render, or a plain label, and the nav buttons
// become per-section buttons -- all driven entirely by whatever that
// section registered via registerPanelControls(), or a plain 1-6
// placeholder for a section that hasn't registered anything (news,
// weather, and any future panel not yet built). Always wraps to exactly
// two rows -- column count is derived from however many buttons this
// section needs, rather than a fixed 3-wide grid, so a 9-button section
// (5+4) and a 6-button section (3+3) both still land on two rows.
// Renders just the nav button strip, independently of the #default
// wrapper's own content -- split out of updateControlArea() so a panel
// can force its button *set* to rebuild (not just refresh existing
// buttons' labels, which refreshAllLabels() below already handles) when
// something other than a section change alters which buttons should be
// showing -- e.g. DEL OBJ's view adding DEL SELECTION/CLEAR while it's
// open. Calling the full updateControlArea() for that would also re-run
// the panel's renderDefaultArea(), which for on-orbit is
// fetchAndRenderOrbitalObjectsList() -- exactly the function that resets
// DEL OBJ's own view state, so it would immediately undo the thing this
// was meant to enable. This function touches only the nav strip.
//
// panel.buttons may be a plain array (every other panel today) or a
// function returning one (on-orbit, so the set can depend on
// delObjViewActive) -- evaluated fresh on every call either way, so a
// function-valued buttons list is never stale.
function renderControlAreaButtons(sectionId) {
    const panel = panelControlRegistry[sectionId];
    const nav = document.querySelector('.data-cascade-button-group nav');
    const groupsArea = document.getElementById('control-area-groups');
    if (!nav) {
        return;
    }

    nav.classList.add('nav-grid-dynamic');
    const buttons = panel ? (typeof panel.buttons === 'function' ? panel.buttons() : panel.buttons) : null;
    // Only ungrouped buttons actually live in nav's own flex-wrap row (see
    // below), so its column math must only count those -- grouped ones
    // render into #control-area-groups instead, a true DOM sibling of nav,
    // not one of its flex items. Counting every button here regardless of
    // grouping was tried first and produced a real layout bug: a button
    // that's twice the height of its row-mates (two stacked, one slot)
    // leaves dead space beside it that the fixed-height siblings don't
    // stretch to fill, which reads as a phantom extra row even though the
    // wrap math itself was technically correct.
    const ungroupedCount = buttons ? buttons.filter((info) => !info.group).length : 6;
    nav.style.setProperty('--nav-columns', Math.ceil(ungroupedCount / 2));
    nav.innerHTML = '';
    if (groupsArea) {
        groupsArea.innerHTML = '';
    }

    if (buttons) {
        // Collected up front so every button's label can be refreshed
        // after ANY button's click, not just the one that was clicked --
        // a handler can have side effects on a sibling button's state
        // (e.g. GRD TRCK turning footprints off also changes what SHW
        // FOOT's own label should read), and a button whose own label
        // depends on state it doesn't own has no other way to find out
        // it needs to redraw itself.
        const setLabelFns = [];
        const refreshAllLabels = () => setLabelFns.forEach((fn) => fn());

        // Buttons sharing the same info.group string get wrapped together
        // in one shared <div> (.control-area-button-group, stacked
        // vertically via CSS) appended to #control-area-groups -- a
        // sibling of nav, not a child of it, specifically so a tall
        // grouped stack never has to coexist inside the same flex-wrap
        // row as nav's own fixed-height individual buttons. Optional:
        // most buttons have no group and append to nav as before.
        // groupContainers keyed by group name so >2 buttons could share
        // one group too, not just pairs.
        const groupContainers = new Map();

        buttons.forEach((info) => {
            const button = document.createElement('button');
            if (info.color) {
                button.style.backgroundColor = info.color;
            }
            const setLabel = () => {
                button.textContent = info.getText ? info.getText() : info.label;
            };
            setLabelFns.push(setLabel);
            setLabel();
            if (info.onClick) {
                button.addEventListener('click', async () => {
                    await info.onClick();
                    refreshAllLabels();
                });
            }

            if (info.group && groupsArea) {
                let container = groupContainers.get(info.group);
                if (!container) {
                    container = document.createElement('div');
                    container.className = 'control-area-button-group';
                    groupContainers.set(info.group, container);
                    groupsArea.appendChild(container);
                }
                container.appendChild(button);
            } else {
                nav.appendChild(button);
            }
        });
    } else {
        ['1', '2', '3', '4', '5', '6'].forEach((text) => {
            const button = document.createElement('button');
            button.textContent = text;
            nav.appendChild(button);
        });
    }
}

function updateControlArea(sectionId, label) {
    const panel = panelControlRegistry[sectionId];

    const wrapper = document.getElementById('default');
    if (wrapper) {
        if (panel && panel.defaultAreaMode === 'key') {
            wrapper.innerHTML = `<div class="control-area-key">${panel.buttons.map(({ label: keyLabel, color, shape }) => `
                <div class="control-area-key-row">
                    <span>${keyLabel}</span>
                    ${renderKeyShape(shape, color)}
                </div>`).join('')}</div>`;
        } else if (panel && panel.defaultAreaMode === 'custom') {
            panel.renderDefaultArea();
        } else {
            wrapper.innerHTML = `<div class="control-area-label">${label}</div>`;
        }
    }

    renderControlAreaButtons(sectionId);

    controlAreaSectionActive = true;
}

// Wired to the GRND SGMNT left-menu button, replacing the old three-
// statement onclick chain (showSection(); initInfrastructureMap();). Both
// files must be loaded -- and, critically, groundSegmentPanel.js's
// registerPanelControls() call must have run -- BEFORE showSection() is
// called, since showSection() calls updateControlArea() synchronously.
// Loading only inside initInfrastructureMap() itself would mean the
// FIRST click on this button renders the '1'..'6' placeholder fallback
// (registry not populated yet), not the real buttons.
//
// Promise.all (parallel, not sequential) is safe and preferable here:
// neither file calls into the other at parse time, only from inside
// function bodies resolved at click time, by which point both are
// guaranteed loaded -- serialising would cost an extra round trip for no
// benefit on this project's high-latency target. loadScriptOnce()'s own
// dedupe makes re-opening this section later in the same session a cheap
// synchronous no-op.
async function openInfrastructureSection() {
    await Promise.all([
        loadScriptOnce('assets/mapCore.js'),
        loadScriptOnce('assets/groundSegmentPanel.js'),
    ]);
    showSection('infrastructure', 'GRND SGMNT');
    initInfrastructureMap();
}

// Wired to the ON-ORBIT left-menu button, replacing the old three-
// statement onclick chain (showSection(); initOnOrbitMap();
// detectObserverLocation();). Same load-before-show reasoning as
// openInfrastructureSection() above -- onOrbitPanel.js's
// registerPanelControls() call must have run before showSection() calls
// updateControlArea(), or the first click renders the placeholder
// fallback instead of the real buttons.
async function openOnOrbitSection() {
    await Promise.all([
        loadScriptOnce('assets/mapCore.js'),
        loadScriptOnce('assets/onOrbitPanel.js'),
    ]);
    showSection('on-orbit', 'ON ORBIT');
    initOnOrbitMap();
    detectObserverLocation();
}

// Wired to the EO left-menu button. Same load-before-show reasoning as
// openOnOrbitSection() -- the panel module's registerPanelControls() call
// must have run before showSection() -> updateControlArea() looks the
// section up, or the first click falls back to the 1..6 placeholder
// buttons. mapCore.js / onOrbitPanel.js / locationMapPanel.js have no
// load-order deps among themselves (they only call into each other from
// click-time handlers), but eoPanel.js calls registerLocationMapPanel()
// at parse time, so it must load after locationMapPanel.js -- hence the
// separate await.
async function openEoSection() {
    await Promise.all([
        loadScriptOnce('assets/mapCore.js'),
        loadScriptOnce('assets/onOrbitPanel.js'),
        loadScriptOnce('assets/locationMapPanel.js'),
    ]);
    await loadScriptOnce('assets/eoPanel.js');
    showSection('eo', 'EO');
    initEoMap();
}

// Wired to the GS OPS left-menu button. Identical shape to
// openEoSection() -- ground-station operations reuses the exact same
// location-map panel (assets/locationMapPanel.js), just a different
// section id, container and first-button label (see gsOpsPanel.js).
async function openGsOpsSection() {
    await Promise.all([
        loadScriptOnce('assets/mapCore.js'),
        loadScriptOnce('assets/onOrbitPanel.js'),
        loadScriptOnce('assets/locationMapPanel.js'),
    ]);
    await loadScriptOnce('assets/gsOpsPanel.js');
    showSection('gs-ops', 'GS OPS');
    initGsOpsMap();
}

// Entry point for the NEWS menu button and the news filter buttons:
// reveals the news section and renders the full article table (separate
// from the header marquee ticker) -- every article for 01-ALL (no topic),
// or only those tagged with `topic` for 02-10 (see scripts/topicRules.py).
function showNewsSection(topic = null, topicLabel = null) {
    showSection('news', topicLabel ? `NEWS - ${topicLabel}` : 'NEWS');
    fetchAndRenderFullNewsTable(topic);
}

// News filter buttons, laid out as two rows of five. Colours follow the
// project's LCARS rules (see the panel-3..11 comment in classic.css): no
// red (reserved for alerts) and no gold (reserved for ACKNOWLEDGMENTS),
// and warm/cool alternate in a checkerboard so no button sits next to a
// similar hue either across a row or down a column. Each topic key must
// match one in scripts/topicRules.py's TOPIC_RULES. Shared by the filter
// buttons and the control panel histogram, so a topic's bar is always the
// same colour as its button.
const NEWS_TOPICS = [
    { number: '02', topic: 'launch', label: 'LAUNCH', color: 'var(--orange)' },
    { number: '03', topic: 'groundSegment', label: 'GRND SGMT', color: 'var(--sky)' },
    { number: '04', topic: 'deepSpace', label: 'DEEP SPACE', color: 'var(--butterscotch)' },
    { number: '05', topic: 'finance', label: 'FINANCE', color: 'var(--bluey)' },
    { number: '06', topic: 'orgs', label: 'ORGS', color: 'var(--sunflower)' },
    { number: '07', topic: 'onOrbit', label: 'ON-ORBIT', color: 'var(--ice)' },
    { number: '08', topic: 'defence', label: 'DEFENCE', color: 'var(--peach)' },
    { number: '09', topic: 'sky', label: 'SKY', color: 'var(--moonlit-violet)' },
    { number: '10', topic: 'eo', label: 'EO', color: 'var(--lima-bean)' },
];

// Per-topic article totals from api/news/topic-counts (stored in the DB by
// scripts/tagNews.py on every refresh) -- fetched once per page load, then
// reused every time the news section reopens.
let newsTopicCountsPromise = null;

function fetchNewsTopicCounts() {
    if (!newsTopicCountsPromise) {
        newsTopicCountsPromise = fetch('api/news/topic-counts')
            .then((response) => {
                if (!response.ok) {
                    throw new Error(`HTTP error ${response.status}`);
                }
                return response.json();
            })
            .catch((error) => {
                console.error('Could not load news topic counts:', error);
                newsTopicCountsPromise = null; // let the next visit retry
                return { counts: {} };
            });
    }
    return newsTopicCountsPromise;
}

// A round axis maximum at or above `maxCount`, and a tick step giving
// roughly four intervals -- step is 1, 2 or 5 times a power of ten (141
// -> step 50, top 150), and never below 1, since counts are whole articles.
function niceHistogramAxis(maxCount) {
    const roughStep = maxCount / 4;
    const magnitude = 10 ** Math.floor(Math.log10(roughStep));
    const step = Math.max(1, [1, 2, 5, 10].map((m) => m * magnitude).find((s) => s >= roughStep));
    return { step, top: Math.ceil(maxCount / step) * step };
}

// LCARS-style horizontal histogram in the control panel, one bar per
// filter button in button order, each in its button's colour, read
// against a horizontal axis with a rounded scale along the bottom. Left
// blank if there are no counts yet.
async function renderNewsTopicHistogram() {
    const wrapper = document.getElementById('default');
    if (!wrapper) {
        return;
    }
    wrapper.innerHTML = '';

    const { counts = {} } = await fetchNewsTopicCounts();

    // The fetch may resolve after the user has moved to another section,
    // whose own content now owns #default.
    const newsSection = document.querySelector('main [data-section="news"]');
    if (!newsSection || newsSection.style.display === 'none') {
        return;
    }

    const maxCount = Math.max(0, ...NEWS_TOPICS.map(({ topic }) => counts[topic] || 0));
    if (maxCount === 0) {
        return;
    }

    const { step, top } = niceHistogramAxis(maxCount);
    const ticks = [];
    for (let value = 0; value <= top; value += step) {
        ticks.push(value);
    }

    const barRows = NEWS_TOPICS.map(({ topic, label, color }) => {
        const count = counts[topic] || 0;
        return `
            <div class="news-histogram-label">${label}</div>
            <div class="news-histogram-track" title="${count}">
                <div class="news-histogram-bar" style="width:${(count / top) * 100}%; background-color:${color}"></div>
            </div>`;
    }).join('');

    const axisRow = `
        <div></div>
        <div class="news-histogram-axis">${ticks.map((value) => `
            <span class="news-histogram-tick" style="left:${(value / top) * 100}%">${value}</span>`).join('')}
        </div>`;

    wrapper.innerHTML = `<div class="news-histogram">${barRows}${axisRow}</div>`;
}

registerPanelControls('news', {
    defaultAreaMode: 'custom',
    renderDefaultArea: renderNewsTopicHistogram,
    buttons: [
        { label: '01-ALL', color: 'var(--african-violet)', onClick: () => showNewsSection() },
        ...NEWS_TOPICS.map(({ number, topic, label, color }) => ({
            label: `${number}-${label}`,
            color,
            onClick: () => showNewsSection(topic, label),
        })),
    ],
});

/* ==========================================================================
   SECTION 2: SPACE WEATHER DATA SUBSYSTEM (NASA DONKI Integration)
   ========================================================================== */

const startDate = "2024-01-01";
const endDate = "2024-01-08";
const NASAapiKey = "DEMO_KEY"; // Replace with your actual NASA API Key if needed
const url = `https://api.nasa.gov/DONKI/GST?startDate=${startDate}&endDate=${endDate}&api_key=${NASAapiKey}`;

async function fetchAndSortGST() {
    try {
        const response = await fetch(url);
        if (!response.ok) {
            throw new Error(`HTTP error! Status: ${response.status}`);
        }
        const data = await response.json();
        
        // Sort the array chronologically by the 'startTime' property (ascending)
        data.sort((a, b) => new Date(a.startTime) - new Date(b.startTime));
        
        console.log("NASA GST Data Fetched Successfully:");
        console.log(data);
    } catch (error) {
        console.error("Error fetching or processing NASA data:", error);
    }
}

/* ==========================================================================
   SECTION 3: SPACE NEWS FROM RSS FEEDS SCRAPED USING A NODE.JS CRAWLER AND STORED IN SQLite 
   ========================================================================== */

let globalNewsData = [];

// Helper to translate database dates into clean 'MMM-DD HH:MM' arrays
function formatNewsDate(dateStr) {
    const date = new Date(dateStr);
    if (isNaN(date.getTime())) return "00-00 00:00";
    
    const months = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"];
    const month = months[date.getMonth()];
    const day = String(date.getDate()).padStart(2, '0');
    const hours = String(date.getHours()).padStart(2, '0');
    const minutes = String(date.getMinutes()).padStart(2, '0');
    
    return `${month}-${day} ${hours}:${minutes}`;
}

// SQL's ORDER BY published_date DESC only does a plain string comparison
// -- published_date is stored as raw RFC 2822 text (e.g. "Wed, 29 Jul
// 2026 23:15:30 +0000"), which starts with the weekday name, so sorting
// it as a string scrambles true chronological order across day/month
// boundaries (e.g. "Thu, 30 Jul" sorts before "Wed, 29 Jul" alphabetically,
// even though Thursday is later -- confirmed live against the real DB).
// Re-sorting here by an actually-parsed Date is what makes "most recent
// first" true rather than approximate. Shared by both fetchAndRenderNews()
// and fetchAndRenderFullNewsTable(), so the ticker and the full table can
// never disagree on ordering.
function sortNewsByDateDesc(items) {
    return items.slice().sort((a, b) => new Date(b.published_date || b.date) - new Date(a.published_date || a.date));
}

// Fetch news records out of the SQLite backend pipeline
async function fetchAndRenderNews() {
    try {
        // Only fetch if we don’t already have data
        if (!Array.isArray(globalNewsData) || globalNewsData.length === 0) {
            
            const response = await fetch('api/news?limit=50');

            if (!response.ok) {
                throw new Error(`HTTP error ${response.status}`);
            }

            const result = await response.json();

            // Handle different API shapes safely
            globalNewsData = Array.isArray(result)
                ? result
                : result.data || result.rows || result.news || [];

            // Final safety fallback
            if (!Array.isArray(globalNewsData)) {
                console.error('Invalid data format:', result);
                globalNewsData = [];
            }

            globalNewsData = sortNewsByDateDesc(globalNewsData);
        }

        // Always safe to call now
        renderNewsTable(globalNewsData);

    } catch (error) {
        console.error("Error fetching news from SQLite DB:", error);

        const wrapper = document.getElementById('default');
        if (wrapper) {
            wrapper.innerHTML =
                `<div style="color: var(--red); padding: 10px; font-weight: bold;">
                    ERR: DATABASE_CONN_FAIL
                 </div>`;
        }
    }
}

// Calculate precise element viewport space and fill rows down to the window fold
function renderNewsTable(newsItems) {
    const wrapper = document.getElementById('default');
    if (!wrapper) return;
    
    wrapper.innerHTML = ''; 
    
    const table = document.createElement('table');
    table.style.width = '100%';
    table.style.borderCollapse = 'collapse';
    table.style.fontFamily = 'Arial, Helvetica, sans-serif';
    table.style.fontSize = '12px';
    table.style.textTransform = 'uppercase'; 
    
    // FIXED HEIGHT MATRIX: Matches the 204px CSS header wrapper boundary
    const rowHeight = 26; 
    const maxRows = 7; 
    const itemsToShow = newsItems.slice(0, maxRows);
    
    itemsToShow.forEach((item, index) => {
        const tr = document.createElement('tr');
        tr.style.height = `${rowHeight}px`;
        tr.style.borderBottom = '1px solid #111';
        
        // Column 1: Datetime Stamp (LCARS CSS Gold Variable remains anchored)
        const tdDate = document.createElement('td');
        tdDate.style.color = 'var(--gold)'; 
        tdDate.style.padding = '2px 12px 2px 4px';
        tdDate.style.whiteSpace = 'nowrap';
        tdDate.textContent = formatNewsDate(item.published_date || item.date);
        
        // Column 2: Article Title String (Color handled via CSS animation)
        const tdTitle = document.createElement('td');
        tdTitle.style.padding = '2px 12px';
        tdTitle.style.width = '100%';
        tdTitle.style.maxWidth = '0';
        tdTitle.style.overflow = 'hidden';
        tdTitle.style.textOverflow = 'ellipsis';
        tdTitle.style.whiteSpace = 'nowrap';
        tdTitle.textContent = item.title;
        
        // RESTORE ANIMATION: Assign looping animation rules (dc-row-1 to dc-row-7)
        // This links the titles directly into the native @keyframes system inside classic.css
        const animationClass = `dc-row-${(index % 7) + 1}`;
        tdTitle.classList.add(animationClass);
        
        tr.appendChild(tdDate);
        tr.appendChild(tdTitle);
        table.appendChild(tr);
    });
    
    wrapper.appendChild(table);
}

/* ==========================================================================
   SECTION 3b: FULL NEWS TABLE (Detail View — triggered by 01-ALL button)
   ========================================================================== */

// Bumped on every call to fetchAndRenderFullNewsTable(), so a slow
// response for an earlier filter button can't overwrite a later one's.
let fullNewsTableRequestID = 0;

// Unfiltered (topic null): reuses globalNewsData (populated by
// fetchAndRenderNews if not already loaded) and renders every row, not just
// the 7-row marquee subset. Filtered: always fetches that topic fresh --
// globalNewsData is the unfiltered set the ticker shares, so filtered rows
// must never be cached in it.
async function fetchAndRenderFullNewsTable(topic = null) {
    const wrapper = document.getElementById('news-table-wrapper');
    if (!wrapper) return;

    const requestID = ++fullNewsTableRequestID;

    try {
        if (topic) {
            const response = await fetch(`api/news?limit=50&topic=${encodeURIComponent(topic)}`);
            if (!response.ok) {
                throw new Error(`HTTP error ${response.status}`);
            }
            const result = await response.json();
            if (requestID !== fullNewsTableRequestID) return;
            const topicItems = sortNewsByDateDesc(Array.isArray(result) ? result : []);
            renderFullNewsTable(topicItems);
            if (topicItems.length === 0) {
                wrapper.insertAdjacentHTML('beforeend',
                    '<div class="news-no-articles">NO ARTICLES</div>');
            }
            updateEoAckGap();
            return;
        }

        if (!Array.isArray(globalNewsData) || globalNewsData.length === 0) {
            const response = await fetch('api/news?limit=50');
            if (!response.ok) {
                throw new Error(`HTTP error ${response.status}`);
            }
            const result = await response.json();
            globalNewsData = Array.isArray(result)
                ? result
                : result.data || result.rows || result.news || [];
            if (!Array.isArray(globalNewsData)) {
                console.error('Invalid data format:', result);
                globalNewsData = [];
            }

            globalNewsData = sortNewsByDateDesc(globalNewsData);
        }

        if (requestID !== fullNewsTableRequestID) return;
        renderFullNewsTable(globalNewsData);

    } catch (error) {
        if (requestID !== fullNewsTableRequestID) return;
        console.error("Error fetching news for full table view:", error);
        wrapper.innerHTML =
            `<div style="color: var(--red); padding: 10px; font-weight: bold;">
                ERR: DATABASE_CONN_FAIL
             </div>`;
    }

    // The table (or error message) only exists in the DOM from this point --
    // re-check the EO/ACK gap now, since showSection()'s earlier check ran
    // before this async fetch resolved, while the payload was still short.
    updateEoAckGap();
}

// Renders date / title (~75% width) / source columns, each row opening the
// article's detail view in place (see showNewsArticleDetail()) rather than
// leaving the app. Field names guessed defensively (title/url/source aren't
// fully confirmed in the API response shape) — adjust if your /api/news
// payload differs.
function renderFullNewsTable(newsItems) {
    const wrapper = document.getElementById('news-table-wrapper');
    if (!wrapper) return;

    // Always resets to "showing the list" -- covers both first render and
    // the back button's return from the detail view.
    const detailWrapper = document.getElementById('news-detail-wrapper');
    if (detailWrapper) {
        detailWrapper.style.display = 'none';
    }
    const backBtn = document.getElementById('news-back-btn');
    if (backBtn) {
        backBtn.classList.add('is-hidden');
    }
    const readFullBtn = document.getElementById('news-read-full-btn');
    if (readFullBtn) {
        readFullBtn.classList.add('is-hidden');
    }
    wrapper.style.display = 'block';

    wrapper.innerHTML = '';

    const table = document.createElement('table');
    table.className = 'news-full-table';

    const thead = document.createElement('thead');
    thead.innerHTML = `
        <tr>
            <th class="news-col-date">DATE</th>
            <th class="news-col-title">TITLE</th>
            <th class="news-col-source">SOURCE</th>
        </tr>`;
    table.appendChild(thead);

    const tbody = document.createElement('tbody');

    newsItems.forEach((item) => {
        const articleUrl = item.url || item.link || item.article_url || '#';
        const source = item.source || item.source_name || item.feed || '—';

        const tr = document.createElement('tr');

        const tdDate = document.createElement('td');
        tdDate.className = 'news-col-date';
        tdDate.textContent = formatNewsDate(item.published_date || item.date);

        const tdTitle = document.createElement('td');
        tdTitle.className = 'news-col-title';
        const titleLink = document.createElement('a');
        titleLink.href = '#';
        titleLink.textContent = item.title || '(untitled)';
        titleLink.addEventListener('click', (e) => {
            e.preventDefault();
            showNewsArticleDetail(item);
        });
        tdTitle.appendChild(titleLink);

        const tdSource = document.createElement('td');
        tdSource.className = 'news-col-source';
        tdSource.textContent = source;

        tr.appendChild(tdDate);
        tr.appendChild(tdTitle);
        tr.appendChild(tdSource);

        // Whole row opens the detail view, not just the title cell.
        tr.style.cursor = 'pointer';
        tr.addEventListener('click', () => {
            showNewsArticleDetail(item);
        });

        tbody.appendChild(tr);
    });

    table.appendChild(tbody);
    wrapper.appendChild(table);
}

// Swaps the news list for a detail view of one article, in place within
// the news data-section, and reveals the bar-8 back button. Built with DOM
// methods rather than innerHTML for the article-derived fields, since news
// content comes from third-party RSS feeds and must be treated as
// untrusted text (see funcReqts_0.2.docx's XSS-sanitisation requirement).
function showNewsArticleDetail(item) {
    const tableWrapper = document.getElementById('news-table-wrapper');
    const detailWrapper = document.getElementById('news-detail-wrapper');
    const backBtn = document.getElementById('news-back-btn');
    const readFullBtn = document.getElementById('news-read-full-btn');
    if (!detailWrapper) return;

    const articleUrl = item.url || item.link || item.article_url || '#';
    const source = item.source || item.source_name || item.feed || '—';
    currentNewsArticleUrl = articleUrl;

    detailWrapper.innerHTML = '';

    const crumb = document.createElement('div');
    crumb.className = 'news-detail-crumb';
    crumb.textContent = 'NEWS > ARTICLE DETAIL';

    const title = document.createElement('h2');
    title.className = 'news-detail-title';
    title.textContent = item.title || '(untitled)';

    const meta = document.createElement('div');
    meta.className = 'news-detail-meta';
    const metaSource = document.createElement('span');
    metaSource.textContent = `SOURCE: ${source}`;
    const metaDate = document.createElement('span');
    metaDate.textContent = `PUBLISHED: ${formatNewsDate(item.published_date || item.date)}`;
    meta.appendChild(metaSource);
    meta.appendChild(metaDate);

    const note = document.createElement('p');
    note.className = 'go-big';
    note.textContent = item.description
        || "No summary available from the feed for this article — full article text isn't stored locally either.";

    const link = document.createElement('a');
    link.className = 'news-detail-link';
    link.href = articleUrl;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    link.textContent = 'Read full article ↗';

    detailWrapper.appendChild(crumb);
    detailWrapper.appendChild(title);
    detailWrapper.appendChild(meta);
    detailWrapper.appendChild(note);
    detailWrapper.appendChild(link);

    if (tableWrapper) {
        tableWrapper.style.display = 'none';
    }
    detailWrapper.style.display = 'block';
    if (backBtn) {
        backBtn.classList.remove('is-hidden');
    }
    if (readFullBtn) {
        readFullBtn.classList.remove('is-hidden');
    }

    updateEoAckGap();
}

// Wired to the bar-9 "READ IN FULL" button -- always opens the original
// source in a separate window/tab, distinct from the in-app detail view.
function openCurrentArticleInFull() {
    if (currentNewsArticleUrl) {
        window.open(currentNewsArticleUrl, '_blank', 'noopener,noreferrer');
    }
}

// Wired to the bar-7 back button; re-rendering the list also resets its
// own visibility state (see renderFullNewsTable() above).
function backToNewsList() {
    renderFullNewsTable(globalNewsData);
    updateEoAckGap();
}

/* ==========================================================================
   SECTION 4: LAZY-LOAD HELPERS

   Generic <link>/<script> lazy-loading, deduped by DOM query -- used to
   pull in every self-hosted third-party lib and panel module on demand
   (Leaflet, satellite.js, and the panel modules themselves) rather than
   bundling everything into the initial page load. These two stay here in
   the shell since they're what load the panel modules below in the first
   place; everything else that used to live in this section (the shared
   Leaflet base map, per-panel map init, observer location, the plotted-
   objects list, add-object search/ground track/footprints) has moved out
   into assets/mapCore.js, assets/groundSegmentPanel.js, and
   assets/onOrbitPanel.js -- see registerPanelControls() above for how
   each of those panels plugs back into this file.
   ========================================================================== */

function loadStylesheetOnce(href) {
    if (document.querySelector(`link[href="${href}"]`)) {
        return Promise.resolve();
    }
    return new Promise((resolve, reject) => {
        const link = document.createElement('link');
        link.rel = 'stylesheet';
        link.href = href;
        link.onload = resolve;
        link.onerror = reject;
        document.head.appendChild(link);
    });
}

function loadScriptOnce(src) {
    if (document.querySelector(`script[src="${src}"]`)) {
        return Promise.resolve();
    }
    return new Promise((resolve, reject) => {
        const script = document.createElement('script');
        script.src = src;
        script.onload = resolve;
        script.onerror = reject;
        document.body.appendChild(script);
    });
}

// #utc-clock lives as static markup right below #location-readout in the
// map overlay (see index.html), sharing the same .location-readout/
// .loc-label/.loc-value classes so it reads as one continuous LAT/LON/UTC
// block rather than a separate widget. Kept as its own element instead of
// folded into renderLocationReadout()'s innerHTML so a once-a-second tick
// doesn't need to re-render the LAT/LON grid too. Runs unconditionally
// from page load rather than only while ON-ORBIT is open -- the element
// sits inert (and this is a single textContent write) while its section
// is hidden, cheap enough not to bother gating.
function renderUtcClock() {
    const value = document.querySelector('#utc-clock .loc-value');
    if (!value) {
        return;
    }
    const now = new Date();
    const hh = String(now.getUTCHours()).padStart(2, '0');
    const mm = String(now.getUTCMinutes()).padStart(2, '0');
    const ss = String(now.getUTCSeconds()).padStart(2, '0');
    value.textContent = `${hh}:${mm}:${ss}`;
}

setInterval(renderUtcClock, 1000);
renderUtcClock();


// Sections 5 (observer location, except renderUtcClock() below which runs
// unconditionally from page load), 6 (plotted orbital objects list), and
// 6b (add object search / ground track / live position / footprints) now
// live in assets/onOrbitPanel.js, alongside the rest of the on-orbit
// panel's own code, plus the on-orbit terminator/graticule/map-init code
// that used to sit in Section 4 above.


/* ==========================================================================
   SECTION 5: HOME-PAGE LIVE FEED CYCLER (YouTube IFrame Player API)

   Reads assets/youtubeFeeds.json and tries each candidate, in order, until
   one actually starts playing. There is no free/keyless way to ask YouTube
   "is this specific stream live right now" -- that requires the YouTube
   Data API (an API key, quota management, a bigger decision than this
   feature). What this does instead: use the real IFrame Player API (not a
   plain iframe) and watch its actual player events -- if a candidate
   starts playing, treat it as working; if it errors out or never starts
   within LIVE_FEED_TIMEOUT_MS, move to the next one. That's a genuine
   "first one that's actually running" check, just not a guaranteed
   live-broadcast flag.

   Some JSON entries point at a channel's /streams tab rather than a
   specific video (e.g. NASA's and NASASpaceflight's general channels) --
   those aren't embeddable at all, so they're filtered out up front rather
   than left to fail the cycle one by one.
   ========================================================================== */

const LIVE_FEED_TIMEOUT_MS = 6000;

function extractYouTubeVideoId(url) {
    try {
        const u = new URL(url);
        if (u.hostname === 'youtu.be') {
            return u.pathname.slice(1) || null;
        }
        if (u.hostname.endsWith('youtube.com')) {
            if (u.pathname === '/watch') {
                return u.searchParams.get('v');
            }
            if (u.pathname.startsWith('/embed/')) {
                return u.pathname.split('/')[2] || null;
            }
        }
    } catch (error) {
        // Malformed URL -- fall through to null.
    }
    return null; // Channel pages, /streams tabs, etc. aren't a specific video.
}

let liveFeedPlayer = null;
let liveFeedCandidates = [];
let liveFeedIndex = 0;
let liveFeedTimeoutHandle = null;

function loadYouTubeIframeAPI() {
    if (window.YT && window.YT.Player) {
        onYouTubeIframeAPIReady();
        return;
    }
    const tag = document.createElement('script');
    tag.src = 'https://www.youtube.com/iframe_api';
    document.head.appendChild(tag);
}

// Called automatically by the YouTube IFrame API once it has loaded --
// must be a global function, that's the API's own contract.
window.onYouTubeIframeAPIReady = function () {
    if (liveFeedCandidates.length === 0) return;
    liveFeedPlayer = new YT.Player('live-feed-player', {
        width: '100%',
        height: '100%',
        videoId: liveFeedCandidates[0].videoId,
        // origin/enablejsapi make YouTube's IFrame API and the player
        // iframe agree on the expected postMessage target -- without them
        // the console fills with "target origin ... does not match" warns
        // whenever the API talks to the player (candidate swaps, or after
        // showSection() hides #default-content).
        playerVars: {
            autoplay: 1,
            rel: 0,
            enablejsapi: 1,
            origin: window.location.origin,
        },
        events: {
            onReady: onLiveFeedPlayerReady,
            onStateChange: onLiveFeedStateChange,
            onError: onLiveFeedError,
        },
    });
};

function onLiveFeedPlayerReady(event) {
    event.target.mute(); // Required for autoplay to be allowed at all.
    event.target.playVideo();
    armLiveFeedTimeout();
}

function armLiveFeedTimeout() {
    clearTimeout(liveFeedTimeoutHandle);
    liveFeedTimeoutHandle = setTimeout(tryNextLiveFeedCandidate, LIVE_FEED_TIMEOUT_MS);
}

function onLiveFeedStateChange(event) {
    if (event.data === YT.PlayerState.PLAYING) {
        clearTimeout(liveFeedTimeoutHandle);
        showLiveFeedCredit(liveFeedCandidates[liveFeedIndex]);
    }
}

function onLiveFeedError() {
    tryNextLiveFeedCandidate();
}

function tryNextLiveFeedCandidate() {
    clearTimeout(liveFeedTimeoutHandle);
    liveFeedIndex++;
    if (liveFeedIndex >= liveFeedCandidates.length) {
        showLiveFeedUnavailable();
        return;
    }
    liveFeedPlayer.loadVideoById(liveFeedCandidates[liveFeedIndex].videoId);
    armLiveFeedTimeout();
}

function showLiveFeedCredit(entry) {
    const titleEl = document.getElementById('live-feed-title');
    const creditEl = document.getElementById('live-feed-credit');
    if (titleEl) titleEl.textContent = entry.name;
    if (creditEl) creditEl.textContent = entry.licensingNotes;
}

function showLiveFeedUnavailable() {
    const titleEl = document.getElementById('live-feed-title');
    const creditEl = document.getElementById('live-feed-credit');
    if (titleEl) titleEl.textContent = 'NO LIVE FEED AVAILABLE';
    if (creditEl) creditEl.textContent = '';
}

async function initLiveFeedCycler() {
    try {
        const response = await fetch('assets/youtubeFeeds.json');
        if (!response.ok) throw new Error(`HTTP error ${response.status}`);
        const feeds = await response.json();
        liveFeedCandidates = feeds
            .map((entry) => ({ ...entry, videoId: extractYouTubeVideoId(entry.url) }))
            .filter((entry) => entry.videoId);
        if (liveFeedCandidates.length === 0) {
            showLiveFeedUnavailable();
            return;
        }
        loadYouTubeIframeAPI();
    } catch (error) {
        console.error('Error loading live feed candidates:', error);
        showLiveFeedUnavailable();
    }
}

/* ==========================================================================
   SECTION 6: SYSTEM EVENT LIFECYCLE LISTENERS
   ========================================================================== */

window.addEventListener('DOMContentLoaded', fetchAndRenderNews);
// The landing page is the news view, so its nav shows the news filter
// buttons from the start -- nav strip only, leaving the ticker in #default.
window.addEventListener('DOMContentLoaded', () => renderControlAreaButtons('news'));
window.addEventListener('DOMContentLoaded', initLiveFeedCycler);
window.addEventListener('resize', () => {
    if (!controlAreaSectionActive && globalNewsData.length > 0) {
        renderNewsTable(globalNewsData);
    }
});