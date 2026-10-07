import json
from typing import Any

import ollama
import pytest
from conftest import fake_chat
from pydantic import BaseModel

from hypomnemata.core.audit import AuditLog
from hypomnemata.core.llm import LLM, Embedder, LLMError


class Answer(BaseModel):
    word: str


def events(audit: AuditLog) -> list[dict[str, Any]]:
    return [json.loads(line) for line in audit.path.read_text(encoding="utf-8").splitlines()]


def test_valid_answer_is_parsed_and_recorded(audit: AuditLog) -> None:
    calls: list[dict[str, Any]] = []
    llm = LLM("fake:1b", audit, fake_chat({"word": "ok"}, calls))

    assert llm.ask("system", "prompt", Answer) == Answer(word="ok")

    assert calls[0]["think"] is False
    assert calls[0]["format"] == Answer.model_json_schema()
    [event] = events(audit)
    assert event["event"] == "llm.answered"
    assert event["model"] == "fake:1b"
    assert event["prompt"] == "prompt"
    assert json.loads(event["output"]) == {"word": "ok"}


def test_invalid_answer_is_rejected(audit: AuditLog) -> None:
    llm = LLM("fake:1b", audit, fake_chat("pas du JSON"))

    with pytest.raises(LLMError, match="invalide"):
        llm.ask("system", "prompt", Answer)
    assert events(audit)[0]["event"] == "llm.invalid"


def test_unreachable_ollama(audit: AuditLog) -> None:
    def down(**kwargs: Any) -> ollama.ChatResponse:
        raise ConnectionError("refused")

    with pytest.raises(LLMError, match="Ollama"):
        LLM("fake:1b", audit, down).ask("system", "prompt", Answer)
    assert events(audit)[0]["event"] == "llm.failed"


def test_embedder_returns_one_vector_per_text(audit: AuditLog) -> None:
    def embed(**kwargs: Any) -> ollama.EmbedResponse:
        return ollama.EmbedResponse(embeddings=[[1.0, 2.0] for _ in kwargs["input"]])

    assert Embedder("e", audit, embed).embed(["a", "b"]) == [[1.0, 2.0], [1.0, 2.0]]
    assert events(audit)[-1]["event"] == "embed.computed"


def test_embedder_failures(audit: AuditLog) -> None:
    def down(**kwargs: Any) -> ollama.EmbedResponse:
        raise ConnectionError("refused")

    def short(**kwargs: Any) -> ollama.EmbedResponse:
        return ollama.EmbedResponse(embeddings=[[1.0]])

    with pytest.raises(LLMError, match="Ollama"):
        Embedder("e", audit, down).embed(["a"])
    with pytest.raises(LLMError, match="1 vecteurs pour 2 textes"):
        Embedder("e", audit, short).embed(["a", "b"])
