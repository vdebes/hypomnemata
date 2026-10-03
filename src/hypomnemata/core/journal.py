"""The /journal command: create an empty, dated journal entry in the inbox.

No model is involved here: the filename, the date and the frontmatter are
produced by code. The entry gets a random adjective-noun placeholder name;
the real title and tags will be proposed later, once the entry is written.
"""

import random
from datetime import datetime
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from hypomnemata.core.audit import AuditLog
from hypomnemata.core.config import Config

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


class JournalError(Exception):
    """The entry could not be created. The message is meant for the user."""


class Generated(BaseModel):
    model_config = ConfigDict(extra="forbid")

    by: str = Field(pattern=r"^human:[a-z0-9]+(-[a-z0-9]+)*$")
    at: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$")


class Frontmatter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["Journal Entry"] = "Journal Entry"
    tags: list[str] = Field(min_length=1)
    generated: Generated


def random_slug(rng: random.Random) -> str:
    return f"{rng.choice(ADJECTIVES)}-{rng.choice(NOUNS)}"


def render(frontmatter: Frontmatter, heading: str) -> str:
    header = yaml.safe_dump(
        frontmatter.model_dump(),
        allow_unicode=True,
        default_flow_style=None,
        sort_keys=False,
    )
    return f"---\n{header}---\n\n# {heading}\n\n"


def body_length(path: Path) -> int:
    """Characters written by hand: frontmatter, heading and surrounding blanks excluded."""
    text = path.read_text(encoding="utf-8")
    if text.startswith("---\n"):
        _, _, text = text[4:].partition("\n---\n")
    text = text.strip()
    if text.startswith("# "):
        _, _, text = text.partition("\n")
    return len(text.strip())


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
    stem = f"{now:%Y-%m-%d}-{slug}"

    # Mode "x" never overwrites: a name already taken gets a suffix.
    for attempt in range(1, 100):
        suffix = "" if attempt == 1 else f"-{attempt}"
        path = config.inbox / f"{stem}{suffix}.md"
        try:
            with path.open("x", encoding="utf-8") as entry:
                entry.write(content)
        except FileExistsError:
            continue
        audit.record("journal.created", path=path)
        return path
    raise JournalError(f"Trop d'entrées nommées {stem}*.md dans {config.inbox}")
