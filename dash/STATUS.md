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

The blocker for the last several weeks was the **A2P 10DLC campaign** — the
carrier registration every organization must pass before sending any SMS in
the US. It was rejected three times and **was approved on 7 September 2026**.
Both channels now work: the browser interview, which was never affected, and
the text-message path, verified end to end on the day approval landed.

## Key facts

| Thing | Value |
| --- | --- |
| Study SMS number (DID) | +1 (507) 431-7807 |
| Study site (participant flow) | https://dash.study.childmind.org |
| Prolific study URL | https://dash.study.childmind.org/start — confirm it is set to this in Prolific |
| Opt-in page (cited in the campaign) | https://matter.childmind.org/studies/dash/opt-in/ |
| A2P campaign / program name | Child Mind Institute — the filed Application Name, rebranded from "Child Mind Institute MATTER Lab" on 1 Sep 2026. The page, the consent record, the confirmation SMS and the campaign must all use this one name. |
| Retell chat agent (both channels) | `agent_52cce77d02d3721f680b1194f5` ("DASH-MH-P-GS TEXT"), conversation flow `conversation_flow_596a14d64b4e` |
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
  matter.childmind.org. Hosts the opt-in page and the two policy pages. It sits
  behind a Cloudflare bot challenge that used to return 403 to anything that
  was not a real browser; the four filed paths are now exempted, and the rest
  of the site still is not.

## How the flow works now

1. Prolific sends the participant to `/start` with their identifiers.
2. `/consent` shows the information sheet. Agreeing records consent to take
   part; it sends no messages.
3. `/begin` offers the interview. `SMS_ENABLED` decides: unset, it offers the
   browser only; set, it offers both, device-appropriate one first, with both
   always available. **It is set to 1 on the droplet**, so both are offered,
   which is now correct — the campaign is approved.
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

Two causes, **both since fixed**; the fourth submission was approved on 7
September 2026.

1. **The filed URLs returned 403 to the reviewer.** Checked 26 Aug 2026: the
   opt-in page, `/sms-terms/`, `/sms-privacy/` and `/text-study/` all answered
   403 to any non-browser client. TCR fetches them with a script, so it saw
   challenge pages instead of disclosures. The existing Cloudflare skip rule
   did not cover Super Bot Fight Mode and its expression covered `/studies/`
   only. Fixed by CMI IT; all four returned 200 to `curl` when re-checked on 7
   Sep 2026. This was invisible from a browser, which is why it survived two
   rounds of checking.
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

The campaign was approved at **program level**, as the Child Mind Institute's
participant messaging, rather than as one DASH application. The opt-in page and
both policy pages describe the program, not a single study; only the study
site's own pages name the DASH pilot. One consequence: the campaign covers
studies that do not exist yet, so nothing published under it should be worded
as if DASH were the only one.

## What is waiting on other people

| Waiting on | What | Why it matters |
| --- | --- | --- |
| Twilio, via Retell | Whether the confirmation SMS must precede the participant's first inbound message | If not, the opt-in form drops the phone number field and goes back to a checkbox alone, restoring the property that a number only ever reaches us because someone texted us. Retell is opening a support ticket rather than guessing. |
| — | Three questions about `create-sms-chat` | **Answered 25 Aug 2026.** `text` is ignored, the agent's begin message decides; the participant's reply lands in the chat that call opened; no timer starts at creation, but auto-close runs from the last message, which is the confirmation. All three match the patched flow. `text` is not even a documented field — the ones that exist are `from_number`, `to_number`, `override_agent_id`, `override_agent_version`, `metadata` and `retell_llm_dynamic_variables`. |
| — | Whether two chats can be open on one handset at once | **Yes, observed 7 Sep 2026.** A cold inbound text with no outbound chat open creates its own inbound chat; a later `create-sms-chat` to the same number opened a second, and both sat `ongoing`. Which one a subsequent reply reaches is undefined, and the code has to arrive in the chat the verification node is waiting in. Opt in first and text second, and do not mix the two orders in one test. |
| — | DNS record `*.study.childmind.org` → 167.71.248.46 | **Done, 25 Aug 2026.** Resolves at the authoritative nameservers and at 1.1.1.1, wildcard confirmed, grey cloud. The hostname switch is now ours to do: see `dash/optin/hostname-switch.md`. |
| CMI IT | Cloudflare bot-challenge exemption on matter.childmind.org | **This caused rejection 3. Resolved.** CMI IT added Super Bot Fight Mode to the skipped components and extended the rule's expression to all four paths. Re-verified 7 Sep 2026: `/studies/dash/opt-in/`, `/sms-terms/`, `/sms-privacy/` and `/text-study/` all return 200 to `curl`. A browser check cannot detect a regression here, so re-run the `curl` loop in `A2P_submission.md` rather than clicking the links. |
| TCR | Campaign approval | **Approved 7 September 2026**, on the fourth submission. |

