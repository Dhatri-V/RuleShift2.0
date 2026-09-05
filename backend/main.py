from typing import Optional

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ai.extraction import extract_attendance_rule
from ai.rag import answer_policy_question, store_policy_pages
from core.impact import compare_rules
from database.db import Base, SessionLocal, engine
from database.models import POLICY_STATUS_DRAFT, POLICY_STATUSES, Policy
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
    version: str
    attendance_requirement: float


class StatusUpdate(BaseModel):
    status: str


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
    existing = (
        database.query(Policy)
        .filter(Policy.name == policy.name, Policy.version == policy.version)
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Policy '{policy.name}' version '{policy.version}' already exists.",
        )

    new_policy = Policy(
        name=policy.name,
        version=policy.version,
        attendance_requirement=policy.attendance_requirement,
        status=POLICY_STATUS_DRAFT,
    )

    database.add(new_policy)
    try:
        database.commit()
    except IntegrityError:
        database.rollback()
        raise HTTPException(
            status_code=409,
            detail=f"Policy '{policy.name}' version '{policy.version}' already exists.",
        )
    database.refresh(new_policy)

    return {
        "id": new_policy.id,
        "name": new_policy.name,
        "version": new_policy.version,
        "attendance_requirement": new_policy.attendance_requirement,
        "status": new_policy.status,
    }


@app.get("/policies")
def get_policies(database: Session = Depends(get_database)):
    policies = database.query(Policy).all()

    return [
        {
            "id": policy.id,
            "name": policy.name,
            "version": policy.version,
            "attendance_requirement": policy.attendance_requirement,
            "status": policy.status,
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

    existing = (
        database.query(Policy)
        .filter(Policy.name == policy_name, Policy.version == version)
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Policy '{policy_name}' version '{version}' already exists.",
        )

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
        version=version,
        attendance_requirement=rule.attendance_requirement,
        status=POLICY_STATUS_DRAFT,
    )
    database.add(new_policy)
    try:
        database.commit()
    except IntegrityError:
        database.rollback()
        raise HTTPException(
            status_code=409,
            detail=f"Policy '{policy_name}' version '{version}' already exists.",
        )
    database.refresh(new_policy)

    return {
        "id": new_policy.id,
        "name": policy_name,
        "version": version,
        "attendance_requirement": rule.attendance_requirement,
        "status": new_policy.status,
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


@app.patch("/policies/{policy_id}/status")
def update_policy_status(
    policy_id: int,
    payload: StatusUpdate,
    database: Session = Depends(get_database),
):
    if payload.status not in POLICY_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Status must be one of: {', '.join(POLICY_STATUSES)}",
        )

    policy = database.query(Policy).filter(Policy.id == policy_id).first()
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found.")

    policy.status = payload.status
    database.commit()
    database.refresh(policy)

    return {
        "id": policy.id,
        "name": policy.name,
        "version": policy.version,
        "attendance_requirement": policy.attendance_requirement,
        "status": policy.status,
    }


@app.post("/policies/{policy_id}/mark-current")
def mark_policy_current(policy_id: int, database: Session = Depends(get_database)):
    policy = database.query(Policy).filter(Policy.id == policy_id).first()
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found.")

    # Find whichever other version of this same policy is currently CURRENT,
    # regardless of its version string, and supersede it. We never compare
    # version strings numerically to decide "old" vs "new".
    previous_current = (
        database.query(Policy)
        .filter(
            Policy.name == policy.name,
            Policy.status == "CURRENT",
            Policy.id != policy.id,
        )
        .first()
    )

    if previous_current:
        previous_current.status = "SUPERSEDED"

    policy.status = "CURRENT"
    database.commit()
    database.refresh(policy)

    return {
        "id": policy.id,
        "name": policy.name,
        "version": policy.version,
        "attendance_requirement": policy.attendance_requirement,
        "status": policy.status,
        "superseded_id": previous_current.id if previous_current else None,
        "superseded_version": previous_current.version if previous_current else None,
    }
