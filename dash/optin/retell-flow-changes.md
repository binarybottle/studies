# Retell flow changes — DASH-MH-P-GS TEXT

Written against the exported flow `DASH-MH-P-GS TEXT (1).json`, 423 nodes,
`start_node_id: greet-hello`, `start_speaker: agent`. Every claim below was
checked by walking the exported graph, not by reading the canvas.

## The one that matters

**Code verification never runs. Nothing links a conversation to a Prolific
submission.**

`Extract study code`, `Verify code`, and `Code not accepted` form a closed
loop that nothing outside it points into. Walking the graph from
`greet-hello` reaches 412 of 423 nodes; those three are among the eleven it
never reaches. The live path is:

    Greeting -> Proceed? -> Instructions -> Ask Name -> interview

The interview begins with no code, no `verify_code` call, and therefore no
row bound in `participants.chat_id`. Every transcript collected this way is
permanently unattributable, which is the one failure the whole linkage design
exists to prevent. Fix this before any participant reaches the agent, with or
without the campaign.

## Corrections to the notes you were given

Two instructions in them do not match the export:

- *"Greeting: turn off Skip Response."* The Greeting node has no Skip
  Response edge. It already has the right transition, `When the participant
  sends any message`, and it already sends `static_text`.
- *"With Skip Response on, the flow currently runs straight into code
  extraction with no participant message."* It does not. Greeting goes to
  `Proceed?`. Code extraction is unreachable, which is a different and worse
  problem.

Everything else in those notes checks out and is folded in below.

## How to apply it

All seven changes are applied by `patch_retell_flow.py` in this directory:

```bash
python dash/optin/patch_retell_flow.py \
    ~/Downloads/"DASH-MH-P-GS TEXT (1).json" \
    ~/Downloads/"DASH-MH-P-GS TEXT (patched).json"
```

`DASH-MH-P-GS TEXT (patched).json` is written and checked: the start node is
the confirmation, the verification path is reachable, and the confirmation
opens with `CONFIRMATION_SMS` from `study_site.py` byte for byte. Exactly one
detached node is attached — Start, and with it the three code-verification
nodes it leads into. Nothing is deleted, and every other detached node in the
export stays detached. **Import it
into Retell as a new version and diff it in the canvas before publishing** —
the script has been run against the export, not against Retell's importer,
and how that importer treats an export with an empty `agent_id` is not
something this repository can verify.

Each edit asserts what it expects to find first, so if the live flow has
moved on since the export, re-export and re-run: it will fail loudly rather
than quietly producing something different.

The steps below describe what the script does, in the order it does it, so
the diff can be read against them — or clicked by hand if you would rather
not import.

## What to change, in order

### 1. Start node — the confirmation message

A node named **Start** already exists carrying the confirmation text, but it
is not wired in and would not send the text verbatim. Three things to fix:

- Its instruction type is **prompt**, which lets the model rewrite it. Change
  it to **static text**. The first sentence is registered with the carrier
  and has to go out exactly as submitted; the instruction after it saves a
  round trip in which the participant replies to the confirmation with "hi"
  and has to be asked again:

      Child Mind Institute MATTER Lab: You are opted in to research study messages. Msg & data rates may apply. Msg freq varies. Reply STOP to cancel, HELP for help. To continue, text the five-character code shown on the study page.

  That is 226 GSM-7 units, so two segments rather than one. The registered
  sentence stays a verbatim prefix, which is what a reviewer comparing the
  live message against the sample on file needs to see.

- Its only edge has no destination. Point it at **Extract study code**, with
  the condition `When the participant sends any message`.
- Make it the flow's start node. `start_node_id` is still `greet-hello`.

This is the message `create-sms-chat` sends when someone opts in on the web
page.

### 2. Extract study code — send a first-timer somewhere useful

Its Else edge points at `Verify code`, the same place as the success edge, so
a participant who writes "hi" instead of a code has the endpoint called with
nothing. Point **Else** at a new node instead.

