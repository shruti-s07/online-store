"""Desktop client entry point (python store.py ui)."""
from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication


def create_app(argv=None):
    from ui.folder_a_shell import context
    from ui.folder_a_shell.api_client import make_client
    from ui.folder_a_shell.theme import Theme

    app = QApplication.instance() or QApplication(argv or sys.argv)
    theme = Theme()
    app.setStyleSheet(theme.stylesheet())
    app.setFont(theme.font())
    context.init(make_client(), theme)
    # Folder A screens, then folder B panels: both register themselves in the page registry.
    import ui.folder_a_shell.pages_customer  # noqa: F401
    import ui.folder_a_shell.pages_staff  # noqa: F401
    import ui.folder_b_panels  # noqa: F401
    from ui.folder_a_shell.shell import MainWindow
    return app, MainWindow()


def main() -> int:
    app, window = create_app()
    window.show()
    window.start()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
