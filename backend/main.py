from typing import Optional
import re

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ai.extraction import extract_attendance_rule
from ai.rag import (answer_policy_question, delete_chunk_ids, delete_policy_chunks,
                    policy_chunk_ids, store_policy_pages)
from core.auth import create_access_token, require_admin, verify_admin_credentials
from core.config import ConfigError, get_max_upload_bytes
from core.evaluator import check_attendance
from core.impact import compare_attendance_requirements, compare_rules
from database.db import Base, SessionLocal, engine
from database.models import (
    POLICY_STATUS_CURRENT,
    POLICY_STATUS_DRAFT,
    POLICY_STATUS_SUPERSEDED,
    POLICY_STATUS_VERIFIED,
    POLICY_STATUSES,
    Policy,
    PolicyFamily,
)
from services.source_service import persist_source
from services.rule_source import source_check, require_source_match, record_verified_rule
from database.models import AuditEvent
from database.decision_models import ImpactRun
from services.index_service import begin_generation, mark_generation_ready, require_healthy_index
from services.pdf_service import PdfValidationError, extract_pdf_pages


# Schema is managed by Alembic migrations (see alembic/). We do NOT call
# Base.metadata.create_all here so that startup never silently creates or
# alters schema outside of migrations. Run `alembic upgrade head` instead.
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


class RuleUpdate(BaseModel):
    attendance_requirement: float = Field(ge=0, le=100)


class CompareInput(BaseModel):
    attendance: Optional[float] = None
    old_attendance_requirement: float
    new_attendance_requirement: float


class PolicyComparisonInput(BaseModel):
    old_policy_id: int
    new_policy_id: int


class StudentImpactInput(BaseModel):
    old_policy_id: int
    new_policy_id: int
    attendance: float = Field(ge=0, le=100)


class PolicyQuestion(BaseModel):
    policy_name: str
    version: Optional[str] = None
    question: str


class AdminLogin(BaseModel):
    email: str
    password: str


def get_or_create_policy_family(database, name):
    family = database.query(PolicyFamily).filter(PolicyFamily.name == name).first()
    if family is not None:
        return family
    try:
        with database.begin_nested():
            family = PolicyFamily(name=name)
            database.add(family)
            database.flush()
    except IntegrityError:
        # Another transaction may have created this family in the meantime.
        family = database.query(PolicyFamily).filter(PolicyFamily.name == name).one()
    return family


def get_database():
    database = SessionLocal()
    try:
        yield database
    finally:
        database.close()


@app.get("/")
def home():
    return {"message": "RuleShift API is running"}


@app.get("/health")
def health():
    """API liveness, independent of database and local AI availability."""
    return {"status": "ok"}


@app.post("/auth/login")
def admin_login(credentials: AdminLogin):
    if not verify_admin_credentials(credentials.email, credentials.password):
        raise HTTPException(
            status_code=401,
            detail="Invalid admin email or password.",
        )

    try:
        access_token = create_access_token(credentials.email)
    except ConfigError as error:
        raise HTTPException(status_code=503, detail=str(error))

    return {
        "access_token": access_token,
        "token_type": "bearer",
    }


@app.post("/policies")
def create_policy(
    policy: PolicyInput,
    database: Session = Depends(get_database),
    admin: dict = Depends(require_admin),
):
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
        family=get_or_create_policy_family(database, policy.name),
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


def policy_payload(policy):
    return {
        "id": policy.id,
        "family_id": policy.family_id,
        "name": policy.name,
        "version": policy.version,
        "attendance_requirement": policy.attendance_requirement,
        "status": policy.status,
        "source_check": source_check(policy),
    }


@app.get("/policies")
def get_policies(database: Session = Depends(get_database)):
    """Public catalogue: never expose drafts or partially reviewed versions."""
    policies = database.query(Policy).filter(
        Policy.status.in_((POLICY_STATUS_VERIFIED, POLICY_STATUS_CURRENT, POLICY_STATUS_SUPERSEDED))
    ).all()
    return [policy_payload(policy) for policy in policies]


@app.get("/admin/policies")
def get_admin_policies(
    database: Session = Depends(get_database),
    admin: dict = Depends(require_admin),
):
    """Admin catalogue includes drafts required by review and upload workflows."""
    return [policy_payload(policy) for policy in database.query(Policy).all()]


