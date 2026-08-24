# A2P resubmission — DASH text-message interviewer pilot

The rejection came down to one thing: the application said the number is
shown *after* consent, which a campaign review reads as "consent is required
to receive the service." Everything below removes that reading.

## 1. Publish the opt-in page

Publish `dash-optin.html` at:

```
https://matter.childmind.org/studies/dash/
```

It must load with **no query string, no login, and no redirect**. Confirm
before resubmitting:

```bash
curl -s -o /dev/null -w '%{http_code}\n' https://matter.childmind.org/studies/dash/
```

The page must show, without the reviewer clicking anything: the program name,
the DID `+1 (507) 431-7807`, the opt-in disclosure with STOP/HELP and "Message
and data rates may apply", and links to the two existing policy pages. The
number is deliberately the first block on the page.

Leave `https://matter.childmind.org/sms-privacy/` and
`https://matter.childmind.org/sms-terms/` exactly as they are — the reviewer
said both already pass.

## 2. Replace the consent field

**How do end-users consent to receive messages?**

> Opt-in page: https://matter.childmind.org/studies/dash/
>
> End users opt in by texting our number to begin. The program number,
> +1 (507) 431-7807, is published on the public page above, together with the
> full opt-in disclosure (message frequency, "Message and data rates may
> apply", "Reply STOP to cancel", "Reply HELP for help") and links to our SMS
> terms and SMS privacy notice. That page requires no login and no query
> parameters.
>
> Every conversation is started by the end user. The first message is always
> theirs, and we never send a message to a phone number that has not messaged
> us first. There is no list to join, and no phone number is collected on the
> page or anywhere else — we only ever learn a number because someone chose to
> text us.
>
> Testers are recruited through the Prolific research platform and are shown a
> study information page that repeats the same number and the same disclosure
> before they decide whether to take part. Agreeing on that page records the
> tester's informed consent to take part in the pilot; it does not reveal the
> number, and it does not cause any message to be sent. A tester who declines
> is returned to Prolific and is never messaged. Testers are also given a five-character code to send as their
> first message, so a conversation can be matched to a Prolific submission for
> payment. That code identifies a session; it is not what permits us to
> message anyone.
>
> End users may reply STOP at any time to exit, or HELP for help.
> olivia.fitzpatrick@childmind.org is published for questions, troubleshooting, and
> payment problems.

## 3. Optional: tighten the use-case description

The current text switches between "they" and "you" and calls the program both
a pilot and not a research study in consecutive sentences. A reviewer reading
quickly can take that as inconsistency. Suggested replacement:

> The Child Mind Institute is testing an automated text-message interviewer.
> This is a pilot test of the software rather than a research study: its
> purpose is to confirm that the system works reliably before any research
> data is collected, and the responses are used only to check that the
> technology functions correctly. Testers are recruited through the Prolific
> research platform. Each tester is given a short written persona describing a
> fictional parent and a fictional child, and answers a standardized mental
> health screening questionnaire in character as that fictional parent.
> Testers are never asked about their own child, their own family, or their
> own mental health. Every conversation is started by the tester texting our
> published number.

Leave Application Name, Use Case, and Sample Message as they are.

## 4. One deliberate inconsistency to know about

Every page named here publishes **olivia.fitzpatrick@childmind.org** as the
contact. The two pages the reviewer already passed —
`matter.childmind.org/sms-terms/` and `/sms-privacy/` — still publish
lindsay.alexander@childmind.org, and are being left untouched on purpose
rather than resubmitting approved content.

So a reviewer who reads the opt-in page and then the terms page sees two
different addresses for HELP. That is not a compliance failure — both are
monitored childmind.org addresses and the STOP/HELP keywords themselves are
handled by the carrier, not by email — but if it draws a question, the fix is
to add olivia.fitzpatrick@childmind.org alongside the existing address on
those two pages rather than to replace it.

## 5. The study site was changed too

A reviewer who follows a link to `study.arnoklein.info` now finds the same
posture there, so the two sites cannot contradict each other:

- `/` and `/consent` both load with no query string and show the number.
- The consent page shows the number above the decision buttons, and says
  agreeing sends no messages.
- Declining returns the tester to Prolific with the screen-out completion
  code, having sent nothing.

Redeploy with `docker compose up -d --build dash` before resubmitting.
