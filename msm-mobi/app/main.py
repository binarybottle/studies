"""FastAPI application: the Prolific-facing pages and the task API.

Participant journey:

    /start  ->  /consent  ->  /task  ->  /finish  ->  Prolific
    (Prolific)   (agree)     (13 blocks)  (completion code)

The browser never receives the assignment, the Stance, or anything about
future blocks -- it asks the server what to render next and posts back what
the participant did. Every state change is persisted before the response is
returned, so a refresh or a redeploy resumes at the same step.

All handlers are asynchronous. A model call is an awaited network wait, so a
few hundred participants thinking at once cost the process nothing but open
sockets; the only serialization is a per-participant lock, which stops a
double-click or a refresh mid-turn from submitting the same step twice.
"""

from __future__ import annotations

import asyncio
import html
import io
import logging
from pathlib import Path
from typing import Any
from urllib.parse import quote

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import config, prompts
from .content import ContentError, ContentLibrary
from .llm import LLMError, get_client
from .session import STEP_FIELD, FlowError, Session, ValidationError, now_iso
from .store import Participant, Stage, get_store

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("msm")

APP_VERSION = "0.1.0"
STATIC_DIR = Path(__file__).parent / "static"

library: ContentLibrary | None = None
sessions: dict[str, Session] = {}
locks: dict[str, asyncio.Lock] = {}

# Client-reported events that are allowed into the log. Anything else is
# rejected so the browser cannot write arbitrary entries into the record.
CLIENT_EVENTS = frozenset({
    "start_screen_shown",
    "end_screen_shown",
    "fixation_cross_shown",
    "fixation_cross_hidden",
    "window_focus_lost",
    "window_focus_regained",
    "visibility_changed",
    "thinking_shown",
    "thinking_slow_state",
    "validation_blocked",
})


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global library
    library = ContentLibrary()
    get_store()
    # Built here rather than on first use: LiteLLM is slow to import, and that
    # cost would otherwise land inside the first participant's measured wait.
    client = get_client()
    log.info(
        "Loaded %d scenarios in %d categories. LLM provider: %s (%s). Participants: %s",
        len(library.scenarios), len(library.categories),
        client.provider_name, client.model, get_store().summary(),
    )
    yield


app = FastAPI(title=config.STUDY_NAME, version=APP_VERSION, lifespan=lifespan)


def _library() -> ContentLibrary:
    if library is None:
        raise HTTPException(503, "Content library not loaded")
    return library


# --- shared page shell (same shape as the other studies on this server) ---

def page(title: str, body: str, status_code: int = 200) -> HTMLResponse:
    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ font-family: system-ui, -apple-system, sans-serif; max-width: 38rem;
         margin: 0 auto; padding: 1.5rem 1.25rem 4rem; line-height: 1.6; }}
  h1 {{ font-size: 1.5rem; line-height: 1.3; }}
  h2 {{ font-size: 1.1rem; margin-top: 2rem; }}
  .card {{ border: 1px solid currentColor; border-radius: 0.75rem;
           padding: 1.25rem; margin: 1.5rem 0; }}
  button, .btn {{ font: inherit; display: inline-block; padding: 0.8rem 1.4rem;
           border-radius: 0.5rem; border: 1px solid currentColor;
           background: transparent; color: inherit; cursor: pointer;
           text-decoration: none; margin-top: 1rem; }}
  .muted {{ opacity: 0.7; font-size: 0.9rem; }}
