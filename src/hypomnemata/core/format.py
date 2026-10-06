"""The /format command: punctuate and paragraph a dictated entry.

Dictation gives long blocks with missing punctuation. A small model adds
punctuation, capitals and paragraph breaks, one chunk of about 1500
characters at a time (small calls stay fast and far from the context
limit). For each chunk the code checks that the words are exactly the
same, in the same order. If the model changed words, the user is shown
the changes and decides; by default the chunk is kept as dictated: the
model may format, never rewrite what was said without the user agreeing.
"""

import difflib
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel

from hypomnemata.core.audit import AuditLog
from hypomnemata.core.journal import JournalError, read_entry, split
from hypomnemata.core.llm import LLM, LLMError

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

CHUNK_CHARS = 1500
MAX_TOKENS = 2048  # a 1500-character chunk needs about 500; more means a runaway answer

Change = tuple[str, str]  # (words before, words after)
Progress = Callable[[int, int], None]  # (chunk number, total), before each chunk
Review = Callable[[list[Change]], bool]  # the model changed words: accept the chunk?


class FormatError(Exception):
    """The entry was not formatted. The message is meant for the user."""


class Formatted(BaseModel):
    text: str


@dataclass(frozen=True)
class Chunk:
    text: str
    glue: str  # joins it to the previous chunk: "\n\n" between paragraphs, " " inside one


@dataclass
class FormatReport:
    chunks: int = 0
    formatted: int = 0  # words unchanged
    accepted: int = 0  # words changed, accepted by the user
    kept: int = 0  # words changed, refused: kept as dictated
    failed: int = 0  # no valid answer from the model: kept as dictated
    appended: int = 0  # characters dictated meanwhile, kept after the formatted text


def words(text: str) -> list[str]:
    """The words of a text, ignoring case, punctuation, apostrophes and hyphens."""
    return re.findall(r"\w+", text.lower())


def changes(before: str, after: str) -> list[Change]:
    """The words that differ between two texts, as (before, after) pairs."""
    old, new = words(before), words(after)
    matcher = difflib.SequenceMatcher(a=old, b=new, autojunk=False)
    return [
        (" ".join(old[i1:i2]), " ".join(new[j1:j2]))
        for tag, i1, i2, j1, j2 in matcher.get_opcodes()
        if tag != "equal"
    ]


def _pack(units: list[str], size: int) -> list[str]:
    parts: list[str] = []
    for unit in units:
        if parts and len(parts[-1]) + 1 + len(unit) <= size:
            parts[-1] += " " + unit
        else:
            parts.append(unit)
    return parts


def _fit(paragraph: str, size: int) -> list[str]:
    """Cut a paragraph between sentences, or between words for an endless sentence."""
    if len(paragraph) <= size:
        return [paragraph]
    units: list[str] = []
    for sentence in re.split(r"(?<=[.!?…])\s+", paragraph):
        units.extend([sentence] if len(sentence) <= size else _pack(sentence.split(), size))
    return _pack(units, size)


def chunks(body: str, size: int = CHUNK_CHARS) -> list[Chunk]:
    """Cut a body into chunks of at most `size` characters (a single word may exceed it)."""
    pieces: list[Chunk] = []
    for paragraph in re.split(r"\n\s*\n", body):
        if paragraph.strip():
            glue = "\n\n"
            for part in _fit(paragraph.strip(), size):
                pieces.append(Chunk(part, glue))
                glue = " "
    packed: list[Chunk] = []
    for piece in pieces:
        if packed and len(packed[-1].text) + len(piece.glue) + len(piece.text) <= size:
            packed[-1] = Chunk(packed[-1].text + piece.glue + piece.text, packed[-1].glue)
        else:
            packed.append(piece)
    return packed


def _format_chunk(
    text: str, number: int, llm: LLM, audit: AuditLog, path: Path, review: Review | None
) -> tuple[str, str]:
    """The chunk to write, and what happened to it."""
    try:
        formatted = llm.ask(SYSTEM, text, Formatted, max_tokens=MAX_TOKENS).text.strip()
    except LLMError as error:
        audit.record("format.chunk_failed", path=path, chunk=number, error=str(error))
        return text, "failed"
    diff = changes(text, formatted)
    if not diff:
        return formatted, "formatted"
    accepted = review is not None and review(diff)
    audit.record("format.chunk_changed", path=path, chunk=number, changes=diff, accepted=accepted)
    return (formatted, "accepted") if accepted else (text, "kept")


def format_entry(
    path: Path,
    llm: LLM,
    audit: AuditLog,
    progress: Progress | None = None,
    review: Review | None = None,
) -> FormatReport | None:
    """Format the body of `path` in place, chunk by chunk. None when there is nothing to do."""
    text = path.read_text(encoding="utf-8")
    body = split(text)[1]
    if not body:
        return None

    pieces = chunks(body)
    report = FormatReport(chunks=len(pieces))
    output = ""
    for number, chunk in enumerate(pieces, start=1):
        if progress:
            progress(number, len(pieces))
        result, status = _format_chunk(chunk.text, number, llm, audit, path, review)
        setattr(report, status, getattr(report, status) + 1)
        output += (chunk.glue if output else "") + result
    if not report.formatted and not report.accepted:
        audit.record("format.unchanged", path=path, report=report.__dict__)
        return report

    # Text dictated during the calls was appended at the end: keep it. Any other
    # change (an edit higher up) means the formatted text is stale: write nothing.
    current = path.read_text(encoding="utf-8")
    base = text.rstrip()
    if not current.startswith(base):
        audit.record("format.aborted", path=path)
        raise FormatError("Le fichier a changé pendant la mise en forme : rien n'a été écrit.")
    tail = current[len(base) :]
    report.appended = len(tail.strip())
    prefix = text[: text.rindex(body)]
    ending = tail if tail.strip() else "\n"
    path.write_text(f"{prefix}{output}{ending}", encoding="utf-8")
    audit.record("format.applied", path=path, report=report.__dict__)
    return report


def inbox_entry(inbox: Path, name: str) -> Path:
    """A journal entry waiting in the inbox, given by its name or path.

    Only entries still in the inbox may be formatted: filed sources are
    immutable, and nothing outside the second brain is ever touched.
    """
    path = inbox / Path(name).name
    try:
        read_entry(path)
    except (OSError, JournalError) as error:
        raise FormatError(
            f"{Path(name).name} n'est pas une entrée de journal de l'inbox."
        ) from error
    return path


def latest_entry(inbox: Path) -> Path | None:
    """The most recently modified journal entry of the inbox (other notes are ignored)."""
    entries = []
    for path in inbox.glob("*.md"):
        try:
            read_entry(path)
        except JournalError:
            continue
        entries.append(path)
    return max(entries, key=lambda path: path.stat().st_mtime_ns, default=None)
