from pathlib import Path

import pytest

from hypomnemata.core.audit import AuditLog
from hypomnemata.core.config import Config


@pytest.fixture
def second_brain(tmp_path: Path) -> Path:
    root = tmp_path / "second-brain"
    (root / "sources" / "inbox").mkdir(parents=True)
    return root


@pytest.fixture
def config(second_brain: Path) -> Config:
    return Config(second_brain=second_brain, author="test-user")


@pytest.fixture
def audit(tmp_path: Path) -> AuditLog:
    return AuditLog(tmp_path / "var" / "log")


@pytest.fixture
def config_file(tmp_path: Path, second_brain: Path) -> Path:
    path = tmp_path / "config.local.toml"
    path.write_text(f'second_brain = "{second_brain}"\nauthor = "test-user"\n', encoding="utf-8")
    return path
