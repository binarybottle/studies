"""Prolific-to-SMS study site for a Retell chat agent.

Serves the participant-facing web flow and the two server endpoints that
link an out-of-band SMS conversation back to a Prolific submission.

Participant journey
-------------------
1. Prolific sends the participant to ``/start`` with their identifiers.
2. ``/consent`` presents the information sheet and records agreement.
3. ``/begin`` displays the study phone number and a one-time code, then
   polls ``/status`` in the background.
4. The participant texts the code to the number from their own phone.
5. Retell's Function node calls ``/api/verify-code``, binding the chat to
   the participant. This is the only point at which the linkage can be
   made, because inbound SMS chats carry no metadata set by us.
6. Retell's ``chat_ended`` webhook hits ``/api/retell-webhook``, which
   marks the participant complete and releases their completion code.
7. The polling page reveals the Prolific return link.

Completion is keyed on ``chat_ended`` rather than ``chat_analyzed``,
because chats closed by the inactivity timeout never fire the latter.

Routes
------
``GET  /``                  Public study information page. Use this URL as
                            the opt-in URL in A2P campaign registration; it
                            requires no session and no query parameters.
``GET  /sms-terms``         Public messaging terms page.
``GET  /start``             Prolific entry point.
``GET  /consent``           Consent form.
``POST /consent``           Records consent, mints the code.
``GET  /begin``             Number, code, and polling page.
``GET  /status``            Polling target consumed by ``/begin``.
``POST /api/verify-code``   Retell Function node target.
``POST /api/retell-webhook`` Retell chat lifecycle events.
``GET  /finish``            Redirect to the Prolific completion URL.

Example
-------
    $ export STUDY_SMS_NUMBER="+15074317807"
    $ export PROLIFIC_CC_COMPLETE=ABC12345
    $ export PHONE_HASH_SALT="$(openssl rand -hex 16)"
    $ uvicorn study_site:app --reload
    $ open "http://localhost:8000/start?PROLIFIC_PID=$(openssl rand -hex 12)"

Inbound phone numbers are hashed on receipt and the plaintext is never
stored, so the incidental exposure created by SMS does not persist. All
state lives in SQLite via the ``store`` module; that database file is the
only key linking a transcript to a Prolific submission, so back it up.
"""

from __future__ import annotations

import hashlib
import html
import os
import re
import secrets
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel

import store
from store import Participant, Stage

STUDY_SMS_NUMBER = os.environ.get("STUDY_SMS_NUMBER", "+1 (507) 431-7807")
ORG_NAME = os.environ.get("ORG_NAME", "Child Mind Institute")
CONTACT_EMAIL = os.environ.get("CONTACT_EMAIL", "arno.klein@childmind.org")
PRIVACY_URL = "https://childmind.org/privacy/"
TERMS_URL = "https://childmind.org/terms/"

# Expected duration drives the code lifetime and the wording on every page.
# The screener branches heavily, so the range is wide and stated as a range.
DURATION_TEXT = "30 to 60 minutes"

PROLIFIC_COMPLETE_URL = "https://app.prolific.com/submissions/complete?cc={code}"

# One code per outcome. Configure the matching actions in Prolific under
# Completion paths: approve automatically for CC_COMPLETE, hold for review for
# CC_ATTENTION (rejections cannot be automated), and custom screening with a
# fixed reward for CC_NO_CONSENT. Never attach a rejection action to any of
# them.
CC_COMPLETE = os.environ.get("PROLIFIC_CC_COMPLETE", "REPLACE_ME")
CC_ATTENTION = os.environ.get("PROLIFIC_CC_ATTENTION", "REPLACE_ME_TOO")
CC_NO_CONSENT = os.environ.get("PROLIFIC_CC_NO_CONSENT", "REPLACE_ME_THREE")

ATTENTION_FAILURE_THRESHOLD = 2

CODE_ALPHABET = "34679ACDEFHJKMNPRTVWXY"
CODE_LENGTH = 5
CODE_TTL_SECONDS = 21600.0  # Six hours: the session itself can run an hour,
# and participants routinely start, get interrupted, and come back.
MAX_CODE_ATTEMPTS = 5
PHONE_HASH_SALT = os.environ.get("PHONE_HASH_SALT", "change-me")
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")

