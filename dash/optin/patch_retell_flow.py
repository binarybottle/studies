"""Apply the flow changes in retell-flow-changes.md to an exported flow.

Seven edits across a 423-node canvas is a lot of clicking, and one edge
pointed at the wrong node puts the interview back on the path where it
starts without a verified code. Doing it as a transform means the change is
reviewable, repeatable, and checked afterwards by walking the graph.

    $ python dash/optin/patch_retell_flow.py \\
          ~/Downloads/"DASH-MH-P-GS TEXT (1).json" \\
          ~/Downloads/"DASH-MH-P-GS TEXT (patched).json"

Import the result into Retell as a new version and diff it in the canvas
before publishing. Every edit asserts what it expects to find first, so a
flow that has moved on since the export fails here rather than silently
producing something different.

Exactly one previously detached node is attached: the Start node carrying the
confirmation message, and with it the code-verification path it leads to.
Everything else that was detached in the export is left exactly as it was,
attached to nothing and deleting nothing.
"""

from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import study_site as site  # noqa: E402

INTERVIEW_GREETING = (
    "Hello! I am an AI assistant from the Child Mind Institute MATTER Lab, "
    "messaging you to ask some questions about the child described in the "
    "persona you were given, as part of the DASH Mental Health Screener. "
    "Reply STOP at any time to end."
)
# The registered confirmation, then what to do next. Keeping the registered
# text as a verbatim prefix means the message a reviewer tests still opens
# with the sample on file; the instruction that follows saves a round trip in
# which the participant answers the confirmation with "hi" and is asked again.
START_MESSAGE = (
    site.CONFIRMATION_SMS
    + " To continue, text the five-character code shown on the study page."
)
# Where someone who did not send a code lands, and so where the instructions
# for recovering a lost one belong -- not in a message every participant gets.
ASK_CODE = (
    "To begin, please text the five-character code shown on the study page. "
    "If you no longer have it, reopen the study link on Prolific to see it "
    "again."
)
CODE_RETRY = (
    'Send verbatim: "That code was not accepted. {{code_message}} Please text '
    "the five-character code shown on the study page. If you no longer have "
    'it, reopen the study link on Prolific to see it again."\n\n'
    "Wait for the participant to send a code, then continue. Do not restate "
    "or comment on it."
)
SILENCE_MS = 259_200_000  # 72 hours; the timer starts at the confirmation.
# The two custom tools post to the study host. They live in the flow, so an
# import overwrites whatever the dashboard says -- which is how a hostname
# corrected by hand comes back wrong the next time the flow is imported.
STUDY_HOST = "https://dash.studies.childmind.org"

# HELP is a keyword a carrier tests, so its answer cannot be improvised. Left
# to the model it invented an address that exists nowhere. Stated as a
# verbatim rule in the global prompt, which is how this flow already pins its
# other fixed answers. 152 GSM-7 units, one segment.
HELP_REPLY = (
    "Child Mind Institute MATTER Lab: DASH research study messages. "
    f"Help: {site.CONTACT_EMAIL}. Msg & data rates may apply. "
    "Reply STOP to cancel."
)
HELP_RULE = (
    "\n## SMS keywords\n"
    "If the participant sends HELP, or asks how to get help or who to "
    f'contact, reply verbatim: "{HELP_REPLY}"\n'
    "Never invent a contact address. This one and no other.\n"
)

# Retell stores a tool's response variables as text, and the endpoint answers
# with a JSON boolean. Which spelling arrives is not documented, so accept
# every plausible one. Anything else -- false, unset, a timed-out call --
# falls to the Else edge and does not reach the interview.
TRUE_SPELLINGS = ("true", "True", "1")


def node(flow: dict, node_id: str) -> dict:
    """Return one node by id.

    Args:
        flow: The ``conversationFlow`` object.
        node_id: Node identifier.

    Returns:
        The node dictionary.

    Raises:
        KeyError: If the flow has no such node.
    """
    for candidate in flow["nodes"]:
        if candidate["id"] == node_id:
            return candidate
    raise KeyError(node_id)