</style></head>
<body><main>{body}</main></body></html>""", status_code=status_code)


def public_information_body() -> str:
    return f"""
    <h1>{html.escape(config.STUDY_NAME)}</h1>
    <p>{html.escape(config.ORG_NAME)} is piloting an AI chat assistant that
    talks through short imagined scenarios. Participation is by invitation
    through Prolific; if you arrived here another way, there is nothing to do
    on this page.</p>
    <p class="muted">Questions: <a href="mailto:{html.escape(config.CONTACT_EMAIL)}">{html.escape(config.CONTACT_EMAIL)}</a>.
    See also the <a href="{config.PRIVACY_URL}">privacy policy</a> and
    <a href="{config.TERMS_URL}">terms of use</a>.</p>
    """


def missing_identifier_page() -> HTMLResponse:
    return page(
        "Study link incomplete",
        f"""
        <h1>This link is missing your Prolific ID</h1>
        <p>The study opened without the identifier Prolific normally adds to
        the link, so we cannot tell which submission you are.</p>
        <h2>What to do</h2>
        <p>Go back to Prolific and open the study from your list of active
        studies, using the <strong>Open study in new window</strong> button
        rather than a bookmark or a copied link. That button adds the
        identifier automatically.</p>
        <p class="muted">Nothing has been recorded, and your submission is
        unaffected. If the study still does not open, message us through
        Prolific or write to
        <a href="mailto:{html.escape(config.CONTACT_EMAIL)}">{html.escape(config.CONTACT_EMAIL)}</a>.</p>
        """,
        status_code=400,
    )


class UnknownParticipant(HTTPException):
    def __init__(self) -> None:
        super().__init__(status_code=404, detail="Unknown participant")


@app.exception_handler(UnknownParticipant)
async def unknown_participant_handler(request: Request, exc: UnknownParticipant):
    if request.url.path.startswith("/api/"):
        return JSONResponse({"detail": exc.detail}, status_code=404)
    return page(
        "Start from Prolific",
        f"""
        <h1>We do not recognise this link</h1>
        <p>This page only works after the study has been opened from
        Prolific. Go back to Prolific and open the study from your list of
        active studies.</p>
        <p class="muted">If that does not help, email
        <a href="mailto:{html.escape(config.CONTACT_EMAIL)}">{html.escape(config.CONTACT_EMAIL)}</a>
        with your Prolific ID.</p>
        """,
        status_code=404,
    )


@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError):
    if request.url.path.startswith("/api/"):
        return JSONResponse({"detail": exc.errors()}, status_code=422)
    return missing_identifier_page()


def require(pid: str) -> Participant:
    participant = get_store().get_participant(pid)
    if participant is None:
        raise UnknownParticipant()
    return participant


# --- public pages ---

@app.get("/", response_class=HTMLResponse)
async def public_information() -> HTMLResponse:
    """Public information page; also the container healthcheck."""
    return page(config.STUDY_NAME, public_information_body())


@app.get("/start")
async def start(
    PROLIFIC_PID: str | None = None,
    STUDY_ID: str | None = None,
    SESSION_ID: str | None = None,
    pid: str | None = None,
    study_id: str | None = None,
    session_id: str | None = None,
):
    """Entry point registered as the Prolific external study URL.

    Prolific substitutes the identifiers into the URL itself. Re-entry
    resumes at the participant's recorded stage rather than resetting it, so
    refreshing cannot replay the study. Both casings of the parameter names
    are accepted, because the names are editable in Prolific's panel.
    """
    PROLIFIC_PID = (PROLIFIC_PID or pid or "").strip()
    STUDY_ID = STUDY_ID or study_id
    SESSION_ID = SESSION_ID or session_id

    if not PROLIFIC_PID:
        get_store().record_event(None, None, "start_without_pid")
        return missing_identifier_page()

    participant = get_store().create_participant(PROLIFIC_PID, STUDY_ID, SESSION_ID)
    destinations = {
        Stage.ARRIVED: f"/consent?pid={quote(PROLIFIC_PID)}",
        Stage.CONSENTED: f"/task?pid={quote(PROLIFIC_PID)}",
        Stage.IN_TASK: f"/task?pid={quote(PROLIFIC_PID)}",
        Stage.COMPLETE: f"/finish?pid={quote(PROLIFIC_PID)}",
        Stage.WITHDREW: f"/finish?pid={quote(PROLIFIC_PID)}",
    }
    return RedirectResponse(destinations[participant.stage], status_code=303)


@app.get("/consent", response_class=HTMLResponse)
async def consent_form(pid: str | None = None) -> HTMLResponse:
    """The information sheet.

    Replace the body text with the IRB-approved wording verbatim; this is
    the DASH pilot's structure with the study-specific parts changed.
    """
    if not pid:
        return page(config.STUDY_NAME, public_information_body())
    require(pid)
    safe_pid = html.escape(pid)
    return page(
        "About this study",
        f"""
        <h1>About this study</h1>
        <p>Thank you for your interest. Please read this page carefully before
        deciding whether to take part.</p>

        <h2>What this is</h2>
        <p>{html.escape(config.ORG_NAME)} is testing an AI chat assistant that
        talks through short imagined scenarios. This is a <strong>pilot test
        of the software</strong>, not a research study. Its purpose is to find
        out whether the system works reliably. The responses collected here
        will be used only to check that the technology functions correctly,
        and will be discarded rather than analysed or published as
        research.</p>

        <h2>What you will do</h2>
        <p>You will read a practice scenario and then twelve short, everyday
        scenarios. For each one you will rate a statement about it on a scale
        from 0 to 100, say how confident you are, explain your rating in a
        sentence or two, exchange a few messages with an AI assistant about
        your view, and then rate the statement again.</p>
        <p>The scenarios are imagined situations. Answer based on the scenario
        as described; you do not need to share anything personal, and please
        do not enter real personal information about yourself or anyone you
        know.</p>

        <h2>How long it takes</h2>
        <p>Expect <strong>{html.escape(config.DURATION_TEXT)}</strong>. Please
        start only when you can give it an uninterrupted block of time. If you
        are interrupted, open the study link from Prolific again and you will
        pick up where you left off.</p>

        <h2>How to stop</h2>
        <p>Taking part is voluntary and you may stop at any point without
        giving a reason: close the page and return the study on Prolific.
        Stopping will not affect your standing on Prolific in any way.</p>

        <h2>What we collect and keep</h2>
        <p>We keep your ratings, the text you type, the assistant's replies,
        and your Prolific ID. We do not ask for your name, email address or
        phone number. Nothing is sent to your phone.</p>

        <h2>A note on the scenarios</h2>
        <p>Some scenarios describe small setbacks or awkward social moments,
        such as being left out of a message or missing a personal goal. They
        are fictional. If any of it brings up something real and difficult for
        you, please stop and reach out for support: in the US you can call or
        text <strong>988</strong> to reach the Suicide and Crisis Lifeline,
        any time.</p>

        <h2>Questions</h2>
        <p>Contact {html.escape(config.CONTACT_EMAIL)} with your Prolific ID if
        anything goes wrong or you want to know more. See also the
        <a href="{config.PRIVACY_URL}">privacy policy</a> and
        <a href="{config.TERMS_URL}">terms of use</a>.</p>

        <h2>Your decision</h2>
        <p>Agreeing takes you to the task. Declining returns you to Prolific
        straight away, with a code that pays you for the time you spent
        reading this.</p>

        <form method="post" action="/consent?pid={safe_pid}">
          <button type="submit" name="decision" value="consent">
            I have read this and agree to take part
          </button>
        </form>
        <form method="post" action="/consent?pid={safe_pid}">
          <button type="submit" name="decision" value="decline">
            I do not wish to take part
          </button>
        </form>
        """,
    )


@app.post("/consent")
async def consent_submit(pid: str, request: Request):
    """Record the decision. Agreement issues the counterbalancing sequence
    number and the assignment it produces, once."""
    participant = require(pid)
    store = get_store()
    form = await request.form()
    if form.get("decision") == "decline":
        if participant.stage is Stage.ARRIVED:
            store.set_stage(pid, Stage.WITHDREW)
            store.record_event(pid, None, "consent_declined")
        return RedirectResponse(
            config.PROLIFIC_COMPLETE_URL.format(code=config.CC_NO_CONSENT), status_code=303
        )

    if participant.stage is Stage.ARRIVED:
        client = get_client()
        store.issue_assignment(
            pid, _library().assignment,
            app_version=APP_VERSION, llm_model=client.model, llm_provider=client.provider_name,
        )
        store.set_stage(pid, Stage.CONSENTED)
        store.record_event(pid, None, "consent_given")
    return RedirectResponse(f"/task?pid={quote(pid)}", status_code=303)


@app.get("/task", response_class=HTMLResponse)
async def task_page(pid: str) -> HTMLResponse:
    participant = require(pid)
    if participant.stage is Stage.ARRIVED:
        return RedirectResponse(f"/consent?pid={quote(pid)}", status_code=303)
    if participant.stage in (Stage.COMPLETE, Stage.WITHDREW):
        return RedirectResponse(f"/finish?pid={quote(pid)}", status_code=303)

    token = _asset_token()
    doc = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    doc = doc.replace("/static/app.js", f"/static/app.js?v={token}")
    doc = doc.replace("/static/styles.css", f"/static/styles.css?v={token}")
    doc = doc.replace('data-pid=""', f'data-pid="{html.escape(pid, quote=True)}"')
    return HTMLResponse(doc, headers=NO_STORE)


@app.get("/finish")
async def finish(pid: str):
    """Return a finished participant to Prolific, or explain the alternative."""
    participant = require(pid)
    if participant.stage is Stage.COMPLETE:
        return RedirectResponse(
            config.PROLIFIC_COMPLETE_URL.format(code=config.CC_COMPLETE), status_code=303
        )
    if participant.stage is Stage.WITHDREW:
        return RedirectResponse(
            config.PROLIFIC_COMPLETE_URL.format(code=config.CC_NO_CONSENT), status_code=303
        )
    return page(
        "Not finished yet",
        f"""
        <h1>The session is not finished</h1>
        <p>There is no completion code to record until the last scenario is
        done. <a class="btn" href="/task?pid={html.escape(quote(pid), quote=True)}">Return to the task</a></p>
        <p>If you would rather stop, return the study on Prolific. Returning a
        study does not count against you and carries no penalty.</p>
        <p class="muted">If something went wrong, email
        {html.escape(config.CONTACT_EMAIL)} with your Prolific ID and we will
        arrange payment for the part you completed.</p>
        <p class="muted">Your Prolific ID: {html.escape(pid)}</p>
        """,
    )


# --- task API ---

class SessionRequest(BaseModel):
    pid: str = Field(min_length=1, max_length=64)


class SubmitRequest(BaseModel):
    step: str
    value: Any = None


class EventRequest(BaseModel):
    event: str
    detail: dict[str, Any] = Field(default_factory=dict)


def _lock_for(token: str) -> asyncio.Lock:
    lock = locks.get(token)
    if lock is None:
        lock = locks[token] = asyncio.Lock()
    return lock


def _load_session(participant: Participant) -> Session:
    """The in-memory session for a participant, rebuilt from the stored
    state when this process has not seen them yet (first request, or after a
    restart)."""
    assert participant.session_token
    session = sessions.get(participant.session_token)
    if session is None:
        plan = _library().resolve(participant.pid, participant.assignment_index or 0, participant.assignment)
        client = get_client()
        if participant.state:
            session = Session.from_state(plan, client, participant.state)
        else:
            session = Session(plan, client)
        sessions[participant.session_token] = session
    return session


def _persist(session: Session) -> None:
    get_store().save_state(session.participant_id, session.to_state())


def _open_current_block(session: Session) -> None:
    store = get_store()
    store.init_block(session.block_meta())
    store.update_block(session.participant_id, session.block.block_index, {"scenario_shown_at": now_iso()})
    store.record_event(session.participant_id, session.block.block_index, "block_started", {
        "is_practice": session.block.is_practice,
        "category": session.block.category_label,
        "scenario": session.block.scenario.label,
        "stance": session.block.stance.label,
    })


@app.get("/api/config")
async def get_config() -> dict[str, Any]:
    """Constants the browser needs to mirror the server's input rules."""
    return {
        "app_version": APP_VERSION,
        "min_response_words": config.MIN_RESPONSE_WORDS,
        "score_min": config.SCORE_MIN,
        "score_max": config.SCORE_MAX,
        "thinking_slow_after_ms": config.THINKING_SLOW_AFTER_MS,
        "fixation_cross_ms": config.FIXATION_CROSS_MS,
        "total_blocks": config.REAL_BLOCK_COUNT,
        "copy": {
            "start_title": config.STUDY_NAME,
            "start_body": prompts.START_SCREEN_BODY,
            "end_title": prompts.END_SCREEN_TITLE,
            "end_body": prompts.END_SCREEN_BODY,
        },
    }


