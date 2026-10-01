"""The rule (docs/contact-engine/05b-the-rule.md §4).

Each contact's state is one `contact_state` row, written by the act that changes it in
that act's transaction, under the contact's lock. The list is read from that row, the
rep's current settings, part 2's block, the closings in the call record, and the
contact's zones. Dates are whole days and never come early in any of its zones.
"""

import calendar
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from psycopg import sql

from config.params import HOUSE_PARTNER_ID
from db.session import transaction
from domain.errors import ValidationError
from service import calls, zones
from service.dnc import BLOCKED_SQL
from service.sale import SOLD_SQL

CHOICES = {
    "voicemails": (1, 2, 3),
    "calls": (3, 5, 8),
    "days_between": (3, 5, 7),
    "rest_months": (1, 3, 6),
}
CLOSINGS = {"signed_up": "customer", "wrong_number": "wrong_number",
            "not_interested": "not_interested"}
MOVES = frozenset({"got_callback", "closed"})


@dataclass(frozen=True)
class Settings:
    voicemails: int = 2
    calls: int = 5
    days_between: int = 3
    rest_months: int = 3


@dataclass(frozen=True)
class State:
    list: str
    reason: str | None = None
    calls: int = 0
    voicemails: int = 0
    due: date | None = None
    rest_until: date | None = None
    pause_until: date | None = None


@dataclass(frozen=True)
class Lists:
    by_contact: dict[UUID, State]
    calls_received: list[UUID]


def _after_lock(cur) -> None:
    """Called once per verb that locks a contact, right after the lock."""


def _aware(at: datetime) -> None:
    if at.tzinfo is None:
        raise ValidationError("bad_time", "at must carry a time zone")


def _check_rep(cur, rep: UUID) -> None:
    cur.execute("select 1 from partners where id = %s", (rep,))
    if rep == HOUSE_PARTNER_ID or cur.fetchone() is None:
        raise ValidationError("bad_rep", f"no rep {rep}")


def add_months(d: date, n: int) -> date:
    month = d.month - 1 + n
    year = d.year + month // 12
    month = month % 12 + 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def _date_of(moment: datetime, zone_set: frozenset[str]) -> date:
    """A moment's date: its latest local date across the zones."""
    if not zone_set:
        return moment.astimezone(UTC).date()
    return max(moment.astimezone(ZoneInfo(z)).date() for z in zone_set)


def _arrived(day: date, at: datetime, zone_set: frozenset[str]) -> bool:
    """Day X has arrived when the earliest local date of `at` across the zones is ≥ X."""
    if not zone_set:
        return at.astimezone(UTC).date() >= day
    return min(at.astimezone(ZoneInfo(z)).date() for z in zone_set) >= day


# --- settings ---------------------------------------------------------------------


def _settings(cur, rep: UUID) -> Settings:
    cur.execute(
        "select voicemails, calls, days_between, rest_months from rep_settings "
        "where rep_id = %s",
        (rep,),
    )
    row = cur.fetchone()
    return Settings(*row) if row else Settings()


def get_settings(rep: UUID) -> Settings:
    with transaction() as conn:
        with conn.cursor() as cur:
            _check_rep(cur, rep)
            return _settings(cur, rep)


def save_settings(rep: UUID, voicemails: int, calls_: int, days_between: int,
                  rest_months: int, at: datetime) -> str:
    _aware(at)
    values = {"voicemails": voicemails, "calls": calls_, "days_between": days_between,
              "rest_months": rest_months}
    with transaction() as conn:
        with conn.cursor() as cur:
            _check_rep(cur, rep)
            for name, value in values.items():
                if value not in CHOICES[name]:
                    raise ValidationError("bad_setting", f"{name} must be one of "
                                          f"{CHOICES[name]}, not {value!r}")
            cur.execute(
                "insert into rep_settings (rep_id, voicemails, calls, days_between, "
                "rest_months, updated_at) values (%s,%s,%s,%s,%s,%s) "
                "on conflict (rep_id) do update set voicemails = excluded.voicemails, "
                "calls = excluded.calls, days_between = excluded.days_between, "
                "rest_months = excluded.rest_months, updated_at = excluded.updated_at",
                (rep, voicemails, calls_, days_between, rest_months, at),
            )
    return "saved"


