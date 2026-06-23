from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from PyQt6.QtWidgets import QApplication

from .widgets import MainWindow


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.smoke_test:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    app = QApplication.instance() or QApplication(list(sys.argv[:1]))
    window = MainWindow()
    if args.directory:
        if args.smoke_test:
            window.load_path_sync(args.directory)
        else:
            window.load_path(args.directory)
    elif not args.smoke_test:
        window.load_last_directory()

    if args.smoke_test:
        window.resize(960, 640)
        window.show()
        app.processEvents()
        return 0

    window.show()
    return app.exec()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Visualize local Garmin activity exports on an offline map."
    )
    parser.add_argument(
        "directory",
        nargs="?",
        type=Path,
        help="Directory containing exported Garmin JSON files.",
    )
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help=(
            "Create the GUI in offscreen mode and exit without starting the event loop."
        ),
    )
    return parser.parse_args(argv)