app = FastAPI(title="Study site")


@app.on_event("startup")
async def startup() -> None:
    """Open the database and create tables on first run."""
    store.init_db()


def normalize_code(raw: str) -> str:
    """Reduce a participant-typed code to canonical form.

    Strips punctuation and whitespace, uppercases, and folds characters
    excluded from the alphabet onto their visual neighbours.

    Args:
        raw: The string as the agent extracted it.

    Returns:
        A normalized candidate, not necessarily a valid code.

    Example:
        >>> normalize_code("k7 rx-q")
        'K7RXQ'
        >>> normalize_code("0iLs2")
        'OILSZ'
    """
    cleaned = re.sub(r"[^A-Za-z0-9]", "", raw).upper()
    folds = {"0": "O", "1": "I", "5": "S", "2": "Z", "8": "B"}
    return "".join(folds.get(char, char) for char in cleaned)


def completion_code_for(participant: Participant) -> str | None:
    """Return the Prolific completion code matching a participant's outcome.

    Non-consent resolves to the screen-out code, because Prolific forbids
    rejecting a participant who declined to take part. A finished interview
    resolves to the attention code only once the failure threshold is met;
    a single failed check is never sufficient in a study of five minutes or
    longer.

    Args:
        participant: The record to evaluate.

    Returns:
        The completion code, or ``None`` if no outcome has been reached.

    Example:
        >>> p = Participant(pid="x", stage=Stage.COMPLETE)
        >>> p.checks_failed = {"c1", "c2"}
        >>> completion_code_for(p) == CC_ATTENTION
        True
    """
    if participant.stage is Stage.WITHDREW:
        return CC_NO_CONSENT
    if participant.stage is Stage.COMPLETE:
        if len(participant.checks_failed) >= ATTENTION_FAILURE_THRESHOLD:
            return CC_ATTENTION
        return CC_COMPLETE
    return None


def page(title: str, body: str) -> HTMLResponse:
    """Wrap body markup in the site's shared shell.

    Args:
        title: Document title.
        body: Inner HTML for the main element.

    Returns:
        A complete HTML response.
    """
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
  .code {{ font-family: ui-monospace, monospace; font-size: 2.5rem;
           letter-spacing: 0.3em; padding: 1rem 0; text-align: center; }}
  .number {{ font-size: 1.5rem; font-weight: 600; text-align: center;
             padding-bottom: 0.5rem; }}
  .card {{ border: 1px solid currentColor; border-radius: 0.75rem;
           padding: 1.25rem; margin: 1.5rem 0; }}
  button, .btn {{ font: inherit; display: inline-block; padding: 0.8rem 1.4rem;
           border-radius: 0.5rem; border: 1px solid currentColor;
           background: transparent; color: inherit; cursor: pointer;
           text-decoration: none; margin-top: 1rem; }}
  .muted {{ opacity: 0.7; font-size: 0.9rem; }}
  ul {{ padding-left: 1.2rem; }}
