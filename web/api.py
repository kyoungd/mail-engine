"""The thin window over the service verbs (FastAPI). No logic lives here — every route
calls exactly one verb and returns or renders its result. The approval-hash guard lives
in the verbs, not here; execution verbs (execute_wave, recompute_state, run_nightly,
sync) are deliberately NOT routed, with ONE exception: /drops/run triggers the same
run_drops job the CLI/cron uses, gated by DROP_PASSWORD (decided 2026-07-12 — a
password-gated button beats SSH for a two-founder team; fail-closed when unset).

Run in the existing Docker/VPS pattern with `uvicorn web.api:app` (or `make run`).
"""

import hmac
import json
import os
import tempfile
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from domain.errors import ValidationError
from jobs.drop import run_drops
from service.contacts import load_list, record_outcome, set_next_action, suppress
from seams.lob import BadWebhookSignature, LobPrintApi
from service.ingestion import ingest_event, record_note, resolve_orphans
from service.queries import (
    get_activation_board,
    get_approval_queue,
    get_contact_timeline,
    get_pipeline,
    get_wave,
    get_wave_dashboard,
    list_due_nudges,
    list_orphans,
    list_variants,
    list_waves,
    search_contacts,
)
from service.waves import (
    approve_wave,
    cancel_wave,
    create_variant,
    draft_wave,
    preview_audience,
    update_wave,
)

app = FastAPI(title="Mail Engine")
_UI_DIR = Path(__file__).resolve().parent / "ui"
templates = Jinja2Templates(directory=str(_UI_DIR / "templates"))
app.mount("/static", StaticFiles(directory=str(_UI_DIR / "static")), name="static")


@app.exception_handler(ValidationError)
async def _on_validation_error(request: Request, exc: ValidationError) -> JSONResponse:
    return JSONResponse(status_code=409, content={"code": exc.code, "detail": str(exc)})


def _json_field(name: str, raw: str) -> dict[str, Any]:
    """Marshal a JSON-textarea form field into the dict the verb expects."""
    try:
        value = json.loads(raw or "{}")
    except json.JSONDecodeError as exc:
        raise ValidationError("bad_json", f"{name} is not valid JSON: {exc}") from None
    if not isinstance(value, dict):
        raise ValidationError("bad_json", f"{name} must be a JSON object")
    return value


def _load_upload(upload: UploadFile, source: str):
    """Marshal an uploaded CSV into the path-based load_list verb."""
    with tempfile.NamedTemporaryFile(suffix=".csv") as tmp:
        tmp.write(upload.file.read())
        tmp.flush()
        return load_list(tmp.name, source=source)


# --- JSON API bodies (marshalling shapes, no logic) -----------------------------


class DraftWaveBody(BaseModel):
    name: str
    drop_number: int
    audience_rule: dict[str, Any] = {}
    variant_split: dict[str, Any] = {}
    scheduled_for: date | None = None


class VariantBody(BaseModel):
    name: str
    hypothesis: str
    creative: dict[str, Any] = {}


class NoteBody(BaseModel):
    note_type: str = "note.general"
    text: str


class NextActionBody(BaseModel):
    action_date: date
    note: str


class ReasonBody(BaseModel):
    reason: str


# --- JSON API: one verb per route ----------------------------------------------


@app.get("/api/pipeline")
def api_pipeline():
    return get_pipeline()


@app.get("/api/activation")
def api_activation():
    return get_activation_board()


@app.get("/api/approval-queue")
def api_approval_queue():
    return get_approval_queue()


@app.get("/api/nudges")
def api_nudges():
    return list_due_nudges()


@app.get("/api/waves")
def api_waves():
    return list_waves()


@app.post("/api/waves")
def api_draft_wave(body: DraftWaveBody):
    wave_id = draft_wave(
        body.name, body.drop_number, body.audience_rule, body.variant_split, body.scheduled_for
    )
    return {"id": wave_id}


@app.post("/api/waves/{wave_id}/update")
def api_update_wave(wave_id: UUID, body: DraftWaveBody):
    update_wave(
        wave_id, body.name, body.drop_number, body.audience_rule,
        body.variant_split, body.scheduled_for,
    )
    return {"status": "updated"}


@app.get("/api/waves/{wave_id}/dashboard")
def api_wave_dashboard(wave_id: UUID):
    return get_wave_dashboard(wave_id)


@app.get("/api/waves/{wave_id}/preview")
def api_preview(wave_id: UUID):
    return preview_audience(wave_id)


@app.post("/api/waves/{wave_id}/approve")
def api_approve(wave_id: UUID, state_hash: str, approved_by: str = "young"):
    approve_wave(wave_id, approved_by, state_hash)
    return {"status": "approved"}


@app.post("/api/waves/{wave_id}/cancel")
def api_cancel(wave_id: UUID):
    cancel_wave(wave_id)
    return {"status": "cancelled"}


@app.get("/api/variants")
def api_variants():
    return list_variants()


