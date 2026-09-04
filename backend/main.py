from typing import Optional

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ai.extraction import extract_attendance_rule
from ai.rag import answer_policy_question, store_policy_pages
from core.impact import compare_rules
from database.db import Base, SessionLocal, engine
from database.models import Policy
from services.pdf_service import extract_pdf_pages


Base.metadata.create_all(bind=engine)

app = FastAPI(title="RuleShift API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)


class PolicyInput(BaseModel):
    name: str
    attendance_requirement: float


class CompareInput(BaseModel):
    attendance: Optional[float] = None
    old_attendance_requirement: float
    new_attendance_requirement: float


class PolicyQuestion(BaseModel):
    policy_name: str
    version: str
    question: str


def get_database():
    database = SessionLocal()
    try:
        yield database
    finally:
        database.close()


@app.get("/")
def home():
    return {"message": "RuleShift API is running"}


@app.post("/policies")
def create_policy(policy: PolicyInput, database: Session = Depends(get_database)):
    new_policy = Policy(
        name=policy.name,
        attendance_requirement=policy.attendance_requirement,
    )

    database.add(new_policy)
    database.commit()
    database.refresh(new_policy)

    return {
        "id": new_policy.id,
        "name": new_policy.name,
        "attendance_requirement": new_policy.attendance_requirement,
    }


@app.get("/policies")
def get_policies(database: Session = Depends(get_database)):
    policies = database.query(Policy).all()

    return [
        {
            "id": policy.id,
            "name": policy.name,
            "attendance_requirement": policy.attendance_requirement,
        }
        for policy in policies
    ]


@app.post("/policies/upload")
async def upload_policy(
    policy_name: str = Form(...),
    version: str = Form(...),
    file: UploadFile = File(...),
    database: Session = Depends(get_database),
):
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Please upload a PDF file.")

    pdf_bytes = await file.read()

    try:
        pages = extract_pdf_pages(pdf_bytes)
    except Exception as error:
        raise HTTPException(status_code=400, detail=f"Could not read PDF: {error}")

    policy_text = "\n\n".join(
        f"Page {page['page_number']}:\n{page['text']}" for page in pages
    )

    if not any(page["text"] for page in pages):
        raise HTTPException(status_code=400, detail="The PDF does not contain readable text.")

    try:
        rule = extract_attendance_rule(policy_text)
        chunk_count = store_policy_pages(policy_name, version, pages)
    except Exception as error:
        raise HTTPException(status_code=503, detail=f"Local AI service error: {error}")

    new_policy = Policy(
        name=policy_name,
        attendance_requirement=rule.attendance_requirement,
    )
    database.add(new_policy)
    database.commit()
    database.refresh(new_policy)

    return {
        "id": new_policy.id,
        "name": policy_name,
        "version": version,
        "attendance_requirement": rule.attendance_requirement,
        "page_count": len(pages),
        "chunk_count": chunk_count,
    }


@app.post("/compare")
def compare_policy_rules(comparison: CompareInput):
    result = compare_rules(
        comparison.attendance,
        comparison.old_attendance_requirement,
        comparison.new_attendance_requirement,
    )

    return {"result": result}


@app.post("/ask")
def ask_policy_question(request: PolicyQuestion):
    try:
        return answer_policy_question(
            request.policy_name,
            request.version,
            request.question,
        )
    except Exception as error:
        raise HTTPException(status_code=503, detail=f"Local AI service error: {error}")