</style></head>
<body><main>{body}</main></body></html>""")


@app.get("/", response_class=HTMLResponse)
async def public_information() -> HTMLResponse:
    """Serve the public study information page.

    This is the URL to submit as the A2P campaign opt-in URL. It must stay
    reachable with no session, no query parameters, and no login, because
    carrier reviewers open it directly.

    Returns:
        The information page.
    """
    return page(
        "Study information",
        f"""
        <h1>Text-message research pilot</h1>
        <p>{html.escape(ORG_NAME)} is a nonprofit children's mental health
        organization. This page describes a text-message conversation study
        being piloted to test whether an automated interviewer works reliably
        before any research data is collected.</p>

        <h2>What participants do</h2>
        <p>Participants are recruited through the Prolific research platform.
        Each participant is given a short written persona describing a
        fictional parent and child, and is asked to answer a standardized
        mental health screening questionnaire in character. No participant is
        asked about their own child or their own mental health.</p>

        <h2>How it works</h2>
        <p>After reading the study information and agreeing to take part, a
        participant is shown the study number
        <strong>{html.escape(STUDY_SMS_NUMBER)}</strong> together with a
        one-time code, and texts that code from their own phone to begin.
        Every conversation is started by the participant. We never message a
        number that has not messaged us first.</p>

        <h2>Messaging terms</h2>
        <ul>
          <li>Expected length: {html.escape(DURATION_TEXT)}, typically
              100 to 200 messages in a single session.</li>
          <li>Message and data rates may apply.</li>
          <li>Reply STOP at any time to opt out. Reply HELP for help.</li>
          <li>Phone numbers are used only to conduct the conversation. They
              are not sold, rented, or shared with third parties, and are not
              used for marketing.</li>
          <li>Carriers are not liable for delayed or undelivered messages.</li>
        </ul>

        <p class="muted">Questions: {html.escape(CONTACT_EMAIL)} &middot;
        <a href="/sms-privacy">SMS privacy notice</a> &middot;
        <a href="/sms-terms">SMS terms and conditions</a> &middot;
        <a href="{PRIVACY_URL}">Organization privacy policy</a> &middot;
        <a href="{TERMS_URL}">Organization terms of use</a></p>
        """,
    )


@app.get("/sms-privacy", response_class=HTMLResponse)
async def sms_privacy() -> HTMLResponse:
    """Serve the SMS privacy notice.

    Submitted as the Privacy Policy URL on the A2P campaign application.
    Kept separate from the terms page because the application asks for two
    distinct URLs, and a reviewer opening the privacy field expects a
    document about data handling rather than about service conditions.

    Returns:
        The privacy page.
    """
    return page(
        "SMS privacy notice",
        f"""
        <h1>SMS privacy notice</h1>
        <p>This notice covers phone numbers and message content for
        text-message research studies operated by
        {html.escape(ORG_NAME)}, a nonprofit children's mental health
        organization. It supplements our
        <a href="{PRIVACY_URL}">organization-wide privacy policy</a>.</p>

        <h2>Phone numbers are never shared or sold</h2>
        <p><strong>We do not sell, rent, trade, or share mobile phone numbers
        or SMS opt-in data with third parties or affiliates for marketing or
        promotional purposes.</strong> No mobile information is shared with
        third parties for their own purposes under any circumstances.</p>
        <p>Numbers are disclosed only to the service providers that deliver
        the messages on our behalf: our messaging carrier, which transmits
        them, and our conversational agent provider, which processes the
        conversation. Those providers may not use the information for any
        other purpose.</p>

        <h2>What we store</h2>
        <p>Your phone number reaches us as an unavoidable part of sending a
        text message. It is converted to an irreversible cryptographic hash
        on arrival, and the number itself is never written to our database.
        We retain the text of the conversation and a randomly generated
        study code that has no meaning outside our own systems.</p>

        <h2>How long we keep it</h2>
        <p>Conversation records are retained for the duration of the study
        and then deleted. Hashed numbers are deleted on the same schedule.</p>

        <h2>Your choices</h2>
        <p>Reply STOP at any time to end messaging. To request deletion of
        your records, email {html.escape(CONTACT_EMAIL)} with the study code
        you were given.</p>

        <p class="muted">Contact: {html.escape(CONTACT_EMAIL)} &middot;
        <a href="{PRIVACY_URL}">Organization privacy policy</a> &middot;
        <a href="/sms-terms">SMS terms and conditions</a></p>
        """,
    )


@app.get("/sms-terms", response_class=HTMLResponse)
async def sms_terms() -> HTMLResponse:
    """Serve the SMS terms and conditions.

    Submitted as the Terms and Conditions URL on the A2P campaign
    application.

    Returns:
        The terms page.
    """
    return page(
        "SMS terms and conditions",
        f"""
        <h1>SMS terms and conditions</h1>
        <p>These terms govern text messages sent and received in connection
        with research studies operated by {html.escape(ORG_NAME)}. They
        supplement our <a href="{TERMS_URL}">organization-wide terms of
        use</a>.</p>

        <h2>Program description</h2>
        <p>An automated interviewer conducts a research questionnaire by text
        message. Messages consist of questionnaire items and replies to what
        you send. No marketing or promotional messages are ever sent from
        this number.</p>

        <h2>How you opt in</h2>
        <p>Participants are recruited through the Prolific research platform.
        A participant who agrees to take part is shown the study number
        <strong>{html.escape(STUDY_SMS_NUMBER)}</strong> and a one-time code,
        and sends a text message to that number to begin. Sending that message
        is the opt-in. Every conversation is started by the participant. We
        never message a number that has not messaged us first, and we do not
        buy, rent, or import phone number lists.</p>

        <h2>Message frequency</h2>
        <p>Expected length is {html.escape(DURATION_TEXT)}, typically 100 to
        200 messages in a single session.</p>

        <h2>Cost</h2>
        <p>Message and data rates may apply. We do not charge for
        participation.</p>

        <h2>Opting out and getting help</h2>
        <p>Reply <strong>STOP</strong> at any time to end the conversation and
        receive no further messages. Reply <strong>HELP</strong> for
        assistance, or email {html.escape(CONTACT_EMAIL)}. Opting out does not
        affect your standing on Prolific or your compensation for work already
        completed.</p>

        <h2>Carriers and delivery</h2>
        <p>Carriers are not liable for delayed or undelivered messages.
        Supported carriers vary and delivery is not guaranteed on all
        networks.</p>

        <h2>Consent</h2>
        <p>Consent to receive text messages is not a condition of any purchase
        and is not required to participate in any other
        {html.escape(ORG_NAME)} activity. Participation is voluntary and may
        be withdrawn at any time.</p>

        <p class="muted">Contact: {html.escape(CONTACT_EMAIL)} &middot;
        <a href="{TERMS_URL}">Organization terms of use</a> &middot;
        <a href="/sms-privacy">SMS privacy notice</a></p>
        """,
    )


@app.get("/start")
async def start(
    PROLIFIC_PID: str, STUDY_ID: str | None = None, SESSION_ID: str | None = None
):
    """Entry point registered as the Prolific external study URL.

    Re-entry resumes at the participant's recorded stage rather than
    resetting it, so refreshing cannot replay the study or mint a
    second code.

    Args:
        PROLIFIC_PID: Participant ID substituted by Prolific.
        STUDY_ID: Study ID substituted by Prolific.
        SESSION_ID: Session ID substituted by Prolific.

    Returns:
        A redirect to the appropriate stage.
    """
    participant = store.create_participant(PROLIFIC_PID, STUDY_ID, SESSION_ID)

    destinations = {
        Stage.ARRIVED: f"/consent?pid={PROLIFIC_PID}",
        Stage.CONSENTED: f"/begin?pid={PROLIFIC_PID}",
        Stage.TEXTING: f"/begin?pid={PROLIFIC_PID}",
        Stage.COMPLETE: f"/begin?pid={PROLIFIC_PID}",
        Stage.WITHDREW: f"/finish?pid={PROLIFIC_PID}",
    }
    return RedirectResponse(destinations[participant.stage], status_code=303)


def require(pid: str) -> Participant:
    """Fetch a participant record or fail.

    Args:
        pid: Prolific participant ID.

    Returns:
        The stored record.

    Raises:
        HTTPException: 404 when the participant never passed through
            ``/start``, indicating a hand-built or stale URL.
    """
    participant = store.get_participant(pid)
    if participant is None:
        raise HTTPException(status_code=404, detail="Unknown participant")
    return participant


@app.get("/consent", response_class=HTMLResponse)
async def consent_form(pid: str) -> HTMLResponse:
    """Present the consent information sheet.

    Replace the body text with the IRB-approved wording verbatim; the
    structure below is a placeholder that covers the elements carriers and
    review boards both expect to see.

    Args:
        pid: Prolific participant ID.

    Returns:
        The consent page.
    """
    require(pid)
    safe_pid = html.escape(pid)
    return page(
        "About this study",
        f"""
        <h1>About this study</h1>
        <p>Thank you for your interest. Please read this page carefully before
        deciding whether to take part.</p>

        <h2>What this is</h2>
        <p>{html.escape(ORG_NAME)} is testing an automated text-message
        interviewer. This is a <strong>pilot test of the software</strong>,
        not a research study. Its purpose is to find out whether the system
        works reliably. The responses collected here will be used only to
        check that the technology functions correctly, and will be discarded
        rather than analysed or published as research.</p>

        <h2>What you will do</h2>
        <p>You will be given a short written persona describing a fictional
        parent and a fictional child. You will then have a text-message
        conversation with an automated interviewer, answering a standardized
        mental health questionnaire <strong>as that character</strong>.</p>
        <p>You will not be asked about your own child, your own family, or
        your own mental health. Please do not enter any real personal
        information about yourself or anyone you know. Answer in character
        throughout.</p>

        <h2>How long it takes</h2>
        <p>Expect <strong>{html.escape(DURATION_TEXT)}</strong>. The exact
        length depends on your answers, because some sections are skipped
        depending on how earlier questions are answered. You will receive
        roughly 100 to 200 text messages during the session.</p>
        <p>Please start only when you can give it an uninterrupted block of
        time. If you are interrupted, you can reply again later and the
        conversation will pick up where it left off.</p>

        <h2>How to stop</h2>
        <p>Taking part is voluntary and you may stop at any point without
        giving a reason. To stop, <strong>reply STOP</strong> to the text
        conversation. You can also simply close this page and return the
        study on Prolific. Stopping will not affect your standing on Prolific
        in any way.</p>

        <h2>What we collect and keep</h2>
        <p>We keep the text of the conversation and your Prolific ID. Your
        phone number reaches us as an unavoidable part of you sending a text
        message; it is converted to an irreversible code the moment it
        arrives, and the number itself is not stored. Because the answers
        describe a fictional character, the conversation contains no real
        information about any real child.</p>

        <h2>Messaging terms</h2>
        <p>Message and data rates may apply. Reply STOP to opt out, HELP for
        help. Your number will never be used for marketing and will not be
        sold or shared. See the
        <a href="{PRIVACY_URL}">privacy policy</a> and
        <a href="{TERMS_URL}">terms of use</a>, plus our
        <a href="/sms-terms">messaging terms</a>.</p>

        <h2>A note on the questions</h2>
        <p>The questionnaire is a standardized mental health screener, so some
        questions ask about difficult topics including low mood, self-harm,
        and substance use. You are answering these in character about a
        fictional child. If any of it brings up something real and difficult
        for you, please stop and reach out for support: in the US you can call
        or text <strong>988</strong> to reach the Suicide and Crisis Lifeline,
        any time.</p>

        <h2>Questions</h2>
        <p>Contact {html.escape(CONTACT_EMAIL)} with your Prolific ID if
        anything goes wrong or you want to know more.</p>

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
    """Record the consent decision and mint a code on agreement.

    Args:
        pid: Prolific participant ID.
        request: The form submission, carrying the decision field.

    Returns:
        A redirect to the code page or to the withdrawal return path.
    """
    participant = require(pid)
    form = await request.form()
    if form.get("decision") == "decline":
        store.set_stage(pid, Stage.WITHDREW)
        participant.stage = Stage.WITHDREW
        return RedirectResponse(
            PROLIFIC_COMPLETE_URL.format(code=CC_NO_CONSENT), status_code=303
        )

    if participant.stage is Stage.ARRIVED:
        store.set_stage(pid, Stage.CONSENTED)
        store.mint_code(pid, ttl_seconds=CODE_TTL_SECONDS)
    return RedirectResponse(f"/begin?pid={pid}", status_code=303)


