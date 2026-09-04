from typing import Optional

from pydantic import BaseModel


class Student(BaseModel):
    name: str
    attendance: Optional[float] = None
