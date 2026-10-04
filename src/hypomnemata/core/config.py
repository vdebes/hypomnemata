"""Local configuration: read config.local.toml and models.local.toml and validate them."""

import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, DirectoryPath, Field, ValidationError

ModelClass = Literal["small", "medium", "large"]
MODEL_CLASSES: tuple[ModelClass, ...] = ("small", "medium", "large")


class ConfigError(Exception):
    """The configuration is missing or invalid. The message is meant for the user."""


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    second_brain: DirectoryPath
    author: str = Field(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")

    @property
    def inbox(self) -> Path:
        return self.second_brain / "sources" / "inbox"

    @property
    def journal(self) -> Path:
        return self.second_brain / "sources" / "journal"


class Models(BaseModel):
    """Which local model serves each class."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    small: str | None = None
    medium: str | None = None
    large: str | None = None

    def resolve(self, minimum: ModelClass) -> str:
        """The smallest configured model of at least the `minimum` class."""
        for name in MODEL_CLASSES[MODEL_CLASSES.index(minimum) :]:
            model: str | None = getattr(self, name)
            if model:
                return model
        raise ConfigError(
            f"Aucun modèle de classe {minimum} ou plus dans models.local.toml : "
            "cette commande ne peut pas tourner sur cette machine."
        )


def _load[T: BaseModel](path: Path, schema: type[T], example: str) -> T:
    if not path.is_file():
        raise ConfigError(
            f"Configuration introuvable : {path}\nCopie {example} en {path.name} et adapte-le."
        )
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"{path} n'est pas un TOML valide : {error}") from error
    try:
        return schema.model_validate(data)
    except ValidationError as error:
        raise ConfigError(f"{path} est invalide :\n{describe(error)}") from error


def describe(error: ValidationError) -> str:
    """One short line per invalid field, without Pydantic's links."""
    return "\n".join(
        f"  - {'.'.join(str(part) for part in err['loc'])} : {err['msg']}" for err in error.errors()
    )


def load_config(path: Path) -> Config:
    return _load(path, Config, "config.example.toml")


def load_models(path: Path) -> Models:
    return _load(path, Models, "models.example.toml")
