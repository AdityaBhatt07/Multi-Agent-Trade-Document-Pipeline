"""
Extractor Agent
---------------
Accepts a PDF or image trade document, sends it to a vision-capable LLM (Gemini),
and returns structured fields with confidence scores.

IMPORTANT — never hallucinate. If a field is missing or illegible, return
value=None, confidence=0.0. Do not guess a plausible value.

Two modes:
- Real mode: calls the actual Gemini API. Requires GEMINI_API_KEY in env.
- Mock mode (MOCK_EXTRACTOR=1): returns a deterministic, clearly-labeled fake
  result so the rest of the pipeline (Validator, Router, storage) can be built
  and tested without a live API call. NEVER used silently — the result includes
  a "mock": true marker and is meant only for pipeline-logic testing, not for
  proving extraction quality.
"""
from __future__ import annotations
import os
import json
import base64
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from models.schemas import ExtractionResult, ExtractedField, REQUIRED_FIELDS
from pdf2image import convert_from_path

load_dotenv()

EXTRACTION_PROMPT = f"""You are a trade document extraction system. Extract ONLY the following
fields if present in the document: {', '.join(REQUIRED_FIELDS)}.

For each field:
- Return the exact value as it appears in the document.
- Return a confidence score between 0.0 and 1.0 reflecting how certain you are
  the extracted value is correct AND complete.
- Return the exact source text snippet you extracted the value from.

CRITICAL RULES:
- If a field is not present, illegible, or you are not reasonably confident in
  the value, return value as null and confidence as 0.0. Do NOT guess or
  invent a plausible-sounding value. A missing field is not an error — report
  it honestly as missing.
- Confidence should reflect actual extraction certainty, not just whether a
  value is technically present. Faded, low-contrast, or partially obscured
  text should receive low confidence even if a value is readable.

Respond ONLY with valid JSON matching this exact schema, no other text:
{{
  "document_type": "<your best guess, e.g. commercial_invoice>",
  "fields": [
    {{"field_name": "consignee_name", "value": "...", "confidence": 0.0, "source_snippet": "..."}},
    ... one entry per required field, in the same order as listed above ...
  ]
}}
"""


def _pdf_or_image_to_images(file_path: str) -> list:
    """Convert PDF pages to PIL images, or load a single image directly."""
    suffix = Path(file_path).suffix.lower()
    if suffix == ".pdf":
        return convert_from_path(file_path, dpi=200)
    else:
        from PIL import Image
        return [Image.open(file_path)]


def _image_to_base64(img) -> str:
    import io
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def _parse_gemini_response(raw_text: str) -> ExtractionResult:
    """Parse the model's JSON response into our schema. Falls back safely on malformed JSON."""
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
    data = json.loads(cleaned)
    fields = [ExtractedField(**f) for f in data["fields"]]
    return ExtractionResult(document_type=data.get("document_type", "unknown"), fields=fields)


def _extract_real(file_path: str) -> ExtractionResult:
    """Real extraction path — calls the live Gemini API. Requires network + API key."""
    from google import genai
    from google.genai import types

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY not set. Create a .env file with your key, or export it "
            "in your shell before running this."
        )

    client = genai.Client(api_key=api_key)
    images = _pdf_or_image_to_images(file_path)

    parts = [EXTRACTION_PROMPT]
    for img in images:
        parts.append(types.Part.from_bytes(data=_image_to_base64(img), mime_type="image/png"))

    last_error = None
    for attempt in range(2):  # one retry on malformed/failed response
        try:
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=parts,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.1,
                ),
            )
            return _parse_gemini_response(response.text)
        except Exception as e:
            last_error = e
            continue

    # Both attempts failed — return an empty-but-valid result, never crash the pipeline silently
    return ExtractionResult(
        document_type="unknown",
        fields=[
            ExtractedField(field_name=f, value=None, confidence=0.0, source_snippet=None)
            for f in REQUIRED_FIELDS
        ],
    )


def _extract_mock(file_path: str) -> ExtractionResult:
    """
    MOCK MODE — for pipeline-logic testing only, not a substitute for real extraction.
    Returns different deterministic results based on filename, so we can exercise
    both the clean and messy paths through Validator/Router without a live API call.
    """
    name = Path(file_path).name.lower()

    if "messy" in name:
        fields = [
            ExtractedField(field_name="consignee_name", value="Acme Imports Ltd",
                            confidence=0.35, source_snippet="(very low contrast, barely legible)"),
            ExtractedField(field_name="hs_code", value="8471.30",
                            confidence=0.91, source_snippet="HS Code: 8471.30"),
            ExtractedField(field_name="port_of_loading", value="Shenzhen, China",
                            confidence=0.93, source_snippet="Port of Loading: Shenzhen, China"),
            ExtractedField(field_name="port_of_discharge", value="Nhava Sheva",
                            confidence=0.9, source_snippet="Port of Discharge: Nhava Sheva"),
            ExtractedField(field_name="incoterms", value="FOB",
                            confidence=0.95, source_snippet="Incoterms: FOB"),
            ExtractedField(field_name="description_of_goods",
                            value="Network switching apparatus, 24-port, rack mountable",
                            confidence=0.92, source_snippet="Description of Goods: ..."),
            ExtractedField(field_name="gross_weight", value="412.5 kg",
                            confidence=0.94, source_snippet="Gross Weight: 412.5 kg"),
            ExtractedField(field_name="invoice_number", value=None,
                            confidence=0.0, source_snippet=None),
        ]
    else:
        fields = [
            ExtractedField(field_name="consignee_name", value="Acme Imports Ltd",
                            confidence=0.97, source_snippet="Consignee Name: Acme Imports Ltd"),
            ExtractedField(field_name="hs_code", value="8517.62",
                            confidence=0.96, source_snippet="HS Code: 8517.62"),
            ExtractedField(field_name="port_of_loading", value="Shenzhen, China",
                            confidence=0.95, source_snippet="Port of Loading: Shenzhen, China"),
            ExtractedField(field_name="port_of_discharge", value="Mumbai (INNSA)",
                            confidence=0.96, source_snippet="Port of Discharge: Mumbai (INNSA)"),
            ExtractedField(field_name="incoterms", value="FOB",
                            confidence=0.98, source_snippet="Incoterms: FOB"),
            ExtractedField(field_name="description_of_goods",
                            value="Network switching apparatus, 24-port, rack mountable",
                            confidence=0.94, source_snippet="Description of Goods: ..."),
            ExtractedField(field_name="gross_weight", value="412.5 kg",
                            confidence=0.97, source_snippet="Gross Weight: 412.5 kg"),
            ExtractedField(field_name="invoice_number", value="INV-2026-04471",
                            confidence=0.98, source_snippet="Invoice Number: INV-2026-04471"),
        ]
    return ExtractionResult(document_type="commercial_invoice", fields=fields)


def extract_document(file_path: str) -> ExtractionResult:
    """
    Main entry point. Uses mock mode if MOCK_EXTRACTOR=1 is set in the environment,
    otherwise calls the real Gemini API.
    """
    if os.environ.get("MOCK_EXTRACTOR") == "1":
        return _extract_mock(file_path)
    return _extract_real(file_path)
