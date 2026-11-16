"""
PageSmith Central Module Registry
---------------------------------
Add new feature modules here (e.g., pdfeditor, signer, takeoff) so PyInstaller
automatically bundles them into the single-file executable without editing main.py.
"""
from modules import welcome
from modules import updater
from modules import pdfeditor
# Future modules — uncomment/add as you build them:

def register_all(ctx) -> list:
    """Initializes and registers every bundled PageSmith plugin."""
    active_modules = [
        welcome,
        updater,
        pdfeditor,
    ]

    loaded = []
    for mod in active_modules:
        try:
            if hasattr(mod, "register"):
                loaded.append(mod.register(ctx))
        except Exception as exc:
            ctx.status_bar.showMessage(f"Plugin error ({mod.__name__}): {exc}")
    return loaded