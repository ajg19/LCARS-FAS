# ON-ORBIT — Charts Built and Proposed

*LCARS-FAS · 10 October 2026*

This lists the charts and tables in the ON-ORBIT section, built and proposed. They're grouped to match the ON-ORBIT control panel's second button group: **LOCN** (what is where), **COMMERCIAL** (who owns it: owners and countries), **DEBRIS** (where it is, how much there is, how it has grown) and **COMMS** (radio). The LAUNCHES section's charts stay with that section and aren't listed here.

The counting rules behind the charts are on the section's DEFS page and in `assets/onOrbitMethodology.md`.

## Data available

| Database | Source | What it gives the charts |
|---|---|---|
| `orbitalObjects.db` | NORAD catalogue via CelesTrak and Space-Track (SatNOGS for a few) | Every object's current orbit (perigee, apogee, inclination, eccentricity, period), object type (payload / rocket body / debris / unknown), launch and decay dates, radar cross-section, CelesTrak groups (active, stations, Starlink, debris clouds …), and downlink band / EIRP / RF details |
| `gcat.db` | GCAT (J. McDowell) | Owner organisations and their parent organisations, country (state), sector class (A/B/C/D), mission category, mass, manufacturer, bus, launch log, and a per-year summary of every decay (by object type, how it came down, and whether SpaceX owned it) |
| `onOrbitStats.db` | Derived by `scripts/orbitStats.py` | Every precomputed chart's figures, for every filter combination |

On the live server today the catalogue holds 33,149 objects, 32,860 of them in orbit: 18,850 payloads, 10,112 debris, 2,201 rocket bodies, 1,290 unknown and 407 not yet typed.

## Common to every chart

- **Filters:** ACT-ONLY / ACT +DEAD, SAT ONLY / ALL S-CRFT / ALL-OBJ, and INC SPACEX / EX SPACEX. Each chart follows all three. The regime table ignores the SpaceX button, because it shows ALL and EXCL SPACEX side by side.
- **Title bar:** each chart has an LCARS pill title bar, with a total, or how much is shown, at its right-hand end. Where something is left out, a tooltip on the total says what and why.
- **Log scales:** these are used where counts span several powers of ten. The axis title then ends "(LOG SCALE)".
- **Loading:** each chart loads on its own, so if one fails, only that chart shows an error.
- **Sector colours:** the same everywhere: academic blue, commercial earth, civil amber, defence red (as in the LAUNCHES section).
- **DEFS page:** definitions, how the charts are built, and a live reconciliation of the totals.

**Status** in the tables: **Built** (with where it is), or **Proposed**. All four groups are built. ★ marks the suggested next charts. Every proposal uses data we already hold, unless its notes say otherwise.

## LOCN — what is where

| Chart | Type | Data | Status |
|---|---|---|---|
| **Orbit regime table** — payloads per current orbit regime (VLEO, LEO, MEO, GEO, > GEO, HEO, TOTAL); rows ALL, %, EXCL SPACEX, %. HEO (eccentricity > 0.25) classified first, then mean altitude | Table | Current orbit | Built — control area |
| **By orbit type** — the same regime counts as shares of the whole | Pie | Current orbit | Built — top left |
| **By inclination** — current inclination in 5° bands, 0°–180° | Vertical histogram, log | Current orbit | Built |
| **Inclination by orbit type** — the inclination histogram, each band stacked by regime | Stacked histogram | Current orbit | Built |
| **Altitude histogram** — 25–50 km bands up to 2,000 km; shows the LEO shells (Starlink ~550 km, OneWeb ~1,200 km) | Vertical histogram | Perigee / apogee | Built |
| **Altitude vs inclination** — one dot per object, coloured by sector or owner; constellation shells and sun-synchronous orbits show up as clusters | Scatter | Current orbit; GCAT sector / owner | Built — dots per 25 km × 1° cell, coloured by sector |
| **GEO belt map** — satellites along the GEO arc by longitude, coloured by country or owner | Arc / strip plot | Current elements (longitude worked out from them) | Built — 2° bands of longitude, by sector |
| **Active vs inactive by regime** — the share of each regime that is dead | Stacked bars | CelesTrak active group; current orbit | Built |
| **Age profile** — years since launch of active satellites, e.g. GEO satellites over 15 years old | Histogram | Launch date | Built |

