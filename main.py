import sys
import os
import pkgutil
import importlib
import pymupdf
from PySide6.QtCore import Qt, QRectF, QSize, QTimer, QThread, Signal
from PySide6.QtGui import (
    QAction, QImage, QPixmap, QPainter, QPen, QColor, QBrush,
    QIcon, QKeySequence, QDragEnterEvent, QDropEvent
)
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QToolBar, QFileDialog, QSplitter, QListWidget, QListWidgetItem,
    QTreeWidget, QTreeWidgetItem, QTabWidget, QStackedWidget, QGraphicsView,
    QGraphicsScene, QGraphicsPixmapItem, QGraphicsRectItem,
    QLineEdit, QPushButton, QLabel, QSpinBox, QStatusBar
)

APP_VERSION = "v0.2.5"
GITHUB_REPO = "nuruszama/PageSmith"


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

    def current_tab(self) -> "DocumentTab | None":
        return self.window.current_tab()

    def current_canvas(self) -> "PdfReaderCanvas | None":
        tab = self.window.current_tab()
        return tab.canvas if tab else None

    def open_file(self, path: str):
        self.window.open_file(path)

    def add_welcome_action(self, label: str, callback, primary: bool = False) -> QPushButton:
        """Allows modules (e.g., pdfeditor.py) to add action buttons directly to the Welcome Screen."""
        return self.window.add_welcome_button(label, callback, primary=primary)

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
        self.window._sync_page_controls()


class TileRenderWorker(QThread):
    """Renders ONLY the visible viewport rectangle at full target_zoom (up to 12x) off the UI thread."""
    finished = Signal(int, float, pymupdf.Rect, QImage)

    def __init__(self, file_path: str, page_index: int, zoom: float, rotation: int, clip_rect: pymupdf.Rect):
        super().__init__()
        self.file_path = file_path
        self.page_index = page_index
        self.zoom = zoom
        self.rotation = rotation
        self.clip_rect = clip_rect

    def run(self):
        try:
            doc = pymupdf.open(self.file_path)
            if 0 <= self.page_index < len(doc):
                page = doc[self.page_index]
                page.set_rotation(self.rotation)
                mat = pymupdf.Matrix(self.zoom, self.zoom)
                pix = page.get_pixmap(matrix=mat, clip=self.clip_rect, alpha=False)
                img = QImage(
                    pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888
                ).copy()
                doc.close()
                if not self.isInterruptionRequested():
                    self.finished.emit(self.page_index, self.zoom, self.clip_rect, img)
            else:
                doc.close()
        except Exception:
            pass


