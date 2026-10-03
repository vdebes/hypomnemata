import json
import random
import re
from datetime import datetime
from pathlib import Path

import pytest
import yaml

from hypomnemata.core.audit import AuditLog
from hypomnemata.core.config import Config
from hypomnemata.core.journal import (
    ADJECTIVES,
    NOUNS,
    JournalError,
    body_length,
    create_entry,
    random_slug,
)

NOW = datetime(2026, 10, 3, 18, 5)


def same_rng() -> random.Random:
    return random.Random(42)


def read_frontmatter(path: Path) -> dict[str, object]:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    header, _, _ = text[4:].partition("\n---\n")
    data = yaml.safe_load(header)
    assert isinstance(data, dict)
    return data


def test_random_slug_is_adjective_noun() -> None:
    adjective, noun = random_slug(same_rng()).split("-")
    assert adjective in ADJECTIVES
    assert noun in NOUNS


def test_creates_dated_entry_in_inbox(config: Config, audit: AuditLog) -> None:
    slug = random_slug(same_rng())
    path = create_entry(config, audit, NOW, same_rng())

    assert path == config.inbox / f"2026-10-03-{slug}.md"
    assert read_frontmatter(path) == {
        "type": "Journal Entry",
        "tags": ["journal"],
        "generated": {"by": "human:test-user", "at": "2026-10-03T18:05"},
    }
    assert path.read_text().endswith(f"\n# {slug.replace('-', ' ').title()}\n\n")
    assert body_length(path) == 0


def test_name_without_rng_is_random(config: Config, audit: AuditLog) -> None:
    path = create_entry(config, audit, NOW)
    assert re.fullmatch(r"2026-10-03-[a-z]+-[a-z]+\.md", path.name)


def test_never_overwrites_an_entry(config: Config, audit: AuditLog) -> None:
    first = create_entry(config, audit, NOW, same_rng())
    first.write_text(first.read_text() + "Déjà écrit.\n", encoding="utf-8")

    second = create_entry(config, audit, NOW, same_rng())

    assert second.name == f"{first.stem}-2.md"
    assert first.read_text().endswith("Déjà écrit.\n")


def test_records_creation_in_audit_log(config: Config, audit: AuditLog) -> None:
    path = create_entry(config, audit, NOW)

    event = json.loads(audit.path.read_text(encoding="utf-8"))
    assert event["event"] == "journal.created"
    assert event["path"] == str(path)


def test_missing_inbox_is_an_error(config: Config, audit: AuditLog) -> None:
    config.inbox.rmdir()
    with pytest.raises(JournalError, match="inbox"):
        create_entry(config, audit, NOW)


def test_body_length_ignores_frontmatter_and_heading(config: Config, audit: AuditLog) -> None:
    path = create_entry(config, audit, NOW)
    path.write_text(path.read_text() + "Bonjour.\n\n", encoding="utf-8")
    assert body_length(path) == len("Bonjour.")


def test_body_length_without_frontmatter_nor_heading(tmp_path: Path) -> None:
    path = tmp_path / "plain.md"
    path.write_text("Juste du texte.\n", encoding="utf-8")
    assert body_length(path) == len("Juste du texte.")
