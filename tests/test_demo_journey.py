"""A clean authenticated demo journey that survives an application restart."""
from types import SimpleNamespace

from fastapi.testclient import TestClient
from langchain_chroma import Chroma
from langchain_core.embeddings import Embeddings
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import ai.rag as rag
from backend.main import app, get_database
from conftest import TEST_ADMIN_EMAIL, TEST_ADMIN_PASSWORD, drop_all_test_schema, make_attendance_pdf
from database.db import Base


class DemoEmbeddings(Embeddings):
    """Deterministic local embeddings while exercising real persistent Chroma."""

    @staticmethod
    def _embed(text):
        lowered = text.lower()
        return [
            float(lowered.count("attendance")),
            float(lowered.count("minimum")),
            float(lowered.count("75")),
            float(lowered.count("85")),
            1.0,
        ]

    def embed_documents(self, texts):
        return [self._embed(text) for text in texts]

    def embed_query(self, text):
        return self._embed(text)


class RefusingModel:
    def invoke(self, prompt):
        return SimpleNamespace(content=rag.INSUFFICIENT_EVIDENCE_ANSWER)


def test_authenticated_demo_journey_and_restart_persistence(tmp_path, monkeypatch):
    database_path = tmp_path / "demo.db"
    chroma_path = tmp_path / "chroma"
    engine = create_engine(f"sqlite:///{database_path}", connect_args={"check_same_thread": False})
    sessions = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    store_holder = {
        "store": Chroma(
            collection_name=rag.COLLECTION_NAME,
            embedding_function=DemoEmbeddings(),
            persist_directory=str(chroma_path),
        )
    }

    def database():
        with sessions() as session:
            yield session

    app.dependency_overrides[get_database] = database
    monkeypatch.setattr(rag, "get_vector_store", lambda: store_holder["store"])
    monkeypatch.setattr(rag, "get_llm", lambda: RefusingModel())

    try:
        with TestClient(app) as client:
            login = client.post("/auth/login", json={
                "email": TEST_ADMIN_EMAIL, "password": TEST_ADMIN_PASSWORD,
            })
            assert login.status_code == 200
            headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

            versions = []
            for label, attendance in (("2025", 75), ("2026", 85)):
                uploaded = client.post(
                    "/policies/upload",
                    headers=headers,
                    data={"policy_name": "Demo Attendance Policy", "version": label},
                    files={"file": (f"demo-{label}.pdf", make_attendance_pdf(attendance), "application/pdf")},
                )
                assert uploaded.status_code == 200, uploaded.text
                draft = uploaded.json()
                assert draft["page_count"] == 1 and draft["chunk_count"] == 1
                verified = client.post(f"/policies/{draft['id']}/verify", headers=headers)
                assert verified.status_code == 200, verified.text
                published = client.post(f"/policies/{draft['id']}/mark-current", headers=headers)
                assert published.status_code == 200, published.text
                versions.append(draft)

            assert client.get("/policies").status_code == 200
            answer = client.post("/ask", json={
                "policy_name": "Demo Attendance Policy",
                "question": "I have exactly 85% attendance. Am I compliant?",
            })
            assert answer.status_code == 200, answer.text
            assert answer.json()["answer_state"] == "ANSWERED"
            assert "exactly 85% attendance is compliant" in answer.json()["answer"]
            assert answer.json()["resolved_policy"]["version"] == "2026"
            assert answer.json()["citations"][0]["version_id"] == versions[1]["id"]

            comparison = client.post("/compare-versions", json={
                "old_policy_id": versions[0]["id"], "new_policy_id": versions[1]["id"],
            })
            assert comparison.status_code == 200, comparison.text
            assert comparison.json()["difference"] == 10
            impact = client.post("/student-impact", json={
                "old_policy_id": versions[0]["id"], "new_policy_id": versions[1]["id"], "attendance": 80,
            })
            assert impact.status_code == 200, impact.text
            assert impact.json()["impact"] == "NEWLY_NON_COMPLIANT"
            run_id = impact.json()["run_id"]
            audit = client.get("/admin/audit", headers=headers)
            assert audit.status_code == 200
            assert {item["action"] for item in audit.json()} >= {
                "POLICY_UPLOADED", "SOURCE_RULE_VERIFIED", "POLICY_PUBLISHED",
            }

        # A second app client and a newly opened Chroma handle simulate restart.
        store_holder["store"] = Chroma(
            collection_name=rag.COLLECTION_NAME,
            embedding_function=DemoEmbeddings(),
            persist_directory=str(chroma_path),
        )
        with TestClient(app) as restarted:
            catalogue = restarted.get("/policies").json()
            assert [(item["version"], item["status"]) for item in catalogue] == [
                ("2025", "SUPERSEDED"), ("2026", "CURRENT"),
            ]
            historical = restarted.get(f"/impact-runs/{run_id}")
            assert historical.status_code == 200
            assert historical.json()["old_evidence"]["value"] == 75
            assert historical.json()["new_evidence"]["value"] == 85
            answer = restarted.post("/ask", json={
                "policy_name": "Demo Attendance Policy",
                "question": "What is the minimum attendance requirement?",
            })
            assert answer.status_code == 200
            assert answer.json()["resolved_policy"]["version"] == "2026"
            assert answer.json()["citations"][0]["version"] == "2026"
    finally:
        app.dependency_overrides.clear()
        drop_all_test_schema(engine)
        engine.dispose()
