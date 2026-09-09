"""Apply the outstanding flow corrections to an exported Retell flow.

Everything here was found by reading a v4 export against the pilot feedback
of 8 September 2026. Doing it as a transform rather than by hand keeps the
edits reviewable and repeatable, and lets the graph be walked afterwards --
two of these are edges that point nowhere, which is exactly the class of
mistake that clicking makes and re-clicking hides.

    $ python dash/optin/fix_flow.py ~/Downloads/"DASH-MH-P-GS TEXT.json"
    $ python dash/optin/fix_flow.py export.json --token "$RETELL_TOOL_TOKEN"

Writes a sibling ``.fixed.json``. Import it as a new version, diff it in the
canvas, publish it, and then re-point the number's inbound and outbound SMS
agents at the new version -- they are pinned to a version, not to "latest",
so texting keeps running the old flow until you do.

Every edit states what it expects to find and reports when a fix is already
present, so running this twice is safe and running it against a flow that
has moved on fails loudly rather than producing something different.

**With --token the output contains a secret.** It is written into the two
tools' headers because that is the only place an import will not overwrite.
Do not commit the result; delete it once imported.
"""

from __future__ import annotations

import argparse
import copy
import json
import pathlib
import re

# The feedback battery, by node id. fb05 sits between fb04 and fb06 when it
# exists at all.
FB05 = "node-1781658715699"
FB05_EXTRACT = "node-1781658882071"
FB06 = "node-1781658944572"
FB06_EXTRACT = "node-1781659020909"
FB05_QUESTION = """How trustworthy did you feel the AI agent was?

1 - Not at all trustworthy
2 - Slightly trustworthy
3 - Moderately trustworthy
4 - Very trustworthy
5 - Extremely trustworthy"""

# Q78 asserts a diagnosis the flow's own global prompt forbids ("Do NOT
# diagnose"), and asserts it off a gate that fires on any one of five items --
# "cried a lot" alone is enough. The replacement names what they actually
# endorsed instead. The second sentence, the instrument's own duration probe,
# is untouched.
Q78_OLD = "You mentioned {{child_name}} experiencing symptoms of depression."
Q78_NEW = (
    "You mentioned that there were times when {{child_name}} felt sad, "
    "cried more, felt grouchy, or was less interested in things."
)

# A static sentence is sent exactly as written, so the model that leaked its
# own instruction at the end of the interview is no longer in the loop at all.
# Dynamic variables still interpolate.
END_COMPLETE = (
    "Thank you so much for taking the time to answer these questions about "
    "{{child_name}}. Your responses will help us better understand "
    "{{pronoun3}} experiences.\n\n"
    "Please use this link to register your completion on Prolific: "
    "{{completion_url}}"
)

# Asked of everyone, because the extract node before it has no edges and
# falls through to this one. Presupposing discomfort of every participant is
# a leading question; ask whether there was any.
FB12_OLD = "Please describe what felt uncomfortable or concerning."
FB12 = (
    "Was anything about this conversation uncomfortable or concerning? "
    "If so, please describe it."
)

# Deleting the suicidality block left its neighbours pointing at nothing, which
# severs the interview: nothing after the anger section is reachable, including
# the completion node. q-dpscr225 is the next surviving node in the original
# order, so reconnecting there restores the tail without inventing an order.
SEVERED = {
    "ev-dpscr103": ("e-ev-dpscr103-n", "e-ev-dpscr103-u"),
    "ev-dpscr107": ("e-ev-dpscr107-ok",),
}
SEVERED_TARGET = "q-dpscr225"

STRONG_MODEL = {"model": "claude-4.6-sonnet", "type": "cascading"}

