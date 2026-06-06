from __future__ import annotations

import base64
import re
from pathlib import Path
from typing import Any

from . import database
from .agents import (
    CitizenSentimentAgent,
    CivicAgentGraph,
    PredictiveRiskAgent,
    ResourceAllocationAgent,
    run_monitoring,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
UPLOAD_DIR = PROJECT_ROOT / "data" / "uploads"


def sanitize_filename(value: str) -> str:
    name = re.sub(r"[^A-Za-z0-9_.-]+", "_", value or "evidence.jpg").strip("._")
    return name[:80] or "evidence.jpg"


def save_upload(image_data: str | None, image_name: str | None, complaint_seed: str = "upload") -> str | None:
    if not image_data:
        return None
    if "," in image_data and image_data.startswith("data:"):
        image_data = image_data.split(",", 1)[1]
    try:
        raw = base64.b64decode(image_data, validate=False)
    except Exception:
        return None
    if not raw:
        return None
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    filename = sanitize_filename(f"{complaint_seed}_{image_name or 'evidence.jpg'}")
    path = UPLOAD_DIR / filename
    path.write_bytes(raw)
    return str(path)


def submit_complaint(conn, payload: dict[str, Any]) -> dict[str, Any]:
    image_path = save_upload(payload.get("image_data"), payload.get("image_name"), payload.get("name") or "citizen")
    graph = CivicAgentGraph(conn)
    state = graph.process_submission(payload, image_path=image_path)

    citizen_id = database.create_citizen(
        conn,
        {
            "name": state["name"],
            "phone": state.get("phone"),
            "email": state.get("email"),
        },
    )
    now = database.utc_now()
    complaint = {
        "id": state["id"],
        "citizen_id": citizen_id,
        "description": state["description"],
        "location": state["location"],
        "ward": state.get("ward"),
        "category": state["category"],
        "issue_type": state["issue_type"],
        "severity": state["severity"],
        "priority_score": state["priority_score"],
        "priority_band": state["priority_band"],
        "status": state["status"],
        "assigned_department": state["assigned_department"],
        "assigned_officer": state["assigned_officer"],
        "expected_resolution_hours": state["expected_resolution_hours"],
        "duplicate_of": state.get("duplicate_of"),
        "duplicate_confidence": state.get("duplicate_confidence"),
        "image_path": image_path,
        "image_signal": state.get("image_signal"),
        "image_confidence": state.get("image_confidence") or 0,
        "citizen_message": state["citizen_message"],
        "created_at": now,
        "updated_at": now,
        "resolved_at": None,
    }
    database.insert_complaint(conn, complaint)
    database.record_assignment(conn, state["id"], state["assigned_department"], state["assigned_officer"])
    database.record_status(conn, state["id"], state["status"], state["citizen_message"])
    for item in state["agent_trace"]:
        database.record_agent_run(conn, state["id"], item["agent"], item["input"], item["output"])
    conn.commit()
    saved = database.get_complaint(conn, state["id"])
    return {"complaint": saved, "agent_trace": state["agent_trace"]}


def update_status(conn, complaint_id: str, status: str, note: str) -> dict[str, Any] | None:
    existing = database.get_complaint(conn, complaint_id)
    if not existing:
        return None
    database.update_complaint_status(conn, complaint_id, status, note or f"Status changed to {status}")
    conn.commit()
    return database.get_complaint(conn, complaint_id)


def submit_feedback(conn, complaint_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    existing = database.get_complaint(conn, complaint_id)
    if not existing:
        return None
    rating = max(1, min(5, int(payload.get("rating") or 3)))
    feedback = str(payload.get("feedback") or "").strip()
    agent = CitizenSentimentAgent()
    output = agent.run({"rating": rating, "feedback": feedback})
    database.record_feedback(
        conn,
        complaint_id,
        output["rating"],
        output["feedback"],
        output["sentiment"],
        output["confidence"],
    )
    database.record_agent_run(
        conn,
        complaint_id,
        agent.name,
        {"rating": rating, "feedback": feedback},
        output,
    )
    conn.commit()
    return {"complaint": database.get_complaint(conn, complaint_id), "sentiment": output}


def monitor(conn) -> dict[str, Any]:
    return run_monitoring(conn)


def snapshot(conn) -> dict[str, Any]:
    data = database.dashboard_snapshot(conn)
    risk_output = PredictiveRiskAgent(conn).run()
    allocation_output = ResourceAllocationAgent(conn).run()
    data["agent_flow"] = [
        "Complaint Understanding Agent",
        "Vision Verification Agent",
        "Classification Agent",
        "Duplicate Detection Agent",
        "Priority Scoring Agent",
        "Routing Agent",
        "Citizen Communication Agent",
        "Resolution Monitoring Agent",
        "Escalation Agent",
        "Transparency Report Agent",
        "Predictive Risk Agent",
        "Resource Allocation Agent",
        "Citizen Sentiment Agent",
    ]
    data["map_points"] = [map_point(item) for item in data["recent"]]
    data["predictive_risk"] = risk_output
    data["resource_allocation"] = allocation_output
    return data


def map_point(item: dict[str, Any]) -> dict[str, Any]:
    seed = sum(ord(char) for char in f"{item.get('location')} {item.get('ward')}")
    x = 12 + (seed % 78)
    y = 14 + ((seed // 7) % 72)
    return {
        **item,
        "x": x,
        "y": y,
    }
