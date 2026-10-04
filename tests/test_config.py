from pathlib import Path

import pytest

from hypomnemata.core.config import ConfigError, load_config, load_models


def test_loads_valid_config(config_file: Path, second_brain: Path) -> None:
    config = load_config(config_file)
    assert config.second_brain == second_brain
    assert config.inbox == second_brain / "sources" / "inbox"


def test_missing_file_explains_what_to_do(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="config.example.toml"):
        load_config(tmp_path / "config.local.toml")


def test_invalid_toml(tmp_path: Path) -> None:
    path = tmp_path / "config.local.toml"
    path.write_text("second_brain = ", encoding="utf-8")
    with pytest.raises(ConfigError, match="TOML"):
        load_config(path)


def test_second_brain_must_exist(tmp_path: Path) -> None:
    path = tmp_path / "config.local.toml"
    path.write_text(f'second_brain = "{tmp_path / "nope"}"\nauthor = "a"\n', encoding="utf-8")
    with pytest.raises(ConfigError, match="second_brain"):
        load_config(path)


@pytest.mark.parametrize("author", ["", "Vincent", "with space", "-dash"])
def test_rejects_invalid_author(config_file: Path, second_brain: Path, author: str) -> None:
    config_file.write_text(
        f'second_brain = "{second_brain}"\nauthor = "{author}"\n', encoding="utf-8"
    )
    with pytest.raises(ConfigError, match="author"):
        load_config(config_file)


def test_rejects_unknown_keys(config_file: Path) -> None:
    config_file.write_text(config_file.read_text() + 'typo = "x"\n', encoding="utf-8")
    with pytest.raises(ConfigError, match="typo"):
        load_config(config_file)


def test_models_resolve_to_the_smallest_sufficient_class(tmp_path: Path) -> None:
    path = tmp_path / "models.local.toml"
    path.write_text('medium = "m:14b"\nlarge = "l:70b"\n', encoding="utf-8")
    models = load_models(path)

    assert models.resolve("small") == "m:14b"
    assert models.resolve("large") == "l:70b"


def test_models_refuse_when_no_class_is_big_enough(tmp_path: Path) -> None:
    path = tmp_path / "models.local.toml"
    path.write_text('small = "s:4b"\n', encoding="utf-8")
    with pytest.raises(ConfigError, match="medium"):
        load_models(path).resolve("medium")