@app.post("/policies/upload")
async def upload_policy(
    policy_name: str = Form(...),
    version: str = Form(...),
    file: UploadFile = File(...),
    database: Session = Depends(get_database),
    admin: dict = Depends(require_admin),
):
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=400,
            detail="Please upload a PDF file (.pdf extension required).",
        )

    pdf_bytes = await file.read()

    if not pdf_bytes:
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")

    max_upload_bytes = get_max_upload_bytes()
    if len(pdf_bytes) > max_upload_bytes:
        raise HTTPException(
            status_code=413,
            detail=(
                "The PDF is too large. Maximum upload size is "
                f"{get_max_upload_bytes() // (1024 * 1024)} MB."
            ),
        )

    # Reject files that do not even look like a PDF before spending time on
    # full parsing; PyMuPDF still validates the full structure afterwards.
    if not pdf_bytes.lstrip().startswith(b"%PDF-"):
        raise HTTPException(
            status_code=400,
            detail="The uploaded file is not a valid PDF document.",
        )

    existing = (
        database.query(Policy)
        .filter(Policy.name == policy_name, Policy.version == version)
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Policy '{policy_name}' version '{version}' already exists. "
                "Choose a different version number; existing policies are never overwritten."
            ),
        )

    try:
        pages = extract_pdf_pages(pdf_bytes)
    except PdfValidationError as error:
        raise HTTPException(status_code=400, detail=str(error))

    # Keep only pages with extractable text, but preserve their original
    # page numbers so RAG evidence always cites the real PDF page.
    text_pages = [page for page in pages if page["text"]]

    if not text_pages:
        raise HTTPException(
            status_code=400,
            detail=(
                "The PDF does not contain any extractable text. "
                "Scanned image-only PDFs are not supported; "
                "please upload a text-based PDF."
            ),
        )

    policy_text = "\n\n".join(
        f"Page {page['page_number']}:\n{page['text']}" for page in text_pages
    )

    try:
        rule = extract_attendance_rule(policy_text)
    except Exception as error:
        # Extraction failed: fail cleanly without creating a policy with an
        # invented or misleading attendance value.
        raise HTTPException(
            status_code=503,
            detail=(
                "Could not extract the attendance rule from this PDF. "
                "No policy was created. Please try again later. "
                f"(AI generation service error: {error})"
            ),
        )

    try:
        # SQLite must have a physical transaction before the family SAVEPOINT;
        # otherwise releasing that first savepoint commits the new family early.
        connection = database.connection()
        if connection.dialect.name == "sqlite" and not connection.connection.driver_connection.in_transaction:
            connection.exec_driver_sql("BEGIN")
        new_policy = Policy(
            family=get_or_create_policy_family(database, policy_name),
            version=version,
            attendance_requirement=rule.attendance_requirement,
            status=POLICY_STATUS_DRAFT,
        )
        database.add(new_policy)
        database.flush()  # Stable ownership IDs before clauses or index writes.
        chunks = persist_source(database, new_policy, pdf_bytes, pages)
        if source_check(new_policy)["status"] == "MISMATCH":
            require_source_match(new_policy)
        generation = begin_generation(database, new_policy, chunks)
        new_chunk_ids = policy_chunk_ids(chunks)
        try:
            chunk_count = store_policy_pages(policy_name, version, pages, chunks=chunks)
            mark_generation_ready(generation, chunk_count)
            if generation.status != "READY":
                raise RuntimeError(generation.failure_detail)
            database.add(AuditEvent(
                family_id=new_policy.family_id, version_id=None,
                actor_type="ADMIN", actor_id=admin["sub"], action="POLICY_UPLOADED",
                after_state={"version_id": new_policy.id,
                             "source_sha256": new_policy.source_document.sha256,
                             "page_count": len(pages), "chunk_count": chunk_count,
                             "index_generation": generation.generation},
            ))
            database.commit()
        except Exception as error:
            database.rollback()
            try:
                delete_chunk_ids(new_chunk_ids)
            except Exception as cleanup_error:
                raise HTTPException(
                    status_code=503,
                    detail=f"Upload failed and vector cleanup also failed: {cleanup_error}",
                ) from error
            if isinstance(error, IntegrityError):
                raise HTTPException(
                    status_code=409,
                    detail=f"Policy '{policy_name}' version '{version}' already exists.",
                ) from error
            if isinstance(error, HTTPException):
                raise error
            raise HTTPException(status_code=503, detail=f"AI service error: {error}") from error
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


