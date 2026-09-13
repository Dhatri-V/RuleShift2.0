"""Run the labelled attendance evaluation without a model or live database."""
import json
from pathlib import Path
from types import SimpleNamespace

from langchain_core.documents import Document
import ai.rag as rag
from core.attendance_source import attendance_provisions

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "evaluation" / "attendance_cases.json"
REPORT = ROOT / "reports" / "attendance_evaluation.json"


class RefusingModel:
    def invoke(self, prompt):
        return SimpleNamespace(content=rag.INSUFFICIENT_EVIDENCE_ANSWER)


def run():
    cases = json.loads(DATASET.read_text())
    results = []
    for case in cases:
        source_values = {
            fact["value"] for item in case["evidence"]
            if item["version"] == case["selected_version"]
            for fact in attendance_provisions(item["text"])
        }
        if "stored_value" in case:
            state = "SOURCE_MISMATCH" if source_values != {float(case["stored_value"])} else "MATCH"
            answer = f"{next(iter(source_values)):g}%" if source_values else ""
            citations = [item for item in case["evidence"] if item["version"] == case["selected_version"]]
        else:
            documents = [Document(
                page_content=item["text"],
                metadata={"policy_name":"Evaluation Policy", "version":item["version"], "page_number":item["page"],
                          "policy_id":1, "version_id":int(item["version"]), "clause_id":index + 1,
                          "source_sha256":"0" * 64, "start_offset":0, "end_offset":len(item["text"])},
            ) for index, item in enumerate(case["evidence"])]
            original_retrieve, original_llm = rag.retrieve_policy_chunks, rag.get_llm
            try:
                rag.retrieve_policy_chunks = lambda *_: documents
                rag.get_llm = lambda: RefusingModel()
                output = rag.answer_policy_question("Evaluation Policy", case["selected_version"], case["question"])
            finally:
                rag.retrieve_policy_chunks, rag.get_llm = original_retrieve, original_llm
            state, answer, citations = output["answer_state"], output["answer"], output["citations"]
        citation_ok = case["expected_page"] is None or any(item.get("page_number", item.get("page")) == case["expected_page"] for item in citations)
        no_stale = all(item.get("version") == case["selected_version"] for item in citations)
        passed = state == case["expected_state"] and case["answer_contains"].lower() in answer.lower() and citation_ok and no_stale
        results.append({"id":case["id"], "passed":passed, "actual_state":state, "citation_ok":citation_ok, "no_stale_citation":no_stale})
    total = len(results)
    passed = sum(item["passed"] for item in results)
    report = {
        "dataset": str(DATASET.relative_to(ROOT)), "total":total, "passed":passed,
        "accuracy": passed / total, "citation_correctness": sum(item["citation_ok"] for item in results) / total,
        "stale_citation_rate": sum(not item["no_stale_citation"] for item in results) / total,
        "results":results,
    }
    REPORT.parent.mkdir(exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(run())
