"""SQLite persistence for the Prolific-to-SMS study site.

Holds the linkage table that connects a Prolific submission to a Retell
conversation. That table is the only key tying an anonymous transcript back
to a participant, so it is deliberately kept here — inside infrastructure the
research team controls — rather than written into the transcript itself.

Four tables:

``participants``
    One row per Prolific submission: stage, issued code, chat id, and the
    salted hash of the phone number the messages arrived from.
``codes``
    One-time codes, their expiry, attempt count, and the conversation that
    redeemed them. Kept separate from ``participants`` so an expired or
    abandoned code can be audited without touching the participant row.
``attention_checks``
    One row per check per participant, keyed so a retried webhook or a
    duplicated function call cannot inflate the failure count.
``events``
    Append-only audit trail. Useful for reconstructing what happened to a
    participant who reports a problem, and for demonstrating to a review
    board that consent preceded data collection.

SQLite is used because the linkage table is small, the deployment is a
single process, and a single file is trivially backed up — which matters
more than throughput here, since losing this file makes every transcript
permanently unattributable.

Example
-------
    >>> import tempfile, os
    >>> path = os.path.join(tempfile.mkdtemp(), "study.db")
    >>> init_db(path)
    >>> p = create_participant("pid123", "study1", "session1")
    >>> p.stage is Stage.ARRIVED
    True
    >>> code = mint_code("pid123", ttl_seconds=3600)
    >>> len(code)
    5
    >>> redeem_code(code, "chat_abc")
    ('pid123', 'ok')
    >>> record_check("pid123", "ac1", passed=False)
    1
    >>> get_participant("pid123").checks_failed
    {'ac1'}
"""

from __future__ import annotations

import hashlib
import os
import secrets
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterator

DB_PATH = os.environ.get("STUDY_DB_PATH", "study.db")
PHONE_HASH_SALT = os.environ.get("PHONE_HASH_SALT", "change-me")

CODE_ALPHABET = "34679ACDEFHJKMNPRTVWXY"
CODE_LENGTH = 5

