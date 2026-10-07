import json
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

import ollama
import pytest

from hypomnemata.core.audit import AuditLog
from hypomnemata.core.config import Config
from hypomnemata.core.llm import LLM, Embedder


@pytest.fixture(autouse=True)
def isolated_git(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    """Commits in tests never read the user's git configuration."""
    home = tmp_path_factory.mktemp("git-home")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(home / "gitconfig"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for role in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{role}_NAME", "Test")
        monkeypatch.setenv(f"GIT_{role}_EMAIL", "test@example.org")


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return result.stdout


@pytest.fixture
def second_brain(tmp_path: Path) -> Path:
    root = tmp_path / "second-brain"
    (root / "sources" / "inbox").mkdir(parents=True)
    (root / "sources" / "journal").mkdir()
    (root / "sources" / "inbox" / ".gitkeep").touch()
    git(root, "init", "--quiet")
    git(root, "add", ".")
    git(root, "commit", "--quiet", "-m", "init")
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


FakeChat = Callable[..., ollama.ChatResponse]


def fake_chat(answer: dict[str, Any] | str, calls: list[dict[str, Any]] | None = None) -> FakeChat:
    """A stand-in for Ollama that always gives the same answer."""
    content = answer if isinstance(answer, str) else json.dumps(answer)

    def chat(**kwargs: Any) -> ollama.ChatResponse:
        if calls is not None:
            calls.append(kwargs)
        return ollama.ChatResponse(message=ollama.Message(role="assistant", content=content))

    return chat


@pytest.fixture
def llm(audit: AuditLog) -> LLM:
    proposal = {"title": "Un premier essai réussi", "tags": ["personnel", "hypomnemata"]}
    return LLM("fake:1b", audit, fake_chat(proposal))


def topic_embedder(audit: AuditLog, calls: list[list[str]] | None = None) -> Embedder:
    """A stand-in embedding model: sentences about "travail" point one way, the rest another."""

    def embed(**kwargs: Any) -> ollama.EmbedResponse:
        texts = kwargs["input"]
        if calls is not None:
            calls.append(texts)
        vectors = [[1.0, 0.1] if "travail" in text else [0.1, 1.0] for text in texts]
        return ollama.EmbedResponse(embeddings=vectors)

    return Embedder("fake-embed", audit, embed)
