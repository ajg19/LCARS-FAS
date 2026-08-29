/* ==========================================================================
   GS OPS PANEL

   Ground-station operations. Thin wrapper around registerLocationMapPanel()
   (assets/locationMapPanel.js) -- identical setup to the EO panel, see
   that file for the shared base map + graticule + day/night terminator +
   user-location behaviour. Lazily loaded the first time GS OPS is opened;
   openGsOpsSection() in lcars.js loads mapCore.js, onOrbitPanel.js and
   locationMapPanel.js first.

   Payload: the shared map, opened zoomed in on the user's location.
   Control panel: GS LOCN in slot 1 opens the shared LAT/LON/PLACE form;
   slots 2-6 are inert placeholders.
   ========================================================================== */

const gsOpsLocationPanel = registerLocationMapPanel({
    sectionId: 'gs-ops',
    containerId: 'gs-ops-map',
    buttonLabel: 'GS LOCN',
});

// Global alias so openGsOpsSection() (lcars.js) can call it the same way
// the other sections call initOnOrbitMap() / initInfrastructureMap().
function initGsOpsMap() {
    return gsOpsLocationPanel.initMap();
}