### 3. New node: Ask code

Static text:

    To begin, please text the five-character code shown on the study page. If you no longer have it, reopen the study link on Prolific to see it again.

Transition `When the participant sends a message` back to **Extract study
code**. The recovery instruction lives here rather than in the confirmation
because this is where someone without a code actually lands, and because the
opt-in page is public: a member of the public who opted in never had a
Prolific link to reopen.

Keep this separate from `Code not accepted`: that one is for a code the
server rejected.

### 4. Verify code — make it fail closed

Today the edge labelled `{{code_valid}} == true` actually tests
`{{code_valid}} == "false"` and goes to `Code not accepted`, while **Else**
goes to `Proceed?`. It behaves correctly for a valid or invalid code and
wrongly for everything else: a timeout, a 422, or an unset variable falls to
Else and starts the interview unlinked. Rewire:

- `{{code_valid}} == true` -> **Interview greeting** (step 5)
- **Else** -> **Code not accepted**

### 5. Repurpose Greeting as the interview greeting

Keep the node, change its text and where it sits. Static text:

    Hello! I am an AI assistant from the Child Mind Institute MATTER Lab, messaging you to ask some questions about the child described in the persona you were given, as part of the DASH Mental Health Screener. Reply STOP at any time to end.

Turn **Skip Response on** so it flows into `Proceed?` without waiting for
another message; the participant has just texted their code. Its existing
edge to `Proceed?` stays.

### 6. Code not accepted — do not lead with an unset variable

Its text opens with `{{code_message}}`, which is empty when the endpoint
never answered. Reorder so it reads sensibly either way:

    That code was not accepted. {{code_message}} Please text the five-character code shown on the study page. If you no longer have it, reopen the study link on Prolific to see it again.

### 7. A fixed answer for HELP

Typing HELP in the simulator produced this:

    Child Mind Institute MATTER Lab: For help, email support@childmind.org. To continue, please text the five-character code shown on the study page.

That address does not exist. Nothing in the flow, the site, the policies or
the campaign mentions it: the model wrote it, because the global prompt says
nothing about HELP and nothing about who to contact. Two problems, and the
invented address is the smaller one — an improvised answer is different every
time, and HELP is a keyword a carrier tests.

The script appends a rule to the global prompt, matching the two verbatim
rules already there:

    Child Mind Institute MATTER Lab: DASH research study messages. Help: olivia.fitzpatrick@childmind.org. Msg & data rates may apply. Reply STOP to cancel.

152 GSM-7 units, one segment, and it carries the brand, a real contact, the
rates disclosure and the opt-out. The address comes from `CONTACT_EMAIL` in
`study_site.py`, so it cannot drift from the one the pages publish.

**Worth asking Retell:** whether the carrier answers HELP and STOP before the
agent ever sees them. If it does, that response is configured on their side
and this rule never fires — and the wording a carrier tests is theirs, not
ours. If it does not, the agent is the only thing answering a keyword the
carrier requires an answer to. Either way the rule is right; which one is
live is a question for the open thread.

### 8. Silence timeout

`end_chat_after_silence_ms` is 86400000, twenty-four hours, and it now starts
at the confirmation message rather than at the participant's first text.
Someone who opts in on a laptop at night and texts the next evening loses the
chat. Raise it to 48 or 72 hours if the dashboard allows.

### The resulting path

    Start (confirmation)
      -> Extract study code
           code present -> Verify code
                             valid -> Interview greeting -> Proceed? -> interview
                             else  -> Code not accepted -> Extract study code
           no code     -> Ask code -> Extract study code

## Check before you trust it

**Encoding: fixed, nothing to check.** Both tools are configured
`parameter_type: form` while the endpoints parsed only JSON, so a form body
would have answered 422, left `code_valid` unset, and — under the old wiring
— started the interview anyway. The endpoints now accept form and JSON
either way, flat or nested under `args`, including a `call` object arriving
as a JSON string. Whatever the dashboard is set to, the call lands.

