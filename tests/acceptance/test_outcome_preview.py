"""The outcome preview: where a contact would land after each outcome (operator,
2026-10-03, decision 1 of the outcome lines). It is worked out by the rule that applies
a real outcome, and it changes nothing.
"""

from datetime import timedelta
from uuid import UUID

import pytest

import service.calls as calls
import service.rule as rule
from tests.acceptance import test_the_rule
from tests.acceptance.test_the_rule import AT, _call, _contact, _fresh, _refused, _sql, _state

reps = test_the_rule.reps

CALL_OUTCOMES = ["no_answer", "left_voicemail", "owner_unavailable", "busy", "call_not_placed"]
CARD_OUTCOMES = ["spoke", "follow_up", "not_interested", "wrong_number", "signed_up"]
FIELDS = ("list", "reason", "due", "rest_until", "pause_until", "calls", "voicemails")


def _start(owner_conn, rep: UUID, contact: UUID, start: str) -> None:
    if start == "one_voicemail":
        _call(owner_conn, rep, contact, AT - timedelta(days=3), "left_voicemail")
    elif start == "follow_up":
        calls.record_outcome(rep, contact, "follow_up", AT - timedelta(days=3))


def _open(owner_conn, rep: UUID, contact: UUID) -> UUID:
    _fresh(owner_conn, contact, AT)
    return calls.open_call(rep, contact, AT, confirm_outside_hours=True).call_id


@pytest.mark.parametrize("start", ["never_called", "one_voicemail", "follow_up"])
@pytest.mark.parametrize("outcome", CALL_OUTCOMES + CARD_OUTCOMES)
def test_the_preview_agrees_with_what_happens(reps, owner_conn, start, outcome):
    rep = reps()
    previewed, recorded = _contact(owner_conn, rep), _contact(owner_conn, rep)
    for contact in (previewed, recorded):
        _start(owner_conn, rep, contact, start)
    call_a, call_b = _open(owner_conn, rep, previewed), _open(owner_conn, rep, recorded)
    at = AT + timedelta(minutes=1)

    preview = rule.preview_outcomes(rep, previewed, at, call_id=call_a)
    calls.record_outcome(rep, recorded, outcome, at, call_id=call_b)

    after = _state(rep, recorded, at)
    assert {f: getattr(preview[outcome], f) for f in FIELDS} == \
        {f: getattr(after, f) for f in FIELDS}, (start, outcome)


def test_a_preview_changes_nothing(reps, owner_conn):
    rep = reps()
    contact = _contact(owner_conn, rep)
    _call(owner_conn, rep, contact, AT - timedelta(days=3), "left_voicemail")
    call_id = _open(owner_conn, rep, contact)
    read = ("select list, calls, voicemails, last_call_at, last_call_busy, pause_until, "
            "updated_at from contact_state where contact_id = %s")
    before = _sql(owner_conn, read, (contact,))
    calls_before = _sql(owner_conn, "select count(*), count(outcome) from calls "
                                    "where contact_id = %s", (contact,))
    rule.preview_outcomes(rep, contact, AT + timedelta(minutes=1), call_id=call_id)
    assert _sql(owner_conn, read, (contact,)) == before
    assert _sql(owner_conn, "select count(*), count(outcome) from calls "
                            "where contact_id = %s", (contact,)) == calls_before


def test_without_a_call_only_the_card_outcomes_and_none_is_a_call(reps, owner_conn):
    rep = reps()
    contact = _contact(owner_conn, rep)
    preview = rule.preview_outcomes(rep, contact, AT)
    assert sorted(preview) == sorted(CARD_OUTCOMES)
    assert preview["spoke"].list == "follow_up"
    assert all(st.calls == 0 for st in preview.values())


def test_refusals_match_recording(reps, owner_conn):
    rep, other = reps(), reps()
    mine, theirs = _contact(owner_conn, rep), _contact(owner_conn, other)
    their_call = _open(owner_conn, other, theirs)
    _refused("no_call", lambda: rule.preview_outcomes(rep, mine, AT, call_id=their_call))
    _refused("not_yours", lambda: rule.preview_outcomes(rep, theirs, AT))