_connection: sqlite3.Connection | None = None
_write_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS participants (
    pid           TEXT PRIMARY KEY,
    study_id      TEXT,
    session_id    TEXT,
    stage         TEXT NOT NULL,
    code          TEXT UNIQUE,
    chat_id       TEXT,
    phone_hash    TEXT,
    consented_at  REAL,
    completed_at  REAL,
    created_at    REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS codes (
    code             TEXT PRIMARY KEY,
    pid              TEXT NOT NULL REFERENCES participants(pid),
    expires_at       REAL NOT NULL,
    attempts         INTEGER NOT NULL DEFAULT 0,
    redeemed_by_chat TEXT,
    created_at       REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS attention_checks (
    pid         TEXT NOT NULL REFERENCES participants(pid),
    check_id    TEXT NOT NULL,
    passed      INTEGER NOT NULL,
    recorded_at REAL NOT NULL,
    PRIMARY KEY (pid, check_id)
);

CREATE TABLE IF NOT EXISTS events (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    pid      TEXT,
    chat_id  TEXT,
    event    TEXT NOT NULL,
    detail   TEXT,
    at       REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_participants_chat ON participants(chat_id);
CREATE INDEX IF NOT EXISTS idx_events_pid ON events(pid);
"""


class Stage(str, Enum):
    """Ordered stages a participant passes through.

    ``COMPLETE`` and ``TIMED_OUT`` are both terminal and both reached from
    ``TEXTING``, but they mean opposite things. ``COMPLETE`` is written only
    by ``/api/complete``, which the agent calls from the node before its End
    node, so it means the participant reached the end of the interview.
    ``TIMED_OUT`` is written by the ``chat_ended`` webhook when the chat
    closed without that call: the participant texted STOP, or stopped
    replying and the twenty-four hour silence timer expired. Keeping them
    apart is what lets the linkage export distinguish a finished interview
    from an abandoned one.
    """

    ARRIVED = "arrived"
    CONSENTED = "consented"
    TEXTING = "texting"
    COMPLETE = "complete"
    TIMED_OUT = "timed_out"
    WITHDREW = "withdrew"


@dataclass
class Participant:
    """One Prolific submission, as reconstructed from the database.

    Attributes:
        pid: Prolific participant ID.
        study_id: Prolific study ID.
        session_id: Prolific session ID.
        stage: Current position in the flow.
        code: The one-time code issued at consent.
        chat_id: Retell chat ID, set once the code is redeemed.
        phone_hash: Salted hash of the phone number, never the number.
        consented_at: Unix timestamp of consent.
        completed_at: Unix timestamp of completion.
        checks_failed: Check identifiers recorded as failures.
        checks_seen: Check identifiers recorded at all, which distinguishes
            a check that was failed from one that never ran.
    """

    pid: str
    study_id: str | None = None
    session_id: str | None = None
    stage: Stage = Stage.ARRIVED
    code: str | None = None
    chat_id: str | None = None
    phone_hash: str | None = None
    consented_at: float | None = None
    completed_at: float | None = None
    checks_failed: set[str] = field(default_factory=set)
    checks_seen: set[str] = field(default_factory=set)


def init_db(path: str | None = None) -> None:
    """Open the database and create any missing tables.

    Enables write-ahead logging so a reader cannot block the request that
    is recording a participant's consent.

    Args:
        path: Database file path. Defaults to ``STUDY_DB_PATH``.
    """
    global _connection, DB_PATH
    if path is not None:
        DB_PATH = path
    _connection = sqlite3.connect(DB_PATH, check_same_thread=False)
    _connection.row_factory = sqlite3.Row
    _connection.execute("PRAGMA journal_mode=WAL")
    _connection.execute("PRAGMA foreign_keys=ON")
    _connection.executescript(SCHEMA)
    _connection.commit()


def connection() -> sqlite3.Connection:
    """Return the open connection, initialising on first use.

    Returns:
        The module-level SQLite connection.
    """
    if _connection is None:
        init_db()
    assert _connection is not None
    return _connection


def log_event(
    event: str,
    pid: str | None = None,
    chat_id: str | None = None,
    detail: str | None = None,
) -> None:
    """Append a row to the audit trail.

    Args:
        event: Short machine-readable label, e.g. ``"consent_given"``.
        pid: Prolific participant ID, when known.
        chat_id: Retell chat ID, when known.
        detail: Optional free text. Never put message content here.
    """
    with _write_lock:
        connection().execute(
            "INSERT INTO events (pid, chat_id, event, detail, at)"
            " VALUES (?, ?, ?, ?, ?)",
            (pid, chat_id, event, detail, time.time()),
        )
        connection().commit()


def hash_phone(number: str) -> str:
    """Return a salted hash of a phone number.

    The plaintext number is never written to any table. The hash still
    allows detecting that two sessions came from the same handset, which is
    the only property the study needs.

    Args:
        number: The E.164 number as delivered by the webhook.

    Returns:
        A hex digest.

    Example:
        >>> len(hash_phone("+15551234567"))
        64
    """
    return hashlib.sha256((PHONE_HASH_SALT + number).encode()).hexdigest()


def _row_to_participant(row: sqlite3.Row) -> Participant:
    """Build a Participant from a database row, loading its checks.

    Args:
        row: A row from ``participants``.

    Returns:
        The populated participant.
    """
    checks = connection().execute(
        "SELECT check_id, passed FROM attention_checks WHERE pid = ?", (row["pid"],)
    ).fetchall()
    return Participant(
        pid=row["pid"],
        study_id=row["study_id"],
        session_id=row["session_id"],
        stage=Stage(row["stage"]),
        code=row["code"],
        chat_id=row["chat_id"],
        phone_hash=row["phone_hash"],
        consented_at=row["consented_at"],
        completed_at=row["completed_at"],
        checks_failed={c["check_id"] for c in checks if not c["passed"]},
        checks_seen={c["check_id"] for c in checks},
    )


def get_participant(pid: str) -> Participant | None:
    """Fetch one participant by Prolific ID.

    Args:
        pid: Prolific participant ID.

    Returns:
        The participant, or ``None`` if not registered.
    """
    row = connection().execute(
        "SELECT * FROM participants WHERE pid = ?", (pid,)
    ).fetchone()
    return _row_to_participant(row) if row else None


def participant_by_chat(chat_id: str) -> Participant | None:
    """Fetch the participant bound to a Retell conversation.

    Args:
        chat_id: Retell chat or call ID.

    Returns:
        The participant, or ``None`` if the conversation is unrecognised.
    """
    row = connection().execute(
        "SELECT * FROM participants WHERE chat_id = ?", (chat_id,)
    ).fetchone()
    return _row_to_participant(row) if row else None


def create_participant(
    pid: str, study_id: str | None, session_id: str | None
) -> Participant:
    """Register a participant arriving from Prolific, or return the existing row.

    Re-entry never resets an existing participant, so a browser refresh
    cannot replay the study or mint a second code.

    Args:
        pid: Prolific participant ID.
        study_id: Prolific study ID.
        session_id: Prolific session ID.

    Returns:
        The participant, newly created or previously stored.
    """
    existing = get_participant(pid)
    if existing is not None:
        return existing
    with _write_lock:
        connection().execute(
            "INSERT INTO participants (pid, study_id, session_id, stage, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (pid, study_id, session_id, Stage.ARRIVED.value, time.time()),
        )
        connection().commit()
    log_event("arrived", pid=pid)
    return Participant(pid=pid, study_id=study_id, session_id=session_id)


def set_stage(pid: str, stage: Stage) -> None:
    """Advance a participant to a new stage.

    Args:
        pid: Prolific participant ID.
        stage: The stage to record.
    """
    now = time.time()
    with _write_lock:
        if stage is Stage.CONSENTED:
            connection().execute(
                "UPDATE participants SET stage = ?, consented_at = ? WHERE pid = ?",
                (stage.value, now, pid),
            )
        elif stage is Stage.COMPLETE:
            connection().execute(
                "UPDATE participants SET stage = ?, completed_at = ? WHERE pid = ?",
                (stage.value, now, pid),
            )
        else:
            connection().execute(
                "UPDATE participants SET stage = ? WHERE pid = ?", (stage.value, pid)
            )
        connection().commit()
    log_event(f"stage_{stage.value}", pid=pid)


def mint_code(pid: str, ttl_seconds: float) -> str:
    """Issue a one-time code and bind it to a participant.

    The alphabet excludes characters that are ambiguous when read off one
    screen and typed into another (0/O, 1/I/L, 5/S, 2/Z, 8/B).

    Args:
        pid: Prolific participant ID.
        ttl_seconds: Lifetime of the code.

    Returns:
        The issued code.
    """
    existing = get_participant(pid)
    if existing is not None and existing.code:
        return existing.code

    while True:
        code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
        taken = connection().execute(
            "SELECT 1 FROM codes WHERE code = ?", (code,)
        ).fetchone()
        if not taken:
            break

    now = time.time()
    with _write_lock:
        connection().execute(
            "INSERT INTO codes (code, pid, expires_at, created_at) VALUES (?, ?, ?, ?)",
            (code, pid, now + ttl_seconds, now),
        )
        connection().execute(
            "UPDATE participants SET code = ? WHERE pid = ?", (code, pid)
        )
        connection().commit()
    log_event("code_issued", pid=pid)
    return code


def redeem_code(code: str, chat_id: str | None, max_attempts: int = 5) -> tuple[
    str | None, str
]:
    """Validate a code and bind the conversation to its participant.

    Args:
        code: The normalized code the participant typed.
        chat_id: Retell chat ID claiming the code.
        max_attempts: Attempts allowed before the code is locked.

    Returns:
        A tuple of the Prolific ID (or ``None``) and a short reason string:
        ``"ok"``, ``"unknown"``, ``"expired"``, ``"used"``, or
        ``"too_many_attempts"``.
    """
    row = connection().execute("SELECT * FROM codes WHERE code = ?", (code,)).fetchone()
    if row is None:
        return None, "unknown"

    with _write_lock:
        connection().execute(
            "UPDATE codes SET attempts = attempts + 1 WHERE code = ?", (code,)
        )
        connection().commit()

    if row["attempts"] + 1 > max_attempts:
        return None, "too_many_attempts"
    if time.time() > row["expires_at"]:
        return None, "expired"
    if row["redeemed_by_chat"] and row["redeemed_by_chat"] != chat_id:
        return None, "used"

    with _write_lock:
        connection().execute(
            "UPDATE codes SET redeemed_by_chat = ? WHERE code = ?", (chat_id, code)
        )
        connection().execute(
            "UPDATE participants SET chat_id = ?, stage = ?"
            " WHERE pid = ? AND stage = ?",
            (chat_id, Stage.TEXTING.value, row["pid"], Stage.CONSENTED.value),
        )
        connection().commit()
    log_event("code_redeemed", pid=row["pid"], chat_id=chat_id)
    return row["pid"], "ok"


def record_check(pid: str, check_id: str, passed: bool) -> int:
    """Record the outcome of one attention check.

    Idempotent on ``(pid, check_id)``: a retried call overwrites rather
    than accumulating, so the failure count cannot be inflated by network
    retries or a duplicated function node.

    Args:
        pid: Prolific participant ID.
        check_id: Stable identifier for the check, e.g. ``"ac1"``.
        passed: Whether the participant answered correctly.

    Returns:
        The participant's total failure count after recording.
    """
    with _write_lock:
        connection().execute(
            "INSERT INTO attention_checks (pid, check_id, passed, recorded_at)"
            " VALUES (?, ?, ?, ?)"
            " ON CONFLICT(pid, check_id) DO UPDATE SET"
            " passed = excluded.passed, recorded_at = excluded.recorded_at",
            (pid, check_id, 1 if passed else 0, time.time()),
        )
        connection().commit()
    return failure_count(pid)


def failure_count(pid: str) -> int:
    """Count a participant's failed attention checks.

    Args:
        pid: Prolific participant ID.

    Returns:
        The number of checks recorded as failed.
    """
    row = connection().execute(
        "SELECT COUNT(*) AS n FROM attention_checks WHERE pid = ? AND passed = 0",
        (pid,),
    ).fetchone()
    return int(row["n"])


def set_phone_hash(pid: str, number: str) -> None:
    """Store the salted hash of a participant's phone number.

    Only written once; later messages from the same handset do not
    overwrite it.

    Args:
        pid: Prolific participant ID.
        number: The E.164 number from the webhook payload.
    """
    with _write_lock:
        connection().execute(
            "UPDATE participants SET phone_hash = ?"
            " WHERE pid = ? AND phone_hash IS NULL",
            (hash_phone(number), pid),
        )
        connection().commit()


def all_participants() -> Iterator[Participant]:
    """Iterate every participant, oldest first.

    Yields:
        Each stored participant.
    """
    rows = connection().execute(
        "SELECT * FROM participants ORDER BY created_at"
    ).fetchall()
    for row in rows:
        yield _row_to_participant(row)


def summary() -> dict[str, Any]:
    """Return counts by stage, for a quick health check during a pilot.

    Returns:
        A mapping of stage name to participant count, plus the total.
    """
    rows = connection().execute(
        "SELECT stage, COUNT(*) AS n FROM participants GROUP BY stage"
    ).fetchall()
    counts = {row["stage"]: int(row["n"]) for row in rows}
    counts["total"] = sum(counts.values())
    return counts
