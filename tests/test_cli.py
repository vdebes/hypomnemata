import json
from pathlib import Path

import pytest
from conftest import fake_chat

from hypomnemata import cli
from hypomnemata.core.audit import AuditLog
from hypomnemata.core.llm import LLM


def events(log_dir: Path) -> list[str]:
    lines = (log_dir / "audit.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(line)["event"] for line in lines]


def test_journal_creates_entry_and_opens_editor(
    config_file: Path,
    second_brain: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # A fake editor that writes into the entry, as a dictation would.
    monkeypatch.setenv("EDITOR", "sh -c 'echo Bonjour >> \"$0\"'")
    log_dir = tmp_path / "var" / "log"

    assert cli.journal(config_file, log_dir) == 0

    path = Path(capsys.readouterr().out.strip())
    assert path.parent == second_brain / "sources" / "inbox"
    assert path.read_text(encoding="utf-8").endswith("Bonjour\n")
    assert events(log_dir) == ["journal.created", "editor.opened", "editor.closed"]
    closed = json.loads((log_dir / "audit.jsonl").read_text().splitlines()[-1])
    assert closed["chars"] == len("Bonjour")


@pytest.mark.parametrize(
    ("editor", "expected"),
    [
        ("codium --wait", ["codium", "--wait", "--goto", "/e.md:7"]),
        (
            "flatpak run com.vscodium.codium --wait",
            ["flatpak", "run", "com.vscodium.codium", "--wait", "--goto", "/e.md:7"],
        ),
        ("code -w", ["code", "-w", "--goto", "/e.md:7"]),
        ("vim", ["vim", "+7", "/e.md"]),
        ("/usr/bin/nvim", ["/usr/bin/nvim", "+7", "/e.md"]),
        ("nano", ["nano", "/e.md"]),
    ],
)
def test_editor_command_places_cursor(editor: str, expected: list[str]) -> None:
    assert cli.editor_command(editor, Path("/e.md"), 7) == expected


def test_journal_without_editor(
    config_file: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("EDITOR", raising=False)

    assert cli.journal(config_file, tmp_path / "log") == 0
    assert "EDITOR" in capsys.readouterr().out


def test_journal_with_missing_editor(
    config_file: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("EDITOR", "no-such-editor-xyz")
    log_dir = tmp_path / "log"

    assert cli.journal(config_file, log_dir) == 0
    assert "introuvable" in capsys.readouterr().err
    assert events(log_dir)[-1] == "editor.failed"


def test_journal_with_bad_config(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.journal(tmp_path / "absent.toml", tmp_path / "log") == 1
    assert "config.example.toml" in capsys.readouterr().err


def test_main_requires_a_command() -> None:
    with pytest.raises(SystemExit):
        cli.main([])


def scripted(*answers: str) -> cli.Ask:
    remaining = list(answers)

    def ask(prompt: str) -> str:
        print(prompt)
        return remaining.pop(0)

    return ask


def run(config_file: Path, tmp_path: Path, ask: cli.Ask, llm: LLM | None = None) -> int:
    return cli.triage(config_file, tmp_path / "absent.toml", tmp_path / "log", ask, llm)


def write_entry(second_brain: Path, name: str, text: str) -> Path:
    path = second_brain / "sources" / "inbox" / name
    path.write_text(
        "---\ntype: Journal Entry\ntags: [journal]\n"
        "generated: {by: 'human:test-user', at: '2026-10-04T20:15'}\n---\n\n"
        f"# Quiet Otter\n\n{text}\n",
        encoding="utf-8",
    )
    return path


def test_triage_accepts_the_proposal(
    config_file: Path, second_brain: Path, tmp_path: Path, llm: LLM
) -> None:
    source = write_entry(second_brain, "2026-10-04-quiet-otter.md", "Ça marche.")

    assert run(config_file, tmp_path, scripted("o", "", "", "o"), llm) == 0
    assert not source.exists()
    assert (second_brain / "sources" / "journal" / "2026-10-04-un-premier-essai-reussi.md").exists()


def test_triage_with_corrections(
    config_file: Path, second_brain: Path, tmp_path: Path, llm: LLM
) -> None:
    write_entry(second_brain, "2026-10-04-quiet-otter.md", "Ça marche.")

    run(config_file, tmp_path, scripted("o", "Mon titre", "pro, Moto", "o"), llm)

    filed = second_brain / "sources" / "journal" / "2026-10-04-mon-titre.md"
    assert "tags: [journal, pro, moto]" in filed.read_text(encoding="utf-8")


def test_triage_cancel_skip_and_quit(
    config_file: Path, second_brain: Path, tmp_path: Path, llm: LLM
) -> None:
    first = write_entry(second_brain, "2026-10-04-a.md", "Premier.")
    second = write_entry(second_brain, "2026-10-04-b.md", "Deuxième.")
    third = write_entry(second_brain, "2026-10-04-c.md", "Troisième.")

    run(config_file, tmp_path, scripted("o", "", "", "n", "n", "q"), llm)

    assert first.exists() and second.exists() and third.exists()
    assert list((second_brain / "sources" / "journal").iterdir()) == []


def test_triage_without_models_asks_for_the_title(
    config_file: Path, second_brain: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_entry(second_brain, "2026-10-04-quiet-otter.md", "Ça marche.")

    run(config_file, tmp_path, scripted("o", "", "Titre manuel", "", "o"))

    out = capsys.readouterr().out
    assert "models.example.toml" in out
    assert (second_brain / "sources" / "journal" / "2026-10-04-titre-manuel.md").exists()


def test_triage_skips_empty_and_foreign_files(
    config_file: Path, second_brain: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_entry(second_brain, "2026-10-04-empty.md", "")
    (second_brain / "sources" / "inbox" / "note.md").write_text("Sans frontmatter\n")

    assert cli.triage(config_file, tmp_path / "absent.toml", tmp_path / "log", scripted()) == 0

    out = capsys.readouterr().out
    assert "Ignoré" in out
    assert "Entrée vide" in out


def test_triage_with_empty_inbox(
    config_file: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.triage(config_file, tmp_path / "m.toml", tmp_path / "log", scripted()) == 0
    assert "Aucune entrée" in capsys.readouterr().out


def test_triage_stops_on_end_of_input(
    config_file: Path, second_brain: Path, tmp_path: Path, llm: LLM
) -> None:
    source = write_entry(second_brain, "2026-10-04-quiet-otter.md", "Ça marche.")

    def closed(prompt: str) -> str:
        raise EOFError

    assert cli.triage(config_file, tmp_path / "m.toml", tmp_path / "log", closed, llm) == 0
    assert source.exists()


def test_triage_records_the_decision_even_when_cancelled(
    config_file: Path, second_brain: Path, tmp_path: Path, llm: LLM
) -> None:
    write_entry(second_brain, "2026-10-04-quiet-otter.md", "Ça marche.")

    run(config_file, tmp_path, scripted("o", "", "test", "n"), llm)

    assert events(tmp_path / "log")[-2:] == ["triage.decision", "triage.cancelled"]


def test_format_command_formats_the_latest_entry(
    config_file: Path, second_brain: Path, tmp_path: Path, audit: object
) -> None:
    path = write_entry(second_brain, "2026-10-04-quiet-otter.md", "ça marche je crois")
    llm = LLM("fake:1b", AuditLog(tmp_path / "log"), fake_chat({"text": "Ça marche, je crois."}))

    assert cli.format_command(config_file, tmp_path / "m.toml", tmp_path / "log", None, llm) == 0
    assert path.read_text(encoding="utf-8").endswith("\n\nÇa marche, je crois.\n")


def test_format_command_reports_a_rejection(
    config_file: Path, second_brain: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_entry(second_brain, "2026-10-04-quiet-otter.md", "ça marche")
    llm = LLM("fake:1b", AuditLog(tmp_path / "log"), fake_chat({"text": "Ça fonctionne."}))

    assert (
        cli.format_command(config_file, tmp_path / "m.toml", tmp_path / "log", path.name, llm) == 1
    )
    assert "rejetée" in capsys.readouterr().err


def test_format_command_without_entry_or_models(
    config_file: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.format_command(config_file, tmp_path / "m.toml", tmp_path / "log") == 1
    assert "models.example.toml" in capsys.readouterr().err
    llm = LLM("fake:1b", AuditLog(tmp_path / "log"), fake_chat({"text": ""}))
    assert cli.format_command(config_file, tmp_path / "m.toml", tmp_path / "log", None, llm) == 1


def test_format_command_refuses_files_outside_the_inbox(
    config_file: Path, second_brain: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    filed = second_brain / "sources" / "journal" / "2026-10-04-classee.md"
    filed.write_text("---\ntype: Journal Entry\n---\n\nTexte\n", encoding="utf-8")
    llm = LLM("fake:1b", AuditLog(tmp_path / "log"), fake_chat({"text": "Texte."}))

    for target in (str(filed), "../journal/2026-10-04-classee.md", "/etc/passwd"):
        code = cli.format_command(config_file, tmp_path / "m.toml", tmp_path / "log", target, llm)
        assert code == 1
    assert "n'est pas une entrée de journal de l'inbox" in capsys.readouterr().err
    assert filed.read_text(encoding="utf-8").endswith("Texte\n")
