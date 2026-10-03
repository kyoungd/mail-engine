"""The outcome preview over the API: GET /v1/contacts/{id}/outcome-preview[?call_id=]."""

from datetime import date

from tests.acceptance import test_api
from tests.acceptance.test_api import _act, _batch, _contact, _get, _ok, _refused

api, reps = test_api.api, test_api.reps

CALL_OUTCOMES = ["no_answer", "left_voicemail", "owner_unavailable", "busy", "call_not_placed"]
CARD_OUTCOMES = ["spoke", "follow_up", "not_interested", "wrong_number", "signed_up"]


def test_the_outcome_preview_route(api, reps, owner_conn):
    rep = reps()
    contact = _contact(owner_conn)
    _batch(rep, contact)
    call = _ok(_act(api, f"/contacts/{contact}/calls", {"confirm_outside_hours": True},
                    rep=rep))["result"]

    on_call = _ok(_get(api, f"/contacts/{contact}/outcome-preview", rep=rep,
                       params={"call_id": call["call_id"]}))["outcomes"]
    assert sorted(on_call) == sorted(CALL_OUTCOMES + CARD_OUTCOMES)
    no_answer = on_call["no_answer"]
    assert set(no_answer) == {"list", "reason", "due", "rest_until", "pause_until"}
    assert (no_answer["list"], no_answer["reason"]) == ("waiting", "due_later")
    assert date.fromisoformat(no_answer["due"]).isoformat() == no_answer["due"]

    from_card = _ok(_get(api, f"/contacts/{contact}/outcome-preview", rep=rep))["outcomes"]
    assert sorted(from_card) == sorted(CARD_OUTCOMES)
    assert from_card["spoke"] == {"list": "follow_up", "reason": None, "due": None,
                                  "rest_until": None, "pause_until": None}


def test_the_outcome_preview_route_refuses_like_recording(api, reps, owner_conn):
    rep, other = reps(), reps()
    mine, theirs = _contact(owner_conn), _contact(owner_conn)
    _batch(rep, mine)
    _batch(other, theirs)
    their_call = _ok(_act(api, f"/contacts/{theirs}/calls", {"confirm_outside_hours": True},
                          rep=other))["result"]
    _refused(_get(api, f"/contacts/{mine}/outcome-preview", rep=rep,
                  params={"call_id": their_call["call_id"]}), 409, "no_call")
    _refused(_get(api, f"/contacts/{theirs}/outcome-preview", rep=rep), 404, "no_contact")