**Retell confirmed all three open questions on 25 August 2026**, and the
answers match what this file already prescribes. `text` in the
`create-sms-chat` payload is ignored outright — the first outbound message is
always the bound agent's begin message, which for a conversation flow is its
start node, so step 1 is not merely advisable but the only thing that decides
what participants receive. The participant's reply lands in the chat that call
opened rather than a new one, which is what makes step 4's gate reachable at
all. And no timer starts at chat creation, but the auto-close clock runs from
the last message either way — the confirmation — resetting on every inbound,
so step 8's 72 hours is what covers someone who opts in at night and texts
back in the morning. Retell recommended the conversation-flow gate over a
prompt rule for exactly the reason step 4 gives: conditional edges are
deterministic, a prompt is something the model has to remember.

**`{{code_valid}} == true` is the one thing to watch.** The endpoint answers
with a JSON boolean and Retell stores response variables as text; which
spelling arrives is not documented. The success edge therefore matches
`true`, `True`, or `1`. If a valid code still routes to `Code not accepted`
in the simulator, the spelling is something else again — read it off the
variables panel and add it. It fails closed, so the symptom is a rejected
good code, never an unlinked interview.

Argument names and URLs are correct: `participant_code` for `verify_code`,
`ac1`/`ac2`/`ac3` for `complete_study`, both pointing at the study host. Both
tools send no headers, so the endpoints accept unauthenticated POSTs from
anyone who knows the URL. Not a blocker, but worth a shared secret before the
study opens.

## Simulator tests after the rewiring

1. **Opt-in path.** Create the chat by API, confirm the confirmation text
   arrives verbatim, wait, send a valid code, confirm `verify_code` is called,
   the interview greeting follows, and `participants.chat_id` is now set.
2. **Wrong code.** Confirm it routes to `Code not accepted` and loops back
   rather than starting the interview.
3. **No code.** Send "hello" first; confirm `Ask code` appears rather than a
   pointless endpoint call.
4. **Endpoint down.** Stop the container and send a code; confirm the chat
   does not proceed into the interview.
5. **Inbound first.** Someone texts the number with no chat open and no
   opt-in on file. This is the case on the open Retell ticket; the flow should
   still demand a code before interviewing.

## Unrelated breakage found in the same pass

None of this blocks the campaign; all of it affects data.

The script changes none of it. Attaching a detached node changes what
participants are asked; leaving it detached changes nothing. Each of these is
a decision about the study rather than a repair, so each is listed and left
alone.

- **Q181 fb05, "How trustworthy did you feel the AI agent was?", is
  unreachable.** The feedback chain runs fb04 -> fb06, and the extract node
  after fb05 has an edge with no destination, so the question would dead-end
  even if reached. Wiring it in means participants answer one more question;
  leaving it means that item is empty in the data. Both are defensible and
  neither is mine to pick.
- **Q102 dpscr097 ("What is it?") is unreachable and dead-ends.** It reads
  like a follow-up to Q101, but where it belongs is a research call.
- **Preamble: Service Use is unreachable** and its skip edge has no
  destination. Its questions are asked; only the preamble is orphaned.
- **Q177 fb01** has a Skip/Next Question edge with no destination. Whether
  skipping a feedback item should be allowed at all is your call.
- Two empty **Code** nodes and one empty **Subagent** node, unreachable, each
  with a dangling edge. Harmless where they are; delete them in the canvas if
  you want the tidier picture.

## For the campaign application, if TCR comes back

Sample Message 1 already matches the confirmation text exactly. Sample
Message 2 in the submission is the physical-health preamble, which contains
`{{child_name}}`; the reviewer flagged unsubstituted tokens once already. The
interview greeting from step 5 is the better sample: it is what the agent
actually sends second, it carries the brand and the STOP line, and it
contains no placeholder, because the child's name is not known until later in
the flow.
