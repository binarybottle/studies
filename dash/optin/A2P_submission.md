# A2P campaign resubmission — field text

Copy each block into the matching field. Nothing here is served to anyone;
this file is a worksheet.

**Third rejection, 26 August 2026**, on two grounds:

> The campaign submission has been reviewed and it was rejected because of
> provided Opt-in information.; The campaign submission has been reviewed and
> rejected because consent cannot be a required condition for service or
> transaction completion.

Two causes, and only one of them is in this file:

1. **The filed URLs do not load for the reviewer.** All four
   matter.childmind.org URLs return 403 to any client that is not a real
   browser, the opt-in page in field 5 and the policy pages in fields 6 and 7
   included. TCR fetches them with a script. See *Before you submit*, step 2 —
   this is a hard blocker and resubmitting before it is fixed wastes another
   review cycle.
2. **The submission said text messaging was the only way to take part.**
   Field 5 said "no other route to opting in exists" and the study site said
   "there is no other way to join." Both meant *no other way a number reaches
   us*; a review reads them as *consent to SMS is required to receive the
   service*, which is not permitted. It is also no longer true: the same
   interview runs in a web browser, and a participant who never opts in is
   paid identically. Fields 3 and 5 now say so.

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
them. Text messaging is one of two ways to take part: the identical interview
is also offered in a web browser, so consenting to receive text messages is
never a condition of taking part in a study, of completing one, or of being
compensated for one. The current study is a pilot test of the messaging
system, run in preparation for a research study that has not yet begun and for
which the Child Mind Institute will apply for Institutional Review Board
review. Each
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
the same page and check the same box. The number entered is used to send the
confirmation message and is then stored only as an irreversible hash. This
page is the only route by which a phone number reaches us; we do not buy,
rent, or import phone number lists.

**Consent to receive text messages is not a required condition of service.**
It is not a condition of any purchase, of taking part in a study, of
completing one, or of being paid for one. Every study in this program is
offered two ways, and they are the same interview: by text message for
participants who opt in on the page above, or in a web browser for those who
prefer not to receive text messages. Participants choose, and are compensated
identically either way. A participant who never opts in completes the study
and is paid in full. The opt-in page, the study site's public information
page, and the SMS terms each state this in those terms.

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
| Opt-in form endpoint it posts to | `dash.studies.childmind.org/api/opt-in` |
| Participant consent and interview flow | `dash.studies.childmind.org`, also `study.arnoklein.info` |
| SMS privacy notice (field 6) | `matter.childmind.org/sms-privacy/` |
| SMS terms (field 7) | `matter.childmind.org/sms-terms/` |

The opt-in page is CMS content on the organization's domain. Its form posts
to the study host, which is the part a reviewer can see if they inspect the
page. That endpoint is now `dash.studies.childmind.org` — a Child Mind
Institute hostname, resolving to the study server and serving over TLS, so a
reviewer inspecting the form no longer sees a personal domain. `Caddyfile`
serves both names; the participant flow moves to the same host per
`hostname-switch.md`.

# Before you submit

**1. Publish the opt-in page.** It is written and the site builds cleanly:
commit and push the `matter-website` repository, which serves it at
`https://matter.childmind.org/studies/dash/opt-in/`. The page is generated
from the study site's constants — regenerate with
`python dash/optin/build_optin_page.py ~/Software/matter-website/opt-in.html`
rather than editing it there, so the disclosure on the page and the disclosure
recorded with each consent cannot drift apart.

**2. Get every filed URL exempted from Cloudflare's bot challenge.** This is
the blocker. As of 26 August 2026 all four still return 403 to any client that
is not a real browser — the opt-in page in field 5 and both policy pages in
fields 6 and 7. A reviewer or automated checker gets a challenge page rather
than the disclosures, which looks exactly like "the opt-in information is not
there."

The previous request was made and did not work, for two specific reasons worth
repeating to whoever administers the zone:

- The existing skip rule skips **managed rules and rate limiting**, not
  **Super Bot Fight Mode**, which is a separate checkbox and is what is
  actually firing on "definitely automated traffic".
- Its expression covers `/studies/` only. The campaign also files
  `/sms-terms/` and `/sms-privacy/`.

The exemption must cover `/studies/*`, `/sms-terms/*`, `/sms-privacy/*` and
`/text-study/*`. Confirm from outside a browser before submitting — all four
must return 200:

```bash
for u in https://matter.childmind.org/studies/dash/opt-in/ \
         https://matter.childmind.org/sms-terms/ \
         https://matter.childmind.org/sms-privacy/ \
         https://matter.childmind.org/text-study/; do
  printf '%s  %s\n' "$(curl -s -o /dev/null -w '%{http_code}' "$u")" "$u"
done
```

A 403 means the reviewer will see one too. Do not resubmit until this passes:
it is what caused rejection 3, and a browser check cannot detect it.

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

**6. Keep the browser channel working — it is now load-bearing for the
campaign.** Fields 3 and 5 tell TCR that a participant can complete a study
without ever opting in to text messages. That is true only while `/chat` runs,
so it is a compliance claim now and not just a convenience. Walk it once
before submitting, with `SMS_ENABLED` unset:

```
https://study.arnoklein.info/start?PROLIFIC_PID=test123456789012345678
```

Information sheet → consent → the browser interview, with no phone number
asked for anywhere. If a reviewer follows the study site from the opt-in page,
this is the path that substantiates field 5.

**7. Still open with Retell:** whether TCR requires the confirmation to precede
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

**Re-check those three pages against the new field 5 before pushing.** They
were rewritten for the checkbox model, but not for the browser alternative,
and field 5 now asserts that the opt-in page, the study site and the SMS terms
all state that consent is not a condition of taking part. `sms-terms/` is the
one that has to carry it; the regenerated opt-in page and the study site
already do. A reviewer comparing the field against the pages is the failure
mode this project keeps hitting.

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
