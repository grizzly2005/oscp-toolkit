"""Exam Timer — compte a rebours OSCP dans la status bar.

Widget autonome a embarquer dans StatusBar.
  - Click : demarrer / pause / reprendre
  - Right-click : menu (reset, set duration)
  - Auto-save : state dans config/exam_timer.json

States :
  - idle      : pas demarre
  - running   : timer actif
  - paused    : en pause
  - finished  : duree ecoulee

Couleurs (progression) :
  - > 50% restant : vert
  - 25% - 50%     : orange
  - < 25%         : rouge clignotant
"""
from __future__ import annotations

import time
from typing import Optional

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QPalette
from PyQt5.QtWidgets import (
    QAction, QInputDialog, QLabel, QMenu, QMessageBox, QWidget,
)

from core.config_manager import ConfigManager
from core.logger import get_logger

log = get_logger(__name__)


# Duree OSCP par defaut = 23h45 (85500 sec)
DEFAULT_DURATION = 23 * 3600 + 45 * 60


class ExamTimer(QLabel):
    """Widget status bar : compte a rebours configurable."""

    expired = pyqtSignal()

    def __init__(self, config: ConfigManager, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._cm = config

        # State
        self._duration: int = DEFAULT_DURATION
        self._remaining: int = DEFAULT_DURATION
        self._state: str = "idle"          # idle / running / paused / finished
        self._start_ts: Optional[float] = None

        # UI
        self.setMinimumWidth(160)
        self.setAlignment(Qt.AlignCenter)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(
            "Timer exam OSCP\n"
            "Clic : start/pause\n"
            "Clic droit : menu"
        )
        self.setAutoFillBackground(True)

        # Tick
        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(1000)
        self._tick_timer.timeout.connect(self._on_tick)

        # Blink pour les dernieres 15 min
        self._blink_on = False
        self._blink_timer = QTimer(self)
        self._blink_timer.setInterval(500)
        self._blink_timer.timeout.connect(self._on_blink)

        # Right click menu
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_context_menu)

        self._load()
        self._refresh()

    # -- Persistence ---------------------------------------------------------

    def _load(self) -> None:
        data = self._cm.load("exam_timer")
        self._duration = int(data.get("duration", DEFAULT_DURATION))
        self._remaining = int(data.get("remaining", self._duration))
        self._state = data.get("state", "idle")
        # Si on etait en running, on resume pas automatiquement -> paused
        if self._state == "running":
            self._state = "paused"

    def _save(self) -> None:
        self._cm.save("exam_timer", {
            "duration": self._duration,
            "remaining": self._remaining,
            "state": self._state,
        })

    # -- Mouse ---------------------------------------------------------------

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            if self._state in ("idle", "paused"):
                self.start()
            elif self._state == "running":
                self.pause()
            elif self._state == "finished":
                self.reset()
        super().mousePressEvent(event)

    # -- Controls ------------------------------------------------------------

    def start(self) -> None:
        if self._state in ("running", "finished"):
            return
        self._state = "running"
        self._start_ts = time.time()
        self._tick_timer.start()
        self._save()
        self._refresh()
        log.info("ExamTimer started (remaining=%ds)", self._remaining)

    def pause(self) -> None:
        if self._state != "running":
            return
        self._consume_elapsed()
        self._state = "paused"
        self._tick_timer.stop()
        self._blink_timer.stop()
        self._save()
        self._refresh()
        log.info("ExamTimer paused (remaining=%ds)", self._remaining)

    def reset(self) -> None:
        self._state = "idle"
        self._remaining = self._duration
        self._start_ts = None
        self._tick_timer.stop()
        self._blink_timer.stop()
        self._save()
        self._refresh()
        log.info("ExamTimer reset")

    def set_duration(self, seconds: int) -> None:
        self._duration = max(60, int(seconds))
        if self._state == "idle":
            self._remaining = self._duration
        self._save()
        self._refresh()

    def remaining(self) -> int:
        return self._remaining

    def state(self) -> str:
        return self._state

    # -- Tick ----------------------------------------------------------------

    def _consume_elapsed(self) -> None:
        if self._start_ts is None:
            return
        now = time.time()
        elapsed = int(now - self._start_ts)
        self._remaining = max(0, self._remaining - elapsed)
        self._start_ts = now

    def _on_tick(self) -> None:
        self._consume_elapsed()

        if self._remaining <= 0:
            self._state = "finished"
            self._tick_timer.stop()
            self._blink_timer.start()
            self._save()
            self._refresh()
            self.expired.emit()
            return

        # Blink dans les dernieres 15 min
        if self._remaining < 15 * 60 and not self._blink_timer.isActive():
            self._blink_timer.start()
        elif self._remaining >= 15 * 60 and self._blink_timer.isActive():
            self._blink_timer.stop()
            self._blink_on = False

        # Persiste toutes les 60s seulement (pas a chaque tick) :
        # sur 24h d'exam OSCP ca fait 86400 fsync au lieu de 1440,
        # c'est usure pour rien.
        if self._remaining % 60 == 0:
            self._save()
        self._refresh()

    def _on_blink(self) -> None:
        self._blink_on = not self._blink_on
        self._refresh()

    # -- Render --------------------------------------------------------------

    def _refresh(self) -> None:
        h = self._remaining // 3600
        m = (self._remaining % 3600) // 60
        s = self._remaining % 60
        time_str = f"{h:02d}:{m:02d}:{s:02d}"

        if self._state == "idle":
            prefix = "[-]"
            color = "#9e9e9e"
        elif self._state == "paused":
            prefix = "[||]"
            color = "#ffb74d"
        elif self._state == "finished":
            prefix = "[!!]"
            color = "#ef5350" if self._blink_on else "#ffffff"
        else:
            prefix = "[>]"
            # Couleur selon progression
            ratio = self._remaining / self._duration if self._duration else 0
            if ratio > 0.5:
                color = "#81c784"     # vert
            elif ratio > 0.25:
                color = "#ffb74d"     # orange
            else:
                if self._blink_on:
                    color = "#ef5350"
                else:
                    color = "#ffffff"

        self.setText(f"{prefix} {time_str}")
        self.setStyleSheet(
            f"QLabel {{ "
            f"color: {color}; "
            f"font-family: Monospace; "
            f"font-weight: bold; "
            f"padding: 2px 8px; "
            f"border: 1px solid #333; "
            f"border-radius: 3px; "
            f"background: #1a1a1a; "
            f"}}"
        )

    # -- Menu ----------------------------------------------------------------

    def _on_context_menu(self, point) -> None:
        menu = QMenu(self)

        if self._state == "idle":
            act_start = QAction("Demarrer", self)
            act_start.triggered.connect(self.start)
            menu.addAction(act_start)
        elif self._state == "running":
            act_pause = QAction("Pause", self)
            act_pause.triggered.connect(self.pause)
            menu.addAction(act_pause)
        elif self._state == "paused":
            act_resume = QAction("Reprendre", self)
            act_resume.triggered.connect(self.start)
            menu.addAction(act_resume)

        act_reset = QAction("Reset", self)
        act_reset.triggered.connect(self._confirm_reset)
        menu.addAction(act_reset)

        menu.addSeparator()

        act_set = QAction("Configurer duree...", self)
        act_set.triggered.connect(self._on_set_duration)
        menu.addAction(act_set)

        menu.exec_(self.mapToGlobal(point))

    def _confirm_reset(self) -> None:
        res = QMessageBox.question(
            self, "Reset timer",
            "Reset le timer ? Le temps ecoule sera perdu.",
            QMessageBox.Yes | QMessageBox.No,
        )
        if res == QMessageBox.Yes:
            self.reset()

    def _on_set_duration(self) -> None:
        # Propose en heures
        current_h = self._duration / 3600
        hours, ok = QInputDialog.getDouble(
            self, "Duree timer",
            "Duree en heures (defaut OSCP : 23.75) :",
            value=current_h, min=0.25, max=72, decimals=2,
        )
        if ok:
            self.set_duration(int(hours * 3600))