## COMMERCIAL — who owns it, by owner and country

| Chart | Type | Data | Status |
|---|---|---|---|
| **By sector (GCAT class)** — A academic, B commercial, C civil government, D defence, Unknown | Pie | GCAT sector (payload's own, else its owner's) | Built — top right (to sit beside the mission-category pie) |
| **By mission category** — communications, imaging, navigation, science, tech demo … | Pie | GCAT category | Built — beside the sector pie |
| **By nationality** — top 12 countries plus ESA, then Other; US split into Starlink and Other; Soviet Union separate from Russia | Horizontal bars, log | GCAT state | Built |
| **By owner** — the 40 largest owners plus Other; count above each bar, % inside it, names turned 90° | Vertical bars, log | GCAT owners | Built — bottom |
| **Sector by country** — A/B/C/D shares for each of the top 12 countries | Stacked bars | GCAT sector and state | Built |
| **Manufacturers and satellite buses** — who builds what is up there | Bars | GCAT manufacturer, bus | Built — top 20 of each, side by side |
| **Payloads in orbit by year** — payloads in orbit at each year end, by sector (A/B/C/D, labelled and coloured as in the LAUNCHES section) | Stacked area | GCAT launch and decay dates; GCAT sector | Built — SpaceX filter only |
| **Country and owner tree** — countries with their owners beneath, like a Unix/DOS directory listing; click to open a country | Tree | GCAT state and owner | Built |

**Layout note:** the sector pie and the mission-category pie are to be shown **side by side**, as a pair. The orbit-type pie currently sits beside the sector pie, so it would move, or the three pies would share a row.

## DEBRIS — where it is, how much there is, how it has grown

| Chart | Type | Data | Status |
|---|---|---|---|
| **Whole catalogue by object type** — payloads, rocket bodies, debris and unknown, per orbit regime | Stacked bars | Object type; current orbit | Built |
| **Debris by altitude** — where the debris is: altitude bands, stacked by object type, showing the crowded shells (~800 km, where the big break-ups happened) | Stacked histogram | Object type; perigee / apogee | Built — every object below 2,000 km, by type |
| **Debris history** — pieces created per year (bars, by break-up date) with pieces in orbit at year end (line, right axis) | Bars + line, two axes | GCAT debris history (created and re-entered per year) | Built |
| **Debris by inclination** — debris only, current inclination in 5° bands, 0°–180°; the same form as the payload inclination histogram | Vertical histogram, log | Object type; current orbit | Built |
| **Rocket bodies in orbit** by country or launch vehicle | Bars | Object type; GCAT | Built — by country and by launch vehicle, side by side |
| **Debris by origin event** — one bar per object that broke up (e.g. "Long March 6A stage, 2024", not the launch's payload "Qianfan-1"), largest first: Fengyun-1C, Cosmos 2251, Long March 6A stages … | Bars | GCAT's **Parent** field for each fragment (kept by the GCAT ingest) | Built — GCAT parent object, top 20 |

## COMMS — radio

| Chart | Type | Data | Status |
|---|---|---|---|
| **Downlink band** — share of active satellites by main downlink band (UHF, S, X, Ku, Ka …) | Pie | EIRP / RF enrichment — mostly inferred, one band per satellite; best shown EX SPACEX, as Starlink is three-quarters Ku | Built |
| **Band by payload type** — each band's satellites split by mission category | Stacked histogram | RF enrichment; GCAT category | Built |
| **Band by orbit type** — each band's satellites split by orbit regime | Stacked histogram | RF enrichment; current orbit | Built |
