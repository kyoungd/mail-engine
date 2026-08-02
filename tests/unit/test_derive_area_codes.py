"""The recorded area-code derivation (§6 Phase 0): the method's moving parts,
pinned offline — haversine, area-code extraction, unmapped-ZIP accounting, and
the radius filter over synthetic contacts."""

import pytest

from jobs.derive_area_codes import area_code, derive, haversine_miles

# Two real ZCTA centroids ~34.5 miles apart (Chatsworth 91311, downtown LA 90012).
CENTROIDS = {
    "91311": (34.258, -118.616),
    "90012": (34.061, -118.239),
    "91355": (34.417, -118.588),  # Valencia (661 country), ~11 mi north
}


def test_haversine_matches_known_distance():
    # Verified independently: Δlat 0.197° ≈ 13.6 mi, Δlon 0.377°·cos(34.16°) ≈ 21.5 mi,
    # √(13.6² + 21.5²) ≈ 25.4 mi (flat-earth cross-check at this scale).
    d = haversine_miles(*CENTROIDS["91311"], *CENTROIDS["90012"])
    assert d == pytest.approx(25.5, abs=0.3)  # Chatsworth -> downtown LA


def test_area_code_is_the_national_prefix():
    assert area_code("+18185551234") == "818"
    assert area_code("+16615550000") == "661"


def test_derive_filters_by_radius_and_reports_unmapped():
    contacts = [
        ("+18185550001", "91311"),   # at the base
        ("+16615550002", "91355"),   # ~11 mi — inside 15
        ("+12135550003", "90012"),   # ~25 mi — outside 15
        ("+13105550004", "00000"),   # ZIP not in the gazetteer
    ]
    result = derive("91311", 15.0, CENTROIDS, contacts)

    assert result["callable_total"] == 4
    assert result["zip_unmapped"] == 1      # counted, never silently dropped
    assert result["in_radius"] == 2
    assert dict(result["ranked"]) == {"818": 1, "661": 1}


def test_unknown_base_zip_fails_loud():
    with pytest.raises(SystemExit):
        derive("99999", 20.0, CENTROIDS, [])
