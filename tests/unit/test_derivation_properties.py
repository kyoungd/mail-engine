"""Property-based invariants of the derivation module (plan ground rule 6):
recompute determinism (order independence), suppression as an absorbing state,
and legal stage progression only. A counterexample here is a real bug in
derivation/rules.py — fix the code, never loosen the property."""

from datetime import UTC, datetime

from hypothesis import given
from hypothesis import strategies as st

from derivation.rules import derive_stage, is_suppressed
from domain.enums import ContactStage, EventSource
from domain.types import ContactFlags, Event

_EVENT_TYPES = [
    "piece.submitted",
    "piece.returned",
    "page.visit",
    "call.inbound",
    "sms.inbound",
    "sms.outbound",
    "call.answered",
    "signup.completed",
    "contact.opt_out",
    "contact.lost",
    "demo.booked",
]

# Forward progression ranks. Suppressed (absorbing) and lost (revivable) are both
# side-states reachable from / exitable to the progression, so they are excluded
# from the forward-only check rather than ranked.
_RANK = {
    ContactStage.PROSPECT: 0,
    ContactStage.IN_SEQUENCE: 1,
    ContactStage.RESPONDED: 2,
    ContactStage.IN_CONVERSATION: 3,
    ContactStage.WON: 4,
}


@st.composite
def _events(draw) -> list[Event]:
    n = draw(st.integers(min_value=0, max_value=12))
    out = []
    for _ in range(n):
        etype = draw(st.sampled_from(_EVENT_TYPES))
        day = draw(st.integers(min_value=1, max_value=28))
        hour = draw(st.integers(min_value=0, max_value=23))
        at = datetime(2026, 1, day, hour, tzinfo=UTC)
        out.append(
            Event(id=0, source=EventSource.NMC, type=etype, occurred_at=at, ingested_at=at)
        )
    return out


_flags = st.builds(ContactFlags, do_not_mail=st.booleans(), do_not_text=st.booleans())


@given(data=st.data(), flags=_flags)
def test_derive_stage_is_order_independent(data, flags):
    events = data.draw(_events())
    permuted = list(data.draw(st.permutations(events)))
    assert derive_stage(events, flags) == derive_stage(permuted, flags)


@given(data=st.data(), flags=_flags)
def test_suppression_is_absorbing(data, flags):
    events = data.draw(_events())
    if not is_suppressed(events, flags):
        at = datetime(2026, 1, 1, tzinfo=UTC)
        events = events + [
            Event(id=0, source=EventSource.NMC, type="contact.opt_out",
                  occurred_at=at, ingested_at=at)
        ]
    assert is_suppressed(events, flags)
    combined = events + data.draw(_events())
    assert is_suppressed(combined, flags)
    assert derive_stage(combined, flags) is ContactStage.SUPPRESSED


@given(data=st.data(), flags=_flags)
def test_stage_only_moves_forward_over_time(data, flags):
    events = sorted(data.draw(_events()), key=lambda e: e.occurred_at)
    last_rank = -1
    for i in range(1, len(events) + 1):
        stage = derive_stage(events[:i], flags)
        if stage in (ContactStage.SUPPRESSED, ContactStage.LOST):
            continue  # side-states, legal from any prior stage
        assert _RANK[stage] >= last_rank
        last_rank = _RANK[stage]
