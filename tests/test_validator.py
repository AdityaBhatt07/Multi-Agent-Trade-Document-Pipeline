"""
Unit tests for the Validator agent. Uses hand-constructed ExtractionResult
mocks — does NOT call the real Extractor. This proves Validator works in
isolation, per the assignment's "independently testable agents" requirement.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from models.schemas import ExtractionResult, ExtractedField
from agents.validator_agent import validate_extraction
from rules.customer_rules import CUSTOMER_RULES


def _mock_extraction(**overrides) -> ExtractionResult:
    """Builds a fully-matching baseline extraction, with any fields overridden."""
    base = {
        "consignee_name": ("Acme Imports Ltd", 0.95),
        "hs_code": ("8517.62", 0.95),
        "port_of_loading": ("Shenzhen, China", 0.95),
        "port_of_discharge": ("Mumbai (INNSA)", 0.95),
        "incoterms": ("FOB", 0.95),
        "description_of_goods": ("Network switches", 0.95),
        "gross_weight": ("412.5 kg", 0.95),
        "invoice_number": ("INV-001", 0.95),
    }
    base.update(overrides)
    fields = [
        ExtractedField(field_name=name, value=val, confidence=conf, source_snippet="mock")
        for name, (val, conf) in base.items()
    ]
    return ExtractionResult(document_type="commercial_invoice", fields=fields)


def test_fully_matching_case():
    extraction = _mock_extraction()
    result = validate_extraction(extraction, CUSTOMER_RULES)
    counts = result.count_by_status()
    assert counts["match"] == 8, f"Expected all 8 fields to match, got {counts}"
    assert counts["mismatch"] == 0
    assert counts["uncertain"] == 0


def test_clear_mismatch_wrong_hs_code():
    extraction = _mock_extraction(hs_code=("9999.99", 0.95))
    result = validate_extraction(extraction, CUSTOMER_RULES)
    hs_validation = next(fv for fv in result.field_validations if fv.field_name == "hs_code")
    assert hs_validation.status == "mismatch"
    assert hs_validation.found_value == "9999.99"
    assert "9999.99" in hs_validation.reason


def test_low_confidence_forces_uncertain_even_when_value_matches():
    # Value technically matches the rule, but confidence is below threshold —
    # must come out as "uncertain", NOT "match". This is the core trust test.
    extraction = _mock_extraction(consignee_name=("Acme Imports Ltd", 0.3))
    result = validate_extraction(extraction, CUSTOMER_RULES)
    consignee_validation = next(
        fv for fv in result.field_validations if fv.field_name == "consignee_name"
    )
    assert consignee_validation.status == "uncertain", (
        "A low-confidence field that happens to match the rule must be marked "
        "'uncertain', not silently approved as 'match'. This is the silent-"
        "approval failure mode the assignment explicitly warns against."
    )


if __name__ == "__main__":
    test_fully_matching_case()
    print("PASS: test_fully_matching_case")
    test_clear_mismatch_wrong_hs_code()
    print("PASS: test_clear_mismatch_wrong_hs_code")
    test_low_confidence_forces_uncertain_even_when_value_matches()
    print("PASS: test_low_confidence_forces_uncertain_even_when_value_matches")
