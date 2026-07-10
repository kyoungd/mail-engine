"""Phase 0 gate: the event taxonomy is a closed set — known types validate,
unknown types are rejected."""

from domain.taxonomy import EVENT_TYPES, is_valid_type


def test_every_listed_type_is_valid():
    assert all(is_valid_type(t) for t in EVENT_TYPES)


def test_a_known_type_validates():
    assert is_valid_type("piece.delivered")


def test_unknown_type_is_rejected():
    assert not is_valid_type("piece.exploded")


def test_empty_string_is_rejected():
    assert not is_valid_type("")
