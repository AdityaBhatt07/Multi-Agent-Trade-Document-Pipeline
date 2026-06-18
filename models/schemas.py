"""
Shared Pydantic schemas for the trade document validation pipeline.
Every agent reads/writes these typed models — no free-text passing between agents.
"""
from __future__ import annotations
from typing import Optional, List, Literal
from datetime import datetime
from uuid import uuid4
from pydantic import BaseModel, Field


REQUIRED_FIELDS = [
    "consignee_name",
    "hs_code",
    "port_of_loading",
    "port_of_discharge",
    "incoterms",
    "description_of_goods",
    "gross_weight",
    "invoice_number",
]


class ExtractedField(BaseModel):
    field_name: str
    value: Optional[str] = None
    confidence: float = Field(ge=0.0, le=1.0)
    source_snippet: Optional[str] = Field(
        default=None,
        description="Raw text/region the value was extracted from, for traceability.",
    )


class ExtractionResult(BaseModel):
    document_type: str
    fields: List[ExtractedField]
    extraction_timestamp: datetime = Field(default_factory=datetime.utcnow)

    def get(self, field_name: str) -> Optional[ExtractedField]:
        for f in self.fields:
            if f.field_name == field_name:
                return f
        return None


class FieldValidation(BaseModel):
    field_name: str
    status: Literal["match", "mismatch", "uncertain"]
    expected_value: Optional[str] = None
    found_value: Optional[str] = None
    reason: str  # required even for matches — explain why


class ValidationResult(BaseModel):
    field_validations: List[FieldValidation]
    overall_confidence: float = Field(ge=0.0, le=1.0)

    def count_by_status(self) -> dict:
        out = {"match": 0, "mismatch": 0, "uncertain": 0}
        for fv in self.field_validations:
            out[fv.status] += 1
        return out


class RoutingDecision(BaseModel):
    action: Literal["auto_approve", "flag_for_review", "draft_amendment"]
    reasoning: str
    amendment_draft: Optional[str] = None


class PipelineState(BaseModel):
    """Shared state object that flows through every LangGraph node."""
    run_id: str = Field(default_factory=lambda: str(uuid4()))
    document_path: str
    customer_id: str = "acme_imports"
    status: Literal[
        "pending", "extracting", "validating", "routing", "complete", "failed"
    ] = "pending"
    extraction_result: Optional[ExtractionResult] = None
    validation_result: Optional[ValidationResult] = None
    routing_decision: Optional[RoutingDecision] = None
    error_log: List[str] = Field(default_factory=list)

    class Config:
        arbitrary_types_allowed = True
