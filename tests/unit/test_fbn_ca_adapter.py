"""The FBN-CA intake adapter: filter to live statements, dedupe, map to the
canonical intake shape. Pure — convert() takes and returns plain dicts."""

from intake.fbn_ca import CANONICAL_FIELDS, convert


def _raw(**overrides):
    row = {
        "FilingNumber": "2026000001",
        "FiledTS": "2026/02/01 08:00:00+00",
        "FilingType": "FBN Statement",
        "BusinessType": "Individual",
        "BusinessName": "JV Wireless",
        "BusinessAddress": "2209 W Rosecrans Ave",
        "BusinessAddressAdditional": "",
        "BusinessCity": "Gardena",
        "BusinessState": "ca",
        "BusinessZipCode": "90249",
        "RegisteredOwnerName": "Aritzi Beltran",
        "OBJECTID": "1",
        "GlobalID": "g-1",
    }
    row.update(overrides)
    return row


def test_maps_to_canonical_shape_with_prefixed_key():
    (row,) = convert([_raw()])
    assert set(row) == set(CANONICAL_FIELDS)
    assert row["list_key"] == "fbn-ca-2026000001"
    assert row["business_name"] == "JV Wireless"
    assert row["contact_name"] == "Aritzi Beltran"
    assert row["trade"] == ""
    assert row["addr_state"] == "CA"
    assert row["segment"] == "fbn-ca"


def test_keeps_statements_only():
    rows = [
        _raw(),
        _raw(FilingNumber="2", FilingType="FBN Abandonment"),
        _raw(FilingNumber="3", FilingType="FBN Amendment"),
        _raw(FilingNumber="4", FilingType="FBN Renewal - Refile"),
        _raw(FilingNumber="5", FilingType="FBN Withdrawal"),
    ]
    assert [r["list_key"] for r in convert(rows)] == ["fbn-ca-2026000001"]


def test_year_filter_and_segment_vintage():
    rows = [
        _raw(FilingNumber="1", FiledTS="2024/03/01 08:00:00+00"),
        _raw(FilingNumber="2", FiledTS="2026/03/01 08:00:00+00", BusinessName="New Co"),
    ]
    converted = convert(rows, year=2026)
    assert [r["list_key"] for r in converted] == ["fbn-ca-2"]
    assert converted[0]["segment"] == "fbn-ca-2026"


def test_dedupes_filing_number_and_keeps_newest_per_business():
    rows = [
        _raw(FilingNumber="1"),
        _raw(FilingNumber="1"),  # duplicate filing row
        _raw(FilingNumber="2", FiledTS="2026/05/01 08:00:00+00"),  # same biz, newer refile
        _raw(FilingNumber="3", BusinessName="Other Biz"),
    ]
    converted = sorted(convert(rows), key=lambda r: r["list_key"])
    assert [r["list_key"] for r in converted] == ["fbn-ca-2", "fbn-ca-3"]