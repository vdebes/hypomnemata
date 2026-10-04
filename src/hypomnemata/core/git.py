"""Git operations on the journal repository, through the `git` command."""

import subprocess
from pathlib import Path


class GitError(Exception):
    """A git command failed. The message is meant for the user."""


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=False
    )


def is_repo(repo: Path) -> bool:
    return _git(repo, "rev-parse", "--is-inside-work-tree").returncode == 0


def is_tracked(repo: Path, path: Path) -> bool:
    return _git(repo, "ls-files", "--error-unmatch", "--", str(path)).returncode == 0


def commit_paths(repo: Path, paths: list[Path], message: str) -> str:
    """Commit exactly `paths` (additions or deletions), nothing else. Returns the short hash."""
    for args in (
        ("add", "--all", "--", *map(str, paths)),
        ("commit", "--quiet", "--only", "-m", message, "--", *map(str, paths)),
        ("rev-parse", "--short", "HEAD"),
    ):
        result = _git(repo, *args)
        if result.returncode != 0:
            raise GitError(f"git {args[0]} a échoué : {result.stderr.strip()}")
    return result.stdout.strip()
