import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import ollama
import pytest
from conftest import fake_chat

from hypomnemata.core.audit import AuditLog
from hypomnemata.core.format import (
    MAX_TOKENS,
    FormatError,
    changes,
    chunks,
    format_entry,
    latest_entry,
    words,
)
from hypomnemata.core.llm import LLM

HEADER = (
    "---\ntype: Journal Entry\ntags: [journal]\n"
    "generated: {by: 'human:a', at: '2026-10-04'}\n---\n\n# Quiet Otter\n\n"
)
DICTATED = "est-ce que ça marche je crois que oui l'heure système est bonne"
FORMATTED = "Est-ce que ça marche ?\n\nJe crois que oui. L'heure système est bonne."


def entry(tmp_path: Path, body: str = DICTATED) -> Path:
    path = tmp_path / "2026-10-04-quiet-otter.md"
    path.write_text(f"{HEADER}{body}\n", encoding="utf-8")
    return path


def model(audit: AuditLog, text: str) -> LLM:
    return LLM("fake:1b", audit, fake_chat({"text": text}))


def rewriting(audit: AuditLog, rewrite: Callable[[str], str], calls: list[str]) -> LLM:
    """A fake model that answers each chunk with `rewrite(chunk)`."""

    def chat(**kwargs: Any) -> ollama.ChatResponse:
        chunk = kwargs["messages"][-1]["content"]
        calls.append(chunk)
        content = json.dumps({"text": rewrite(chunk)})
        return ollama.ChatResponse(message=ollama.Message(role="assistant", content=content))

    return LLM("fake:1b", audit, chat)


def events(audit: AuditLog) -> list[dict[str, Any]]:
    return [json.loads(line) for line in audit.path.read_text().splitlines()]


def test_words_ignore_case_punctuation_apostrophes_and_hyphens() -> None:
    assert words("Est-ce l'heure ?") == words("est ce l heure") == ["est", "ce", "l", "heure"]


def test_changes_lists_the_differing_words() -> None:
    assert changes("ouais je crois", "Oui, je crois.") == [("ouais", "oui")]
    assert changes("un deux trois", "un trois") == [("deux", "")]


def test_short_body_is_a_single_chunk() -> None:
    assert [c.text for c in chunks(DICTATED)] == [DICTATED]


def test_chunks_respect_the_size_and_keep_every_word() -> None:
    sentence = "une phrase dictée sans fin " * 40  # no punctuation at all
    body = f"Premier paragraphe.\n\n{sentence}\n\nDernier. Encore une phrase."

    parts = chunks(body, size=200)

    assert all(len(c.text) <= 200 for c in parts)
    rebuilt = "".join((c.glue if i else "") + c.text for i, c in enumerate(parts))
    assert words(rebuilt) == words(body)


def test_chunks_cut_between_paragraphs_then_sentences() -> None:
    body = "A. " * 30 + "\n\n" + "B. " * 30

    parts = chunks(body.strip(), size=60)

    assert parts[0].text.startswith("A.")
    glues = {c.glue for c in parts[1:]}
    assert glues == {" ", "\n\n"}


def test_small_paragraphs_are_packed_together() -> None:
    parts = chunks("Un.\n\nDeux.\n\nTrois.", size=100)
    assert [c.text for c in parts] == ["Un.\n\nDeux.\n\nTrois."]


def test_formats_the_body_and_keeps_header_and_heading(tmp_path: Path, audit: AuditLog) -> None:
    path = entry(tmp_path)

    report = format_entry(path, model(audit, FORMATTED), audit)

    assert report is not None and report.formatted == 1
    assert path.read_text(encoding="utf-8") == f"{HEADER}{FORMATTED}\n"
    assert events(audit)[-1]["event"] == "format.applied"


def test_formats_chunk_by_chunk_with_progress(tmp_path: Path, audit: AuditLog) -> None:
    body = "\n\n".join(f"paragraphe {n} " + "mot " * 200 for n in range(4))
    path = entry(tmp_path, body)
    calls: list[str] = []
    seen: list[tuple[int, int]] = []

    report = format_entry(
        path, rewriting(audit, str.upper, calls), audit, progress=lambda n, t: seen.append((n, t))
    )

    assert report is not None and report.chunks == len(calls) > 1
    assert seen == [(n, len(calls)) for n in range(1, len(calls) + 1)]
    assert "PARAGRAPHE 3" in path.read_text(encoding="utf-8")