@app.post("/api/variants")
def api_create_variant(body: VariantBody):
    return {"id": create_variant(body.name, body.hypothesis, body.creative)}


@app.get("/api/contacts")
def api_contacts(q: str = ""):
    return search_contacts(q)


@app.get("/api/contacts/{contact_id}/timeline")
def api_contact_timeline(contact_id: UUID):
    return get_contact_timeline(contact_id)


@app.post("/api/contacts/{contact_id}/note")
def api_note(contact_id: UUID, body: NoteBody):
    return {"event_id": record_note(contact_id, body.note_type, body.text)}


@app.post("/api/contacts/{contact_id}/next-action")
def api_next_action(contact_id: UUID, body: NextActionBody):
    set_next_action(contact_id, body.action_date, body.note)
    return {"status": "set"}


@app.post("/api/contacts/{contact_id}/lost")
def api_lost(contact_id: UUID, body: ReasonBody):
    return {"event_id": record_outcome(contact_id, "lost", body.reason)}


@app.post("/api/contacts/{contact_id}/suppress")
def api_suppress(contact_id: UUID, body: ReasonBody):
    suppress(contact_id, body.reason)
    return {"status": "suppressed"}


@app.get("/api/orphans")
def api_orphans():
    return list_orphans()


@app.post("/api/orphans/resolve")
def api_resolve_orphans():
    return resolve_orphans()


# --- HTML window: each view maps to one verb ------------------------------------


@app.get("/")
def home():
    return RedirectResponse("/waves")


@app.get("/pipeline")
def ui_pipeline(request: Request):
    return templates.TemplateResponse(request, "pipeline.html", {"cards": get_pipeline()})


@app.get("/activation")
def ui_activation(request: Request):
    return templates.TemplateResponse(
        request, "activation.html", {"cards": get_activation_board()}
    )


@app.get("/approvals")
def ui_approvals(request: Request):
    return templates.TemplateResponse(
        request, "approvals.html", {"waves": get_approval_queue()}
    )


@app.get("/waves")
def ui_waves(request: Request):
    return templates.TemplateResponse(request, "waves.html", {"waves": list_waves()})


# NOTE: declared before /waves/{wave_id} so the literal path wins the match.
@app.get("/waves/new")
def ui_wave_new(request: Request):
    return templates.TemplateResponse(request, "wave_new.html", {})


@app.post("/waves/new")
def ui_draft_wave(
    name: str = Form(...),
    drop_number: int = Form(...),
    scheduled_for: str = Form(""),
    audience_rule: str = Form("{}"),
    variant_split: str = Form("{}"),
):
    wave_id = draft_wave(
        name,
        drop_number,
        _json_field("audience_rule", audience_rule),
        _json_field("variant_split", variant_split),
        date.fromisoformat(scheduled_for) if scheduled_for else None,
    )
    return RedirectResponse(f"/waves/{wave_id}/approve", status_code=303)


@app.get("/waves/{wave_id}")
def ui_wave_dashboard(request: Request, wave_id: UUID):
    return templates.TemplateResponse(
        request, "dashboard.html", {"dashboard": get_wave_dashboard(wave_id)}
    )


@app.get("/waves/{wave_id}/edit")
def ui_wave_edit(request: Request, wave_id: UUID):
    return templates.TemplateResponse(request, "wave_edit.html", {"wave": get_wave(wave_id)})


@app.post("/waves/{wave_id}/edit")
def ui_update_wave(
    wave_id: UUID,
    name: str = Form(...),
    drop_number: int = Form(...),
    scheduled_for: str = Form(""),
    audience_rule: str = Form("{}"),
    variant_split: str = Form("{}"),
):
    update_wave(
        wave_id,
        name,
        drop_number,
        _json_field("audience_rule", audience_rule),
        _json_field("variant_split", variant_split),
        date.fromisoformat(scheduled_for) if scheduled_for else None,
    )
    return RedirectResponse(f"/waves/{wave_id}/approve", status_code=303)


@app.get("/waves/{wave_id}/approve")
def ui_approve_screen(request: Request, wave_id: UUID):
    return templates.TemplateResponse(
        request, "approve.html", {"wave_id": wave_id, "preview": preview_audience(wave_id)}
    )


@app.post("/waves/{wave_id}/approve")
def ui_approve(wave_id: UUID, state_hash: str, approved_by: str = "young"):
    approve_wave(wave_id, approved_by, state_hash)
    return RedirectResponse("/approvals", status_code=303)


@app.post("/waves/{wave_id}/cancel")
def ui_cancel(wave_id: UUID):
    cancel_wave(wave_id)
    return RedirectResponse("/waves", status_code=303)


@app.get("/variants")
def ui_variants(request: Request):
    return templates.TemplateResponse(request, "variants.html", {"variants": list_variants()})


@app.post("/variants")
def ui_create_variant(
    name: str = Form(...),
    hypothesis: str = Form(...),
    creative: str = Form("{}"),
):
    create_variant(name, hypothesis, _json_field("creative", creative))
    return RedirectResponse("/variants", status_code=303)


