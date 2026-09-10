# Retell agents and flows

Applies to any study in this repository that runs its interview on Retell.
Everything the interview *says* lives in Retell; everything it *records* lives
in the study's own container. That split is the whole reason this file exists,
because the two halves are joined by identifiers that look alike, live in
different places, and give no error when they disagree — the failure is
silent, and the participant pays for it.

Read this before creating an agent, changing a flow, or moving a study to a
new number.

Concrete values throughout — `dash`, `dash.study.childmind.org`,
`PROLIFIC_CC_*` — come from the DASH study, which is the only one using Retell
so far. Substitute the service name and host of whichever study you are
working on; the structure is the same.

---

## The four identifiers, and which is which

| Identifier | Looks like | Where it must match |
| --- | --- | --- |
| Chat agent | `agent_` + 26 hex | `RETELL_AGENT_ID` in the study's `.env`, **and** the number's SMS bindings |
| Conversation flow | `conversation_flow_` + 12 hex | Owned by the agent; you never configure it directly |
| Agent version | a small integer | Whatever the number's bindings pin, and it must be **published** |
| Tool | `tool_` + timestamp | Internal to the flow; only matters when reading an export |

**An agent id and a flow id are easy to confuse in the dashboard URL, and a
flow id in `RETELL_AGENT_ID` fails identically to a typo.** Both channels go
dark and the log shows `chat_api_failed` with no pid, because the failure
happens before any participant is known.

The agent's own id does not change when you edit its flow. It *does* change
when you import a flow as a new agent, which is the trap in the next section.

### Chat agents are not voice agents

The API keeps them apart, and using the wrong endpoint reports a real agent as
broken:

```bash
# Chat agents — what this study uses
/get-chat-agent/{agent_id}      /list-chat-agents

# Voice agents — a different set entirely
/get-agent/{agent_id}           /list-agents
```

