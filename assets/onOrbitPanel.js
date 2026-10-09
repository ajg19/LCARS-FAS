/* ==========================================================================
   ON-ORBIT OVERVIEW PANEL -- what is on orbit, by nationality, sector
   (GCAT classes: academic, commercial, civil government, defence),
   orbital inclination and altitude. Lazy-loaded by
   openOnOrbitSection() in lcars.js the first time the ON-ORBIT
   menu button is clicked.

   Scaffold only so far: the section exists with its own (empty) control
   area and main-area placeholder. The data -- GCAT (ingestionDBs/gcat.db,
   scripts/ingestGcat.py) joined to orbitalObjects.db by NORAD number --
   and its charts are still to be built.

   Not to be confused with the GRD-TRACK map section (section id
   'grd-track', assets/grdTrackPanel.js), which held the ON-ORBIT name and
   this file name until 2026-10-09.
   ========================================================================== */

registerPanelControls('on-orbit', {
    // Control area: a short status line until the overview's own controls
    // (e.g. nationality / sector / inclination / altitude views) exist.
    defaultAreaMode: 'custom',
    renderDefaultArea: () => {
        const wrapper = document.getElementById('default');
        if (wrapper) {
            wrapper.innerHTML = '<div class="on-orbit-status">ON-ORBIT OVERVIEW &mdash; IN DEVELOPMENT</div>';
        }
    },
    buttons: [],
});