@app.get("/api/status")
async def status(pid: str) -> dict[str, Any]:
    participant = require(pid)
    return {"stage": participant.stage.value}


@app.post("/api/session")
async def open_session(req: SessionRequest) -> dict[str, Any]:
    """Start the task, or resume it at the current step."""
    pid = req.pid.strip()
    participant = require(pid)
    store = get_store()
    if participant.stage is Stage.ARRIVED or not participant.session_token:
        raise HTTPException(409, "Consent has not been recorded.")
    if participant.stage in (Stage.COMPLETE, Stage.WITHDREW):
        raise HTTPException(409, "This session has already ended.")

    async with _lock_for(participant.session_token):
        session = _load_session(participant)
        resumed = participant.state is not None
        if resumed:
            view = session.resume_view()
            store.record_event(pid, session.block.block_index, "session_resumed", {"step": session.step})
        else:
            store.set_stage(pid, Stage.IN_TASK)
            store.record_event(pid, None, "session_started", {
                "assignment_index": participant.assignment_index,
                "block_count": len(session.plan.blocks),
            })
            view = session.open_block()
            _open_current_block(session)
        _persist(session)

    return {"session": participant.session_token, "resumed": resumed, **view.to_dict()}


def _session_for(token: str) -> tuple[Participant, Session]:
    participant = get_store().participant_by_token(token)
    if participant is None or participant.stage in (Stage.ARRIVED, Stage.WITHDREW):
        raise HTTPException(404, "Session not found.")
    if participant.stage is Stage.COMPLETE:
        raise HTTPException(409, "This session has already ended.")
    return participant, _load_session(participant)