class PdfReaderCanvas(QGraphicsView):
    """64-bit PDF viewport with instant GPU zoom + razor-sharp viewport tile sharpening up to 12x."""
    zoom_changed = Signal(float)

    def __init__(self, file_path: str, doc: pymupdf.Document, page_index: int = 0):
        super().__init__()
        self.file_path = file_path
        self.doc = doc
        self.page_index = page_index
        self.target_zoom = 1.5
        self.base_zoom = 1.5
        self.search_rects: list[pymupdf.Rect] = []
        self._worker: TileRenderWorker | None = None

        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setBackgroundBrush(QBrush(QColor(45, 45, 48)))

        self.base_pixmap_item: QGraphicsPixmapItem | None = None
        self.hd_tile_item: QGraphicsPixmapItem | None = None

        self._sharpen_timer = QTimer(self)
        self._sharpen_timer.setSingleShot(True)
        self._sharpen_timer.setInterval(150)
        self._sharpen_timer.timeout.connect(self.request_hd_viewport_tile)

        self.horizontalScrollBar().valueChanged.connect(self._on_viewport_moved)
        self.verticalScrollBar().valueChanged.connect(self._on_viewport_moved)

        self.render_page_sync()

    def _on_viewport_moved(self):
        if self.target_zoom > self.base_zoom * 1.05:
            self._sharpen_timer.start()

    def _clear_hd_tile(self):
        if self.hd_tile_item:
            self._scene.removeItem(self.hd_tile_item)
            self.hd_tile_item = None

    def _draw_search_overlays(self):
        for item in list(self._scene.items()):
            if item not in (self.base_pixmap_item, self.hd_tile_item) and item.zValue() == 10:
                self._scene.removeItem(item)

        for r in self.search_rects:
            scaled = QRectF(
                r.x0 * self.base_zoom,
                r.y0 * self.base_zoom,
                r.width * self.base_zoom,
                r.height * self.base_zoom,
            )
            hl = QGraphicsRectItem(scaled)
            hl.setPen(QPen(QColor(255, 165, 0), 2 / (self.target_zoom / self.base_zoom)))
            hl.setBrush(QBrush(QColor(255, 230, 0, 100)))
            hl.setZValue(10)
            self._scene.addItem(hl)

    def render_page_sync(self):
        if len(self.doc) == 0:
            return
        self.resetTransform()
        self._scene.clear()
        self.base_pixmap_item = None
        self.hd_tile_item = None

        page = self.doc[self.page_index]
        self.base_zoom = 2.0
        mat = pymupdf.Matrix(self.base_zoom, self.base_zoom)
        pix = page.get_pixmap(matrix=mat, alpha=False)

        img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888).copy()
        qpix = QPixmap.fromImage(img)

        self.base_pixmap_item = QGraphicsPixmapItem(qpix)
        self.base_pixmap_item.setZValue(0)
        self._scene.addItem(self.base_pixmap_item)
        self._scene.setSceneRect(0, 0, qpix.width(), qpix.height())

        ratio = self.target_zoom / self.base_zoom
        self.scale(ratio, ratio)

        self._draw_search_overlays()
        self.zoom_changed.emit(self.target_zoom)
        self._sharpen_timer.start()

    def set_zoom_smooth(self, new_zoom: float):
        new_zoom = max(0.15, min(12.0, new_zoom))
        if abs(new_zoom - self.target_zoom) < 1e-4:
            return

        factor = new_zoom / self.target_zoom
        self.target_zoom = new_zoom
        self.scale(factor, factor)
        self.zoom_changed.emit(self.target_zoom)
        self._sharpen_timer.start()

    def request_hd_viewport_tile(self):
        if len(self.doc) == 0 or not self.base_pixmap_item:
            return

        visible_scene = self.mapToScene(self.viewport().rect()).boundingRect()
        inv = 1.0 / self.base_zoom
        page_rect = self.doc[self.page_index].rect

        pad_x = visible_scene.width() * inv * 0.15
        pad_y = visible_scene.height() * inv * 0.15

        clip = pymupdf.Rect(
            max(page_rect.x0, visible_scene.left() * inv - pad_x),
            max(page_rect.y0, visible_scene.top() * inv - pad_y),
            min(page_rect.x1, visible_scene.right() * inv + pad_x),
            min(page_rect.y1, visible_scene.bottom() * inv + pad_y),
        )

        if clip.is_empty or clip.width < 2 or clip.height < 2:
            return

        if self._worker and self._worker.isRunning():
            self._worker.requestInterruption()
            self._worker.wait(50)

        rotation = self.doc[self.page_index].rotation
        self._worker = TileRenderWorker(self.file_path, self.page_index, self.target_zoom, rotation, clip)
        self._worker.finished.connect(self._on_hd_tile_ready)
        self._worker.start()

    def _on_hd_tile_ready(self, page_idx: int, rendered_z: float, clip: pymupdf.Rect, img: QImage):
        if page_idx != self.page_index or not self.base_pixmap_item:
            return
        if abs(rendered_z - self.target_zoom) > 0.05:
            return

        self._clear_hd_tile()
        qpix = QPixmap.fromImage(img)
        self.hd_tile_item = QGraphicsPixmapItem(qpix)
        self.hd_tile_item.setZValue(1)

        self.hd_tile_item.setPos(clip.x0 * self.base_zoom, clip.y0 * self.base_zoom)
        tile_scale = self.base_zoom / rendered_z
        self.hd_tile_item.setScale(tile_scale)
        self._scene.addItem(self.hd_tile_item)

    def fit_width(self):
        if not self.base_pixmap_item:
            return
        page_width_pts = self.doc[self.page_index].rect.width
        if page_width_pts > 0:
            avail_w = max(200, self.viewport().width() - 30)
            self.set_zoom_smooth(avail_w / page_width_pts)

    def fit_page(self):
        if not self.base_pixmap_item:
            return
        rect = self.doc[self.page_index].rect
        if rect.width > 0 and rect.height > 0:
            avail_w = max(200, self.viewport().width() - 30)
            avail_h = max(200, self.viewport().height() - 30)
            self.set_zoom_smooth(min(avail_w / rect.width, avail_h / rect.height))

    def wheelEvent(self, event):
        if event.modifiers() & Qt.ControlModifier:
            angle = event.angleDelta().y()
            if angle != 0:
                factor = 1.0015 ** angle
                self.set_zoom_smooth(self.target_zoom * factor)
            event.accept()
        else:
            super().wheelEvent(event)


