from sqlalchemy import Column, Float, Integer, String, UniqueConstraint

from database.db import Base


POLICY_STATUS_DRAFT = "DRAFT"
POLICY_STATUS_VERIFIED = "VERIFIED"
POLICY_STATUS_CURRENT = "CURRENT"
POLICY_STATUS_SUPERSEDED = "SUPERSEDED"

POLICY_STATUSES = (
    POLICY_STATUS_DRAFT,
    POLICY_STATUS_VERIFIED,
    POLICY_STATUS_CURRENT,
    POLICY_STATUS_SUPERSEDED,
)


class Policy(Base):
    __tablename__ = "policies"
    __table_args__ = (
        UniqueConstraint("name", "version", name="uq_policy_name_version"),
    )

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    version = Column(String, nullable=False)
    attendance_requirement = Column(Float)
    status = Column(String, nullable=False, default=POLICY_STATUS_DRAFT)
