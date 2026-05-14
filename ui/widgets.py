"""Widgets réutilisables — SafeButton et autres."""
from __future__ import annotations
from contextlib import contextmanager
from typing import Iterator, Optional

from PyQt5.QtCore import Qt, QPoint
from PyQt5.QtWidgets import QPushButton, QWidget


class SafeButton(QPushButton):
    """QPushButton qui n'émet clicked() que si la souris est ENCORE
    dans la zone du bouton au moment du mouseRelease.
    Résout le bug Qt où clicked est émis même si on a draggé hors du bouton.
    """
    def __init__(self, text: str = "", parent: Optional[QWidget] = None):
        super().__init__(text, parent)

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.LeftButton:
            if self.rect().contains(event.pos()):
                super().mouseReleaseEvent(event)
            else:
                # Annule le visuel "pressé" sans émettre clicked
                self.setDown(False)
                self.update()
        else:
            super().mouseReleaseEvent(event)


@contextmanager
def frozen_updates(widget: QWidget) -> Iterator[None]:
    """Temporarily suspend repaints while rebuilding a heavy widget."""
    previous = widget.updatesEnabled()
    if previous:
        widget.setUpdatesEnabled(False)
    try:
        yield
    finally:
        if previous:
            widget.setUpdatesEnabled(True)
            widget.update()
