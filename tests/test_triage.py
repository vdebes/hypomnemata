import json
from datetime import datetime
from pathlib import Path

import pytest
import yaml
from conftest import git

from hypomnemata.core.audit import AuditLog
from hypomnemata.core.config import Config
from hypomnemata.core.journal import create_entry, read_entry
from hypomnemata.core.llm import LLM
from hypomnemata.core.triage import (
    Proposal,
    TriageError,
    destination,
    file_entry,
    normalize_tags,
    pending,
    propose,
    record_decision,
    slugify,
)

NOW = datetime(2026, 10, 4, 20, 15)


def written_entry(config: Config, audit: AuditLog, text: str = "Une journée bien remplie.") -> Path:
    path = create_entry(config, audit, NOW)
    path.write_text(path.read_text(encoding="utf-8") + text + "\n", encoding="utf-8")
    return path


def test_pending_keeps_journal_entries_only(config: Config, audit: AuditLog) -> None:
    entry = written_entry(config, audit)
    other = config.inbox / "2026-10-03-compte-rendu.md"
    other.write_text("---\ntype: Decision Log\n---\n\nTexte\n", encoding="utf-8")

    entries, skipped = pending(config)

    assert [e.path for e in entries] == [entry]
    assert [path for path, _ in skipped] == [other]


def test_reads_entries_with_a_bare_yaml_date(config: Config) -> None:
    path = config.inbox / "2026-09-27-hollow-falcon.md"
    path.write_text(
        "---\ntype: Journal Entry\ntags: [journal]\n"
        "generated: { by: human:vdebes, at: 2026-09-27 }\n---\n\n# Hollow Falcon\n\nTexte\n",
        encoding="utf-8",
    )
    entry = read_entry(path)
    assert entry.frontmatter.generated.at == "2026-09-27"
    assert entry.body == "Texte"


def test_propose_sends_the_body_only(config: Config, audit: AuditLog, llm: LLM) -> None:
    written_entry(config, audit)
    [entry], _ = pending(config)
    proposal = propose(entry, llm)

    assert proposal.title == "Un premier essai réussi"
    call = json.loads(audit.path.read_text(encoding="utf-8").splitlines()[-1])
    assert call["prompt"] == "Une journée bien remplie."


@pytest.mark.parametrize(
    ("title", "slug"),
    [
        ("Vertiges face au néant", "vertiges-face-au-neant"),
        ("  L'été, déjà ?! ", "l-ete-deja"),
        ("Œuvre à cœur", "oeuvre-a-coeur"),
    ],
)
def test_slugify(title: str, slug: str) -> None:
    assert slugify(title) == slug


def test_normalize_tags() -> None:
    assert normalize_tags(["Personnel", "journal", "moto", "moto"]) == [
        "journal",
        "personnel",
        "moto",
    ]
    with pytest.raises(TriageError, match="Tag invalide"):
        normalize_tags(["avec espace"])


def test_destination_needs_a_usable_title(config: Config, audit: AuditLog) -> None:
    entry = read_entry(written_entry(config, audit))
    assert destination(entry, "Un titre") == "2026-10-04-un-titre"
    with pytest.raises(TriageError):
        destination(entry, "?!")


def test_file_entry_renames_moves_and_commits(config: Config, audit: AuditLog) -> None:
    source = written_entry(config, audit)
    unrelated = config.second_brain / "unrelated.md"
    unrelated.write_text("not mine\n", encoding="utf-8")

    entry = read_entry(source)
    path, commit = file_entry(config, entry, "Une journée remplie", ["personnel"], audit)

    assert path == config.journal / "2026-10-04-une-journee-remplie.md"
    assert not source.exists()
    text = path.read_text(encoding="utf-8")
    header = yaml.safe_load(text[4:].partition("\n---\n")[0])
    assert header["title"] == "Une journée remplie"
    assert header["tags"] == ["journal", "personnel"]
    assert header["generated"] == {"by": "human:test-user", "at": "2026-10-04T20:15"}
    assert "\n# Une journée remplie\n\nUne journée bien remplie.\n" in text

    assert git(config.second_brain, "rev-parse", "--short", "HEAD").strip() == commit
    committed = git(config.second_brain, "show", "--name-only", "--format=", "HEAD").split()
    assert committed == ["sources/journal/2026-10-04-une-journee-remplie.md"]
    assert "?? unrelated.md" in git(config.second_brain, "status", "--short")

    events = [json.loads(line)["event"] for line in audit.path.read_text().splitlines()]
    assert events[-2:] == ["triage.moved", "triage.committed"]


def test_file_entry_commits_the_removal_of_a_tracked_inbox_file(
    config: Config, audit: AuditLog
) -> None:
    source = written_entry(config, audit)
    git(config.second_brain, "add", ".")
    git(config.second_brain, "commit", "--quiet", "-m", "capture")

    file_entry(config, read_entry(source), "Titre corrigé", ["pro"], audit)

    committed = git(config.second_brain, "show", "--name-status", "--format=", "HEAD")
    # Git sees the move of a tracked file as a rename.
    assert committed.startswith("R")
    assert f"\tsources/inbox/{source.name}\tsources/journal/" in committed
    assert git(config.second_brain, "status", "--short") == ""


def test_refuses_to_file_outside_a_git_repository(config: Config, audit: AuditLog) -> None:
    source = written_entry(config, audit)
    (config.second_brain / ".git").rename(config.second_brain / "not-git")

    with pytest.raises(TriageError, match="dépôt Git"):
        file_entry(config, read_entry(source), "Titre", ["personnel"], audit)
    assert source.exists()
    assert list(config.journal.iterdir()) == []


def last_event(audit: AuditLog) -> dict[str, object]:
    event: dict[str, object] = json.loads(audit.path.read_text().splitlines()[-1])
    return event


def test_record_decision_compares_choice_and_proposal(config: Config, audit: AuditLog) -> None:
    entry = read_entry(written_entry(config, audit))
    proposal = Proposal(title="Test sans fin", tags=["personnel", "doute", "test"])

    record_decision(audit, entry, proposal, "Test sans fin", ["test"])

    decision = last_event(audit)
    assert decision["event"] == "triage.decision"
    assert decision["chosen"] == {"title": "Test sans fin", "tags": ["journal", "test"]}
    assert decision["title_accepted"] is True
    assert decision["tags_accepted"] is False


def test_record_decision_without_proposal(config: Config, audit: AuditLog) -> None:
    entry = read_entry(written_entry(config, audit))
    record_decision(audit, entry, None, "Titre", ["personnel"])

    decision = last_event(audit)
    assert decision["proposed"] is None
    assert decision["title_accepted"] is False