@app.post("/api/session/{token}/submit")
async def submit(token: str, req: SubmitRequest) -> dict[str, Any]:
    participant, session = _session_for(token)
    store = get_store()

    async with _lock_for(token):
        block_index_before = session.block.block_index
        try:
            value, updates, view = session.submit(req.step, req.value)
        except ValidationError as exc:
            store.record_event(participant.pid, block_index_before, "submission_rejected",
                               {"step": req.step, "reason": str(exc)})
            raise HTTPException(422, str(exc)) from exc
        except FlowError as exc:
            # Usually a double submit or a stale tab; the client re-syncs.
            raise HTTPException(409, str(exc)) from exc

        if updates:
            store.update_block(participant.pid, block_index_before, updates)
        # The text itself is in the block row; the log keeps only its size.
        logged = {k: v for k, v in updates.items() if k.endswith("_words") or k in STEP_FIELD.values()}
        logged = {k: v for k, v in logged.items() if not isinstance(v, str) or k.endswith("_words")}
        store.record_event(participant.pid, block_index_before, "submission_recorded",
                           {"step": req.step, **logged})

        # A gate advanced us into a new block: persist its metadata.
        if req.step == "gate" and not view.done:
            _open_current_block(session)
        if view.done:
            _finish(session)
        _persist(session)

    return view.to_dict()


