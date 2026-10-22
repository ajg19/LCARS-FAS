# How the ON-ORBIT figures are counted

This page explains where the numbers in the ON-ORBIT section come from, what is and isn't counted, and how each category is defined. It is written for someone who wants to check or reuse the figures without knowing how the site is built.

*Last reviewed: 22 October 2026.*

---

## 1. In one paragraph

We start from the NORAD satellite catalogue (via Space-Track) — every catalogued object in orbit — and keep the **payloads** (spacecraft, as opposed to rocket bodies and debris) that **have not re-entered**. For each one we take its **current orbit** from that catalogue, and its **owner and country** from Jonathan McDowell's General Catalog of Artificial Space Objects (GCAT), matching the two by **NORAD catalogue number**. Two filters then narrow the set: **active only or all**, and **satellites only or all spacecraft**.

---

## 2. Where the data comes from

| Source | What we take from it | How often it is refreshed here |
|---|---|---|
| **The NORAD satellite catalogue (via Space-Track)** | The list of objects, their type (payload, rocket body, debris), whether they have decayed, and their **current orbit** (perigee and apogee). This is our only source of orbits. | Every 12 hours (the full catalogue daily) |
| **GCAT** — General Catalog of Artificial Space Objects, by Jonathan McDowell | Each object's **owner organisations**, **country (state)**, **payload category** (e.g. communications, imaging, space station, calibration sphere) and, where known, the date its **operations ended** | Weekly |
| **CelesTrak** (Dr T.S. Kelso) | Lists of satellites by group — which are *active*, which are *Starlink*, which belong to each constellation, which are at the *space stations* — when CelesTrak is available to us (see §3, *Active*) | Every 3 days |

The two are joined by the **NORAD catalogue number**, the unique number every tracked object receives. About 97% of payloads in the catalogue have a GCAT entry; the rest are usually very recent launches GCAT has not yet added.

**Why the orbit comes from the NORAD catalogue and not from GCAT:** GCAT records the orbit an object was *first placed in*, not where it is now. Many satellites are released low and then raise themselves — Starlink satellites, for example, are released at about 270–350 km and then climb to about 460–485 km. Using GCAT's orbits would put ten times too many satellites in Very Low Earth Orbit.

---

## 3. What is counted

### All spacecraft
Every **payload** in the NORAD catalogue that **has not decayed** (re-entered the atmosphere). Rocket bodies, debris and objects of unknown type are never counted.

### Satellites
All spacecraft **except**:

- **Crewed space stations and the vehicles visiting them** — the modules of the International Space Station and China's Tiangong station, and docked crew and cargo ships such as Soyuz, Progress, Crew Dragon, Cygnus, Shenzhou and Tianzhou. These are identified by GCAT's *space station* category; a visiting vehicle so new that GCAT has not catalogued it yet is identified by CelesTrak's *stations* list instead, when that list is available.
  - Small satellites recently released from the ISS also appear on CelesTrak's *stations* list. They are ordinary satellites in GCAT, so they **are** counted as satellites.
- **Passive objects** that were launched as payloads but are not working spacecraft — **calibration spheres** (used to calibrate tracking radars) and **targets** (launched for anti-satellite tests).

### Active
Choosing *all* includes satellites that are no longer working — dead satellites remain in orbit, often for decades. Choosing *active* keeps only the working ones, decided in this order:

1. **CelesTrak's *active* list, when it is available** — that is, when we have fetched it successfully within the last 14 days. CelesTrak maintains it from each object's operational status, and it is taken as definitive for every object launched before our latest copy of it.
2. **Recent launches count as active.** A payload launched within the last **3 months** is treated as active unless shown otherwise (a later CelesTrak list leaves it out, or it has re-entered). Catalogues take weeks to record a new satellite's status, so new satellites are assumed to be working.
3. **Otherwise, our own rule:** a payload in orbit counts as active unless GCAT records an end to its operations. This agreed with CelesTrak's list for about 92% of payloads in orbit when we compared them in October 2026.

The same order decides the **Starlink** group (CelesTrak's list when available, otherwise GCAT listing Starlink's operator, SpaceX (Seattle), as owner, or a name beginning STARLINK for payloads GCAT has not yet catalogued) and the other **constellation groups** used elsewhere on the site, such as OneWeb, Kuiper, Iridium, GPS, Galileo and BeiDou.

**While CelesTrak is unavailable to us, some groups are missing.** A few groups — the space stations, ORBCOMM, SES, Intelsat, Telesat, Spire, and the navigation-augmentation and search-and-rescue groups among them — could not be matched reliably by rules of our own, so we show them only from CelesTrak's lists. When CelesTrak cannot be reached for more than 14 days, those groups are absent from the site (for example from the ADD OBJ group filter) until it is back. The figures on this page are not affected, apart from the rare visiting vehicle that GCAT has not yet catalogued.

### The four combinations
The two filters can be combined freely: *active satellites*, *active spacecraft*, *all satellites*, *all spacecraft*. Every figure in the section is calculated for all four.

---

## 4. Ownership and nationality

