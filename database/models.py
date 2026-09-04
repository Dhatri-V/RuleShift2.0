from sqlalchemy import Column, Float, Integer, String

from database.db import Base


class Policy(Base):
    __tablename__ = "policies"

    id = Column(Integer, primary_key=True)
    name = Column(String)
    attendance_requirement = Column(Float)
