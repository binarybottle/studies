"""End-to-end exercise of the participant journey and the block flow."""

import json
import re
from collections import Counter

from app import assign, config
from app.store import get_store

WORDS = "I think this depends a great deal on the specific person and their particular circumstances here."
assert len(WORDS.split()) >= config.MIN_RESPONSE_WORDS


def arrive(client, pid="P1"):
    r = client.get(f"/start?PROLIFIC_PID={pid}&STUDY_ID=S&SESSION_ID=X")
    assert r.status_code == 303 and r.headers["location"] == f"/consent?pid={pid}"
    return pid


def consent(client, pid="P1"):
    arrive(client, pid)
    r = client.post(f"/consent?pid={pid}", data={"decision": "consent"})
    assert r.status_code == 303 and r.headers["location"] == f"/task?pid={pid}"
    return pid


def open_session(client, pid="P1"):
    consent(client, pid)
    r = client.post("/api/session", json={"pid": pid})
    assert r.status_code == 200, r.text
    return r.json()


def run_block(client, token, view):
    """Drive one block from its opening view to whatever comes after it."""
    while True:
        if view.get("done"):
            return view
        if view.get("awaiting_llm"):
            view = client.post(f"/api/session/{token}/llm").json()
            continue
        spec = view["input"]
        value = 55 if spec["type"] == "numeric" else (WORDS if spec["type"] == "text" else True)
        r = client.post(f"/api/session/{token}/submit", json={"step": spec["step"], "value": value})
        assert r.status_code == 200, r.text
        view = r.json()
        if spec["step"] == "gate":
            return view


# --- Prolific journey ---

def test_start_without_pid_is_explained(client):
    r = client.get("/start")
    assert r.status_code == 400 and "Prolific ID" in r.text


def test_reentry_resumes_by_stage(client):
    pid = consent(client)
    r = client.get(f"/start?PROLIFIC_PID={pid}")
    assert r.headers["location"] == f"/task?pid={pid}"


def test_decline_returns_to_prolific_with_screenout_code(client):
    pid = arrive(client)
    r = client.post(f"/consent?pid={pid}", data={"decision": "decline"})
    assert r.status_code == 303 and r.headers["location"].endswith("cc=CCNOPE")
    assert client.get(f"/start?PROLIFIC_PID={pid}").headers["location"] == f"/finish?pid={pid}"
    assert client.get(f"/finish?pid={pid}").headers["location"].endswith("cc=CCNOPE")


def test_task_before_consent_redirects(client):
    pid = arrive(client)
    assert client.get(f"/task?pid={pid}").headers["location"] == f"/consent?pid={pid}"
    assert client.post("/api/session", json={"pid": pid}).status_code == 409


def test_unknown_pid_is_a_page_not_a_stack_trace(client):
    assert client.get("/task?pid=NOBODY").status_code == 404
    assert client.post("/api/session", json={"pid": "NOBODY"}).status_code == 404


def test_task_page_carries_the_pid(client):
    pid = consent(client)
    r = client.get(f"/task?pid={pid}")
    assert r.status_code == 200 and f'data-pid="{pid}"' in r.text
    assert r.headers["cache-control"].startswith("no-store")


# --- full session ---

def test_full_session_ends_with_completion_code(client):
    pid = "P1"
    view = open_session(client, pid)
    token = view["session"]
    assert view["is_practice"] is True and view["input"]["step"] == "answer_1"
    assert view["resumed"] is False

    seen = []
    for _ in range(config.REAL_BLOCK_COUNT + 1):
        seen.append(view["block_index"])
        view = run_block(client, token, view)
        if view.get("done"):
            break
    assert view["done"] is True
    assert seen == list(range(0, config.REAL_BLOCK_COUNT + 1))

    assert client.get(f"/finish?pid={pid}").headers["location"].endswith("cc=CCDONE")
    assert client.get(f"/start?PROLIFIC_PID={pid}").headers["location"] == f"/finish?pid={pid}"
    assert client.post("/api/session", json={"pid": pid}).status_code == 409

    rows = get_store().block_rows(pid)
    assert len(rows) == config.REAL_BLOCK_COUNT + 1
    real = [dict(r) for r in rows if r["is_practice"] == "0"]
    assert Counter(r["category_label"] for r in real) == {c: 3 for c in {r["category_label"] for r in real}}
    assert Counter((r["category_label"], r["stance_label"]) for r in real).most_common(1)[0][1] == 1
    assert len({r["scenario_label"] for r in real}) == config.REAL_BLOCK_COUNT
    for r in real:
        assert r["llm_text_1"] and r["llm_text_2"] and r["activation_score"] == "55"


def test_finish_before_completion_explains(client):
    pid = consent(client)
    r = client.get(f"/finish?pid={pid}")
    assert r.status_code == 200 and "not finished" in r.text


