from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def get_db_path() -> Path:
    configured = os.getenv("CIVICAI_DB_PATH")
    if configured:
        return Path(configured)
    return PROJECT_ROOT / "data" / "civicai.db"


def connect(db_path: str | Path | None = None) -> sqlite3.Connection:
    path = Path(db_path) if db_path else get_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def rows_to_dicts(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]


def init_database(db_path: str | Path | None = None) -> None:
    conn = connect(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS citizens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                phone TEXT,
                email TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS departments (
                key TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                sla_hours INTEGER NOT NULL,
                escalation_role TEXT NOT NULL,
                contact TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS complaints (
                id TEXT PRIMARY KEY,
                citizen_id INTEGER NOT NULL,
                description TEXT NOT NULL,
                location TEXT NOT NULL,
                ward TEXT,
                category TEXT NOT NULL,
                issue_type TEXT NOT NULL,
                severity TEXT NOT NULL,
                priority_score INTEGER NOT NULL,
                priority_band TEXT NOT NULL,
                status TEXT NOT NULL,
                assigned_department TEXT NOT NULL,
                assigned_officer TEXT NOT NULL,
                expected_resolution_hours INTEGER NOT NULL,
                duplicate_of TEXT,
                duplicate_confidence REAL,
                image_path TEXT,
                image_signal TEXT,
                image_confidence REAL NOT NULL DEFAULT 0,
                citizen_message TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                resolved_at TEXT,
                FOREIGN KEY (citizen_id) REFERENCES citizens(id)
            );

            CREATE TABLE IF NOT EXISTS assignments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                complaint_id TEXT NOT NULL,
                department TEXT NOT NULL,
                officer TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (complaint_id) REFERENCES complaints(id)
            );

            CREATE TABLE IF NOT EXISTS status_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                complaint_id TEXT NOT NULL,
                status TEXT NOT NULL,
                note TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (complaint_id) REFERENCES complaints(id)
            );

            CREATE TABLE IF NOT EXISTS escalations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                complaint_id TEXT NOT NULL,
                level INTEGER NOT NULL,
                from_role TEXT NOT NULL,
                to_role TEXT NOT NULL,
                reason TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (complaint_id) REFERENCES complaints(id)
            );

            CREATE TABLE IF NOT EXISTS agent_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                complaint_id TEXT NOT NULL,
                agent_name TEXT NOT NULL,
                input_json TEXT NOT NULL,
                output_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (complaint_id) REFERENCES complaints(id)
            );

            CREATE TABLE IF NOT EXISTS procedures (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                issue_type TEXT NOT NULL,
                department TEXT NOT NULL,
                sop TEXT NOT NULL,
                priority_rules TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                complaint_id TEXT NOT NULL,
                rating INTEGER NOT NULL,
                feedback TEXT NOT NULL,
                sentiment TEXT NOT NULL,
                confidence REAL NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (complaint_id) REFERENCES complaints(id)
            );
            """
        )
        seed_departments(conn)
        seed_procedures(conn)
        conn.commit()
    finally:
        conn.close()


def seed_departments(conn: sqlite3.Connection) -> None:
    departments = [
        ("roads", "Roads Department", 72, "Municipal Engineer", "roads-desk@civicai.local"),
        ("water", "Water Supply Department", 48, "Water Works Officer", "water-desk@civicai.local"),
        ("electrical", "Electrical Department", 48, "Electrical Supervisor", "electrical-desk@civicai.local"),
        ("sanitation", "Sanitation Department", 36, "Sanitation Inspector", "sanitation-desk@civicai.local"),
        ("sewerage", "Sewerage Department", 24, "Sewerage Officer", "sewerage-desk@civicai.local"),
        ("traffic", "Traffic Management Department", 24, "Traffic Control Officer", "traffic-desk@civicai.local"),
        ("parks", "Parks Department", 96, "Parks Supervisor", "parks-desk@civicai.local"),
    ]
    conn.executemany(
        """
        INSERT OR IGNORE INTO departments(key, name, sla_hours, escalation_role, contact)
        VALUES (?, ?, ?, ?, ?)
        """,
        departments,
    )


def seed_procedures(conn: sqlite3.Connection) -> None:
    procedures = [
        (
            "pothole",
            "Roads Department",
            "Verify road hazard, dispatch ward road crew, barricade if critical, patch or resurface.",
            "Boost priority near schools, hospitals, bus stands, main roads, and accident reports.",
        ),
        (
            "water leakage",
            "Water Supply Department",
            "Isolate suspected pipe segment, dispatch leak team, protect public access, repair and restore supply.",
            "Boost priority for high-flow leakage, schools, hospitals, and affected citizens above 25.",
        ),
        (
            "garbage accumulation",
            "Sanitation Department",
            "Validate collection point, assign collection vehicle, clear waste, record before/after evidence.",
            "Boost priority for illegal dumping, market areas, schools, hospitals, and repeat locations.",
        ),
        (
            "sewage overflow",
            "Sewerage Department",
            "Dispatch jetting team, check manhole blockage, disinfect affected surface, verify flow restoration.",
            "Treat as critical when overflow enters road, residence, school, hospital, or water body.",
        ),
        (
            "broken streetlight",
            "Electrical Department",
            "Inspect pole and feeder, replace lamp/driver, verify night-time illumination.",
            "Boost priority near crossings, bus stops, schools, hospitals, and repeated safety complaints.",
        ),
        (
            "traffic signal issue",
            "Traffic Management Department",
            "Check controller, field wiring and power, deploy technician, coordinate manual traffic control if required.",
            "Treat as critical for junctions, peak-hour reports, accident mentions, and main-road disruption.",
        ),
    ]
    existing = conn.execute("SELECT COUNT(*) AS count FROM procedures").fetchone()["count"]
    if existing == 0:
        conn.executemany(
            """
            INSERT INTO procedures(issue_type, department, sop, priority_rules)
            VALUES (?, ?, ?, ?)
            """,
            procedures,
        )


def create_citizen(conn: sqlite3.Connection, citizen: dict[str, Any]) -> int:
    now = utc_now()
    conn.execute(
        "INSERT INTO citizens(name, phone, email, created_at) VALUES (?, ?, ?, ?)",
        (
            citizen.get("name") or "Anonymous Citizen",
            citizen.get("phone") or "",
            citizen.get("email") or "",
            now,
        ),
    )
    return int(conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"])


def insert_complaint(conn: sqlite3.Connection, complaint: dict[str, Any]) -> None:
    now = complaint.get("created_at") or utc_now()
    conn.execute(
        """
        INSERT INTO complaints(
            id, citizen_id, description, location, ward, category, issue_type,
            severity, priority_score, priority_band, status, assigned_department,
            assigned_officer, expected_resolution_hours, duplicate_of,
            duplicate_confidence, image_path, image_signal, image_confidence,
            citizen_message, created_at, updated_at, resolved_at
        )
        VALUES (
            :id, :citizen_id, :description, :location, :ward, :category, :issue_type,
            :severity, :priority_score, :priority_band, :status, :assigned_department,
            :assigned_officer, :expected_resolution_hours, :duplicate_of,
            :duplicate_confidence, :image_path, :image_signal, :image_confidence,
            :citizen_message, :created_at, :updated_at, :resolved_at
        )
        """,
        {
            **complaint,
            "created_at": now,
            "updated_at": complaint.get("updated_at") or now,
            "resolved_at": complaint.get("resolved_at"),
        },
    )


def record_assignment(conn: sqlite3.Connection, complaint_id: str, department: str, officer: str) -> None:
    conn.execute(
        "INSERT INTO assignments(complaint_id, department, officer, created_at) VALUES (?, ?, ?, ?)",
        (complaint_id, department, officer, utc_now()),
    )


def record_status(conn: sqlite3.Connection, complaint_id: str, status: str, note: str) -> None:
    conn.execute(
        "INSERT INTO status_history(complaint_id, status, note, created_at) VALUES (?, ?, ?, ?)",
        (complaint_id, status, note, utc_now()),
    )


def record_agent_run(
    conn: sqlite3.Connection,
    complaint_id: str,
    agent_name: str,
    input_payload: dict[str, Any],
    output_payload: dict[str, Any],
) -> None:
    conn.execute(
        """
        INSERT INTO agent_runs(complaint_id, agent_name, input_json, output_json, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            complaint_id,
            agent_name,
            json.dumps(input_payload, ensure_ascii=True, sort_keys=True),
            json.dumps(output_payload, ensure_ascii=True, sort_keys=True),
            utc_now(),
        ),
    )