## What is left to do

Owned by us, in order:

1. ~~**Chase CMI IT on the Cloudflare exemption.**~~ **Done.** All four filed
   URLs return 200 to `curl`, re-verified 7 Sep 2026.
2. ~~**Deploy the consent-wording changes and push `matter-website`.**~~
   **Done, 26 Aug 2026.** The droplet and this repository are both at the same
   commit, both hostnames serve the new wording, and `matter-website` is
   pushed to `gh-pages`. The CMS pages could not be verified from outside a
   browser until the Cloudflare exemption landed; they can be now.
3. ~~**Put the Retell API key on the droplet.**~~ **Done.** It is set as
   `RETELL_API_KEY`; `SMS_SEND_TOKEN` stays unset and falls back to it. Do not
   set both — one secret under two names is how one goes stale.
4. ~~**Set the outbound agent's begin message.**~~ **Done, differently than
   this item assumed.** There is no dashboard begin message to set: the flow's
   start node emits `{{opening}}`, and the flow carries
   `default_dynamic_variables = {"study_channel": "sms", "opening": …}` holding
   the registered confirmation followed by the instruction to text the code.
   SMS gets that by default; the browser overrides both variables with
   `WEB_OPENING` and `study_channel: "web"`, which is what the start node's
   first edge branches on. Changing the confirmation therefore means changing
   `CONFIRMATION_SMS` **and** the flow's default, or the two drift.
5. ~~**Resubmit the A2P campaign.**~~ **Approved 7 September 2026.**
6. **Check the Prolific completion paths.** Still open, and now the main thing
   between here and a live study. The three codes are set on the droplet and
   the application emits them correctly (see below); what is unverified is the
   action attached to each one in Prolific. Never a rejection.
7. **Dry-run the participant path** in a browser with a fresh Prolific ID.
8. ~~**On approval:** verify a confirmation text actually arrives.~~
   **Verified 7 Sep 2026** — see *How the text channel was verified* below.
9. ~~**Switch hostnames.**~~ **Done.** CMI IT renamed the wildcard to
   `*.study.childmind.org` (singular) on 1 Sep 2026; it was *swapped*, not
   added, so `*.studies` no longer resolves at all. All four places that name
   the host now agree on the singular form — `Caddyfile`, `OPTIN_API_URL` in
   `study_site.py`, and the flow's two function nodes — and
   `dash.study.childmind.org` serves over TLS. `hostname-switch.md` remains the
   runbook if it ever moves again.

**Note on `SMS_ENABLED`.** It is `1` on the droplet, which is now correct: the
campaign is approved and both channels are offered. Before approval this was a
liability; it no longer is.

## How the text channel was verified, 7 September 2026

Approval alone did not make texting work — the number had never been bound to
an SMS agent. `POST /create-sms-chat` failed with *"No outbound agent id set up
for phone number"*, and inbound texts reached a number whose only agent was a
**voice** agent, so nothing answered. Retell keeps SMS on separate fields from
voice: `inbound_sms_agents` and `outbound_sms_agents`, which take a **chat**
agent. Both are now bound to `agent_52cce77d02d3721f680b1194f5` at
`agent_version: 2`, the published version.

