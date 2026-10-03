"""Local configuration: read config.local.toml and validate it."""

import tomllib
from pathlib import Path

from pydantic import BaseModel, ConfigDict, DirectoryPath, Field, ValidationError


class ConfigError(Exception):
    """The configuration is missing or invalid. The message is meant for the user."""


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    second_brain: DirectoryPath
    author: str = Field(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")

    @property
    def inbox(self) -> Path:
        return self.second_brain / "sources" / "inbox"


def load_config(path: Path) -> Config:
    if not path.is_file():
        raise ConfigError(
            f"Configuration introuvable : {path}\n"
            f"Copie config.example.toml en {path.name} et adapte-le."
        )
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"{path} n'est pas un TOML valide : {error}") from error
    try:
        return Config.model_validate(data)
    except ValidationError as error:
        details = "\n".join(
            f"  - {'.'.join(str(part) for part in err['loc'])} : {err['msg']}"
            for err in error.errors()
        )
        raise ConfigError(f"{path} est invalide :\n{details}") from error
