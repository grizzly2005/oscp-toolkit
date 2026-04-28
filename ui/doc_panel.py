"""Doc Panel — affichage des cheatsheets Markdown.

- Liste des fichiers .md du dossier cheatsheets/ (récursive)
- Recherche plein-texte
- Rendu : `markdown` si dispo sinon texte brut
- Liens relatifs + externes
- Petite table des matières (TOC) générée à la volée (niveau 2 et 3)
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional

from PyQt5.QtCore import Qt, QUrl, pyqtSignal
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QLineEdit, QListWidget, QListWidgetItem,
    QPushButton, QSplitter, QTextBrowser, QVBoxLayout, QWidget, QLabel,
)


class DocPanel(QWidget):
    """Panneau Documentation / Cheatsheets."""

    def __init__(
        self,
        cheatsheets_dir: Path | str = "cheatsheets",
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.cheats_dir = Path(cheatsheets_dir)
        self.cheats_dir.mkdir(parents=True, exist_ok=True)

        root = QVBoxLayout(self)
        root.setContentsMargins(2, 2, 2, 2)

        # Search bar
        row = QHBoxLayout()
        self._search = QLineEdit()
        self._search.setPlaceholderText(" Rechercher dans les cheatsheets...")
        self._search.textChanged.connect(self._refresh_list)
        row.addWidget(self._search)
        reload_btn = QPushButton("->")
        reload_btn.setMaximumWidth(30)
        reload_btn.clicked.connect(self._refresh_list)
        row.addWidget(reload_btn)
        root.addLayout(row)

        splitter = QSplitter(Qt.Horizontal)

        self._list = QListWidget()
        self._list.setSelectionMode(QAbstractItemView.SingleSelection)
        self._list.currentItemChanged.connect(self._on_current_changed)
        splitter.addWidget(self._list)

        right = QWidget()
        r_layout = QVBoxLayout(right)
        r_layout.setContentsMargins(0, 0, 0, 0)

        self._title = QLabel("-")
        f = self._title.font(); f.setBold(True); self._title.setFont(f)
        r_layout.addWidget(self._title)

        self._browser = QTextBrowser()
        self._browser.setOpenExternalLinks(True)
        self._browser.setFont(QFont("Sans Serif", 10))
        r_layout.addWidget(self._browser, 1)

        splitter.addWidget(right)
        splitter.setSizes([200, 640])
        root.addWidget(splitter)

        self._refresh_list()

    # ----------------------------------------------------------

    def load_doc(self, path: str) -> None:
        """Accès programmatique depuis ailleurs (Tool Panel doc_requested)."""
        p = Path(path)
        if not p.is_absolute():
            p = Path.cwd() / p
        if not p.exists():
            return
        # Sélectionner l'item dans la liste si présent
        for i in range(self._list.count()):
            item = self._list.item(i)
            if item.data(Qt.UserRole) == str(p):
                self._list.setCurrentRow(i)
                return
        # Sinon charger directement sans sélection
        self._render_file(p)

    def _refresh_list(self) -> None:
        query = self._search.text().strip().lower()
        self._list.clear()
        files = sorted(self.cheats_dir.rglob("*.md"))
        for p in files:
            if query:
                try:
                    content = p.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    content = ""
                if query not in content.lower() and query not in p.stem.lower():
                    continue
            rel = p.relative_to(self.cheats_dir)
            item = QListWidgetItem(str(rel))
            item.setData(Qt.UserRole, str(p))
            self._list.addItem(item)

    def _on_current_changed(self, current: Optional[QListWidgetItem], _prev) -> None:
        if current is None:
            return
        p = Path(current.data(Qt.UserRole))
        self._render_file(p)

    def _render_file(self, p: Path) -> None:
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            self._browser.setPlainText(f"Cannot read {p}: {exc}")
            return
        # Python 3.8 compat : pas de Path.is_relative_to
        try:
            rel = p.relative_to(self.cheats_dir)
            self._title.setText(str(rel))
        except ValueError:
            self._title.setText(p.name)

        try:
            import markdown   # type: ignore
            html = markdown.markdown(
                text,
                extensions=["fenced_code", "tables", "toc", "admonition"],
            )
            # Ajouter une minimale feuille de style
            styled = f"""
            <style>
              body {{ font-family: sans-serif; }}
              code {{ background: #f0f0f0; padding: 1px 4px; border-radius: 3px; }}
              pre  {{ background: #f0f0f0; padding: 6px; border-radius: 4px; overflow-x: auto; }}
              h1, h2, h3 {{ color: #1565c0; }}
              table {{ border-collapse: collapse; }}
              th, td {{ border: 1px solid #ccc; padding: 3px 8px; }}
            </style>
            {html}
            """
            self._browser.setHtml(styled)
            self._browser.setSearchPaths([str(p.parent)])
        except ImportError:
            self._browser.setPlainText(text)
