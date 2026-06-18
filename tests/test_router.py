"""
Unit tests for the Router agent. Uses hand-built mock ValidationResults —
does NOT depend on the Extractor or Validator running. Covers all three
possible actions plus the priority rule (uncertain beats mismatch).
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from models.schemas import ValidationResult, FieldValidation
from agents.router_agent import route_decision


def _mock_validation(statuses: list[str], overall_confidence: float) -> ValidationResult:
    fvs = []
    for i, status in enumerate(statuses):
        fvs.append(FieldValidation(
            field_name=f"field_{i}",
            status=status,
            expected_value="expected" if status == "mismatch" else None,
            found_value="found" if status != "match" else "expected",
            reason=f"mock reason for {status}",
        ))
    return ValidationResult(field_validations=fvs, overall_confidence=overall_confidence)


def test_all_match_high_confidence_auto_approves():
    validation = _mock_validation(["match"] * 8, overall_confidence=0.95)
    decision = route_decision(validation)
    assert decision.action == "auto_approve"
    assert "auto-approve" in decision.reasoning.lower() or "auto_approve" in decision.reasoning.lower()


def test_uncertain_field_flags_for_review():
    validation = _mock_validation(["match", "match", "uncertain"], overall_confidence=0.6)
    decision = route_decision(validation)
    assert decision.action == "flag_for_review"
    assert "field_2" in decision.reasoning, "Reasoning should reference the specific uncertain field"


def test_mismatch_without_uncertain_drafts_amendment():
    validation = _mock_validation(["match", "mismatch"], overall_confidence=0.7)
    decision = route_decision(validation)
    assert decision.action == "draft_amendment"
    assert decision.amendment_draft is not None
    assert "field_1" in decision.amendment_draft


def test_uncertain_takes_priority_over_mismatch():
    # Mix of mismatch AND uncertain — uncertain must win, per the non-negotiable
    # trust rule: ambiguity is never auto-resolved just because other fields
    # have a clear (even if bad) answer.
    validation = _mock_validation(["mismatch", "uncertain"], overall_confidence=0.4)
    decision = route_decision(validation)
    assert decision.action == "flag_for_review", (
        "Uncertain must take priority over mismatch — a clear failure (mismatch) "
        "does not excuse leaving an unverified field (uncertain) unresolved."
    )


if __name__ == "__main__":
    test_all_match_high_confidence_auto_approves()
    print("PASS: test_all_match_high_confidence_auto_approves")
    test_uncertain_field_flags_for_review()
    print("PASS: test_uncertain_field_flags_for_review")
    test_mismatch_without_uncertain_drafts_amendment()
    print("PASS: test_mismatch_without_uncertain_drafts_amendment")
    test_uncertain_takes_priority_over_mismatch()
    print("PASS: test_uncertain_takes_priority_over_mismatch")
