"""Phase 4 gate: each of the ten rules has a scenario that fires it and a near-miss
that stays silent. Rules are evaluated directly against the read-only DB."""

from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

import psycopg
from psycopg.types.json import Json

from config.params import DEFAULT_PARAMS
from judgment.rules.activation_partial import RULE as activation_partial
from judgment.rules.activation_stalled import RULE as activation_stalled
from judgment.rules.approval_pending import RULE as approval_pending
from judgment.rules.demo_no_show import RULE as demo_no_show
from judgment.rules.hot_response import RULE as hot_response
from judgment.rules.lost_aging import RULE as lost_aging
from judgment.rules.orphan_events import RULE as orphan_events
from judgment.rules.quiet_reengage import RULE as quiet_reengage
from judgment.rules.returned_mail import RULE as returned_mail
from judgment.rules.wave_anomaly import RULE as wave_anomaly

AS_OF = date(2026, 7, 1)


def _dt(days_ago: int) -> datetime:
    return datetime.combine(AS_OF - timedelta(days=days_ago), datetime.min.time(), tzinfo=UTC)


def _evaluate(readonly_url, rule, as_of=AS_OF, params=DEFAULT_PARAMS):
    with psycopg.connect(readonly_url) as conn:
        conn.read_only = True
        with conn.cursor() as cur:
            return rule.evaluate(cur, params, as_of)


def _contact(conn, stage="prospect", owner="young") -> UUID:
    contact_id = uuid4()
    with conn.cursor() as cur:
        cur.execute(
            "insert into contacts (id, trade, stage_snapshot, owner) values (%s, 'plumber', %s, %s)",
            (contact_id, stage, owner),
        )
    conn.commit()
    return contact_id


def _event(conn, contact_id, etype, at):
    with conn.cursor() as cur:
        cur.execute(
            "insert into events (contact_id, source, type, occurred_at, payload) "
            "values (%s, 'nmc', %s, %s, %s)",
            (contact_id, etype, at, Json({})),
        )
    conn.commit()


def _activation(conn, contact_id, signed_days_ago, first_lead=None, forwarding=None, calendar=None):
    with conn.cursor() as cur:
        cur.execute(
            "insert into activation (contact_id, signed_up_at, first_lead_at, forwarding_at, calendar_at) "
            "values (%s, %s, %s, %s, %s)",
            (contact_id, _dt(signed_days_ago), first_lead, forwarding, calendar),
        )
    conn.commit()


def _wave(conn, status="sent", scheduled=None) -> tuple[UUID, UUID]:
    variant_id, wave_id = uuid4(), uuid4()
    with conn.cursor() as cur:
        cur.execute(
            "insert into variants (id, name, hypothesis, creative) values (%s, %s, 'h', %s)",
            (variant_id, f"v-{variant_id}", Json({})),
        )
        cur.execute(
            "insert into waves (id, name, drop_number, audience_rule, variant_split, status, scheduled_for) "
            "values (%s, %s, 1, %s, %s, %s, %s)",
            (wave_id, f"w-{wave_id}", Json({}), Json({}), status, scheduled),
        )
    conn.commit()
    return wave_id, variant_id


def _piece(conn, wave_id, variant_id, status, i):
    contact_id = _contact(conn)
    with conn.cursor() as cur:
        cur.execute(
            "insert into pieces (contact_id, wave_id, variant_id, mailer_code, status) "
            "values (%s, %s, %s, %s, %s)",
            (contact_id, wave_id, variant_id, f"mc-{wave_id}-{i}", status),
        )
    conn.commit()


# --- hot_response --------------------------------------------------------------


def test_hot_response_fires_for_new_responder(clean_db, owner_conn, readonly_url):
    contact_id = _contact(owner_conn, stage="responded")
    assert [h.contact_id for h in _evaluate(readonly_url, hot_response)] == [contact_id]


def test_hot_response_near_miss_already_nudged(clean_db, owner_conn, readonly_url):
    contact_id = _contact(owner_conn, stage="responded")
    _event(owner_conn, contact_id, "nudge.sent", _dt(1))
    assert _evaluate(readonly_url, hot_response) == []


# --- activation_stalled --------------------------------------------------------


def test_activation_stalled_fires(clean_db, owner_conn, readonly_url):
    contact_id = _contact(owner_conn, stage="won")
    _activation(owner_conn, contact_id, 20)
    assert [h.contact_id for h in _evaluate(readonly_url, activation_stalled)] == [contact_id]


def test_activation_stalled_near_miss_recent_signup(clean_db, owner_conn, readonly_url):
    contact_id = _contact(owner_conn, stage="won")
    _activation(owner_conn, contact_id, 10)
    assert _evaluate(readonly_url, activation_stalled) == []


# --- activation_partial --------------------------------------------------------


def test_activation_partial_fires(clean_db, owner_conn, readonly_url):
    contact_id = _contact(owner_conn, stage="won")
    _activation(owner_conn, contact_id, 7)  # forwarding+calendar null, 4 < 7 < 14
    assert [h.contact_id for h in _evaluate(readonly_url, activation_partial)] == [contact_id]


def test_activation_partial_near_miss_setup_complete(clean_db, owner_conn, readonly_url):
    contact_id = _contact(owner_conn, stage="won")
    _activation(owner_conn, contact_id, 7, forwarding=_dt(6), calendar=_dt(6))
    assert _evaluate(readonly_url, activation_partial) == []


