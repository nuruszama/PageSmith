import sys
import os
import pymupdf
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIcon, QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QToolBar, QFileDialog,
    QTabWidget, QStackedWidget, QPushButton, QLabel, QStatusBar
)

import modules
from modules.pdfreader import DocumentTab, PdfReaderCanvas

APP_VERSION = "v0.3.3"
GITHUB_REPO = "nuruszama/PageSmith"

GLOBAL_STYLESHEET = """
QMainWindow, QWidget {
    background-color: #23272e;
    color: #e6edf3;
    font-family: "Segoe UI", sans-serif;
    font-size: 12px;
}
QToolBar {
    background-color: #1c2026;
    border-bottom: 1px solid #30363d;
    spacing: 4px;
    padding: 3px 6px;
}
QToolBar::separator {
    background-color: #30363d;
    width: 1px;
    margin: 4px 4px;
}
QToolButton {
    background-color: transparent;
    color: #c9d1d9;
    border: 1px solid transparent;
    border-radius: 4px;
    padding: 4px 8px;
    font-weight: 500;
}
QToolButton:hover {
    background-color: #2d333b;
    border-color: #444c56;
    color: #ffffff;
}
QToolButton:pressed {
    background-color: #16191e;
}
QLineEdit, QSpinBox {
    background-color: #16191e;
    color: #f0f6fc;
    border: 1px solid #30363d;
    border-radius: 4px;
    padding: 3px 6px;
    selection-background-color: #e67e22;
}
QLineEdit:focus, QSpinBox:focus {
    border-color: #e67e22;
}
QPushButton {
    background-color: #2d333b;
    color: #e6edf3;
    border: 1px solid #444c56;
    border-radius: 4px;
    padding: 4px 10px;
}
QPushButton:hover {
    background-color: #373e47;
    border-color: #8b949e;
}
QTabWidget::pane {
    border: none;
    background-color: #181b20;
}
QTabBar::tab {
    background-color: #1c2026;
    color: #9da7b3;
    border-right: 1px solid #30363d;
    border-bottom: 1px solid #30363d;
    padding: 5px 12px;
    font-size: 12px;
}
QTabBar::tab:selected {
    background-color: #23272e;
    color: #ffffff;
    border-bottom: 2px solid #e67e22;
}
QTabBar::tab:hover:!selected {
    background-color: #262b33;
    color: #e6edf3;
}
QListWidget, QTreeWidget {
    background-color: #1c2026;
    color: #c9d1d9;
    border: none;
    border-right: 1px solid #30363d;
    outline: none;
}
QListWidget::item {
    padding: 4px;
    border-radius: 4px;
}
QListWidget::item:selected, QTreeWidget::item:selected {
    background-color: #2d333b;
    color: #e67e22;
}
QStatusBar {
    background-color: #1c2026;
    color: #9da7b3;
    border-top: 1px solid #30363d;
    font-size: 11px;
}
QStatusBar::item {
    border: none;
}
QMenu {
    background-color: #1c2026;
    color: #e6edf3;
    border: 1px solid #30363d;
    padding: 4px;
}
QMenu::item {
    padding: 6px 18px;
    border-radius: 4px;
}
QMenu::item:selected {
    background-color: #e67e22;
    color: #ffffff;
}
QMenu::separator {
    height: 1px;
    background: #30363d;
    margin: 4px 8px;
}
"""


def resource_path(relative_path: str) -> str:
    """Resolve bundled asset paths inside PyInstaller --onefile or source runs."""
    base_path = getattr(sys, "_MEIPASS", os.path.abspath("."))
    return os.path.join(base_path, relative_path)


class PageSmithContext:
    """Clean API bridge passed to every plugin inside modules/."""
    def __init__(self, main_window: "MainWindow"):
        self.window = main_window
        self.app_version = APP_VERSION
        self.github_repo = GITHUB_REPO

    @property
    def toolbar(self) -> QToolBar:
        return self.window.main_toolbar

    @property
    def tabs(self) -> QTabWidget:
        return self.window.tabs

    @property
    def status_bar(self) -> QStatusBar:
        return self.window.status

    @property
    def welcome_slot(self) -> QWidget:
        return self.window.welcome_slot

    def resource_path(self, relative_path: str) -> str:
        return resource_path(relative_path)

    def current_tab(self) -> DocumentTab | None:
        return self.window.current_tab()

    def current_canvas(self) -> PdfReaderCanvas | None:
        tab = self.window.current_tab()
        return tab.canvas if tab else None

    def open_file(self, path: str):
        self.window.open_file(path)

    def add_welcome_action(self, label: str, callback, primary: bool = False) -> QPushButton | None:
        if hasattr(self.window, "_welcome_button_handler") and self.window._welcome_button_handler:
            return self.window._welcome_button_handler(label, callback, primary)
        return None

    def reload_current_tab(self):
        """Re-opens the active PDF from disk after an editor module modifies pages/annotations."""
        tab = self.window.current_tab()
        if not tab:
            return
        saved_page = tab.canvas.page_index
        saved_zoom = tab.canvas.target_zoom
        tab.doc.close()
        tab.doc = pymupdf.open(tab.file_path)
        tab.canvas.doc = tab.doc
        tab.canvas.page_index = min(saved_page, max(0, len(tab.doc) - 1))
        tab.canvas.target_zoom = saved_zoom
        tab.canvas.render_page_sync()
        tab.populate_thumbnails()
        tab.populate_toc()
        self.window._sync_workspace_state()