@app.get("/begin", response_class=HTMLResponse)
async def begin(pid: str) -> HTMLResponse:
    """Display the study number and code, and poll for completion.

    The page stays open while the conversation happens on the
    participant's phone. Polling is the only way the browser learns that
    the out-of-band conversation finished.

    Args:
        pid: Prolific participant ID.

    Returns:
        The instructions and polling page.
    """
    participant = require(pid)
    if participant.stage is Stage.ARRIVED:
        return RedirectResponse(f"/consent?pid={pid}", status_code=303)

    sms_link = f"sms:{STUDY_SMS_NUMBER.replace(' ', '')}&body={participant.code}"
    return page(
        "Start the interview",
        f"""
        <h1>Text us to begin</h1>
        <div class="card">
          <p class="muted">Send a text message to</p>
          <div class="number">{html.escape(STUDY_SMS_NUMBER)}</div>
          <p class="muted">with this code as your first message</p>
          <div class="code">{html.escape(participant.code or '')}</div>
          <p style="text-align:center">
            <a class="btn" href="{html.escape(sms_link)}">Open my messaging app</a>
          </p>
        </div>

        <p><strong>Keep this page open.</strong> When the interview finishes,
        your completion link will appear here automatically. We will also text
        it to you, so you can close this page if you need to.</p>

        <p class="muted">Expect {html.escape(DURATION_TEXT)}. If you get
        interrupted, reply again any time within 24 hours and we will pick up
        where we left off. After 24 hours the conversation closes and cannot
        be resumed.</p>

        <p class="muted">You can stop at any time by replying STOP. If you do
        stop, or if you decide not to finish, email
        {html.escape(CONTACT_EMAIL)} with your Prolific ID so we can arrange
        payment for the part you completed &mdash; replying STOP ends the
        conversation, so we cannot send you a completion link.</p>

        <p class="muted">Message and data rates may apply. This code expires in
        six hours. No reply after a couple of minutes? Email
        {html.escape(CONTACT_EMAIL)} with your Prolific ID rather than
        submitting without a code, and we will sort out payment.</p>

        <div id="done" style="display:none">
          <h2>All finished</h2>
          <p>Thank you. Use the button below to register your completion on
          Prolific.</p>
          <a class="btn" id="done-link" href="#">Return to Prolific</a>
        </div>

        <script>
        const pid = {pid!r};
        async function poll() {{
          try {{
            const response = await fetch(`/status?pid=${{encodeURIComponent(pid)}}`);
            const state = await response.json();
            if (state.complete) {{
              document.getElementById("done-link").href = state.completion_url;
              document.getElementById("done").style.display = "block";
              return;
            }}
          }} catch (error) {{ /* transient; keep polling */ }}
          setTimeout(poll, 5000);
        }}
        poll();
        </script>
        """,
    )


