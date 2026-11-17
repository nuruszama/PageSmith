from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QLineEdit, QPushButton, QLabel, QSpinBox, QWidget, QSizePolicy


class ReaderToolsPlugin:
    """Compact, single-row slim reader toolbar for navigation, zoom, sidebar toggle, and search."""
    def __init__(self, ctx):
        self.ctx = ctx
        win = ctx.window
        tb = ctx.toolbar

        tb.setMovable(False)
        tb.setFloatable(False)
        tb.setToolButtonStyle(Qt.ToolButtonTextOnly)

        # Sidebar toggle (collapses thumbnails/bookmarks for maximum canvas space)
        act_sidebar = QAction("☰", win)
        act_sidebar.setToolTip("Toggle Pages & Bookmarks Sidebar (Ctrl+B)")
        act_sidebar.setShortcut(QKeySequence("Ctrl+B"))
        act_sidebar.triggered.connect(self.toggle_sidebar)
        win.addAction(act_sidebar)
        tb.addAction(act_sidebar)

        act_open = QAction("Open", win)
        act_open.setToolTip("Open PDF (Ctrl+O)")
        act_open.setShortcut(QKeySequence.Open)
        act_open.triggered.connect(win.open_pdf_dialog)
        win.addAction(act_open)
        tb.addAction(act_open)

        tb.addSeparator()

        # Compact Page Navigation
        act_prev = QAction("◀", win)
        act_prev.setToolTip("Previous Page (Page Up)")
        act_prev.setShortcut(Qt.Key_PageUp)
        act_prev.triggered.connect(lambda: self.step_page(-1))
        tb.addAction(act_prev)

        self.page_spin = QSpinBox()
        self.page_spin.setMinimum(1)
        self.page_spin.setMaximum(1)
        self.page_spin.setButtonSymbols(QSpinBox.NoButtons)
        self.page_spin.setAlignment(Qt.AlignCenter)
        self.page_spin.setFixedWidth(44)
        self.page_spin.valueChanged.connect(self._on_spin_page)
        tb.addWidget(self.page_spin)

        self.lbl_total_pages = QLabel("/ 0")
        self.lbl_total_pages.setStyleSheet("color: #9da7b3; padding: 0 4px;")
        tb.addWidget(self.lbl_total_pages)

        act_next = QAction("▶", win)
        act_next.setToolTip("Next Page (Page Down)")
        act_next.setShortcut(Qt.Key_PageDown)
        act_next.triggered.connect(lambda: self.step_page(1))
        tb.addAction(act_next)

        tb.addSeparator()

        # Compact Zoom & View Controls
        act_zout = QAction("−", win)
        act_zout.setToolTip("Zoom Out (Ctrl+-)")
        act_zout.setShortcut(QKeySequence.ZoomOut)
        act_zout.triggered.connect(lambda: self.adjust_zoom(0.8))
        tb.addAction(act_zout)

        act_zin = QAction("+", win)
        act_zin.setToolTip("Zoom In (Ctrl++)")
        act_zin.setShortcut(QKeySequence.ZoomIn)
        act_zin.triggered.connect(lambda: self.adjust_zoom(1.25))
        tb.addAction(act_zin)

        act_fitw = QAction("Fit W", win)
        act_fitw.setToolTip("Fit Page Width")
        act_fitw.triggered.connect(self.fit_width)
        tb.addAction(act_fitw)

        act_fitp = QAction("Fit P", win)
        act_fitp.setToolTip("Fit Full Page")
        act_fitp.triggered.connect(self.fit_page)
        tb.addAction(act_fitp)

        act_rot = QAction("↻ 90°", win)
        act_rot.setToolTip("Rotate Page 90° Clockwise")
        act_rot.triggered.connect(self.rotate_view)
        tb.addAction(act_rot)

        tb.addSeparator()

        # Compact Search Box
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Find (Ctrl+F)...")
        self.search_input.setFixedWidth(185)
        self.search_input.returnPressed.connect(self.find_next)
        tb.addWidget(self.search_input)

        act_focus_search = QAction("Find", win)
        act_focus_search.setShortcut(QKeySequence.Find)
        act_focus_search.triggered.connect(self.search_input.setFocus)
        win.addAction(act_focus_search)

        btn_find = QPushButton("Next")
        btn_find.setToolTip("Find Next Match")
        btn_find.clicked.connect(self.find_next)
        tb.addWidget(btn_find)

        # Push subsequent plugin widgets (Edit & Sign, Updates) cleanly to the right
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        tb.addWidget(spacer)

        # Keep page controls synced whenever tabs or pages change
        win.tab_changed.connect(self.sync_controls)
        win._tools_sync_hook = self.sync_controls

    def sync_controls(self, tab=None):
        tab = tab or self.ctx.current_tab()
        self.page_spin.blockSignals(True)
        if tab:
            total = len(tab.doc)
            self.page_spin.setMaximum(max(1, total))
            self.page_spin.setValue(tab.canvas.page_index + 1)
            self.lbl_total_pages.setText(f"/ {total}")
        else:
            self.page_spin.setMaximum(1)
            self.page_spin.setValue(1)
            self.lbl_total_pages.setText("/ 0")
        self.page_spin.blockSignals(False)

    def toggle_sidebar(self):
        tab = self.ctx.current_tab()
        if tab:
            tab.toggle_sidebar()

    def _on_spin_page(self, val: int):
        tab = self.ctx.current_tab()
        if tab:
            tab.go_to_page(val - 1)

    def step_page(self, delta: int):
        tab = self.ctx.current_tab()
        if tab:
            target = tab.canvas.page_index + delta
            if 0 <= target < len(tab.doc):
                tab.go_to_page(target)
                self.sync_controls(tab)

    def adjust_zoom(self, factor: float):
        tab = self.ctx.current_tab()
        if tab:
            tab.canvas.set_zoom_smooth(tab.canvas.target_zoom * factor)

    def fit_width(self):
        tab = self.ctx.current_tab()
        if tab:
            tab.canvas.fit_width()

    def fit_page(self):
        tab = self.ctx.current_tab()
        if tab:
            tab.canvas.fit_page()

    def rotate_view(self):
        tab = self.ctx.current_tab()
        if tab:
            page = tab.doc[tab.canvas.page_index]
            page.set_rotation((page.rotation + 90) % 360)
            tab.canvas.render_page_sync()
            tab.populate_thumbnails()

    def find_next(self):
        tab = self.ctx.current_tab()
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
                self.sync_controls(tab)
                self.ctx.status_bar.showMessage(f"Found {len(rects)} match(es) on Page {p_idx + 1}")
                return

        self.ctx.status_bar.showMessage(f"No matches found for '{query}'")


def register(ctx):
    return ReaderToolsPlugin(ctx)