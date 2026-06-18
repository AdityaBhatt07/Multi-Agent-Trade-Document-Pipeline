"""
Router / Decision Agent
------------------------
Reads a ValidationResult and decides one of three actions:
- auto_approve: all fields match, overall confidence is high
- flag_for_review: any field is uncertain (uncertain is NEVER silently resolved
  either direction — it always means a human looks at it)
- draft_amendment: there are mismatches but no uncertain fields, so we can
  confidently tell the supplier exactly what's wrong

The agent must explain its decision referencing specific fields, not just
emit a label.
"""
from __future__ import annotations

from models.schemas import ValidationResult, RoutingDecision

AUTO_APPROVE_CONFIDENCE_THRESHOLD = 0.85


def _build_amendment_draft(validation: ValidationResult) -> str:
    mismatches = [fv for fv in validation.field_validations if fv.status == "mismatch"]
    lines = [
        "Subject: Amendment Required — Discrepancies Found in Submitted Documents",
        "",
        "The following field(s) do not match the customer's requirements and need correction:",
        "",
    ]
    for fv in mismatches:
        lines.append(
            f"  - {fv.field_name}: found '{fv.found_value}', expected '{fv.expected_value}'. "
            f"{fv.reason}"
        )
    lines.append("")
    lines.append("Please resubmit corrected documents at your earliest convenience.")
    return "\n".join(lines)


def _generate_reasoning(action: str, validation: ValidationResult) -> str:
    counts = validation.count_by_status()
    uncertain_fields = [fv.field_name for fv in validation.field_validations if fv.status == "uncertain"]
    mismatch_fields = [fv.field_name for fv in validation.field_validations if fv.status == "mismatch"]

    if action == "auto_approve":
        return (
            f"All {counts['match']} fields matched the customer's rule set with no "
            f"mismatches or uncertain values, and overall confidence ({validation.overall_confidence:.2f}) "
            f"exceeds the auto-approve threshold ({AUTO_APPROVE_CONFIDENCE_THRESHOLD}). "
            f"Safe to auto-approve without human review."
        )
    if action == "flag_for_review":
        return (
            f"Flagged for human review because the following field(s) could not be "
            f"confidently verified: {', '.join(uncertain_fields)}. Uncertain fields are "
            f"never auto-resolved in either direction — a human must confirm these "
            f"before this shipment can proceed, regardless of how many other fields matched."
        )
    # draft_amendment
    return (
        f"Drafted an amendment request because {len(mismatch_fields)} field(s) clearly "
        f"mismatched the customer's rules ({', '.join(mismatch_fields)}), and no fields "
        f"were uncertain, so we can state the required corrections with confidence "
        f"rather than needing a human to first resolve ambiguity."
    )


def route_decision(validation: ValidationResult) -> RoutingDecision:
    counts = validation.count_by_status()

    if counts["uncertain"] > 0:
        # Uncertain ALWAYS wins, regardless of mismatches present. Never silently
        # resolved either direction — this is the core trust rule of the system.
        action = "flag_for_review"
    elif counts["mismatch"] > 0:
        action = "draft_amendment"
    elif validation.overall_confidence >= AUTO_APPROVE_CONFIDENCE_THRESHOLD:
        action = "auto_approve"
    else:
        # All fields matched, but overall confidence is still below threshold —
        # conservative fallback: don't auto-approve on a technicality.
        action = "flag_for_review"

    reasoning = _generate_reasoning(action, validation)
    amendment_draft = _build_amendment_draft(validation) if action == "draft_amendment" else None

    return RoutingDecision(action=action, reasoning=reasoning, amendment_draft=amendment_draft)