@app.delete("/policies/{policy_id}")
def delete_draft_policy(
    policy_id: int,
    database: Session = Depends(get_database),
    admin: dict = Depends(require_admin),
):
    policy = database.query(Policy).filter(Policy.id == policy_id).first()
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found.")

    if policy.status != POLICY_STATUS_DRAFT:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Only DRAFT policies can be deleted. "
                f"Policy '{policy.name}' version '{policy.version}' is {policy.status}."
            ),
        )

    if policy.audit_events:
        raise HTTPException(status_code=409, detail="This draft has review history and must be retained for audit; it cannot be deleted.")

    # Remove the derived RAG index entries first so no orphaned chunks remain
    # if the SQLite delete fails; SQLite stays the authoritative record.
    try:
        delete_policy_chunks(policy.name, policy.version)
    except Exception as error:
        raise HTTPException(status_code=503, detail=f"AI service error: {error}")

    # Index generations describe derived chunks and must be removed with a draft.
    for generation in policy.index_generations:
        database.delete(generation)
    database.flush()

    # Migration preserves legacy thresholds as unverified Rule records.
    # Remove those source-free records when deleting their draft owner.
    for rule in policy.rules:
        if rule.legacy_unverified and rule.source_clause_id is None:
            database.delete(rule)
    database.flush()
    # Uploaded drafts now own source clauses and PDF evidence. Preserve existing
    # draft deletion while foreign keys still protect referenced clauses/rules.
    for clause in policy.clauses:
        database.delete(clause)
    database.flush()
    if policy.source_document is not None:
        for page in policy.source_document.pages:
            database.delete(page)
        database.flush()
        database.delete(policy.source_document)
        database.flush()
    database.delete(policy)
    database.commit()

    return {
        "id": policy_id,
        "name": policy.name,
        "version": policy.version,
        "status": POLICY_STATUS_DRAFT,
        "deleted": True,
    }


@app.post("/compare")
def compare_policy_rules(comparison: CompareInput):
    result = compare_rules(
        comparison.attendance,
        comparison.old_attendance_requirement,
        comparison.new_attendance_requirement,
    )

    return {"result": result}


@app.post("/student-impact")
def calculate_student_impact(
    payload: StudentImpactInput,
    database: Session = Depends(get_database),
):
    old_policy = database.query(Policy).filter(Policy.id == payload.old_policy_id).first()
    if not old_policy:
        raise HTTPException(
            status_code=404,
            detail=f"Policy id {payload.old_policy_id} not found.",
        )

    new_policy = database.query(Policy).filter(Policy.id == payload.new_policy_id).first()
    if not new_policy:
        raise HTTPException(
            status_code=404,
            detail=f"Policy id {payload.new_policy_id} not found.",
        )

    require_comparable_versions(old_policy, new_policy)

    if old_policy.attendance_requirement is None or new_policy.attendance_requirement is None:
        raise HTTPException(
            status_code=409,
            detail="Both policy versions must have a verified attendance requirement.",
        )

    old_result = check_attendance(payload.attendance, old_policy.attendance_requirement)
    new_result = check_attendance(payload.attendance, new_policy.attendance_requirement)
    impact = compare_rules(
        payload.attendance,
        old_policy.attendance_requirement,
        new_policy.attendance_requirement,
    )
    old_evidence = rule_evidence(old_policy)
    new_evidence = rule_evidence(new_policy)
    run = ImpactRun(
        old_version_id=old_policy.id,
        new_version_id=new_policy.id,
        attendance=payload.attendance,
        old_rule_snapshot=old_evidence,
        new_rule_snapshot=new_evidence,
        old_result=old_result,
        new_result=new_result,
        impact=impact,
    )
    database.add(run)
    database.commit()
    database.refresh(run)

    return {
        "run_id": run.id,
        "attendance": payload.attendance,
        "old_policy": {
            "id": old_policy.id,
            "name": old_policy.name,
            "version": old_policy.version,
            "attendance_requirement": old_policy.attendance_requirement,
            "status": old_policy.status,
            "result": old_result,
            "evidence": old_evidence,
        },
        "new_policy": {
            "id": new_policy.id,
            "name": new_policy.name,
            "version": new_policy.version,
            "attendance_requirement": new_policy.attendance_requirement,
            "status": new_policy.status,
            "result": new_result,
            "evidence": new_evidence,
        },
        "impact": impact,
        "snapshot": {
            "attendance": payload.attendance,
            "old": old_evidence,
            "new": new_evidence,
        },
    }


