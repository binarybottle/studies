# DASH text-message pilot — status handoff

A self-contained briefing. Written to be pasted to an assistant that cannot
see the repository, so everything needed to help is stated here rather than
referenced.

## What this project is

The Child Mind Institute MATTER Lab is piloting an automated text-message
interviewer. Participants are recruited on Prolific, given a written persona
describing a fictional parent and child, and answer a standardized mental
health screening questionnaire **in character**. The same interview runs two
ways — by SMS, or in a web browser — and a participant choosing the browser
never gives us a phone number. Nobody is asked about their own child or their
own mental health. It is a test of whether the
software works, not a research study; a research study may follow and has not
yet been submitted for Institutional Review Board review.

The blocker for the last several weeks has been the **A2P 10DLC campaign** —
the carrier registration every organization must pass before sending any SMS
in the US. It has been rejected three times. Nothing can launch by text
message until it is approved; the browser channel works today and is not
affected.

## Key facts

| Thing | Value |
| --- | --- |
| Study SMS number (DID) | +1 (507) 431-7807 |
| Study site (participant flow) | https://study.arnoklein.info |
| Prolific study URL | https://study.arnoklein.info/start |
| Opt-in page (cited in the campaign) | https://matter.childmind.org/studies/dash/opt-in/ |
| A2P campaign / program name | Child Mind Institute MATTER Lab |
| SMS terms | https://matter.childmind.org/sms-terms/ |
| SMS privacy notice | https://matter.childmind.org/sms-privacy/ |
| Pilot information page | https://matter.childmind.org/text-study/ |
| Study contact (participants) | olivia.fitzpatrick@childmind.org |
| Policy contact (legal) | lindsay.alexander@childmind.org |
| Server | DigitalOcean droplet, 167.71.248.46 |
| SMS/agent provider | Retell |
| Team | Mike, Laura, Lauren, Olivia, Arno |

Two code repositories:

- **studies** — the participant-facing web application. FastAPI + SQLite in
  Docker, behind Caddy for TLS. One container per study; `dash/` is this
  study.
- **matter-website** — the MATTER Lab site, Jekyll on GitHub Pages, serving
  matter.childmind.org. Hosts the opt-in page and the two policy pages. Note
  it is behind a Cloudflare bot challenge that returns 403 to anything that
  is not a real browser, so it cannot be checked with curl.

## How the flow works now

1. Prolific sends the participant to `/start` with their identifiers.
2. `/consent` shows the information sheet. Agreeing records consent to take
   part; it sends no messages.
3. `/begin` offers the interview. While `SMS_ENABLED` is unset — which it is,
   because carriers filter A2P traffic until the campaign is approved — it
   offers the browser only. With it set, it offers both, device-appropriate
   one first, and both are always available.
4. **By text:** the opt-in page on matter.childmind.org collects a mobile
   number and an **unchecked** checkbox carrying the SMS disclosure.
   Submitting posts to `POST /api/opt-in` on the study site, which records the
   consent and asks Retell to send a confirmation text. The participant then
   texts their five-character code; Retell's function node calls
   `/api/verify-code`, which binds the conversation to the Prolific
   submission — the only point at which that link can be made.
5. **In the browser:** `/chat` runs the same Retell agent over
   `/api/chat/start` and `/api/chat/send`. No phone number is involved and the
   code is bound at chat creation.
6. At the end, a function node calls `/api/complete`, which releases the
   Prolific completion code.

Phone numbers are hashed on arrival and never stored in plaintext. The
database on the droplet is the only key connecting a transcript to a Prolific
submission.

## Rejection 3, 26 August 2026

> rejected because of provided Opt-in information.; ... rejected because
> consent cannot be a required condition for service or transaction
> completion.

Two causes, both now addressed in the repository but **one still blocked on
CMI IT**:

1. **The filed URLs return 403 to the reviewer.** Checked 26 Aug 2026: the
   opt-in page, `/sms-terms/`, `/sms-privacy/` and `/text-study/` all answer
   403 to any non-browser client. TCR fetches them with a script, so it saw
   challenge pages instead of disclosures. The existing Cloudflare skip rule
   does not cover Super Bot Fight Mode and its expression covers `/studies/`
   only. **Do not resubmit until `curl` returns 200 for all four** — this is
   invisible from a browser.
