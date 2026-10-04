"""Journal entries: their format, and the /journal command that creates them.

No model is involved here: the filename, the date and the frontmatter are
produced by code. A new entry gets a random adjective-noun placeholder name;
the real title and tags are proposed when the entry is filed (see triage.py).
"""

import random
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from hypomnemata.core.audit import AuditLog
from hypomnemata.core.config import Config, describe

ADJECTIVES = (
    "radical", "quiet", "stubborn", "wandering", "curious", "restless",
    "steady", "blunt", "tangled", "hollow", "electric", "patient",
    "reckless", "faded", "sudden", "wild", "careful", "distracted",
    "brave", "weary", "sharp", "gentle", "foggy", "stormy",
)  # fmt: skip
NOUNS = (
    "cheerleader", "cartographer", "locksmith", "drifter", "alchemist",
    "gardener", "sentinel", "tinkerer", "wanderer", "archivist",
    "blacksmith", "navigator", "hermit", "juggler", "watchman", "dreamer",
    "mechanic", "scribe", "falcon", "otter", "compass", "anchor", "ember",
    "lantern",
)  # fmt: skip

TAG_PATTERN = r"^[a-z0-9]+(-[a-z0-9]+)*$"


class JournalError(Exception):
    """An entry could not be created or read. The message is meant for the user."""


class Generated(BaseModel):
    model_config = ConfigDict(extra="forbid")

    by: str = Field(pattern=r"^human:[a-z0-9]+(-[a-z0-9]+)*$")
    at: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2})?$")

    @field_validator("at", mode="before")
    @classmethod
    def from_yaml_date(cls, value: object) -> object:
        # YAML reads an unquoted 2026-10-03 as a date, not a string.
        if isinstance(value, datetime):
            return value.strftime("%Y-%m-%dT%H:%M")
        if isinstance(value, date):
            return value.isoformat()
        return value


class Frontmatter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["Journal Entry"] = "Journal Entry"
    title: str | None = Field(default=None, min_length=1)
    tags: list[str] = Field(min_length=1)
    generated: Generated

    @field_validator("tags")
    @classmethod
    def journal_first(cls, tags: list[str]) -> list[str]:
        if tags[0] != "journal":
            raise ValueError("le premier tag doit être journal")
        return tags


@dataclass(frozen=True)
class Entry:
    path: Path
    frontmatter: Frontmatter
    body: str  # what was written by hand, without frontmatter nor heading


def random_slug(rng: random.Random) -> str:
    return f"{rng.choice(ADJECTIVES)}-{rng.choice(NOUNS)}"


def render(frontmatter: Frontmatter, heading: str, body: str = "") -> str:
    header = yaml.safe_dump(
        frontmatter.model_dump(exclude_none=True),
        allow_unicode=True,
        default_flow_style=None,
        sort_keys=False,
    )
    text = f"---\n{header}---\n\n# {heading}\n\n"
    return f"{text}{body}\n" if body else text


def split(text: str) -> tuple[str | None, str]:
    """Split a file into its frontmatter (if any) and its body, heading removed."""
    header = None
    if text.startswith("---\n"):
        header, _, text = text[4:].partition("\n---\n")
    text = text.strip()
    if text.startswith("# "):
        _, _, text = text.partition("\n")
    return header, text.strip()


def body_length(path: Path) -> int:
    """Characters written by hand: frontmatter, heading and surrounding blanks excluded."""
    return len(split(path.read_text(encoding="utf-8"))[1])


def read_entry(path: Path) -> Entry:
    header, body = split(path.read_text(encoding="utf-8"))
    if header is None:
        raise JournalError(f"{path.name} n'a pas de frontmatter")
    try:
        data = yaml.safe_load(header)
    except yaml.YAMLError as error:
        raise JournalError(f"{path.name} : frontmatter YAML illisible") from error
    kind = data.get("type") if isinstance(data, dict) else None
    if kind != "Journal Entry":
        raise JournalError(f"{path.name} (type {kind}, pas une entrée de journal)")
    try:
        frontmatter = Frontmatter.model_validate(data)
    except ValidationError as error:
        message = f"{path.name} : entrée de journal invalide\n{describe(error)}"
        raise JournalError(message) from error
    return Entry(path, frontmatter, body)


def write_exclusive(directory: Path, stem: str, content: str) -> Path:
    """Write a new file, never overwriting: a name already taken gets a suffix."""
    for attempt in range(1, 100):
        suffix = "" if attempt == 1 else f"-{attempt}"
        path = directory / f"{stem}{suffix}.md"
        try:
            with path.open("x", encoding="utf-8") as file:
                file.write(content)
        except FileExistsError:
            continue
        return path
    raise JournalError(f"Trop de fichiers nommés {stem}*.md dans {directory}")


def create_entry(
    config: Config, audit: AuditLog, now: datetime, rng: random.Random | None = None
) -> Path:
    if not config.inbox.is_dir():
        raise JournalError(f"Dossier inbox introuvable : {config.inbox}")

    frontmatter = Frontmatter(
        tags=["journal"],
        generated=Generated(
            by=f"human:{config.author}",
            at=now.strftime("%Y-%m-%dT%H:%M"),
        ),
    )
    slug = random_slug(rng or random.Random())
    content = render(frontmatter, heading=slug.replace("-", " ").title())
    path = write_exclusive(config.inbox, f"{now:%Y-%m-%d}-{slug}", content)
    audit.record("journal.created", path=path)
    return path
