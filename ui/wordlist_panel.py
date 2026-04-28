"""Wordlist Manager Panel.

Table des wordlists (nom, path, size, catégorie, présent).
Dialog pour générer une wordlist custom depuis des mots de base
(users ou passwords connus + mutations).
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QDialog, QDialogButtonBox,
    QFileDialog, QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMenu, QPlainTextEdit, QPushButton, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from core.wordlist_manager import WordlistManager, WordlistEntry


class _GenerateDialog(QDialog):
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Générer une wordlist custom")
        self.setMinimumSize(520, 480)
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("Mots de base (un par ligne) :"))
        self._words = QPlainTextEdit()
        self._words.setPlaceholderText("admin\nroot\nwebadmin\n...")
        layout.addWidget(self._words)

        form = QFormLayout()
        self._name = QLineEdit("custom")
        form.addRow("Nom de sortie :", self._name)
        layout.addLayout(form)

        opts = QHBoxLayout()
        self._cap = QCheckBox("Capitaliser"); self._cap.setChecked(True)
        self._num = QCheckBox("+chiffres"); self._num.setChecked(True)
        self._spec = QCheckBox("+spéciaux"); self._spec.setChecked(True)
        self._years = QCheckBox("+années"); self._years.setChecked(True)
        self._leet = QCheckBox("Leet"); self._leet.setChecked(True)
        self._combos = QCheckBox("Combos (+lent)"); self._combos.setChecked(False)
        for c in (self._cap, self._num, self._spec, self._years, self._leet, self._combos):
            opts.addWidget(c)
        layout.addLayout(opts)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        layout.addWidget(bb)

    def get_values(self) -> dict:
        words = [l for l in self._words.toPlainText().splitlines() if l.strip()]
        return {
            "base_words": words,
            "output_name": self._name.text().strip() or "custom",
            "capitalize": self._cap.isChecked(),
            "numbers": self._num.isChecked(),
            "specials": self._spec.isChecked(),
            "years": self._years.isChecked(),
            "leet": self._leet.isChecked(),
            "combos": self._combos.isChecked(),
        }


class WordlistPanel(QWidget):
    def __init__(self, manager: WordlistManager, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._mgr = manager

        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)

        bar = QHBoxLayout()
        self._search = QLineEdit()
        self._search.setPlaceholderText(" Filtrer...")
        self._search.textChanged.connect(self._refresh)
        bar.addWidget(self._search, 1)

        btn_add = QPushButton("+ Ajouter")
        btn_add.clicked.connect(self._on_add)
        bar.addWidget(btn_add)

        btn_gen = QPushButton(" Générer")
        btn_gen.clicked.connect(self._on_generate)
        bar.addWidget(btn_gen)

        btn_refresh = QPushButton("")
        btn_refresh.setToolTip("Vérifier présence et tailles")
        btn_refresh.clicked.connect(self._on_refresh_metadata)
        bar.addWidget(btn_refresh)

        root.addLayout(bar)

        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(
            ["Présent", "Nom", "Catégorie", "Lignes", "Path"])
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        self._table.setContextMenuPolicy(Qt.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._on_context_menu)
        root.addWidget(self._table, 1)

        self._mgr.catalog_changed.connect(self._refresh)
        self._refresh()

    # ----------------------------------------------------------

    def _refresh(self) -> None:
        q = self._search.text().strip().lower()
        self._table.setRowCount(0)
        for e in self._mgr.all():
            if q:
                hay = f"{e.name} {e.path} {e.category} {e.description}".lower()
                if q not in hay:
                    continue
            row = self._table.rowCount()
            self._table.insertRow(row)

            presence = "[OK]" if e.present else "[KO]"
            pres_item = QTableWidgetItem(presence)
            pres_item.setTextAlignment(Qt.AlignCenter)
            self._table.setItem(row, 0, pres_item)

            self._table.setItem(row, 1, QTableWidgetItem(e.name))
            self._table.setItem(row, 2, QTableWidgetItem(e.category))

            lines = f"{e.lines:,}" if e.lines else "-"
            self._table.setItem(row, 3, QTableWidgetItem(lines))

            p_item = QTableWidgetItem(e.path)
            if not e.present:
                p_item.setForeground(QColor("#ef5350"))
            self._table.setItem(row, 4, p_item)

            self._table.item(row, 1).setData(Qt.UserRole, e.path)

        self._table.resizeColumnToContents(0)
        self._table.resizeColumnToContents(1)
        self._table.resizeColumnToContents(2)
        self._table.resizeColumnToContents(3)

    def _selected_entry(self) -> Optional[WordlistEntry]:
        row = self._table.currentRow()
        if row < 0:
            return None
        path = self._table.item(row, 1).data(Qt.UserRole)
        for e in self._mgr.all():
            if e.path == path:
                return e
        return None

    # ----------------------------------------------------------

    def _on_context_menu(self, point) -> None:
        e = self._selected_entry()
        if e is None:
            return
        m = QMenu(self)
        m.addAction("Copier le path",
                    lambda: QApplication.clipboard().setText(e.path))
        m.addSeparator()
        m.addAction(" Retirer du catalogue",
                    lambda: self._mgr.remove(e.path))
        m.exec_(self._table.viewport().mapToGlobal(point))

    def _on_refresh_metadata(self) -> None:
        self._mgr.refresh_metadata()
        self._refresh()

    def _on_add(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Ajouter une wordlist", "/usr/share/wordlists",
                                               "Text (*.txt *.lst *.dic);;Tous (*)")
        if not path:
            return
        name, ok_name = QFileDialog.getSaveFileName(self, "Nom descriptif",
                                                     Path(path).stem,
                                                     "Pas d'extension")
        # Pas super pratique ; on utilise juste stem
        self._mgr.add(WordlistEntry(
            name=Path(path).stem, path=path, category="misc",
            present=True,
        ))

    def _on_generate(self) -> None:
        dlg = _GenerateDialog(parent=self)
        if dlg.exec_() != QDialog.Accepted:
            return
        vals = dlg.get_values()
        try:
            target = self._mgr.generate_custom(**vals)
        except Exception as exc:
            from ui.dialogs import error_box
            error_box(self, "Erreur génération", str(exc))
            return
        from ui.dialogs import info_box
        info_box(self, "Wordlist générée", f"Écrite dans :\n{target}")