- **Country** is GCAT's *state* for the object — the state responsible for it, which is not always where it was built or launched.
- **United States** is split into **Starlink** and **Other**, because Starlink alone is more than half of all active satellites.
- **Soviet Union** and **Russia** are kept separate. Satellites launched by the USSR that are still in orbit are listed under the Soviet Union; almost all are inactive, so the Soviet Union largely disappears from the *active* view.
- **International organisations** (such as the European Space Agency) are listed under their own name, not under a country. The European Space Agency is always shown individually.
- The **twelve largest** countries are shown individually; all others — plus any payload GCAT has not yet catalogued — are grouped as **Other**.
- Country names are GCAT's short English names, written out in full where GCAT uses an abbreviation (e.g. "United Kingdom" rather than "UK").

### Excluding SpaceX ("EXCL SPACEX")
A payload is excluded if **SpaceX is among its owners** in GCAT — under any of GCAT's SpaceX codes, which cover the company's sites including Starlink's operator, SpaceX (Seattle). This removes the Starlink constellation and a handful of other SpaceX-owned or co-owned satellites. For a payload GCAT has not yet catalogued, membership of the Starlink group (above) is used instead.

---

## 5. Orbit regimes

### Definitions

| Regime | Name | Definition used here |
|---|---|---|
| **VLEO** | Very Low Earth Orbit | Mean altitude **below 450 km**. This is the most common definition, used by ESA and DARPA; some sources put the ceiling at 400 km or 500 km. Orbits this low decay quickly without regular propulsion. |
| **LEO** | Low Earth Orbit | Mean altitude **450 km to 2,000 km**. Most satellites, including the large broadband constellations and most Earth-observation satellites. |
| **MEO** | Medium Earth Orbit | Mean altitude **2,000 km to 35,586 km**. Navigation systems (GPS, Galileo, GLONASS, BeiDou) sit at about 19,000–23,000 km. |
| **GEO** | Geostationary Orbit | Mean altitude **within ±200 km of 35,786 km** — the altitude at which an orbit takes one day, so a satellite over the equator appears fixed in the sky. Used by most broadcast and many communications and weather satellites. |
| **> GEO** | Above geostationary | Mean altitude **more than 200 km above GEO**. Almost all are **retired GEO satellites moved to "graveyard" orbits** a few hundred kilometres higher at the end of their lives, plus a few science missions in very high orbits. |
| **HEO** | Highly Elliptical Orbit | Current **eccentricity above 0.25**, whatever the altitude — very low at one end, very high at the other. Examples: **Molniya** orbits (roughly 500 km × 40,000 km), **Tundra** orbits, **geostationary transfer orbits**, and science missions on long looping orbits (such as TESS and the Chandra X-ray Observatory). |

### How an object is placed in a regime
Each object is placed from its **current** orbit in two steps:

1. **Shape first.** If the orbit's eccentricity is above 0.25 it is **HEO**, whatever its altitude. Eccentricity is worked out from the current perigee (lowest point) and apogee (highest point): (apogee radius − perigee radius) ÷ (apogee radius + perigee radius), with radii measured from Earth's centre.
2. **Then altitude.** Every other (near-circular) orbit is placed by its **mean altitude**, the average of perigee and apogee, into VLEO, LEO, MEO, GEO or > GEO.

Classifying shape first matters: by mean altitude alone a Molniya orbit (average about 20,000 km) would look like **MEO**, and a very eccentric science orbit like **> GEO**.

### Objects with no current orbit
A handful of payloads in the catalogue have no current orbit on file. They are **not placed in any regime** (rather than being guessed), and their number is given on the DEFINITIONS page's reconciliation.

---

## 6. Totals and percentages

- **TOTAL** is the sum of the regime rows shown, so it excludes payloads with no current orbit on file.
- Each **%** row is a share of **its own row's total** — the ALL percentages of the ALL total, the EXCL SPACEX percentages of the EXCL SPACEX total — so each % row adds up to 100%.
- The nationality chart uses a **logarithmic scale** because the largest bar (Starlink) is hundreds of times the smallest; the exact count is printed at the end of every bar.

---

## 7. Timing and limitations

- **Snapshot.** The figures are recalculated after every catalogue refresh (every 12 hours) and every GCAT refresh (weekly). Orbits are therefore at most about 12 hours old, ownership at most about a week.
- **"Active" is a judgement**, CelesTrak's when its list is available and otherwise GCAT's record of when operations ended. Either can lag reality for satellites that fail or are retired quietly, and the 3-month rule counts a new satellite as working even if it failed on arrival.
- **The 0.25 eccentricity threshold** is a common convention, not a standard. Orbits just below it are placed by mean altitude.
- **About 3% of payloads have no GCAT entry yet**, so they have no country and are counted under *Other* in the nationality chart.
- **Categories are GCAT's.** What counts as a space station, calibration sphere or target follows GCAT's own classification.

---

## 8. Sources and credits

- **NORAD satellite catalogue** — via **Space-Track** (space-track.org).
- **Satellite group lists** — **CelesTrak** (celestrak.org, Dr T.S. Kelso).
- **GCAT** — General Catalog of Artificial Space Objects. *Data from GCAT (J. McDowell, planet4589.org/space/gcat)*, used under the CC-BY-4.0 licence.
- VLEO definition: European Space Agency and DARPA (mean altitude below 450 km).
