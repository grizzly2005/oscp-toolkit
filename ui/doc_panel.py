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

from PyQt5.QtCore import Qt, QTimer, QUrl, pyqtSignal
from PyQt5.QtGui import QDesktopServices, QFont
from PyQt5.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QLineEdit, QListWidget, QListWidgetItem,
    QPushButton, QSplitter, QTextBrowser, QVBoxLayout, QWidget, QLabel,
)
from .widgets import frozen_updates


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
        self.setObjectName("docPanel")
        self._install_style()

        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)

        header = QHBoxLayout()
        self._heading = QLabel("Cheatsheets")
        self._heading.setObjectName("docHeading")
        header.addWidget(self._heading)
        header.addStretch()
        open_btn = QPushButton("Ouvrir dossier")
        open_btn.setObjectName("docOpen")
        open_btn.clicked.connect(self._open_folder)
        header.addWidget(open_btn)
        root.addLayout(header)

        # Search bar
        row = QHBoxLayout()
        self._search = QLineEdit()
        self._search.setPlaceholderText(" Rechercher dans les cheatsheets...")
        self._search.textChanged.connect(lambda: self._search_timer.start())
        row.addWidget(self._search)
        reload_btn = QPushButton("Rafraichir")
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
        self._title.setObjectName("docTitle")
        f = self._title.font(); f.setBold(True); self._title.setFont(f)
        r_layout.addWidget(self._title)

        self._browser = QTextBrowser()
        self._browser.setOpenExternalLinks(True)
        self._browser.setFont(QFont("Sans Serif", 10))
        self._browser.setObjectName("docBrowser")
        r_layout.addWidget(self._browser, 1)

        splitter.addWidget(right)
        splitter.setSizes([200, 640])
        root.addWidget(splitter)

        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(180)
        self._search_timer.timeout.connect(self._refresh_list)

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
        files = sorted(self.cheats_dir.rglob("*.md"))
        shown = 0
        with frozen_updates(self._list):
            self._list.clear()
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
                shown += 1
        self._heading.setText(f"Cheatsheets ({shown}/{len(files)})")
        if shown and self._list.currentRow() < 0:
            self._list.setCurrentRow(0)
        elif not shown:
            self._title.setText("-")
            self._browser.setHtml(
                "<div style='color:#9e9e9e; padding:12px;'>Aucune cheatsheet trouvee.</div>"
            )

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
              body {{
                font-family: "Segoe UI", "Noto Sans", sans-serif;
                background: #181818;
                color: #d4d4d4;
                line-height: 1.45;
              }}
              h1, h2, h3 {{
                color: #4fc3f7;
                border-bottom: 1px solid #333;
                padding-bottom: 4px;
              }}
              code {{
                background: #252526;
                color: #ffe0b2;
                padding: 2px 5px;
                border-radius: 3px;
              }}
              pre {{
                background: #101010;
                border: 1px solid #333;
                border-left: 4px solid #4fc3f7;
                padding: 10px;
                border-radius: 4px;
                white-space: pre-wrap;
              }}
              pre code {{ background: transparent; color: #d4d4d4; padding: 0; }}
              blockquote {{
                border-left: 4px solid #ffb74d;
                margin-left: 0;
                padding-left: 10px;
                color: #cfcfcf;
              }}
              table {{ border-collapse: collapse; width: 100%; }}
              th, td {{ border: 1px solid #333; padding: 5px 8px; }}
              th {{ background: #252526; color: #ffffff; }}
              a {{ color: #81d4fa; }}
            </style>
            {html}
            """
            self._browser.setHtml(styled)
            self._browser.setSearchPaths([str(p.parent)])
        except ImportError:
            self._browser.setPlainText(text)

    def _open_folder(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.cheats_dir.resolve())))

    def _install_style(self) -> None:
        self.setStyleSheet("""
            QWidget#docPanel QLabel#docHeading {
                color: #4fc3f7;
                font-weight: bold;
                font-size: 11pt;
            }
            QWidget#docPanel QLabel#docTitle {
                color: #eceff1;
                padding: 4px 6px;
                background: #252526;
                border: 1px solid #333;
                border-radius: 4px;
            }
            QWidget#docPanel QPushButton#docOpen {
                background: #34343a;
                border-color: #5a5a64;
            }
            QWidget#docPanel QListWidget::item {
                padding: 5px 6px;
            }
            QTextBrowser#docBrowser {
                padding: 8px;
            }
        """)
