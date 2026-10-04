import json
from pathlib import Path

import pytest
from conftest import fake_chat

from hypomnemata.core.audit import AuditLog
from hypomnemata.core.format import FormatError, format_entry, latest_entry, words
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


def test_words_ignore_case_punctuation_apostrophes_and_hyphens() -> None:
    assert words("Est-ce l'heure ?") == words("est ce l heure") == ["est", "ce", "l", "heure"]


def test_formats_the_body_and_keeps_header_and_heading(tmp_path: Path, audit: AuditLog) -> None:
    path = entry(tmp_path)

    assert format_entry(path, model(audit, FORMATTED), audit)

    assert path.read_text(encoding="utf-8") == f"{HEADER}{FORMATTED}\n"
    event = json.loads(audit.path.read_text().splitlines()[-1])
    assert event["event"] == "format.applied"


def test_rejects_a_changed_word_and_leaves_the_file(tmp_path: Path, audit: AuditLog) -> None:
    path = entry(tmp_path)
    original = path.read_text(encoding="utf-8")
    rewritten = FORMATTED.replace("L'heure système", "Leur système")

    with pytest.raises(FormatError, match="'l' devenu 'leur'"):
        format_entry(path, model(audit, rewritten), audit)

    assert path.read_text(encoding="utf-8") == original
    assert json.loads(audit.path.read_text().splitlines()[-1])["event"] == "format.rejected"


def test_rejects_a_dropped_word(tmp_path: Path, audit: AuditLog) -> None:
    path = entry(tmp_path)
    with pytest.raises(FormatError, match="mots avant"):
        format_entry(path, model(audit, FORMATTED.removesuffix(" bonne.")), audit)


def test_empty_entry_is_left_alone(tmp_path: Path, audit: AuditLog) -> None:
    assert not format_entry(entry(tmp_path, ""), model(audit, "x"), audit)


def test_aborts_if_the_file_changed_meanwhile(tmp_path: Path, audit: AuditLog) -> None:
    path = entry(tmp_path)

    def chat_while_dictating(**kwargs: object) -> object:
        path.write_text(path.read_text() + "encore un mot\n", encoding="utf-8")
        return fake_chat({"text": FORMATTED})(**kwargs)

    with pytest.raises(FormatError, match="a changé"):
        format_entry(path, LLM("fake:1b", audit, chat_while_dictating), audit)  # type: ignore[arg-type]
    assert path.read_text().endswith("encore un mot\n")


def test_latest_entry_ignores_other_notes(tmp_path: Path) -> None:
    import os

    assert latest_entry(tmp_path) is None
    old = tmp_path / "2026-10-04-a.md"
    old.write_text(f"{HEADER}A\n", encoding="utf-8")
    new = tmp_path / "2026-10-04-b.md"
    new.write_text(f"{HEADER}B\n", encoding="utf-8")
    note = tmp_path / "2026-10-04-compte-rendu.md"
    note.write_text("---\ntype: Decision Log\n---\n\nNote\n", encoding="utf-8")
    os.utime(old, ns=(1, 1))

    assert latest_entry(tmp_path) == new