# --- resume ---

def test_resume_replays_the_current_block(client):
    pid = "P1"
    view = open_session(client, pid)
    token = view["session"]
    client.post(f"/api/session/{token}/submit", json={"step": "answer_1", "value": 40})
    client.post(f"/api/session/{token}/submit", json={"step": "confidence_1", "value": 60})
    client.post(f"/api/session/{token}/submit", json={"step": "text_1", "value": WORDS})
    client.post(f"/api/session/{token}/llm")

    # A new process knows nothing: drop the in-memory session.
    from app import main
    main.sessions.clear()

    assert client.get(f"/api/status?pid={pid}").json()["stage"] == "in_task"
    r = client.post("/api/session", json={"pid": pid})
    assert r.status_code == 200
    view = r.json()
    assert view["resumed"] is True and view["session"] == token
    assert view["reset_transcript"] is True
    kinds = [m["kind"] for m in view["messages"]]
    assert kinds == ["interstitial", "scenario", "prompt", "user-numeric", "prompt", "user-numeric",
                     "prompt", "user-text", "llm"]
    assert view["input"]["step"] == "text_2"

    # And the flow continues from there.
    r = client.post(f"/api/session/{token}/submit", json={"step": "text_2", "value": WORDS})
    assert r.status_code == 200 and r.json()["awaiting_llm"]


def test_resume_mid_llm_turn_reruns_the_turn(client):
    pid = "P1"
    view = open_session(client, pid)
    token = view["session"]
    for step, value in (("answer_1", 40), ("confidence_1", 60), ("text_1", WORDS)):
        client.post(f"/api/session/{token}/submit", json={"step": step, "value": value})
    from app import main
    main.sessions.clear()
    view = client.post("/api/session", json={"pid": pid}).json()
    assert view["awaiting_llm"] is True
    view = client.post(f"/api/session/{token}/llm").json()
    assert view["input"]["step"] == "text_2"


def test_repeated_llm_request_is_harmless(client):
    """A refresh mid-thinking asks for the turn again; the second call must not
    run a second model turn or fail, just report where things are."""
    view = open_session(client)
    token = view["session"]
    for step, value in (("answer_1", 40), ("confidence_1", 60), ("text_1", WORDS)):
        client.post(f"/api/session/{token}/submit", json={"step": step, "value": value})
    first = client.post(f"/api/session/{token}/llm").json()
    second = client.post(f"/api/session/{token}/llm").json()
    assert first["input"]["step"] == second["input"]["step"] == "text_2"
    llm_msgs = [m for m in second["messages"] if m["kind"] == "llm"]
    assert len(llm_msgs) == 1 and llm_msgs[0]["text"] == first["messages"][0]["text"]


def test_double_submit_is_a_conflict(client):
    view = open_session(client)
    token = view["session"]
    assert client.post(f"/api/session/{token}/submit", json={"step": "answer_1", "value": 40}).status_code == 200
    assert client.post(f"/api/session/{token}/submit", json={"step": "answer_1", "value": 40}).status_code == 409


# --- input rules ---

def test_numeric_validation(client):
    token = open_session(client)["session"]
    for bad in ["", "abc", "50.5", "-1", "101"]:
        r = client.post(f"/api/session/{token}/submit", json={"step": "answer_1", "value": bad})
        assert r.status_code == 422, f"{bad!r} should have been rejected"
    assert client.post(f"/api/session/{token}/submit", json={"step": "answer_1", "value": "0"}).status_code == 200


def test_text_minimum_words(client):
    token = open_session(client)["session"]
    client.post(f"/api/session/{token}/submit", json={"step": "answer_1", "value": 40})
    client.post(f"/api/session/{token}/submit", json={"step": "confidence_1", "value": 60})
    r = client.post(f"/api/session/{token}/submit", json={"step": "text_1", "value": "too short"})
    assert r.status_code == 422 and "15 words" in r.json()["detail"]


def test_answer_1_prompt_is_templated(client):
    token = open_session(client)["session"]
    client.post(f"/api/session/{token}/submit", json={"step": "answer_1", "value": 73})
    view = client.post(f"/api/session/{token}/submit", json={"step": "confidence_1", "value": 60}).json()
    assert "73 out of 100" in view["messages"][0]["text"]


# --- the hidden manipulation stays hidden ---

def test_stance_never_reaches_the_client(client):
    view = open_session(client)
    token = view["session"]
    payloads = [json.dumps(view), json.dumps(client.get("/api/config").json())]
    for step, value in (("answer_1", 50), ("confidence_1", 50), ("text_1", WORDS)):
        payloads.append(json.dumps(client.post(f"/api/session/{token}/submit", json={"step": step, "value": value}).json()))
    payloads.append(json.dumps(client.post(f"/api/session/{token}/llm").json()))
    payloads.append(client.get("/task?pid=P1").text)

    blob = " ".join(payloads).lower()
    for term in ["aligning", "calibrated", "counterbalancing", "stance", "system_prompt", "assignment"]:
        assert not re.search(rf"\b{term}\b", blob), f"{term!r} leaked to the client"


