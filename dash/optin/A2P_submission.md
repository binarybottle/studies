# A2P campaign resubmission — field text

Copy each block into the matching field. Nothing here is served to anyone;
this file is a worksheet.

The rejection came down to one sentence in the consent field saying the number
is shown after consent, which a review reads as "consent is required to
receive the service." Field 5 is the substantive change; the rest is cleanup.

---

## 1. Application Name

Child Mind Institute MATTER Lab

---

## 2. Use Case

Customer Care

---

## 3. Description for the use of sms

The Child Mind Institute MATTER Lab runs research studies in which an
automated interviewer conducts a standardized questionnaire by text message.
Messages consist of questionnaire items and replies to what the participant
sends. No marketing or promotional messages are ever sent from this number.
Participants opt in on our published opt-in page before any message is sent to
them. The current study is a pilot test of the messaging system, run in
preparation for a research study that has not yet begun and for which the
Child Mind Institute will apply for Institutional Review Board review. Each
participant is given a short written persona describing a fictional parent and
a fictional child, and answers a standardized mental health screening
questionnaire in character as that fictional parent. Participants are never
asked about their own child, their own family, or their own mental health.

---

## 4. Sample Messages

**Sample A — welcome / confirmation, sent the moment consent is recorded**

Child Mind Institute MATTER Lab: You are opted in to research study messages.
Msg & data rates may apply. Msg freq varies. Reply STOP to cancel, HELP for
help.

**Sample B — first message of a session**

Hello! I am an AI assistant from the Child Mind Institute, messaging you to
ask some questions about the child described in the persona you were given, as
part of the DASH Mental Health Screener. The first few questions ask about
{{child_name}}'s physical health. Msg & data rates may apply. Reply STOP to
cancel, HELP for help.

**On the placeholder.** `{{child_name}}` is left as written, on your
instruction. The reviewer's item 3 asked for it to be substituted, so expect
the question again; the answer is that it is a template variable filled per
participant, and Sample A — the message every opted-in person receives, and
the one the footer requirement is about — contains no placeholder.

---

## 5. How do end-users consent to receive messages?