@app.get("/status")
async def status(pid: str) -> dict[str, Any]:
    """Report whether the participant's conversation has finished.

    Args:
        pid: Prolific participant ID.

    Returns:
        The current stage, a completion flag, and the Prolific return URL
        once available.
    """
    participant = require(pid)
    code = completion_code_for(participant)
    complete = participant.stage is Stage.COMPLETE
    return {
        "stage": participant.stage.value,
        "complete": complete,
        "completion_url": (
            PROLIFIC_COMPLETE_URL.format(code=code) if complete and code else None
        ),
    }


class RetellFunctionCall(BaseModel):
    """Payload sent by a Retell Function node.

    Retell's "Payload: args only" toggle changes the request shape: when it
    is off the parameters arrive nested under ``args``, and when it is on
    they arrive at the top level alongside ``call``. Both are accepted so
    the endpoints keep working whichever way the node is configured.

    Attributes:
        args: Extracted arguments keyed by parameter name, when nested.
        call: Conversation context, including the chat identifier.
    """

    model_config = {"extra": "allow"}

    args: dict[str, Any] = {}
    call: dict[str, Any] = {}

    def argument(self, name: str) -> str:
        """Read one argument regardless of payload shape.

        Args:
            name: The parameter name configured on the Function node.

        Returns:
            The argument as a stripped string, empty if absent.

        Example:
            >>> RetellFunctionCall(args={"ac1": "pass"}).argument("ac1")
            'pass'
            >>> RetellFunctionCall(**{"ac1": "fail"}).argument("ac1")
            'fail'
        """
        if name in self.args:
            return str(self.args[name]).strip()
        extra = self.model_extra or {}
        return str(extra.get(name, "")).strip()

    def chat_identifier(self) -> str | None:
        """Return the conversation id from whichever field carries it.

        Returns:
            The chat or call id, or ``None`` when neither is present.
        """
        extra = self.model_extra or {}
        return (
            self.call.get("chat_id")
            or self.call.get("call_id")
            or extra.get("chat_id")
            or extra.get("call_id")
        )


