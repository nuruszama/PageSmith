import pymupdf
from PySide6.QtCore import Qt, QRectF, QSize, QTimer, QThread, Signal
from PySide6.QtGui import QImage, QPixmap, QPainter, QPen, QColor, QBrush, QIcon
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QSplitter, QListWidget, QListWidgetItem,
    QTreeWidget, QTreeWidgetItem, QTabWidget, QGraphicsView,
    QGraphicsScene, QGraphicsPixmapItem, QGraphicsRectItem
)


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
        self.setFrameShape(QGraphicsView.NoFrame)
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setBackgroundBrush(QBrush(QColor("#181b20")))

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
    """Single PDF document tab with collapsible Thumbnails, Bookmarks (TOC), and Reader Canvas."""
    def __init__(self, file_path: str):
        super().__init__()
        self.file_path = file_path
        self.doc = pymupdf.open(file_path)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setHandleWidth(1)

        self.nav_tabs = QTabWidget()
        self.nav_tabs.setMaximumWidth(185)
        self.nav_tabs.setMinimumWidth(140)
        self.nav_tabs.setDocumentMode(True)

        self.thumb_list = QListWidget()
        self.thumb_list.setViewMode(QListWidget.IconMode)
        self.thumb_list.setFlow(QListWidget.TopToBottom)
        self.thumb_list.setWrapping(False)
        self.thumb_list.setResizeMode(QListWidget.Adjust)
        self.thumb_list.setIconSize(QSize(110, 145))
        self.thumb_list.setSpacing(6)
        self.thumb_list.currentRowChanged.connect(self.go_to_page)
        self.nav_tabs.addTab(self.thumb_list, "Pages")

        self.toc_tree = QTreeWidget()
        self.toc_tree.setHeaderHidden(True)
        self.toc_tree.itemClicked.connect(self._on_toc_clicked)
        self.nav_tabs.addTab(self.toc_tree, "Bookmarks")

        self.canvas = PdfReaderCanvas(file_path, self.doc, 0)

        self.splitter.addWidget(self.nav_tabs)
        self.splitter.addWidget(self.canvas)
        self.splitter.setStretchFactor(1, 1)
        layout.addWidget(self.splitter)

        self.populate_thumbnails()
        self.populate_toc()

    def toggle_sidebar(self):
        self.nav_tabs.setVisible(not self.nav_tabs.isVisible())

    def populate_thumbnails(self):
        self.thumb_list.blockSignals(True)
        self.thumb_list.clear()
        for i in range(len(self.doc)):
            page = self.doc[i]
            pix = page.get_pixmap(matrix=pymupdf.Matrix(0.18, 0.18), alpha=False)
            img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888).copy()
            item = QListWidgetItem(QIcon(QPixmap.fromImage(img)), f"{i + 1}")
            item.setTextAlignment(Qt.AlignCenter)
            self.thumb_list.addItem(item)
        self.thumb_list.setCurrentRow(self.canvas.page_index)
        self.thumb_list.blockSignals(False)

    def populate_toc(self):
        self.toc_tree.clear()
        toc = self.doc.get_toc()
        if not toc:
            placeholder = QTreeWidgetItem(["No bookmarks"])
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