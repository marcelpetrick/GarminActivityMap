import json
from pathlib import Path

from activity_map.settings import (
    CURRENT_SETTINGS_VERSION,
    AppSettings,
    SettingsStore,
    settings_from_mapping,
)


def test_settings_store_round_trip_and_atomic_cleanup(tmp_path: Path) -> None:
    path = tmp_path / "config" / "settings.json"
    store = SettingsStore(path)
    settings = AppSettings(
        last_track_directory="/tmp/tracks",
        track_color="#123abc",
        preferences={"future": {"enabled": True}},
    )

    store.save(settings)
    restored = store.load()

    assert restored == settings
    assert not (path.parent / ".settings.json.tmp").exists()


def test_settings_store_recovers_from_missing_and_corrupt_files(
    tmp_path: Path,
) -> None:
    path = tmp_path / "settings.json"
    store = SettingsStore(path)

    assert store.load() == AppSettings()

    path.write_text("{broken", encoding="utf-8")
    recovered = store.load()

    assert recovered == AppSettings()
    assert store.last_error is not None


def test_settings_loader_ignores_unknown_and_invalid_fields() -> None:
    settings = settings_from_mapping(
        {
            "version": 99,
            "track_color": "not-a-color",
            "track_opacity": 500,
            "show_track_names": "yes",
            "unknown_future_field": {"safe": True},
            "preferences": {"new_option": 1},
        }
    )

    assert settings.version == CURRENT_SETTINGS_VERSION
    assert settings.track_color == AppSettings().track_color
    assert settings.track_opacity == AppSettings().track_opacity
    assert settings.show_track_names is False
    assert settings.preferences == {"new_option": 1}


def test_settings_store_rejects_non_object_payload(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(["invalid"]), encoding="utf-8")
    store = SettingsStore(path)

    assert store.load() == AppSettings()
    assert store.last_error == "Settings file must contain a JSON object"
