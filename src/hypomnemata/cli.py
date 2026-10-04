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
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path

from hypomnemata.core import format as core_format
from hypomnemata.core import triage as core_triage
from hypomnemata.core.audit import AuditLog
from hypomnemata.core.config import Config, ConfigError, load_config, load_models
from hypomnemata.core.journal import Entry, JournalError, body_length, create_entry
from hypomnemata.core.llm import LLM, LLMError

# src/hypomnemata/cli.py -> repository root. Config and logs live there for now.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = PROJECT_ROOT / "config.local.toml"
MODELS_PATH = PROJECT_ROOT / "models.local.toml"
LOG_DIR = PROJECT_ROOT / "var" / "log"
PREVIEW_CHARS = 300

Ask = Callable[[str], str]


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


def ask_tags(ask: Ask, default: list[str]) -> list[str]:
    shown = ", ".join(tag for tag in default if tag != "journal")
    while True:
        answer = ask(f"Tags [{shown}] : ").strip()
        try:
            return core_triage.normalize_tags(answer.replace(",", " ").split() or default)
        except core_triage.TriageError as error:
            print(error)


def triage_one(config: Config, entry: Entry, llm: LLM | None, audit: AuditLog, ask: Ask) -> bool:
    """Walk one entry through the triage. Returns False when the user wants to stop."""
    print(f"\n── {entry.path.name} ({len(entry.body)} caractères)")
    if not entry.body:
        print("Entrée vide : rien à classer.")
        return True
    preview = entry.body[:PREVIEW_CHARS]
    print(preview + ("…" if len(entry.body) > PREVIEW_CHARS else ""))
    choice = ask("Classer cette entrée ? [o]ui / [n]on / [q]uitter : ").strip().lower()
    if choice == "q":
        return False
    if choice != "o":
        audit.record("triage.skipped", path=entry.path)
        return True

    proposal = None
    if llm:
        print(f"Proposition du modèle ({llm.model})…", flush=True)
        try:
            proposal = core_triage.propose(entry, llm)
        except LLMError as error:
            print(f"{error}\nSaisis le titre toi-même.")

    title = ""
    while not title:
        default = proposal.title if proposal else ""
        title = ask(f"Titre [{default}] : " if default else "Titre : ").strip() or default
    tags = ask_tags(ask, proposal.tags if proposal else ["personnel"])
    core_triage.record_decision(audit, entry, proposal, title, tags)

    try:
        stem = core_triage.destination(entry, title)
    except core_triage.TriageError as error:
        print(error)
        return True
    print(f"→ sources/journal/{stem}.md  ·  tags : {', '.join(tags)}")
    if ask("Classer et commiter ? [o/N] : ").strip().lower() != "o":
        audit.record("triage.cancelled", path=entry.path)
        return True
    try:
        path, commit = core_triage.file_entry(config, entry, title, tags, audit)
    except (core_triage.TriageError, JournalError) as error:
        print(error, file=sys.stderr)
        return True
    print(f"Classé : {path.name} (commit {commit})")
    return True


def triage(
    config_path: Path,
    models_path: Path,
    log_dir: Path,
    ask: Ask = input,
    llm: LLM | None = None,
) -> int:
    audit = AuditLog(log_dir)
    try:
        config = load_config(config_path)
    except ConfigError as error:
        print(error, file=sys.stderr)
        return 1
    entries, skipped = core_triage.pending(config)
    for _path, reason in skipped:
        print(f"Ignoré : {reason}")
    if not entries:
        print("Aucune entrée de journal à classer dans l'inbox.")
        return 0
    if llm is None:
        try:
            llm = LLM(load_models(models_path).resolve("small"), audit)
        except ConfigError as error:
            print(f"{error}\nPas de proposition automatique : titres saisis à la main.")
    try:
        for entry in entries:
            if not triage_one(config, entry, llm, audit, ask):
                break
    except (EOFError, KeyboardInterrupt):
        print()
    return 0


def format_command(
    config_path: Path,
    models_path: Path,
    log_dir: Path,
    target: Path | None = None,
    llm: LLM | None = None,
) -> int:
    audit = AuditLog(log_dir)
    try:
        config = load_config(config_path)
        if llm is None:
            llm = LLM(load_models(models_path).resolve("small"), audit)
    except ConfigError as error:
        print(error, file=sys.stderr)
        return 1
    path = target or core_format.latest_entry(config.inbox)
    if path is None or not path.is_file():
        print("Aucune entrée à mettre en forme.", file=sys.stderr)
        return 1
    print(f"Mise en forme de {path.name} ({llm.model})…", flush=True)
    try:
        changed = core_format.format_entry(path, llm, audit)
    except (core_format.FormatError, LLMError) as error:
        print(error, file=sys.stderr)
        return 1
    print("Fait : ton éditeur recharge le fichier." if changed else "Entrée vide : rien à faire.")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hypomnemata")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("journal", help="crée une entrée de journal vide dans l'inbox")
    commands.add_parser(
        "triage", help="classe les entrées de journal de l'inbox (titre, tags, commit)"
    )
    format_parser = commands.add_parser(
        "format",
        help="ponctue et découpe en paragraphes une entrée dictée (la plus récente par défaut)",
    )
    format_parser.add_argument("entry", nargs="?", type=Path, help="fichier de l'entrée")
    args = parser.parse_args(argv)
    if args.command == "triage":
        return triage(CONFIG_PATH, MODELS_PATH, LOG_DIR)
    if args.command == "format":
        return format_command(CONFIG_PATH, MODELS_PATH, LOG_DIR, args.entry)
    return journal(CONFIG_PATH, LOG_DIR)


if __name__ == "__main__":
    sys.exit(main())
