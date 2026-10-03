"""The API (docs/contact-engine/06a-the-api.md): the only way in from outside.

Routes parse, call a verb or a read, and shape the answer; every rule is in
`service/`. An action and its request memory commit in one transaction (§4.3); a read
runs in one REPEATABLE READ, READ ONLY transaction. Run with
`uvicorn web.api:create_app --factory`.
"""

import dataclasses
import hashlib
import hmac
import json
import os
import re
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Body, FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import Response
from pydantic import BaseModel, StringConstraints
from starlette.exceptions import HTTPException

from config.params import REGIONS
from db.session import ping, request_connection
from domain.errors import ValidationError
from domain.types import RepRow
from service import (assignment, calls, dnc, reads, rep_intake, roster, rule, runs, vouch,
                     zones)

MEMORY_DAYS = 90
KEY_LIMIT = 200
_ROUTE_ID = re.compile(r"-?[0-9]+")
_REP_ID = re.compile(r"[0-9]+")
NO_CONTACT = {"code": "no_contact", "message": "no such contact", "detail": {}}


def _now() -> datetime:
    return datetime.now(UTC)


def _before_memory() -> None:
    """Called between an action's verb and its memory row."""


# --- answers ----------------------------------------------------------------------


def _plain(value: Any) -> Any:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: _plain(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, frozenset | set):
        return sorted(_plain(v) for v in value)
    if isinstance(value, list | tuple):
        return [_plain(v) for v in value]
    return value


def _text(content: Any) -> str:
    return json.dumps(_plain(content), separators=(",", ":"))


def _answer(status: int, content: Any) -> Response:
    return Response(_text(content), status_code=status, media_type="application/json")


def _error(status: int, code: str, message: str, detail: dict | None = None) -> Response:
    return _answer(status, {"code": code, "message": message, "detail": detail or {}})


class _Refused(Exception):
    def __init__(self, response: Response) -> None:
        self.response = response


def _refuse(status: int, code: str, message: str) -> _Refused:
    return _Refused(_error(status, code, message))


# --- who asks (§4.1) --------------------------------------------------------------


def _caller(request: Request, allowed: tuple[str, ...]) -> str:
    given = request.headers.get("X-API-Key", "").encode()
    keys: dict[str, str] = request.app.state.keys
    caller = next(
        (name for name, key in keys.items() if hmac.compare_digest(given, key.encode())),
        None,
    )
    if caller is None:
        raise _refuse(401, "bad_key", "no such key")
    if caller not in allowed:
        raise _refuse(403, "wrong_key", "this key may not use this route")
    return caller


def _admin(request: Request) -> str:
    name = request.headers.get("X-Admin", "").strip()
    if not name:
        raise _refuse(403, "no_admin", "an admin route names its admin")
    return name


def _rep_id(request: Request) -> int:
    raw = request.headers.get("X-Rep", "")
    if not _REP_ID.fullmatch(raw):
        raise _refuse(403, "unknown_rep", "no such rep")
    return int(raw)


def _resolve(sales_rep_id: int, allow_inactive: bool) -> UUID:
    try:
        return roster.resolve_rep(sales_rep_id, allow_inactive)
    except ValidationError as err:
        raise _refuse(403, err.code, str(err)) from err


def _key(request: Request) -> str:
    key = request.headers.get("Idempotency-Key")
    if key is None or not key.strip() or len(key) > KEY_LIMIT:
        raise _refuse(400, "no_key", "an action carries an Idempotency-Key")
    return key


def _uuid(raw: str, *, contact: bool) -> UUID:
    try:
        return UUID(raw)
    except ValueError:
        if contact:
            raise _Refused(_answer(404, NO_CONTACT)) from None
        raise _refuse(400, "bad_request", f"not an id: {raw!r}") from None


def _roster_id(raw: str) -> int:
    if not _ROUTE_ID.fullmatch(raw):
        raise _refuse(400, "bad_request", f"not a roster id: {raw!r}")
    return int(raw)


# --- the two shapes of a request --------------------------------------------------


@dataclasses.dataclass(frozen=True)
class _Asker:
    caller: str
    rep: UUID | None = None
    admin: str | None = None


def _refusal(err: ValidationError, asker: _Asker, contact: UUID | None,
             hides: bool) -> Response:
    if err.code == "bad_request":
        return _error(400, err.code, str(err))
    if err.code == "unknown_rep":
        return _error(404, err.code, str(err))
    if hides and asker.rep is not None and reads.hide(asker.rep, contact, err):
        return _answer(404, NO_CONTACT)
    return _error(409, err.code, str(err), _plain(err.detail))