@app.post("/api/session/{token}/llm")
async def llm_turn(token: str) -> dict[str, Any]:
    participant, session = _session_for(token)
    store = get_store()

    async with _lock_for(token):
        if session.step not in ("llm_1", "llm_2"):
            # The turn already ran (a refresh mid-thinking, or a retry that
            # raced its predecessor). Hand back where things actually are.
            return session.resume_view().to_dict()

        block_index = session.block.block_index
        store.record_event(participant.pid, block_index, "llm_request_sent", {"step": session.step})
        try:
            result, updates, view = await session.run_llm_turn()
        except LLMError as exc:
            store.record_event(participant.pid, block_index, "llm_request_failed", {"error": str(exc)})
            raise HTTPException(502, f"The model did not return a response: {exc}") from exc
        except Exception as exc:
            log.exception("LLM turn failed")
            store.record_event(participant.pid, block_index, "llm_request_failed", {"error": repr(exc)})
            raise HTTPException(502, "The model did not return a response.") from exc

        store.update_block(participant.pid, block_index, updates)
        store.record_event(participant.pid, block_index, "llm_response_received", {
            "latency_ms": result.latency_ms, "truncated": result.truncated,
            "elicited": result.elicited, "model": result.model, "provider": result.provider,
            "word_count": len(result.text.split()),
        })
        _persist(session)

    return view.to_dict()


