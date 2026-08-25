# Reply to Retell — three questions about create-sms-chat

**Subject:** Re: DASH pilot — create-sms-chat behavior before we go live

Hi,

Thank you, this is exactly what we needed. The endpoint is wired up and
tested against a mock, and it sends what you specified:

    POST https://api.retellai.com/create-sms-chat
    Authorization: Bearer <our dashboard key>
    {"from_number": "+15074317807", "to_number": "+1XXXXXXXXXX", "text": "..."}

Three questions before we rely on it, all following from your note that the
first message is agent-authored and that this opens a chat rather than
sending a single message.

**1. If we set the agent's begin message to our confirmation text, is the
`text` field then ignored?**

We would rather not have two places that decide what the first message says.
Our plan is to set the outbound agent's begin message to the exact wording
registered with the campaign:

> Child Mind Institute: You are opted in for the DASH pilot. Msg & data rates
> may apply. Msg freq varies. Reply STOP to cancel, HELP for help.

If we also pass `text`, which one does the participant receive? We want the
one the carrier approved, every time.

**2. Will the participant's later inbound message land in the chat that
create-sms-chat opened, and can we stop the agent interviewing until we say
so?**

Our flow is: participant opts in on a web page, gets the confirmation, then
texts us a five-character code. Our `/api/verify-code` function node checks
that code and is what binds the conversation to their study record.

If the chat is already open when they text, the agent could start the
interview on their first inbound message, before the code is verified. That
would be bad in two ways: someone who opts in from the public page and never
had a code would get interviewed anyway, and we would lose the linkage
between conversation and participant.

What is the right way to make the agent send the confirmation, then wait, and
only proceed once `verify-code` returns valid? Is that a prompt instruction, a
node in the flow, or something else?

**3. When do the chat's silence and timeout timers start — at
create-sms-chat, or at the participant's first message?**

Participants may opt in on a laptop and text from their phone some time later.
If the twenty-four hour window starts when we open the chat rather than when
they first reply, someone who opts in and comes back the next morning may find
the conversation already closed. What is the actual timeout, does it start at
chat creation, and can we change it?

**On your point 2**, thank you for opening the Twilio ticket rather than
guessing. One thing worth putting in front of them, if it helps frame it: our
participants take part from their own phones, answering a mental health
screening questionnaire in character as a fictional parent. The design
deliberately never collected a phone number — a number reached us only because
someone chose to text us, and it was hashed on arrival and never stored in
plaintext. We have built the number-collecting version and will ship it if TCR
requires it, but if an unchecked checkbox with the disclosures shown at the
point of opt-in is sufficient, with the confirmation wording carried by the
agent's first reply, we would prefer that and can revert the form in an hour.

Thanks again,

Arno Klein
Child Mind Institute
arno.klein@childmind.org