# --- demo_no_show --------------------------------------------------------------


def test_demo_no_show_fires(clean_db, owner_conn, readonly_url):
    contact_id = _contact(owner_conn, stage="responded")
    _event(owner_conn, contact_id, "demo.no_show", _dt(1))
    assert [h.contact_id for h in _evaluate(readonly_url, demo_no_show)] == [contact_id]


def test_demo_no_show_near_miss_rebooked(clean_db, owner_conn, readonly_url):
    contact_id = _contact(owner_conn, stage="responded")
    _event(owner_conn, contact_id, "demo.no_show", _dt(2))
    _event(owner_conn, contact_id, "demo.booked", _dt(1))
    assert _evaluate(readonly_url, demo_no_show) == []


# --- quiet_reengage ------------------------------------------------------------


def test_quiet_reengage_fires(clean_db, owner_conn, readonly_url):
    contact_id = _contact(owner_conn, stage="in_conversation")
    _event(owner_conn, contact_id, "sms.inbound", _dt(6))
    assert [h.contact_id for h in _evaluate(readonly_url, quiet_reengage)] == [contact_id]


def test_quiet_reengage_near_miss_recent_inbound(clean_db, owner_conn, readonly_url):
    contact_id = _contact(owner_conn, stage="in_conversation")
    _event(owner_conn, contact_id, "sms.inbound", _dt(2))
    assert _evaluate(readonly_url, quiet_reengage) == []


# --- lost_aging ----------------------------------------------------------------


def test_lost_aging_fires(clean_db, owner_conn, readonly_url):
    contact_id = _contact(owner_conn, stage="in_conversation")
    _event(owner_conn, contact_id, "sms.inbound", _dt(40))
    _event(owner_conn, contact_id, "nudge.sent", _dt(20))
    assert [h.contact_id for h in _evaluate(readonly_url, lost_aging)] == [contact_id]


def test_lost_aging_near_miss_never_nudged(clean_db, owner_conn, readonly_url):
    contact_id = _contact(owner_conn, stage="in_conversation")
    _event(owner_conn, contact_id, "sms.inbound", _dt(40))
    assert _evaluate(readonly_url, lost_aging) == []


# --- returned_mail (roll-up) ---------------------------------------------------


def test_returned_mail_fires_rollup(clean_db, owner_conn, readonly_url):
    contact_id = _contact(owner_conn)
    _event(owner_conn, contact_id, "piece.returned", _dt(3))
    _event(owner_conn, contact_id, "piece.returned", _dt(2))
    hits = _evaluate(readonly_url, returned_mail)
    assert len(hits) == 1
    assert hits[0].contact_id is None
    assert hits[0].facts["count"] == 1


def test_returned_mail_near_miss_single_return(clean_db, owner_conn, readonly_url):
    contact_id = _contact(owner_conn)
    _event(owner_conn, contact_id, "piece.returned", _dt(2))
    assert _evaluate(readonly_url, returned_mail) == []


# --- orphan_events (roll-up) ---------------------------------------------------


def _seed_orphans(conn, n):
    with conn.cursor() as cur:
        for i in range(n):
            cur.execute(
                "insert into events (source, type, occurred_at, external_id) "
                "values ('posthog', 'page.visit', %s, %s)",
                (_dt(1), f"orphan-{i}"),
            )
    conn.commit()


def test_orphan_events_fires_over_threshold(clean_db, owner_conn, readonly_url):
    _seed_orphans(owner_conn, 21)
    hits = _evaluate(readonly_url, orphan_events)
    assert len(hits) == 1
    assert hits[0].facts["count"] == 21


def test_orphan_events_near_miss_under_threshold(clean_db, owner_conn, readonly_url):
    _seed_orphans(owner_conn, 5)
    assert _evaluate(readonly_url, orphan_events) == []


# --- wave_anomaly --------------------------------------------------------------


def test_wave_anomaly_fires_on_high_failure(clean_db, owner_conn, readonly_url):
    wave_id, variant_id = _wave(owner_conn)
    for i in range(10):
        _piece(owner_conn, wave_id, variant_id, "returned" if i < 2 else "delivered", i)
    assert [h.wave_id for h in _evaluate(readonly_url, wave_anomaly)] == [wave_id]


def test_wave_anomaly_near_miss_low_failure(clean_db, owner_conn, readonly_url):
    wave_id, variant_id = _wave(owner_conn)
    for i in range(20):
        _piece(owner_conn, wave_id, variant_id, "returned" if i < 1 else "delivered", i)
    assert _evaluate(readonly_url, wave_anomaly) == []


# --- approval_pending ----------------------------------------------------------


def test_approval_pending_fires(clean_db, owner_conn, readonly_url):
    wave_id, _ = _wave(owner_conn, status="draft", scheduled=AS_OF + timedelta(days=2))
    assert [h.wave_id for h in _evaluate(readonly_url, approval_pending)] == [wave_id]


def test_approval_pending_near_miss_far_out(clean_db, owner_conn, readonly_url):
    _wave(owner_conn, status="draft", scheduled=AS_OF + timedelta(days=10))
    assert _evaluate(readonly_url, approval_pending) == []