@app.post("/api/session/{token}/event")
async def client_event(token: str, req: EventRequest) -> dict[str, str]:
    """Log UI events the browser owns (focus loss, blocked paste, thinking
    indicator state). Restricted to a known set of names, and the detail is
    trimmed so the browser cannot bloat the log."""
    participant, session = _session_for(token)
    if req.event not in CLIENT_EVENTS:
        raise HTTPException(400, f"Unknown client event: {req.event}")
    detail = {k: v for k, v in list(req.detail.items())[:12] if isinstance(v, (str, int, float, bool)) and len(str(v)) <= 200}
    get_store().record_event(participant.pid, session.block.block_index, req.event, {"source": "client", **detail})
    return {"status": "ok"}


def _finish(session: Session) -> None:
    store = get_store()
    store.set_stage(session.participant_id, Stage.COMPLETE)
    store.record_event(session.participant_id, None, "session_completed")


# --- admin exports ---

def _admin(token: str) -> None:
    # 404 rather than 403, so the endpoint's existence is not confirmed to a
    # prober; the Caddyfile additionally IP-restricts /admin/*.
    if not config.ADMIN_TOKEN or token != config.ADMIN_TOKEN:
        raise HTTPException(status_code=404, detail="Not found")


@app.get("/admin/blocks.csv")
async def export_blocks(token: str) -> Response:
    """Every block of every participant, one wide row each: the analysis file."""
    _admin(token)
    buf = io.StringIO()
    get_store().export_blocks_csv(buf)
    return Response(buf.getvalue(), media_type="text/csv")


@app.get("/admin/participants.csv")
async def export_participants(token: str) -> Response:
    """One row per Prolific submission: stage, sequence number, timestamps."""
    _admin(token)
    buf = io.StringIO()
    get_store().export_participants_csv(buf)
    return Response(buf.getvalue(), media_type="text/csv")


@app.get("/admin/events/{pid}.jsonl")
async def export_events(pid: str, token: str) -> Response:
    """The full event log for one participant, for investigating a report."""
    _admin(token)
    buf = io.StringIO()
    get_store().export_events(buf, pid)
    return Response(buf.getvalue(), media_type="application/x-ndjson")


# --- static frontend ---

# A cached app.js that disagrees with the server's flow is the kind of
# failure that only shows up mid-session, so nothing here is cacheable.
NO_STORE = {"Cache-Control": "no-store, must-revalidate", "Pragma": "no-cache", "Expires": "0"}


class UncachedStaticFiles(StaticFiles):
    def file_response(self, *args: Any, **kwargs: Any):
        response = super().file_response(*args, **kwargs)
        response.headers.update(NO_STORE)
        return response

    def is_not_modified(self, response_headers, request_headers) -> bool:
        return False


def _asset_token() -> str:
    stamp = max((p.stat().st_mtime_ns for p in STATIC_DIR.iterdir() if p.is_file()), default=0)
    return f"{APP_VERSION}-{stamp:x}"


app.mount("/static", UncachedStaticFiles(directory=STATIC_DIR), name="static")
