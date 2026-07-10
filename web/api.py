"""The thin window over the service verbs (FastAPI). No logic lives here — every route
calls exactly one verb and returns or renders its result. The approval-hash guard lives
in the verbs, not here; execution verbs (execute_wave, recompute_state) are deliberately
NOT routed — dropping mail is a job, never an HTTP call.

Run in the existing Docker/VPS pattern with `uvicorn web.api:app`.
"""

from pathlib import Path
from uuid import UUID

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from domain.errors import ValidationError
from service.queries import (
    get_activation_board,
    get_approval_queue,
    get_contact_timeline,
    get_pipeline,
    get_wave_dashboard,
    list_due_nudges,
)
from service.waves import approve_wave, preview_audience

app = FastAPI(title="Mail Engine")
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "ui" / "templates"))


@app.exception_handler(ValidationError)
async def _on_validation_error(request: Request, exc: ValidationError) -> JSONResponse:
    return JSONResponse(status_code=409, content={"code": exc.code, "detail": str(exc)})


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


@app.get("/api/waves/{wave_id}/dashboard")
def api_wave_dashboard(wave_id: UUID):
    return get_wave_dashboard(wave_id)


@app.get("/api/contacts/{contact_id}/timeline")
def api_contact_timeline(contact_id: UUID):
    return get_contact_timeline(contact_id)


@app.get("/api/waves/{wave_id}/preview")
def api_preview(wave_id: UUID):
    return preview_audience(wave_id)


@app.post("/api/waves/{wave_id}/approve")
def api_approve(wave_id: UUID, state_hash: str, approved_by: str = "young"):
    approve_wave(wave_id, approved_by, state_hash)
    return {"status": "approved"}


# --- HTML window: each view maps to one query verb -----------------------------


@app.get("/")
def home():
    return RedirectResponse("/pipeline")


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


@app.get("/waves/{wave_id}")
def ui_wave_dashboard(request: Request, wave_id: UUID):
    return templates.TemplateResponse(
        request, "dashboard.html", {"dashboard": get_wave_dashboard(wave_id)}
    )


@app.get("/contacts/{contact_id}")
def ui_contact_timeline(request: Request, contact_id: UUID):
    return templates.TemplateResponse(
        request,
        "timeline.html",
        {"contact_id": contact_id, "events": get_contact_timeline(contact_id)},
    )


@app.get("/waves/{wave_id}/approve")
def ui_approve_screen(request: Request, wave_id: UUID):
    return templates.TemplateResponse(
        request, "approve.html", {"wave_id": wave_id, "preview": preview_audience(wave_id)}
    )


@app.post("/waves/{wave_id}/approve")
def ui_approve(wave_id: UUID, state_hash: str, approved_by: str = "young"):
    approve_wave(wave_id, approved_by, state_hash)
    return RedirectResponse("/approvals", status_code=303)
