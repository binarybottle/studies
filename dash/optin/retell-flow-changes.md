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

## What to change, in order

### 1. Start node — the confirmation message

A node named **Start** already exists carrying the confirmation text, but it
is not wired in and would not send the text verbatim. Three things to fix:

- Its instruction type is **prompt**, which lets the model rewrite it. Change
  it to **static text**. The wording is registered with the carrier and has
  to go out exactly as submitted:

      Child Mind Institute MATTER Lab: You are opted in to research study messages. Msg & data rates may apply. Msg freq varies. Reply STOP to cancel, HELP for help.

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

    To begin, please text the five-character code shown on the study page.

Transition `When the participant sends a message` back to **Extract study
code**.

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

### 7. Silence timeout

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

**The tools post form data; the endpoints read JSON.** Both `verify_code` and
`complete_study` are configured `parameter_type: form`, and both endpoints
parse a JSON body through a Pydantic model. If Retell sends
`application/x-www-form-urlencoded`, FastAPI answers 422, `code_valid` is
never set, and with the current wiring the interview starts anyway. Test one
call in the simulator and watch the study site's logs. If it 422s, either
switch the tools to JSON or widen the endpoints to accept both.

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

- **Q181 fb05, "How trustworthy did you feel the AI agent was?", is
  unreachable.** The feedback chain runs fb04 -> fb06. Its extract node also
  has an edge with no destination, so the question would dead-end even if
  reached. Anyone analysing the feedback battery will find that item empty.
- **Q102 dpscr097 ("What is it?") is unreachable and dead-ends** — nothing
  points to it, and its only edge has no destination.
- **Preamble: Service Use is unreachable** and its skip edge has no
  destination.
- **Q177 fb01** has a Skip/Next Question edge with no destination.
- Two empty **Code** nodes and one empty **Subagent** node, all unreachable,
  all with dangling edges. Delete them.

## For the campaign application, if TCR comes back

Sample Message 1 already matches the confirmation text exactly. Sample
Message 2 in the submission is the physical-health preamble, which contains
`{{child_name}}`; the reviewer flagged unsubstituted tokens once already. The
interview greeting from step 5 is the better sample: it is what the agent
actually sends second, it carries the brand and the STOP line, and it
contains no placeholder, because the child's name is not known until later in
the flow.
