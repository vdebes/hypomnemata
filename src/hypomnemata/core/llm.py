"""The only module that talks to a language model (through Ollama).

A model's answer is a proposal: it must match a Pydantic schema, otherwise
it is rejected. Every call is recorded in the audit log with its prompt,
its output and its duration, so the model's work can be reviewed.
"""

import time
from collections.abc import Callable

import ollama
from pydantic import BaseModel, ValidationError

from hypomnemata.core.audit import AuditLog

Chat = Callable[..., ollama.ChatResponse]


class LLMError(Exception):
    """The model could not produce a valid answer. The message is meant for the user."""


class LLM:
    def __init__(self, model: str, audit: AuditLog, chat: Chat | None = None) -> None:
        self.model = model
        self.audit = audit
        self.chat = chat or ollama.Client().chat

    def ask[T: BaseModel](
        self, system: str, prompt: str, schema: type[T], max_tokens: int | None = None
    ) -> T:
        """`max_tokens` caps the answer: a runaway generation ends as an invalid answer."""
        start = time.monotonic()
        options: dict[str, int | float] = {"temperature": 0}
        if max_tokens:
            options["num_predict"] = max_tokens
        call = {"model": self.model, "system": system, "prompt": prompt, "schema": schema.__name__}
        try:
            response = self.chat(
                model=self.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                format=schema.model_json_schema(),
                think=False,
                options=options,
            )
        except (ollama.ResponseError, ConnectionError) as error:
            self.audit.record("llm.failed", **call, error=str(error))
            raise LLMError(f"Ollama ne répond pas ({self.model}) : {error}") from error
        output = response.message.content or ""
        seconds = round(time.monotonic() - start, 1)
        try:
            answer = schema.model_validate_json(output)
        except ValidationError as error:
            self.audit.record("llm.invalid", **call, output=output, seconds=seconds)
            message = f"Réponse du modèle invalide : {error.error_count()} erreur(s)"
            raise LLMError(message) from error
        self.audit.record("llm.answered", **call, output=output, seconds=seconds)
        return answer
