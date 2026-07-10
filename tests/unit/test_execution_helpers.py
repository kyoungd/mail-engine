"""Unit tests for execute_wave's pure helpers: deterministic mailer codes and
deterministic weighted variant assignment."""

from uuid import uuid4

from service.execution import _assign_variant, _mailer_code


def test_mailer_code_is_deterministic_per_wave_and_contact():
    wave, contact = uuid4(), uuid4()
    assert _mailer_code(wave, contact) == _mailer_code(wave, contact)


def test_mailer_code_differs_by_contact_and_by_wave():
    wave, other_wave = uuid4(), uuid4()
    contact, other_contact = uuid4(), uuid4()
    assert _mailer_code(wave, contact) != _mailer_code(wave, other_contact)
    assert _mailer_code(wave, contact) != _mailer_code(other_wave, contact)


def test_mailer_code_is_ten_lowercase_chars():
    code = _mailer_code(uuid4(), uuid4())
    assert len(code) == 10
    assert code == code.lower()


def test_assign_variant_is_deterministic():
    contact = uuid4()
    split = {"a": 1.0, "b": 1.0}
    assert _assign_variant(contact, split) == _assign_variant(contact, split)


def test_assign_variant_with_one_variant_always_picks_it():
    assert _assign_variant(uuid4(), {"only": 1.0}) == "only"


def test_assign_variant_distributes_across_variants():
    split = {"a": 1.0, "b": 1.0}
    seen = {_assign_variant(uuid4(), split) for _ in range(200)}
    assert seen == {"a", "b"}
