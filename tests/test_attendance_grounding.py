from unittest.mock import patch, MagicMock
import pytest
from langchain_core.documents import Document
from ai.rag import answer_policy_question, INSUFFICIENT_EVIDENCE_ANSWER
from ai.extraction import extract_attendance_rule

QUESTIONS = ["What attendance should I maintain?", "What is the minimum attendance requirement?", "How much attendance is required?", "What attendance percentage do I need?"]
COMPLIANCE_QUESTIONS = [
    ("I have 84% attendance. Do I meet the attendance requirement?", "No.", "does not meet"),
    ("I have exactly 85% attendance. Am I compliant?", "Yes.", "exactly 85% attendance is compliant"),
    ("I have 86% attendance. Do I meet the attendance requirement?", "Yes.", "86% attendance meets"),
    ("Is 85% attendance enough?", "Yes.", "exactly 85% attendance is compliant"),
    ("Do I satisfy the attendance rule with 85%?", "Yes.", "exactly 85% attendance is compliant"),
]

def doc(value=85, version="2027"):
    return Document(page_content=f"The minimum attendance requirement is {value}% in each course. This applies to the incoming cohort.", metadata={"policy_name":"Test", "version":version, "page_number":11})

@pytest.mark.parametrize("question", QUESTIONS)
def test_explicit_rule_recovers_model_refusal_with_selected_citation(question):
    with patch("ai.rag.retrieve_policy_chunks", return_value=[doc(80,"2026"),doc()]), patch("ai.rag.get_llm") as llm:
        llm.return_value.invoke.return_value.content=INSUFFICIENT_EVIDENCE_ANSWER
        result=answer_policy_question("Test","2027",question)
    assert "85%" in result["answer"] and "80%" not in result["answer"]
    assert "Page 11" in result["answer"]
    assert [e["version"] for e in result["evidence"]]==["2027"]
    assert result["evidence"][0]["page_number"]==11
    assert "incoming cohort" in result["evidence"][0]["text"]


@pytest.mark.parametrize("question,prefix,decision", COMPLIANCE_QUESTIONS)
def test_explicit_rule_deterministically_answers_attendance_boundaries(question, prefix, decision):
    with patch("ai.rag.retrieve_policy_chunks", return_value=[doc(80, "2026"), doc()]), patch("ai.rag.get_llm") as llm:
        llm.return_value.invoke.return_value.content = INSUFFICIENT_EVIDENCE_ANSWER
        result = answer_policy_question("Test", "2027", question)
    assert result["answer"].startswith(prefix)
    assert "minimum attendance requirement is 85%" in result["answer"]
    assert decision in result["answer"]
    assert result["evidence"]
    assert all(item["version"] == "2027" for item in result["evidence"])
    assert result["evidence"][0]["page_number"] == 11
    llm.return_value.invoke.assert_called_once()


def test_compliance_inference_fails_closed_for_ambiguous_selected_version_evidence():
    with patch("ai.rag.retrieve_policy_chunks", return_value=[doc(80), doc(85)]), patch("ai.rag.get_llm") as llm:
        llm.return_value.invoke.return_value.content = INSUFFICIENT_EVIDENCE_ANSWER
        result = answer_policy_question("Test", "2027", "Is 85% attendance enough?")
    assert result["answer_state"] == "CONFLICTING_EVIDENCE"
    assert "conflicting" in result["answer"].lower()

@pytest.mark.parametrize("documents,question", [([doc(80),doc(85)], QUESTIONS[0]),([doc()],"Am I eligible with medical condonation?"),([doc()],"What attendance applies to continuing students?"),([doc(80,"2026")],QUESTIONS[0])])
def test_refusal_not_overridden_for_ambiguity_exceptions_or_foreign_version(documents,question):
    with patch("ai.rag.retrieve_policy_chunks",return_value=documents),patch("ai.rag.get_llm") as llm:
        llm.return_value.invoke.return_value.content=INSUFFICIENT_EVIDENCE_ANSWER
        result=answer_policy_question("Test","2027",question)
    if len(documents) == 2 and all(item.metadata.get("version") == "2027" for item in documents):
        assert result["answer_state"] == "CONFLICTING_EVIDENCE"
    else:
        assert result["answer"] == INSUFFICIENT_EVIDENCE_ANSWER

def test_long_source_explicit_rule_does_not_depend_on_truncated_llm():
    with patch("ai.extraction.get_llm") as llm:
        rule=extract_attendance_rule("Unrelated material. "*5000+"The minimum attendance requirement is 85% in each course.")
    assert rule.attendance_requirement==85
    llm.assert_not_called()

@pytest.mark.parametrize("text",["The minimum attendance requirement is 80%. The minimum attendance requirement is 85%.","Unrelated text. "*5000])
def test_ambiguous_or_unbounded_extraction_fails_closed(text):
    with pytest.raises(ValueError): extract_attendance_rule(text)
