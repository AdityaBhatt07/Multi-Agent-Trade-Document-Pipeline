import os
os.environ["MOCK_EXTRACTOR"] = "1"

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

TEST_DB = "test_nova_pipeline.db"
TEST_CHECKPOINT_DB = "test_storage_checkpoints.sqlite"


def _cleanup():
    for f in [TEST_DB, TEST_CHECKPOINT_DB]:
        if os.path.exists(f):
            os.remove(f)


def test_save_and_query_round_trip():
    from graph.pipeline_graph import run_pipeline
    from storage.db import save_pipeline_state
    from storage.queries import total_run_counts, get_run_detail

    _cleanup()
    final_state = run_pipeline("sample_docs/clean_invoice.pdf", checkpoint_db_path=TEST_CHECKPOINT_DB)
    run_id = save_pipeline_state(final_state, db_path=TEST_DB)

    detail = get_run_detail(run_id, db_path=TEST_DB)
    assert detail is not None
    assert detail["action"] == "auto_approve"

    counts = total_run_counts(db_path=TEST_DB)
    assert counts.get("auto_approve") == 1
    _cleanup()


def test_nl_query_routes_to_correct_function():
    from graph.pipeline_graph import run_pipeline
    from storage.db import save_pipeline_state
    from storage.queries import answer_natural_language_query

    _cleanup()
    final_state = run_pipeline("sample_docs/messy_invoice.pdf", checkpoint_db_path=TEST_CHECKPOINT_DB)
    save_pipeline_state(final_state, db_path=TEST_DB)

    answer = answer_natural_language_query("show me pending reviews", db_path=TEST_DB)
    assert "1" in answer or "flagged" in answer.lower()
    _cleanup()


if __name__ == "__main__":
    test_save_and_query_round_trip()
    print("PASS: test_save_and_query_round_trip")
    test_nl_query_routes_to_correct_function()
    print("PASS: test_nl_query_routes_to_correct_function")
