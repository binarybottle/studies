# Email to Retell — outbound send endpoint, and one open question

**Subject:** DASH pilot — outbound send endpoint for the opt-in confirmation, and a question on the consent model

Hi,

Thank you for the detailed review notes — they were clear and we have made all
five changes in one pass. Two things I need from you to finish, one concrete
and one a judgement call I would rather ask about than guess at.

**1. Which endpoint should we use to send the confirmation SMS?**

We have built the opt-in flow you described: a public page on our own domain
with an unchecked disclosure checkbox, which on submission records the consent
and sends the confirmation message. The one piece we cannot supply ourselves is
the outbound send. Our study number, +1 (507) 431-7807, is provisioned through
Retell, and until now every message has been a reply within an inbound
conversation, so we have never sent to a number that had not messaged us first.

Could you tell us which API to call to send a single SMS from that number to a
given number, what authentication it expects, and whether sending outbound to a
number with no existing chat is supported on our account? Our code posts JSON
of the form `{"from_number": ..., "to_number": ..., "text": ...}` to a
configurable URL with a bearer token, so if your endpoint differs we will adapt
to whatever shape you specify.

**2. Does TCR need the confirmation before the participant texts us, or is the
first reply enough?**

Our participants are recruited on Prolific and take part from their own phones,
answering a standardized mental health screening questionnaire in character as
a fictional parent. The design deliberately never collected a phone number: a
number reached us only because the participant chose to text us, and it was
hashed on arrival and never stored in plaintext. That property is part of what
we tell participants, and it is a meaningful protection in a study that touches
mental health topics.

Collecting the number on a web form to send a confirmation text changes that.
It is a real change rather than a cosmetic one, so before we ship it: is an
explicit unchecked checkbox with the disclosures shown at the point of opt-in,
where the confirmation message is the agent's first reply once the participant
texts in and carries the full footer, something TCR would accept? Or does TCR
specifically require a confirmation sent before any inbound message, which
means we must collect the number?

We have built the number-collecting version so we are not blocked either way,
and will ship whichever you tell us TCR will accept. If it is the first, we
would prefer it, and would revert the form to a checkbox only.

**For reference, what is now in place:**

- Opt-in page on a Child Mind Institute domain, publicly reachable with no
  login and no query parameters, showing +1 (507) 431-7807 before any
  interaction, with an unchecked checkbox carrying your suggested disclosure
  wording verbatim.
- Each consent stored with the exact disclosure text agreed to, so an audit
  shows what that person saw rather than what the page says today.
- Sample A rewritten as a welcome/confirmation message with the full footer,
  and the `{{child_name}}` token replaced with a rendered name in both samples.
- The SMS clause has been sent to the team that maintains childmind.org/privacy
  for addition to the organization-wide policy.

Thanks again,

Arno Klein
Child Mind Institute
arno.klein@childmind.org
