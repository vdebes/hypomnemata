"""The /triage command, alpha scope: file journal entries from the inbox.

The model proposes a title and tags; the user confirms or corrects them;
the code renames the entry (slug of the title), moves it to
sources/journal/ and commits it. Every step goes to the audit log, including
what the user did with the proposal: that is the signal to improve on.
"""

import re
import unicodedata
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

from hypomnemata.core import git
from hypomnemata.core.audit import AuditLog
from hypomnemata.core.config import Config
from hypomnemata.core.journal import (
    TAG_PATTERN,
    Entry,
    JournalError,
    read_entry,
    render,
    write_exclusive,
)
from hypomnemata.core.llm import LLM

Tag = Annotated[str, StringConstraints(pattern=TAG_PATTERN)]

SYSTEM = """\
Tu proposes un titre et des tags pour une entrée de journal personnel écrite en français.

Titre : 3 à 6 mots, en français, sans ponctuation finale. Il capture l'idée \
principale de l'entrée, pas son premier sujet. Exemples de ton : \
"Points de choix", "Vertiges face au néant", "Démons à bord du navire".

Tags : 1 à 3 tags en minuscules, sans accents, mots séparés par des tirets. \
Le premier est "personnel" ou "professionnel" selon le contenu. \
Les suivants nomment les thèmes principaux. N'inclus pas le tag "journal".

Réponds uniquement avec le JSON demandé."""


class TriageError(Exception):
    """The entry could not be filed. The message is meant for the user."""


class Proposal(BaseModel):
    title: str = Field(min_length=3, max_length=80)
    tags: list[Tag] = Field(min_length=1, max_length=4)


def pending(config: Config) -> tuple[list[Entry], list[tuple[Path, str]]]:
    """Journal entries waiting in the inbox, and the other files with why they are skipped."""
    entries: list[Entry] = []
    skipped: list[tuple[Path, str]] = []
    for path in sorted(config.inbox.glob("*.md")):
        try:
            entries.append(read_entry(path))
        except JournalError as error:
            skipped.append((path, str(error)))
    return entries, skipped


def propose(entry: Entry, llm: LLM) -> Proposal:
    return llm.ask(SYSTEM, entry.body, Proposal)


def slugify(title: str) -> str:
    # Ligatures have no decomposition: spell them out before dropping accents.
    title = title.lower().replace("œ", "oe").replace("æ", "ae")
    ascii_title = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_title.lower()).strip("-")


def normalize_tags(tags: list[str]) -> list[str]:
    """`journal` first, then the given tags in order, without duplicates."""
    result = ["journal"]
    for tag in (tag.strip().lower() for tag in tags):
        if tag and tag not in result:
            if not re.fullmatch(TAG_PATTERN, tag):
                raise TriageError(f"Tag invalide : {tag!r} (minuscules, chiffres et tirets)")
            result.append(tag)
    return result


def destination(entry: Entry, title: str) -> str:
    """Stem of the filed entry: its date, then the slug of its title."""
    slug = slugify(title)
    if not slug:
        raise TriageError(f"Impossible de tirer un nom de fichier de {title!r}")
    return f"{entry.frontmatter.generated.at[:10]}-{slug}"


def record_decision(
    audit: AuditLog, entry: Entry, proposal: Proposal | None, title: str, tags: list[str]
) -> None:
    """What the user did with the proposal: the signal to improve the harness on."""
    tags = normalize_tags(tags)
    audit.record(
        "triage.decision",
        path=entry.path,
        proposed=proposal.model_dump() if proposal else None,
        chosen={"title": title, "tags": tags},
        title_accepted=proposal is not None and proposal.title == title,
        tags_accepted=proposal is not None and normalize_tags(proposal.tags) == tags,
    )


def file_entry(
    config: Config, entry: Entry, title: str, tags: list[str], audit: AuditLog
) -> tuple[Path, str]:
    """Rename, move and commit an entry. Returns its new path and the commit hash."""
    repo = config.second_brain
    if not git.is_repo(repo):
        raise TriageError(f"{repo} n'est pas un dépôt Git : rien n'a été déplacé.")
    if not config.journal.is_dir():
        raise TriageError(f"Dossier introuvable : {config.journal}")

    tags = normalize_tags(tags)
    frontmatter = entry.frontmatter.model_copy(update={"title": title, "tags": tags})
    content = render(frontmatter, heading=title, body=entry.body)
    new_path = write_exclusive(config.journal, destination(entry, title), content)
    was_tracked = git.is_tracked(repo, entry.path)
    entry.path.unlink()
    audit.record("triage.moved", source=entry.path, destination=new_path)

    paths = [new_path, entry.path] if was_tracked else [new_path]
    message = (
        f"Classement : {title}\n\n"
        f"{entry.path.relative_to(repo)} → {new_path.relative_to(repo)}\n"
        f"Tags : {', '.join(tags)}\n\n"
        "Classé par Hypomnemata."
    )
    try:
        commit = git.commit_paths(repo, paths, message)
    except git.GitError as error:
        audit.record("triage.commit_failed", path=new_path, error=str(error))
        raise TriageError(f"Entrée déplacée mais pas commitée : {error}") from error
    audit.record("triage.committed", path=new_path, commit=commit)
    return new_path, commit
