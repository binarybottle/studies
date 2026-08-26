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
6. A Function node before the End node calls ``/api/complete``, which
   marks the participant complete and releases their completion code.
7. The polling page reveals the Prolific return link.

Completion is written only by ``/api/complete``. The ``chat_ended``
webhook marks anyone still at ``TEXTING`` as ``TIMED_OUT`` instead, which
covers both STOP and silent abandonment; neither earns a completion code.

Routes
------
``GET  /``                  Public study information page. Use this URL as
                            the opt-in URL in A2P campaign registration; it
                            requires no session and no query parameters.
``GET  /sms-terms``         Redirect to the canonical messaging terms.
``GET  /sms-privacy``       Redirect to the canonical privacy notice.
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
import json
import os
import re
import secrets
import time
from urllib.parse import quote
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
import httpx
from pydantic import BaseModel

import store
from store import Participant, Stage

STUDY_SMS_NUMBER = os.environ.get("STUDY_SMS_NUMBER", "+1 (507) 431-7807")
ORG_NAME = os.environ.get("ORG_NAME", "Child Mind Institute")
CONTACT_EMAIL = os.environ.get("CONTACT_EMAIL", "olivia.fitzpatrick@childmind.org")
PRIVACY_URL = "https://childmind.org/privacy/"
# The messaging policy pages are canonical on the organization's domain: they
# are the URLs submitted with the A2P campaign, and the versions a carrier
# reviewer has already passed. This site keeps no copy of its own — a second
# copy is how the pre-rejection opt-in wording survived on a live page after
# the canonical text had been corrected.
SMS_TERMS_URL = os.environ.get(
    "SMS_TERMS_URL", "https://matter.childmind.org/sms-terms/"
)
SMS_PRIVACY_URL = os.environ.get(
    "SMS_PRIVACY_URL", "https://matter.childmind.org/sms-privacy/"
)
TERMS_URL = "https://childmind.org/terms/"

# Expected duration drives the code lifetime and the wording on every page.
# The screener branches heavily, so the range is wide and stated as a range.
DURATION_TEXT = "30 to 60 minutes"

# The name on the A2P campaign application. A reviewer opening the opt-in
# URL matches what they read against the campaign in front of them, so the
# page has to call the program what the application calls it. The campaign
# covers the lab's participant messaging as a whole, not one study.
PROGRAM_NAME = "Child Mind Institute MATTER Lab"

# What this particular study calls itself, on its own pages. A different fact
# from the program name: one campaign covers many studies.
STUDY_NAME = "DASH text-message interviewer pilot"

# The public opt-in page, hosted on the organization's own CMS. It posts here
# from the browser, so its origin is the one allowed to call /api/opt-in.
OPTIN_PAGE_URL = os.environ.get(
    "OPTIN_PAGE_URL", "https://matter.childmind.org/studies/dash/opt-in/"
)
OPTIN_PAGE_ORIGIN = os.environ.get("OPTIN_PAGE_ORIGIN", "https://matter.childmind.org")
# Where that page posts its form. Read only by the page generator, which runs
# on a laptop rather than on the server, so this default is the value that
# matters -- setting it in the droplet's .env changes nothing.
OPTIN_API_URL = os.environ.get(
    "OPTIN_API_URL", "https://dash.studies.childmind.org/api/opt-in"
)

# The exact checkbox wording. Stored verbatim with every consent, so it is
# defined once here and rendered into every page that collects consent: the
# CMS page is generated from this constant rather than retyping it, because a
# disclosure that differs between the page and the audit record is worthless.
#
# It links the SMS notice and SMS terms rather than the organization-wide
# policy and terms. What a campaign review checks is the policy linked at the
# point of opt-in, and the no-sharing clause it looks for lives in the SMS
# notice; the organization-wide policy is a general document that does not
# mention messaging at all.
OPTIN_DISCLOSURE = (
    "I agree to receive text messages from the Child Mind Institute MATTER "
    "Lab at this number. Msg & data rates may apply. Msg freq varies. "
    "Reply STOP to cancel, HELP for help."
)
CONFIRMATION_SMS = (
    "Child Mind Institute MATTER Lab: You are opted in to research study "
    "messages. Msg & data rates may apply. Msg freq varies. "
    "Reply STOP to cancel, HELP for help."
)

