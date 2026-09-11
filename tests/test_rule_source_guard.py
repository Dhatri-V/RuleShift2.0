from unittest.mock import patch
import pytest
from database.models import PolicyVersion, Rule, AuditEvent
from test_large_pdf_ingestion import pipeline, upload
import pymupdf

def pdf(text="The minimum attendance requirement is 85% in each course."):
    d=pymupdf.open();p=d.new_page();p.insert_text((40,80),text);return d.tobytes()

def test_verification_rejects_mismatch_and_patch_requires_source(pipeline, admin_headers):
    response=upload(pipeline,pdf(),admin_headers);pid=response.json()["id"]
    with pipeline.sessions() as db:
        v=db.get(PolicyVersion,pid);v.attendance_requirement=80;db.commit()
    assert pipeline.client.post(f"/policies/{pid}/verify",headers=admin_headers).status_code==409
    assert pipeline.client.patch(f"/policies/{pid}/rule",headers=admin_headers,json={"attendance_requirement":75}).status_code==409
    assert pipeline.client.patch(f"/policies/{pid}/rule",headers=admin_headers,json={"attendance_requirement":85}).status_code==200
    assert pipeline.client.post(f"/policies/{pid}/verify",headers=admin_headers).status_code==200
    with pipeline.sessions() as db:
        v=db.get(PolicyVersion,pid);assert v.rules[0].attendance_requirement==85
        assert v.rules[0].source_clause.version_id==pid
        assert db.query(AuditEvent).filter_by(action="SOURCE_RULE_VERIFIED").count()==1


def test_preexisting_verified_mismatch_is_visible_blocked_and_reopened(pipeline,admin_headers):
    pid=upload(pipeline,pdf(),admin_headers).json()["id"]
    with pipeline.sessions() as db:
        v=db.get(PolicyVersion,pid);v.attendance_requirement=80;v.status="VERIFIED";db.commit()
    row=pipeline.client.get("/policies").json()[0]
    assert row["source_check"]["status"]=="MISMATCH" and row["source_check"]["expected_value"]==85
    assert pipeline.client.post(f"/policies/{pid}/mark-current",headers=admin_headers).status_code==409
    repaired=pipeline.client.patch(f"/policies/{pid}/rule",headers=admin_headers,json={"attendance_requirement":85})
    assert repaired.status_code==200 and repaired.json()["status"]=="DRAFT"
    with pipeline.sessions() as db:
        event=db.query(AuditEvent).filter_by(action="SOURCE_MISMATCH_REOPENED").one()
        assert event.before_state=={"attendance_requirement":80,"status":"VERIFIED"}
    assert pipeline.client.post(f"/policies/{pid}/verify",headers=admin_headers).status_code==200


def test_conflicting_source_is_not_verifiable(pipeline,admin_headers):
    pid=upload(pipeline,pdf("The minimum attendance requirement is 80%. The minimum attendance requirement is 85%."),admin_headers).json()["id"]
    assert pipeline.client.post(f"/policies/{pid}/verify",headers=admin_headers).status_code==409


def test_wrong_extractor_value_cannot_persist_or_index(pipeline,admin_headers):
    pipeline.extract.return_value.attendance_requirement=80
    result=upload(pipeline,pdf(),admin_headers)
    assert result.status_code==409
    assert pipeline.client.get("/policies").json()==[]
    assert pipeline.store.get()["ids"]==[]


def test_mismatch_cannot_drive_comparison_or_impact(pipeline,admin_headers):
    old=upload(pipeline,pdf(),admin_headers,version="2026").json()["id"]
    new=upload(pipeline,pdf(),admin_headers,version="2027").json()["id"]
    with pipeline.sessions() as db:
        for pid in (old,new):db.get(PolicyVersion,pid).status="VERIFIED"
        db.get(PolicyVersion,new).attendance_requirement=80;db.commit()
    payload={"old_policy_id":old,"new_policy_id":new}
    assert pipeline.client.post("/compare-versions",json=payload).status_code==409
    assert pipeline.client.post("/student-impact",json={**payload,"attendance":82}).status_code==409


@pytest.mark.parametrize("question", ["What attendance should I maintain?", "What is the minimum attendance requirement?", "How much attendance is required?", "What attendance percentage do I need?"])
def test_ask_api_preserves_source_answer_after_verified_upload(pipeline,admin_headers,question):
    pid=upload(pipeline,pdf(),admin_headers).json()["id"]
    assert pipeline.client.post(f"/policies/{pid}/verify",headers=admin_headers).status_code==200
    row=pipeline.client.get("/policies").json()[0]
    from ai.rag import INSUFFICIENT_EVIDENCE_ANSWER
    with patch("ai.rag.get_llm") as llm:
        llm.return_value.invoke.return_value.content=INSUFFICIENT_EVIDENCE_ANSWER
        result=pipeline.client.post("/ask",json={"policy_name":row["name"],"version":row["version"],"question":question})
    assert result.status_code==200
    assert "85%" in result.json()["answer"]
    assert result.json()["evidence"][0]["page_number"]==1
    assert result.json()["evidence"][0]["version"]==row["version"]


def test_reopened_review_history_is_retained_without_vector_deletion(pipeline,admin_headers):
    pid=upload(pipeline,pdf(),admin_headers).json()["id"]
    with pipeline.sessions() as db:
        v=db.get(PolicyVersion,pid);v.status="VERIFIED";v.attendance_requirement=80;db.commit()
    pipeline.client.patch(f"/policies/{pid}/rule",headers=admin_headers,json={"attendance_requirement":85})
    before=pipeline.store.get()["ids"]
    result=pipeline.client.delete(f"/policies/{pid}",headers=admin_headers)
    assert result.status_code==409 and "audit" in result.json()["detail"]
    assert pipeline.store.get()["ids"]==before
