"""
Minimal Streamlit UI for the trade document pipeline.
Shows: upload -> run -> extracted fields w/ confidence -> validation result ->
routing decision w/ reasoning -> NL query box over stored history.

Run with: streamlit run ui/app.py
"""
import sys
import os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st
from graph.pipeline_graph import run_pipeline
from storage.db import save_pipeline_state
from storage.queries import answer_natural_language_query

st.set_page_config(page_title="Nova Trade Doc Pipeline", layout="wide")
st.title("Trade Document Validation Pipeline")
st.caption("Extractor -> Validator -> Router, running live on the uploaded document.")

if os.environ.get("MOCK_EXTRACTOR") == "1":
    st.warning(
        "Running in MOCK_EXTRACTOR mode — extraction results are deterministic "
        "test fixtures, not a live Gemini call. Set MOCK_EXTRACTOR=0 and provide "
        "GEMINI_API_KEY to run real extraction.",
        icon="⚠️",
    )

uploaded_file = st.file_uploader("Upload a trade document (PDF or image)", type=["pdf", "png", "jpg", "jpeg"])

if uploaded_file is not None:
    temp_path = f"/tmp/{uploaded_file.name}"
    with open(temp_path, "wb") as f:
        f.write(uploaded_file.getbuffer())

    if st.button("Run Pipeline", type="primary"):
        with st.status("Running pipeline...", expanded=True) as status:
            st.write("Extracting fields...")
            final_state = run_pipeline(temp_path)
            st.write("Validating against customer rules...")
            st.write("Routing decision...")
            run_id = save_pipeline_state(final_state)
            status.update(label="Pipeline complete", state="complete")

        st.session_state["last_run"] = final_state

if "last_run" in st.session_state:
    state = st.session_state["last_run"]
    st.divider()
    st.subheader(f"Run {state.run_id[:8]} — status: {state.status}")

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("### Extracted Fields")
        if state.extraction_result:
            for f in state.extraction_result.fields:
                if f.confidence > 0.8:
                    badge = "🟢"
                elif f.confidence >= 0.5:
                    badge = "🟡"
                else:
                    badge = "🔴"
                st.write(f"{badge} **{f.field_name}**: `{f.value}` (confidence: {f.confidence:.2f})")
                if f.source_snippet:
                    st.caption(f"source: {f.source_snippet}")

    with col2:
        st.markdown("### Validation Result")
        if state.validation_result:
            for fv in state.validation_result.field_validations:
                icon = {"match": "✅", "mismatch": "❌", "uncertain": "❓"}[fv.status]
                st.write(f"{icon} **{fv.field_name}**: {fv.status}")
                if fv.status == "mismatch":
                    st.caption(f"found: {fv.found_value} | expected: {fv.expected_value}")
                st.caption(fv.reason)
            st.metric("Overall confidence", f"{state.validation_result.overall_confidence:.2f}")

    st.divider()
    st.markdown("### Routing Decision")
    if state.routing_decision:
        action_colors = {
            "auto_approve": "success",
            "flag_for_review": "warning",
            "draft_amendment": "info",
        }
        getattr(st, action_colors.get(state.routing_decision.action, "info"))(
            f"**Action: {state.routing_decision.action}**\n\n{state.routing_decision.reasoning}"
        )
        if state.routing_decision.amendment_draft:
            st.markdown("**Amendment draft:**")
            st.code(state.routing_decision.amendment_draft, language=None)

    if state.error_log:
        st.error("Errors logged during this run:\n" + "\n".join(state.error_log))

st.divider()
st.markdown("### Ask a question about stored shipments")
question = st.text_input("e.g. 'how many shipments were flagged this week?'")
if question:
    answer = answer_natural_language_query(question)
    st.info(answer)
