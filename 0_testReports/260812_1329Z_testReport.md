# Test Report — 2026-08-12 13:29 UTC

**Command:** `pytest 0_tests -v`
**Result:** ✔ PASS — 26 passed, 0 failed, 0 errors (0.29s)

## Summary

| Metric | Count |
|---|---|
| Total | 26 |
| Passed | 26 |
| Failed | 0 |
| Errors | 0 |

## Notes

First run under the pytest suite (migrated from an earlier `unittest`
version). Confirms the migration itself: same coverage, now expressed
with `pytest.mark.parametrize` instead of manual loops (26 collected
test cases vs. 21 previously, since parametrized cases now count
individually).

Covers all 5 API endpoints (status, `Content-Type`, JSON shape), static
file serving (including a direct regression check for the stub-page
deploy failure this project hit once in production), a SQL-injection
safety check, and the pure `parse_inclination_deg`/`get_param` logic.
Runs against the real local databases in `ingestionDBs/` — no mocks.

## Full output

```
============================= test session starts =============================
platform win32 -- Python 3.14.6, pytest-9.1.1, pluggy-1.6.0 -- C:\Python314\python.exe
cachedir: .pytest_cache
rootdir: C:\Users\User\DEV\LCARS-FAS
collecting ... collected 26 items

0_tests/test_server.py::test_news_endpoint_returns_json_list PASSED      [  3%]
0_tests/test_server.py::test_news_endpoint_respects_limit_param PASSED   [  7%]
0_tests/test_server.py::test_ground_segment_assets_endpoint_returns_json_list PASSED [ 11%]
0_tests/test_server.py::test_orbital_objects_endpoint_empty_ids_returns_empty_list PASSED [ 15%]
0_tests/test_server.py::test_orbital_objects_endpoint_with_id_param PASSED [ 19%]
0_tests/test_server.py::test_orbital_objects_endpoint_ignores_malformed_ids PASSED [ 23%]
0_tests/test_server.py::test_filter_options_endpoint_shape PASSED        [ 26%]
0_tests/test_server.py::test_orbital_objects_search_default_shape PASSED [ 30%]
0_tests/test_server.py::test_orbital_objects_search_altitude_regime_filter_does_not_error[LEO] PASSED [ 34%]
0_tests/test_server.py::test_orbital_objects_search_altitude_regime_filter_does_not_error[MEO] PASSED [ 38%]
0_tests/test_server.py::test_orbital_objects_search_altitude_regime_filter_does_not_error[GEO] PASSED [ 42%]
0_tests/test_server.py::test_orbital_objects_search_altitude_regime_filter_does_not_error[OTHER] PASSED [ 46%]
0_tests/test_server.py::test_orbital_objects_search_inclination_band_filter_does_not_error[EQUATORIAL] PASSED [ 50%]
0_tests/test_server.py::test_orbital_objects_search_inclination_band_filter_does_not_error[MID] PASSED [ 53%]
0_tests/test_server.py::test_orbital_objects_search_inclination_band_filter_does_not_error[POLAR_SSO] PASSED [ 57%]
0_tests/test_server.py::test_orbital_objects_search_name_filter_is_sql_injection_safe PASSED [ 61%]
0_tests/test_server.py::test_root_serves_index_html PASSED               [ 65%]
0_tests/test_server.py::test_js_asset_has_correct_content_type PASSED    [ 69%]
0_tests/test_server.py::test_css_asset_has_correct_content_type PASSED   [ 73%]
0_tests/test_server.py::test_missing_file_returns_404 PASSED             [ 76%]
0_tests/test_server.py::test_parse_inclination_deg_valid_tle_line PASSED [ 80%]
0_tests/test_server.py::test_parse_inclination_deg_handles_bad_input[not a tle line] PASSED [ 84%]
0_tests/test_server.py::test_parse_inclination_deg_handles_bad_input[None] PASSED [ 88%]
0_tests/test_server.py::test_parse_inclination_deg_handles_bad_input[] PASSED [ 92%]
0_tests/test_server.py::test_get_param_returns_first_value PASSED        [ 96%]
0_tests/test_server.py::test_get_param_returns_none_when_absent PASSED   [100%]

============================= 26 passed in 0.29s ==============================
```