@app.get("/impact-runs/{run_id}")
def get_impact_run(run_id: int, database: Session = Depends(get_database)):
    run = database.get(ImpactRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Impact run not found.")
    return {
        "run_id": run.id,
        "attendance": run.attendance,
        "old_result": run.old_result,
        "new_result": run.new_result,
        "impact": run.impact,
        "engine_version": run.engine_version,
        "old_evidence": run.old_rule_snapshot,
        "new_evidence": run.new_rule_snapshot,
        "created_at": run.created_at,
    }


def version_sort_key(value):
    """Numeric-aware, deterministic ordering for year and dotted version labels."""
    return tuple(
        (0, int(token)) if token.isdigit() else (1, token.lower())
        for token in re.findall(r"\d+|[^\d]+", value.strip())
    )


def require_comparable_versions(old_policy, new_policy):
    if old_policy.family_id != new_policy.family_id:
        raise HTTPException(status_code=400, detail="Only versions of the same policy can be compared.")
    allowed = {POLICY_STATUS_VERIFIED, POLICY_STATUS_CURRENT, POLICY_STATUS_SUPERSEDED}
    for policy, label in ((old_policy, "Old"), (new_policy, "New")):
        if policy.status not in allowed:
            raise HTTPException(
                status_code=409,
                detail=f"{label} policy version {policy.version} is {policy.status}. Only reviewed versions can be compared.",
            )
        require_source_match(policy)
        if not policy.rules or policy.rules[0].source_clause_id is None:
            raise HTTPException(status_code=409, detail=f"{label} version has no verified source-linked rule.")
    if version_sort_key(new_policy.version) <= version_sort_key(old_policy.version):
        raise HTTPException(status_code=409, detail="New policy version must be chronologically newer than old policy version.")


def rule_evidence(policy):
    rule = policy.rules[0]
    clause = rule.source_clause
    return {
        "policy_id": policy.family_id,
        "version_id": policy.id,
        "policy_name": policy.name,
        "version": policy.version,
        "rule_id": rule.id,
        "rule_type": rule.rule_type,
        "value": rule.attendance_requirement,
        "clause_id": clause.id,
        "page_number": clause.page_number,
        "clause_label": clause.clause_label,
        "source_text": clause.source_text,
        "source_sha256": policy.source_document.sha256,
    }


@app.post("/compare-versions")
def compare_policy_versions(
    comparison: PolicyComparisonInput,
    database: Session = Depends(get_database),
):
    if comparison.old_policy_id == comparison.new_policy_id:
        raise HTTPException(
            status_code=400,
            detail="Old and new policy versions must be different.",
        )

    old_policy = database.query(Policy).filter(Policy.id == comparison.old_policy_id).first()
    if not old_policy:
        raise HTTPException(
            status_code=404,
            detail=f"Policy id {comparison.old_policy_id} not found.",
        )

    new_policy = database.query(Policy).filter(Policy.id == comparison.new_policy_id).first()
    if not new_policy:
        raise HTTPException(
            status_code=404,
            detail=f"Policy id {comparison.new_policy_id} not found.",
        )

    require_comparable_versions(old_policy, new_policy)

    if old_policy.attendance_requirement is None or new_policy.attendance_requirement is None:
        raise HTTPException(
            status_code=409,
            detail="Both policy versions must have a verified attendance requirement.",
        )

    result = compare_attendance_requirements(
        old_policy.attendance_requirement,
        new_policy.attendance_requirement,
    )

    return {
        "old_policy": {
            "id": old_policy.id,
            "name": old_policy.name,
            "version": old_policy.version,
            "attendance_requirement": old_policy.attendance_requirement,
            "status": old_policy.status,
            "evidence": rule_evidence(old_policy),
        },
        "new_policy": {
            "id": new_policy.id,
            "name": new_policy.name,
            "version": new_policy.version,
            "attendance_requirement": new_policy.attendance_requirement,
            "status": new_policy.status,
            "evidence": rule_evidence(new_policy),
        },
        "direction": result["direction"],
        "difference": result["difference"],
    }


@app.post("/ask")
def ask_policy_question(
    request: PolicyQuestion,
    database: Session = Depends(get_database),
):
    query = database.query(Policy).filter(Policy.name == request.policy_name)
    if request.version is None:
        policy = query.filter(Policy.status == POLICY_STATUS_CURRENT).first()
        if not policy:
            raise HTTPException(status_code=404, detail=f"No CURRENT version exists for policy '{request.policy_name}'.")
    else:
        policy = query.filter(Policy.version == request.version).first()
        if not policy:
            raise HTTPException(status_code=404, detail=f"Policy '{request.policy_name}' version '{request.version}' not found.")
        if policy.status not in {POLICY_STATUS_VERIFIED, POLICY_STATUS_CURRENT, POLICY_STATUS_SUPERSEDED}:
            raise HTTPException(status_code=409, detail=f"Policy '{request.policy_name}' version '{request.version}' is {policy.status} and cannot be queried.")

    require_source_match(policy)
    if not policy.rules or policy.rules[0].source_clause_id is None:
        raise HTTPException(status_code=409, detail="Selected policy has no verified source-linked rule.")

    try:
        result = answer_policy_question(policy.name, policy.version, request.question)
        result["resolved_policy"] = {
            "policy_id": policy.family_id,
            "version_id": policy.id,
            "policy_name": policy.name,
            "version": policy.version,
            "status": policy.status,
        }
        return result
    except Exception as error:
        raise HTTPException(status_code=503, detail=f"AI generation service error: {error}")


@app.get("/admin/audit")
def get_audit_events(
    database: Session = Depends(get_database),
    admin: dict = Depends(require_admin),
):
    events = database.query(AuditEvent).order_by(AuditEvent.id.desc()).all()
    return [{
        "id": event.id,
        "family_id": event.family_id,
        "version_id": event.version_id,
        "rule_id": event.rule_id,
        "clause_id": event.clause_id,
        "actor_type": event.actor_type,
        "actor_id": event.actor_id,
        "action": event.action,
        "reason": event.reason,
        "before_state": event.before_state,
        "after_state": event.after_state,
        "occurred_at": event.occurred_at,
    } for event in events]


@app.patch("/policies/{policy_id}/status")
def update_policy_status(
    policy_id: int,
    payload: StatusUpdate,
    database: Session = Depends(get_database),
    admin: dict = Depends(require_admin),
):
    if payload.status not in POLICY_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Status must be one of: {', '.join(POLICY_STATUSES)}",
        )

    policy = database.query(Policy).filter(Policy.id == policy_id).first()
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found.")

    if payload.status == POLICY_STATUS_VERIFIED:
        raise HTTPException(
            status_code=400,
            detail="Use the verify endpoint to verify a policy.",
        )
    if payload.status == POLICY_STATUS_CURRENT:
        raise HTTPException(
            status_code=400,
            detail="Use the mark-current endpoint to make a policy current.",
        )
    if payload.status == POLICY_STATUS_DRAFT and policy.status != POLICY_STATUS_DRAFT:
        raise HTTPException(
            status_code=409,
            detail="A policy cannot return to DRAFT after review.",
        )

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


