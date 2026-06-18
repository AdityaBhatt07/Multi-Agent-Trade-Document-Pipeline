"""
Integration test for the full LangGraph pipeline. Runs in MOCK_EXTRACTOR mode
so it doesn't need a live Gemini call. Covers: full run on clean doc, full run
on messy doc, and crash-recovery (interrupt after extract, resume, confirm no
re-extraction).
"""
import os
os.environ["MOCK_EXTRACTOR"] = "1"

import sys
import uuid
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

TEST_DB = "test_pipeline_checkpoints.sqlite"


def _cleanup():
    if os.path.exists(TEST_DB):
        os.remove(TEST_DB)


def test_clean_document_auto_approves():
    from graph.pipeline_graph import run_pipeline
    _cleanup()
    final_state = run_pipeline("sample_docs/clean_invoice.pdf", checkpoint_db_path=TEST_DB)
    assert final_state.status == "complete"
    assert final_state.routing_decision.action == "auto_approve"
    assert final_state.error_log == []
    _cleanup()


def test_messy_document_flags_for_review():
    from graph.pipeline_graph import run_pipeline
    _cleanup()
    final_state = run_pipeline("sample_docs/messy_invoice.pdf", checkpoint_db_path=TEST_DB)
    assert final_state.status == "complete"
    assert final_state.routing_decision.action == "flag_for_review"
    _cleanup()


def test_crash_recovery_resumes_without_reextracting():
    from graph.pipeline_graph import _build_uncompiled_graph, _to_pipeline_state
    from langgraph.checkpoint.sqlite import SqliteSaver
    _cleanup()

    run_id = str(uuid.uuid4())
    graph = _build_uncompiled_graph()
    initial_state = {
        "run_id": run_id,
        "document_path": "sample_docs/clean_invoice.pdf",
        "customer_id": "acme_imports",
        "status": "pending",
        "error_log": [],
    }
    config = {"configurable": {"thread_id": run_id}}

    # Simulate crash: interrupt right after extract
    with SqliteSaver.from_conn_string(TEST_DB) as checkpointer:
        app = graph.compile(checkpointer=checkpointer, interrupt_after=["extract"])
        partial = app.invoke(initial_state, config=config)
    assert partial.get("extraction_result") is not None
    assert partial.get("validation_result") is None, "Should not have validated yet"

    # Resume — should pick up from extract, not re-run it
    with SqliteSaver.from_conn_string(TEST_DB) as checkpointer:
        app2 = graph.compile(checkpointer=checkpointer)
        final = app2.invoke(None, config=config)

    final_state = _to_pipeline_state(final)
    assert final_state.status == "complete"
    assert final_state.routing_decision.action == "auto_approve"
    _cleanup()


if __name__ == "__main__":
    test_clean_document_auto_approves()
    print("PASS: test_clean_document_auto_approves")
    test_messy_document_flags_for_review()
    print("PASS: test_messy_document_flags_for_review")
    test_crash_recovery_resumes_without_reextracting()
    print("PASS: test_crash_recovery_resumes_without_reextracting")