2. **Everything we had filed said SMS was the only way to take part.** Field 5
   said "no other route to opting in exists"; the study site said "there is no
   other way to join"; `text-study/` said "to take part, opt in". All meant
   *no other way a number reaches us*, and all read as *consent to SMS is
   required for service*. Fixed: the browser channel is now stated
   affirmatively in field 3, field 5, the opt-in page, the study site's public
   information page, `sms-terms/` and `text-study/`. A participant who never
   opts in completes the study and is paid identically.

## Why the campaign was rejected earlier, and what changed

**Rejection 1** — the study number was shown only after a participant agreed,
which a carrier review reads as "consent is required to receive the service".
Also the opt-in URL returned an error without a query parameter, so a reviewer
opening it directly saw nothing.

**Rejection 2** — five items, all now addressed:

1. Opt-in page must be on a Child Mind Institute domain, publicly reachable
   with no login and no query string, showing the number on the page.
   → Published at matter.childmind.org/studies/dash/opt-in/.
2. The consent field must cite that URL inline and describe an explicit
   opt-in action. → Rewritten.
3. Sample messages must not contain unsubstituted tokens, and one must be a
   welcome/confirmation with the full footer. → Both rewritten.
4. The privacy policy linked at the point of opt-in must carry an explicit
   no-sharing clause. → The checkbox now links the SMS privacy notice, which
   carries it, rather than the organization-wide policy, which does not
   mention messaging.
5. TCR wants an explicit consent action — a checkbox — followed by a
   confirmation SMS, rather than treating "the participant texted us first"
   as the opt-in. → Built.

The campaign is being resubmitted at **program level**, as the Child Mind
Institute MATTER Lab's participant messaging, rather than as one DASH
application. The opt-in page and both policy pages describe the program, not a
single study; only the study site's own pages name the DASH pilot. One
consequence: the campaign covers studies that do not exist yet, so nothing
published under it should be worded as if DASH were the only one.

## What is waiting on other people

| Waiting on | What | Why it matters |
| --- | --- | --- |
| Twilio, via Retell | Whether the confirmation SMS must precede the participant's first inbound message | If not, the opt-in form drops the phone number field and goes back to a checkbox alone, restoring the property that a number only ever reaches us because someone texted us. Retell is opening a support ticket rather than guessing. |
| — | Three questions about `create-sms-chat` | **Answered 25 Aug 2026.** `text` is ignored, the agent's begin message decides; the participant's reply lands in the chat that call opened; no timer starts at creation, but auto-close runs from the last message, which is the confirmation. All three match the patched flow. |
| — | DNS record `*.studies.childmind.org` → 167.71.248.46 | **Done, 25 Aug 2026.** Resolves at the authoritative nameservers and at 1.1.1.1, wildcard confirmed, grey cloud. The hostname switch is now ours to do: see `dash/optin/hostname-switch.md`. |
| CMI IT | Cloudflare bot-challenge exemption on matter.childmind.org | **This caused rejection 3.** Re-checked 26 Aug 2026: `/studies/dash/opt-in/`, `/sms-terms/`, `/sms-privacy/` and `/text-study/` all return 403 to a non-browser. The challenge is Super Bot Fight Mode on "definitely automated traffic". A skip rule exists and matches, but skips managed rules and rate limiting rather than SBFM, which is its own checkbox; and its expression covers `/studies/` only. It must cover all four paths, and skip SBFM. Nothing else can proceed until `curl` returns 200. |
| TCR | Campaign approval | No SMS can be sent at all until this lands, including the confirmation message. |

## What is left to do

Owned by us, in order:

1. **Chase CMI IT on the Cloudflare exemption.** Nothing else matters until
   all four URLs return 200 to `curl`. See rejection 3 above.
2. **Deploy the consent-wording changes** (`docker compose up -d --build
   dash`) and **push `matter-website`** — the opt-in page, `sms-terms.html`
   and `text-study.html` are edited and uncommitted there.
3. **Put the Retell API key on the droplet** as `SMS_SEND_TOKEN` in
   `dash/.env`, then redeploy.
4. **Set the outbound agent's begin message** in the Retell dashboard to
   exactly the confirmation text registered with the campaign:
   *"Child Mind Institute MATTER Lab: You are opted in to research study
   messages. Msg & data rates may apply. Msg freq varies. Reply STOP to
   cancel, HELP for help."*
5. **Resubmit the A2P campaign.** The field text is written and ready.
6. **Check the Prolific completion paths** — three codes exist (complete,
   attention-check failure, no-consent screen-out) and each needs the right
   action attached. Never a rejection.
