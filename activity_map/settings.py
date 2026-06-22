from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

CURRENT_SETTINGS_VERSION = 1
DEFAULT_SETTINGS_PATH = Path.home() / ".config" / "GarminActivityMap" / "settings.json"


@dataclass
class AppSettings:
    version: int = CURRENT_SETTINGS_VERSION
    last_track_directory: str | None = None
    last_run_timestamp: str | None = None
    track_color: str = "#2ddcff"
    track_opacity: int = 72
    show_track_names: bool = False
    map_opacity: int = 82
    map_layer_enabled: bool = True
    preferences: dict[str, Any] = field(default_factory=dict)


class SettingsStore:
    def __init__(self, path: Path | None = None) -> None:
        configured_path = os.environ.get("ACTIVITY_MAP_SETTINGS_PATH")
        self.path = path or (
            Path(configured_path) if configured_path else DEFAULT_SETTINGS_PATH
        )
        self.last_error: str | None = None

    def load(self) -> AppSettings:
        self.last_error = None
        if not self.path.exists():
            return AppSettings()
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            self.last_error = f"Could not load settings: {exc}"
            return AppSettings()
        if not isinstance(payload, dict):
            self.last_error = "Settings file must contain a JSON object"
            return AppSettings()
        return settings_from_mapping(payload)

    def save(self, settings: AppSettings) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.path.with_name(f".{self.path.name}.tmp")
        try:
            temporary_path.write_text(
                json.dumps(
                    asdict(settings),
                    indent=2,
                    sort_keys=True,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            temporary_path.replace(self.path)
            self.last_error = None
        except OSError as exc:
            self.last_error = f"Could not save settings: {exc}"
        finally:
            temporary_path.unlink(missing_ok=True)


def settings_from_mapping(payload: dict[str, Any]) -> AppSettings:
    defaults = AppSettings()
    return AppSettings(
        version=CURRENT_SETTINGS_VERSION,
        last_track_directory=optional_string(
            payload.get("last_track_directory"),
            defaults.last_track_directory,
        ),
        last_run_timestamp=optional_string(
            payload.get("last_run_timestamp"),
            defaults.last_run_timestamp,
        ),
        track_color=color_string(payload.get("track_color"), defaults.track_color),
        track_opacity=percentage(payload.get("track_opacity"), defaults.track_opacity),
        show_track_names=boolean(
            payload.get("show_track_names"),
            defaults.show_track_names,
        ),
        map_opacity=percentage(payload.get("map_opacity"), defaults.map_opacity),
        map_layer_enabled=boolean(
            payload.get("map_layer_enabled"),
            defaults.map_layer_enabled,
        ),
        preferences=dictionary(payload.get("preferences")),
    )


def optional_string(value: Any, default: str | None) -> str | None:
    return value if value is None or isinstance(value, str) else default


def color_string(value: Any, default: str) -> str:
    if not isinstance(value, str):
        return default
    normalized = value.lower()
    if len(normalized) != 7 or not normalized.startswith("#"):
        return default
    try:
        int(normalized[1:], 16)
    except ValueError:
        return default
    return normalized


def percentage(value: Any, default: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return default
    return value if 0 <= value <= 100 else default


def boolean(value: Any, default: bool) -> bool:
    return value if isinstance(value, bool) else default


def dictionary(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}