# Q184 offers five options and invites "(Select all that apply)", but its
# extract wants a single number and its edge matches one value. "1, 3" fails
# extraction and falls to the else edge, which re-asks the same question --
# forever. Accepting a selection means storing what they picked as text.
FB08 = "node-1781659304121"
FB08_EXTRACT = "node-1781659347728"
FB08_VARIABLE = {
    "name": "fb08",
    "type": "string",
    "description": (
        "Privacy reassurances chosen. Exactly one of these three shapes: a "
        "comma-separated list of any of 1, 2 and 3 (e.g. '1,3'); or exactly "
        "'4'; or '5' followed by a colon and what they typed. 4 means none of "
        "the above and 5 means something else, so neither ever appears "
        "alongside another option. If the reply mixes 4 or 5 with any other "
        "option, or names no option at all, do not extract."
    ),
}
FB08_TRANSITION = (
    "Transition when the participant picks either one or more of 1, 2 and 3, "
    "or 4 on its own, or 5 on its own with what they would want. Options 4 "
    "and 5 are exclusive: they cannot be combined with any other option, or "
    "with each other. If they combine them, or reply with anything else, send "
    'verbatim: "Please pick one or more of 1, 2 and 3, or 4 on its own, or 5 '
    'on its own." then re-send the question and the five numbered options '
    "verbatim."
)

