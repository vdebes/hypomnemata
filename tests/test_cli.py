import json
from pathlib import Path

import pytest

from hypomnemata import cli


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