def get_department_by_name(conn: sqlite3.Connection, name: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM departments WHERE name = ?", (name,)).fetchone()
    return row_to_dict(row)


def list_complaints(conn: sqlite3.Connection, limit: int = 100) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT c.*, citizens.name AS citizen_name, citizens.phone AS citizen_phone, citizens.email AS citizen_email
        FROM complaints c
        JOIN citizens ON citizens.id = c.citizen_id
        ORDER BY c.created_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return rows_to_dicts(rows)


def get_complaint(conn: sqlite3.Connection, complaint_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT c.*, citizens.name AS citizen_name, citizens.phone AS citizen_phone, citizens.email AS citizen_email
        FROM complaints c
        JOIN citizens ON citizens.id = c.citizen_id
        WHERE c.id = ?
        """,
        (complaint_id,),
    ).fetchone()
    complaint = row_to_dict(row)
    if complaint is None:
        return None
    complaint["history"] = rows_to_dicts(
        conn.execute(
            "SELECT status, note, created_at FROM status_history WHERE complaint_id = ? ORDER BY created_at ASC, id ASC",
            (complaint_id,),
        ).fetchall()
    )
    complaint["agent_runs"] = rows_to_dicts(
        conn.execute(
            "SELECT agent_name, input_json, output_json, created_at FROM agent_runs WHERE complaint_id = ? ORDER BY id ASC",
            (complaint_id,),
        ).fetchall()
    )
    complaint["escalations"] = rows_to_dicts(
        conn.execute(
            "SELECT level, from_role, to_role, reason, created_at FROM escalations WHERE complaint_id = ? ORDER BY level ASC, id ASC",
            (complaint_id,),
        ).fetchall()
    )
    complaint["feedback"] = rows_to_dicts(
        conn.execute(
            """
            SELECT rating, feedback, sentiment, confidence, created_at
            FROM feedback
            WHERE complaint_id = ?
            ORDER BY created_at DESC, id DESC
            """,
            (complaint_id,),
        ).fetchall()
    )
    return complaint


def update_complaint_status(conn: sqlite3.Connection, complaint_id: str, status: str, note: str) -> None:
    now = utc_now()
    resolved_at = now if status.lower() in {"resolved", "closed"} else None
    if resolved_at:
        conn.execute(
            "UPDATE complaints SET status = ?, updated_at = ?, resolved_at = ? WHERE id = ?",
            (status, now, resolved_at, complaint_id),
        )
    else:
        conn.execute(
            "UPDATE complaints SET status = ?, updated_at = ? WHERE id = ?",
            (status, now, complaint_id),
        )
    record_status(conn, complaint_id, status, note)


def open_complaints(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT * FROM complaints
        WHERE status NOT IN ('Resolved', 'Closed', 'Linked Duplicate')
        ORDER BY created_at ASC
        """
    ).fetchall()
    return rows_to_dicts(rows)


def duplicate_candidates(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, description, location, ward, issue_type, assigned_department, status,
               priority_score, expected_resolution_hours, created_at
        FROM complaints
        WHERE status NOT IN ('Resolved', 'Closed')
        ORDER BY created_at DESC
        LIMIT 200
        """
    ).fetchall()
    return rows_to_dicts(rows)


def count_escalations(conn: sqlite3.Connection, complaint_id: str) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS count FROM escalations WHERE complaint_id = ?",
        (complaint_id,),
    ).fetchone()
    return int(row["count"])


def create_escalation(
    conn: sqlite3.Connection,
    complaint_id: str,
    level: int,
    from_role: str,
    to_role: str,
    reason: str,
) -> None:
    now = utc_now()
    conn.execute(
        """
        INSERT INTO escalations(complaint_id, level, from_role, to_role, reason, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (complaint_id, level, from_role, to_role, reason, now),
    )
    conn.execute(
        "UPDATE complaints SET status = 'Escalated', updated_at = ? WHERE id = ?",
        (now, complaint_id),
    )
    record_status(conn, complaint_id, "Escalated", reason)


def record_feedback(
    conn: sqlite3.Connection,
    complaint_id: str,
    rating: int,
    feedback: str,
    sentiment: str,
    confidence: float,
) -> None:
    conn.execute(
        """
        INSERT INTO feedback(complaint_id, rating, feedback, sentiment, confidence, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (complaint_id, rating, feedback, sentiment, confidence, utc_now()),
    )


def feedback_summary(conn: sqlite3.Connection) -> dict[str, Any]:
    rows = rows_to_dicts(
        conn.execute(
            """
            SELECT rating, sentiment, confidence, created_at
            FROM feedback
            ORDER BY created_at DESC
            """
        ).fetchall()
    )
    if not rows:
        return {
            "citizen_satisfaction": None,
            "responses": 0,
            "positive": 0,
            "neutral": 0,
            "negative": 0,
            "average_rating": None,
        }
    positive = sum(1 for row in rows if row["sentiment"] == "Positive")
    neutral = sum(1 for row in rows if row["sentiment"] == "Neutral")
    negative = sum(1 for row in rows if row["sentiment"] == "Negative")
    average_rating = round(sum(int(row["rating"]) for row in rows) / len(rows), 1)
    satisfaction = round((positive + (0.5 * neutral)) / len(rows) * 100)
    return {
        "citizen_satisfaction": satisfaction,
        "responses": len(rows),
        "positive": positive,
        "neutral": neutral,
        "negative": negative,
        "average_rating": average_rating,
    }


def dashboard_snapshot(conn: sqlite3.Connection) -> dict[str, Any]:
    total = conn.execute("SELECT COUNT(*) AS count FROM complaints").fetchone()["count"]
    open_count = conn.execute(
        "SELECT COUNT(*) AS count FROM complaints WHERE status NOT IN ('Resolved', 'Closed', 'Linked Duplicate')"
    ).fetchone()["count"]
    escalated = conn.execute("SELECT COUNT(*) AS count FROM complaints WHERE status = 'Escalated'").fetchone()["count"]
    critical = conn.execute("SELECT COUNT(*) AS count FROM complaints WHERE priority_score >= 80").fetchone()["count"]

    by_department = rows_to_dicts(
        conn.execute(
            """
            SELECT assigned_department AS label, COUNT(*) AS value
            FROM complaints
            GROUP BY assigned_department
            ORDER BY value DESC
            """
        ).fetchall()
    )
    by_status = rows_to_dicts(
        conn.execute(
            """
            SELECT status AS label, COUNT(*) AS value
            FROM complaints
            GROUP BY status
            ORDER BY value DESC
            """
        ).fetchall()
    )
    trends = rows_to_dicts(
        conn.execute(
            """
            SELECT substr(created_at, 1, 10) AS label, COUNT(*) AS value
            FROM complaints
            GROUP BY substr(created_at, 1, 10)
            ORDER BY label ASC
            LIMIT 14
            """
        ).fetchall()
    )
    department_rankings = rows_to_dicts(
        conn.execute(
            """
            SELECT assigned_department AS department,
                   COUNT(*) AS total,
                   SUM(CASE WHEN status IN ('Resolved', 'Closed') THEN 1 ELSE 0 END) AS resolved,
                   SUM(CASE WHEN status = 'Escalated' THEN 1 ELSE 0 END) AS escalated,
                   ROUND(AVG(priority_score), 1) AS avg_priority
            FROM complaints
            GROUP BY assigned_department
            ORDER BY total DESC
            """
        ).fetchall()
    )
    recent = rows_to_dicts(
        conn.execute(
            """
            SELECT id, location, ward, issue_type, status, assigned_department, priority_score, created_at
            FROM complaints
            ORDER BY created_at DESC
            LIMIT 20
            """
        ).fetchall()
    )
    return {
        "kpis": {
            "total": total,
            "open": open_count,
            "escalated": escalated,
            "critical": critical,
        },
        "by_department": by_department,
        "by_status": by_status,
        "trends": trends,
        "department_rankings": department_rankings,
        "recent": recent,
        "feedback": feedback_summary(conn),
    }