# A question that lists four options but signs off "send the question and all
# five options" is telling the model to send an option that does not exist --
# left over from rescaling the battery from five points to four. The count is
# read from the text rather than hard-coded, so this cannot mislabel a
# question someone later rewrites.
NUMBER_WORDS = {2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven"}
OPTION_LINE = re.compile(r"^(\d+)(?:\s[-\u2013\u2014]\s|\.\s)", re.MULTILINE)
OPTION_TAIL = re.compile(r"all (\w+) options in a single message")

# Reachable from the start node in the v4 export but attached to nothing that
# leads anywhere, or vice versa. Left alone unless --prune is passed.
KNOWN_ORPHANS = (
    "preamble-service",
    "q-dpscr097",
    "node-1776965282383",
    "node-1787226863223",
)


def node(flow: dict, node_id: str) -> dict:
    """Return one node by id.

    Args:
        flow: The ``conversationFlow`` object.
        node_id: Node id to find.

    Returns:
        The node.

    Raises:
        SystemExit: When the flow has no such node, which means the export
            has moved on and the rest of this script cannot be trusted.
    """
    for candidate in flow["nodes"]:
        if candidate["id"] == node_id:
            return candidate
    raise SystemExit(f"No node {node_id!r}: is this the right export?")


def tool(flow: dict, name: str) -> dict:
    """Return one custom tool by name.

    Args:
        flow: The ``conversationFlow`` object.
        name: Tool name as configured in the dashboard.

    Returns:
        The tool definition.

    Raises:
        SystemExit: When the tool is absent.
    """
    for candidate in flow.get("tools") or []:
        if candidate.get("name") == name:
            return candidate
    raise SystemExit(f"No tool {name!r}: is this the right export?")


def fix_end_nodes(flow: dict) -> list[str]:
    """Take the model out of the final message, and off the declined one.

    The completion node emitted its own instruction -- "Send verbatim: ...
    Then politely end the chat" -- to at least two participants. It was the
    only node whose text a model wrote without a ``model_choice`` of its own,
    so it ran on the flow default, which is the weakest model in the account.
    A static sentence removes the model rather than upgrading it.

    Args:
        flow: The ``conversationFlow`` object.

    Returns:
        A line per change made.
    """
    done = []

    complete = node(flow, "end-complete")
    if complete["instruction"].get("type") != "static_text":
        assert "Send verbatim" in complete["instruction"]["text"], (
            "end-complete no longer carries the verbatim wrapper; check what "
            "it says now before replacing it"
        )
        complete["instruction"] = {"type": "static_text", "text": END_COMPLETE}
        done.append("end-complete sends a static sentence, no model involved")
    elif complete["instruction"]["text"] != END_COMPLETE:
        # Already static, but still carrying the prompt scaffolding, which a
        # static node sends word for word.
        complete["instruction"]["text"] = END_COMPLETE
        done.append("end-complete static text stripped of its prompt wrapper")

    declined = node(flow, "end-declined")
    if declined.get("model_choice", {}).get("model") != STRONG_MODEL["model"]:
        declined["model_choice"] = dict(STRONG_MODEL)
        done.append("end-declined pinned to claude-4.6-sonnet")

    return done


def fix_q78(flow: dict) -> list[str]:
    """Stop telling a parent their child has symptoms of depression.

    Args:
        flow: The ``conversationFlow`` object.

    Returns:
        A line per change made.
    """
    q78 = node(flow, "q-dpscr250")
    text = q78["instruction"]["text"]
    if Q78_OLD not in text:
        return []
    q78["instruction"]["text"] = text.replace(Q78_OLD, Q78_NEW, 1)
    return ["Q78 names the endorsed items rather than a diagnosis"]


def restore_fb05(flow: dict) -> list[str]:
    """Rebuild the trustworthiness question from its surviving neighbour.

    The v5 export deletes ``fb05`` and its extract node rather than attaching
    them, so the item is gone from the battery entirely. Rebuilding it by
    cloning ``fb06`` keeps every convention of the surrounding nodes -- the
    preamble, the trailing instruction, the em dash, the transition wording --
    which retyping would not.

    Args:
        flow: The ``conversationFlow`` object.

    Returns:
        A line per change made.
    """
    template = copy.deepcopy(node(flow, FB06))
    text = template["instruction"]["text"]
    opening = text.index('"') + 1
    closing = text.index("\n\nPlease reply", opening)
    template["instruction"]["text"] = text[:opening] + FB05_QUESTION + text[closing:]
    template["id"] = FB05
    template["name"] = "Q181: fb05"
    template["display_position"] = {"x": 109062, "y": 222}
    template["edges"] = [
        dict(template["edges"][0], id="e-fb05", destination_node_id=FB05_EXTRACT)
    ]

    extract = copy.deepcopy(node(flow, FB06_EXTRACT))
    extract["id"] = FB05_EXTRACT
    extract["display_position"] = {"x": 109062, "y": 894}
    extract["variables"] = [
        {
            "name": "fb05",
            "type": "number",
            "description": "How trustworthy the agent seemed",
        }
    ]
    edge = extract["edges"][0]
    edge["id"] = "e-fb05-answered"
    edge["destination_node_id"] = FB06
    for equation in edge["transition_condition"]["equations"]:
        equation["left"] = "{{fb05}}"
    extract["else_edge"] = dict(extract["else_edge"], destination_node_id=FB05)

    flow["nodes"].extend([template, extract])
    return [f"rebuilt {FB05} and {FB05_EXTRACT} from fb06"]


def fix_feedback_battery(flow: dict, restore: bool) -> list[str]:
    """Route the battery correctly, and stop fb12 presupposing an answer.

    ``fb05`` -- "How trustworthy did you feel the AI agent was?" -- is asked
    of nobody. In the v4 export it was orphaned and would have trapped anyone
    who reached it, its answer edge having no destination; in v5 it is
    deleted outright. Either way the item is missing from the data, so this
    reports rather than guesses unless asked to restore it.

    Args:
        flow: The ``conversationFlow`` object.
        restore: Whether to rebuild fb05 when the export no longer has it.

    Returns:
        A line per change made.
    """
    done = []
    present = {n["id"] for n in flow["nodes"]}

    if FB05 not in present and restore:
        done += restore_fb05(flow)
        present = {n["id"] for n in flow["nodes"]}

    if FB05 in present:
        fb04_extract = node(flow, "node-1781658556125")
        edge = fb04_extract["edges"][0]
        if edge.get("destination_node_id") != FB05:
            assert edge.get("destination_node_id") == FB06, (
                "fb04 no longer routes to fb06; the battery has been rewired"
            )
            edge["destination_node_id"] = FB05
            done.append("fb04 leads to fb05 (trustworthiness) rather than past it")

        fb05_extract = node(flow, FB05_EXTRACT)
        edge = fb05_extract["edges"][0]
        if not edge.get("destination_node_id"):
            edge["destination_node_id"] = FB06
            done.append("fb05's answer edge leads to fb06 instead of nowhere")
    else:
        done.append(
            "note: fb05 (trustworthiness) is not in this export and was not "
            "recreated; pass --restore-fb05 to rebuild it"
        )

    # Only the wording this was written for. The battery has been rewritten
    # once already, and clobbering someone's new question with an old fix is
    # worse than leaving it alone.
    fb12 = node(flow, "node-1781655693730")
    if fb12["instruction"]["text"] == FB12_OLD:
        fb12["instruction"]["text"] = FB12
        done.append("fb12 asks whether anything was uncomfortable, not what was")

    fb01 = node(flow, "node-1781653422043")
    dangling = [e for e in fb01["edges"] if not e.get("destination_node_id")]
    if dangling:
        fb01["edges"] = [e for e in fb01["edges"] if e.get("destination_node_id")]
        done.append(f"fb01 drops {len(dangling)} transition(s) pointing nowhere")

    return done


def fix_severed_anger(flow: dict) -> list[str]:
    """Reattach the edges the deleted suicidality block left hanging.

    Repaired only when the block really is gone and the target really is
    present, so this cannot fire on a flow that still has its own routing.

    Args:
        flow: The ``conversationFlow`` object.

    Returns:
        A line per change made.
    """
    present = {n["id"] for n in flow["nodes"]}
    if "preamble-suicide" in present or SEVERED_TARGET not in present:
        return []

    done = []
    for node_id, edge_ids in SEVERED.items():
        if node_id not in present:
            continue
        for edge in node(flow, node_id)["edges"]:
            if edge.get("id") in edge_ids and not edge.get("destination_node_id"):
                edge["destination_node_id"] = SEVERED_TARGET
                done.append(
                    f"{node_id}/{edge['id']} now leads to {SEVERED_TARGET} "
                    "instead of nowhere"
                )
    return done


def fix_multiselect(flow: dict) -> list[str]:
    """Let the multi-select question accept a multiple selection.

    Q184 says "(Select all that apply)" and then refuses to. Its variable is
    a number and its edge matches a single value, so "1, 3" -- the answer the
    question invites -- fails extraction, falls to the else edge, and re-asks
    the same question with no way forward.

    Args:
        flow: The ``conversationFlow`` object.

    Returns:
        A line per change made.
    """
    present = {n["id"] for n in flow["nodes"]}
    if FB08 not in present or FB08_EXTRACT not in present:
        return []

    done = []
    question = node(flow, FB08)
    if "Select all that apply" not in question["instruction"]["text"]:
        return []

    edge = question["edges"][0]
    if edge["transition_condition"].get("prompt") != FB08_TRANSITION:
        edge["transition_condition"]["prompt"] = FB08_TRANSITION
        done.append("Q184 transitions on a selection, not on one number")

    extract = node(flow, FB08_EXTRACT)
    if extract["variables"] != [FB08_VARIABLE]:
        extract["variables"] = [copy.deepcopy(FB08_VARIABLE)]
        done.append("fb08 is stored as text, so more than one choice survives")

    answered = extract["edges"][0]
    if answered["transition_condition"].get("type") != "equation" or answered[
        "transition_condition"
    ]["equations"] != [{"left": "{{fb08}}", "operator": "exists"}]:
        answered["transition_condition"] = {
            "type": "equation",
            "operator": "&&",
            "equations": [{"left": "{{fb08}}", "operator": "exists"}],
        }
        answered["condition"] = "{{fb08}} exists"
        done.append("fb08's answer edge passes on any selection, not five values")

    return done


def fix_option_counts(flow: dict) -> list[str]:
    """Make each question's closing instruction name the options it lists.

    Args:
        flow: The ``conversationFlow`` object.

    Returns:
        A line per change made.
    """
    done = []
    for candidate in flow["nodes"]:
        text = (candidate.get("instruction") or {}).get("text") or ""
        tail = OPTION_TAIL.search(text)
        if not tail:
            continue
        listed = len(OPTION_LINE.findall(text))
        correct = NUMBER_WORDS.get(listed)
        if not correct or tail.group(1) == correct:
            continue
        candidate["instruction"]["text"] = (
            text[: tail.start(1)] + correct + text[tail.end(1) :]
        )
        done.append(
            f"{candidate.get('name')} lists {listed} options and now says so "
            f"(was \"{tail.group(1)}\")"
        )
    return done


def fix_tools(flow: dict, token: str | None) -> list[str]:
    """Give the completion call a second way to identify the participant.

    ``/api/complete`` finds the participant by conversation id. When that
    misses -- and on 8 September 2026 it missed for every session -- nothing
    identifies them, no completion URL comes back, and the flow walks into
    its End node anyway with ``{{completion_url}}`` unresolved. The flow
    knows ``{{prolific_pid}}`` in both channels, so send it.

    The shared secret is what makes that safe: a conversation id is a secret
    only Retell holds, a Prolific ID is not, and completion links are worth
    money. Without the header the application refuses the fallback.

    Args:
        flow: The ``conversationFlow`` object.
        token: Value for the ``X-Study-Token`` header, or None to leave the
            headers alone and set them in the dashboard by hand.

    Returns:
        A line per change made.
    """
    done = []

    complete = tool(flow, "complete_study")
    properties = complete["parameters"]["properties"]
    if "pid" not in properties:
        properties["pid"] = {
            "type": "string",
            "description": "Prolific participant ID. Use exactly: {{prolific_pid}}",
        }
        done.append("complete_study sends pid so completion does not hang on payload shape")

    # The flow runs with tool_call_strict_mode on, and strict function calling
    # rejects a schema that does not list every property as required.
    # verify_code lists its one parameter and is called successfully all day;
    # complete_study listed none and has never once produced a stage_complete.
    # Matching the tool that works costs nothing if the cause is elsewhere.
    wanted = sorted(properties)
    if sorted(complete["parameters"].get("required") or []) != wanted:
        complete["parameters"]["required"] = wanted
        done.append(
            "complete_study declares its parameters required, as strict mode "
            f"demands: {', '.join(wanted)}"
        )

    verify = tool(flow, "verify_code")
    if "prolific_pid" not in verify.get("response_variables", {}):
        verify.setdefault("response_variables", {})["prolific_pid"] = "prolific_pid"
        done.append("verify_code captures prolific_pid, so the SMS path knows it too")

    if token:
        for candidate in (verify, complete):
            headers = candidate.setdefault("headers", {})
            if headers.get("X-Study-Token") != token:
                headers["X-Study-Token"] = token
                done.append(f"{candidate['name']} carries the X-Study-Token header")

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
        current_node = nodes[current]
        for edge in list(current_node.get("edges") or []):
            if edge.get("destination_node_id"):
                queue.append(edge["destination_node_id"])
        for key in ("else_edge", "skip_response_edge"):
            edge = current_node.get(key)
            if edge and edge.get("destination_node_id"):
                queue.append(edge["destination_node_id"])
    return seen


def main() -> None:
    """Patch the export named on the command line."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("export", help="Exported agent JSON from Retell.")
    parser.add_argument(
        "--token",
        help="RETELL_TOOL_TOKEN. Written into both tools' headers; the output "
        "then contains a secret and must not be committed.",
    )
    parser.add_argument(
        "--restore-fb05",
        action="store_true",
        help="Rebuild the trustworthiness question when the export omits it.",
    )
    parser.add_argument(
        "--prune",
        action="store_true",
        help="Also delete nodes that are attached to nothing.",
    )
    args = parser.parse_args()

    source = pathlib.Path(args.export).expanduser()
    agent = json.loads(source.read_text(encoding="utf-8"))
    flow = agent["conversationFlow"]

    changes = (
        fix_end_nodes(flow)
        + fix_q78(flow)
        + fix_feedback_battery(flow, args.restore_fb05)
        + fix_severed_anger(flow)
        + fix_multiselect(flow)
        + fix_option_counts(flow)
        + fix_tools(flow, args.token)
    )

    start = flow["start_node_id"]
    live = reachable(flow, start)

    # Everything the interview cannot lose. Checked after the edits rather
    # than before, because the edits move edges.
    for landmark, label in (
        ("fn-verify-code", "code verification"),
        ("fn-complete", "the completion function"),
        ("end-complete", "the completion node"),
        ("q-dpscr250", "Q78"),
    ):
        if landmark not in live:
            raise SystemExit(f"{label} is not reachable from {start}.")

    if FB05 in {n["id"] for n in flow["nodes"]} and FB05 not in live:
        raise SystemExit("fb05 exists but nothing reaches it.")

    orphans = sorted({n["id"] for n in flow["nodes"]} - live)
    if args.prune and orphans:
        flow["nodes"] = [n for n in flow["nodes"] if n["id"] in live]
        changes.append(f"pruned {len(orphans)} unattached node(s): {', '.join(orphans)}")
        orphans = []

    if not changes:
        print("Nothing to change; this export already has every fix.")
        return

    for change in changes:
        print(f"  {change}")
    if orphans:
        print(f"  note: attached to nothing, left in place: {', '.join(orphans)}")

    out = source.with_suffix(".fixed.json")
    out.write_text(json.dumps(agent, indent=2), encoding="utf-8")
    print(f"wrote {out}")
    if args.token:
        print("This file contains RETELL_TOOL_TOKEN. Do not commit it.")


if __name__ == "__main__":
    main()
