"""Executable entry point for the LinkForge desktop GUI."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMessageBox

from linkforge.log import setup_logging
from linkforge.ui import MainWindow

logger = logging.getLogger(__name__)


def main() -> int:
    """Start the LinkForge Qt application and return its exit code."""
    application = QApplication(sys.argv)
    application.setApplicationName("LinkForge")
    application.setOrganizationName("LinkForge")
    try:
        log_file = setup_logging()
    except OSError:
        QMessageBox.critical(
            None,
            "无法创建运行日志",
            "LinkForge 无法创建或写入 logs 文件夹。\n"
            "请将完整程序解压到有写入权限的目录（例如下载目录）后重试。",
        )
        return 1
    logger.info("GUI logging initialized: %s", log_file)
    if len(sys.argv) == 3 and sys.argv[1] == "--self-test":
        from linkforge.ui.package_check import run_package_check

        return run_package_check(application, Path(sys.argv[2]), log_file)
    window = MainWindow(log_dir=log_file.parent)
    window.show()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