# Outbound send. No credentials ship with this repo: the provider endpoint is
# whatever Retell exposes for sending from the study number, and until it is
# configured the endpoint records consent and reports that the confirmation
# was not sent rather than pretending it was.
# One credential for everything Retell: the dashboard API key. SMS_SEND_TOKEN
# is kept as an override for the case where a separate key is ever issued for
# sending, but leaving it unset is the normal configuration -- two names for
# one secret is how one of them ends up stale.
RETELL_API_KEY = os.environ.get("RETELL_API_KEY", "")
RETELL_AGENT_ID = os.environ.get("RETELL_AGENT_ID", "")
SMS_SEND_URL = os.environ.get(
    "SMS_SEND_URL", "https://api.retellai.com/create-sms-chat"
)
SMS_SEND_TOKEN = os.environ.get("SMS_SEND_TOKEN", "") or RETELL_API_KEY

# An endpoint that texts whatever number is posted to it is a way to text
# strangers. These caps are per rolling day.
MAX_OPTINS_PER_NUMBER = 3
MAX_OPTINS_PER_IP = 10
LAB_NAME = os.environ.get("LAB_NAME", "Child Mind Institute MATTER Lab")

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
    if participant.stage is Stage.TIMED_OUT:
        # Deliberately no code. The consent copy tells participants that
        # stopping ends the conversation and to email for payment covering
        # the part they completed, so /finish sends them there rather than
        # approving an interview that never finished.
        return None
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


def public_information_body() -> str:
    """Build the public study information markup.

    Shared by ``/`` and by ``/consent`` when it is opened without a
    participant ID, so that every URL a carrier reviewer might be given
    resolves to the same disclosures without a query string.

    The study number appears in the markup before any button, and the
    opt-in is described as the participant texting us. A campaign review
    reads a number revealed only after an agreement as "consent required
    to receive the service", which is not permitted; here the agreement
    records consent to take part and reveals nothing but a session code.

    Returns:
        The inner HTML of the information page.
    """
    return f"""
        <h1>{html.escape(STUDY_NAME)}</h1>
        <p class="muted">A study of {html.escape(LAB_NAME)}.
        {html.escape(ORG_NAME)} is a nonprofit children's mental health
        organization.</p>

        <p>This page describes a text-message conversation program being
        piloted to test whether an automated interviewer works reliably. It is
        a pilot test of the software rather than a research study: the
        responses are used only to check that the technology functions
        correctly, and the research study it prepares for has not yet
        begun.</p>

        <h2>The study number, and how to opt in</h2>
        <div class="card">
          <p class="muted">Messages in this program are sent from and received
          at</p>
          <div class="number">{html.escape(STUDY_SMS_NUMBER)}</div>
          <p>The number is published here so that anyone can see it without
          agreeing to anything first.</p>
        </div>

        <p><strong>You opt in on our
        <a href="{OPTIN_PAGE_URL}">opt-in page</a></strong>, by entering your
        mobile number and ticking a box to agree. The box is not ticked for
        you, and nothing is sent unless you tick it. We then send one
        confirmation text, and the interview itself starts when you text us.
        There is no other way to join: we do not buy, rent, or import phone
        number lists.</p>

        <div class="card">
          <p>By opting in you agree to receive text messages from the
          {html.escape(PROGRAM_NAME)}.
          <strong>Message frequency varies</strong>; one session runs
          {html.escape(DURATION_TEXT)} as a continuous conversation of
          approximately 100 to 200 messages.
          <strong>Message and data rates may apply.</strong> Reply
          <strong>STOP</strong> at any time to cancel. Reply
          <strong>HELP</strong> for help, or email
          <a href="mailto:{html.escape(CONTACT_EMAIL)}">{html.escape(CONTACT_EMAIL)}</a>.
          Carriers are not liable for delayed or undelivered messages.</p>
        </div>

        <p>Participants recruited through Prolific are also given a
        five-character code to send as that first message. The code is how a
        conversation is matched to a Prolific submission so the participant
        can be paid. It identifies a session; it is not what permits us to
        message anyone, and messaging begins only once the participant has
        texted us.</p>

        <h2>What participants do</h2>
        <p>Participants are recruited through the Prolific research platform.
        Each participant is given a short written persona describing a
        fictional parent and child, and is asked to answer a standardized
        mental health screening questionnaire in character. No participant is
        asked about their own child or their own mental health.</p>

        <h2>What the messages look like</h2>
        <p class="muted">Hello! I am an AI assistant from
        {html.escape(ORG_NAME)}, messaging you to ask some questions about the
        child described in the persona you were given, as part of the DASH
        Mental Health Screener. The first few questions ask about the child's
        physical health.</p>

        <h2>Messaging terms</h2>
        <ul>
          <li>No marketing or promotional messages are ever sent from this
              number.</li>
          <li>Phone numbers are used only to conduct the conversation. They
              are not sold, rented, or shared with third parties, and are not
              used for marketing.</li>
          <li>A number reaches us only because someone texted us. It is
              hashed on arrival and the number itself is never stored.</li>
        </ul>

        <p class="muted">Taking part through Prolific? Open the study from
        your Prolific dashboard to continue; the link there carries the
        identifier that resumes your session.</p>

        <p class="muted">Questions: {html.escape(CONTACT_EMAIL)} &middot;
        <a href="{SMS_PRIVACY_URL}">SMS privacy notice</a> &middot;
        <a href="{SMS_TERMS_URL}">SMS terms and conditions</a> &middot;
        <a href="{PRIVACY_URL}">Organization privacy policy</a> &middot;
        <a href="{TERMS_URL}">Organization terms of use</a></p>
        """


