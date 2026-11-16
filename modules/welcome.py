import os
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QGridLayout, QFrame, QLabel, QPushButton
)


class WelcomePlugin:
    def __init__(self, ctx):
        self.ctx = ctx
        screen = ctx.welcome_slot
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
            QFrame#shortcutCard {
                background-color: #1c2026;
                border: 1px solid #30363d;
                border-radius: 8px;
            }
            QLabel#cardHeader {
                font-size: 13px;
                font-weight: bold;
                color: #e67e22;
                background: transparent;
            }
            QLabel#actionText {
                font-size: 12px;
                color: #c9d1d9;
                background: transparent;
            }
            QLabel#keyBadge {
                font-size: 11px;
                font-weight: 600;
                color: #f0f6fc;
                background-color: #2d333b;
                border: 1px solid #444c56;
                border-radius: 4px;
                padding: 3px 8px;
            }
        """)

        outer = QVBoxLayout(screen)
        outer.setAlignment(Qt.AlignCenter)
        outer.setSpacing(12)

        icon_file = ctx.resource_path("assets/icon.png")
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

        sub_lbl = QLabel(f"Portable 64-Bit PDF Studio by Abdul Samad  •  {ctx.app_version}")
        sub_lbl.setObjectName("subtitleLabel")
        sub_lbl.setAlignment(Qt.AlignCenter)
        outer.addWidget(sub_lbl)

        outer.addSpacing(14)

        self.btn_row = QHBoxLayout()
        self.btn_row.setAlignment(Qt.AlignCenter)
        self.btn_row.setSpacing(14)
        outer.addLayout(self.btn_row)

        outer.addSpacing(22)
        outer.addWidget(self._build_shortcuts_card(), alignment=Qt.AlignCenter)

        ctx.window._welcome_button_handler = self.add_button
        self.add_button("Open PDF...", ctx.window.open_pdf_dialog, primary=True)

    def _build_shortcuts_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("shortcutCard")
        card.setFixedWidth(500)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(10)

        header = QLabel("Keyboard Shortcuts & Controls")
        header.setObjectName("cardHeader")
        layout.addWidget(header)

        grid = QGridLayout()
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(8)

        shortcuts = [
            ("Open PDF(s)", "Ctrl + O  or  Drag & Drop"),
            ("Smooth Zoom In / Out", "Ctrl + Mouse Wheel  /  Ctrl + + / -"),
            ("Pan Canvas", "Click & Drag"),
            ("Next / Previous Page", "Page Down  /  Page Up"),
            ("Find Text", "Ctrl + F"),
        ]

        for row, (action, keys) in enumerate(shortcuts):
            lbl_act = QLabel(action)
            lbl_act.setObjectName("actionText")

            lbl_key = QLabel(keys)
            lbl_key.setObjectName("keyBadge")
            lbl_key.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

            grid.addWidget(lbl_act, row, 0, Qt.AlignLeft)
            grid.addWidget(lbl_key, row, 1, Qt.AlignRight)

        layout.addLayout(grid)
        return card

    def add_button(self, label: str, callback, primary: bool = False) -> QPushButton:
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
                QPushButton:pressed { background-color: #d35400; }
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
        self.btn_row.addWidget(btn)
        return btn


def register(ctx):
    return WelcomePlugin(ctx)