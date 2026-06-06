from __future__ import annotations

import math
import random
import re
import string
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

try:
    import numpy as np
    from PIL import Image
except Exception:  # pragma: no cover - runtime fallback for minimal Python installs
    Image = None
    np = None

from . import database
from .gemini import generate_json


ISSUE_RULES = [
    (
        "sewage overflow",
        "Sewerage",
        "Sewerage Department",
        ["sewage", "sewer", "drain overflow", "manhole", "waste water", "dirty water"],
    ),
    (
        "water leakage",
        "Water",
        "Water Supply Department",
        ["water leak", "water leakage", "pipe burst", "pipeline", "tap leaking", "water flowing", "water logging"],
    ),
    (
        "broken streetlight",
        "Electricity",
        "Electrical Department",
        ["streetlight", "street light", "lamp post", "light not working", "dark road", "pole light"],
    ),
    (
        "garbage accumulation",
        "Sanitation",
        "Sanitation Department",
        ["garbage", "trash", "waste", "dumping", "illegal dump", "overflowing bin", "debris"],
    ),
    (
        "traffic signal issue",
        "Traffic",
        "Traffic Management Department",
        ["traffic signal", "signal not working", "red light", "junction signal", "traffic light"],
    ),
    (
        "pothole",
        "Roads",
        "Roads Department",
        ["pothole", "road damage", "broken road", "crater", "bad road", "road cave", "road repair"],
    ),
    (
        "park maintenance",
        "Parks",
        "Parks Department",
        ["park", "playground", "fallen branch", "garden", "tree blocking", "bench broken"],
    ),
]

DEPARTMENT_KEYS = {
    "Roads Department": "roads",
    "Water Supply Department": "water",
    "Electrical Department": "electrical",
    "Sanitation Department": "sanitation",
    "Sewerage Department": "sewerage",
    "Traffic Management Department": "traffic",
    "Parks Department": "parks",
}

CRITICAL_LOCATIONS = [
    "school",
    "hospital",
    "clinic",
    "bus stand",
    "bus stop",
    "railway",
    "market",
    "main road",
    "junction",
    "bridge",
]

SEVERITY_HIGH_WORDS = [
    "danger",
    "accident",
    "injured",
    "overflow",
    "flood",
    "burst",
    "blocked",
    "emergency",
    "unsafe",
]

SEVERITY_MEDIUM_WORDS = ["large", "huge", "major", "several", "many", "spreading", "bad smell", "night"]
STOPWORDS = {
    "the",
    "and",
    "near",
    "road",
    "street",
    "there",
    "this",
    "that",
    "with",
    "from",
    "have",
    "been",
    "issue",
    "problem",
    "please",
    "urgent",
}

ESCALATION_CHAIN = [
    ("Ward Officer", "Municipal Engineer"),
    ("Municipal Engineer", "Zonal Commissioner"),
    ("Zonal Commissioner", "City Commissioner"),
]

STAFF_BASELINE = {
    "Roads Department": 10,
    "Water Supply Department": 12,
    "Electrical Department": 9,
    "Sanitation Department": 18,
    "Sewerage Department": 8,
    "Traffic Management Department": 7,
    "Parks Department": 6,
}

RISK_PREDICTIONS = {
    "water leakage": "Potential pipeline failure in next 14 days",
    "sewage overflow": "Possible sewer blockage cluster in next 7 days",
    "garbage accumulation": "Likely illegal dumping hotspot formation",
    "broken streetlight": "Night-time public safety risk may increase",
    "traffic signal issue": "Junction congestion and accident risk may rise",
    "pothole": "Road-surface failure cluster may expand after rain",
}


def complaint_id() -> str:
    token = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    return f"CIV-{day}-{token}"


def normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def tokenize(value: str) -> set[str]:
    tokens = re.findall(r"[a-z0-9]+", value.lower())
    return {token for token in tokens if token not in STOPWORDS and len(token) > 2}


def issue_from_text(text: str) -> tuple[str, str, str, float]:
    lower = text.lower()
    best = ("general civic issue", "Civic Operations", "Sanitation Department", 0.0)
    for issue_type, category, department, keywords in ISSUE_RULES:
        score = 0.0
        for keyword in keywords:
            if keyword in lower:
                score += 1.0 + min(len(keyword) / 24, 0.6)
        if score > best[3]:
            best = (issue_type, category, department, min(score / 2.2, 1.0))
    return best


