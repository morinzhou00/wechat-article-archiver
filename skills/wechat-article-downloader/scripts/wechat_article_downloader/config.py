from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from pathlib import Path

from .errors import InvalidInputError
from .utils import atomic_write_json, default_data_dir, default_output_dir, parse_formats, read_json


@dataclass(slots=True)
class RuntimeConfig:
    output_dir: str = str(default_output_dir())
    request_interval_seconds: float = 3.0
    timeout_seconds: int = 30
    max_pages: int = 30
    include_assets: bool = True
    default_formats: tuple[str, ...] = ("html", "md", "pdf")
    console_port: int = 8765

    def validate(self) -> "RuntimeConfig":
        if not isinstance(self.output_dir, str) or not self.output_dir.strip() or len(self.output_dir) > 1000:
            raise InvalidInputError("output_dir must be a non-empty path string.")
        try:
            resolved_output = Path(self.output_dir).expanduser().resolve()
        except (OSError, ValueError) as exc:
            raise InvalidInputError("output_dir is not a valid path.") from exc
        if resolved_output.parent == resolved_output:
            raise InvalidInputError("output_dir cannot be a filesystem root.")
        if isinstance(self.request_interval_seconds, bool):
            raise InvalidInputError("request_interval_seconds must be a finite number.")
        try:
            interval = float(self.request_interval_seconds)
        except (TypeError, ValueError) as exc:
            raise InvalidInputError("request_interval_seconds must be a finite number.") from exc
        if not math.isfinite(interval):
            raise InvalidInputError("request_interval_seconds must be a finite number.")
        if not 1.0 <= interval <= 60.0:
            raise InvalidInputError("request_interval_seconds must be between 1 and 60.")
        self.request_interval_seconds = interval
        if not isinstance(self.timeout_seconds, int) or isinstance(self.timeout_seconds, bool):
            raise InvalidInputError("timeout_seconds must be an integer.")
        if not 5 <= self.timeout_seconds <= 180:
            raise InvalidInputError("timeout_seconds must be between 5 and 180.")
        if not isinstance(self.max_pages, int) or isinstance(self.max_pages, bool):
            raise InvalidInputError("max_pages must be an integer.")
        if not 1 <= self.max_pages <= 200:
            raise InvalidInputError("max_pages must be between 1 and 200.")
        if not isinstance(self.include_assets, bool):
            raise InvalidInputError("include_assets must be true or false.")
        if not isinstance(self.console_port, int) or isinstance(self.console_port, bool):
            raise InvalidInputError("console_port must be an integer.")
        if not 1024 <= self.console_port <= 65535:
            raise InvalidInputError("console_port must be between 1024 and 65535.")
        if isinstance(self.default_formats, str):
            self.default_formats = tuple(parse_formats(self.default_formats))
        elif isinstance(self.default_formats, (list, tuple)):
            self.default_formats = tuple(parse_formats(list(self.default_formats)))
        else:
            raise InvalidInputError("default_formats must be a list or comma-separated string.")
        return self

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["default_formats"] = list(self.default_formats)
        return payload


class ConfigStore:
    def __init__(self, data_dir: Path | None = None) -> None:
        self.data_dir = data_dir or default_data_dir()
        self.path = self.data_dir / "config.json"

    def load(self) -> RuntimeConfig:
        raw = read_json(self.path, {}) or {}
        if not isinstance(raw, dict):
            raw = {}
        defaults = RuntimeConfig()
        merged = defaults.to_dict()
        merged.update({key: value for key, value in raw.items() if key in merged})
        return RuntimeConfig(**merged).validate()

    def save(self, config: RuntimeConfig) -> RuntimeConfig:
        config.validate()
        atomic_write_json(self.path, config.to_dict())
        return config

    def update(self, changes: dict[str, object]) -> RuntimeConfig:
        config = self.load()
        allowed = set(config.to_dict())
        unknown = sorted(set(changes) - allowed)
        if unknown:
            raise InvalidInputError(f"Unknown configuration field(s): {', '.join(unknown)}.")
        for key, value in changes.items():
            if key == "default_formats":
                value = tuple(value) if isinstance(value, list) else tuple(str(value).split(","))
            setattr(config, key, value)
        return self.save(config)
