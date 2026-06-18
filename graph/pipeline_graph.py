"""
LangGraph orchestration for the trade document pipeline.

Nodes: extract_node -> validate_node -> route_node
Each node wraps the corresponding agent, updates PipelineState.status, and
appends to error_log on failure rather than letting exceptions propagate
and corrupt downstream state.

State is checkpointed after every node via LangGraph's SqliteSaver, so a
crashed run can be resumed from the last completed node using the same
thread_id (we use the PipelineState.run_id as the thread_id) instead of
restarting from scratch and re-paying for a vision API call.
"""
from __future__ import annotations
import os
from typing import TypedDict, Optional

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.sqlite import SqliteSaver

from models.schemas import (
    PipelineState, ExtractionResult, ValidationResult, RoutingDecision
)
from agents.extractor_agent import extract_document
from agents.validator_agent import validate_extraction
from agents.router_agent import route_decision
from rules.customer_rules import CUSTOMER_RULES


# LangGraph's StateGraph wants a dict-like state schema for its internal
# diffing/merging. We use a TypedDict mirror of PipelineState's fields and
# convert to/from our Pydantic model inside each node, so the rest of the
# codebase keeps working with the validated Pydantic types.
class GraphState(TypedDict, total=False):
    run_id: str
    document_path: str
    customer_id: str
    status: str
    extraction_result: Optional[dict]
    validation_result: Optional[dict]
    routing_decision: Optional[dict]
    error_log: list


def extract_node(state: GraphState) -> GraphState:
    try:
        result = extract_document(state["document_path"])
        return {
            "status": "extracting",
            "extraction_result": result.model_dump(mode="json"),
        }
    except Exception as e:
        return {
            "status": "failed",
            "error_log": state.get("error_log", []) + [f"extract_node failed: {e}"],
        }


def validate_node(state: GraphState) -> GraphState:
    if state.get("status") == "failed":
        return {}  # pass through, do not attempt validation on failed state
    try:
        extraction = ExtractionResult(**state["extraction_result"])
        result = validate_extraction(extraction, CUSTOMER_RULES)
        return {
            "status": "validating",
            "validation_result": result.model_dump(mode="json"),
        }
    except Exception as e:
        return {
            "status": "failed",
            "error_log": state.get("error_log", []) + [f"validate_node failed: {e}"],
        }


def route_node(state: GraphState) -> GraphState:
    if state.get("status") == "failed":
        return {}
    try:
        validation = ValidationResult(**state["validation_result"])
        decision = route_decision(validation)
        return {
            "status": "complete",
            "routing_decision": decision.model_dump(mode="json"),
        }
    except Exception as e:
        return {
            "status": "failed",
            "error_log": state.get("error_log", []) + [f"route_node failed: {e}"],
        }


def _route_after_extract(state: GraphState) -> str:
    """Conditional edge: stop the graph early if extraction failed."""
    return END if state.get("status") == "failed" else "validate"


def _route_after_validate(state: GraphState) -> str:
    return END if state.get("status") == "failed" else "route"


def _build_uncompiled_graph() -> StateGraph:
    graph = StateGraph(GraphState)
    graph.add_node("extract", extract_node)
    graph.add_node("validate", validate_node)
    graph.add_node("route", route_node)

    graph.set_entry_point("extract")
    graph.add_conditional_edges("extract", _route_after_extract, {"validate": "validate", END: END})
    graph.add_conditional_edges("validate", _route_after_validate, {"route": "route", END: END})
    graph.add_edge("route", END)
    return graph


def run_pipeline(document_path: str, customer_id: str = "acme_imports",
                  checkpoint_db_path: str = "pipeline_checkpoints.sqlite") -> PipelineState:
    """
    Runs the full pipeline on a document. Returns the final PipelineState.
    Uses run_id as the LangGraph thread_id so a crashed run can be resumed
    later by calling resume_pipeline(run_id) with the same checkpoint db.

    NOTE on SqliteSaver: in the currently installed langgraph-checkpoint-sqlite
    version, SqliteSaver.from_conn_string() is a @contextmanager, not a plain
    factory — it must be used with `with`, or the underlying sqlite connection
    is closed before compile() can use it. Verified directly against the
    installed library source rather than assumed from memory.
    """
    import uuid
    run_id = str(uuid.uuid4())
    graph = _build_uncompiled_graph()

    initial_state: GraphState = {
        "run_id": run_id,
        "document_path": document_path,
        "customer_id": customer_id,
        "status": "pending",
        "error_log": [],
    }
    config = {"configurable": {"thread_id": run_id}}

    with SqliteSaver.from_conn_string(checkpoint_db_path) as checkpointer:
        app = graph.compile(checkpointer=checkpointer)
        final_state = app.invoke(initial_state, config=config)

    return _to_pipeline_state(final_state)


def resume_pipeline(run_id: str, checkpoint_db_path: str = "pipeline_checkpoints.sqlite") -> PipelineState:
    """
    Resumes a previously crashed/interrupted run using its run_id as the
    thread_id. LangGraph's checkpointer restores state from the last
    successfully completed node, so we do NOT re-run nodes that already
    finished (e.g. we won't re-call the Extractor's Gemini API if it already
    succeeded before the crash).
    """
    graph = _build_uncompiled_graph()
    config = {"configurable": {"thread_id": run_id}}

    with SqliteSaver.from_conn_string(checkpoint_db_path) as checkpointer:
        app = graph.compile(checkpointer=checkpointer)
        # Passing None as input tells LangGraph to continue from the last
        # checkpoint for this thread_id rather than starting a new run.
        final_state = app.invoke(None, config=config)

    return _to_pipeline_state(final_state)


def _to_pipeline_state(graph_state: GraphState) -> PipelineState:
    return PipelineState(
        run_id=graph_state.get("run_id", "unknown"),
        document_path=graph_state.get("document_path", ""),
        customer_id=graph_state.get("customer_id", "acme_imports"),
        status=graph_state.get("status", "pending"),
        extraction_result=ExtractionResult(**graph_state["extraction_result"])
            if graph_state.get("extraction_result") else None,
        validation_result=ValidationResult(**graph_state["validation_result"])
            if graph_state.get("validation_result") else None,
        routing_decision=RoutingDecision(**graph_state["routing_decision"])
            if graph_state.get("routing_decision") else None,
        error_log=graph_state.get("error_log", []),
    )
