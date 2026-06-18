"""
Validator Agent
----------------
Takes an ExtractionResult and a customer rule set, produces a field-by-field
ValidationResult: match / mismatch / uncertain.

CRITICAL RULE: a field whose extraction confidence is below LOW_CONFIDENCE_THRESHOLD
must be marked "uncertain" even if its value happens to match the rule. A correct-
looking value extracted at low confidence is a coincidence, not a verified match —
treating it as a match would be a silent approval of something we can't actually
vouch for.

Uncertain must always surface. It is never silently resolved to match or mismatch.
"""
from __future__ import annotations
from typing import Optional

from models.schemas import ExtractionResult, ValidationResult, FieldValidation
from rules.customer_rules import CUSTOMER_RULES, LOW_CONFIDENCE_THRESHOLD


def _normalize(value: Optional[str]) -> str:
    """Loose normalization for comparison — lowercase, strip whitespace."""
    if value is None:
        return ""
    return value.strip().lower()


def _check_consignee_name(value: Optional[str], rules: dict) -> tuple[str, str]:
    expected = rules["expected_consignee_name"]
    if value is None:
        return "uncertain", f"consignee_name is missing from the document; expected '{expected}'."
    if _normalize(value) == _normalize(expected):
        return "match", f"Extracted consignee '{value}' matches expected '{expected}'."
    return "mismatch", f"Extracted consignee '{value}' does not match expected '{expected}'."


def _check_hs_code(value: Optional[str], rules: dict) -> tuple[str, str]:
    approved = rules["approved_hs_codes"]
    if value is None:
        return "uncertain", f"hs_code is missing from the document; expected one of {approved}."
    if value.strip() in approved:
        return "match", f"HS code '{value}' is in the approved list {approved}."
    return "mismatch", f"HS code '{value}' is NOT in the approved list {approved}."


def _check_incoterms(value: Optional[str], rules: dict) -> tuple[str, str]:
    allowed = rules["allowed_incoterms"]
    if value is None:
        return "uncertain", f"incoterms is missing from the document; expected one of {allowed}."
    if value.strip().upper() in allowed:
        return "match", f"Incoterms '{value}' is in the allowed list {allowed}."
    return "mismatch", f"Incoterms '{value}' is NOT in the allowed list {allowed}."


def _check_port_of_discharge(value: Optional[str], rules: dict) -> tuple[str, str]:
    expected = rules["expected_port_of_discharge"]
    if value is None:
        return "uncertain", f"port_of_discharge is missing; expected '{expected}'."
    # NOTE: deliberately simple exact-normalized-match here. A real-world port
    # name like "Nhava Sheva" vs "Mumbai (INNSA)" refers to the SAME port but
    # will NOT match this naive check — this is a known, documented limitation,
    # not a bug. See technical write-up: "nastiest failure modes" for why a
    # production system needs a port-code lookup table, not string matching.
    if _normalize(value) == _normalize(expected):
        return "match", f"Port of discharge '{value}' matches expected '{expected}'."
    return "mismatch", (
        f"Port of discharge '{value}' does not exactly match expected '{expected}'. "
        f"NOTE: this may be a false mismatch if '{value}' is a known alias/synonym "
        f"for the same port — naive string matching cannot tell. Flagging conservatively."
    )


def _check_presence_only(field_name: str, value: Optional[str]) -> tuple[str, str]:
    """For fields with no fixed business rule — just check presence."""
    if value is None:
        return "uncertain", f"{field_name} is missing from the document and has no fallback."
    return "match", f"{field_name} is present ('{value}'); no fixed rule to violate."


CHECKERS = {
    "consignee_name": _check_consignee_name,
    "hs_code": _check_hs_code,
    "incoterms": _check_incoterms,
    "port_of_discharge": _check_port_of_discharge,
}


def validate_extraction(extraction: ExtractionResult, rules: dict = None) -> ValidationResult:
    if rules is None:
        rules = CUSTOMER_RULES

    field_validations = []
    confidences_used = []

    for field in extraction.fields:
        name = field.field_name
        value = field.value
        confidence = field.confidence

        if name in CHECKERS:
            status, reason = CHECKERS[name](value, rules)
        else:
            status, reason = _check_presence_only(name, value)

        # Low-confidence override: even a rule-matching value cannot be trusted
        # as a confirmed match if the extraction itself was uncertain.
        if status == "match" and confidence < LOW_CONFIDENCE_THRESHOLD:
            status = "uncertain"
            reason = (
                f"Value '{value}' technically matches the expected rule, but "
                f"extraction confidence was only {confidence:.2f} (below the "
                f"{LOW_CONFIDENCE_THRESHOLD} threshold). Cannot treat a low-confidence "
                f"extraction as a verified match — surfacing as uncertain instead "
                f"of silently approving."
            )

        field_validations.append(FieldValidation(
            field_name=name,
            status=status,
            expected_value=rules.get(f"expected_{name}") or str(rules.get(f"approved_{name}s", "")) or None,
            found_value=value,
            reason=reason,
        ))
        if status == "match":
            confidences_used.append(confidence)

    # Overall confidence: average confidence of matched fields, penalized by
    # the proportion of fields that are NOT clean matches. Documented formula —
    # this is a deliberate, simple, explainable choice over something opaque.
    counts = {"match": 0, "mismatch": 0, "uncertain": 0}
    for fv in field_validations:
        counts[fv.status] += 1
    total = len(field_validations)
    match_ratio = counts["match"] / total if total else 0
    avg_match_confidence = sum(confidences_used) / len(confidences_used) if confidences_used else 0
    overall_confidence = round(avg_match_confidence * match_ratio, 3)

    return ValidationResult(
        field_validations=field_validations,
        overall_confidence=overall_confidence,
    )
