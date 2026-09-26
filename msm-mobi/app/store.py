"""SQLite persistence.

Three tables:

``participants``
    One row per Prolific submission: stage, the counterbalancing sequence
    number and the assignment it produced, and the session's serialized
    state. The state column is what lets a participant who refreshes, loses
    their connection, or comes back after a container restart pick up at the
    exact step they left, with the same plan.
``blocks``
    One wide row per block per participant, holding every value and timestamp
    the protocol calls for, plus the transcript of the LLM exchange. Wide
    because the schema is fixed and a flat row exports directly to an
    analysis-ready CSV.
``events``
    Append-only log of every step, submission, model call and client-side
    integrity event (focus loss, blocked paste), for reconstructing what
    happened to a participant who reports a problem.

Rows are written as the session progresses, not at the end, so an abandoned
run still leaves everything collected up to that point.

SQLite because the deployment is one process and one file is trivially
backed up. WAL mode with a busy timeout: reads never block the write that is
recording a participant's answer.
"""

from __future__ import annotations

import csv
import json
import logging
import secrets
import sqlite3
import threading
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Iterable

from . import config

log = logging.getLogger(__name__)


class Stage(str, Enum):
    """Ordered stages a participant passes through."""

    ARRIVED = "arrived"        # reached /start; consent not yet given
    CONSENTED = "consented"    # consent recorded; assignment issued
    IN_TASK = "in_task"        # opened the task at least once
    COMPLETE = "complete"      # finished block 12
    WITHDREW = "withdrew"      # declined at the consent page


@dataclass
class Participant:
    pid: str
    study_id: str | None
    prolific_session_id: str | None
    stage: Stage
    assignment_index: int | None
    assignment: list[dict[str, str]] | None
    session_token: str | None
    state: dict[str, Any] | None
    created_at: float
    consented_at: float | None
    started_at: float | None
    completed_at: float | None


# Per-block value columns, in the order the participant produces them.
BLOCK_VALUE_COLUMNS: tuple[str, ...] = (
    "scenario_shown_at",
    "answer_score_1", "answer_score_1_at",
    "confidence_score_1", "confidence_score_1_at",
    "user_text_1", "user_text_1_words", "user_text_1_at",
    "llm_text_1", "llm_text_1_raw", "llm_text_1_truncated", "llm_text_1_elicited",
    "llm_text_1_requested_at", "llm_text_1_received_at", "llm_text_1_latency_ms",
    "llm_text_1_model",
    "user_text_2", "user_text_2_words", "user_text_2_at",
    "llm_text_2", "llm_text_2_raw", "llm_text_2_truncated", "llm_text_2_elicited",
    "llm_text_2_requested_at", "llm_text_2_received_at", "llm_text_2_latency_ms",
    "llm_text_2_model",
    "user_text_3", "user_text_3_words", "user_text_3_at",
    "answer_score_2", "answer_score_2_at",
    "confidence_score_2", "confidence_score_2_at",
    "activation_score", "activation_score_at",
    "advanced_at",
)

BLOCK_META_COLUMNS: tuple[str, ...] = (
    "participant_id", "block_index", "is_practice",
    "category_label", "category_name",
    "scenario_label", "scenario_text", "question_text",
    "scale_low_label", "scale_high_label",
    "stance_label", "stance_name",
    "prompt_version",
)

_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS participants (
    pid                 TEXT PRIMARY KEY,
    study_id            TEXT,
    prolific_session_id TEXT,
    stage               TEXT NOT NULL,
    assignment_index    INTEGER UNIQUE,
    assignment          TEXT,
    session_token       TEXT UNIQUE,
    state               TEXT,
    app_version         TEXT,
    llm_model           TEXT,
    llm_provider        TEXT,
    created_at          REAL NOT NULL,
    consented_at        REAL,
    started_at          REAL,
    completed_at        REAL
);

CREATE TABLE IF NOT EXISTS blocks (
    {", ".join(f"{c} TEXT" for c in BLOCK_META_COLUMNS)},
    {", ".join(f"{c} TEXT" for c in BLOCK_VALUE_COLUMNS)},
    PRIMARY KEY (participant_id, block_index)
);

