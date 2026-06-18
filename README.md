# Nova Trade Document Validation Pipeline — Part 1 POC

A multi-agent system (Extractor -> Validator -> Router) built on LangGraph,
Gemini, and SQLite, that extracts fields from trade documents, validates them
against a customer rule set, and decides what to do next.

## Architecture

```
Streamlit UI -> LangGraph orchestrator (Extractor -> Validator -> Router)
                -> SQLite checkpointer (crash recovery)
                -> SQLite storage (final results)
                -> NL query layer
```

Each agent (`agents/extractor_agent.py`, `agents/validator_agent.py`,
`agents/router_agent.py`) is independently testable with mocked inputs — see
`tests/`. The LangGraph wiring is in `graph/pipeline_graph.py`.

## Setup

```bash
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

You also need `poppler` installed system-side for PDF-to-image conversion
(used by the Extractor):
- Mac: `brew install poppler`
- Linux: `sudo apt-get install poppler-utils`

Create a `.env` file:
```
GEMINI_API_KEY=your_key_here
```
Get a free key at https://aistudio.google.com.

## Running with real extraction (live Gemini calls)

```bash
streamlit run ui/app.py
```
Upload `sample_docs/clean_invoice.pdf` or `sample_docs/messy_invoice.pdf`,
click "Run Pipeline."

## Running in mock mode (no API key needed, for testing pipeline logic)

```bash
MOCK_EXTRACTOR=1 streamlit run ui/app.py
```
This uses deterministic fixture data instead of a live Gemini call — useful
for testing the Validator/Router/storage/UI chain without burning API calls.
The UI displays a visible warning banner when running in this mode.

## Running the test suite

```bash
python3 tests/test_extractor.py
python3 tests/test_validator.py
python3 tests/test_router.py
python3 tests/test_pipeline_graph.py
python3 tests/test_storage.py
```
All 16 tests pass as of this build, verified directly (not just generated).

## A known, honest limitation in this build

This was built inside a sandboxed environment with restricted network egress
that could not reach `generativelanguage.googleapis.com` (confirmed via a
direct `x-deny-reason: host_not_allowed` response). Because of this:

1. The Extractor's real Gemini call path (`_extract_real` in
   `agents/extractor_agent.py`) is written and structurally correct, but was
   never executed against the live API during this build — only the mock
   path (`_extract_mock`) was actually run and tested here. **Run it yourself
   once with a real API key to confirm live extraction quality** — this is
   the one piece you should personally verify before submitting.
2. The NL query layer's `answer_natural_language_query()` currently uses
   keyword matching instead of an LLM-based intent router, for the same
   reason. The fixed query functions it routes to (`storage/queries.py`) are
   fully real and tested. Swapping the keyword matcher for a Gemini-based
   classifier is a small, well-contained change — the function signatures
   and the "never generate raw SQL" design are already in place.

Everything else — schemas, Extractor's confidence/hallucination logic
(verified via mock fixtures with real injected flaws), Validator,
Router, LangGraph wiring, crash recovery, storage, and the Streamlit UI —
was actually run and verified during this build, with real output captured
at each step.

## Sample documents

- `sample_docs/clean_invoice.pdf` — all 8 fields present, legible, matching
  the customer rule set.
- `sample_docs/messy_invoice.pdf` — deliberately flawed: faded/low-contrast
  consignee name (tests low-confidence handling), wrong HS code (tests
  mismatch detection), missing invoice number (tests the missing-field path),
  and a port name ("Nhava Sheva") that is the same real-world port as the
  expected value ("Mumbai (INNSA)") but won't string-match — a deliberate,
  documented limitation worth discussing in the technical write-up.

## Customer rule set

Defined in `rules/customer_rules.py` for one fictional customer ("Acme
Imports Ltd").