@app.get("/", response_class=HTMLResponse)
async def public_information() -> HTMLResponse:
    """Serve the public study information page.

    This is the URL to submit as the A2P campaign opt-in URL. It must stay
    reachable with no session, no query parameters, and no login, because
    carrier reviewers open it directly.

    Returns:
        The information page.
    """
    return page(STUDY_NAME, public_information_body())


@app.get("/sms-privacy")
async def sms_privacy() -> RedirectResponse:
    """Redirect to the canonical SMS privacy notice.

    The notice itself lives on the organization's domain, which is the URL
    submitted as the campaign's Privacy Policy URL. The route is kept so
    that links printed or indexed before the move continue to resolve.

    Returns:
        A permanent redirect.
    """
    return RedirectResponse(SMS_PRIVACY_URL, status_code=301)


@app.get("/sms-terms")
async def sms_terms() -> RedirectResponse:
    """Redirect to the canonical SMS terms and conditions.

    Returns:
        A permanent redirect.
    """
    return RedirectResponse(SMS_TERMS_URL, status_code=301)


def missing_identifier_page() -> HTMLResponse:
    """Explain that a study link arrived without its Prolific identifiers.

    Returned instead of the framework's validation error, which renders as
    raw JSON and leaves the participant with nothing to act on. The status
    is 400 so the condition is still visible in the access log.

    Returns:
        The explanatory page, with a 400 status.
    """
    response = page(
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
        <a href="mailto:{html.escape(CONTACT_EMAIL)}">{html.escape(CONTACT_EMAIL)}</a>
        so we can look into it.</p>
        """,
    )
    response.status_code = 400
    return response


@app.get("/start")
async def start(
    PROLIFIC_PID: str | None = None,
    STUDY_ID: str | None = None,
    SESSION_ID: str | None = None,
):
    """Entry point registered as the Prolific external study URL.

    Re-entry resumes at the participant's recorded stage rather than
    resetting it, so refreshing cannot replay the study or mint a
    second code.

    Prolific substitutes the identifiers into the URL itself, so a request
    without ``PROLIFIC_PID`` means the participant arrived some other way:
    a bookmark, a link shared between participants, or a study URL saved
    before the query parameters were configured. They are shown an
    explanation rather than a validation error.

    Args:
        PROLIFIC_PID: Participant ID substituted by Prolific.
        STUDY_ID: Study ID substituted by Prolific.
        SESSION_ID: Session ID substituted by Prolific.

    Returns:
        A redirect to the appropriate stage, or the missing-identifier page
        when Prolific's identifiers are absent.
    """
    if not PROLIFIC_PID:
        store.log_event("start_without_pid")
        return missing_identifier_page()

    participant = store.create_participant(PROLIFIC_PID, STUDY_ID, SESSION_ID)

    destinations = {
        Stage.ARRIVED: f"/consent?pid={PROLIFIC_PID}",
        Stage.CONSENTED: f"/begin?pid={PROLIFIC_PID}",
        Stage.TEXTING: f"/begin?pid={PROLIFIC_PID}",
        Stage.COMPLETE: f"/begin?pid={PROLIFIC_PID}",
        Stage.TIMED_OUT: f"/finish?pid={PROLIFIC_PID}",
        Stage.WITHDREW: f"/finish?pid={PROLIFIC_PID}",
    }
    return RedirectResponse(destinations[participant.stage], status_code=303)


class UnknownParticipant(HTTPException):
    """Raised when a ``pid`` matches no stored participant.

    A distinct class so one handler can answer it two ways: participants
    browsing ``/consent``, ``/begin``, or ``/finish`` get an explanation
    they can act on, while ``/status`` and the Retell endpoints keep the
    JSON body their callers already parse.
    """

    def __init__(self) -> None:
        super().__init__(status_code=404, detail="Unknown participant")


# Paths whose callers are code rather than people: the /begin poller, the
# Retell function nodes, and the linkage export.
MACHINE_PATH_PREFIXES = ("/status", "/api/", "/admin/")


@app.exception_handler(UnknownParticipant)
async def unknown_participant_handler(
    request: Request, exc: UnknownParticipant
) -> Response:
    """Answer an unrecognised ``pid`` in the form its caller expects.

    Args:
        request: The request that raised, used to tell people from code.
        exc: The raised exception.

    Returns:
        The stale-link page for participants, or the original JSON body
        for the polling and integration endpoints.
    """
    if request.url.path.startswith(MACHINE_PATH_PREFIXES):
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)

    response = page(
        "Study link expired",
        f"""
        <h1>This link is no longer valid</h1>
        <p>The link you opened refers to a study session we have no record
        of. That usually means it was copied from somewhere else, or it is
        left over from an earlier session that has since closed.</p>

        <h2>What to do</h2>
        <p>Go back to Prolific and open the study from your list of active
        studies. That will put you back at the right place.</p>

        <p class="muted">If you had already texted us and were part-way
        through the interview, do not start over. Email
        <a href="mailto:{html.escape(CONTACT_EMAIL)}">{html.escape(CONTACT_EMAIL)}</a>
        with your Prolific ID and we will arrange payment for the part you
        completed.</p>
        """,
    )
    response.status_code = exc.status_code
    return response


@app.exception_handler(RequestValidationError)
async def validation_handler(
    request: Request, exc: RequestValidationError
) -> Response:
    """Explain a malformed participant URL instead of dumping the error.

    A participant route can fail validation for exactly one reason: the
    ``pid`` query parameter is absent, which means the link lost its query
    string. The framework's default body is raw JSON, which a participant
    can neither read nor act on.

    Args:
        request: The request that failed validation.
        exc: The raised validation error.

    Returns:
        The missing-identifier page, or the default JSON body for the
        polling and integration endpoints.
    """
    if request.url.path.startswith(MACHINE_PATH_PREFIXES):
        return JSONResponse(
            {"detail": jsonable_encoder(exc.errors())}, status_code=422
        )
    return missing_identifier_page()


def require(pid: str) -> Participant:
    """Fetch a participant record or fail.

    Args:
        pid: Prolific participant ID.

    Returns:
        The stored record.

    Raises:
        UnknownParticipant: 404 when the participant never passed through
            ``/start``, indicating a hand-built or stale URL.
    """
    participant = store.get_participant(pid)
    if participant is None:
        raise UnknownParticipant()
    return participant


@app.get("/consent", response_class=HTMLResponse)
async def consent_form(pid: str | None = None) -> HTMLResponse:
    """Present the consent information sheet.

    Replace the body text with the IRB-approved wording verbatim; the
    structure below is a placeholder that covers the elements carriers and
    review boards both expect to see.

    Without a ``pid`` the request is not a participant's: a carrier
    reviewer opening the URL from a campaign application, or a link copied
    without its query string. Those get the public information page rather
    than a validation error, so every URL the campaign lists resolves to
    the disclosures with no query parameters required.

    Args:
        pid: Prolific participant ID, absent for a public visitor.

    Returns:
        The consent page, or the public information page.
    """
    if not pid:
        return page(STUDY_NAME, public_information_body())

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

        <h2>The study number</h2>
        <div class="card">
          <p class="muted">You will text</p>
          <div class="number">{html.escape(STUDY_SMS_NUMBER)}</div>
          <p>Agreeing below records your consent to take part in the pilot. It
          does not send you any messages and does not sign you up for anything.
          Text messages are a separate, optional step: after this page you are
          shown our opt-in page, where you enter your mobile number and tick a
          box to agree to receive them. You can take part only if you complete
          that step, but nothing is sent to you until you do.</p>
        </div>

        <h2>Messaging terms</h2>
        <p>Message and data rates may apply, and this study is unusually
        message-heavy: expect roughly 100 to 200 messages in one session.
        Reply STOP to opt out, HELP for
        help. Your number will never be used for marketing and will not be
        sold or shared. See the
        <a href="{PRIVACY_URL}">privacy policy</a> and
        <a href="{TERMS_URL}">terms of use</a>, plus our
        <a href="{SMS_TERMS_URL}">messaging terms</a> and
        <a href="{SMS_PRIVACY_URL}">SMS privacy notice</a>, which describes
        what happens to your phone number.</p>

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

        <h2>Your decision</h2>
        <p>Agreeing takes you to the next step: opting in to text messages,
        and then the number again with your one-time code. Declining returns
        you to Prolific straight away, with a code that pays you for the time
        you spent reading this. Either way you are never sent a text message
        you did not ask for.</p>

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

    # The study number is configured for display, so strip it to E.164 before
    # putting it in a URI: "sms:+1 (507) 431-7807" is not a link any handset
    # parses. The separator differs by platform -- RFC 5724 says "?", which
    # Android follows, while iOS wants "&" -- so the page ships the standard
    # form and a few lines of script swap it on iOS. Either way the recipient
    # is right, and the code is displayed on the page regardless, so a handset
    # that prefills nothing costs a participant one paste rather than the
    # conversation.
    sms_number = normalize_phone(STUDY_SMS_NUMBER) or STUDY_SMS_NUMBER
    sms_link = f"sms:{sms_number}?body={participant.code}"
    optin_link = f"{OPTIN_PAGE_URL}?pid={quote(pid)}"
    return page(
        "Start the interview",
        f"""
        <h1>Two steps to begin</h1>

        <h2>Step 1: opt in to text messages</h2>
        <p><a class="btn" href="{html.escape(optin_link)}">Opt in to text
        messages</a></p>
        <p class="muted">This opens our opt-in page, where you enter your
        mobile number and tick a box to agree to receive messages. The box is
        not ticked for you. We send one confirmation text, and then you send
        the code below. Opting in through that page is what records your
        permission to be messaged.</p>

        <h2>Step 2: text us the code</h2>
        <div class="card">
          <p class="muted">Send a text message to</p>
          <div class="number">{html.escape(STUDY_SMS_NUMBER)}</div>
          <p class="muted">with this code as your first message</p>
          <div class="code">{html.escape(participant.code or '')}</div>
          <p style="text-align:center">
            <a class="btn" id="sms-link"
               href="{html.escape(sms_link)}">Open my messaging app</a>
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
        // iOS does not follow RFC 5724 here: it expects & where the standard
        // says ?. Rewriting on the client keeps one link correct on both.
        if (/iPad|iPhone|iPod/.test(navigator.userAgent)) {{
          const link = document.getElementById("sms-link");
          if (link) {{ link.href = link.href.replace("?body=", "&body="); }}
        }}

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


async def retell_payload(request: Request) -> RetellFunctionCall:
    """Read a Retell function-call body whether it is JSON or form encoded.

    A custom tool's ``parameter_type`` decides which one it sends, and that
    setting lives in the Retell dashboard rather than here. Accepting both
    means the setting cannot silently break the linkage: a body this
    application refuses is a 422, which leaves ``code_valid`` unset, which
    is exactly the case the agent flow has to treat as "do not proceed".

    Args:
        request: The incoming request.

    Returns:
        The parsed payload, empty rather than raising when the body is
        missing or unreadable. The endpoints already handle absent
        arguments, and refusing the request outright is the worse failure.
    """
    body = await request.body()
    if not body:
        return RetellFunctionCall()

    data: Any = None
    if "form" in request.headers.get("content-type", ""):
        data = dict(await request.form())
    else:
        try:
            data = json.loads(body)
        except ValueError:
            data = dict(await request.form())

    if not isinstance(data, dict):
        return RetellFunctionCall()

    # Form encoding flattens everything to strings, so a nested object
    # arrives as its JSON text. Restore the two the model declares.
    for key in ("args", "call"):
        if isinstance(data.get(key), str):
            try:
                data[key] = json.loads(data[key])
            except ValueError:
                data.pop(key)
        if key in data and not isinstance(data[key], dict):
            data.pop(key)

    return RetellFunctionCall(**data)


def normalize_phone(raw: str) -> str | None:
    """Reduce a typed phone number to E.164, or reject it.

    Deliberately narrow: North American numbers only, which is the only
    region this study recruits in. A number that does not fit is refused
    rather than guessed at, because the cost of guessing is a text message
    sent to a stranger.

    Args:
        raw: The number as typed, in any common punctuation.

    Returns:
        The E.164 number, or None if it is not a valid NANP number.

    Example:
        >>> normalize_phone("(507) 431-7807")
        '+15074317807'
        >>> normalize_phone("1-507-431-7807")
        '+15074317807'
        >>> normalize_phone("+44 20 7946 0958") is None
        True
        >>> normalize_phone("555-1234") is None
        True
    """
    digits = re.sub(r"\D", "", raw)
    if raw.strip().startswith("+") and not digits.startswith("1"):
        return None
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10:
        return None
    # NANP area codes and exchange codes both start 2-9.
    if digits[0] in "01" or digits[3] in "01":
        return None
    return f"+1{digits}"


async def send_confirmation_sms(number: str) -> str:
    """Send the opt-in confirmation message.

    Posts to Retell's ``create-sms-chat``, which opens an outbound-initiated
    SMS chat from the study number. Three things Retell confirmed on 25
    August 2026, none of them guesses any more:

    The ``text`` below is **ignored**. The first outbound message is always
    the begin message of the agent bound to ``from_number``, which for a
    conversation flow is its start node. It is sent regardless so the
    payload records what the message is meant to say, and both come from
    ``CONFIRMATION_SMS``, so the two cannot disagree.

    The participant's later reply lands in this same chat rather than
    opening a new one, keyed to the conversation already open on the DID.
    That is what makes the code they text arrive where the verification
    node is waiting for it.

    No timer starts when the chat is created, but the auto-close clock runs
    from the last message in either direction, which at that point is the
    confirmation, and it resets on every inbound message. Someone who opts
    in on a laptop and texts back the next morning is inside the window
    only because the flow sets it to 72 hours.

    Args:
        number: E.164 destination.

    Returns:
        ``"sent"``, ``"failed"``, or ``"unconfigured"`` when no provider
        endpoint is set. The caller records whichever it gets: a consent
        whose confirmation never went out is still a consent, and the
        difference is exactly what an audit would ask about. Note that a
        carrier silently filters outbound messages until the A2P campaign
        is approved, so ``"sent"`` means the provider accepted it, not that
        it was delivered.
    """
    if not SMS_SEND_URL or not SMS_SEND_TOKEN:
        store.log_event("confirmation_unconfigured")
        return "unconfigured"
    # The study number is configured in a human-readable form for display.
    # The API wants E.164, and rejects the punctuation.
    from_number = normalize_phone(STUDY_SMS_NUMBER) or STUDY_SMS_NUMBER
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                SMS_SEND_URL,
                headers={"Authorization": f"Bearer {SMS_SEND_TOKEN}"},
                json={
                    "from_number": from_number,
                    "to_number": number,
                    "text": CONFIRMATION_SMS,
                },
            )
        response.raise_for_status()
    except Exception as error:  # noqa: BLE001 - provider errors are opaque
        store.log_event("confirmation_failed", detail=type(error).__name__)
        return "failed"

    # The response identifies the chat this opened. Recording it means a
    # conversation can still be traced to its opt-in if the participant
    # never sends their code, which the linkage table alone would miss.
    try:
        chat_id = response.json().get("chat_id")
    except Exception:  # noqa: BLE001 - a non-JSON body is not an error here
        chat_id = None
    store.log_event("confirmation_sent", chat_id=chat_id)
    return "sent"