CREATE TABLE IF NOT EXISTS attention_checks (
    participant_id TEXT NOT NULL,
    check_id       TEXT NOT NULL,
    block_index    INTEGER,
    expected       INTEGER NOT NULL,
    given          INTEGER NOT NULL,
    passed         INTEGER NOT NULL,
    recorded_at    REAL NOT NULL,
    PRIMARY KEY (participant_id, check_id)
);

CREATE TABLE IF NOT EXISTS events (
    event_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    participant_id TEXT,
    block_index    INTEGER,
    event          TEXT NOT NULL,
    t_unix         REAL NOT NULL,
    t_iso          TEXT NOT NULL,
    payload        TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_participant ON events(participant_id, t_unix);
"""


class Store:
    def __init__(self, db_path: Path | None = None) -> None:
        self.path = Path(db_path or config.DB_PATH)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False, timeout=10)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("PRAGMA busy_timeout=10000")
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._add_missing_block_columns()
            self._conn.commit()

    def _add_missing_block_columns(self) -> None:
        """CREATE TABLE IF NOT EXISTS leaves an older ``blocks`` table alone, so
        a column added later would fail the first UPDATE that named it, on a
        participant. Columns are only ever added, so ADD COLUMN is the whole
        migration."""
        have = {r["name"] for r in self._conn.execute("PRAGMA table_info(blocks)")}
        for column in (*BLOCK_META_COLUMNS, *BLOCK_VALUE_COLUMNS):
            if column not in have:
                self._conn.execute(f"ALTER TABLE blocks ADD COLUMN {column} TEXT")
                log.info("Added missing column blocks.%s", column)

    # --- participants ---

    def _row_to_participant(self, row: sqlite3.Row) -> Participant:
        return Participant(
            pid=row["pid"],
            study_id=row["study_id"],
            prolific_session_id=row["prolific_session_id"],
            stage=Stage(row["stage"]),
            assignment_index=row["assignment_index"],
            assignment=json.loads(row["assignment"]) if row["assignment"] else None,
            session_token=row["session_token"],
            state=json.loads(row["state"]) if row["state"] else None,
            created_at=row["created_at"],
            consented_at=row["consented_at"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
        )

    def create_participant(self, pid: str, study_id: str | None, prolific_session_id: str | None) -> Participant:
        """Register a Prolific arrival, or return the existing record so that
        re-entry resumes rather than resets."""
        with self._lock:
            self._conn.execute(
                """INSERT OR IGNORE INTO participants (pid, study_id, prolific_session_id, stage, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (pid, study_id, prolific_session_id, Stage.ARRIVED.value, time.time()),
            )
            self._conn.commit()
        participant = self.get_participant(pid)
        assert participant is not None
        return participant

    def get_participant(self, pid: str) -> Participant | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM participants WHERE pid = ?", (pid,)).fetchone()
        return self._row_to_participant(row) if row else None

    def participant_by_token(self, token: str) -> Participant | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM participants WHERE session_token = ?", (token,)
            ).fetchone()
        return self._row_to_participant(row) if row else None

    def set_stage(self, pid: str, stage: Stage) -> None:
        stamp_column = {
            Stage.CONSENTED: "consented_at",
            Stage.IN_TASK: "started_at",
            Stage.COMPLETE: "completed_at",
        }.get(stage)
        with self._lock:
            if stamp_column:
                self._conn.execute(
                    f"UPDATE participants SET stage = ?, {stamp_column} = COALESCE({stamp_column}, ?) WHERE pid = ?",
                    (stage.value, time.time(), pid),
                )
            else:
                self._conn.execute("UPDATE participants SET stage = ? WHERE pid = ?", (stage.value, pid))
            self._conn.commit()

    def issue_assignment(self, pid: str, build: Any, **meta: Any) -> Participant:
        """Give a consenting participant the next sequence number and the
        blocks it produces.

        ``build(index)`` turns a sequence number into the label triplets; it
        is called inside the write lock so two participants consenting at the
        same instant cannot receive the same number. Idempotent: a participant
        who already holds an assignment keeps it.
        """
        with self._lock:
            row = self._conn.execute(
                "SELECT assignment_index FROM participants WHERE pid = ?", (pid,)
            ).fetchone()
            if row is None:
                raise KeyError(pid)
            if row["assignment_index"] is None:
                nxt = self._conn.execute(
                    "SELECT COALESCE(MAX(assignment_index), -1) + 1 FROM participants"
                ).fetchone()[0]
                self._conn.execute(
                    """UPDATE participants
                       SET assignment_index = ?, assignment = ?, session_token = ?,
                           app_version = ?, llm_model = ?, llm_provider = ?
                       WHERE pid = ?""",
                    (
                        nxt, json.dumps(build(nxt)), secrets.token_urlsafe(24),
                        meta.get("app_version"), meta.get("llm_model"), meta.get("llm_provider"),
                        pid,
                    ),
                )
                self._conn.commit()
        participant = self.get_participant(pid)
        assert participant is not None
        return participant

    def save_state(self, pid: str, state: dict[str, Any]) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE participants SET state = ? WHERE pid = ?",
                (json.dumps(state, ensure_ascii=False), pid),
            )
            self._conn.commit()

    def all_participants(self) -> list[Participant]:
        with self._lock:
            rows = list(self._conn.execute("SELECT * FROM participants ORDER BY created_at"))
        return [self._row_to_participant(r) for r in rows]

    def summary(self) -> dict[str, int]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT stage, COUNT(*) AS n FROM participants GROUP BY stage"
            ).fetchall()
        return {r["stage"]: r["n"] for r in rows}

    # --- attention checks ---

    def record_check(self, pid: str, check_id: str, block_index: int, expected: int, given: int) -> bool:
        """Record one instructed-response answer. Keyed per check so a
        replayed submission cannot count twice. Returns whether it passed."""
        passed = given == expected
        with self._lock:
            self._conn.execute(
                """INSERT OR IGNORE INTO attention_checks
                   (participant_id, check_id, block_index, expected, given, passed, recorded_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (pid, check_id, block_index, expected, given, int(passed), time.time()),
            )
            self._conn.commit()
        return passed

    def checks_for(self, pid: str) -> dict[str, bool]:
        """check id -> passed, for every check the participant answered."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT check_id, passed FROM attention_checks WHERE participant_id = ?", (pid,)
            ).fetchall()
        return {r["check_id"]: bool(r["passed"]) for r in rows}

    def failures_by_pid(self) -> dict[str, int]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT participant_id, SUM(1 - passed) AS failed FROM attention_checks GROUP BY participant_id"
            ).fetchall()
        return {r["participant_id"]: int(r["failed"]) for r in rows}

    # --- blocks ---

    def init_block(self, meta: dict[str, Any]) -> None:
        cols = [c for c in BLOCK_META_COLUMNS if c in meta]
        with self._lock:
            self._conn.execute(
                f"INSERT OR IGNORE INTO blocks ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                [_text(meta[c]) for c in cols],
            )
            self._conn.commit()

    def update_block(self, pid: str, block_index: int, values: dict[str, Any]) -> None:
        unknown = set(values) - set(BLOCK_VALUE_COLUMNS)
        if unknown:
            raise KeyError(f"Unknown block columns: {sorted(unknown)}")
        if not values:
            return
        assignments = ", ".join(f"{c} = ?" for c in values)
        with self._lock:
            self._conn.execute(
                f"UPDATE blocks SET {assignments} WHERE participant_id = ? AND block_index = ?",
                [*(_text(v) for v in values.values()), pid, str(block_index)],
            )
            self._conn.commit()

    def block_rows(self, pid: str) -> list[sqlite3.Row]:
        with self._lock:
            return list(
                self._conn.execute(
                    "SELECT * FROM blocks WHERE participant_id = ? ORDER BY CAST(block_index AS INTEGER)",
                    (pid,),
                )
            )

    # --- events ---

    def record_event(self, pid: str | None, block_index: int | None, event: str, payload: dict[str, Any] | None = None) -> None:
        wall = time.time()
        with self._lock:
            self._conn.execute(
                """INSERT INTO events (participant_id, block_index, event, t_unix, t_iso, payload)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    pid, block_index, event, wall, _iso(wall),
                    json.dumps(payload, ensure_ascii=False) if payload else None,
                ),
            )
            self._conn.commit()

    # --- export ---

    def export_blocks_csv(self, out: Any, pids: Iterable[str] | None = None) -> None:
        """One row per block, all metadata and values flat -- the analysis
        format. ``out`` is any text file object."""
        columns = [*BLOCK_META_COLUMNS, *BLOCK_VALUE_COLUMNS]
        with self._lock:
            if pids is None:
                rows = list(self._conn.execute("SELECT * FROM blocks"))
            else:
                ids = list(pids)
                rows = list(
                    self._conn.execute(
                        f"SELECT * FROM blocks WHERE participant_id IN ({', '.join('?' * len(ids))})", ids
                    )
                )
        rows.sort(key=lambda r: (r["participant_id"] or "", int(r["block_index"] or 0)))
        w = csv.DictWriter(out, fieldnames=columns)
        w.writeheader()
        for r in rows:
            w.writerow({c: r[c] for c in columns})

    PARTICIPANT_EXPORT_COLUMNS = (
        "pid", "study_id", "prolific_session_id", "stage", "assignment_index",
        "attention_seen", "attention_failed",
        "app_version", "llm_model", "llm_provider",
        "created_at", "consented_at", "started_at", "completed_at",
    )

    def export_participants_csv(self, out: Any) -> None:
        with self._lock:
            rows = list(self._conn.execute("SELECT * FROM participants ORDER BY created_at"))
            checks = self._conn.execute(
                "SELECT participant_id, COUNT(*) AS seen, SUM(1 - passed) AS failed "
                "FROM attention_checks GROUP BY participant_id"
            ).fetchall()
        by_pid = {c["participant_id"]: c for c in checks}
        w = csv.DictWriter(out, fieldnames=list(self.PARTICIPANT_EXPORT_COLUMNS))
        w.writeheader()
        for r in rows:
            c = by_pid.get(r["pid"])
            row = {col: r[col] for col in self.PARTICIPANT_EXPORT_COLUMNS if col in r.keys()}
            row["attention_seen"] = c["seen"] if c else 0
            row["attention_failed"] = c["failed"] if c else 0
            w.writerow(row)

    QUALITY_COLUMNS = (
        "pid", "stage", "blocks_completed", "total_minutes",
        "median_reply_words", "min_reply_words", "distinct_reply_ratio",
        "median_read_seconds", "min_read_seconds",
        "rating_sd", "unchanged_rating_share",
        "attention_failed",
        "focus_lost_seconds", "paste_blocked", "prompt_version",
    )

    def export_quality_csv(self, out: Any) -> None:
        """One row per participant with the signals a low-effort session
        leaves behind, so exclusion criteria are a filter rather than a
        transcript read. Nothing here is a verdict; a short reply can be a
        good one. The columns:

        median_reply_words / min_reply_words   over every free-text reply
        distinct_reply_ratio    unique reply texts / replies; near 1 is
                                normal, well below means the same sentence
                                was reused across blocks
        median_read_seconds / min_read_seconds  from the Scenario appearing
                                to Answer Score 1; a few seconds means the
                                scenario was not read
        rating_sd               spread of Answer Score 1 across blocks; 0 is
                                straight-lining
        attention_failed        instructed-response checks answered wrongly
        unchanged_rating_share  blocks where Answer Score 2 == Answer Score 1
        focus_lost_seconds      time the tab was hidden or unfocused
        paste_blocked           attempts to paste into a text box
        """
        import statistics

        def secs(a: str | None, b: str | None) -> float | None:
            if not a or not b:
                return None
            from datetime import datetime
            return (datetime.fromisoformat(b) - datetime.fromisoformat(a)).total_seconds()

        with self._lock:
            participants = list(self._conn.execute("SELECT * FROM participants ORDER BY created_at"))
            blocks = list(self._conn.execute("SELECT * FROM blocks WHERE is_practice = '0'"))
            events = list(self._conn.execute(
                "SELECT participant_id, event, payload FROM events "
                "WHERE event IN ('window_focus_regained', 'validation_blocked')"
            ))

        failed = self.failures_by_pid()
        by_pid: dict[str, list[sqlite3.Row]] = {}
        for b in blocks:
            by_pid.setdefault(b["participant_id"], []).append(b)
        focus: dict[str, float] = {}
        pastes: dict[str, int] = {}
        for e in events:
            payload = json.loads(e["payload"]) if e["payload"] else {}
            if e["event"] == "window_focus_regained":
                focus[e["participant_id"]] = focus.get(e["participant_id"], 0.0) + float(payload.get("unfocused_ms") or 0) / 1000
            elif payload.get("reason") == "paste_blocked":
                pastes[e["participant_id"]] = pastes.get(e["participant_id"], 0) + 1

        w = csv.DictWriter(out, fieldnames=list(self.QUALITY_COLUMNS))
        w.writeheader()
        for p in participants:
            rows = by_pid.get(p["pid"], [])
            done = [r for r in rows if r["activation_score"]]
            words = [int(r[f"user_text_{n}_words"]) for r in rows for n in (1, 2, 3) if r[f"user_text_{n}_words"]]
            texts = [r[f"user_text_{n}"].strip().lower() for r in rows for n in (1, 2, 3) if r[f"user_text_{n}"]]
            reads = [s for s in (secs(r["scenario_shown_at"], r["answer_score_1_at"]) for r in rows) if s is not None]
            first = [int(r["answer_score_1"]) for r in rows if r["answer_score_1"]]
            pairs = [(int(r["answer_score_1"]), int(r["answer_score_2"])) for r in rows if r["answer_score_1"] and r["answer_score_2"]]
            total = None
            if p["started_at"] and (p["completed_at"] or rows):
                end = p["completed_at"] or max(
                    (float(datetime_to_unix(r[c])) for r in rows for c in ("advanced_at", "activation_score_at") if r[c]),
                    default=None,
                )
                total = round((end - p["started_at"]) / 60, 1) if end else None
            w.writerow({
                "pid": p["pid"],
                "stage": p["stage"],
                "blocks_completed": len(done),
                "total_minutes": total,
                "median_reply_words": statistics.median(words) if words else None,
                "min_reply_words": min(words) if words else None,
                "distinct_reply_ratio": round(len(set(texts)) / len(texts), 2) if texts else None,
                "median_read_seconds": round(statistics.median(reads), 1) if reads else None,
                "min_read_seconds": round(min(reads), 1) if reads else None,
                "rating_sd": round(statistics.pstdev(first), 1) if len(first) > 1 else None,
                "unchanged_rating_share": round(sum(a == b for a, b in pairs) / len(pairs), 2) if pairs else None,
                "attention_failed": failed.get(p["pid"], 0),
                "focus_lost_seconds": round(focus.get(p["pid"], 0.0)),
                "paste_blocked": pastes.get(p["pid"], 0),
                "prompt_version": rows[0]["prompt_version"] if rows else None,
            })

    def export_events(self, out: Any, pid: str) -> None:
        with self._lock:
            rows = list(
                self._conn.execute(
                    "SELECT * FROM events WHERE participant_id = ? ORDER BY t_unix", (pid,)
                )
            )
        for r in rows:
            out.write(json.dumps(dict(r), ensure_ascii=False) + "\n")

    def close(self) -> None:
        with self._lock:
            self._conn.close()


def _text(v: Any) -> Any:
    """Every block column is TEXT so exports round-trip without type surprises."""
    if v is None:
        return None
    if isinstance(v, bool):
        return "1" if v else "0"
    return str(v)


def _iso(wall: float) -> str:
    from datetime import datetime, timezone

    return datetime.fromtimestamp(wall, tz=timezone.utc).isoformat(timespec="milliseconds")


def datetime_to_unix(iso: str) -> float:
    from datetime import datetime

    return datetime.fromisoformat(iso).timestamp()


_store: Store | None = None


def get_store() -> Store:
    global _store
    if _store is None:
        _store = Store()
    return _store