@app.patch("/policies/{policy_id}/rule")
def update_policy_rule(
    policy_id: int,
    payload: RuleUpdate,
    database: Session = Depends(get_database),
    admin: dict = Depends(require_admin),
):
    policy = database.query(Policy).filter(Policy.id == policy_id).first()
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found.")
    check = source_check(policy)
    repair = policy.status != POLICY_STATUS_DRAFT and check['status'] == 'MISMATCH'
    if policy.status != POLICY_STATUS_DRAFT and not repair:
        raise HTTPException(status_code=409, detail="Only DRAFT policies can have their rule edited.")
    require_source_match(policy, payload.attendance_requirement)
    if repair:
        database.add(AuditEvent(family_id=policy.family_id, version_id=policy.id,
            actor_type='ADMIN', actor_id=admin['sub'], action='SOURCE_MISMATCH_REOPENED',
            before_state={'attendance_requirement': policy.attendance_requirement, 'status': policy.status},
            after_state={'attendance_requirement': payload.attendance_requirement, 'status': POLICY_STATUS_DRAFT},
            reason=check['message']))
        policy.status = POLICY_STATUS_DRAFT
        if policy.rules and policy.rules[0].review is not None:
            review = policy.rules[0].review
            review.status = 'PENDING_REVIEW'
            review.reviewer_id = None
            review.reviewed_at = None
            review.reason = None
            review.rule_snapshot = None
    policy.attendance_requirement = payload.attendance_requirement
    database.commit()
    database.refresh(policy)

    return {
        "id": policy.id,
        "name": policy.name,
        "version": policy.version,
        "attendance_requirement": policy.attendance_requirement,
        "status": policy.status,
    }