End-users opt in to receive SMS from the Child Mind Institute MATTER Lab by
visiting https://matter.childmind.org/studies/dash/opt-in/ and checking an
optional, unchecked box that reads: "I agree to receive text messages from the
Child Mind Institute MATTER Lab at this number. Msg & data rates may apply.
Msg freq varies. Reply STOP to cancel, HELP for help." Our privacy policy
(https://matter.childmind.org/sms-privacy/) and terms
(https://matter.childmind.org/sms-terms/) are linked directly beside that
checkbox. Upon consent, the user receives a confirmation SMS: "Child Mind
Institute MATTER Lab: You are opted in to research study messages. Msg & data
rates may apply. Msg freq varies. Reply STOP to cancel, HELP for help."

The box is unchecked when the page loads and the submission is refused unless
it arrives checked. The page is publicly reachable with no login and no query
parameters, and displays the program number +1 (507) 431-7807 before any
interaction. Testers recruited through the Prolific research platform reach
the same page and check the same box; no other route to opting in exists. The
number entered is used to send the confirmation message and is then stored
only as an irreversible hash.

**On the confirmation message and approval order.** Carriers filter outbound
A2P messages until the campaign is approved, so the confirmation cannot
actually be delivered before TCR clears the campaign this field is part of.
That is expected: the field describes the flow that runs once approved, and
the flow is built and configured rather than promised. What must be true
before submitting is that the page is published, the send is configured, and
the agent's begin message matches the confirmation text quoted above.

## 6. Privacy Policy URL

https://matter.childmind.org/sms-privacy/

The reviewer's item 4 asked for an explicit SMS clause on
**https://childmind.org/privacy/**. Nothing there needs to change. The clause
already exists on `matter.childmind.org/sms-privacy/`, and now leads with the
phrasing a review looks for:

No mobile information will be shared with third parties or affiliates for
marketing or promotional purposes; text-messaging opt-in data and consent will
not be shared with any third parties.

What a campaign review checks is the privacy policy **linked at the point of
opt-in**. The reviewer's suggested checkbox wording linked the
organization-wide policy, which is a general document that does not mention
messaging; the checkbox now links the SMS notice and SMS terms, which govern
this program and carry the clause. That is the only reason item 4 came up, and
it is why the disclosure quoted in field 5 differs from the reviewer's draft in
its last two URLs.

If TCR insists on the organization-wide policy specifically, the sentence above
is ready to hand to whoever maintains childmind.org.

## 7. Terms and Conditions URL

https://matter.childmind.org/sms-terms/

---

# Where each page lives

| Page | Host |
| --- | --- |
| Opt-in page (cited in field 5) | `matter.childmind.org/studies/dash/opt-in/` |
| Pilot information page | `matter.childmind.org/text-study/`, also `/studies/dash/` |
| Opt-in form endpoint it posts to | `study.arnoklein.info/api/opt-in` |
| Participant consent and interview flow | `study.arnoklein.info` |
| SMS privacy notice (field 6) | `matter.childmind.org/sms-privacy/` |
| SMS terms (field 7) | `matter.childmind.org/sms-terms/` |

The opt-in page is CMS content on the organization's domain. Its form posts
to the study host, which is the part a reviewer can see if they inspect the
page: the endpoint is on `study.arnoklein.info` until a Child Mind Institute
hostname points at that server. The email in `email-cmi-subdomain.md` asks for
one.

# Before you submit

**1. Publish the opt-in page.** It is written and the site builds cleanly:
commit and push the `matter-website` repository, which serves it at
`https://matter.childmind.org/studies/dash/opt-in/`. The page is generated
from the study site's constants — regenerate with
`python dash/optin/build_optin_page.py ~/Software/matter-website/opt-in.html`
rather than editing it there, so the disclosure on the page and the disclosure
recorded with each consent cannot drift apart.

**2. Get the opt-in URL exempted from Cloudflare's bot challenge.**
matter.childmind.org sits behind a Cloudflare managed challenge that returns
403 to every request that is not a real browser — the site root included. A
reviewer or automated checker fetching the opt-in URL gets a challenge page
rather than the disclosures, which looks exactly like "the URL does not load":
the complaint that started this. Ask whoever administers the Cloudflare zone to
exempt `/studies/dash/*`, then confirm from outside a browser:

```bash
curl -s -o /dev/null -w '%{http_code}\n' \
  https://matter.childmind.org/studies/dash/opt-in/
```

Expect 200. A 403 means the reviewer will see one too.

**3. Configure the send, and fix the agent's begin message.** Retell confirmed
the endpoint: `POST https://api.retellai.com/create-sms-chat`, authenticated
with your dashboard API key as a bearer token. `SMS_SEND_URL` already defaults
to it; put the key in `SMS_SEND_TOKEN` in `dash/.env`.

The part that is not just configuration: `create-sms-chat` opens a chat, and
its first message is authored by **the outbound SMS agent bound to
+1 (507) 431-7807**, not necessarily by the `text` this application sends. Set
that agent's begin message in the Retell dashboard to the confirmation text
quoted in field 5, word for word. If it says anything else, the message
participants receive will not match what the campaign registered, which is its
own compliance problem.

Two consequences of it being a chat rather than a bare message, worth deciding
on deliberately:

- The conversation the participant later texts their code into is this one, so
  the agent must not begin interviewing before the code is verified.
- The agent's silence timers start at opt-in, not at the participant's first
  message. Someone who opts in and texts an hour later may find the chat
  already closed.

**4. Redeploy the study site:**

```bash
docker compose up -d --build dash
```

**5. Test what can be tested before approval** — open the published page,
enter your own mobile number, tick the box, and confirm the request is accepted
and recorded. The text itself will not arrive until the campaign is approved,
because the carrier filters it; check the Retell dashboard for the chat the
call created rather than waiting for a message on your phone. Test delivery
again the day approval lands, before any participant sees the page.

**6. Still open with Retell:** whether TCR requires the confirmation to precede
the participant's first inbound message at all. Retell is opening a Twilio
Support ticket rather than guessing. If the answer is that it does not, the
form can drop the phone number field and go back to a checkbox alone, which
restores the property that a number only ever reaches us because someone chose
to text us. Do not spend effort tuning the number-collecting flow until that
comes back.

**The website is already updated** in the `matter-website` repository and
needs only a commit and push. Three pages described the old consent model and
would have contradicted field 5:

- `sms-terms/` said "you opt in by sending a text message to that number
  yourself, and that message is the opt-in". Now describes the checkbox, the
  confirmation message, and links to the opt-in page.
- `sms-privacy/` said your number "reaches us as an unavoidable part of sending
  a text message". Now covers the opt-in page too, and records that the
  disclosure wording is stored alongside each consent.
- `text-study/`, the pilot information page also served at `/studies/dash/`,
  said taking part is "entirely participant-initiated". Now points at the
  opt-in page for opting in, and keeps the number public.

**Contact addresses differ by page, deliberately.** The policy pages —
`sms-terms/` and `sms-privacy/` — publish lindsay.alexander@childmind.org, who
handles legal questions about the messaging program. Every study-facing page —
the opt-in page, the pilot information page, and the study site — publishes
olivia.fitzpatrick@childmind.org, who manages this study and answers
participants. Do not unify them: a policy question and a "my code did not
arrive" question should not go to the same inbox. If a reviewer asks, that is
the answer.

**The participant flow is on the same host as the opt-in page.** A reviewer
who clicks past the front page reaches the consent sheet, which shows the same
number above its buttons and states that agreeing sends no messages. The two
cannot contradict each other: they are rendered from the same file.