Both directions were then confirmed on the live number:

- **Inbound** — a text to +1 (507) 431-7807 opened a chat and the agent replied
  with the confirmation plus the instruction to text the five-character code.
- **Outbound** — `create-sms-chat` returned 200 and billed one `sms_message`,
  with the same opening.

Two symptoms worth recognizing if this ever regresses. A number with no SMS
agent bound is silent inbound and 400s outbound, which looks like a carrier
problem and is not one. And a failed confirmation is visible on the opt-in page
without any log access: the success wording is *"Check your phone for a
confirmation text, then text …"*, so a page that says only *"You are opted in.
Text … to begin."* means the send failed.

## The agent flow

The patched flow is live. The start node is the confirmation, the verification
path is reachable, HELP has a fixed answer and auto-close is 72 hours
(`end_chat_after_silence_ms: 259200000`). Chat agent version **2** is published
and is what the number is pinned to; version 3 is a draft that differs from it
in two interview nodes only (`q-dpscr011`,
`conversation-1782878930497-0`) — the whole code-verification path is identical
in both, so nothing about SMS depends on publishing v3.

## What the agent flow used to do

The exported Retell flow reaches 412 of its 423 nodes from the start node.
`Extract study code`, `Verify code` and `Code not accepted` are among the
eleven it never reaches: they form a closed loop nothing points into, so the
interview begins without a code and no conversation is ever bound to a
Prolific submission. Fixing this is independent of the campaign and had to
happen before any participant reached the agent. The patch has since been
applied and imported; all that is left is confirming the version is published.

## Traps — things that look fine and are not

- **A "sent" result still only means Retell accepted it.** Approval removed
  the carrier filter, but the API call and the delivery are separate facts,
  and only a handset proves the second one.
- **Retell's `create-sms-chat` opens a chat; the first message is written by
  the agent bound to the number, not by the text our code sends.** If that
  agent's opening is not the registered confirmation wording, participants
  receive something different from what the carrier approved.
- **Because it opens a chat, the participant's later message lands in a
  conversation that is already live.** The agent must not start interviewing
  before `/api/verify-code` succeeds, or someone who opted in from the public
  page gets interviewed with no code and no linkage.
- **Two chats can be open on one handset at once**, one inbound and one
  outbound, if someone texts the number before opting in. Which one their next
  message reaches is undefined, and the code has to arrive in the chat the
  verification node is waiting in. Close stale chats with
  `PATCH /end-chat/{chat_id}` before re-testing.
- **SMS agents are bound to the number on different fields from voice agents.**
  A number can look fully configured — `inbound_agents` and `outbound_agents`
  both populated — and still be silent on SMS, because those are the voice
  fields. SMS needs `inbound_sms_agents` and `outbound_sms_agents`, and needs a
  chat agent rather than a voice one.
- **The agent's silence timers may start at opt-in rather than at the
  participant's first message.** Someone who opts in on a laptop and texts
  the next morning could find the chat closed.
- **matter.childmind.org used to return 403 to curl.** The Cloudflare
  exemption now covers all four filed paths, but a browser check cannot detect
  a regression — only `curl` can.
- **The three Prolific completion codes are set in the application but
  unverified in Prolific.** The application emits `C1NLN7GA` on a clean
  completion, `C1I7LHFW` when two or more attention checks fail, and
  `CUS43GAW` when someone declines on the consent page; a participant who
  times out mid-interview deliberately gets **no code at all** and is sent to
  return the study. What is not verified is the action Prolific has attached to
  each code. Never attach a rejection action to any of the three —
  `C1I7LHFW` is hold-for-review, not reject.

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
  study subdomain hosts any study, by whatever channel, and only DASH has a
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
