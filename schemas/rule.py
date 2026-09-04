from pydantic import BaseModel


class Rule(BaseModel):
    attendance_requirement: float
