from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["CIVICAI_DB_PATH"] = str(Path(tmp) / "civicai-test.db")
        from app import database
        from app import services

        database.init_database()
        conn = database.connect()
        try:
            first = services.submit_complaint(
                conn,
                {
                    "name": "Asha Kumar",
                    "phone": "+91 90000 00000",
                    "email": "asha@example.com",
                    "ward": "Central",
                    "location": "ABC Road near Government School",
                    "description": "Huge water leakage near ABC road affecting students at the school entrance.",
                    "affected_citizens": 42,
                },
            )
            complaint = first["complaint"]
            assert complaint["assigned_department"] == "Water Supply Department"
            assert complaint["priority_score"] >= 70
            assert len(first["agent_trace"]) == 7

            duplicate = services.submit_complaint(
                conn,
                {
                    "name": "Ravi",
                    "ward": "Central",
                    "location": "ABC Road near Government School",
                    "description": "Water leak is still flowing near ABC road school gate.",
                    "affected_citizens": 10,
                },
            )
            assert duplicate["complaint"]["duplicate_of"] == complaint["id"]

            status = services.update_status(conn, complaint["id"], "In Progress", "Crew dispatched")
            assert status and status["status"] == "In Progress"

            old_timestamp = (datetime.now(timezone.utc) - timedelta(hours=56)).replace(microsecond=0).isoformat()
            conn.execute(
                "UPDATE complaints SET created_at = ?, updated_at = ?, expected_resolution_hours = 48 WHERE id = ?",
                (old_timestamp, old_timestamp, complaint["id"]),
            )
            conn.commit()

            monitor = services.monitor(conn)
            assert monitor["decisions"][0]["sla_breach"] is True
            assert monitor["escalations"][0]["escalation_status"] == "Triggered"

            active_snapshot = services.snapshot(conn)
            assert active_snapshot["predictive_risk"]["risks"]
            assert active_snapshot["resource_allocation"]["allocations"]

            resolved = services.update_status(conn, complaint["id"], "Resolved", "Leak repaired")
            assert resolved and resolved["status"] == "Resolved"

            feedback = services.submit_feedback(
                conn,
                complaint["id"],
                {"rating": 2, "feedback": "Issue reopened after 2 days"},
            )
            assert feedback and feedback["sentiment"]["sentiment"] == "Negative"

            snapshot = services.snapshot(conn)
            assert snapshot["kpis"]["total"] == 2
            assert snapshot["by_department"]
            assert snapshot["predictive_risk"]["risks"]
            assert snapshot["feedback"]["citizen_satisfaction"] is not None
        finally:
            conn.close()
    print("CivicAI smoke test passed")


if __name__ == "__main__":
    main()
