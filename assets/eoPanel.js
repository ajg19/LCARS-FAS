/* ==========================================================================
   EO PANEL

   Thin wrapper around registerLocationMapPanel() (assets/locationMapPanel.js)
   -- see that file for the shared base map + graticule + day/night
   terminator + user-location behaviour. Lazily loaded the first time EO
   is opened; openEoSection() in lcars.js loads mapCore.js, onOrbitPanel.js
   and locationMapPanel.js first.

   Payload: the shared map, opened zoomed in on the user's location.
   Control panel: TGT LOCN in slot 1 opens the shared LAT/LON/PLACE form;
   slots 2-6 are inert placeholders.
   ========================================================================== */

const eoLocationPanel = registerLocationMapPanel({
    sectionId: 'eo',
    containerId: 'eo-map',
    buttonLabel: 'TGT LOCN',
});

// Global alias so openEoSection() (lcars.js) can call it the same way the
// other sections call initOnOrbitMap() / initInfrastructureMap().
function initEoMap() {
    return eoLocationPanel.initMap();
}
