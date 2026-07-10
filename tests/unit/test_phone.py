"""E.164 normalization — the shared key the resolution chain depends on."""

import pytest

from domain.phone import to_e164


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("(818) 679-3565", "+18186793565"),
        ("818-679-3565", "+18186793565"),
        ("1-818-679-3565", "+18186793565"),
        ("+18186793565", "+18186793565"),
        ("18186793565", "+18186793565"),
        ("818.679.3565", "+18186793565"),
    ],
)
def test_valid_numbers_normalize(raw, expected):
    assert to_e164(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ["", "123", "abc", None, "123456789012", "+44 20 7946 0958"],
)
def test_unnormalizable_numbers_return_none(raw):
    assert to_e164(raw) is None