def test_caps_the_length_of_each_answer(audit: AuditLog, tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []
    format_entry(
        entry(tmp_path), LLM("fake:1b", audit, fake_chat({"text": FORMATTED}, calls)), audit
    )
    assert calls[0]["options"]["num_predict"] == MAX_TOKENS


def test_changed_words_are_kept_as_dictated_by_default(tmp_path: Path, audit: AuditLog) -> None:
    path = entry(tmp_path)
    original = path.read_text(encoding="utf-8")

    report = format_entry(path, model(audit, FORMATTED.replace("oui", "ouais")), audit)

    assert report is not None and report.kept == 1
    assert path.read_text(encoding="utf-8") == original
    changed = next(e for e in events(audit) if e["event"] == "format.chunk_changed")
    assert changed["changes"] == [["oui", "ouais"]]
    assert changed["accepted"] is False


def test_changed_words_accepted_by_the_user(tmp_path: Path, audit: AuditLog) -> None:
    path = entry(tmp_path)
    rewritten = FORMATTED.replace("oui", "ouais")
    reviewed: list[list[tuple[str, str]]] = []

    def accept(diff: list[tuple[str, str]]) -> bool:
        reviewed.append(diff)
        return True

    report = format_entry(path, model(audit, rewritten), audit, review=accept)

    assert report is not None and report.accepted == 1
    assert reviewed == [[("oui", "ouais")]]
    assert path.read_text(encoding="utf-8").endswith(f"{rewritten}\n")


def test_one_bad_chunk_does_not_spoil_the_others(tmp_path: Path, audit: AuditLog) -> None:
    body = "premier " * 150 + "\n\n" + "second " * 150
    path = entry(tmp_path, body)

    def rewrite(chunk: str) -> str:
        return chunk.upper() if chunk.startswith("premier") else chunk.replace("second", "autre")

    report = format_entry(path, rewriting(audit, rewrite, []), audit)

    assert report is not None and (report.formatted, report.kept) == (1, 1)
    text = path.read_text(encoding="utf-8")
    assert "PREMIER" in text and "second" in text and "autre" not in text


def test_failed_chunk_is_kept_and_the_rest_formatted(tmp_path: Path, audit: AuditLog) -> None:
    body = "premier " * 150 + "\n\n" + "second " * 150
    path = entry(tmp_path, body)
    answers = iter([json.dumps({"text": ("premier " * 150).upper()}), "pas du JSON"])

    def chat(**kwargs: Any) -> ollama.ChatResponse:
        content = next(answers)
        return ollama.ChatResponse(message=ollama.Message(role="assistant", content=content))

    report = format_entry(path, LLM("fake:1b", audit, chat), audit)

    assert report is not None and (report.formatted, report.failed) == (1, 1)
    assert "PREMIER" in path.read_text(encoding="utf-8")


def test_empty_entry_is_left_alone(tmp_path: Path, audit: AuditLog) -> None:
    assert format_entry(entry(tmp_path, ""), model(audit, "x"), audit) is None


def test_keeps_text_dictated_during_the_call(tmp_path: Path, audit: AuditLog) -> None:
    path = entry(tmp_path)

    def chat_while_dictating(**kwargs: Any) -> ollama.ChatResponse:
        path.write_text(path.read_text() + "\nencore un mot\n", encoding="utf-8")
        return fake_chat({"text": FORMATTED})(**kwargs)

    report = format_entry(path, LLM("fake:1b", audit, chat_while_dictating), audit)

    assert report is not None and report.appended == len("encore un mot")
    assert path.read_text(encoding="utf-8") == f"{HEADER}{FORMATTED}\n\nencore un mot\n"


def test_aborts_if_the_text_was_edited_above(tmp_path: Path, audit: AuditLog) -> None:
    path = entry(tmp_path)

    def chat_while_editing(**kwargs: Any) -> ollama.ChatResponse:
        path.write_text(path.read_text().replace("marche", "fonctionne"), encoding="utf-8")
        return fake_chat({"text": FORMATTED})(**kwargs)

    with pytest.raises(FormatError, match="a changé"):
        format_entry(path, LLM("fake:1b", audit, chat_while_editing), audit)
    assert "fonctionne" in path.read_text(encoding="utf-8")


def test_latest_entry_ignores_other_notes(tmp_path: Path) -> None:
    assert latest_entry(tmp_path) is None
    old = tmp_path / "2026-10-04-a.md"
    old.write_text(f"{HEADER}A\n", encoding="utf-8")
    new = tmp_path / "2026-10-04-b.md"
    new.write_text(f"{HEADER}B\n", encoding="utf-8")
    note = tmp_path / "2026-10-04-compte-rendu.md"
    note.write_text("---\ntype: Decision Log\n---\n\nNote\n", encoding="utf-8")
    os.utime(old, ns=(1, 1))

    assert latest_entry(tmp_path) == new