class DocumentTab(QWidget):
    """Single PDF document tab with Thumbnails, Bookmarks (TOC), and Reader Canvas."""
    def __init__(self, file_path: str):
        super().__init__()
        self.file_path = file_path
        self.doc = pymupdf.open(file_path)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        splitter = QSplitter(Qt.Horizontal)

        self.nav_tabs = QTabWidget()
        self.nav_tabs.setMaximumWidth(230)

        self.thumb_list = QListWidget()
        self.thumb_list.setIconSize(QSize(130, 170))
        self.thumb_list.currentRowChanged.connect(self.go_to_page)
        self.nav_tabs.addTab(self.thumb_list, "Pages")

        self.toc_tree = QTreeWidget()
        self.toc_tree.setHeaderHidden(True)
        self.toc_tree.itemClicked.connect(self._on_toc_clicked)
        self.nav_tabs.addTab(self.toc_tree, "Bookmarks")

        self.canvas = PdfReaderCanvas(file_path, self.doc, 0)

        splitter.addWidget(self.nav_tabs)
        splitter.addWidget(self.canvas)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter)

        self.populate_thumbnails()
        self.populate_toc()

    def populate_thumbnails(self):
        self.thumb_list.blockSignals(True)
        self.thumb_list.clear()
        for i in range(len(self.doc)):
            page = self.doc[i]
            pix = page.get_pixmap(matrix=pymupdf.Matrix(0.22, 0.22), alpha=False)
            img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888).copy()
            item = QListWidgetItem(QIcon(QPixmap.fromImage(img)), f"Page {i + 1}")
            self.thumb_list.addItem(item)
        self.thumb_list.setCurrentRow(self.canvas.page_index)
        self.thumb_list.blockSignals(False)

    def populate_toc(self):
        self.toc_tree.clear()
        toc = self.doc.get_toc()
        if not toc:
            placeholder = QTreeWidgetItem(["No bookmarks in PDF"])
            placeholder.setDisabled(True)
            self.toc_tree.addTopLevelItem(placeholder)
            return

        stack: list[tuple[int, QTreeWidgetItem]] = []
        for lvl, title, page_num in toc:
            node = QTreeWidgetItem([title])
            node.setData(0, Qt.UserRole, max(0, page_num - 1))
            while stack and stack[-1][0] >= lvl:
                stack.pop()
            if stack:
                stack[-1][1].addChild(node)
            else:
                self.toc_tree.addTopLevelItem(node)
            stack.append((lvl, node))
        self.toc_tree.expandAll()

    def _on_toc_clicked(self, item: QTreeWidgetItem, _col: int):
        target_page = item.data(0, Qt.UserRole)
        if isinstance(target_page, int):
            self.go_to_page(target_page)

    def go_to_page(self, index: int):
        if 0 <= index < len(self.doc):
            self.canvas.page_index = index
            self.canvas.search_rects = []
            self.canvas.render_page_sync()
            self.thumb_list.blockSignals(True)
            self.thumb_list.setCurrentRow(index)
            self.thumb_list.blockSignals(False)


