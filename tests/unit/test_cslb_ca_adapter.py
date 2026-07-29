"""The CSLB-CA intake adapter: CLEAR-only default, class→trade mapping, filters,
dedupe, canonical mapping. Pure — convert() takes and returns plain dicts."""

from intake.cslb_ca import CANONICAL_FIELDS, convert


def _raw(**overrides):
    row = {
        "LicenseNo": "1000002",
        "LastUpdate": "09/15/2025",
        "BusinessName": "DOCKERY RANDALL MARK",
        "FullBusinessName": "RANDALL MARK DOCKERY",
        "MailingAddress": "301 SOUTH MILLS AVENUE",
        "City": "LODI",
        "State": "CA",
        "County": "San Joaquin",
        "ZIPCode": "95242",
        "BusinessPhone": "(925) 383 0487",
        "BusinessType": "Sole Owner",
        "PrimaryStatus": "CLEAR",
        "Classifications(s)": "C36",
        "WorkersCompCoverageType": "Exempt",
    }
    row.update(overrides)
    return row


def test_maps_to_canonical_shape():
    (row,) = convert([_raw()])
    assert set(row) == set(CANONICAL_FIELDS)
    assert row["list_key"] == "cslb-1000002"
    assert row["trade"] == "plumber"
    assert row["license_class"] == "C36"
    assert row["phone"] == "(925) 383 0487"
    assert row["segment"] == "plumber-san-joaquin"
    assert row["contact_name"] == "RANDALL MARK DOCKERY"


def test_clear_only_by_default_and_include_suspended_override():
    rows = [_raw(), _raw(LicenseNo="2", PrimaryStatus="Work Comp Susp")]
    assert [r["list_key"] for r in convert(rows)] == ["cslb-1000002"]
    assert len(convert(rows, include_suspended=True)) == 2


def test_unmapped_classes_are_skipped_and_multi_class_priority():
    rows = [
        _raw(LicenseNo="1", **{"Classifications(s)": "B"}),  # no NMC trade -> skipped
        _raw(LicenseNo="2", **{"Classifications(s)": "B|C-10"}),  # electrician
        _raw(LicenseNo="3", **{"Classifications(s)": "C10, C36"}),  # plumber outranks
    ]
    converted = convert(rows)
    assert [(r["list_key"], r["trade"]) for r in converted] == [
        ("cslb-2", "electrician"),
        ("cslb-3", "plumber"),
    ]
    assert converted[1]["license_class"] == "C10|C36"


def test_county_and_classes_filters():
    rows = [
        _raw(LicenseNo="1", County="Los Angeles"),
        _raw(LicenseNo="2", County="Orange"),
        _raw(LicenseNo="3", County="Los Angeles", **{"Classifications(s)": "C20"}),
    ]
    la = convert(rows, counties={"los angeles"})
    assert [r["list_key"] for r in la] == ["cslb-1", "cslb-3"]
    la_plumbers = convert(rows, counties={"Los Angeles"}, classes={"C36"})
    assert [r["list_key"] for r in la_plumbers] == ["cslb-1"]


def test_multiclass_row_emits_all_matching_trades():
    """Phase 1 gate (design §2.1): `trades` carries EVERY matching NMC trade as the
    sorted distinct union (§6 pins the ordering, so a pipe-join is deterministic),
    while `trade` keeps its first-match priority semantics unchanged."""
    (row,) = convert([_raw(**{"Classifications(s)": "C20|C36"})])
    assert row["trades"] == "hvac|plumber"  # sorted, not TRADE_BY_CLASS priority
    assert row["trade"] == "plumber"  # C36 outranks C20 — unchanged behaviour


def test_single_class_row_emits_one_trade():
    (row,) = convert([_raw()])  # C36
    assert row["trades"] == "plumber"
    assert row["trade"] == "plumber"


def test_trades_ignores_classes_with_no_nmc_trade():
    """B (general building) maps to no NMC trade, so it never enters `trades`."""
    (row,) = convert([_raw(**{"Classifications(s)": "B|C-10"})])
    assert row["trades"] == "electrician"
    assert row["trade"] == "electrician"


def test_trades_joined_canonical_fields():
    (row,) = convert([_raw()])
    assert "trades" in CANONICAL_FIELDS
    assert set(row) == set(CANONICAL_FIELDS)


def test_wc_exempt_filter_and_dedupe():
    rows = [
        _raw(LicenseNo="1"),
        _raw(LicenseNo="1"),  # duplicate license row
        _raw(LicenseNo="2", WorkersCompCoverageType="Workers' Compensation Insurance"),
    ]
    assert len(convert(rows)) == 2
    assert [r["list_key"] for r in convert(rows, wc_exempt_only=True)] == ["cslb-1"]