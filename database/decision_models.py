"""Immutable snapshots of deterministic attendance impact decisions."""
from sqlalchemy import CheckConstraint, Column, DateTime, DDL, Float, ForeignKey, Integer, JSON, String, event, func

from database.db import Base


class ImpactRun(Base):
    __tablename__ = "impact_runs"
    __table_args__ = (
        CheckConstraint("attendance >= 0 AND attendance <= 100", name="ck_impact_attendance"),
        CheckConstraint("length(trim(impact)) > 0", name="ck_impact_result"),
        CheckConstraint("old_version_id != new_version_id", name="ck_impact_distinct_versions"),
    )

    id = Column(Integer, primary_key=True)
    old_version_id = Column(Integer, ForeignKey("policy_versions.id", ondelete="RESTRICT"), nullable=False)
    new_version_id = Column(Integer, ForeignKey("policy_versions.id", ondelete="RESTRICT"), nullable=False)
    attendance = Column(Float, nullable=False)
    old_rule_snapshot = Column(JSON(none_as_null=True), nullable=False)
    new_rule_snapshot = Column(JSON(none_as_null=True), nullable=False)
    old_result = Column(String, nullable=False)
    new_result = Column(String, nullable=False)
    impact = Column(String, nullable=False)
    engine_version = Column(String, nullable=False, default="attendance-v1", server_default="attendance-v1")
    created_at = Column(DateTime, nullable=False, server_default=func.current_timestamp())


for operation in ("UPDATE", "DELETE"):
    event.listen(
        ImpactRun.__table__,
        "after_create",
        DDL(
            f"CREATE TRIGGER impact_runs_no_{operation.lower()} BEFORE {operation} ON impact_runs "
            "BEGIN SELECT RAISE(ABORT, 'impact history is immutable'); END"
        ).execute_if(dialect="sqlite"),
    )