class MainWindow(QMainWindow):
    tab_changed = Signal(object)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("PageSmith - Portable 64-Bit PDF Reader by Abdul Samad")
        self.resize(1380, 880)
        self.setAcceptDrops(True)
        self.loaded_plugins: list = []

        icon_file = resource_path("assets/icon.png")
        if os.path.exists(icon_file):
            self.setWindowIcon(QIcon(icon_file))

        # Central stack: index 0 = Welcome Screen, index 1 = Active Document Tabs
        self.central_stack = QStackedWidget()
        self.welcome_widget = self._build_welcome_screen(icon_file)
        self.central_stack.addWidget(self.welcome_widget)

        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.currentChanged.connect(self._sync_page_controls)
        self.central_stack.addWidget(self.tabs)

        self.setCentralWidget(self.central_stack)

        self.status = QStatusBar()
        self.lbl_version = QLabel(f" {APP_VERSION} ")
        self.lbl_zoom = QLabel("Zoom: 100%")
        self.status.addPermanentWidget(self.lbl_zoom)
        self.status.addPermanentWidget(self.lbl_version)
        self.setStatusBar(self.status)
        self.status.showMessage("Ready — Open or drag & drop a PDF file")

        self._build_toolbar()
        self._load_modules()

    def _build_welcome_screen(self, icon_file: str) -> QWidget:
        screen = QWidget()
        screen.setStyleSheet("""
            QWidget {
                background-color: #23272e;
                color: #e6edf3;
            }
            QLabel#titleLabel {
                font-size: 28px;
                font-weight: bold;
                color: #ffffff;
            }
            QLabel#subtitleLabel {
                font-size: 14px;
                color: #9da7b3;
            }
            QLabel#hintLabel {
                font-size: 12px;
                color: #768390;
                margin-top: 12px;
            }
        """)

        outer = QVBoxLayout(screen)
        outer.setAlignment(Qt.AlignCenter)
        outer.setSpacing(12)

        if os.path.exists(icon_file):
            logo_lbl = QLabel()
            pix = QPixmap(icon_file).scaled(104, 104, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            logo_lbl.setPixmap(pix)
            logo_lbl.setAlignment(Qt.AlignCenter)
            outer.addWidget(logo_lbl)

        title_lbl = QLabel("PageSmith")
        title_lbl.setObjectName("titleLabel")
        title_lbl.setAlignment(Qt.AlignCenter)
        outer.addWidget(title_lbl)

        sub_lbl = QLabel(f"Portable 64-Bit PDF Studio by Abdul Samad  •  {APP_VERSION}")
        sub_lbl.setObjectName("subtitleLabel")
        sub_lbl.setAlignment(Qt.AlignCenter)
        outer.addWidget(sub_lbl)

        outer.addSpacing(16)

        self.welcome_btn_row = QHBoxLayout()
        self.welcome_btn_row.setAlignment(Qt.AlignCenter)
        self.welcome_btn_row.setSpacing(14)

        btn_open = QPushButton("  Open PDF...  ")
        btn_open.setCursor(Qt.PointingHandCursor)
        btn_open.setStyleSheet("""
            QPushButton {
                background-color: #e67e22;
                color: #ffffff;
                font-size: 14px;
                font-weight: bold;
                padding: 11px 24px;
                border-radius: 6px;
                border: none;
            }
            QPushButton:hover { background-color: #f39c12; }
            QPushButton:pressed { background-color: #d35400; }
        """)
        btn_open.clicked.connect(self.open_pdf_dialog)
        self.welcome_btn_row.addWidget(btn_open)

        outer.addLayout(self.welcome_btn_row)

        hint_lbl = QLabel("Tip: You can also drag and drop any PDF file anywhere onto this window")
        hint_lbl.setObjectName("hintLabel")
        hint_lbl.setAlignment(Qt.AlignCenter)
        outer.addWidget(hint_lbl)

        return screen

    def add_welcome_button(self, label: str, callback, primary: bool = False) -> QPushButton:
        """Adds an action button to the Welcome Screen (used by updater, pdfeditor, etc.)."""
        btn = QPushButton(f"  {label}  ")
        btn.setCursor(Qt.PointingHandCursor)
        if primary:
            btn.setStyleSheet("""
                QPushButton {
                    background-color: #e67e22;
                    color: #ffffff;
                    font-size: 14px;
                    font-weight: bold;
                    padding: 11px 24px;
                    border-radius: 6px;
                    border: none;
                }
                QPushButton:hover { background-color: #f39c12; }
            """)
        else:
            btn.setStyleSheet("""
                QPushButton {
                    background-color: #30363d;
                    color: #e6edf3;
                    font-size: 14px;
                    font-weight: 600;
                    padding: 11px 22px;
                    border-radius: 6px;
                    border: 1px solid #484f58;
                }
                QPushButton:hover { background-color: #3c444d; border-color: #8b949e; }
                QPushButton:pressed { background-color: #282e34; }
            """)
        btn.clicked.connect(callback)
        self.welcome_btn_row.addWidget(btn)
        return btn

    def _build_toolbar(self):
        tb = QToolBar("Reader Toolbar")
        tb.setMovable(False)
        self.main_toolbar = tb
        self.addToolBar(tb)

        act_open = QAction("Open PDF", self)
        act_open.setShortcut(QKeySequence.Open)
        act_open.triggered.connect(self.open_pdf_dialog)
        tb.addAction(act_open)

        tb.addSeparator()

        act_prev = QAction("◀ Prev", self)
        act_prev.setShortcut(Qt.Key_PageUp)
        act_prev.triggered.connect(lambda: self.step_page(-1))
        tb.addAction(act_prev)

        self.page_spin = QSpinBox()
        self.page_spin.setMinimum(1)
        self.page_spin.setMaximum(1)
        self.page_spin.valueChanged.connect(self._on_spin_page)
        tb.addWidget(self.page_spin)

        self.lbl_total_pages = QLabel(" / 0 ")
        tb.addWidget(self.lbl_total_pages)

        act_next = QAction("Next ▶", self)
        act_next.setShortcut(Qt.Key_PageDown)
        act_next.triggered.connect(lambda: self.step_page(1))
        tb.addAction(act_next)

        tb.addSeparator()

        act_zout = QAction("Zoom -", self)
        act_zout.setShortcut(QKeySequence.ZoomOut)
        act_zout.triggered.connect(lambda: self.adjust_zoom(0.8))
        tb.addAction(act_zout)

        act_zin = QAction("Zoom +", self)
        act_zin.setShortcut(QKeySequence.ZoomIn)
        act_zin.triggered.connect(lambda: self.adjust_zoom(1.25))
        tb.addAction(act_zin)

        act_fitw = QAction("Fit Width", self)
        act_fitw.triggered.connect(self.fit_width)
        tb.addAction(act_fitw)

        act_fitp = QAction("Fit Page", self)
        act_fitp.triggered.connect(self.fit_page)
        tb.addAction(act_fitp)

        act_rot = QAction("Rotate 90°", self)
        act_rot.triggered.connect(self.rotate_view)
        tb.addAction(act_rot)

        tb.addSeparator()

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Find text in PDF (Ctrl+F)...")
        self.search_input.setMaximumWidth(240)
        self.search_input.returnPressed.connect(self.find_next)
        tb.addWidget(self.search_input)

        act_focus_search = QAction("Find", self)
        act_focus_search.setShortcut(QKeySequence.Find)
        act_focus_search.triggered.connect(self.search_input.setFocus)
        tb.addAction(act_focus_search)

        btn_find = QPushButton("Find Next")
        btn_find.clicked.connect(self.find_next)
        tb.addWidget(btn_find)

    def _load_modules(self):
        """Loads bundled core modules (PyInstaller-safe) and auto-discovers any extra plugins in modules/."""
        ctx = PageSmithContext(self)
        loaded_names = set()

        bundled_modules = ["modules.updater"]
        for full_name in bundled_modules:
            try:
                mod = importlib.import_module(full_name)
                if hasattr(mod, "register"):
                    self.loaded_plugins.append(mod.register(ctx))
                    loaded_names.add(full_name.split(".")[-1])
            except Exception as exc:
                self.status.showMessage(f"Module load error ({full_name}): {exc}")

        try:
            import modules
            for _, mod_name, is_pkg in pkgutil.iter_modules(modules.__path__):
                if is_pkg or mod_name.startswith("_") or mod_name in loaded_names:
                    continue
                mod = importlib.import_module(f"modules.{mod_name}")
                if hasattr(mod, "register"):
                    self.loaded_plugins.append(mod.register(ctx))
                    loaded_names.add(mod_name)
        except Exception:
            pass

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
        self._sync_page_controls()
        self.status.showMessage(f"Opened {name} ({len(tab.doc)} pages)")

    def open_pdf_dialog(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Open PDF Document(s)", "", "PDF Files (*.pdf)"
        )
        for p in paths:
            self.open_file(p)

    def _sync_page_controls(self):
        tab = self.current_tab()
        self.page_spin.blockSignals(True)
        if tab:
            self.central_stack.setCurrentWidget(self.tabs)
            total = len(tab.doc)
            self.page_spin.setMaximum(max(1, total))
            self.page_spin.setValue(tab.canvas.page_index + 1)
            self.lbl_total_pages.setText(f" / {total} ")
            self.lbl_zoom.setText(f"Zoom: {int((tab.canvas.target_zoom / 1.5) * 100)}%")
            pdf_name = os.path.basename(tab.file_path)
            self.setWindowTitle(f"{pdf_name} - PageSmith by Abdul Samad")
        else:
            self.central_stack.setCurrentWidget(self.welcome_widget)
            self.page_spin.setMaximum(1)
            self.page_spin.setValue(1)
            self.lbl_total_pages.setText(" / 0 ")
            self.lbl_zoom.setText("Zoom: 100%")
            self.setWindowTitle("PageSmith - Portable 64-Bit PDF Reader by Abdul Samad")
        self.page_spin.blockSignals(False)
        self.tab_changed.emit(tab)

    def _on_spin_page(self, val: int):
        tab = self.current_tab()
        if tab:
            tab.go_to_page(val - 1)

    def step_page(self, delta: int):
        tab = self.current_tab()
        if tab:
            target = tab.canvas.page_index + delta
            if 0 <= target < len(tab.doc):
                tab.go_to_page(target)
                self._sync_page_controls()

    def adjust_zoom(self, factor: float):
        tab = self.current_tab()
        if tab:
            tab.canvas.set_zoom_smooth(tab.canvas.target_zoom * factor)

    def fit_width(self):
        tab = self.current_tab()
        if tab:
            tab.canvas.fit_width()

    def fit_page(self):
        tab = self.current_tab()
        if tab:
            tab.canvas.fit_page()

    def rotate_view(self):
        tab = self.current_tab()
        if tab:
            page = tab.doc[tab.canvas.page_index]
            page.set_rotation((page.rotation + 90) % 360)
            tab.canvas.render_page_sync()
            tab.populate_thumbnails()

    def find_next(self):
        tab = self.current_tab()
        query = self.search_input.text().strip()
        if not tab or not query:
            return

        total = len(tab.doc)
        start_page = tab.canvas.page_index
        for offset in range(total):
            p_idx = (start_page + offset) % total
            rects = tab.doc[p_idx].search_for(query)
            if rects:
                tab.go_to_page(p_idx)
                tab.canvas.search_rects = rects
                tab.canvas._draw_search_overlays()
                self._sync_page_controls()
                self.status.showMessage(f"Found {len(rects)} match(es) on Page {p_idx + 1}")
                return

        self.status.showMessage(f"No matches found for '{query}'")

    def close_tab(self, index: int):
        tab = self.tabs.widget(index)
        if isinstance(tab, DocumentTab):
            tab.doc.close()
        self.tabs.removeTab(index)
        self._sync_page_controls()

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

    icon_file = resource_path("assets/icon.png")
    if os.path.exists(icon_file):
        app.setWindowIcon(QIcon(icon_file))

    window = MainWindow()
    window.show()

    for arg in sys.argv[1:]:
        if arg.lower().endswith(".pdf"):
            window.open_file(arg)

    sys.exit(app.exec())