7. **Dry-run the participant path** in a browser with a fresh Prolific ID.
8. **On approval:** verify a confirmation text actually arrives before any
   participant sees the page.
9. **When DNS lands:** switch hostnames. A runbook exists; four places name
   the host and three fail quietly if missed.

## The agent flow, as of 25 August 2026

The patched flow is imported: the start node is the confirmation, the
verification path is reachable, HELP has a fixed answer and auto-close is 72
hours. **Check that the version is published** — the export reads
`is_published: false`, which for a draft version means the live number may
still be answering with the old flow.

## What the agent flow used to do

The exported Retell flow reaches 412 of its 423 nodes from the start node.
`Extract study code`, `Verify code` and `Code not accepted` are among the
eleven it never reaches: they form a closed loop nothing points into, so the
interview begins without a code and no conversation is ever bound to a
Prolific submission. Fixing this is independent of the campaign and has to
happen before any participant reaches the agent. Step-by-step dashboard
changes are in `dash/optin/retell-flow-changes.md`.

## Traps — things that look fine and are not

- **The confirmation text cannot be tested before approval.** Carriers filter
  outbound A2P messages until the campaign is approved, and approval is what
  we are applying for. A successful API call before then means Retell accepted
  it, not that anyone received it.
- **Retell's `create-sms-chat` opens a chat; the first message is written by
  the agent bound to the number, not by the text our code sends.** If that
  agent's begin message is not the registered confirmation wording,
  participants receive something different from what the carrier approved.
- **Because it opens a chat, the participant's later message lands in a
  conversation that is already live.** The agent must not start interviewing
  before `/api/verify-code` succeeds, or someone who opted in from the public
  page gets interviewed with no code and no linkage.
- **The agent's silence timers may start at opt-in rather than at the
  participant's first message.** Someone who opts in on a laptop and texts
  the next morning could find the chat closed.
- **matter.childmind.org cannot be checked with curl** — Cloudflare returns
  403 to non-browsers. Always verify those pages in a browser.

## Decisions already made, with reasons

Please do not re-open these without a reason; each cost real time.

- **The opt-in page is generated from the application's constants**, not
  written by hand in the website repository. The disclosure wording must be
  identical on the page and in the consent record stored for each person, and
  keeping two copies is how they drift. A previous duplicate is exactly how
  pre-rejection wording stayed live after the canonical text was corrected.
- **The study site no longer serves its own copies of the policy pages.**
  Those live on matter.childmind.org and the study site redirects to them.
- **Two different contact addresses, deliberately.** Policy pages publish the
  legal contact; study-facing pages publish the person managing the study. A
  policy question and a "my code did not arrive" question should not land in
  the same inbox.
- **The five-character code is not the opt-in.** It identifies a session so a
  conversation can be matched to a Prolific submission for payment. The
  campaign application says this explicitly, because a reviewer could
  otherwise read it as a second gate.
- **Agreeing on the consent page is not the SMS opt-in either.** It is consent
  to take part in the pilot. The SMS opt-in is the checkbox. Keeping them
  separate is what fixed the first rejection.
- **The browser channel is load-bearing for the campaign.** It began as a way
  to keep the study running while approval was pending. Since rejection 3 it
  is also the fact that makes "consent is not a required condition of service"
  true for DASH. Removing it, or describing the study as text-message-only
  anywhere public, re-creates the rejection.
- **DASH's two channels are equals; the program is not browser-based.** The
  studies subdomain hosts any study, by whatever channel, and only DASH has a
  browser interview. DASH's own pages may and do present SMS and browser as
  two equal ways to take part. Program-level pages —
  the opt-in page, `sms-terms/`, `sms-privacy/` — and the campaign fields
  state the principle (messaging consent is never required to take part or be
  paid; every study offers a route without it) and cite DASH's browser
  interview only as the current instance. Wording them as if every study were
  browser-backed commits studies nobody has designed, which is the mirror of
  the mistake of wording them as if DASH were the only study.

## How to help me

Useful things to ask for: reviewing wording before it is sent to a carrier or
to IT; thinking through the Retell agent configuration; checking that a change
in one place does not contradict another page; drafting replies. The recurring
failure mode in this project has been **two sources saying different things** —
the site contradicting the policy pages, the policy pages contradicting the
campaign application — so when something changes, the question to ask is
always "what else says this, and does it still agree?"
