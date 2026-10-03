"""Command-line interface: a thin layer that calls the core.

Temporary entry point until the TUI exists. It only parses arguments,
calls the core and prints results; all the work lives in core/.
"""

import argparse
import os
import shlex
import subprocess
import sys
import time
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from hypomnemata.core.audit import AuditLog
from hypomnemata.core.config import ConfigError, load_config
from hypomnemata.core.journal import JournalError, body_length, create_entry

# src/hypomnemata/cli.py -> repository root. Config and logs live there for now.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = PROJECT_ROOT / "config.local.toml"
LOG_DIR = PROJECT_ROOT / "var" / "log"


def editor_command(editor: str, path: Path, line: int) -> list[str]:
    """Build the command opening `path` with the cursor on `line`, when the editor allows it."""
    tokens = shlex.split(editor)
    if any("codium" in token or Path(token).name == "code" for token in tokens):
        return [*tokens, "--goto", f"{path}:{line}"]
    if Path(tokens[0]).name in {"vi", "vim", "nvim"}:
        return [*tokens, f"+{line}", str(path)]
    return [*tokens, str(path)]


def open_in_editor(path: Path, audit: AuditLog) -> None:
    editor = os.environ.get("EDITOR")
    if not editor:
        print("EDITOR n'est pas défini : ouvre le fichier toi-même.")
        return
    # Cursor on the last line: below the frontmatter and the heading.
    line = path.read_text(encoding="utf-8").count("\n") + 1
    command = editor_command(editor, path, line)
    audit.record("editor.opened", command=command)
    start = time.monotonic()
    try:
        result = subprocess.run(command, check=False)
    except FileNotFoundError:
        audit.record("editor.failed", command=command)
        print(f"Éditeur introuvable : {command[0]}", file=sys.stderr)
        return
    audit.record(
        "editor.closed",
        returncode=result.returncode,
        seconds=round(time.monotonic() - start, 1),
        chars=body_length(path),
    )


def journal(config_path: Path, log_dir: Path) -> int:
    audit = AuditLog(log_dir)
    try:
        config = load_config(config_path)
        path = create_entry(config, audit, datetime.now())
    except (ConfigError, JournalError) as error:
        print(error, file=sys.stderr)
        return 1
    print(path)
    open_in_editor(path, audit)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hypomnemata")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("journal", help="crée une entrée de journal vide dans l'inbox")
    parser.parse_args(argv)
    return journal(CONFIG_PATH, LOG_DIR)


if __name__ == "__main__":
    sys.exit(main())
