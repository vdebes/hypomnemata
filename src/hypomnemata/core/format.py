"""The /format command: punctuate and paragraph a dictated entry.

Dictation gives long blocks with missing punctuation. A small model adds
punctuation, capitals and paragraph breaks; the code then checks that the
words are exactly the same, in the same order. If a single word changed,
the proposal is rejected and the entry is left untouched: the model may
format, never rewrite what was said.
"""

import re
from pathlib import Path

from pydantic import BaseModel

from hypomnemata.core.audit import AuditLog
from hypomnemata.core.journal import split
from hypomnemata.core.llm import LLM

SYSTEM = """\
Tu mets en forme un texte dicté en français, transcrit par reconnaissance vocale.

Tu ajoutes ou corriges uniquement :
- la ponctuation (points, virgules, points d'interrogation pour les questions) ;
- les majuscules en début de phrase ;
- les sauts de paragraphe (ligne vide) quand l'idée change.

Interdit : ajouter, supprimer, remplacer ou déplacer un seul mot, même pour \
corriger une faute ou une erreur de transcription. Garde exactement les mêmes \
mots, dans le même ordre.

Réponds uniquement avec le JSON demandé, le texte mis en forme dans "text"."""


class FormatError(Exception):
    """The entry was not formatted. The message is meant for the user."""


class Formatted(BaseModel):
    text: str


def words(text: str) -> list[str]:
    """The words of a text, ignoring case, punctuation, apostrophes and hyphens."""
    return re.findall(r"\w+", text.lower())


def first_difference(before: list[str], after: list[str]) -> str:
    for index, (old, new) in enumerate(zip(before, after, strict=False)):
        if old != new:
            return f"mot {index + 1} : {old!r} devenu {new!r}"
    return f"{len(before)} mots avant, {len(after)} après"


def format_entry(path: Path, llm: LLM, audit: AuditLog) -> bool:
    """Format the body of `path` in place. Returns False when there is nothing to format."""
    text = path.read_text(encoding="utf-8")
    mtime = path.stat().st_mtime_ns
    body = split(text)[1]
    if not body:
        return False

    formatted = llm.ask(SYSTEM, body, Formatted).text.strip()
    before, after = words(body), words(formatted)
    if before != after:
        difference = first_difference(before, after)
        audit.record("format.rejected", path=path, difference=difference)
        raise FormatError(f"Mise en forme rejetée, le modèle a changé des mots ({difference}).")
    if path.stat().st_mtime_ns != mtime:
        audit.record("format.aborted", path=path)
        raise FormatError("Le fichier a changé pendant la mise en forme : rien n'a été écrit.")

    prefix = text[: text.rindex(body)]
    path.write_text(f"{prefix}{formatted}\n", encoding="utf-8")
    audit.record("format.applied", path=path, chars_before=len(body), chars_after=len(formatted))
    return True


def latest_entry(inbox: Path) -> Path | None:
    """The most recently modified Markdown file of the inbox."""
    entries = sorted(inbox.glob("*.md"), key=lambda path: path.stat().st_mtime_ns)
    return entries[-1] if entries else None
