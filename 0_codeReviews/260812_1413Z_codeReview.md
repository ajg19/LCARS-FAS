# Code Review — 2026-08-12 14:13 UTC

**Scope:** commit `99c6752` (`spaceKateVersion`) — `assets/onOrbitPanel.js`, `assets/lcars.js`, `assets/classic.css`, `index.html`

## Findings

| Severity | Location | Description |
|---|---|---|
| LOW | `assets/onOrbitPanel.js:1265-1269` | `renderDelObjResults()` calls `renderAddObjectResultsTable(objects, false)`, which unconditionally sets `#add-object-status` based on `objects.length`, then the caller immediately re-blanks it when `showStatusMessages` is `false`. Net effect is correct (empty string either way), but the double-write is easy to misread as a bug when tracing status-text ownership. Consider having `renderAddObjectResultsTable` accept/respect the flag directly. |
| LOW | `assets/onOrbitPanel.js:1969-2016` (`registerPanelControls`) | The previously-existing inert "IN VIEW" placeholder button was dropped from on-orbit's control panel. Functionally harmless (no dangling references found anywhere), but the surrounding comment doesn't call out this removal as intentional — could read as an accidental drop to a future maintainer. |
| INFO | `index.html:32` / `assets/classic.css:1918` | The new `#control-area-groups` div is now an unconditional sibling between `#default` and `nav` inside `.data-cascade-button-group`, shifting `nav` from `:nth-child(2)` to `:nth-child(3)`. A pre-existing responsive rule (`.data-cascade-button-group:has(.header-content) > *:nth-child(2)`, `classic.css:2002`) targets that index, but `.header-content` is not created anywhere in the codebase — the rule was already dead before this change and stays dead after it. Flagging only because it's the kind of thing that bites later if `.header-content` is ever reintroduced. |

## Conclusion

No correctness, security (XSS/eval), or unfinished-code issues found. New
DOM insertion consistently uses `textContent`/`createElement` rather than
`innerHTML` for any server- or user-derived data (OBJ TYPE column, button
labels, etc.); the one `innerHTML` usage on dynamic data (KEY-column SVG
swatch) only interpolates internally-computed hex colors/dash patterns,
not object-derived strings. `objectType` field confirmed present in
`server.py`'s API response, so the new OBJ TYPE column is not dead.
