import os
import pymupdf
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QFileDialog, QInputDialog, QMessageBox, QMenu, QToolButton
)


class PdfEditorPlugin:
    def __init__(self, ctx):
        self.ctx = ctx

        # Add "Edit PDF" directly to the Welcome Screen
        ctx.add_welcome_action("Edit PDF", self.open_pdf_to_edit, primary=False)

        # Add Editor Dropdown Menu to the Main Toolbar
        ctx.toolbar.addSeparator()
        editor_btn = QToolButton(ctx.window)
        editor_btn.setText("Edit & Sign ▾")
        editor_btn.setPopupMode(QToolButton.InstantPopup)

        menu = QMenu(editor_btn)

        act_new = QAction("Create New Blank PDF...", ctx.window)
        act_new.triggered.connect(self.create_blank_pdf)
        menu.addAction(act_new)

        menu.addSeparator()

        act_text = QAction("Add Text to Current Page...", ctx.window)
        act_text.triggered.connect(self.add_text_to_page)
        menu.addAction(act_text)

        act_hl = QAction("Highlight Text Phrase...", ctx.window)
        act_hl.triggered.connect(self.highlight_phrase)
        menu.addAction(act_hl)

        act_sign = QAction("Place Image Signature (.png/.jpg)...", ctx.window)
        act_sign.triggered.connect(self.place_signature)
        menu.addAction(act_sign)

        menu.addSeparator()

        act_merge = QAction("Append / Merge Another PDF...", ctx.window)
        act_merge.triggered.connect(self.merge_pdf)
        menu.addAction(act_merge)

        act_blank_pg = QAction("Insert Blank Page After Current", ctx.window)
        act_blank_pg.triggered.connect(self.insert_blank_page)
        menu.addAction(act_blank_pg)

        act_del_pg = QAction("Delete Current Page", ctx.window)
        act_del_pg.triggered.connect(self.delete_current_page)
        menu.addAction(act_del_pg)

        menu.addSeparator()

        act_save_as = QAction("Save Copy As...", ctx.window)
        act_save_as.triggered.connect(self.save_copy_as)
        menu.addAction(act_save_as)

        editor_btn.setMenu(menu)
        ctx.toolbar.addWidget(editor_btn)

    def _save_and_reload(self, tab):
        """Safely saves incremental/full changes to the active PDF and refreshes the canvas."""
        temp_path = tab.file_path + ".tmp.pdf"
        tab.doc.save(temp_path, garbage=3, deflate=True)
        tab.doc.close()
        os.replace(temp_path, tab.file_path)
        tab.doc = pymupdf.open(tab.file_path)
        self.ctx.reload_current_tab()

    def open_pdf_to_edit(self):
        path, _ = QFileDialog.getOpenFileName(
            self.ctx.window, "Select PDF to Edit", "", "PDF Files (*.pdf)"
        )
        if path:
            self.ctx.open_file(path)
            self.ctx.status_bar.showMessage(
                f"Editing '{os.path.basename(path)}' — Use 'Edit & Sign ▾' in the top toolbar."
            )

    def create_blank_pdf(self):
        save_path, _ = QFileDialog.getSaveFileName(
            self.ctx.window, "Create New PDF", "Untitled.pdf", "PDF Files (*.pdf)"
        )
        if not save_path:
            return
        if not save_path.lower().endswith(".pdf"):
            save_path += ".pdf"

        doc = pymupdf.open()
        doc.new_page(width=595, height=842)  # Standard A4 (points)
        doc.save(save_path)
        doc.close()
        self.ctx.open_file(save_path)
        self.ctx.status_bar.showMessage(f"Created new A4 PDF: {os.path.basename(save_path)}")

    def add_text_to_page(self):
        tab = self.ctx.current_tab()
        if not tab:
            QMessageBox.information(self.ctx.window, "No PDF Open", "Open a PDF document first.")
            return

        text, ok = QInputDialog.getMultiLineText(
            self.ctx.window, "Insert Text", "Enter text to stamp onto the top-left area of this page:"
        )
        if not ok or not text.strip():
            return

        page = tab.doc[tab.canvas.page_index]
        page.insert_text((50, 70), text.strip(), fontsize=12, color=(0.1, 0.1, 0.1))
        self._save_and_reload(tab)
        self.ctx.status_bar.showMessage("Text inserted and saved.")

    def highlight_phrase(self):
        tab = self.ctx.current_tab()
        if not tab:
            QMessageBox.information(self.ctx.window, "No PDF Open", "Open a PDF document first.")
            return

        phrase, ok = QInputDialog.getText(
            self.ctx.window, "Highlight Phrase", "Enter exact word or phrase to highlight on this page:"
        )
        if not ok or not phrase.strip():
            return

        page = tab.doc[tab.canvas.page_index]
        rects = page.search_for(phrase.strip())
        if not rects:
            QMessageBox.information(self.ctx.window, "Not Found", f"'{phrase}' was not found on this page.")
            return

        for r in rects:
            annot = page.add_highlight_annot(r)
            annot.update()
        self._save_and_reload(tab)
        self.ctx.status_bar.showMessage(f"Highlighted {len(rects)} occurrence(s) of '{phrase}'.")

    def place_signature(self):
        tab = self.ctx.current_tab()
        if not tab:
            QMessageBox.information(self.ctx.window, "No PDF Open", "Open a PDF document first.")
            return

        sig_path, _ = QFileDialog.getOpenFileName(
            self.ctx.window, "Select Signature Image", "", "Images (*.png *.jpg *.jpeg)"
        )
        if not sig_path:
            return

        page = tab.doc[tab.canvas.page_index]
        rect = page.rect
        # Place cleanly in bottom-right signature block area (160x65 pts)
        sig_rect = pymupdf.Rect(rect.width - 210, rect.height - 115, rect.width - 50, rect.height - 50)
        page.insert_image(sig_rect, filename=sig_path, keep_proportion=True)
        self._save_and_reload(tab)
        self.ctx.status_bar.showMessage("Signature placed and saved.")

    def merge_pdf(self):
        tab = self.ctx.current_tab()
        if not tab:
            return

        other_path, _ = QFileDialog.getOpenFileName(
            self.ctx.window, "Select PDF to Append", "", "PDF Files (*.pdf)"
        )
        if not other_path:
            return

        other_doc = pymupdf.open(other_path)
        added_pages = len(other_doc)
        tab.doc.insert_pdf(other_doc)
        other_doc.close()
        self._save_and_reload(tab)
        self.ctx.status_bar.showMessage(f"Merged {added_pages} page(s) from {os.path.basename(other_path)}.")

    def insert_blank_page(self):
        tab = self.ctx.current_tab()
        if not tab:
            return

        idx = tab.canvas.page_index
        ref_rect = tab.doc[idx].rect
        tab.doc.new_page(pno=idx + 1, width=ref_rect.width, height=ref_rect.height)
        self._save_and_reload(tab)
        self.ctx.status_bar.showMessage(f"Inserted blank page after Page {idx + 1}.")

    def delete_current_page(self):
        tab = self.ctx.current_tab()
        if not tab:
            return
        if len(tab.doc) <= 1:
            QMessageBox.warning(self.ctx.window, "Cannot Delete", "A PDF must contain at least 1 page.")
            return

        idx = tab.canvas.page_index
        reply = QMessageBox.question(
            self.ctx.window, "Delete Page", f"Permanently delete Page {idx + 1}?"
        )
        if reply == QMessageBox.Yes:
            tab.doc.delete_page(idx)
            self._save_and_reload(tab)
            self.ctx.status_bar.showMessage(f"Deleted Page {idx + 1}.")

    def save_copy_as(self):
        tab = self.ctx.current_tab()
        if not tab:
            return

        out_path, _ = QFileDialog.getSaveFileName(
            self.ctx.window, "Save PDF Copy As", tab.file_path, "PDF Files (*.pdf)"
        )
        if out_path:
            tab.doc.save(out_path, garbage=3, deflate=True)
            self.ctx.status_bar.showMessage(f"Saved copy to {os.path.basename(out_path)}.")


def register(ctx):
    return PdfEditorPlugin(ctx)