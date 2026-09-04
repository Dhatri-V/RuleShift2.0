from pydantic import BaseModel, Field


class Rule(BaseModel):
    attendance_requirement: float = Field(
        ge=0,
        le=100,
        description="Minimum attendance percentage required by the policy",
    )
