# A2P campaign resubmission — field text

Copy each block into the matching field. Nothing here is served to anyone;
this file is a worksheet.

The rejection came down to one sentence in the consent field saying the number
is shown after consent, which a review reads as "consent is required to
receive the service." Field 5 is the substantive change; the rest is cleanup.

---

## 1. Application Name

Child Mind Institute DASH text-message interviewer pilot

---

## 2. Use Case

Customer Care

---

## 3. Description for the use of sms

The Child Mind Institute is testing an automated text-message interviewer.
This is a pilot test of the software rather than a research study: its purpose
is to confirm that the system works reliably before any research data is
collected, and the responses are used only to check that the technology
functions correctly. Testers are recruited through the Prolific research
platform. Each tester is given a short written persona describing a fictional
parent and a fictional child, and answers a standardized mental health
screening questionnaire in character as that fictional parent. Testers are
never asked about their own child, their own family, or their own mental
health. Every conversation is started by the tester texting our published
number.

*(Changed from the original, which alternated between "they" and "you" and
called the program a pilot and "not a research study" in consecutive
sentences. A reviewer skimming can read that as inconsistency.)*

---

## 4. Sample Messages

**Sample A — welcome / confirmation, sent the moment consent is recorded**

Child Mind Institute: You are opted in for the DASH pilot. Msg & data rates
may apply. Msg freq varies. Reply STOP to cancel, HELP for help.

**Sample B — first interview message**

Hello! I am an AI assistant from the Child Mind Institute, messaging you to
ask some questions about the child described in the persona you were given, as
part of the DASH Mental Health Screener. The first few questions ask about
Alex's physical health. Msg & data rates may apply. Reply STOP to cancel, HELP
for help.

**On the placeholder.** You asked me not to substitute `{{child_name}}`, and
the reviewer's item 3 requires it. Both hold: the application shows a rendered
example, because an unsubstituted token in a submitted sample is what the
reviewer flagged, while the agent's own prompt template keeps `{{child_name}}`
and fills it per participant. Nothing in the agent changes.

## 5. How do end-users consent to receive messages?

End-users opt in to receive SMS from Child Mind Institute by visiting
https://matter.childmind.org/studies/dash/opt-in/ and checking an optional,
unchecked box that reads: "I agree to receive SMS from Child Mind Institute
for the DASH text-message interview pilot. Message and data rates may apply.
Message frequency varies (approximately 100-200 messages per session). Reply
STOP to cancel or HELP for help. Privacy:
https://matter.childmind.org/sms-privacy/ Terms:
https://matter.childmind.org/sms-terms/". Upon consent, the user receives a
confirmation SMS: "Child Mind Institute: You are opted in for the DASH pilot.
Msg & data rates may apply. Msg freq varies. Reply STOP to cancel, HELP for
help."

The box is unchecked when the page loads and the submission is refused unless
it arrives checked. The page is publicly reachable with no login and no query
parameters, and displays the program number +1 (507) 431-7807 before any
interaction. Testers recruited through the Prolific research platform reach
the same page and check the same box; no other route to opting in exists. The
number entered is used to send the confirmation message and is then stored
only as an irreversible hash.

**Do not submit until both are true:** the page is published at that URL, and
`SMS_SEND_URL` is configured so the confirmation message actually sends. Until
the second is set the endpoint records each consent and reports the
confirmation as unconfigured, which is the honest behavior but not what this
field describes.

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

**3. Get the outbound send endpoint from Retell** and set `SMS_SEND_URL` and
`SMS_SEND_TOKEN` in `dash/.env`. Nothing else about the confirmation message
needs building; the endpoint is written and tested against both a missing
provider and an unreachable one.

**4. Redeploy the study site:**

```bash
docker compose up -d --build dash
```

**5. Test the whole path yourself** — open the published page, enter your own
mobile number, tick the box, and confirm the text arrives.

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
