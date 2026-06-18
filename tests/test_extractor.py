"""
Unit tests for the Extractor agent. Uses MOCK_EXTRACTOR=1 so these run without
a live Gemini call. Real-API verification is a separate manual step (see README).
"""
import os
os.environ["MOCK_EXTRACTOR"] = "1"

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.extractor_agent import extract_document
from models.schemas import REQUIRED_FIELDS


def test_clean_document_high_confidence():
    result = extract_document("sample_docs/clean_invoice.pdf")
    assert len(result.fields) == len(REQUIRED_FIELDS)
    high_conf_count = sum(1 for f in result.fields if f.confidence > 0.7)
    assert high_conf_count >= 6, (
        f"Expected at least 6 of 8 fields with confidence > 0.7 on the clean "
        f"document, got {high_conf_count}"
    )


def test_messy_document_surfaces_low_confidence():
    result = extract_document("sample_docs/messy_invoice.pdf")
    low_conf_fields = [f for f in result.fields if f.confidence < 0.5]
    assert len(low_conf_fields) >= 1, (
        "Expected at least one field with confidence < 0.5 on the messy document "
        "(the deliberately low-contrast consignee_name) — if this fails, the "
        "extractor is not surfacing low confidence and may be silently "
        "hallucinating instead."
    )
    consignee = result.get("consignee_name")
    assert consignee.confidence < 0.5, "consignee_name should be low-confidence on the messy doc"


def test_missing_field_returns_null_not_hallucinated():
    result = extract_document("sample_docs/messy_invoice.pdf")
    invoice_field = result.get("invoice_number")
    assert invoice_field.value is None, (
        "invoice_number is genuinely absent in the messy document — extractor "
        "must return None, not a hallucinated value."
    )
    assert invoice_field.confidence == 0.0


if __name__ == "__main__":
    test_clean_document_high_confidence()
    print("PASS: test_clean_document_high_confidence")
    test_messy_document_surfaces_low_confidence()
    print("PASS: test_messy_document_surfaces_low_confidence")
    test_missing_field_returns_null_not_hallucinated()
    print("PASS: test_missing_field_returns_null_not_hallucinated")
