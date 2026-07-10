"""Phase 4 gate: the discipline that keeps the nudge channel trusted — budget with
priority overflow, per-contact cooldown (broken only by a new inbound), expiry, human
actions respected, composer fallback, silence as a valid output, and every nudge logged
as an event. Uses as_of = today so record_nudge's timestamps align with seeded events."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import psycopg
from psycopg.types.json import Json

from judgment import digest
from service.nudges import expire_stale_actions

AS_OF = datetime.now(UTC).date()


def _at(days_from_now: int) -> datetime:
    return datetime.combine(AS_OF + timedelta(days=days_from_now), datetime.min.time(), tzinfo=UTC)


def _contact(conn, stage="prospect", owner="young") -> UUID:
    contact_id = uuid4()
    with conn.cursor() as cur:
        cur.execute(
            "insert into contacts (id, trade, stage_snapshot, owner) values (%s, 'plumber', %s, %s)",
            (contact_id, stage, owner),
        )
    conn.commit()
    return contact_id


def _stalled(conn) -> UUID:
    contact_id = _contact(conn, stage="won")
    with conn.cursor() as cur:
        cur.execute(
            "insert into activation (contact_id, signed_up_at) values (%s, %s)",
            (contact_id, _at(-20)),
        )
    conn.commit()
    return contact_id


def test_budget_caps_at_five_and_defers_the_rest(clean_db, owner_conn):
    for _ in range(11):
        _stalled(owner_conn)

    result = digest.run(AS_OF)

    assert len(result.sent.get("young", [])) == 5
    assert len(result.deferred) == 6


def test_overflow_is_deferred_in_priority_order(clean_db, owner_conn):
    for _ in range(3):
        _stalled(owner_conn)  # activation_stalled, priority 2
    for _ in range(3):
        _contact(owner_conn, stage="responded")  # hot_response, priority 1

    result = digest.run(AS_OF)

    sent = result.sent["young"]
    assert len(sent) == 5
    assert sum(1 for n in sent if n.rule == "hot_response") == 3  # priority 1 all sent
    assert {n.rule for n in result.deferred} == {"activation_stalled"}


def test_cooldown_suppresses_repeat_then_reevaluates_fresh(clean_db, owner_conn):
    _stalled(owner_conn)

    first = digest.run(AS_OF)
    assert len(first.sent["young"]) == 1

    within = digest.run(AS_OF + timedelta(days=1))  # inside 3-day cooldown
    assert within.sent.get("young", []) == []

    after = digest.run(AS_OF + timedelta(days=4))  # cooldown passed — fires fresh
    assert len(after.sent["young"]) == 1


def test_new_inbound_breaks_cooldown(clean_db, owner_conn):
    contact_id = _stalled(owner_conn)
    digest.run(AS_OF)

    with owner_conn.cursor() as cur:
        cur.execute(
            "insert into events (contact_id, source, type, occurred_at, payload) "
            "values (%s, 'nmc', 'sms.inbound', %s, %s)",
            (contact_id, _at(1), Json({})),
        )
    owner_conn.commit()

    reengaged = digest.run(AS_OF + timedelta(days=1))  # inside cooldown, but inbound broke it
    assert len(reengaged.sent["young"]) == 1


def test_human_next_action_is_never_overwritten(clean_db, owner_conn, readonly_url):
    contact_id = _stalled(owner_conn)
    with owner_conn.cursor() as cur:
        cur.execute(
            "update contacts set next_action_at = %s, next_action_note = 'call thursday' "
            "where id = %s",
            (AS_OF + timedelta(days=3), contact_id),
        )
    owner_conn.commit()

    result = digest.run(AS_OF)

    assert all(n.contact_id != contact_id for n in result.sent.get("young", []))
    with psycopg.connect(readonly_url) as conn:
        with conn.cursor() as cur:
            cur.execute("select next_action_note from contacts where id = %s", (contact_id,))
            row = cur.fetchone()
            assert row is not None
            assert row[0] == "call thursday"


def test_expiry_clears_a_stale_slot_but_not_a_future_one(clean_db, owner_conn, readonly_url):
    stale = _contact(owner_conn)
    future = _contact(owner_conn)
    with owner_conn.cursor() as cur:
        cur.execute(
            "update contacts set next_action_at = %s, next_action_note = 'old' where id = %s",
            (AS_OF - timedelta(days=10), stale),
        )
        cur.execute(
            "update contacts set next_action_at = %s, next_action_note = 'soon' where id = %s",
            (AS_OF + timedelta(days=2), future),
        )
    owner_conn.commit()

    expire_stale_actions(AS_OF, 5)

    with psycopg.connect(readonly_url) as conn:
        with conn.cursor() as cur:
            cur.execute("select next_action_at from contacts where id = %s", (stale,))
            stale_row = cur.fetchone()
            assert stale_row is not None and stale_row[0] is None
            cur.execute("select next_action_at from contacts where id = %s", (future,))
            future_row = cur.fetchone()
            assert future_row is not None and future_row[0] is not None


class _FailingAi:
    def complete(self, prompt: str) -> str:
        raise RuntimeError("model down")


class _WorkingAi:
    def complete(self, prompt: str) -> str:
        return "Call them today — signed up 20 days ago, never activated."


def test_composer_falls_back_to_template_on_model_failure(clean_db, owner_conn):
    _stalled(owner_conn)
    result = digest.run(AS_OF, ai_client=_FailingAi())
    sent = result.sent["young"]
    assert len(sent) == 1
    assert sent[0].brief.startswith("[activation_stalled]")


def test_composer_uses_the_model_when_it_works(clean_db, owner_conn):
    _stalled(owner_conn)
    result = digest.run(AS_OF, ai_client=_WorkingAi())
    assert result.sent["young"][0].brief == "Call them today — signed up 20 days ago, never activated."


def test_a_zero_hit_night_sends_nothing(clean_db, owner_conn):
    _contact(owner_conn, stage="prospect")
    result = digest.run(AS_OF)
    assert result.sent == {}
    assert result.deferred == []


def test_every_sent_nudge_is_logged_as_an_event(clean_db, owner_conn, readonly_url):
    contact_id = _stalled(owner_conn)

    digest.run(AS_OF)

    with psycopg.connect(readonly_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select contact_id, payload from events where type = 'nudge.sent' and source = 'system'"
            )
            rows = cur.fetchall()
    assert len(rows) == 1
    contact, payload = rows[0]
    assert contact == contact_id
    assert payload["rule"] == "activation_stalled"
    assert "brief" in payload