def _act(
    request: Request,
    body: BaseModel | None,
    run: Callable[[_Asker, datetime], Any],
    *,
    keys: tuple[str, ...] = ("dialer", "website"),
    rep: bool = True,
    admin: bool = False,
    allow_inactive: bool = False,
    contact: UUID | None = None,
    hides: bool = False,
    who: str | None = None,
) -> Response:
    """An action (§4.3): resolve, lock the key, replay or act, remember — one
    transaction."""
    try:
        caller = _caller(request, keys)
        key = _key(request)
        actor = _admin(request) if admin else None
        sales_rep_id = _rep_id(request) if rep else None
    except _Refused as refused:
        return refused.response
    at = _now()
    body_hash = hashlib.sha256(
        json.dumps(body.model_dump(mode="json") if body is not None else None,
                   sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    asker = _Asker(caller=caller, admin=actor)
    try:
        with request_connection() as conn:
            if sales_rep_id is not None:
                asker = _Asker(caller=caller, rep=_resolve(sales_rep_id, allow_inactive))
            scope = who or (f"rep:{asker.rep}" if asker.rep else f"admin:{actor}")
            conn.execute(
                "select pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (f"{caller}:{scope}:{key}",),
            )
            stored = conn.execute(
                "select method, path, body_hash, status, answer from api_requests "
                "where caller = %s and who = %s and key = %s and at > %s",
                (caller, scope, key, at - timedelta(days=MEMORY_DAYS)),
            ).fetchone()
            if stored is not None:
                if stored[:3] != (request.method, request.url.path, body_hash):
                    raise _refuse(409, "key_mismatch",
                                  "this key was used for another request")
                return Response(stored[4], status_code=stored[3],
                                media_type="application/json",
                                headers={"Idempotent-Replay": "true"})
            answer = _text({"result": run(asker, at)})
            _before_memory()
            made = conn.execute(
                "insert into api_requests (caller, who, key, method, path, body_hash, "
                "status, answer, at) values (%s,%s,%s,%s,%s,%s,200,%s,%s) "
                "on conflict (caller, who, key) do update set method = excluded.method, "
                "path = excluded.path, body_hash = excluded.body_hash, "
                "status = excluded.status, answer = excluded.answer, at = excluded.at "
                "where api_requests.at <= %s",
                (caller, scope, key, request.method, request.url.path, body_hash,
                 answer, at, at - timedelta(days=MEMORY_DAYS)),
            )
            if made.rowcount != 1:
                raise RuntimeError("request memory: a second act for one key")
    except _Refused as refused:
        return refused.response
    except ValidationError as err:
        return _refusal(err, asker, contact, hides)
    return Response(answer, media_type="application/json")


def _read(
    request: Request,
    run: Callable[[_Asker, datetime], Any],
    *,
    keys: tuple[str, ...] = ("dialer", "website"),
    rep: bool = True,
    admin: bool = False,
    contact: UUID | None = None,
    hides: bool = False,
) -> Response:
    """A read: one REPEATABLE READ, READ ONLY transaction, no lock."""
    try:
        caller = _caller(request, keys)
        actor = _admin(request) if admin else None
        asker = _Asker(caller=caller, admin=actor)
        if rep:
            asker = _Asker(caller=caller, rep=_resolve(_rep_id(request), False))
    except _Refused as refused:
        return refused.response
    at = _now()
    try:
        with request_connection(read_only=True):
            content = run(asker, at)
    except ValidationError as err:
        return _refusal(err, asker, contact, hides)
    return _answer(200, content)


# --- bodies -----------------------------------------------------------------------

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class NameBody(BaseModel):
    name: Text


class SettingsBody(BaseModel):
    voicemails: int
    calls: int
    days_between: int
    rest_months: int


class RegionBody(BaseModel):
    region: str


class RowBody(BaseModel):
    phone: str
    business_name: str | None = None
    contact_name: str | None = None
    contact_role: str | None = None
    trade: str | None = None
    addr_city: str | None = None
    addr_state: str | None = None
    how_obtained: str | None = None


class AddBody(BaseModel):
    rows: list[RowBody]
    how_obtained: str | None = None
    confirmation: str | None = None


class CallBody(BaseModel):
    confirm_outside_hours: bool = False


class OutcomeBody(BaseModel):
    outcome: str
    call_id: UUID | None = None
    memo: str | None = None


class ReasonBody(BaseModel):
    reason: str


class MaybeReasonBody(BaseModel):
    reason: str | None = None


class TextBody(BaseModel):
    text: str


class VouchBody(BaseModel):
    reason: str | None = None
    confirmation: str | None = None


class ZoneBody(BaseModel):
    zone: str


class MoveBody(BaseModel):
    to: str


class PauseBody(BaseModel):
    until: date


class PhoneBody(BaseModel):
    phone: str


class ResolveBody(BaseModel):
    resolution: str


class AdminDncBody(BaseModel):
    phone: str
    reason: str


class LiftBody(BaseModel):
    seen: int
    reason: str


def _rep(asker: _Asker) -> UUID:
    assert asker.rep is not None
    return asker.rep


def _actor(asker: _Asker) -> str:
    assert asker.admin is not None
    return asker.admin


# --- the routes (§5) --------------------------------------------------------------


def _routes() -> APIRouter:  # noqa: C901, PLR0915
    r = APIRouter(prefix="/v1")
    website = ("website",)
    dialer = ("dialer",)

    # the roster (§4.4)
    @r.put("/reps/{sales_rep_id}")
    def make_known(request: Request, sales_rep_id: str, body: NameBody) -> Response:
        try:
            sid = _roster_id(sales_rep_id)
        except _Refused as refused:
            return refused.response
        return _act(request, body, lambda a, at: roster.make_known(sid, body.name),
                    keys=dialer, rep=False, who=f"roster:{sid}")

    @r.post("/reps/{sales_rep_id}/deactivate")
    def deactivate(request: Request, sales_rep_id: str) -> Response:
        try:
            sid = _roster_id(sales_rep_id)
        except _Refused as refused:
            return refused.response
        return _act(request, None, lambda a, at: roster.deactivate(sid),
                    keys=dialer, rep=False, who=f"roster:{sid}")

    # the rep's own
    @r.get("/regions")
    def regions(request: Request) -> Response:
        return _read(request, lambda a, at: {"regions": list(REGIONS)})

    @r.get("/me/settings")
    def get_settings(request: Request) -> Response:
        return _read(request, lambda a, at: rule.get_settings(_rep(a)))

    @r.put("/me/settings")
    def save_settings(request: Request, body: SettingsBody) -> Response:
        return _act(request, body, lambda a, at: rule.save_settings(
            _rep(a), body.voicemails, body.calls, body.days_between, body.rest_months, at),
            keys=website)

    @r.post("/me/settings/restore")
    def restore(request: Request) -> Response:
        return _act(request, None, lambda a, at: rule.restore_defaults(_rep(a), at),
                    keys=website)

    @r.get("/me/lists")
    def lists(request: Request) -> Response:
        return _read(request, lambda a, at: reads.lists(_rep(a), at))

    @r.get("/me/known-callers")
    def known_callers(request: Request) -> Response:
        return _read(request, lambda a, at: reads.known_callers(_rep(a)))

    @r.get("/me/search")
    def search(request: Request,
               q: Annotated[str, Query(min_length=2)]) -> Response:
        return _read(request, lambda a, at: reads.search(_rep(a), q, at))

    @r.post("/me/more-numbers")
    def more_numbers(request: Request, body: RegionBody) -> Response:
        key = request.headers.get("Idempotency-Key", "")

        def run(a: _Asker, at: datetime) -> dict[str, Any]:
            report = assignment.get_more_numbers(
                _rep(a), body.region,
                f"api:{a.caller}:rep:{a.rep}:{key}:{at.astimezone(UTC).date().isoformat()}",
                at,
            )
            return {"batch_id": report.batch_id, "assigned": len(report.assigned),
                    "shortfall": {k: len(v) for k, v in report.shortfall.items()},
                    "retry": report.retry}

        return _act(request, body, run)

    @r.post("/contacts")
    def add_numbers(request: Request, body: AddBody) -> Response:
        return _act(request, body, lambda a, at: rep_intake.add_numbers(
            _rep(a), [RepRow(**row.model_dump()) for row in body.rows],
            body.how_obtained, body.confirmation, at))

    # a contact (§4.5: a contact never held is no such contact)
    def contact_read(request: Request, id_: str,
                     run: Callable[[UUID, UUID, datetime], Any]) -> Response:
        try:
            cid = _uuid(id_, contact=True)
        except _Refused as refused:
            return refused.response
        return _read(request, lambda a, at: run(_rep(a), cid, at), contact=cid, hides=True)

    def contact_act(request: Request, id_: str, body: BaseModel | None,
                    run: Callable[[UUID, UUID, datetime], Any],
                    allow_inactive: bool = False) -> Response:
        try:
            cid = _uuid(id_, contact=True)
        except _Refused as refused:
            return refused.response
        return _act(request, body, lambda a, at: run(_rep(a), cid, at), contact=cid,
                    hides=True, allow_inactive=allow_inactive)

    @r.get("/contacts/{id_}")
    def card(request: Request, id_: str) -> Response:
        return contact_read(request, id_, reads.card)

    @r.get("/contacts/{id_}/history")
    def history(request: Request, id_: str) -> Response:
        return contact_read(request, id_, lambda rep, cid, at: reads.history(rep, cid))

    @r.get("/contacts/{id_}/may-call")
    def may_call(request: Request, id_: str) -> Response:
        def run(rep: UUID, cid: UUID, at: datetime) -> dict[str, bool]:
            rule.may_call(rep, cid, at)
            return {"yes": True}

        return contact_read(request, id_, run)

    @r.post("/contacts/{id_}/calls")
    def open_call(request: Request, id_: str,
                  body: Annotated[CallBody | None, Body()] = None) -> Response:
        confirm = body.confirm_outside_hours if body is not None else False
        return contact_act(request, id_, body, lambda rep, cid, at: calls.open_call(
            rep, cid, at, confirm_outside_hours=confirm))

    @r.post("/contacts/{id_}/outcomes")
    def record_outcome(request: Request, id_: str, body: OutcomeBody) -> Response:
        return contact_act(request, id_, body, lambda rep, cid, at: calls.record_outcome(
            rep, cid, body.outcome, at, call_id=body.call_id, memo=body.memo))

    @r.post("/contacts/{id_}/memos")
    def add_memo(request: Request, id_: str, body: TextBody) -> Response:
        return contact_act(request, id_, body, lambda rep, cid, at: calls.add_memo(
            rep, cid, body.text, at))

    @r.post("/contacts/{id_}/zone")
    def set_zone(request: Request, id_: str, body: ZoneBody) -> Response:
        return contact_act(request, id_, body, lambda rep, cid, at: zones.set_zone(
            cid, body.zone, at, rep=rep))

    @r.post("/contacts/{id_}/move")
    def move(request: Request, id_: str, body: MoveBody) -> Response:
        return contact_act(request, id_, body, lambda rep, cid, at: rule.move(
            rep, cid, body.to, at))

    @r.post("/contacts/{id_}/pause")
    def pause(request: Request, id_: str, body: PauseBody) -> Response:
        return contact_act(request, id_, body, lambda rep, cid, at: rule.pause(
            rep, cid, body.until, at))

    @r.post("/contacts/{id_}/unpause")
    def unpause(request: Request, id_: str) -> Response:
        return contact_act(request, id_, None, rule.unpause)

    @r.post("/contacts/{id_}/restart")
    def restart(request: Request, id_: str) -> Response:
        return contact_act(request, id_, None, rule.restart)

    @r.post("/contacts/{id_}/do-not-call")
    def do_not_call(request: Request, id_: str,
                    body: Annotated[MaybeReasonBody | None, Body()] = None) -> Response:
        reason = body.reason if body is not None else None
        return contact_act(request, id_, body, lambda rep, cid, at: dnc.report_do_not_call(
            rep, cid, reason, at), allow_inactive=True)

    @r.post("/contacts/{id_}/vouch")
    def vouch_for(request: Request, id_: str, body: VouchBody) -> Response:
        return contact_act(request, id_, body, lambda rep, cid, at: vouch.vouch(
            rep, cid, body.reason, body.confirmation, at))

    @r.post("/contacts/{id_}/vouch/withdraw")
    def withdraw(request: Request, id_: str, body: MaybeReasonBody) -> Response:
        return contact_act(request, id_, body, lambda rep, cid, at: vouch.withdraw(
            rep, cid, body.reason, at))

    @r.post("/outcomes/{id_}/undo")
    def undo(request: Request, id_: str, body: ReasonBody) -> Response:
        try:
            oid = _uuid(id_, contact=False)
        except _Refused as refused:
            return refused.response
        return _act(request, body, lambda a, at: calls.undo_outcome(
            _rep(a), oid, body.reason, at))

    @r.post("/calls-received")
    def receive_call(request: Request, body: PhoneBody) -> Response:
        return _act(request, body, lambda a, at: calls.receive_call(
            _rep(a), body.phone, at), hides=True)

    @r.post("/calls-received/{id_}/resolve")
    def resolve(request: Request, id_: str, body: ResolveBody) -> Response:
        try:
            rid = _uuid(id_, contact=False)
        except _Refused as refused:
            return refused.response
        return _act(request, body, lambda a, at: calls.resolve_received(
            _rep(a), rid, body.resolution, at))

    # the website's status (06b §4.3): its key only, no admin named
    @r.get("/status")
    def status(request: Request) -> Response:
        return _read(request, lambda a, at: runs.status(at), keys=website, rep=False)

    # an admin's
    def admin_read(request: Request, run: Callable[[_Asker, datetime], Any]) -> Response:
        return _read(request, run, keys=website, rep=False, admin=True)

    def admin_act(request: Request, body: BaseModel | None,
                  run: Callable[[_Asker, datetime], Any]) -> Response:
        return _act(request, body, run, keys=website, rep=False, admin=True)

    @r.get("/admin/calls/open")
    def open_calls(request: Request) -> Response:
        return admin_read(request, lambda a, at: {"calls": reads.open_calls()})

    @r.post("/admin/calls/{id_}/clear")
    def clear(request: Request, id_: str, body: ReasonBody) -> Response:
        try:
            call_id = _uuid(id_, contact=False)
        except _Refused as refused:
            return refused.response
        return admin_act(request, body, lambda a, at: calls.clear_call(
            call_id, _actor(a), body.reason, at))

    @r.post("/admin/do-not-call")
    def admin_do_not_call(request: Request, body: AdminDncBody) -> Response:
        return admin_act(request, body, lambda a, at: dnc.record_do_not_call_request(
            body.phone, _actor(a), body.reason, at))

    @r.get("/admin/do-not-call/{phone}")
    def dnc_history(request: Request, phone: str) -> Response:
        return admin_read(request, lambda a, at: {"entries": dnc.dnc_history(phone)})

    @r.post("/admin/do-not-call/{phone}/lift")
    def lift(request: Request, phone: str, body: LiftBody) -> Response:
        return admin_act(request, body, lambda a, at: dnc.lift_do_not_call(
            phone, body.seen, _actor(a), body.reason, at))

    @r.post("/admin/contacts/{id_}/zone")
    def admin_zone(request: Request, id_: str, body: ZoneBody) -> Response:
        try:
            cid = _uuid(id_, contact=False)
        except _Refused as refused:
            return refused.response
        return admin_act(request, body, lambda a, at: zones.set_zone(
            cid, body.zone, at, actor=_actor(a)))

    @r.post("/admin/reps/{sales_rep_id}/reclaim")
    def reclaim(request: Request, sales_rep_id: str, body: ReasonBody) -> Response:
        try:
            sid = _roster_id(sales_rep_id)
        except _Refused as refused:
            return refused.response
        return admin_act(request, body, lambda a, at: assignment.reclaim(
            roster.resolve_rep(sid, True), body.reason, _actor(a)))

    return r


# --- the app ----------------------------------------------------------------------


def create_app() -> FastAPI:
    dialer = os.environ.get("CE_DIALER_KEY") or ""
    website = os.environ.get("CE_WEBSITE_KEY") or ""
    if not dialer or not website or dialer == website:
        raise RuntimeError("CE_DIALER_KEY and CE_WEBSITE_KEY must be set and differ")
    app = FastAPI(title="contact-engine", openapi_url=None, docs_url=None, redoc_url=None)
    app.state.keys = {"dialer": dialer, "website": website}

    @app.exception_handler(RequestValidationError)
    def bad_request(request: Request, exc: RequestValidationError) -> Response:
        return _error(400, "bad_request", "the request does not parse",
                      {"errors": [str(e.get("msg")) for e in exc.errors()]})

    @app.exception_handler(HTTPException)
    def no_route(request: Request, exc: HTTPException) -> Response:
        if exc.status_code == 405:
            return _error(405, "no_route", "this route takes another method")
        return _error(exc.status_code if exc.status_code >= 400 else 404, "no_route",
                      "no such route")

    @app.get("/health")
    def health() -> Response:
        if ping():
            return _answer(200, {"ok": True})
        return _answer(503, {"ok": False})

    app.include_router(_routes())
    return app