@app.post("/api/verify-code")
async def verify_code(payload: RetellFunctionCall) -> dict[str, Any]:
    """Validate a code and bind the SMS conversation to a participant.

    This is the sole opportunity to establish the linkage: inbound SMS
    chats are created by the participant's message, so no metadata of ours
    is attached at creation. Configure the Function node with one string
    parameter named ``participant_code`` and branch on ``valid``.

    Args:
        payload: The Retell function-call body.

    Returns:
        ``valid``, a ``message`` safe for the agent to send verbatim, and
        on success the bound ``prolific_pid``.
    """
    raw = payload.argument("participant_code")
    chat_id = payload.chat_identifier()
    code = normalize_code(raw)

    pid, reason = store.redeem_code(code, chat_id, max_attempts=MAX_CODE_ATTEMPTS)
    if pid is None:
        messages = {
            "unknown": "That code was not recognised.",
            "expired": "That code has expired.",
            "used": "That code has already been used.",
            "too_many_attempts": "Too many attempts for this code.",
        }
        return {"valid": False, "message": messages.get(reason, "Code not accepted.")}

    return {"valid": True, "prolific_pid": pid, "message": "Code accepted."}


@app.post("/api/complete")
async def complete(payload: RetellFunctionCall) -> dict[str, Any]:
    """Mark a participant complete and return their completion link.

    Called by a Function node placed immediately before the End node, and
    the primary completion signal for this study. The webhook alone is not
    sufficient: the agent's silence timeout is twenty-four hours, so
    ``chat_ended`` may not fire until long after the participant has given
    up waiting and their Prolific submission has timed out.

    Configure the node with three optional string parameters ``ac1``,
    ``ac2``, and ``ac3``, passing the dynamic variables of the same name so
    the attention-check outcomes are recorded in one call.

    Args:
        payload: The Retell function-call body.

    Returns:
        The completion URL, which the final node should send to the
        participant verbatim, alongside the resolved outcome.
    """
    chat_id = payload.chat_identifier()
    participant = store.participant_by_chat(chat_id or "")
    if participant is None:
        return {"completed": False, "message": "Unrecognised conversation."}

    for tag in ("ac1", "ac2", "ac3"):
        verdict = payload.argument(tag).lower()
        if verdict in {"pass", "fail"}:
            store.record_check(participant.pid, tag, passed=verdict == "pass")

    store.set_stage(participant.pid, Stage.COMPLETE)
    participant = store.get_participant(participant.pid)
    assert participant is not None
    code = completion_code_for(participant)
    return {
        "completed": True,
        "completion_url": PROLIFIC_COMPLETE_URL.format(code=code),
        "failures": len(participant.checks_failed),
        "message": "Recorded.",
    }


