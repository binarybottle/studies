"""Add the browser branch to an exported Retell flow.

The flow was built for text messages: its first node sends the opt-in
confirmation and then waits for a five-character code. A browser participant
has neither opted in by text nor been given a code -- this application created
their conversation on their behalf and already knows who they are -- so that
opening is wrong for them and the code gate is unreachable machinery.

Two edits fix it without a second copy of the questionnaire:

1. The first node's text becomes ``{{opening}}``, with the confirmation
   wording as its default. A text conversation is then unchanged, whether
   this application starts it or someone texts the number cold, and a browser
   conversation supplies its own opening.

2. That node gains an edge on ``{{study_channel}}``. Browser conversations
   go straight to the yes/no extraction; everything else takes the existing
   path through the code gate.

The branch is on the node's *outgoing edge* rather than the node itself,
which matters: Retell takes the first outbound SMS from the start node's
begin message, so that node has to stay a message node. Leave it a message
node and the text path is byte-identical to what the carrier reviewed.

Usage::

    $ python dash/optin/add_web_branch.py ~/Downloads/flow.json
    wrote ~/Downloads/flow.web.json

Import the result in the Retell dashboard, then publish. Running it twice on
the same file is harmless; it reports that the branch is already present and
writes nothing.
"""

from __future__ import annotations

import json
import pathlib
import sys

WEB_EDGE_ID = "e-start-web"
OPENING_PLACEHOLDER = "{{opening}}"

# Where each channel goes after the first node speaks and the participant
# replies. Text conversations extract a code; browser conversations extract
# the yes or no that the opening asked for.
SMS_DESTINATION = "ev-study-code"
WEB_DESTINATION = "ev-confirm_start"


def patch(flow: dict) -> list[str]:
    """Apply both edits in place.

    Args:
        flow: The ``conversationFlow`` object.

    Returns:
        What changed, one line each. Empty if the flow was already patched.

    Raises:
        SystemExit: If the flow is not the one this script was written for.
            Failing loudly beats importing a flow that silently drops one of
            its two channels.
    """
    done: list[str] = []
    nodes = {n["id"]: n for n in flow["nodes"]}

    start = nodes.get(flow.get("start_node_id"))
    if start is None:
        raise SystemExit("The flow has no start node; is this the right export?")
    if start.get("type") != "conversation":
        raise SystemExit(
            f"The start node is a {start.get('type')!r} node. It must stay a\n"
            "message node: Retell takes the first outbound SMS from it."
        )
    for required in (SMS_DESTINATION, WEB_DESTINATION):
        if required not in nodes:
            raise SystemExit(f"Expected a node called {required!r} and found none.")

    # 1. The opening becomes a variable, keeping its current text as default.
    instruction = start.get("instruction") or {}
    text = instruction.get("text", "")
    if text != OPENING_PLACEHOLDER:
        if instruction.get("type") != "static_text":
            raise SystemExit("The start node's text is not static; refusing to guess.")
        defaults = flow.setdefault("default_dynamic_variables", {})
        defaults["opening"] = text
        # Without a default, {{study_channel}} is unset in a text conversation
        # and the equation below compares against nothing.
        defaults.setdefault("study_channel", "sms")
        instruction["text"] = OPENING_PLACEHOLDER
        done.append("start node speaks {{opening}}, defaulting to the confirmation")

    # 2. The branch, listed first so it is considered before the code path.
    edges = start.setdefault("edges", [])
    if not any(edge.get("id") == WEB_EDGE_ID for edge in edges):
        if not any(e.get("destination_node_id") == SMS_DESTINATION for e in edges):
            raise SystemExit(
                f"The start node does not lead to {SMS_DESTINATION!r}. This script\n"
                "expects the text-message path to be in place already."
            )
        edges.insert(
            0,
            {
                "id": WEB_EDGE_ID,
                "condition": "{{study_channel}} == web",
                "destination_node_id": WEB_DESTINATION,
                "transition_condition": {
                    "type": "equation",
                    "operator": "&&",
                    "equations": [
                        {
                            "left": "{{study_channel}}",
                            "operator": "==",
                            "right": "web",
                        }
                    ],
                },
            },
        )
        done.append(f"browser conversations branch to {WEB_DESTINATION}")

    return done


def reachable(flow: dict, start: str) -> set[str]:
    """Every node reachable from one starting point.

    Args:
        flow: The ``conversationFlow`` object.
        start: Node id to walk from.

    Returns:
        The reachable node ids, including the start.
    """
    nodes = {n["id"]: n for n in flow["nodes"]}
    seen: set[str] = set()
    queue = [start]
    while queue:
        current = queue.pop()
        if current in seen or current not in nodes:
            continue
        seen.add(current)
        node = nodes[current]
        for edge in list(node.get("edges") or []):
            for key in ("destination_node_id",):
                if edge.get(key):
                    queue.append(edge[key])
        for key in ("else_edge", "skip_response_edge"):
            edge = node.get(key)
            if edge and edge.get("destination_node_id"):
                queue.append(edge["destination_node_id"])
    return seen


def main() -> None:
    """Patch the file named on the command line."""
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    source = pathlib.Path(sys.argv[1]).expanduser()
    agent = json.loads(source.read_text(encoding="utf-8"))
    flow = agent["conversationFlow"]

    changes = patch(flow)
    if not changes:
        print("Already patched; nothing written.")
        return
    for change in changes:
        print(f"  {change}")

    # Both channels must actually arrive somewhere useful.
    from_start = reachable(flow, flow["start_node_id"])
    for destination, label in (
        (SMS_DESTINATION, "text message"),
        (WEB_DESTINATION, "browser"),
    ):
        if destination not in from_start:
            raise SystemExit(f"The {label} path is unreachable after patching.")
    for landmark, label in (
        ("fn-verify-code", "code verification"),
        ("end-complete", "the completion node"),
        ("fn-complete", "the completion function"),
    ):
        if landmark not in from_start:
            raise SystemExit(f"{label} became unreachable after patching.")

    web_only = reachable(flow, WEB_DESTINATION)
    if "fn-verify-code" in web_only:
        print("  note: the browser path can still reach the code gate")

    out = source.with_suffix(".web.json")
    out.write_text(json.dumps(agent, indent=2), encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