def restore_defaults(rep: UUID, at: datetime) -> str:
    _aware(at)
    with transaction() as conn:
        with conn.cursor() as cur:
            _check_rep(cur, rep)
            cur.execute("delete from rep_settings where rep_id = %s", (rep,))
    return "restored"


# --- writing the state ------------------------------------------------------------


def _write_state(cur, contact_id: UUID, change: dict[str, Any]) -> None:
    """The one writer of `contact_state`: create the row at the start, then set
    `change`, in the caller's transaction (the caller holds the contact's lock)."""
    cur.execute(
        "insert into contact_state (contact_id, updated_at) values (%s, %s) "
        "on conflict (contact_id) do nothing",
        (contact_id, change["updated_at"]),
    )
    cur.execute(
        sql.SQL("update contact_state set {} where contact_id = %s").format(
            sql.SQL(", ").join(
                sql.SQL("{} = %s").format(sql.Identifier(k)) for k in change
            )
        ),
        [*change.values(), contact_id],
    )


def _row(cur, contact_id: UUID) -> tuple[str, int, int]:
    cur.execute(
        "select list, calls, voicemails from contact_state where contact_id = %s",
        (contact_id,),
    )
    row = cur.fetchone()
    return row if row else ("sequence", 0, 0)


def apply_outcome(cur, contact_id: UUID, outcome: str, happened: bool,
                  opened_at: datetime | None, at: datetime) -> None:
    """§4.3: an outcome, judged on the list as it stands before it."""
    current, count, voicemails = _row(cur, contact_id)
    change: dict[str, Any] = {}
    if happened and current == "sequence":
        change.update(
            calls=count + 1,
            voicemails=voicemails + (1 if outcome == "left_voicemail" else 0),
            last_call_at=opened_at,
            last_call_busy=outcome == "busy",
        )
    if outcome in ("spoke", "follow_up"):
        change["list"] = "follow_up"
    if change:
        change["updated_at"] = at
        _write_state(cur, contact_id, change)


def apply_resolution(cur, contact_id: UUID, rep: UUID, resolution: str,
                     at: datetime) -> None:
    """§4.3: only the holder's resolution of a call received moves the contact."""
    cur.execute("select owner_id from contacts where id = %s", (contact_id,))
    holder = cur.fetchone()
    if holder is None or holder[0] != rep:
        return
    target = {"spoke": "follow_up", "call_back": "got_callback"}.get(resolution)
    if target is not None:
        _write_state(cur, contact_id, {"list": target, "updated_at": at})


# --- reading the state ------------------------------------------------------------


def _states(cur, rep: UUID, contact_ids: list[UUID], at: datetime) -> dict[UUID, State]:
    """§4.4 for each contact, read in bulk on the caller's cursor; no lock taken."""
    if not contact_ids:
        return {}
    s = _settings(cur, rep)
    cur.execute(
        "select contact_id, outcome from calls where contact_id = any(%s) "
        "and outcome in ('signed_up', 'wrong_number', 'not_interested') "
        "and undone_at is null",
        (contact_ids,),
    )
    closings: dict[UUID, set[str]] = {}
    for contact_id, outcome in cur.fetchall():
        closings.setdefault(contact_id, set()).add(outcome)
    cur.execute(
        sql.SQL(
            "select c.id, c.phone_e164, c.addr_state, {blocked}, {sold}, "
            "(select z.zone from contact_zones z where z.contact_id = c.id "
            " order by z.seq desc limit 1), "
            "coalesce(st.list, 'sequence'), coalesce(st.rep_closed, false), "
            "coalesce(st.calls, 0), coalesce(st.voicemails, 0), st.last_call_at, "
            "coalesce(st.last_call_busy, false), st.pause_until "
            "from contacts c left join contact_state st on st.contact_id = c.id "
            "where c.id = any(%s)"
        ).format(blocked=BLOCKED_SQL, sold=SOLD_SQL),
        (contact_ids,),
    )
    out: dict[UUID, State] = {}
    for (contact_id, phone, state, blocked, sold, set_zone, lst, rep_closed, count,
         voicemails, last_call_at, last_busy, pause_until) in cur.fetchall():
        zone_set = (frozenset({set_zone}) if set_zone
                    else zones._evidence(phone, state))  # noqa: SLF001
        out[contact_id] = _decide(
            s, zone_set, at, blocked=blocked, sold=sold,
            closed=closings.get(contact_id, set()),
            rep_closed=rep_closed, lst=lst, count=count, voicemails=voicemails,
            last_call_at=last_call_at, last_busy=last_busy, pause_until=pause_until,
        )
    return out


