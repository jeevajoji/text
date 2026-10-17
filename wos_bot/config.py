"""Load config.yaml into typed dataclasses.

Unknown keys and wrong value types raise ConfigError, so a typo in the YAML fails at
startup instead of silently falling back to a default.
"""
from __future__ import annotations

import dataclasses
import typing
from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = ROOT / "config.yaml"


class ConfigError(ValueError):
    pass


@dataclass
class AdbConfig:
    serial: str = "127.0.0.1:5555"
    adb_path: str = ""
    timeout: float = 10.0


@dataclass
class GameConfig:
    package: str = "com.gof.global"
    width: int = 720
    height: int = 1280
    dpi: int = 240


@dataclass
class LoggingConfig:
    level: str = "INFO"
    dir: str = "logs"


@dataclass
class Config:
    adb: AdbConfig = field(default_factory=AdbConfig)
    game: GameConfig = field(default_factory=GameConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> Config:
    path = Path(path)
    if not path.exists():
        raise ConfigError(f"config file not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return _build(Config, data, "config")


def resolve_path(p: str | Path) -> Path:
    """Paths in the config are relative to the project folder, not the current directory."""
    p = Path(p)
    return p if p.is_absolute() else ROOT / p


def _build(cls: type, data: object, where: str):
    if not isinstance(data, dict):
        raise ConfigError(f"{where}: expected a mapping, got {type(data).__name__}")
    hints = typing.get_type_hints(cls)
    names = [f.name for f in dataclasses.fields(cls)]
    unknown = sorted(set(data) - set(names))
    if unknown:
        raise ConfigError(f"{where}: unknown key(s) {unknown}; valid keys: {names}")

    kwargs = {}
    for name, value in data.items():
        expected = hints[name]
        key = f"{where}.{name}"
        if dataclasses.is_dataclass(expected):
            kwargs[name] = _build(expected, value if value is not None else {}, key)
        else:
            kwargs[name] = _check_scalar(value, expected, key)
    return cls(**kwargs)


def _check_scalar(value: object, expected: type, where: str) -> object:
    if expected is float and isinstance(value, int) and not isinstance(value, bool):
        return float(value)
    # bool is a subclass of int; don't let `width: true` through as 1.
    if expected in (int, float) and isinstance(value, bool):
        raise ConfigError(f"{where}: expected {expected.__name__}, got bool")
    if expected in (str, int, float, bool) and not isinstance(value, expected):
        raise ConfigError(f"{where}: expected {expected.__name__}, got {type(value).__name__} ({value!r})")
    return value
