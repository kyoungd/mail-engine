"""Fixture-list unit tests for the derivation definitions (data document §3).
These pin the boundaries the whole system's numbers depend on."""

from datetime import UTC, date, datetime

from derivation.rules import derive_stage, is_responded, is_suppressed, quiet_days
from domain.enums import ContactStage, EventSource
from domain.types import ContactFlags, Event

NO_FLAGS = ContactFlags()


def _dt(day: int, hour: int = 12) -> datetime:
    return datetime(2026, 1, day, hour, tzinfo=UTC)


def _ev(type: str, at: datetime) -> Event:
    return Event(id=0, source=EventSource.NMC, type=type, occurred_at=at, ingested_at=at)


# --- is_responded --------------------------------------------------------------


def test_inbound_before_any_piece_is_not_a_response():
    assert is_responded([_ev("sms.inbound", _dt(5))]) is False


def test_inbound_after_first_piece_is_a_response():
    events = [_ev("piece.submitted", _dt(1)), _ev("sms.inbound", _dt(3))]
    assert is_responded(events) is True


def test_inbound_dated_before_the_piece_does_not_count():
    events = [_ev("sms.inbound", _dt(1)), _ev("piece.submitted", _dt(3))]
    assert is_responded(events) is False


def test_inbound_at_the_same_instant_as_the_piece_is_not_a_response():
    # "after the first piece" is strict: a simultaneous inbound does not count.
    events = [_ev("piece.submitted", _dt(1)), _ev("sms.inbound", _dt(1))]
    assert is_responded(events) is False


# --- quiet_days ----------------------------------------------------------------


def test_quiet_days_is_none_without_any_inbound():
    assert quiet_days([_ev("piece.submitted", _dt(1))], date(2026, 1, 10)) is None


def test_quiet_days_counts_from_the_last_inbound():
    # QUIET_DAYS boundary: last inbound exactly 4 days before as_of reads as 4.
    events = [_ev("sms.inbound", _dt(7)), _ev("sms.inbound", _dt(11))]
    assert quiet_days(events, date(2026, 1, 15)) == 4


# --- is_suppressed -------------------------------------------------------------


def test_do_not_mail_flag_suppresses():
    assert is_suppressed([], ContactFlags(do_not_mail=True)) is True


def test_opt_out_event_suppresses():
    assert is_suppressed([_ev("contact.opt_out", _dt(1))], NO_FLAGS) is True


def test_one_returned_piece_is_not_suppression():
    assert is_suppressed([_ev("piece.returned", _dt(1))], NO_FLAGS) is False


def test_two_returned_pieces_suppress():
    events = [_ev("piece.returned", _dt(1)), _ev("piece.returned", _dt(2))]
    assert is_suppressed(events, NO_FLAGS) is True


# --- derive_stage --------------------------------------------------------------


def test_stage_prospect_when_no_events():
    assert derive_stage([], NO_FLAGS) is ContactStage.PROSPECT


def test_stage_in_sequence_after_a_piece():
    assert derive_stage([_ev("piece.submitted", _dt(1))], NO_FLAGS) is ContactStage.IN_SEQUENCE


def test_stage_responded_on_inbound_without_our_reply():
    events = [_ev("piece.submitted", _dt(1)), _ev("sms.inbound", _dt(3))]
    assert derive_stage(events, NO_FLAGS) is ContactStage.RESPONDED


def test_stage_in_conversation_once_we_reply():
    events = [
        _ev("piece.submitted", _dt(1)),
        _ev("sms.inbound", _dt(3)),
        _ev("sms.outbound", _dt(4)),
    ]
    assert derive_stage(events, NO_FLAGS) is ContactStage.IN_CONVERSATION


def test_repeated_inbound_without_our_reply_stays_responded():
    # Engagement is us replying, not the contact pinging again — a later inbound
    # is not an engage type, so the stage stays responded.
    events = [
        _ev("piece.submitted", _dt(1)),
        _ev("sms.inbound", _dt(3)),
        _ev("call.inbound", _dt(5)),
    ]
    assert derive_stage(events, NO_FLAGS) is ContactStage.RESPONDED


def test_reply_at_the_same_instant_as_the_inbound_is_not_engagement():
    # "after the first response" is strict: a simultaneous reply does not engage.
    events = [
        _ev("piece.submitted", _dt(1)),
        _ev("sms.inbound", _dt(3)),
        _ev("sms.outbound", _dt(3)),
    ]
    assert derive_stage(events, NO_FLAGS) is ContactStage.RESPONDED


def test_stage_won_on_signup():
    events = [_ev("piece.submitted", _dt(1)), _ev("signup.completed", _dt(5))]
    assert derive_stage(events, NO_FLAGS) is ContactStage.WON


def test_suppression_absorbs_even_a_won_contact():
    # Suppression is irreversible by design; an opt-out wins over signup.
    events = [_ev("signup.completed", _dt(5)), _ev("contact.opt_out", _dt(6))]
    assert derive_stage(events, NO_FLAGS) is ContactStage.SUPPRESSED