def _decide(s: Settings, zone_set: frozenset[str], at: datetime, *, blocked: bool,
            sold: bool, closed: set[str], rep_closed: bool, lst: str, count: int, voicemails: int,
            last_call_at: datetime | None, last_busy: bool,
            pause_until: date | None) -> State:
    base = State(list="", calls=count, voicemails=voicemails)
    if blocked:
        return replace(base, list="closed", reason="asked_not_to_be_called")
    if sold:
        return replace(base, list="closed", reason="customer")
    for outcome in ("wrong_number", "not_interested"):
        if outcome in closed:
            return replace(base, list="closed", reason=CLOSINGS[outcome])
    if rep_closed:
        return replace(base, list="closed", reason="closed")
    if lst == "sequence" and count and (voicemails >= s.voicemails or count >= s.calls):
        assert last_call_at is not None
        rest_until = add_months(_date_of(last_call_at, zone_set), s.rest_months)
        reason = "rest_over" if _arrived(rest_until, at, zone_set) else "resting"
        return replace(base, list="limit_reached", reason=reason, rest_until=rest_until)
    if pause_until is not None and not _arrived(pause_until, at, zone_set):
        return replace(base, list="waiting", reason="paused", pause_until=pause_until)
    if lst in ("got_callback", "follow_up"):
        return replace(base, list=lst)
    if count == 0:
        return replace(base, list="never_called")
    assert last_call_at is not None
    due = _date_of(last_call_at, zone_set) + timedelta(
        days=1 if last_busy else s.days_between)
    if _arrived(due, at, zone_set):
        return replace(base, list="all_due_retries", due=due)
    return replace(base, list="waiting", reason="due_later", due=due)


def _holder(cur, contact_id: UUID, rep: UUID, *, lock: bool) -> None:
    cur.execute(
        "select owner_id from contacts where id = %s" + (" for update" if lock else ""),
        (contact_id,),
    )
    row = cur.fetchone()
    if row is None:
        raise ValidationError("no_contact", f"no contact {contact_id}")
    if lock:
        _after_lock(cur)
    if row[0] != rep:
        raise ValidationError("not_yours", "the rep does not hold this contact")


def contact_state(rep: UUID, contact_id: UUID, at: datetime) -> State:
    _aware(at)
    with transaction() as conn:
        with conn.cursor() as cur:
            _check_rep(cur, rep)
            _holder(cur, contact_id, rep, lock=False)
            return _states(cur, rep, [contact_id], at)[contact_id]


def rep_lists(rep: UUID, at: datetime) -> Lists:
    _aware(at)
    with transaction() as conn:
        with conn.cursor() as cur:
            _check_rep(cur, rep)
            cur.execute("select id from contacts where owner_id = %s", (rep,))
            held = [r[0] for r in cur.fetchall()]
            states = _states(cur, rep, held, at)
            cur.execute(
                "select id from calls_received where rep_id = %s and resolution is null "
                "order by received_at, id",
                (rep,),
            )
            received = [r[0] for r in cur.fetchall()]
    return Lists(by_contact=states, calls_received=received)


def refuse_call(cur, rep: UUID, contact_id: UUID, at: datetime) -> None:
    """§4.6: the rule's refusals for opening a call, on the caller's cursor."""
    st = _states(cur, rep, [contact_id], at)[contact_id]
    if st.list == "closed":
        raise ValidationError("closed", f"closed: {st.reason}", {"reason": st.reason})
    if st.list == "limit_reached":
        raise ValidationError("limit_reached", "the sequence has ended",
                              {"rest_until": st.rest_until})
    if st.list == "waiting" and st.reason == "paused":
        raise ValidationError("paused", "paused", {"until": st.pause_until})
    if st.list == "waiting":
        raise ValidationError("not_due", "not due yet", {"due": st.due})


