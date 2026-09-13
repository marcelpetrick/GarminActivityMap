from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from time import sleep

import pytest
from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

import activity_map.loader as loader
import activity_map.loading as loading
from activity_map.models import ActivityTrack, LoadReport, LoadWarning
from tests.gui_helpers import (
    configure_gui_environment,
    drag_canvas,
    launch_window,
    make_activity_directory,
    make_malformed_activity_directory,
    select_directory_with_dialog,
    wait_for_completed_load,
    wheel_canvas,
)


@pytest.fixture(autouse=True)
def offscreen_qt(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    configure_gui_environment(monkeypatch, tmp_path)


def test_directory_selection_loads_incrementally_and_supports_interaction(
    tmp_path: Path,
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory = make_activity_directory(tmp_path, track_count=12)
    select_directory_with_dialog(monkeypatch, directory)
    install_observable_loader(monkeypatch, progress_batch_size=3, delay_seconds=0.01)
    window = launch_window(qtbot)

    qtbot.mouseClick(  # type: ignore[no-untyped-call]
        window.choose_button,
        Qt.MouseButton.LeftButton,
    )

    qtbot.waitUntil(
        lambda: window.total_track_count > 0 and window.report is None,
        timeout=5_000,
    )
    assert window.load_status_text.startswith("Loading... ")
    assert "tracks" in window.load_status_text
    partial_count = window.total_track_count

    wait_for_completed_load(qtbot, window, expected_tracks=12)

    assert partial_count < window.total_track_count
    assert window.report is not None
    assert window.report.files_read == 12
    assert window.warning_label.text() == "No warnings"

    original_viewport = window.canvas.viewport
    drag_canvas(window.canvas, QPointF(460, 320), QPointF(520, 350))
    wheel_canvas(window.canvas, QPointF(500, 340), 120)
    qtbot.wait(80)
    QApplication.processEvents()
    pixmap = window.canvas.render_to_pixmap()

    assert window.canvas.viewport != original_viewport
    assert not pixmap.isNull()
    assert window.total_track_count == 12
    assert window.canvas.retained_track_paths
    assert window.canvas.path_draw_call_count <= window.total_track_count


def test_directory_selection_recovers_from_malformed_activity_files(
    tmp_path: Path,
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    malformed = make_malformed_activity_directory(tmp_path)
    valid = make_activity_directory(tmp_path, track_count=2)
    window = launch_window(qtbot)

    select_directory_with_dialog(monkeypatch, malformed)
    qtbot.mouseClick(  # type: ignore[no-untyped-call]
        window.choose_button,
        Qt.MouseButton.LeftButton,
    )
    wait_for_completed_load(qtbot, window, expected_tracks=0)

    assert window.report is not None
    assert window.report.files_read == 2
    assert window.total_track_count == 0
    assert "files skipped or incomplete" in window.warning_label.text()

    select_directory_with_dialog(monkeypatch, valid)
    qtbot.mouseClick(  # type: ignore[no-untyped-call]
        window.choose_button,
        Qt.MouseButton.LeftButton,
    )
    wait_for_completed_load(qtbot, window, expected_tracks=2)

    assert window.report is not None
    assert window.report.files_read == 2
    assert window.total_track_count == 2
    assert window.warning_label.text() == "No warnings"


def install_observable_loader(
    monkeypatch: pytest.MonkeyPatch,
    *,
    progress_batch_size: int,
    delay_seconds: float,
) -> None:
    original_load_activity_result = loader.load_activity_result

    def delayed_load_activity_result(
        file_path: Path,
        max_speed_kmh: float | None,
    ) -> tuple[ActivityTrack | None, LoadWarning | None]:
        sleep(delay_seconds)
        return original_load_activity_result(file_path, max_speed_kmh)

    def load_directory_with_small_batches(
        root: Path,
        max_speed_kmh: float | None = None,
        workers: int = 4,
        progress: Callable[
            [LoadReport, tuple[ActivityTrack, ...]],
            None,
        ]
        | None = None,
        progress_batch_size: int = loader.DEFAULT_PROGRESS_BATCH_SIZE,
        cancelled: Callable[[], bool] | None = None,
    ) -> LoadReport:
        return loader.load_directory_parallel(
            root,
            max_speed_kmh=max_speed_kmh,
            workers=workers,
            progress=progress,
            progress_batch_size=min(progress_batch_size, progress_batch_size_override),
            cancelled=cancelled,
        )

    monkeypatch.setattr(loader, "load_activity_result", delayed_load_activity_result)
    progress_batch_size_override = progress_batch_size
    monkeypatch.setattr(
        loading,
        "load_directory_parallel",
        load_directory_with_small_batches,
    )