@app.get("/contacts")
def ui_contacts(request: Request, q: str = ""):
    return templates.TemplateResponse(
        request, "contacts.html", {"q": q, "contacts": search_contacts(q)}
    )


@app.get("/contacts/{contact_id}")
def ui_contact_timeline(request: Request, contact_id: UUID):
    return templates.TemplateResponse(
        request,
        "timeline.html",
        {"contact_id": contact_id, "events": get_contact_timeline(contact_id)},
    )


@app.post("/contacts/{contact_id}/note")
def ui_note(contact_id: UUID, note_type: str = Form("note.general"), text: str = Form(...)):
    record_note(contact_id, note_type, text)
    return RedirectResponse(f"/contacts/{contact_id}", status_code=303)


@app.post("/contacts/{contact_id}/next-action")
def ui_next_action(contact_id: UUID, action_date: date = Form(...), note: str = Form(...)):
    set_next_action(contact_id, action_date, note)
    return RedirectResponse(f"/contacts/{contact_id}", status_code=303)


@app.post("/contacts/{contact_id}/lost")
def ui_lost(contact_id: UUID, reason: str = Form(...)):
    record_outcome(contact_id, "lost", reason)
    return RedirectResponse(f"/contacts/{contact_id}", status_code=303)


@app.post("/contacts/{contact_id}/suppress")
def ui_suppress(contact_id: UUID, reason: str = Form(...)):
    suppress(contact_id, reason)
    return RedirectResponse(f"/contacts/{contact_id}", status_code=303)


@app.get("/intake")
def ui_intake(request: Request):
    return templates.TemplateResponse(request, "intake.html", {"report": None})


@app.post("/intake")
def ui_load_list(request: Request, file: UploadFile = File(...), source: str = Form("cslb")):
    report = _load_upload(file, source)
    return templates.TemplateResponse(request, "intake.html", {"report": report})


@app.get("/orphans")
def ui_orphans(request: Request):
    return templates.TemplateResponse(request, "orphans.html", {"events": list_orphans()})


@app.post("/orphans/resolve")
def ui_resolve_orphans():
    resolve_orphans()
    return RedirectResponse("/orphans", status_code=303)


@app.get("/drops")
def ui_drops(request: Request):
    return templates.TemplateResponse(
        request,
        "drops.html",
        {
            "enabled": bool(os.environ.get("DROP_PASSWORD", "")),
            "default_as_of": date.today() + timedelta(days=1),
            "reports": None,
        },
    )


@app.post("/drops/run")
def ui_run_drops(request: Request, password: str = Form(...), as_of: date = Form(...)):
    """The one routed execution trigger (see module docstring). Same verb as the
    cron/CLI path; the password is deliberate-action friction, and fail-closed
    mirrors the webhook secret."""
    secret = os.environ.get("DROP_PASSWORD", "")
    if not secret:
        return JSONResponse(
            status_code=503, content={"detail": "DROP_PASSWORD not configured"}
        )
    if not hmac.compare_digest(password.encode(), secret.encode()):
        return JSONResponse(status_code=401, content={"detail": "wrong password"})
    api = LobPrintApi(
        os.environ["LOB_API_KEY"],
        {
            "name": os.environ["LOB_FROM_NAME"],
            "address_line1": os.environ["LOB_FROM_LINE1"],
            "address_city": os.environ["LOB_FROM_CITY"],
            "address_state": os.environ["LOB_FROM_STATE"],
            "address_zip": os.environ["LOB_FROM_ZIP"],
        },
        cost_cents=int(os.environ.get("LOB_COST_CENTS", "87")),
    )
    return templates.TemplateResponse(
        request,
        "drops.html",
        {"enabled": True, "default_as_of": as_of, "reports": run_drops(api, as_of)},
    )


@app.post("/webhooks/lob")
async def lob_webhook(request: Request):
    """Lob delivery webhook -> canonical event. Fail-closed: no configured secret or a
    bad signature is rejected, never ingested (the SEC-01 lesson)."""
    secret = os.environ.get("LOB_WEBHOOK_SECRET", "")
    if not secret:
        return JSONResponse(status_code=503, content={"detail": "webhook secret not configured"})
    raw = await request.body()
    client = LobPrintApi(api_key="", from_address={}, webhook_secret=secret)
    try:
        event = client.parse_webhook(raw, dict(request.headers))
    except BadWebhookSignature:
        return JSONResponse(status_code=401, content={"detail": "bad signature"})
    if event is None:
        return {"status": "ignored"}
    ingest_event(
        source="lob",
        type=event.type,
        occurred_at=event.occurred_at,
        payload=event.payload,
        external_id=event.external_id,
    )
    return {"status": "ok"}


@app.get("/nudges")
def ui_nudges(request: Request):
    return templates.TemplateResponse(request, "nudges.html", {"nudges": list_due_nudges()})
