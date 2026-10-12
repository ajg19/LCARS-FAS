/* ==========================================================================
   GRD VIEW SATELLITE WORKER

   Runs in a background thread (a Web Worker started by grdViewPanel.js), so
   the orbit calculations never hold up the page -- dragging the direction
   dial stays smooth however many objects are in play.

   Messages in:
     { type: 'init', rows }   rows from api/sky/satellites (see server.py:
                              noradID, kind, stdMag, active, spacex, then
                              the OMM orbital elements). Builds one
                              satellite.js record per object, once.
     { type: 'compute', timeMs, aheadMs, latitude, longitude }
                              positions at that moment for that observer,
                              and aheadMs later (for the page to glide
                              each dot between the two).
   Message out:
     { type: 'result', timeMs, objects: [[index, altitudeDeg, azimuthDeg,
       magnitude, sunlit, altitudeDeg2, azimuthDeg2], ...] } -- every object
       above the horizon, the last two its position aheadMs later; index is
       the row's position in the init rows. }

   Speed (the server has already dropped everything that can never reach
   magnitude 5):
     * far below the horizon: an object more than FAR_BELOW_DEG below it
       can't rise for several minutes, so it is skipped until
       RECHECK_FAR_BELOW_MS later instead of computed every time.

   Apparent magnitude: standard magnitude (1,000 km, half lit) adjusted for
     * distance        + 5 log10(range / 1,000 km)
     * lighting        - 2.5 log10(pi F(phase)), F the diffuse-sphere phase
                       function ((pi - p) cos p + sin p) / pi, 1/pi half lit
     * air             + EXTINCTION_MAG x (airmass - 1), dimming near the
                       horizon
   Sunlit: outside the Earth's shadow, taken as a cylinder. Whether the
   observer's sky is dark enough is decided by the page, from the Sun.
   ========================================================================== */

importScripts('satellite/satellite.min.js');

const FAR_BELOW_DEG = -20;
const RECHECK_FAR_BELOW_MS = 60 * 1000;
const EARTH_RADIUS_KM = 6371;
const AU_KM = 149597870.7;
const EXTINCTION_MAG = 0.2;   // per airmass, a typical clear sky
const DEG = Math.PI / 180;

let records = [];       // { satrec, stdMag } per row; null if unusable
let nextCheck = [];     // time (ms) before which a row is skipped

function makeRecord(row) {
    try {
        const satrec = satellite.json2satrec({
            NORAD_CAT_ID: row[0],
            EPOCH: row[5],
            MEAN_MOTION: row[6],
            ECCENTRICITY: row[7],
            INCLINATION: row[8],
            RA_OF_ASC_NODE: row[9],
            ARG_OF_PERICENTER: row[10],
            MEAN_ANOMALY: row[11],
            BSTAR: row[12],
            MEAN_MOTION_DOT: row[13],
            MEAN_MOTION_DDOT: row[14],
        });
        return { satrec, stdMag: row[2] };
    } catch (error) {
        return null;
    }
}

function init(rows) {
    records = rows.map(makeRecord);
    nextCheck = new Array(records.length).fill(0);
}

// The moment's shared geometry: Sun, observer, sidereal times.
function scene(timeMs, aheadMs, latitude, longitude) {
    const date = new Date(timeMs);
    const later = new Date(timeMs + aheadMs);
    const gmst = satellite.gstime(date);
    const sun = satellite.sunPos(satellite.jday(date)).rsun.map((x) => x * AU_KM);
    const sunLength = Math.hypot(sun[0], sun[1], sun[2]);
    const observerGd = { latitude: latitude * DEG, longitude: longitude * DEG, height: 0 };
    return {
        date, later, gmst, gmstLater: satellite.gstime(later), sun,
        sunUnit: sun.map((x) => x / sunLength),
        observerGd,
        observerEci: satellite.ecfToEci(satellite.geodeticToEcf(observerGd), gmst),
    };
}

// One object seen from the observer: [elevation, azimuth, magnitude,
// sunlit, elevation later, azimuth later]. magnitude is 99 if the lit
// side faces away, null if the object has no standard magnitude.
function observe(record, sc, look, r) {
    const elevation = look.elevation / DEG;

    // Earth's shadow, as a cylinder behind the Earth.
    const along = r.x * sc.sunUnit[0] + r.y * sc.sunUnit[1] + r.z * sc.sunUnit[2];
    const sunlit = along > 0 || Math.hypot(r.x - along * sc.sunUnit[0], r.y - along * sc.sunUnit[1], r.z - along * sc.sunUnit[2]) > EARTH_RADIUS_KM;

    let magnitude = null;
    if (record.stdMag !== null && record.stdMag !== undefined) {
        // Phase angle at the object, between the Sun and the observer.
        const toSun = [sc.sun[0] - r.x, sc.sun[1] - r.y, sc.sun[2] - r.z];
        const toObserver = [sc.observerEci.x - r.x, sc.observerEci.y - r.y, sc.observerEci.z - r.z];
        const cosPhase = (toSun[0] * toObserver[0] + toSun[1] * toObserver[1] + toSun[2] * toObserver[2])
            / (Math.hypot(...toSun) * Math.hypot(...toObserver));
        const phase = Math.acos(Math.max(-1, Math.min(1, cosPhase)));
        const f = ((Math.PI - phase) * Math.cos(phase) + Math.sin(phase)) / Math.PI;
        const airmass = 1 / Math.sin(Math.max(elevation, 1) * DEG);
        magnitude = f > 1e-6
            ? record.stdMag + 5 * Math.log10(look.rangeSat / 1000) - 2.5 * Math.log10(Math.PI * f) + EXTINCTION_MAG * (airmass - 1)
            : 99;
    }

    const pvLater = satellite.propagate(record.satrec, sc.later);
    const lookLater = pvLater && pvLater.position
        ? satellite.ecfToLookAngles(sc.observerGd, satellite.eciToEcf(pvLater.position, sc.gmstLater))
        : look;
    return [elevation, look.azimuth / DEG, magnitude, sunlit ? 1 : 0,
        lookLater.elevation / DEG, lookLater.azimuth / DEG];
}

function lookFor(record, sc) {
    const pv = satellite.propagate(record.satrec, sc.date);
    if (!pv || !pv.position) return null;
    return { look: satellite.ecfToLookAngles(sc.observerGd, satellite.eciToEcf(pv.position, sc.gmst)), r: pv.position };
}

function compute(sc, timeMs) {
    const objects = [];
    for (let i = 0; i < records.length; i++) {
        const record = records[i];
        if (!record || nextCheck[i] > timeMs) continue;
        const found = lookFor(record, sc);
        if (!found) {
            nextCheck[i] = Infinity;   // decayed or bad elements: never again this session
            continue;
        }
        const elevation = found.look.elevation / DEG;
        if (elevation < FAR_BELOW_DEG) {
            nextCheck[i] = timeMs + RECHECK_FAR_BELOW_MS;
            continue;
        }
        if (elevation < 0) continue;
        objects.push([i, ...observe(record, sc, found.look, found.r)]);
    }
    return objects;
}

self.onmessage = (event) => {
    const message = event.data;
    if (message.type === 'init') {
        init(message.rows);
    } else if (message.type === 'compute') {
        const sc = scene(message.timeMs, message.aheadMs || 0, message.latitude, message.longitude);
        self.postMessage({
            type: 'result',
            timeMs: message.timeMs,
            objects: compute(sc, message.timeMs),
        });
    }
};