@app.post("/api/attention-check")
async def attention_check(payload: RetellFunctionCall) -> dict[str, Any]:
    """Record the outcome of a single attention check.

    Called by a Function node placed immediately after each check in the
    conversation flow. Counting happens here rather than in the model so the
    failure threshold is applied deterministically and survives a retry.

    Configure the node with two parameters: ``check_id`` (a stable string
    such as ``"ac1"``) and ``passed`` (boolean). The flow must continue
    regardless of the returned value: a study of five minutes or longer may
    not screen a participant out on a single failed check, so the interview
    runs to completion and the outcome is resolved at the end.

    Args:
        payload: The Retell function-call body.

    Returns:
        An acknowledgement and the running failure count, for logging only.
    """
    chat_id = payload.chat_identifier()
    participant = store.participant_by_chat(chat_id or "")
    if participant is None:
        return {"recorded": False, "message": "Unrecognised conversation."}

    check_id = payload.argument("check_id") or "unlabelled"
    raw = payload.argument("passed").lower()
    passed = raw in {"true", "yes", "1", "pass", "passed"}

    failures = store.record_check(participant.pid, check_id, passed=passed)
    return {"recorded": True, "failures": failures, "message": "Recorded."}


@app.post("/api/retell-webhook")
async def retell_webhook(request: Request) -> dict[str, bool]:
    """Receive Retell chat lifecycle events.

    Completion is keyed on ``chat_ended`` rather than ``chat_analyzed``,
    because conversations closed by the inactivity timeout end without
    ever running analysis and would otherwise never complete.

    Verify the signature header before trusting this in production.

    Args:
        request: The raw webhook request.

    Returns:
        An acknowledgement; a 2xx within ten seconds prevents retries.
    """
    body = await request.json()
    event = body.get("event")
    chat = body.get("chat") or body.get("call") or {}
    chat_id = chat.get("chat_id") or chat.get("call_id")

    participant = store.participant_by_chat(chat_id or "")
    if participant is None:
        return {"ok": True}

    from_number = chat.get("from_number")
    if from_number:
        store.set_phone_hash(participant.pid, from_number)

    store.log_event(event or "webhook", pid=participant.pid, chat_id=chat_id)
    if event == "chat_ended" and participant.stage is Stage.TEXTING:
        store.set_stage(participant.pid, Stage.COMPLETE)
    return {"ok": True}


