"""Global Command History Panel.

Table avec date | terminal | tool | machine | commande | exit.
Recherche / filtre. Double-clic = copier la commande.
"""
from __future__ import annotations

import time
from typing import Optional

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QFont
from PyQt5.QtWidgets import (
    QAbstractItemView, QApplication, QHBoxLayout, QHeaderView, QLineEdit,
    QMenu, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from core.command_history import CommandHistory, HistoryEntry
from .widgets import frozen_updates


class HistoryPanel(QWidget):
    def __init__(self, history: CommandHistory, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._h = history

        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)

        bar = QHBoxLayout()
        self._search = QLineEdit()
        self._search.setPlaceholderText(" Filtrer (commande / tool / machine)...")
        self._search.textChanged.connect(self._refresh)
        bar.addWidget(self._search, 1)

        self._tool_filter = QLineEdit()
        self._tool_filter.setPlaceholderText("tool")
        self._tool_filter.setMaximumWidth(120)
        self._tool_filter.textChanged.connect(self._refresh)
        bar.addWidget(self._tool_filter)

        self._machine_filter = QLineEdit()
        self._machine_filter.setPlaceholderText("machine")
        self._machine_filter.setMaximumWidth(120)
        self._machine_filter.textChanged.connect(self._refresh)
        bar.addWidget(self._machine_filter)

        btn_clear = QPushButton("")
        btn_clear.setToolTip("Vider l'historique")
        btn_clear.clicked.connect(self._on_clear)
        bar.addWidget(btn_clear)

        root.addLayout(bar)

        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(
            ["Date", "Terminal", "Tool", "Machine", "Commande"])
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        self._table.setContextMenuPolicy(Qt.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._on_context_menu)
        self._table.cellDoubleClicked.connect(self._on_double_click)
        root.addWidget(self._table, 1)

        self._h.history_changed.connect(self._refresh)
        self._refresh()

    # ----------------------------------------------------------

    def _refresh(self) -> None:
        q = self._search.text().strip()
        tool = self._tool_filter.text().strip() or None
        machine = self._machine_filter.text().strip() or None

        entries = self._h.search(query=q, tool=tool, machine=machine)

        with frozen_updates(self._table):
            self._table.setRowCount(0)
            # Les plus récents en premier (déjà le cas avec search)
            for e in entries[:1000]:      # safety
                row = self._table.rowCount()
                self._table.insertRow(row)

                ts = time.strftime("%m-%d %H:%M:%S", time.localtime(e.ts))
                self._table.setItem(row, 0, QTableWidgetItem(ts))
                self._table.setItem(row, 1, QTableWidgetItem(e.terminal or "-"))
                self._table.setItem(row, 2, QTableWidgetItem(e.tool or "-"))
                self._table.setItem(row, 3, QTableWidgetItem(e.machine or "-"))

                cmd_item = QTableWidgetItem(e.command)
                cmd_item.setFont(QFont("Monospace", 9))
                if e.exit_code is not None and e.exit_code != 0:
                    cmd_item.setForeground(QColor("#ef5350"))
                self._table.setItem(row, 4, cmd_item)

                # Stock ref de l'entry sur la cellule 0
                self._table.item(row, 0).setData(Qt.UserRole, e)

            if self._table.rowCount() < 250:
                self._table.resizeColumnToContents(0)
                self._table.resizeColumnToContents(1)
                self._table.resizeColumnToContents(2)
                self._table.resizeColumnToContents(3)

    def _selected_entry(self) -> Optional[HistoryEntry]:
        row = self._table.currentRow()
        if row < 0:
            return None
        item = self._table.item(row, 0)
        if item is None:
            return None
        return item.data(Qt.UserRole)

    def _on_double_click(self, row: int, _col: int) -> None:
        item = self._table.item(row, 0)
        if item is None:
            return
        e: HistoryEntry = item.data(Qt.UserRole)
        QApplication.clipboard().setText(e.command)

    def _on_context_menu(self, point) -> None:
        e = self._selected_entry()
        if e is None:
            return
        m = QMenu(self)
        m.addAction("Copier la commande",
                    lambda: QApplication.clipboard().setText(e.command))
        m.exec_(self._table.viewport().mapToGlobal(point))

    def _on_clear(self) -> None:
        from ui.dialogs import confirm
        if confirm(self, "Vider l'historique",
                   "Supprimer toutes les commandes loggées ?"):
            self._h.clear()