@app.post("/policies/{policy_id}/verify")
def verify_policy(
    policy_id: int,
    database: Session = Depends(get_database),
    admin: dict = Depends(require_admin),
):
    policy = database.query(Policy).filter(Policy.id == policy_id).first()
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found.")
    if policy.status != POLICY_STATUS_DRAFT:
        raise HTTPException(
            status_code=409,
            detail="Only DRAFT policies can be verified.",
        )

    if any(issue.status == "OPEN" and issue.is_blocking for issue in policy.validation_issues):
        raise HTTPException(status_code=409, detail="Verification blocked by unresolved validation issues.")
    try:
        record_verified_rule(database, policy, admin)
    except HTTPException as error:
        database.rollback()
        policy = database.get(Policy, policy_id)
        database.add(AuditEvent(
            family_id=policy.family_id, version_id=policy.id,
            actor_type="ADMIN", actor_id=admin["sub"], action="VERIFICATION_BLOCKED",
            reason=str(error.detail), after_state={"status": policy.status},
        ))
        database.commit()
        raise error
    policy.status = POLICY_STATUS_VERIFIED
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
def mark_policy_current(
    policy_id: int,
    database: Session = Depends(get_database),
    admin: dict = Depends(require_admin),
):
    policy = database.query(Policy).filter(Policy.id == policy_id).first()
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found.")
    if policy.status != POLICY_STATUS_VERIFIED:
        raise HTTPException(
            status_code=409,
            detail="Only VERIFIED policies can be marked CURRENT.",
        )

    require_source_match(policy)
    if not policy.rules or policy.rules[0].source_clause_id is None:
        raise HTTPException(status_code=409, detail="Publication blocked: no verified source-linked rule exists.")
    if any(issue.status == "OPEN" and issue.is_blocking for issue in policy.validation_issues):
        raise HTTPException(status_code=409, detail="Publication blocked by unresolved validation issues.")
    generation = require_healthy_index(policy)

    # Find whichever other version of this same policy is currently CURRENT,
    # regardless of its version string, and supersede it. We never compare
    # version strings numerically to decide "old" vs "new".
    previous_current = (
        database.query(Policy)
        .filter(
            Policy.name == policy.name,
            Policy.status == POLICY_STATUS_CURRENT,
            Policy.id != policy.id,
        )
        .first()
    )

    if previous_current:
        if version_sort_key(policy.version) <= version_sort_key(previous_current.version):
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Publication blocked: version {policy.version} is not chronologically newer "
                    f"than current version {previous_current.version}."
                ),
            )
        previous_current.status = POLICY_STATUS_SUPERSEDED
        # Release the unique CURRENT slot before activating another version,
        # regardless of the order of their primary keys. Both share one commit.
        database.flush()

    policy.status = POLICY_STATUS_CURRENT
    policy.supersedes_version_id = previous_current.id if previous_current else policy.supersedes_version_id
    database.add(AuditEvent(
        family_id=policy.family_id, version_id=policy.id,
        actor_type="ADMIN", actor_id=admin["sub"], action="POLICY_PUBLISHED",
        before_state={"status": POLICY_STATUS_VERIFIED},
        after_state={"status": POLICY_STATUS_CURRENT,
                     "index_generation": generation.generation,
                     "superseded_version_id": previous_current.id if previous_current else None},
    ))
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
