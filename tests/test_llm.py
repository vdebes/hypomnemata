import json
from typing import Any

import ollama
import pytest
from conftest import fake_chat
from pydantic import BaseModel

from hypomnemata.core.audit import AuditLog
from hypomnemata.core.llm import LLM, LLMError


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
