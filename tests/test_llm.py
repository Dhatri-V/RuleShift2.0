from langchain_core.messages import AIMessage

from ai.llm import get_embeddings, get_llm
from schemas.rule import Rule


def test_generation_adapter_uses_litellm_configuration(monkeypatch):
    monkeypatch.setenv("RULESHIFT_LITELLM_MODEL", "gemini/gemini-3.5-flash-lite")
    monkeypatch.setenv("RULESHIFT_GEMINI_API_KEY", "test-key")

    llm = get_llm()

    assert llm.__class__.__name__ == "ChatLiteLLM"
    assert llm.model == "gemini/gemini-3.5-flash-lite"
    assert llm.api_key == "test-key"
    assert llm.temperature == 0


def test_litellm_invoke_and_structured_output_contract(monkeypatch):
    import litellm

    monkeypatch.setenv("RULESHIFT_GEMINI_API_KEY", "test-key")
    responses = iter([
        {
            "choices": [{
                "message": {"role": "assistant", "content": "grounded answer"},
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        },
        {
            "choices": [{
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{
                        "id": "call-rule",
                        "type": "function",
                        "function": {
                            "name": "Rule",
                            "arguments": '{"attendance_requirement": 80}',
                        },
                    }],
                },
                "finish_reason": "tool_calls",
            }],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        },
    ])
    monkeypatch.setattr(litellm, "completion", lambda **kwargs: next(responses))
    llm = get_llm()

    response = llm.invoke("Answer from context")
    structured = llm.with_structured_output(Rule).invoke("Extract the rule")

    assert isinstance(response, AIMessage)
    assert response.content == "grounded answer"
    assert structured == Rule(attendance_requirement=80)


def test_embeddings_use_gemini_api(monkeypatch):
    monkeypatch.setenv("RULESHIFT_EMBEDDING_PROVIDER", "google")
    monkeypatch.setenv("RULESHIFT_EMBEDDING_MODEL", "gemini-embedding-001")
    monkeypatch.setenv("RULESHIFT_GEMINI_API_KEY", "gemini-key")

    embeddings = get_embeddings()

    assert embeddings.__class__.__name__ == "GoogleGenerativeAIEmbeddings"
    assert embeddings.model == "models/gemini-embedding-001"