def patch(data: dict) -> dict:
    """Apply every change to a parsed export, in place.

    Args:
        data: The parsed agent export.

    Returns:
        The same object, modified.
    """
    flow = data["conversationFlow"]

    # 1. Start node: the confirmation, sent verbatim, wired into the code path.
    start = node(flow, "node-1787629784000")
    assert start["instruction"]["type"] == "prompt", "Start already converted?"
    start["instruction"] = {"type": "static_text", "text": START_MESSAGE}
    start["edges"] = [
        {
            "id": "e-start-to-code",
            "destination_node_id": "ev-study-code",
            "transition_condition": {
                "type": "prompt",
                "prompt": "When the participant sends any message",
            },
        }
    ]
    flow["start_node_id"] = "node-1787629784000"

    # 2 and 3. A first message that is not a code gets asked for one, rather
    # than calling the endpoint with nothing.
    extract = node(flow, "ev-study-code")
    assert extract["else_edge"]["destination_node_id"] == "fn-verify-code"
    extract["else_edge"]["destination_node_id"] = "q-ask-code"
    flow["nodes"].append(
        {
            "id": "q-ask-code",
            "name": "Ask code",
            "type": "conversation",
            "display_position": {"x": 420, "y": 180},
            "instruction": {"type": "static_text", "text": ASK_CODE},
            "edges": [
                {
                    "id": "e-q-ask-code",
                    "destination_node_id": "ev-study-code",
                    "transition_condition": {
                        "type": "prompt",
                        "prompt": "When the participant sends a message",
                    },
                }
            ],
        }
    )

    # 4. Fail closed. The old edge was labelled == true and tested == false,
    # with Else falling through to the interview.
    verify = node(flow, "fn-verify-code")
    assert verify["else_edge"]["destination_node_id"] == "q-confirm_start"
    verify["edges"] = [
        {
            "id": "e-fn-verify-ok",
            "destination_node_id": "greet-hello",
            "condition": "{{code_valid}} == true",
            "transition_condition": {
                "type": "equation",
                "operator": "||",
                "equations": [
                    {"left": "{{code_valid}}", "operator": "==", "right": spelling}
                    for spelling in TRUE_SPELLINGS
                ],
            },
        }
    ]
    verify["else_edge"]["destination_node_id"] = "q-code-retry"

    # 5. The old greeting becomes the interview greeting, after verification.
    greeting = node(flow, "greet-hello")
    assert greeting["edges"][0]["destination_node_id"] == "q-confirm_start"
    greeting["name"] = "Interview greeting"
    greeting["instruction"] = {"type": "static_text", "text": INTERVIEW_GREETING}
    greeting["edges"] = []
    greeting["skip_response_edge"] = {
        "id": "skip-interview-greeting",
        "destination_node_id": "q-confirm_start",
        "condition": "Skip response",
        "transition_condition": {"type": "prompt", "prompt": "Skip response"},
    }

    # 6. The retry no longer opens with a variable that is unset when the
    # endpoint never answered.
    retry = node(flow, "q-code-retry")
    assert retry["instruction"]["text"].startswith('Send verbatim: "{{code_message}}')
    retry["instruction"]["text"] = CODE_RETRY

    # 7. The silence timer now runs from the confirmation, not from the
    # participant's first message.
    data["end_chat_after_silence_ms"] = SILENCE_MS

    # 8. Both tools point at the study host, which is now the organization's.
    for tool in flow.get("tools", []):
        if "/api/" in tool.get("url", ""):
            tool["url"] = STUDY_HOST + tool["url"].split("/api/", 1)[1].join(
                ("/api/", "")
            )

    # 9. A fixed answer for HELP.
    assert "HELP" not in flow["global_prompt"], "HELP rule already present?"
    flow["global_prompt"] = flow["global_prompt"].rstrip("\n") + "\n" + HELP_RULE

    # Nothing else is attached or removed. Every other node that was
    # unreachable in the export stays unreachable here, including the three
    # empty ones and the skipped feedback question: what to do with them is a
    # decision about the study, and a node left detached changes nothing,
    # while a node wired in changes what participants are asked.
    return data


def reachable(flow: dict) -> set[str]:
    """Return the node ids reachable from the start node.

    Args:
        flow: The ``conversationFlow`` object.

    Returns:
        Reachable node identifiers.
    """
    ids = {n["id"] for n in flow["nodes"]}
    seen: set[str] = set()
    stack = [flow["start_node_id"]]
    while stack:
        current = stack.pop()
        if current in seen or current not in ids:
            continue
        seen.add(current)
        found = node(flow, current)
        edges = list(found.get("edges") or [])
        for key in ("else_edge", "skip_response_edge"):
            if found.get(key):
                edges.append(found[key])
        stack.extend(e["destination_node_id"] for e in edges
                     if e.get("destination_node_id"))
    return seen


if __name__ == "__main__":
    source = pathlib.Path(sys.argv[1]).expanduser()
    target = pathlib.Path(sys.argv[2]).expanduser()
    patched = patch(json.loads(source.read_text(encoding="utf-8")))
    target.write_text(json.dumps(patched, indent=2), encoding="utf-8")
    print(f"wrote {target}")
