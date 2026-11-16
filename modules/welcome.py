import os
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QVBoxLayout, QHBoxLayout, QLabel, QPushButton


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
            QLabel#hintLabel {
                font-size: 12px;
                color: #768390;
                margin-top: 12px;
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

        outer.addSpacing(16)

        self.btn_row = QHBoxLayout()
        self.btn_row.setAlignment(Qt.AlignCenter)
        self.btn_row.setSpacing(14)
        outer.addLayout(self.btn_row)

        hint_lbl = QLabel("Tip: You can also drag and drop any PDF file anywhere onto this window")
        hint_lbl.setObjectName("hintLabel")
        hint_lbl.setAlignment(Qt.AlignCenter)
        outer.addWidget(hint_lbl)

        # Register handler so other plugins can add buttons cleanly
        ctx.window._welcome_button_handler = self.add_button

        # Default primary Open PDF button
        self.add_button("Open PDF...", ctx.window.open_pdf_dialog, primary=True)

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