def may_call(rep: UUID, contact_id: UUID, at: datetime) -> str:
    """The answer `open_call` would give, without opening a call."""
    _aware(at)
    with transaction() as conn:
        with conn.cursor() as cur:
            checked = calls._check_open(cur, rep, contact_id, at, False,  # noqa: SLF001
                                        lock=False)
    return checked.phone


# --- what the rep asks for --------------------------------------------------------


def _start(cur, rep: UUID, contact_id: UUID, *, any_call: bool) -> None:
    _check_rep(cur, rep)
    _holder(cur, contact_id, rep, lock=True)
    if any_call:
        cur.execute(
            "select 1 from calls where contact_id = %s and opened_at is not null "
            "and outcome is null and cleared_at is null",
            (contact_id,),
        )
        if cur.fetchone() is not None:
            raise ValidationError("call_open", "a call is open on this contact")
    else:
        own = calls._own_open_call(cur, rep, contact_id)  # noqa: SLF001
        if own is not None:
            raise ValidationError("call_open", "your call is open on this contact",
                                  {"call_id": own})


def _zones_of(cur, contact_id: UUID) -> frozenset[str]:
    cur.execute(
        "select c.phone_e164, c.addr_state, (select z.zone from contact_zones z "
        "where z.contact_id = c.id order by z.seq desc limit 1) "
        "from contacts c where c.id = %s",
        (contact_id,),
    )
    phone, state, set_zone = cur.fetchone()
    return frozenset({set_zone}) if set_zone else zones._evidence(phone, state)  # noqa: SLF001


def move(rep: UUID, contact_id: UUID, to: str, at: datetime) -> str:
    _aware(at)
    with transaction() as conn:
        with conn.cursor() as cur:
            _start(cur, rep, contact_id, any_call=False)
            if to not in MOVES:
                raise ValidationError("bad_list", f"cannot move to {to!r}")
            if _states(cur, rep, [contact_id], at)[contact_id].list == "closed":
                raise ValidationError("closed_already", "the contact is closed")
            change = {"list": "got_callback"} if to == "got_callback" else {"rep_closed": True}
            _write_state(cur, contact_id, {**change, "updated_at": at})
    return "moved"


def pause(rep: UUID, contact_id: UUID, until: date, at: datetime) -> str:
    _aware(at)
    with transaction() as conn:
        with conn.cursor() as cur:
            _start(cur, rep, contact_id, any_call=False)
            st = _states(cur, rep, [contact_id], at)[contact_id]
            if st.list == "closed":
                raise ValidationError("closed_already", "the contact is closed")
            if st.list == "limit_reached":
                raise ValidationError("not_pausable", "the sequence has ended")
            if _arrived(until, at, _zones_of(cur, contact_id)):
                raise ValidationError("bad_date", f"{until} has already arrived")
            _write_state(cur, contact_id, {"pause_until": until, "updated_at": at})
    return "paused"


def unpause(rep: UUID, contact_id: UUID, at: datetime) -> str:
    _aware(at)
    with transaction() as conn:
        with conn.cursor() as cur:
            _start(cur, rep, contact_id, any_call=False)
            st = _states(cur, rep, [contact_id], at)[contact_id]
            if not (st.list == "waiting" and st.reason == "paused"):
                raise ValidationError("not_paused", "the contact is not paused")
            _write_state(cur, contact_id, {"pause_until": None, "updated_at": at})
    return "unpaused"


def restart(rep: UUID, contact_id: UUID, at: datetime) -> str:
    _aware(at)
    with transaction() as conn:
        with conn.cursor() as cur:
            _start(cur, rep, contact_id, any_call=True)
            st = _states(cur, rep, [contact_id], at)[contact_id]
            if st.list != "limit_reached":
                raise ValidationError("not_limit_reached", "the sequence has not ended")
            if st.reason == "resting":
                raise ValidationError("still_resting", f"resting until {st.rest_until}",
                                      {"rest_until": st.rest_until})
            _write_state(cur, contact_id, {
                "list": "sequence", "calls": 0, "voicemails": 0, "last_call_at": None,
                "last_call_busy": False, "pause_until": None, "updated_at": at,
            })
    return "restarted"
