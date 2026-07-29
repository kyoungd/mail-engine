"""Unit tests for the Lob response -> VerificationResult mapping (offline, no vendor).

Tier-2 disposable tests: the frozen acceptance tests pin the JOB's behaviour through the
seam, and these pin the one thing they cannot — that the vendor's field names land in the
right places, and that the verdict/error split is drawn where §5 says it is.
"""

import pytest

from seams.address_verifier import AddressVerificationError
from seams.lob_address import LobAddressVerifier

# Shape per Lob US Address Verification, fields verified 2026-07-27 (design §5).
DELIVERABLE_RESPONSE = {
    "id": "us_ver_abc",
    "primary_line": "185 BERRY ST STE 6100",
    "secondary_line": "",
    "last_line": "SAN FRANCISCO CA 94107-1741",
    "deliverability": "deliverable",
    "components": {
        "city": "SAN FRANCISCO",
        "state": "CA",
        "zip_code": "94107",
        "zip_code_plus_4": "1741",
        "delivery_point_barcode": "941071741992",
    },
}


def test_a_deliverable_response_maps_every_field():
    result = LobAddressVerifier._to_result(DELIVERABLE_RESPONSE)

    assert result.deliverability == "deliverable"
    assert result.delivery_point == "941071741992"
    assert result.std_addr_line1 == "185 BERRY ST STE 6100"
    assert result.std_addr_city == "SAN FRANCISCO"
    assert result.std_addr_state == "CA"
    assert result.std_addr_zip == "94107-1741"  # ZIP+4, joined
    assert result.has_components is True


def test_a_missing_plus4_leaves_a_bare_zip():
    payload = {**DELIVERABLE_RESPONSE, "components": {
        **DELIVERABLE_RESPONSE["components"], "zip_code_plus_4": ""}}

    assert LobAddressVerifier._to_result(payload).std_addr_zip == "94107"


def test_an_undeliverable_response_is_a_result_not_an_error():
    """The category distinction the whole seam exists for."""
    payload = {**DELIVERABLE_RESPONSE, "deliverability": "undeliverable"}

    result = LobAddressVerifier._to_result(payload)

    assert result.deliverability == "undeliverable"


def test_an_empty_barcode_is_the_no_delivery_point_case_not_an_error():
    payload = {**DELIVERABLE_RESPONSE, "components": {
        **DELIVERABLE_RESPONSE["components"], "delivery_point_barcode": ""}}

    assert LobAddressVerifier._to_result(payload).delivery_point == ""


def test_the_unit_variants_are_recognized_verdicts():
    for verdict in (
        "deliverable_missing_unit",
        "deliverable_incorrect_unit",
        "deliverable_unnecessary_unit",
    ):
        payload = {**DELIVERABLE_RESPONSE, "deliverability": verdict}
        assert LobAddressVerifier._to_result(payload).deliverability == verdict


def test_an_unrecognized_verdict_is_an_error_not_a_verbatim_store():
    """§6's exclusion reads this column, so a value we do not understand must surface as
    an unverified row rather than silently failing to exclude a bad address."""
    payload = {**DELIVERABLE_RESPONSE, "deliverability": "probably_fine_who_knows"}

    with pytest.raises(AddressVerificationError):
        LobAddressVerifier._to_result(payload)


def test_a_missing_components_block_does_not_crash():
    payload = {"primary_line": "1 MAIN ST", "deliverability": "undeliverable"}

    result = LobAddressVerifier._to_result(payload)

    assert result.delivery_point == ""
    assert result.has_components is False


def test_the_verifier_requires_a_key():
    with pytest.raises(ValueError):
        LobAddressVerifier("")
