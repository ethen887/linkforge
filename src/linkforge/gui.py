"""Executable entry point for the LinkForge desktop GUI."""

from __future__ import annotations

import logging
import sys

from PySide6.QtWidgets import QApplication

from linkforge.log import setup_logging
from linkforge.ui import MainWindow

logger = logging.getLogger(__name__)


def main() -> int:
    """Start the LinkForge Qt application and return its exit code."""
    log_file = setup_logging()
    logger.info("GUI logging initialized: %s", log_file)
    application = QApplication(sys.argv)
    application.setApplicationName("LinkForge")
    application.setOrganizationName("LinkForge")
    window = MainWindow()
    window.show()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