def location_from_description(description: str, fallback: str) -> str:
    if fallback:
        return fallback
    match = re.search(
        r"(?:near|at|opposite|behind|beside|in front of)\s+([A-Za-z0-9 ,.-]{4,80})",
        description,
        flags=re.IGNORECASE,
    )
    if match:
        return match.group(1).strip(" ,.-")
    return "Location pending verification"


@dataclass
class AgentResult:
    agent: str
    input: dict[str, Any]
    output: dict[str, Any]


class BaseAgent:
    name = "Base Agent"

    def run(self, state: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    def input_summary(self, state: dict[str, Any]) -> dict[str, Any]:
        return {
            "complaint_id": state.get("id"),
            "description": state.get("description"),
            "location": state.get("location"),
            "ward": state.get("ward"),
            "issue_type": state.get("issue_type"),
            "severity": state.get("severity"),
        }


class ComplaintUnderstandingAgent(BaseAgent):
    name = "Complaint Understanding Agent"

    def run(self, state: dict[str, Any]) -> dict[str, Any]:
        description = normalize_text(state.get("description"))
        location = location_from_description(description, normalize_text(state.get("location")))
        combined = f"{description} {location}"

        llm_result = generate_json(
            "Extract a civic complaint as JSON with issue_type, category, location, severity. "
            f"Complaint: {combined}"
        )
        if llm_result:
            return {
                "issue_type": normalize_text(llm_result.get("issue_type")) or issue_from_text(combined)[0],
                "category": normalize_text(llm_result.get("category")) or issue_from_text(combined)[1],
                "location": normalize_text(llm_result.get("location")) or location,
                "severity": normalize_text(llm_result.get("severity")).lower() or "medium",
                "language": "llm-assisted",
                "understanding_confidence": float(llm_result.get("confidence", 0.82) or 0.82),
            }

        issue_type, category, department, confidence = issue_from_text(combined)
        lower = combined.lower()
        affected = int(state.get("affected_citizens") or 1)
        if any(word in lower for word in SEVERITY_HIGH_WORDS) or affected >= 50:
            severity = "high"
        elif any(word in lower for word in SEVERITY_MEDIUM_WORDS) or affected >= 10:
            severity = "medium"
        else:
            severity = "low" if confidence < 0.4 else "medium"
        if issue_type in {"sewage overflow", "traffic signal issue"} and affected >= 20:
            severity = "critical"

        return {
            "issue_type": issue_type,
            "category": category,
            "suggested_department": department,
            "location": location,
            "severity": severity,
            "language": "local-rule",
            "understanding_confidence": round(max(confidence, 0.52), 2),
        }


class VisionVerificationAgent(BaseAgent):
    name = "Vision Verification Agent"

    def run(self, state: dict[str, Any]) -> dict[str, Any]:
        image_path = state.get("image_path")
        if not image_path:
            return {
                "image_signal": "No image uploaded",
                "image_detected_issue": None,
                "image_confidence": 0.0,
                "vision_source": "not-applicable",
            }

        llm_result = generate_json(
            "Inspect this civic complaint image. Return JSON with detected_issue, confidence, evidence.",
            image_path=image_path,
        )
        if llm_result:
            return {
                "image_signal": normalize_text(llm_result.get("evidence")) or "Gemini vision evidence",
                "image_detected_issue": normalize_text(llm_result.get("detected_issue")) or None,
                "image_confidence": float(llm_result.get("confidence", 0.85) or 0.85),
                "vision_source": "gemini",
            }

        detected_from_name = issue_from_text(Path(image_path).name.replace("_", " "))[0]
        if detected_from_name != "general civic issue":
            return {
                "image_signal": f"Image filename contains evidence for {detected_from_name}",
                "image_detected_issue": detected_from_name,
                "image_confidence": 0.78,
                "vision_source": "local-filename",
            }

        if Image is None or np is None:
            return {
                "image_signal": "Image uploaded; local image libraries unavailable for inspection",
                "image_detected_issue": state.get("issue_type"),
                "image_confidence": 0.45,
                "vision_source": "local-unavailable",
            }

        try:
            img = Image.open(image_path).convert("RGB")
            img.thumbnail((256, 256))
            arr = np.asarray(img).astype("float32")
        except Exception:
            return {
                "image_signal": "Image upload stored, but could not be decoded",
                "image_detected_issue": state.get("issue_type"),
                "image_confidence": 0.35,
                "vision_source": "decode-failed",
            }

        red, green, blue = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
        brightness = arr.mean(axis=2)
        dark_ratio = float((brightness < 70).mean())
        blue_ratio = float(((blue > red + 20) & (blue > green + 10) & (brightness > 70)).mean())
        brown_green_ratio = float(((red > 75) & (green > 55) & (blue < 95) & (brightness < 150)).mean())
        variance = float(arr.std())

        issue_hint = state.get("issue_type") or "general civic issue"
        detected = issue_hint
        confidence = 0.55
        evidence = "Image uploaded and locally inspected"

        if blue_ratio > 0.08:
            detected = "water leakage"
            confidence = 0.72
            evidence = "Blue/reflective regions suggest water accumulation or leakage"
        elif dark_ratio > 0.28 and variance > 45:
            detected = "pothole" if issue_hint == "pothole" else "sewage overflow"
            confidence = 0.68
            evidence = "Dark irregular regions suggest road cavity, sewage, or stagnant hazard"
        elif brown_green_ratio > 0.22 and variance > 38:
            detected = "garbage accumulation"
            confidence = 0.66
            evidence = "Mixed brown/green textured regions suggest waste or dumping"
        elif issue_hint != "general civic issue":
            confidence = 0.58
            evidence = f"Image evidence is present and text indicates {issue_hint}"

        return {
            "image_signal": evidence,
            "image_detected_issue": detected,
            "image_confidence": round(confidence, 2),
            "vision_source": "local-image-heuristic",
        }


class ClassificationAgent(BaseAgent):
    name = "Classification Agent"

    def run(self, state: dict[str, Any]) -> dict[str, Any]:
        text_issue = state.get("issue_type", "general civic issue")
        vision_issue = state.get("image_detected_issue")
        image_confidence = float(state.get("image_confidence") or 0)
        chosen_issue = vision_issue if vision_issue and image_confidence >= 0.72 and text_issue == "general civic issue" else text_issue
        issue_type, category, department, confidence = issue_from_text(chosen_issue)
        if issue_type == "general civic issue":
            issue_type, category, department = text_issue, state.get("category", "Civic Operations"), state.get(
                "suggested_department", "Sanitation Department"
            )
        disagreement = bool(vision_issue and vision_issue != text_issue and image_confidence >= 0.65)
        return {
            "issue_type": issue_type,
            "category": category,
            "suggested_department": department,
            "classification_confidence": round(max(confidence, state.get("understanding_confidence", 0.55)), 2),
            "vision_text_disagreement": disagreement,
        }


class DuplicateDetectionAgent(BaseAgent):
    name = "Duplicate Detection Agent"

    def __init__(self, conn):
        self.conn = conn

    def run(self, state: dict[str, Any]) -> dict[str, Any]:
        candidates = database.duplicate_candidates(self.conn)
        current_tokens = tokenize(f"{state.get('description')} {state.get('location')}")
        best: dict[str, Any] | None = None
        best_score = 0.0
        current_text = f"{state.get('description')} {state.get('location')}".lower()
        for candidate in candidates:
            if candidate["id"] == state.get("id"):
                continue
            candidate_text = f"{candidate['description']} {candidate['location']}".lower()
            candidate_tokens = tokenize(candidate_text)
            union = current_tokens | candidate_tokens
            jaccard = len(current_tokens & candidate_tokens) / len(union) if union else 0
            sequence = SequenceMatcher(None, current_text, candidate_text).ratio()
            same_issue = 1.0 if candidate["issue_type"] == state.get("issue_type") else 0.0
            same_ward = 1.0 if (candidate.get("ward") and candidate.get("ward") == state.get("ward")) else 0.0
            location_similarity = SequenceMatcher(
                None,
                str(state.get("location", "")).lower(),
                str(candidate.get("location", "")).lower(),
            ).ratio()
            score = (0.35 * jaccard) + (0.25 * sequence) + (0.2 * same_issue) + (0.15 * location_similarity) + (
                0.05 * same_ward
            )
            if score > best_score:
                best_score = score
                best = candidate

        if best and best_score >= 0.66:
            return {
                "duplicate_of": best["id"],
                "duplicate_confidence": round(best_score, 2),
                "duplicate_reason": f"Similar {best['issue_type']} complaint already open at {best['location']}",
                "existing_department": best["assigned_department"],
                "existing_expected_resolution_hours": best["expected_resolution_hours"],
            }
        return {
            "duplicate_of": None,
            "duplicate_confidence": round(best_score, 2) if best else 0,
            "duplicate_reason": "No active duplicate crossed the similarity threshold",
        }


class PriorityScoringAgent(BaseAgent):
    name = "Priority Scoring Agent"

    def run(self, state: dict[str, Any]) -> dict[str, Any]:
        severity = str(state.get("severity") or "medium").lower()
        base = {"low": 24, "medium": 46, "high": 68, "critical": 84}.get(severity, 46)
        affected = max(1, int(state.get("affected_citizens") or 1))
        affected_boost = min(16, int(math.log2(affected + 1) * 3))
        text = f"{state.get('description')} {state.get('location')}".lower()
        location_boost = 12 if any(term in text for term in CRITICAL_LOCATIONS) else 0
        issue_boost = 10 if state.get("issue_type") in {"sewage overflow", "traffic signal issue", "water leakage"} else 0
        image_boost = min(8, int(float(state.get("image_confidence") or 0) * 8))
        disagreement_boost = 5 if state.get("vision_text_disagreement") else 0
        duplicate_adjustment = -10 if state.get("duplicate_of") else 0
        score = max(5, min(100, base + affected_boost + location_boost + issue_boost + image_boost + disagreement_boost + duplicate_adjustment))
        if score >= 80:
            band = "Critical"
        elif score >= 60:
            band = "High"
        elif score >= 35:
            band = "Medium"
        else:
            band = "Low"
        return {
            "priority_score": int(score),
            "priority_band": band,
            "priority_factors": {
                "severity": severity,
                "affected_citizens": affected,
                "critical_location": bool(location_boost),
                "high_risk_issue": bool(issue_boost),
                "image_confidence": state.get("image_confidence"),
                "duplicate_adjustment": duplicate_adjustment,
            },
        }


class RoutingAgent(BaseAgent):
    name = "Routing Agent"

    def __init__(self, conn):
        self.conn = conn

    def run(self, state: dict[str, Any]) -> dict[str, Any]:
        if state.get("duplicate_of") and state.get("existing_department"):
            department_name = state["existing_department"]
        else:
            department_name = state.get("suggested_department") or issue_from_text(state.get("issue_type", ""))[2]

        department = database.get_department_by_name(self.conn, department_name) or {
            "name": department_name,
            "sla_hours": 48,
            "escalation_role": "Ward Officer",
        }
        score = int(state.get("priority_score") or 50)
        base_sla = int(department.get("sla_hours") or 48)
        if score >= 85:
            expected = min(12, base_sla)
        elif score >= 70:
            expected = min(24, base_sla)
        elif score >= 50:
            expected = min(48, base_sla)
        else:
            expected = base_sla
        ward = state.get("ward") or "Central"
        officer = f"{department['name'].replace(' Department', '')} - Ward {ward} Desk"
        status = "Linked Duplicate" if state.get("duplicate_of") else "Assigned"
        return {
            "assigned_department": department["name"],
            "assigned_officer": officer,
            "expected_resolution_hours": int(state.get("existing_expected_resolution_hours") or expected),
            "status": status,
            "routing_reason": f"{state.get('issue_type')} mapped to {department['name']} with SLA {expected} hours",
        }


class CitizenCommunicationAgent(BaseAgent):
    name = "Citizen Communication Agent"

    def run(self, state: dict[str, Any]) -> dict[str, Any]:
        if state.get("duplicate_of"):
            message = (
                f"Your report is linked to existing complaint {state['duplicate_of']}. "
                f"The {state['assigned_department']} is already assigned and updates will be tracked here."
            )
        else:
            message = (
                f"Your complaint {state['id']} has been assigned to {state['assigned_department']}. "
                f"Expected resolution: {state['expected_resolution_hours']} hours. "
                f"Priority: {state['priority_band']} ({state['priority_score']}/100)."
            )
        return {"citizen_message": message}


class ResolutionMonitoringAgent(BaseAgent):
    name = "Resolution Monitoring Agent"

    def run(self, state: dict[str, Any]) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        assigned_at = state.get("created_at") or state.get("assigned_at") or database.utc_now()
        assigned_dt = datetime.fromisoformat(assigned_at)
        elapsed_hours = round((now - assigned_dt).total_seconds() / 3600, 1)
        sla = int(state.get("expected_resolution_hours") or 48)
        sla_breach = elapsed_hours > sla
        return {
            "ticket_id": state.get("id"),
            "assigned_at": assigned_dt.date().isoformat(),
            "elapsed_hours": elapsed_hours,
            "sla": sla,
            "sla_breach": sla_breach,
            "action": "escalate" if sla_breach else "continue_monitoring",
        }


class EscalationAgent(BaseAgent):
    name = "Escalation Agent"

    def __init__(self, conn):
        self.conn = conn

    def run(self, state: dict[str, Any]) -> dict[str, Any]:
        monitoring = state.get("monitoring_decision") or {}
        if not monitoring.get("sla_breach"):
            return {
                "current_level": "Ward Officer",
                "next_level": None,
                "reason": "SLA is still within the permitted window",
                "escalation_status": "Not Triggered",
            }

        current_count = database.count_escalations(self.conn, str(state.get("id")))
        if current_count >= len(ESCALATION_CHAIN):
            return {
                "current_level": ESCALATION_CHAIN[-1][1],
                "next_level": None,
                "reason": "Maximum escalation level already reached",
                "escalation_status": "Already At Highest Level",
            }

        current_level, next_level = ESCALATION_CHAIN[current_count]
        breach_by = round(float(monitoring["elapsed_hours"]) - float(monitoring["sla"]), 1)
        reason = f"SLA breached by {breach_by:g} hours"
        database.create_escalation(self.conn, str(state["id"]), current_count + 1, current_level, next_level, reason)
        return {
            "current_level": current_level,
            "next_level": next_level,
            "reason": reason,
            "escalation_status": "Triggered",
        }


class PredictiveRiskAgent(BaseAgent):
    name = "Predictive Risk Agent"

    def __init__(self, conn):
        self.conn = conn

    def run(self, state: dict[str, Any] | None = None) -> dict[str, Any]:
        rows = database.rows_to_dicts(
            self.conn.execute(
                """
                SELECT ward, issue_type, created_at, status
                FROM complaints
                WHERE status NOT IN ('Closed')
                """
            ).fetchall()
        )
        now = datetime.now(timezone.utc)
        groups: dict[tuple[str, str], dict[str, Any]] = {}
        for row in rows:
            ward = row.get("ward") or "Central"
            issue_type = row["issue_type"]
            key = (ward, issue_type)
            created = datetime.fromisoformat(row["created_at"])
            bucket = groups.setdefault(
                key,
                {"ward": ward, "issue_type": issue_type, "current": 0, "previous": 0, "total": 0},
            )
            age_days = (now - created).total_seconds() / 86400
            bucket["total"] += 1
            if age_days <= 7:
                bucket["current"] += 1
            elif age_days <= 14:
                bucket["previous"] += 1

        risks: list[dict[str, Any]] = []
        for item in groups.values():
            current = int(item["current"])
            previous = int(item["previous"])
            total = int(item["total"])
            if total == 0:
                continue
            trend = "increasing" if current >= previous and total >= 2 else "stable"
            if current < previous:
                trend = "decreasing"
            high_risk_issue = item["issue_type"] in {"water leakage", "sewage overflow", "traffic signal issue"}
            if total >= 4 or (total >= 2 and high_risk_issue and trend == "increasing"):
                risk_level = "High"
            elif total >= 2 or high_risk_issue:
                risk_level = "Medium"
            else:
                risk_level = "Low"
            issue_key = f"{str(item['issue_type']).replace(' ', '_')}_reports"
            risks.append(
                {
                    "ward": item["ward"],
                    issue_key: total,
                    "issue_type": item["issue_type"],
                    "trend": trend,
                    "risk_level": risk_level,
                    "prediction": RISK_PREDICTIONS.get(item["issue_type"], "Civic service demand may increase"),
                }
            )

        rank = {"High": 3, "Medium": 2, "Low": 1}
        risks.sort(key=lambda row: (rank[row["risk_level"]], row.get("trend") == "increasing"), reverse=True)
        return {
            "generated_at": database.utc_now(),
            "risks": risks[:6],
            "summary": "Ward-level issue clusters analyzed for forward municipal risk.",
        }


class ResourceAllocationAgent(BaseAgent):
    name = "Resource Allocation Agent"

    def __init__(self, conn):
        self.conn = conn

    def run(self, state: dict[str, Any] | None = None) -> dict[str, Any]:
        rows = database.rows_to_dicts(
            self.conn.execute(
                """
                SELECT assigned_department AS department, COUNT(*) AS active_complaints
                FROM complaints
                WHERE status NOT IN ('Resolved', 'Closed', 'Linked Duplicate')
                GROUP BY assigned_department
                ORDER BY active_complaints DESC
                """
            ).fetchall()
        )
        allocations: list[dict[str, Any]] = []
        for row in rows:
            department = row["department"]
            active = int(row["active_complaints"])
            available = STAFF_BASELINE.get(department, 8)
            recommended = max(available, available + max(0, math.ceil(active / 10)))
            additional = max(0, recommended - available)
            recommendation = (
                f"Deploy {additional} additional technicians"
                if additional
                else "Current staffing is sufficient"
            )
            allocations.append(
                {
                    "department": department.replace(" Department", ""),
                    "active_complaints": active,
                    "available_staff": available,
                    "recommended_staff": recommended,
                    "recommendation": recommendation,
                }
            )
        return {
            "generated_at": database.utc_now(),
            "allocations": allocations,
            "summary": "Active workload converted into staffing recommendations.",
        }


class CitizenSentimentAgent(BaseAgent):
    name = "Citizen Sentiment Agent"

    def run(self, state: dict[str, Any]) -> dict[str, Any]:
        rating = int(state.get("rating") or 3)
        feedback = normalize_text(state.get("feedback")).lower()
        negative_terms = ["reopened", "not fixed", "again", "bad", "delay", "ignored", "same issue"]
        positive_terms = ["fixed", "resolved", "quick", "good", "thank", "satisfied"]
        if rating <= 2 or any(term in feedback for term in negative_terms):
            sentiment = "Negative"
            confidence = 0.91 if any(term in feedback for term in negative_terms) else 0.82
        elif rating >= 4 or any(term in feedback for term in positive_terms):
            sentiment = "Positive"
            confidence = 0.88 if any(term in feedback for term in positive_terms) else 0.8
        else:
            sentiment = "Neutral"
            confidence = 0.68
        return {
            "rating": rating,
            "feedback": state.get("feedback") or "",
            "sentiment": sentiment,
            "confidence": round(confidence, 2),
        }


class CivicAgentGraph:
    def __init__(self, conn):
        self.conn = conn

    def process_submission(self, payload: dict[str, Any], image_path: str | None = None) -> dict[str, Any]:
        state: dict[str, Any] = {
            "id": complaint_id(),
            "name": normalize_text(payload.get("name")) or "Anonymous Citizen",
            "phone": normalize_text(payload.get("phone")),
            "email": normalize_text(payload.get("email")),
            "description": normalize_text(payload.get("description")),
            "location": normalize_text(payload.get("location")),
            "ward": normalize_text(payload.get("ward")),
            "affected_citizens": int(payload.get("affected_citizens") or 1),
            "image_path": image_path,
        }
        agents: list[BaseAgent] = [
            ComplaintUnderstandingAgent(),
            VisionVerificationAgent(),
            ClassificationAgent(),
            DuplicateDetectionAgent(self.conn),
            PriorityScoringAgent(),
            RoutingAgent(self.conn),
            CitizenCommunicationAgent(),
        ]
        trace: list[AgentResult] = []
        for agent in agents:
            input_payload = agent.input_summary(state)
            output = agent.run(state)
            state.update(output)
            trace.append(AgentResult(agent=agent.name, input=input_payload, output=output))
        state["agent_trace"] = [
            {"agent": item.agent, "input": item.input, "output": item.output}
            for item in trace
        ]
        return state


def run_monitoring(conn) -> dict[str, Any]:
    decisions: list[dict[str, Any]] = []
    escalations: list[dict[str, Any]] = []
    monitoring_agent = ResolutionMonitoringAgent()
    escalation_agent = EscalationAgent(conn)
    for complaint in database.open_complaints(conn):
        monitoring_output = monitoring_agent.run(complaint)
        decisions.append(monitoring_output)
        database.record_agent_run(
            conn,
            complaint["id"],
            monitoring_agent.name,
            {"ticket_id": complaint["id"], "status": complaint["status"]},
            monitoring_output,
        )
        if monitoring_output["sla_breach"]:
            escalation_output = escalation_agent.run({**complaint, "monitoring_decision": monitoring_output})
            escalations.append({"ticket_id": complaint["id"], **escalation_output})
            database.record_agent_run(
                conn,
                complaint["id"],
                escalation_agent.name,
                monitoring_output,
                escalation_output,
            )
    conn.commit()
    return {
        "agent": "Resolution Monitoring Agent + Escalation Agent",
        "decisions": decisions,
        "escalations": escalations,
        "actions": escalations,
        "checked_open_complaints": len(decisions),
    }
