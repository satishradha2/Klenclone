from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3


class UatReviewStore:
    """Append-only UAT review metadata stored outside the cloned business database."""

    def __init__(self, path: str) -> None:
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS discrepancy_proposals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    snapshot_name TEXT NOT NULL,
                    exception_id INTEGER NOT NULL,
                    proposal_version INTEGER NOT NULL,
                    resolution_code TEXT NOT NULL,
                    proposed_value_json TEXT NOT NULL,
                    rationale TEXT NOT NULL,
                    proposal_status TEXT NOT NULL CHECK (proposal_status = 'draft'),
                    proposed_by TEXT NOT NULL,
                    source_exception_fingerprint TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(snapshot_name, exception_id, proposal_version)
                );
                CREATE TABLE IF NOT EXISTS review_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    proposal_id INTEGER NOT NULL REFERENCES discrepancy_proposals(id),
                    actor TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    details_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS governance_assignments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    function_code TEXT NOT NULL,
                    assignment_version INTEGER NOT NULL,
                    display_name TEXT NOT NULL,
                    login_alias TEXT NOT NULL,
                    location_codes_json TEXT NOT NULL,
                    threshold_rule TEXT NOT NULL,
                    delegation_rule TEXT NOT NULL,
                    sod_exclusive INTEGER NOT NULL CHECK (sod_exclusive = 1),
                    assignment_status TEXT NOT NULL CHECK (assignment_status = 'draft_synthetic'),
                    created_by TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(function_code, assignment_version)
                );
                CREATE TABLE IF NOT EXISTS business_review_decisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    snapshot_name TEXT NOT NULL,
                    module_code TEXT NOT NULL,
                    package_sha256 TEXT NOT NULL,
                    decision_version INTEGER NOT NULL,
                    decision_code TEXT NOT NULL CHECK (decision_code IN (
                        'accepted_for_uat', 'conditionally_accepted_for_uat',
                        'rejected_for_uat', 'evidence_requested')),
                    rationale TEXT NOT NULL,
                    decided_by TEXT NOT NULL,
                    location_codes_json TEXT NOT NULL,
                    synthetic_only INTEGER NOT NULL CHECK (synthetic_only = 1),
                    production_signoff INTEGER NOT NULL CHECK (production_signoff = 0),
                    created_at TEXT NOT NULL,
                    UNIQUE(snapshot_name, module_code, package_sha256, decision_version)
                );
                CREATE TABLE IF NOT EXISTS business_review_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    decision_id INTEGER NOT NULL REFERENCES business_review_decisions(id),
                    event_type TEXT NOT NULL CHECK (event_type = 'uat_decision_recorded'),
                    actor TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    details_json TEXT NOT NULL
                );
                CREATE TRIGGER IF NOT EXISTS proposals_no_update
                BEFORE UPDATE ON discrepancy_proposals BEGIN
                    SELECT RAISE(ABORT, 'discrepancy proposals are append-only');
                END;
                CREATE TRIGGER IF NOT EXISTS proposals_no_delete
                BEFORE DELETE ON discrepancy_proposals BEGIN
                    SELECT RAISE(ABORT, 'discrepancy proposals are append-only');
                END;
                CREATE TRIGGER IF NOT EXISTS review_events_no_update
                BEFORE UPDATE ON review_events BEGIN
                    SELECT RAISE(ABORT, 'review events are append-only');
                END;
                CREATE TRIGGER IF NOT EXISTS review_events_no_delete
                BEFORE DELETE ON review_events BEGIN
                    SELECT RAISE(ABORT, 'review events are append-only');
                END;
                CREATE TRIGGER IF NOT EXISTS governance_assignments_no_update
                BEFORE UPDATE ON governance_assignments BEGIN
                    SELECT RAISE(ABORT, 'governance assignments are append-only');
                END;
                CREATE TRIGGER IF NOT EXISTS governance_assignments_no_delete
                BEFORE DELETE ON governance_assignments BEGIN
                    SELECT RAISE(ABORT, 'governance assignments are append-only');
                END;
                CREATE TRIGGER IF NOT EXISTS business_review_decisions_no_update
                BEFORE UPDATE ON business_review_decisions BEGIN
                    SELECT RAISE(ABORT, 'business review decisions are append-only');
                END;
                CREATE TRIGGER IF NOT EXISTS business_review_decisions_no_delete
                BEFORE DELETE ON business_review_decisions BEGIN
                    SELECT RAISE(ABORT, 'business review decisions are append-only');
                END;
                CREATE TRIGGER IF NOT EXISTS business_review_events_no_update
                BEFORE UPDATE ON business_review_events BEGIN
                    SELECT RAISE(ABORT, 'business review events are append-only');
                END;
                CREATE TRIGGER IF NOT EXISTS business_review_events_no_delete
                BEFORE DELETE ON business_review_events BEGIN
                    SELECT RAISE(ABORT, 'business review events are append-only');
                END;
            """)

    def add_proposal(self, *, snapshot_name: str, exception_id: int,
                     resolution_code: str, proposed_value: dict, rationale: str,
                     proposed_by: str, source_exception_fingerprint: str) -> dict:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as connection:
            version = connection.execute(
                "SELECT COALESCE(MAX(proposal_version), 0) + 1 FROM discrepancy_proposals "
                "WHERE snapshot_name=? AND exception_id=?",
                (snapshot_name, exception_id),
            ).fetchone()[0]
            cursor = connection.execute(
                "INSERT INTO discrepancy_proposals "
                "(snapshot_name, exception_id, proposal_version, resolution_code, proposed_value_json, "
                "rationale, proposal_status, proposed_by, source_exception_fingerprint, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, 'draft', ?, ?, ?)",
                (snapshot_name, exception_id, version, resolution_code,
                 json.dumps(proposed_value, separators=(",", ":"), sort_keys=True),
                 rationale, proposed_by, source_exception_fingerprint, now),
            )
            proposal_id = int(cursor.lastrowid)
            connection.execute(
                "INSERT INTO review_events (event_type, proposal_id, actor, occurred_at, details_json) "
                "VALUES ('proposal_created', ?, ?, ?, ?)",
                (proposal_id, proposed_by, now,
                 json.dumps({"resolution_code": resolution_code, "version": version},
                            separators=(",", ":"), sort_keys=True)),
            )
            row = connection.execute(
                "SELECT * FROM discrepancy_proposals WHERE id=?", (proposal_id,)).fetchone()
            return self._serialize(row)

    def proposals_for(self, snapshot_name: str, exception_ids: list[int]) -> dict[int, list[dict]]:
        if not exception_ids:
            return {}
        placeholders = ",".join("?" for _ in exception_ids)
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM discrepancy_proposals WHERE snapshot_name=? "
                f"AND exception_id IN ({placeholders}) ORDER BY exception_id, proposal_version DESC",
                [snapshot_name, *exception_ids],
            ).fetchall()
        result: dict[int, list[dict]] = {}
        for row in rows:
            result.setdefault(row["exception_id"], []).append(self._serialize(row))
        return result

    def add_governance_assignment(self, *, function_code: str, display_name: str,
                                  login_alias: str, location_codes: list[str],
                                  threshold_rule: str, delegation_rule: str,
                                  created_by: str = "system_design") -> dict:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as connection:
            version = connection.execute(
                "SELECT COALESCE(MAX(assignment_version), 0) + 1 FROM governance_assignments "
                "WHERE function_code=?", (function_code,)).fetchone()[0]
            cursor = connection.execute(
                "INSERT INTO governance_assignments "
                "(function_code, assignment_version, display_name, login_alias, location_codes_json, "
                "threshold_rule, delegation_rule, sod_exclusive, assignment_status, created_by, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 1, 'draft_synthetic', ?, ?)",
                (function_code, version, display_name, login_alias,
                 json.dumps(location_codes, separators=(",", ":")), threshold_rule,
                 delegation_rule, created_by, now),
            )
            return self._serialize_assignment(connection.execute(
                "SELECT * FROM governance_assignments WHERE id=?", (cursor.lastrowid,)).fetchone())

    def latest_governance_assignments(self) -> dict[str, dict]:
        with self._connect() as connection:
            rows = connection.execute("""
                SELECT item.* FROM governance_assignments item
                JOIN (
                    SELECT function_code, MAX(assignment_version) AS version
                    FROM governance_assignments GROUP BY function_code
                ) latest ON latest.function_code=item.function_code
                    AND latest.version=item.assignment_version
                ORDER BY item.function_code
            """).fetchall()
        return {row["function_code"]: self._serialize_assignment(row) for row in rows}

    def add_business_review_decision(self, *, snapshot_name: str, module_code: str,
                                     package_sha256: str, decision_code: str,
                                     rationale: str, decided_by: str,
                                     location_codes: list[str]) -> dict:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as connection:
            version = connection.execute(
                "SELECT COALESCE(MAX(decision_version), 0) + 1 FROM business_review_decisions "
                "WHERE snapshot_name=? AND module_code=? AND package_sha256=?",
                (snapshot_name, module_code, package_sha256),
            ).fetchone()[0]
            cursor = connection.execute(
                "INSERT INTO business_review_decisions "
                "(snapshot_name, module_code, package_sha256, decision_version, decision_code, "
                "rationale, decided_by, location_codes_json, synthetic_only, production_signoff, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, 0, ?)",
                (snapshot_name, module_code, package_sha256, version, decision_code, rationale,
                 decided_by, json.dumps(sorted(location_codes), separators=(",", ":")), now),
            )
            decision_id = int(cursor.lastrowid)
            connection.execute(
                "INSERT INTO business_review_events "
                "(decision_id, event_type, actor, occurred_at, details_json) "
                "VALUES (?, 'uat_decision_recorded', ?, ?, ?)",
                (decision_id, decided_by, now, json.dumps(
                    {"module_code": module_code, "decision_code": decision_code,
                     "production_signoff": False}, separators=(",", ":"), sort_keys=True)),
            )
            return self._serialize_business_review(connection.execute(
                "SELECT * FROM business_review_decisions WHERE id=?", (decision_id,)).fetchone())

    def latest_business_review_decisions(self, snapshot_name: str) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute("""
                SELECT item.* FROM business_review_decisions item
                JOIN (
                    SELECT snapshot_name, module_code, package_sha256,
                           MAX(decision_version) AS version
                    FROM business_review_decisions WHERE snapshot_name=?
                    GROUP BY snapshot_name, module_code, package_sha256
                ) latest ON latest.snapshot_name=item.snapshot_name
                    AND latest.module_code=item.module_code
                    AND latest.package_sha256=item.package_sha256
                    AND latest.version=item.decision_version
                ORDER BY item.module_code, item.created_at DESC
            """, (snapshot_name,)).fetchall()
        return [self._serialize_business_review(row) for row in rows]

    @staticmethod
    def _serialize(row: sqlite3.Row) -> dict:
        value = dict(row)
        value["proposed_value"] = json.loads(value.pop("proposed_value_json"))
        return value

    @staticmethod
    def _serialize_assignment(row: sqlite3.Row) -> dict:
        value = dict(row)
        value["location_codes"] = json.loads(value.pop("location_codes_json"))
        value["sod_exclusive"] = bool(value["sod_exclusive"])
        return value

    @staticmethod
    def _serialize_business_review(row: sqlite3.Row) -> dict:
        value = dict(row)
        value["location_codes"] = json.loads(value.pop("location_codes_json"))
        value["synthetic_only"] = bool(value["synthetic_only"])
        value["production_signoff"] = bool(value["production_signoff"])
        return value
