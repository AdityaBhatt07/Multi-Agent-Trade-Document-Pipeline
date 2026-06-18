"""
Storage layer — persists every completed PipelineState to SQLite via SQLAlchemy.
This is the queryable history the NL query layer reads from. Distinct from
the LangGraph checkpointer (which is for crash-resume mid-run); this table is
for permanent record-keeping of finished runs.
"""
from __future__ import annotations
from datetime import datetime
from sqlalchemy import create_engine, Column, String, Float, DateTime, Text
from sqlalchemy.orm import declarative_base, sessionmaker

from models.schemas import PipelineState

Base = declarative_base()


class ShipmentRecord(Base):
    __tablename__ = "shipment_records"

    run_id = Column(String, primary_key=True)
    document_path = Column(String)
    customer_id = Column(String, index=True)
    status = Column(String, index=True)
    action = Column(String, index=True)  # auto_approve / flag_for_review / draft_amendment
    reasoning = Column(Text)
    extraction_json = Column(Text)
    validation_json = Column(Text)
    routing_json = Column(Text)
    overall_confidence = Column(Float)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


def get_session(db_path: str = "nova_pipeline.db"):
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return Session()


def save_pipeline_state(state: PipelineState, db_path: str = "nova_pipeline.db"):
    session = get_session(db_path)
    try:
        record = ShipmentRecord(
            run_id=state.run_id,
            document_path=state.document_path,
            customer_id=state.customer_id,
            status=state.status,
            action=state.routing_decision.action if state.routing_decision else None,
            reasoning=state.routing_decision.reasoning if state.routing_decision else None,
            extraction_json=state.extraction_result.model_dump_json() if state.extraction_result else None,
            validation_json=state.validation_result.model_dump_json() if state.validation_result else None,
            routing_json=state.routing_decision.model_dump_json() if state.routing_decision else None,
            overall_confidence=state.validation_result.overall_confidence if state.validation_result else None,
        )
        session.merge(record)  # merge = insert or update by primary key
        session.commit()
        return record.run_id
    finally:
        session.close()
