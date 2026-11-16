import sys
import os
import pymupdf
from PySide6.QtCore import Qt, QRectF, QSize
from PySide6.QtGui import (
    QAction, QImage, QPixmap, QPainter, QPen, QColor, QBrush,
    QIcon, QKeySequence, QDragEnterEvent, QDropEvent
)
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout,
    QToolBar, QFileDialog, QSplitter, QListWidget, QListWidgetItem,
    QTreeWidget, QTreeWidgetItem, QTabWidget, QGraphicsView,
    QGraphicsScene, QGraphicsPixmapItem, QGraphicsRectItem,
    QLineEdit, QPushButton, QLabel, QSpinBox, QStatusBar
)


class PdfReaderCanvas(QGraphicsView):
    """64-bit hardware-accelerated PDF viewport with smooth zoom, pan, and search highlights."""
    def __init__(self, doc: pymupdf.Document, page_index: int = 0):
        super().__init__()
        self.doc = doc
        self.page_index = page_index
        self.zoom_factor = 1.5
        self.search_rects: list[pymupdf.Rect] = []

        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setBackgroundBrush(QBrush(QColor(45, 45, 48)))

        self.pixmap_item = None
        self.render_page()

    def render_page(self):
        self._scene.clear()
        if len(self.doc) == 0:
            return

        page = self.doc[self.page_index]
        mat = pymupdf.Matrix(self.zoom_factor, self.zoom_factor)
        pix = page.get_pixmap(matrix=mat, alpha=False)

        img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888)
        qpix = QPixmap.fromImage(img)

        self.pixmap_item = QGraphicsPixmapItem(qpix)
        self._scene.addItem(self.pixmap_item)
        self._scene.setSceneRect(0, 0, qpix.width(), qpix.height())

        for r in self.search_rects:
            scaled = QRectF(
                r.x0 * self.zoom_factor,
                r.y0 * self.zoom_factor,
                r.width * self.zoom_factor,
                r.height * self.zoom_factor,
            )
            hl = QGraphicsRectItem(scaled)
            hl.setPen(QPen(QColor(255, 165, 0), 2))
            hl.setBrush(QBrush(QColor(255, 230, 0, 100)))
            self._scene.addItem(hl)

    def fit_width(self):
        if not self.pixmap_item:
            return
        page_width_pts = self.doc[self.page_index].rect.width
        if page_width_pts > 0:
            avail_w = max(200, self.viewport().width() - 30)
            self.zoom_factor = avail_w / page_width_pts
            self.render_page()

    def fit_page(self):
        if not self.pixmap_item:
            return
        rect = self.doc[self.page_index].rect
        if rect.width > 0 and rect.height > 0:
            avail_w = max(200, self.viewport().width() - 30)
            avail_h = max(200, self.viewport().height() - 30)
            self.zoom_factor = min(avail_w / rect.width, avail_h / rect.height)
            self.render_page()

    def wheelEvent(self, event):
        if event.modifiers() & Qt.ControlModifier:
            delta = event.angleDelta().y()
            factor = 1.15 if delta > 0 else 1 / 1.15
            new_zoom = max(0.2, min(8.0, self.zoom_factor * factor))
            if new_zoom != self.zoom_factor:
                self.zoom_factor = new_zoom
                self.render_page()
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

        self.canvas = PdfReaderCanvas(self.doc, 0)

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
            img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888)
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
            self.canvas.render_page()
            self.thumb_list.blockSignals(True)
            self.thumb_list.setCurrentRow(index)
            self.thumb_list.blockSignals(False)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PageSmith — Portable 64-Bit PDF Reader")
        self.resize(1380, 880)
        self.setAcceptDrops(True)

        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.currentChanged.connect(self._sync_page_controls)
        self.setCentralWidget(self.tabs)

        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.status.showMessage("Ready — Open or drag & drop a PDF file")

        self._build_toolbar()

    def _build_toolbar(self):
        tb = QToolBar("Reader Toolbar")
        tb.setMovable(False)
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

    def current_tab(self) -> DocumentTab | None:
        w = self.tabs.currentWidget()
        return w if isinstance(w, DocumentTab) else None

    def open_file(self, path: str):
        if not os.path.isfile(path):
            return
        tab = DocumentTab(path)
        name = os.path.basename(path)
        idx = self.tabs.addTab(tab, name)
        self.tabs.setCurrentIndex(idx)
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
            total = len(tab.doc)
            self.page_spin.setMaximum(max(1, total))
            self.page_spin.setValue(tab.canvas.page_index + 1)
            self.lbl_total_pages.setText(f" / {total} ")
        else:
            self.page_spin.setMaximum(1)
            self.page_spin.setValue(1)
            self.lbl_total_pages.setText(" / 0 ")
        self.page_spin.blockSignals(False)

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
            tab.canvas.zoom_factor = max(0.2, min(8.0, tab.canvas.zoom_factor * factor))
            tab.canvas.render_page()

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
            tab.canvas.render_page()
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
                tab.canvas.render_page()
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
    app = QApplication(sys.argv)
    app.setApplicationName("PageSmith")
    app.setStyle("Fusion")
    window = MainWindow()
    window.show()

    for arg in sys.argv[1:]:
        if arg.lower().endswith(".pdf"):
            window.open_file(arg)

    sys.exit(app.exec())