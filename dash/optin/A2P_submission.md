# A2P campaign resubmission — field text

Copy each block into the matching field. Nothing here is served to anyone;
this file is a worksheet.

---

## 1. Application Name

Child Mind Institute MATTER Lab

---

## 2. Use Case

Customer Care

---

## 3. Description for the use of sms

The Child Mind Institute MATTER Lab runs research studies in which an automated interviewer conducts a standardized questionnaire by text message. Messages consist of questionnaire items and replies to what the participant sends. No marketing or promotional messages are ever sent from this number. Participants opt in on our published opt-in page before any message is sent to them. Consenting to receive text messages is never a condition of taking part in a study, of completing one, or of being compensated for one: no study in this program requires messaging in order to participate, and each provides a way to take part without it. The DASH pilot, the study this campaign is being registered for, is offered two ways — by text message, or as the identical interview in a web browser — and participants choose. The current study is a pilot test of the messaging system, run in preparation for a research study that has not yet begun and for which the Child Mind Institute will apply for Institutional Review Board review. Each participant is given a short written persona describing a fictional parent and a fictional child, and answers a standardized mental health screening questionnaire in character as that fictional parent. Participants are never asked about their own child, their own family, or their own mental health.

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
Alex's physical health. Msg & data rates may apply. Reply STOP to
cancel, HELP for help.

---

## 5. How do end-users consent to receive messages?

End-users opt in to receive SMS from the Child Mind Institute MATTER Lab by visiting https://matter.childmind.org/studies/dash/opt-in/ and checking an optional, unchecked box that reads: "I agree to receive text messages from the Child Mind Institute MATTER Lab at this number. Msg & data rates may apply. Msg freq varies. Reply STOP to cancel, HELP for help." Our privacy policy (https://matter.childmind.org/sms-privacy/) and terms (https://matter.childmind.org/sms-terms/) are linked directly beside that checkbox. Upon consent, the user receives a confirmation SMS: "Child Mind Institute MATTER Lab: You are opted in to research study messages. Msg & data rates may apply. Msg freq varies. Reply STOP to cancel, HELP for help."

The box is unchecked when the page loads and the submission is refused unless it arrives checked. The page is publicly reachable with no login and no query parameters, and displays the program number +1 (507) 431-7807 before any interaction. Testers recruited through the Prolific research platform reach the same page and check the same box. The number entered is used to send the confirmation message and is then stored only as an irreversible hash. This page is the only route by which a phone number reaches us; we do not buy, rent, or import phone number lists.

## 6. Privacy Policy URL

https://matter.childmind.org/sms-privacy/

The reviewer's item 4 asked for an explicit SMS clause on https://childmind.org/privacy/. Nothing there needs to change. The clause already exists on `matter.childmind.org/sms-privacy/`, and now leads with the phrasing a review looks for:

No mobile information will be shared with third parties or affiliates for marketing or promotional purposes; text-messaging opt-in data and consent will not be shared with any third parties.

What a campaign review checks is the privacy policy linked at the point of opt-in. The reviewer's suggested checkbox wording linked the organization-wide policy, which is a general document that does not mention messaging; the checkbox now links the SMS notice and SMS terms, which govern this program and carry the clause. That is the only reason item 4 came up, and it is why the disclosure quoted in field 5 differs from the reviewer's draft in its last two URLs.

If TCR insists on the organization-wide policy specifically, the sentence above is ready to hand to whoever maintains childmind.org.

## 7. Terms and Conditions URL

https://matter.childmind.org/sms-terms/

---

# Where each page lives

| Page | Host |
| --- | --- |
| Opt-in page (cited in field 5) | `matter.childmind.org/studies/dash/opt-in/` |
| Pilot information page | `matter.childmind.org/text-study/`, also `/studies/dash/` |
| Opt-in form endpoint it posts to | `dash.study.childmind.org/api/opt-in` |
| Participant consent and interview flow | `dash.study.childmind.org` |
| SMS privacy notice (field 6) | `matter.childmind.org/sms-privacy/` |
| SMS terms (field 7) | `matter.childmind.org/sms-terms/` |

The opt-in page is CMS content on the organization's domain. Its form posts
to the study host, which is the part a reviewer can see if they inspect the
page. That endpoint is now `dash.study.childmind.org` — a Child Mind
Institute hostname, resolving to the study server and serving over TLS, so a
reviewer inspecting the form no longer sees a personal domain. `Caddyfile`
serves both names; the participant flow moves to the same host per
`hostname-switch.md`.

# Before you submit

**1. Publish the opt-in page.** ~~Pending.~~ **Done, 26 Aug 2026** — pushed to
`gh-pages`. Re-do this whenever the disclosure changes: the page is generated,
so regenerate rather than editing the website copy. It is served at
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

**3. Configure the send, and fix the agent's begin message.** The send is
configured — `RETELL_API_KEY` is set on the droplet and `SMS_SEND_TOKEN` falls
back to it. The begin message is still outstanding. Retell confirmed
the endpoint: `POST https://api.retellai.com/create-sms-chat`, authenticated
with your dashboard API key as a bearer token. `SMS_SEND_URL` already defaults
to it; put the key in `RETELL_API_KEY` in `dash/.env` and leave
`SMS_SEND_TOKEN` unset — it falls back to `RETELL_API_KEY`, and one secret
under two names is how one of them goes stale. **Done:** the key is set on the
droplet and the container reports the send as configured.

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

**6. Keep the browser channel working** Fields 3 and 5 tell TCR that a participant can complete a study without ever opting in to text messages. That is true only while `/chat` runs, so it is a compliance claim now and not just a convenience. Walk it once before submitting, with `SMS_ENABLED` unset:

```
https://dash.study.childmind.org/start?PROLIFIC_PID=test123456789012345678
```

**7. Still open with Retell:** whether TCR requires the confirmation to precede
the participant's first inbound message at all. Retell is opening a Twilio
Support ticket rather than guessing. If the answer is that it does not, the
form can drop the phone number field and go back to a checkbox alone, which
restores the property that a number only ever reaches us because someone chose
to text us. Do not spend effort tuning the number-collecting flow until that
comes back.