Asking `/get-agent` about a chat agent returns **400 "Invalid agent channel"**,
and `/list-agents` omits it completely. Neither says "this is the wrong
endpoint". `404 Not Found` means the agent really is gone; `400 Invalid agent
channel` means you asked the wrong half of the API.

---

## Editing a flow: dashboard first, import last

**Prefer editing in the dashboard.** Importing a flow can create a *new agent*
with a *new id*, and then:

- `RETELL_AGENT_ID` still points at the old agent, so the browser channel runs
  the old flow;
- the number's SMS bindings still point at the old agent, so texting runs the
  old flow;
- both keep working, so nothing looks wrong until the data is inspected.

If you do import — worth it for edits spread across hundreds of nodes, which is
what `optin/fix_flow.py` exists for — treat it as a migration:

1. Import.
2. Find the new agent id: dashboard URL, or `/list-chat-agents`.
3. Set `RETELL_AGENT_ID` in the study's `.env` and recreate the container.
4. Re-point the number's `inbound_sms_agents` and `outbound_sms_agents`.
5. Publish (see below).
6. Update the identifiers in `STATUS.md`, so the next person is not debugging a
   flow nobody is running.

**An import overwrites the tools**, including their headers, because the tools
live inside the flow. Anything set by hand in the dashboard is lost. Either
re-add it after importing, or bake it into the file first — `fix_flow.py
--token` does exactly this, which is why it is the recommended route.

---

## Publishing

A version that is not published is a draft. `create-chat` serves the
**published** version, so an unpublished edit changes nothing a participant
sees while appearing correct in the canvas.

```bash
# is the version you just edited actually live?
/list-chat-agents        # look for is_published on the highest version
```

The symptom is the worst kind: the fix is visibly present in the editor, and
the interview keeps behaving exactly as it did before.

---

## Binding a phone number

SMS and voice are separate fields on the number. A number can look fully
configured for voice and be completely silent over SMS.

| Field | Takes |
| --- | --- |
| `inbound_sms_agents` | a **chat** agent |
| `outbound_sms_agents` | a **chat** agent |

Both must name the current agent, and both should pin the version you
published. Symptoms of getting this wrong, neither of which mentions SMS:

- `create-sms-chat` returns *"No outbound agent id set up for phone number"*;
- inbound texts reach a number whose only agent is a voice agent, so nothing
  answers at all. This reads as a carrier problem. It is not one.

---

## Tools: what has to be true

Both custom tools post to this application. Four things must hold, and three
of them fail silently.

**1. URLs point at the study host.** They live in the flow, so an import
restores whatever the file says — which is how a hostname corrected by hand
comes back wrong later.

```
https://dash.study.childmind.org/api/verify-code
https://dash.study.childmind.org/api/complete
```

**2. Every parameter is listed in `required`.** The flow runs with
`tool_call_strict_mode: true`, and strict function calling rejects a schema
that omits it. The tool is then never validly called: no request arrives, no
error appears in the transcript, and the flow takes its `Else` edge as though
the call had merely returned nothing.

`verify_code` needs `participant_code`. `complete_study` needs `ac1`, `ac2`,
`ac3` and `pid`.

**3. Both carry the `X-Study-Token` header**, matching `RETELL_TOOL_TOKEN` in
`.env`. See the security section below.

**4. Response variables are mapped.** `verify_code` must map `prolific_pid`,
or `{{prolific_pid}}` is empty on the SMS path and the completion fallback has
nothing to fall back to.

---

## Models

Each node may override the flow's default model, and the default is the
cheapest one in the account. Any node whose text a model *writes* — a Function
node's spoken result, an End node with a `prompt` instruction, a question —
needs a capable model named on the node itself.

Two failure modes, both seen in the September 2026 pilot:

**A weak model emits its own instruction.** The End node's text began *"Send
verbatim: …"* and the model sent that phrase to the participant, scaffolding
and all.

**A weak model invents a plausible value.** Told to send a completion link it
did not have, it produced `cc=C1234567` — the example code from Prolific's own
documentation. A wrong-looking code is a support ticket; a *plausible* one is a
participant who taps it, is rejected, and has no record of finishing.

**Prefer a static sentence wherever no reasoning is needed.** A `static_text`
node interpolates `{{variables}}` but runs no model, so an unresolved variable
renders as visible braces — obviously broken, rather than convincingly wrong.
The final message is static for exactly this reason.

---

## Two different things called a "code"

Confusing these is the most expensive mistake available here.

**The study code** — five characters, e.g. `K7RXQ`. Generated per participant,
shown on the study page, texted *in* by the participant to bind their SMS
conversation. Expires after six hours; `mint_code` re-issues an expired one.
Lives in `study.db`. Never in the flow.

**The Prolific completion code** — e.g. `C1NLN7GA`. Fixed per *study*, one per
outcome, sent *out* at the end inside `{{completion_url}}`. Lives in `.env` as
`PROLIFIC_CC_COMPLETE`, `PROLIFIC_CC_ATTENTION`, `PROLIFIC_CC_NO_CONSENT`.

**Completion codes must never be written into the flow.** The server chooses
which one applies from the attention-check outcome and returns a finished URL;
the flow only ever interpolates `{{completion_url}}`. A completion code stored
in a node is a payment credential sitting in an exportable document, and it
also hard-codes an outcome the server is supposed to decide.

Check them against the Prolific study page — placeholder values are easy to
leave in and impossible to spot in a link:

```bash
docker compose exec -T dash printenv | grep PROLIFIC_CC
```

Each completion path also needs the right action on Prolific: approve for
complete, **hold for review** for the attention-check code, screen-out for
no-consent. Never auto-reject.

---

## Secrets, and what may be shared

### The three sensitive things

**The study's `.env`** (`dash/.env`) — every secret. `chmod 600`, never committed.

**`study.db`** (the `dash_data` volume) — the more serious one. It holds the
linkage table: Prolific IDs, session IDs, chat IDs, salted phone hashes. This
is the only key tying an anonymous transcript back to a participant, and
through Prolific to their demographics. Losing it makes every transcript
permanently unattributable; leaking it de-anonymises them.

**Backups of that volume**, wherever the cron job writes them.

### The two tokens are not interchangeable

| | Guards | Travels as | Held by |
| --- | --- | --- | --- |
| `ADMIN_TOKEN` | `/admin/linkage.csv` | `?token=` in the URL | you |
| `RETELL_TOOL_TOKEN` | the `pid` fallback in `/api/complete` | the `X-Study-Token` header | Retell, in both tools |

**Never reuse `ADMIN_TOKEN` as the tool token.** It would work, and it would
put the key to the entire linkage table into a third party's tool
configuration — where it sits in the flow, in every export of it, and in the
Downloads folder of everyone who has ever exported it.

### Sharing a flow

**An exported flow that carries the header is a secret-bearing document.**
Anyone who can read it can call `/api/complete` with any Prolific ID and mint a
completion link.

- **Publicly: no.** Rotate the token first if a flow with headers has ever left
  your control — new `openssl rand -hex 24`, into `.env`, recreate the
  container, update both tool headers.
- **With a colleague: yes**, exported without `--token`, or with the two
  `headers` objects emptied. What remains is questions and routing.
- **Before publishing anything anywhere**, settle whether the instrument's
  licence permits republishing its verbatim items. That is a question for
  whoever owns the instrument, not a technical one.

Exports produced by `fix_flow.py --token` are gitignored as `*.fixed.json`.
Delete them once imported.

---

## Pre-flight check

Run before every test round. Everything is read-only, and it runs from the
droplet because that is where the API key lives. `dash` is the compose service
name — use the study's own.

```bash
ssh arno@167.71.248.46 'cd ~/studies && docker compose exec -T dash python -c "
import os, json, urllib.request, hashlib
k=os.environ[\"RETELL_API_KEY\"]; a=os.environ[\"RETELL_AGENT_ID\"]
g=lambda p: json.load(urllib.request.urlopen(urllib.request.Request(
    \"https://api.retellai.com\"+p, headers={\"Authorization\":\"Bearer \"+k}), timeout=25))

ag = g(\"/get-chat-agent/\"+a)
flow = (ag.get(\"response_engine\") or {}).get(\"conversation_flow_id\")
print(\"agent  \", a, ag.get(\"agent_name\"))
print(\"flow   \", flow, \"version\", ag.get(\"version\"), \"published\", ag.get(\"is_published\"))

pub = [x for x in g(\"/list-chat-agents\") if x.get(\"agent_id\")==a and x.get(\"is_published\")]
print(\"published versions:\", sorted(x.get(\"version\") for x in pub))

ver = ag.get(\"version\")
f = g(\"/get-conversation-flow/\"+flow+\"?version=\"+str(ver))
print(\"nodes\", len(f.get(\"nodes\") or []), \"strict\", f.get(\"tool_call_strict_mode\"))
env = os.environ.get(\"RETELL_TOOL_TOKEN\",\"\")
for t in f.get(\"tools\") or []:
    p = t.get(\"parameters\") or {}
    hdr = (t.get(\"headers\") or {}).get(\"X-Study-Token\",\"\")
    print(\" \", t.get(\"name\"),
          \"| required:\", p.get(\"required\",\"ABSENT\"),
          \"| token matches env:\", bool(hdr) and hdr==env,
          \"|\", t.get(\"url\"))
"'
```

Everything must be true at once:

- the agent id printed is the one in `.env`;
- the highest version is **published**;
- both tools list every parameter as `required`;
- both report `token matches env: True`;
- both URLs name the study host.

Then confirm the deployed code is the code you think it is:

```bash
ssh arno@167.71.248.46 'cd ~/studies && git log --oneline -1 && \
  docker compose exec -T dash md5sum /app/study_site.py && md5sum dash/study_site.py'
```

The two hashes must match. They diverge whenever someone pulls without
rebuilding, and the symptom is a fix that is committed, present on the server,
and not running.

---

## Restarting the container mid-study

The interview lives in Retell and the linkage lives in a named volume, so a
rebuild loses neither. Reopening `/chat?pid=…` resumes: the stored `chat_id`
pulls the history back and re-asks the last question.

The rebuild is roughly 20–40 seconds of 502.

- A browser participant between questions notices nothing.
- One who sends during the window sees *"The interviewer is not responding.
  Your answer was not lost; try again."* — accurate; the message never left.

**The case that does harm is a Retell tool call landing in the window**, since
those do not retry. `verify_code` falls to its Else edge and tells a
participant their valid code was rejected; `complete_study` falls to its Else
edge and sends someone to the End node with no completion link.

So: rebuild in the middle of interviews, never at the beginning or the end.

---

## What a silent failure looks like

Every one of these produces a participant who finished and cannot be paid,
with nothing in the transcript to show for it. This is the list to check.

| Symptom | Cause |
| --- | --- |
| Fix visible in the canvas, behaviour unchanged | version not published |
| Browser works, texting runs an old script | number bound to the previous agent |
| Both channels dead, `chat_api_failed` with no pid | `RETELL_AGENT_ID` wrong or a flow id |
| Tool never called, no error anywhere | a parameter missing from `required` under strict mode |
| `tool_unresolved … unauth` | `X-Study-Token` and `RETELL_TOOL_TOKEN` disagree |
| `tool_unresolved … no-pid` | `pid` parameter missing from `complete_study` |
| `{{completion_url}}` sent literally | the call failed; a static End node made it visible |
| A plausible but invented completion code | a model-written End node on a weak model |
| Code rejected at the gate for no reason | expired code, or a tool call during a restart |

---

See also [`dash/README.md`](dash/README.md) for that study, [`dash/STATUS.md`](dash/STATUS.md)
for the current identifiers and outstanding decisions, and
[`dash/optin/fix_flow.py`](dash/optin/fix_flow.py) for the flow transform.