@app.get("/admin/linkage.csv")
async def linkage_export(token: str) -> Response:
    """Export the participant-to-conversation linkage table.

    This table is the only key connecting a Retell transcript to a Prolific
    submission, and therefore to Prolific's demographic export. It is held
    here rather than written into the transcript so that no direct
    identifier is stored by the vendor. Losing it makes every transcript
    permanently unattributable, so back it up alongside the data.

    Args:
        token: Shared secret matching ``ADMIN_TOKEN``.

    Returns:
        A CSV with one row per participant.

    Raises:
        HTTPException: 404 if the token does not match, chosen over 403 so
            the endpoint's existence is not confirmed to a prober.
    """
    if not ADMIN_TOKEN or token != ADMIN_TOKEN:
        raise HTTPException(status_code=404, detail="Not found")

    rows = [
        "prolific_pid,session_id,code,chat_id,stage,attention_failures,"
        "checks_seen,consented_at"
    ]
    for participant in store.all_participants():
        rows.append(
            ",".join(
                [
                    participant.pid,
                    participant.session_id or "",
                    participant.code or "",
                    participant.chat_id or "",
                    participant.stage.value,
                    str(len(participant.checks_failed)),
                    str(len(participant.checks_seen)),
                    f"{participant.consented_at:.0f}" if participant.consented_at else "",
                ]
            )
        )
    return Response("\n".join(rows) + "\n", media_type="text/csv")


@app.get("/finish")
async def finish(pid: str):
    """Return a finished participant to Prolific, or explain the alternative.

    The completion code is released only to participants whose conversation
    reached ``chat_ended``. Everyone else is directed to return the study on
    Prolific, which carries no penalty for them and produces no rejection on
    the researcher's record.

    Args:
        pid: Prolific participant ID.

    Returns:
        A redirect to Prolific on completion, otherwise an explanatory page.
    """
    participant = require(pid)
    code = completion_code_for(participant)
    if code is not None:
        return RedirectResponse(
            PROLIFIC_COMPLETE_URL.format(code=code), status_code=303
        )
    return page(
        "Returning the study",
        f"""
        <h1>No problem</h1>
        <p>Because the interview was not completed, there is no completion code
        to record. Please return the study on Prolific. Returning a study does
        not count against you and carries no penalty.</p>
        <p>If you did start the interview but something went wrong &mdash; the
        text never arrived, or the conversation stopped responding &mdash;
        email {html.escape(CONTACT_EMAIL)} with your Prolific ID and we will
        arrange payment manually.</p>
        <p class="muted">Your Prolific ID: {html.escape(pid)}</p>
        """,
    )