def test_llm_reply_elicits_the_next_response_itself(client):
    token = open_session(client)["session"]
    client.post(f"/api/session/{token}/submit", json={"step": "answer_1", "value": 40})
    client.post(f"/api/session/{token}/submit", json={"step": "confidence_1", "value": 60})
    for step, next_step in (("text_1", "text_2"), ("text_2", "text_3")):
        view = client.post(f"/api/session/{token}/submit", json={"step": step, "value": WORDS}).json()
        assert view["awaiting_llm"]
        view = client.post(f"/api/session/{token}/llm").json()
        assert [m["kind"] for m in view["messages"]] == ["llm"]
        assert view["messages"][0]["text"].rstrip().endswith("?")
        assert len(view["messages"][0]["text"].split()) <= config.MAX_LLM_WORDS
        assert view["input"]["step"] == next_step and view["input"]["placeholder"]


# --- events ---

def test_client_events_are_allowlisted_and_trimmed(client):
    token = open_session(client)["session"]
    r = client.post(f"/api/session/{token}/event",
                    json={"event": "window_focus_lost", "detail": {"reason": "blur", "junk": {"a": 1}}})
    assert r.status_code == 200
    assert client.post(f"/api/session/{token}/event", json={"event": "arbitrary", "detail": {}}).status_code == 400
    rows = get_store()._conn.execute(
        "SELECT payload FROM events WHERE event = 'window_focus_lost'").fetchall()
    payload = json.loads(rows[-1]["payload"])
    assert payload["reason"] == "blur" and "junk" not in payload


# --- counterbalancing ---

def test_assignment_is_counterbalanced_across_twelve_participants(client):
    from app import main
    positions = {}  # (category, stance) -> Counter of positions
    for k in range(12):
        blocks = main.library.assignment(k)
        assert len(blocks) == 12
        assert len({(b["category"], b["stance"]) for b in blocks}) == 12
        assert len({b["scenario"] for b in blocks}) == 12
        for pos, b in enumerate(blocks):
            positions.setdefault((b["category"], b["stance"]), Counter())[pos] += 1
    # Every condition in every position exactly once across the cycle.
    for cond, counter in positions.items():
        assert counter == Counter(range(12)), cond


def test_scenarios_rotate_through_the_bank(client):
    from app import main
    n_per_category = min(len(main.library.scenarios_for(c)) for c in main.library.categories)
    cycle = n_per_category // 3
    used = Counter()
    for k in range(cycle):
        for b in main.library.assignment(k):
            used[b["scenario"]] += 1
    assert max(used.values()) == 1, "a scenario repeated before the bank was exhausted"


def test_williams_square_is_a_latin_square_balanced_for_carryover():
    n = 12
    square = assign.williams_square(n)
    for row in square:
        assert sorted(row) == list(range(n))
    for col in zip(*square):
        assert sorted(col) == list(range(n))
    pairs = Counter((row[i], row[i + 1]) for row in square for i in range(n - 1))
    assert max(pairs.values()) == 1 and len(pairs) == n * (n - 1)


def test_sequence_numbers_are_unique_and_stored(client):
    for pid in ("A", "B", "C"):
        consent(client, pid)
    store = get_store()
    indices = [store.get_participant(p).assignment_index for p in ("A", "B", "C")]
    assert indices == [0, 1, 2]
    a = store.get_participant("A")
    assert a.assignment == main_library_assignment(0)
    # Re-consenting (a refresh of the consent POST) keeps the same assignment.
    client.post("/consent?pid=A", data={"decision": "consent"})
    assert store.get_participant("A").assignment_index == 0


def main_library_assignment(k):
    from app import main
    return main.library.assignment(k)


# --- admin exports ---

def test_admin_exports_require_the_token(client):
    view = open_session(client)
    run_block(client, view["session"], view)
    assert client.get("/admin/blocks.csv?token=wrong").status_code == 404
    r = client.get("/admin/blocks.csv?token=test-admin-token")
    assert r.status_code == 200
    header, first, *_ = r.text.splitlines()
    assert header.startswith("participant_id,block_index,is_practice")
    assert first.startswith("P1,0,1,practice")
    r = client.get("/admin/participants.csv?token=test-admin-token")
    assert "P1" in r.text and "in_task" in r.text
    r = client.get("/admin/events/P1.jsonl?token=test-admin-token")
    assert "session_started" in r.text