class MainWindow(QMainWindow):
    tab_changed = Signal(object)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("PageSmith - Portable 64-Bit PDF Reader by Abdul Samad")
        self.resize(1380, 880)
        self.setAcceptDrops(True)
        self.loaded_plugins: list = []
        self._welcome_button_handler = None
        self._tools_sync_hook = None

        icon_file = resource_path("assets/icon.png")
        if os.path.exists(icon_file):
            self.setWindowIcon(QIcon(icon_file))

        # Central stack: index 0 = Welcome Screen, index 1 = Active Document Tabs
        self.central_stack = QStackedWidget()
        self.welcome_slot = QWidget()
        self.central_stack.addWidget(self.welcome_slot)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.currentChanged.connect(self._sync_workspace_state)
        self.central_stack.addWidget(self.tabs)

        self.setCentralWidget(self.central_stack)

        # Compact Status Bar
        self.status = QStatusBar()
        self.status.setSizeGripEnabled(False)
        self.lbl_version = QLabel(f" {APP_VERSION} ")
        self.lbl_zoom = QLabel("Zoom: 100%")
        self.status.addPermanentWidget(self.lbl_zoom)
        self.status.addPermanentWidget(self.lbl_version)
        self.setStatusBar(self.status)
        self.status.showMessage("Ready — Open or drag & drop a PDF file")

        # Single Toolbar populated by modules/tools.py and other plugins
        self.main_toolbar = QToolBar("Main Toolbar")
        self.addToolBar(self.main_toolbar)

        self._load_modules()
        self.main_toolbar.setVisible(False)

    def _load_modules(self):
        ctx = PageSmithContext(self)
        self.loaded_plugins = modules.register_all(ctx)

    def current_tab(self) -> DocumentTab | None:
        w = self.tabs.currentWidget()
        return w if isinstance(w, DocumentTab) else None

    def open_file(self, path: str):
        if not os.path.isfile(path):
            return
        tab = DocumentTab(path)
        tab.canvas.zoom_changed.connect(
            lambda z: self.lbl_zoom.setText(f"Zoom: {int((z / 1.5) * 100)}%")
        )
        name = os.path.basename(path)
        idx = self.tabs.addTab(tab, name)
        self.tabs.setCurrentIndex(idx)
        self.central_stack.setCurrentWidget(self.tabs)
        self._sync_workspace_state()
        self.status.showMessage(f"Opened {name} ({len(tab.doc)} pages)")

    def open_pdf_dialog(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Open PDF Document(s)", "", "PDF Files (*.pdf)"
        )
        for p in paths:
            self.open_file(p)

    def _sync_workspace_state(self):
        tab = self.current_tab()
        if tab:
            self.main_toolbar.setVisible(True)
            self.central_stack.setCurrentWidget(self.tabs)
            self.lbl_zoom.setText(f"Zoom: {int((tab.canvas.target_zoom / 1.5) * 100)}%")
            pdf_name = os.path.basename(tab.file_path)
            self.setWindowTitle(f"{pdf_name} - PageSmith by Abdul Samad")
        else:
            self.main_toolbar.setVisible(False)
            self.central_stack.setCurrentWidget(self.welcome_slot)
            self.lbl_zoom.setText("Zoom: 100%")
            self.setWindowTitle("PageSmith - Portable 64-Bit PDF Reader by Abdul Samad")

        if self._tools_sync_hook:
            self._tools_sync_hook(tab)
        self.tab_changed.emit(tab)

    def close_tab(self, index: int):
        tab = self.tabs.widget(index)
        if isinstance(tab, DocumentTab):
            tab.doc.close()
        self.tabs.removeTab(index)
        self._sync_workspace_state()

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        for url in event.mimeData().urls():
            local_path = url.toLocalFile()
            if local_path.lower().endswith(".pdf"):
                self.open_file(local_path)


if __name__ == "__main__":
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("nuruszama.PageSmith.Desktop.1")

    app = QApplication(sys.argv)
    app.setApplicationName("PageSmith")
    app.setStyle("Fusion")
    app.setStyleSheet(GLOBAL_STYLESHEET)

    icon_file = resource_path("assets/icon.png")
    if os.path.exists(icon_file):
        app.setWindowIcon(QIcon(icon_file))

    window = MainWindow()
    window.show()

    for arg in sys.argv[1:]:
        if arg.lower().endswith(".pdf"):
            window.open_file(arg)

    sys.exit(app.exec())