class OptIn(BaseModel):
    """Payload from the opt-in form.

    Attributes:
        phone: The number as typed by the person.
        consent: Whether the disclosure checkbox was checked. The field
            has no default: an absent value is a rejected submission, not
            an assumed yes.
        pid: Prolific participant ID, when a recruited participant opts in
            rather than a member of the public.
    """

    phone: str
    consent: bool
    pid: str | None = None


def cors_headers() -> dict[str, str]:
    """Return the headers letting the CMS page call this endpoint.

    The opt-in page is served from the organization's CMS and posts here
    from the browser, which makes this a cross-origin request. Exactly one
    origin is allowed.

    Returns:
        Response headers for the opt-in endpoint.
    """
    return {
        "Access-Control-Allow-Origin": OPTIN_PAGE_ORIGIN,
        "Access-Control-Allow-Headers": "content-type",
        "Access-Control-Allow-Methods": "POST, OPTIONS",
        "Access-Control-Max-Age": "600",
    }


@app.options("/api/opt-in")
async def opt_in_preflight() -> Response:
    """Answer the browser's preflight for the cross-origin opt-in POST.

    Returns:
        An empty 204 carrying the CORS headers.
    """
    return Response(status_code=204, headers=cors_headers())


@app.post("/api/opt-in")
async def opt_in(payload: OptIn, request: Request) -> JSONResponse:
    """Record express written consent and send the confirmation message.

    This is the opt-in of record. The checkbox is unchecked when the page
    loads, the disclosure sits beside it, and this endpoint refuses the
    submission unless it arrives checked — an opt-in that can happen by
    default is not consent.

    Args:
        payload: Number, consent flag, and optional Prolific ID.
        request: The request, for the caller address used in rate limiting.

    Returns:
        A JSON body the page shows the visitor. It reports whether the
        confirmation message went out, and never reveals whether a number
        had opted in before: that would turn the endpoint into a way of
        testing whether a given number is in the study.
    """
    headers = cors_headers()
    if not payload.consent:
        return JSONResponse(
            {"ok": False, "error": "Please tick the box to agree before continuing."},
            status_code=400,
            headers=headers,
        )

    number = normalize_phone(payload.phone)
    if number is None:
        return JSONResponse(
            {
                "ok": False,
                "error": "Please enter a 10-digit US or Canadian mobile number.",
            },
            status_code=400,
            headers=headers,
        )

    caller = request.client.host if request.client else None
    if store.optin_count(number=number) >= MAX_OPTINS_PER_NUMBER or (
        caller and store.optin_count(ip=caller) >= MAX_OPTINS_PER_IP
    ):
        store.log_event("optin_rate_limited")
        return JSONResponse(
            {
                "ok": False,
                "error": "That number has already been signed up today. "
                f"Email {CONTACT_EMAIL} if you need help.",
            },
            status_code=429,
            headers=headers,
        )

    confirmation = await send_confirmation_sms(number)
    store.record_optin(
        number,
        disclosure=OPTIN_DISCLOSURE,
        confirmation=confirmation,
        pid=payload.pid,
        ip=caller,
    )
    if payload.pid:
        store.set_phone_hash(payload.pid, number)

    return JSONResponse(
        {
            "ok": True,
            "confirmed": confirmation == "sent",
            "message": (
                "You are opted in. Check your phone for a confirmation text, "
                f"then text {STUDY_SMS_NUMBER} to begin."
                if confirmation == "sent"
                else "You are opted in. Text "
                f"{STUDY_SMS_NUMBER} to begin."
            ),
        },
        headers=headers,
    )


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
async def verify_code(payload: RetellFunctionCall = Depends(retell_payload)) -> dict[str, Any]:
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
async def complete(payload: RetellFunctionCall = Depends(retell_payload)) -> dict[str, Any]:
    """Mark a participant complete and return their completion link.

    Called by a Function node placed immediately before the End node, and
    the primary completion signal for this study. The webhook alone is not
    sufficient: the agent's silence timeout is seventy-two hours, so
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
async def attention_check(payload: RetellFunctionCall = Depends(retell_payload)) -> dict[str, Any]:
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
        # Still TEXTING at chat_ended means /api/complete never ran, so the
        # interview did not reach its final node. Record that rather than
        # inferring completion: a participant who texts STOP, or who simply
        # stops replying, also ends up here, and paying them the full
        # completion code for an abandoned interview is both wrong and
        # invisible in the data.
        store.set_stage(participant.pid, Stage.TIMED_OUT)
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
