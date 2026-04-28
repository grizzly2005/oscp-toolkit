"""Tool Panel — sidebar gauche.

Affiche la liste des outils groupés par catégorie (tree widget), avec :
- Favoris (étoile cliquable)
- Search bar live
- Indicateur de présence ([OK]/[KO]) via check_integrity
- Tooltip description
- Menu contextuel : édition, duplication, suppression
- Double-click : émet `launch_requested(tool, template_index=-1)` pour
  choisir le template dans un sub-menu ou dans l'UI

Les actions complexes (édition du tool) sont déléguées à un dialog
externe (dialogs.ToolEditDialog, inclus ici).
"""

from __future__ import annotations

from typing import List, Optional

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QIcon
from PyQt5.QtWidgets import (
    QAction, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
    QLineEdit, QMenu, QMessageBox, QPushButton, QPlainTextEdit,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from core.tool_manager import Tool, ToolManager
from core.logger import get_logger
from .dialogs import confirm, error_box

log = get_logger(__name__)


CATEGORY_ORDER = [
    "Enumeration", "AD", "Exploitation", "PrivEsc", "Cracking",
    "Transfert", "Listener", "Divers",
]


class ToolEditDialog(QDialog):
    def __init__(self, tool: Optional[Tool] = None, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Outil" if tool else "Nouvel outil")
        self.setMinimumWidth(560)
        self._tool = tool

        layout = QFormLayout(self)
        self._name = QLineEdit(tool.name if tool else "")
        self._category = QLineEdit(tool.category if tool else "Divers")
        self._tags = QLineEdit(",".join(tool.tags) if tool else "")
        self._path = QLineEdit(tool.path if tool else "")
        self._description = QLineEdit(tool.description if tool else "")
        self._doc = QLineEdit(tool.doc_link if tool else "")
        self._templates = QPlainTextEdit(
            "\n".join(tool.templates) if tool else ""
        )
        self._templates.setFont(QFont("Monospace"))
        self._templates.setPlaceholderText(
            "Un template par ligne. Utiliser {{IP}}, {{LHOST}}, {{CRED:user}}, ..."
        )

        layout.addRow("Nom", self._name)
        layout.addRow("Catégorie", self._category)
        layout.addRow("Tags (virgule)", self._tags)
        layout.addRow("Chemin binaire", self._path)
        layout.addRow("Description", self._description)
        layout.addRow("Doc (chemin .md)", self._doc)
        layout.addRow("Templates", self._templates)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def result_tool(self) -> Tool:
        templates = [
            t.strip() for t in self._templates.toPlainText().splitlines()
            if t.strip()
        ]
        tags = [t.strip() for t in self._tags.text().split(",") if t.strip()]
        return Tool(
            name=self._name.text().strip(),
            category=self._category.text().strip() or "Divers",
            tags=tags,
            path=self._path.text().strip(),
            description=self._description.text().strip(),
            doc_link=self._doc.text().strip(),
            templates=templates,
            favorite=self._tool.favorite if self._tool else False,
            history=self._tool.history if self._tool else [],
            # Préserver les champs non-éditables dans le dialog
            os_target=self._tool.os_target if self._tool else "multi",
            dependencies=list(self._tool.dependencies) if self._tool else [],
        )


class ToolPanel(QWidget):
    launch_requested = pyqtSignal(object, int)       # Tool, template_index (-1 = prompt)
    edit_requested = pyqtSignal(object)               # Tool
    doc_requested = pyqtSignal(str)                   # doc_link

    def __init__(self, tool_manager: ToolManager, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._tm = tool_manager

        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(4)

        # Search bar
        search_row = QHBoxLayout()
        self._search = QLineEdit()
        self._search.setPlaceholderText(" Rechercher...")
        self._search.textChanged.connect(self._rebuild)
        search_row.addWidget(self._search)

        btn_new = QPushButton("+")
        btn_new.setToolTip("Ajouter un outil")
        btn_new.clicked.connect(self._on_new_tool)
        search_row.addWidget(btn_new)

        btn_check = QPushButton("")
        btn_check.setToolTip("Vérifier intégrité (binaires)")
        btn_check.clicked.connect(self._on_check_integrity)
        search_row.addWidget(btn_check)

        root.addLayout(search_row)

        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setAlternatingRowColors(True)
        self._tree.setIndentation(14)
        self._tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        self._tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._on_context_menu)
        root.addWidget(self._tree, 1)

        self._tm.tools_changed.connect(self._rebuild)
        self._tm.integrity_checked.connect(lambda _: self._rebuild())
        self._rebuild()

    # ----------------------------------------------------------

    def _rebuild(self) -> None:
        self._tree.clear()
        query = self._search.text().strip().lower()
        favorites = [t for t in self._tm.all() if t.favorite]
        if favorites:
            fav_root = QTreeWidgetItem(["* Favoris"])
            fav_root.setForeground(0, QColor("#ffa000"))
            for t in favorites:
                if query and query not in t.name.lower():
                    continue
                fav_root.addChild(self._make_item(t))
            self._tree.addTopLevelItem(fav_root)
            fav_root.setExpanded(True)

        by_cat = self._tm.by_category()
        # Ordre maîtrisé, puis catégories inconnues en fin
        ordered = [c for c in CATEGORY_ORDER if c in by_cat] + [
            c for c in sorted(by_cat.keys()) if c not in CATEGORY_ORDER
        ]
        for cat in ordered:
            cat_item = QTreeWidgetItem([cat])
            f = cat_item.font(0)
            f.setBold(True)
            cat_item.setFont(0, f)
            added = 0
            for t in by_cat[cat]:
                if query:
                    haystack = (t.name + " " + t.description + " " + " ".join(t.tags)).lower()
                    if query not in haystack:
                        continue
                cat_item.addChild(self._make_item(t))
                added += 1
            if added == 0 and query:
                continue
            self._tree.addTopLevelItem(cat_item)
            cat_item.setExpanded(True)

    def _make_item(self, tool: Tool) -> QTreeWidgetItem:
        label = tool.name
        if tool.present is True:
            label = "[OK]" + label
        elif tool.present is False:
            label = "[KO]" + label
        elif tool.path == "":
            label = "*" + label    # à transférer sur cible
        item = QTreeWidgetItem([label])
        item.setData(0, Qt.UserRole, tool.name)
        tooltip = tool.description or tool.name
        if tool.templates:
            tooltip += f"\n{len(tool.templates)} template(s)"
        if tool.path:
            tooltip += f"\npath: {tool.path}"
        item.setToolTip(0, tooltip)
        return item

    # ----------------------------------------------------------

    def _on_check_integrity(self) -> None:
        self._tm.check_integrity(force=True)

    def _on_new_tool(self) -> None:
        dlg = ToolEditDialog(parent=self)
        if dlg.exec_() == QDialog.Accepted:
            new_tool = dlg.result_tool()
            if not new_tool.name:
                error_box(self, "Invalide", "Le nom est requis.")
                return
            try:
                self._tm.add(new_tool)
            except ValueError as exc:
                error_box(self, "Doublon", str(exc))

    def _on_item_double_clicked(self, item: QTreeWidgetItem, col: int) -> None:
        name = item.data(0, Qt.UserRole)
        if not name:
            return
        tool = self._tm.get(name)
        if tool is None:
            return
        # Si plusieurs templates, on laisse main_window choisir via signal
        self.launch_requested.emit(tool, -1)

    def _on_context_menu(self, point) -> None:
        item = self._tree.itemAt(point)
        if item is None:
            return
        name = item.data(0, Qt.UserRole)
        if not name:
            return
        tool = self._tm.get(name)
        if tool is None:
            return
        menu = QMenu(self)

        if tool.templates:
            sub = menu.addMenu("Lancer template...")
            for i, tpl in enumerate(tool.templates):
                act = QAction(tpl[:80] + ("..." if len(tpl) > 80 else ""), self)
                act.triggered.connect(
                    lambda _checked=False, t=tool, idx=i: self.launch_requested.emit(t, idx)
                )
                sub.addAction(act)

        fav_label = "* Retirer des favoris" if tool.favorite else " Ajouter aux favoris"
        fav_act = QAction(fav_label, self)
        fav_act.triggered.connect(lambda: self._tm.toggle_favorite(tool.name))
        menu.addAction(fav_act)

        edit_act = QAction("Éditer...", self)
        edit_act.triggered.connect(lambda: self._edit_tool(tool))
        menu.addAction(edit_act)

        if tool.doc_link:
            doc_act = QAction(" Ouvrir documentation", self)
            doc_act.triggered.connect(lambda: self.doc_requested.emit(tool.doc_link))
            menu.addAction(doc_act)

        del_act = QAction("Supprimer...", self)
        del_act.triggered.connect(lambda: self._delete_tool(tool))
        menu.addAction(del_act)

        menu.exec_(self._tree.viewport().mapToGlobal(point))

    def _edit_tool(self, tool: Tool) -> None:
        dlg = ToolEditDialog(tool=tool, parent=self)
        if dlg.exec_() == QDialog.Accepted:
            updated = dlg.result_tool()
            if updated.name != tool.name:
                # Rename = remove + add. ATTENTION : si on remove avant
                # d'add et que add echoue (nom deja pris), l'outil est
                # perdu. On essaie d'add d'abord ; si OK, on remove l'ancien.
                # Si le nouveau nom existe deja, l'ancien reste intact.
                try:
                    self._tm.add(updated)
                except ValueError as exc:
                    error_box(self, "Erreur", str(exc))
                    return
                try:
                    self._tm.remove(tool.name)
                except Exception:
                    # add a reussi mais remove a echoue : on a un doublon
                    # mais pas de perte. On loggue et on continue.
                    log.exception("Could not remove old tool name '%s' after rename to '%s'",
                                  tool.name, updated.name)
            else:
                self._tm.update(updated)

    def _delete_tool(self, tool: Tool) -> None:
        if confirm(self, "Supprimer", f"Supprimer l'outil '{tool.name}' ?"):
            self._tm.remove(tool.name)
