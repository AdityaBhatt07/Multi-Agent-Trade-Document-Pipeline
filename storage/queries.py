"""
Query layer.

Two parts:
1. A small, fixed set of parameterized query functions — these are the only
   things that ever actually touch the database. Reviewed, safe, predictable.
2. answer_natural_language_query() — uses an LLM purely for INTENT CLASSIFICATION
   (which fixed query to call, with what parameters), never to generate raw SQL.
   This is a deliberate safety/predictability tradeoff over open text-to-SQL.
"""
from __future__ import annotations
from datetime import datetime, timedelta
from sqlalchemy import func

from storage.db import get_session, ShipmentRecord


def count_flagged_in_last_n_days(days: int = 7, db_path: str = "nova_pipeline.db") -> int:
    session = get_session(db_path)
    try:
        cutoff = datetime.utcnow() - timedelta(days=days)
        return session.query(ShipmentRecord).filter(
            ShipmentRecord.action == "flag_for_review",
            ShipmentRecord.created_at >= cutoff,
        ).count()
    finally:
        session.close()


def list_runs_by_action(action: str, db_path: str = "nova_pipeline.db") -> list[dict]:
    session = get_session(db_path)
    try:
        rows = session.query(ShipmentRecord).filter(ShipmentRecord.action == action).all()
        return [
            {"run_id": r.run_id, "document_path": r.document_path,
             "customer_id": r.customer_id, "created_at": str(r.created_at)}
            for r in rows
        ]
    finally:
        session.close()


def list_runs_by_customer(customer_id: str, db_path: str = "nova_pipeline.db") -> list[dict]:
    session = get_session(db_path)
    try:
        rows = session.query(ShipmentRecord).filter(ShipmentRecord.customer_id == customer_id).all()
        return [
            {"run_id": r.run_id, "action": r.action, "created_at": str(r.created_at)}
            for r in rows
        ]
    finally:
        session.close()


def get_run_detail(run_id: str, db_path: str = "nova_pipeline.db") -> dict | None:
    session = get_session(db_path)
    try:
        r = session.query(ShipmentRecord).filter(ShipmentRecord.run_id == run_id).first()
        if not r:
            return None
        return {
            "run_id": r.run_id, "document_path": r.document_path, "action": r.action,
            "reasoning": r.reasoning, "overall_confidence": r.overall_confidence,
        }
    finally:
        session.close()


def total_run_counts(db_path: str = "nova_pipeline.db") -> dict:
    session = get_session(db_path)
    try:
        rows = session.query(ShipmentRecord.action, func.count(ShipmentRecord.run_id)).group_by(
            ShipmentRecord.action
        ).all()
        return {action: count for action, count in rows}
    finally:
        session.close()


# Registry of available query functions, exposed to the NL routing layer.
# Each entry: (function, description of when to use it, expected params)
QUERY_REGISTRY = {
    "count_flagged_in_last_n_days": {
        "fn": count_flagged_in_last_n_days,
        "description": "Count how many shipments were flagged for review in the last N days.",
        "params": {"days": "integer, number of days to look back, default 7"},
    },
    "list_runs_by_action": {
        "fn": list_runs_by_action,
        "description": "List all runs that resulted in a specific action.",
        "params": {"action": "one of: auto_approve, flag_for_review, draft_amendment"},
    },
    "list_runs_by_customer": {
        "fn": list_runs_by_customer,
        "description": "List all runs for a specific customer_id.",
        "params": {"customer_id": "string customer identifier"},
    },
    "get_run_detail": {
        "fn": get_run_detail,
        "description": "Get full detail for a single run by its run_id.",
        "params": {"run_id": "string run identifier"},
    },
    "total_run_counts": {
        "fn": total_run_counts,
        "description": "Get a breakdown of how many runs ended in each action type, overall.",
        "params": {},
    },
}


def answer_natural_language_query(question: str, db_path: str = "nova_pipeline.db") -> str:
    """
    Routes a natural-language question to one of the fixed query functions
    above using an LLM for intent classification + parameter extraction only.

    NOTE: in this build, intent routing uses simple keyword matching as a
    network-independent fallback (since this environment can't reach the
    Gemini API — see README). The production version replaces the keyword
    matcher below with an LLM call that picks from QUERY_REGISTRY and
    extracts parameters via structured output, then executes the SAME fixed
    functions — the LLM never generates or runs raw SQL.
    """
    q = question.lower()

    if "flagged" in q and ("week" in q or "day" in q):
        days = 7
        count = count_flagged_in_last_n_days(days=days, db_path=db_path)
        return f"{count} shipment(s) were flagged for review in the last {days} days."

    if "pending" in q or "flag" in q:
        rows = list_runs_by_action("flag_for_review", db_path=db_path)
        return f"{len(rows)} shipment(s) are currently flagged for review: " + \
               ", ".join(r["run_id"][:8] for r in rows) if rows else "No shipments are currently flagged for review."

    if "approved" in q or "auto" in q:
        rows = list_runs_by_action("auto_approve", db_path=db_path)
        return f"{len(rows)} shipment(s) have been auto-approved."

    if "breakdown" in q or "how many" in q and "total" in q:
        counts = total_run_counts(db_path=db_path)
        return f"Run breakdown by decision: {counts}"

    return ("I couldn't confidently match that question to a known query type. "
            "Try asking about: flagged shipments this week, pending reviews, "
            "auto-approved counts, or a breakdown of all decisions.")
