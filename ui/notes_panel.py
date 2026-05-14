"""Notes Panel — liste de notes + éditeur Markdown + preview.

Layout :
┌──────┬──────────────────────────┐
│ List │ Toolbar [title][save][↻] │
│  of  │ ───────────────────────  │
│notes │ Editor (plain text MD)   │
│      │ ───────────────────────  │
│      │ Preview (QTextBrowser)   │
└──────┴──────────────────────────┘

- Auto-save toutes les 30s et à la désactivation du widget.
- Insertion screenshot (depuis clipboard) via bouton dédié.
- Preview à la demande (toggle) — si `markdown` absent, preview désactivée.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PyQt5.QtCore import QTimer, Qt, pyqtSignal
from PyQt5.QtGui import QFont, QKeySequence
from PyQt5.QtWidgets import (
    QAbstractItemView, QAction, QFileDialog, QHBoxLayout, QInputDialog,
    QLabel, QListWidget, QListWidgetItem, QMenu, QMessageBox,
    QPlainTextEdit, QPushButton, QShortcut, QSplitter, QTextBrowser, QToolBar,
    QVBoxLayout, QWidget,
)

from core.notes import Note, NotesManager
from .dialogs import confirm, error_box, info_box
from .widgets import frozen_updates


class NotesPanel(QWidget):
    note_switched = pyqtSignal(object)           # Note or None
    append_command_requested = pyqtSignal(str)   # pour que main_window pousse

    def __init__(self, notes_manager: NotesManager, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._nm = notes_manager

        root = QVBoxLayout(self)
        root.setContentsMargins(2, 2, 2, 2)

        splitter = QSplitter(Qt.Horizontal)

        # Left : list
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        btn_new = QPushButton("+ Nouvelle note")
        btn_new.clicked.connect(self._on_new)
        left_layout.addWidget(btn_new)

        self._list = QListWidget()
        self._list.setSelectionMode(QAbstractItemView.SingleSelection)
        self._list.currentItemChanged.connect(self._on_current_changed)
        self._list.setContextMenuPolicy(Qt.CustomContextMenu)
        self._list.customContextMenuRequested.connect(self._on_context_menu)
        left_layout.addWidget(self._list, 1)

        splitter.addWidget(left)

        # Right : editor + preview
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)

        toolbar = QToolBar()
        self._lbl_title = QLabel("-")
        font = self._lbl_title.font()
        font.setBold(True)
        self._lbl_title.setFont(font)
        toolbar.addWidget(self._lbl_title)
        toolbar.addSeparator()

        save_btn = QAction(" Sauver", self)
        save_btn.setShortcut("Ctrl+S")
        save_btn.triggered.connect(self._on_save)
        toolbar.addAction(save_btn)

        preview_act = QAction(" Preview", self)
        preview_act.setCheckable(True)
        preview_act.setChecked(False)
        preview_act.toggled.connect(self._toggle_preview)
        toolbar.addAction(preview_act)

        screenshot_act = QAction(" Coller capture", self)
        screenshot_act.triggered.connect(self._on_paste_screenshot)
        toolbar.addAction(screenshot_act)

        export_act = QAction(" Export...", self)
        export_menu = QMenu(self)
        act_md = QAction("Markdown (.md)", self)
        act_md.triggered.connect(self._on_export_md)
        act_pdf = QAction("PDF (.pdf)", self)
        act_pdf.triggered.connect(self._on_export_pdf)
        export_menu.addAction(act_md)
        export_menu.addAction(act_pdf)
        export_act.setMenu(export_menu)
        toolbar.addAction(export_act)
        right_layout.addWidget(toolbar)

        self._editor = QPlainTextEdit()
        self._editor.setFont(QFont("Monospace"))
        self._editor.textChanged.connect(self._on_editor_changed)
        right_layout.addWidget(self._editor, 2)

        self._preview = QTextBrowser()
        self._preview.setOpenExternalLinks(True)
        self._preview.hide()
        right_layout.addWidget(self._preview, 2)

        splitter.addWidget(right)
        splitter.setSizes([200, 640])
        root.addWidget(splitter)

        # Connections
        self._nm.note_created.connect(lambda _: self._refresh_list())
        self._nm.note_deleted.connect(lambda _: self._refresh_list())
        self._nm.note_changed.connect(self._on_note_changed_external)

        # Auto-save
        self._autosave_timer = QTimer(self)
        self._autosave_timer.setInterval(30_000)
        self._autosave_timer.timeout.connect(self._auto_save)
        self._autosave_timer.start()

        # Debounce du rendu Markdown : 500ms apres la derniere frappe
        # (evite de relancer markdown.markdown() a chaque keystroke).
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(500)
        self._preview_timer.timeout.connect(self._update_preview)

        self._dirty = False
        self._current: Optional[Note] = None
        self._refresh_list()

    # ----------------------------------------------------------

    def current_note(self) -> Optional[Note]:
        return self._current

    def append_command(self, command: str, output: str = "") -> None:
        if self._current is None:
            return
        # Force save avant pour ne pas écraser
        self._on_save(silent=True)
        self._nm.append_command(self._current.name, command, output)
        # Recharge depuis disque pour capturer les changements
        fresh = self._nm.get(self._current.name)
        if fresh:
            self._current = fresh
            self._editor.blockSignals(True)
            self._editor.setPlainText(fresh.content)
            self._editor.blockSignals(False)
            self._dirty = False

    # ---------- list ----------

    def _refresh_list(self) -> None:
        current_name = self._current.name if self._current else None
        self._list.blockSignals(True)
        try:
            with frozen_updates(self._list):
                self._list.clear()
                for n in self._nm.all():
                    item = QListWidgetItem(n.name)
                    item.setData(Qt.UserRole, n.name)
                    self._list.addItem(item)
        finally:
            self._list.blockSignals(False)

        if current_name:
            # Reselect
            for i in range(self._list.count()):
                if self._list.item(i).data(Qt.UserRole) == current_name:
                    self._list.setCurrentRow(i)
                    break

    # ---------- actions ----------

    def _on_new(self) -> None:
        name, ok = QInputDialog.getText(self, "Nouvelle note", "Nom (ex: 10.10.10.10 - WEB01) :")
        if not ok or not name.strip():
            return
        try:
            ip, _, _ = name.partition(" ")
            self._nm.create(name.strip(), ip=ip if ip.count(".") == 3 else "")
            self._refresh_list()
            # auto-select
            for i in range(self._list.count()):
                if self._list.item(i).data(Qt.UserRole) == name.strip():
                    self._list.setCurrentRow(i)
                    break
        except ValueError as exc:
            error_box(self, "Erreur", str(exc))

    def _on_current_changed(self, current: Optional[QListWidgetItem], _prev) -> None:
        # sauver la note précédente
        self._on_save(silent=True)
        if current is None:
            self._current = None
            self._editor.clear()
            self._lbl_title.setText("-")
            self.note_switched.emit(None)
            return
        name = current.data(Qt.UserRole)
        note = self._nm.get(name)
        if note is None:
            return
        self._current = note
        self._editor.blockSignals(True)
        self._editor.setPlainText(note.content)
        self._editor.blockSignals(False)
        self._lbl_title.setText(note.name)
        self._dirty = False
        self._update_preview()
        self.note_switched.emit(note)
        self._nm.set_active(note.name)

    def _on_editor_changed(self) -> None:
        self._dirty = True
        # Debounce : on rearme le timer (500ms apres la derniere frappe)
        self._preview_timer.start()

    def _on_save(self, silent: bool = False) -> None:
        if not self._current:
            return
        if not self._dirty:
            return
        try:
            self._nm.save(self._current.name, self._editor.toPlainText())
            self._dirty = False
        except KeyError:
            # Note supprimée entre-temps : on se désactive silencieusement
            self._current = None
            self._editor.clear()
            self._dirty = False
        except OSError as exc:
            if not silent:
                error_box(self, "Sauvegarde", str(exc))

    def _auto_save(self) -> None:
        self._on_save(silent=True)

    def _on_note_changed_external(self, note: Note) -> None:
        if self._current and note.name == self._current.name:
            # éviter de boucler si c'est notre save
            if self._editor.toPlainText() != note.content:
                self._editor.blockSignals(True)
                self._editor.setPlainText(note.content)
                self._editor.blockSignals(False)
                self._dirty = False
                self._update_preview()

    def _toggle_preview(self, enabled: bool) -> None:
        self._preview.setVisible(enabled)
        if enabled:
            self._update_preview()

    def _update_preview(self) -> None:
        if not self._preview.isVisible():
            return
        text = self._editor.toPlainText()
        try:
            import markdown  # type: ignore
            html = markdown.markdown(text, extensions=["fenced_code", "tables"])
            self._preview.setHtml(html)
        except ImportError:
            self._preview.setPlainText(text)

    def _on_paste_screenshot(self) -> None:
        from PyQt5.QtWidgets import QApplication
        from PyQt5.QtGui import QImage
        clip = QApplication.clipboard()
        img: QImage = clip.image()
        if img.isNull():
            info_box(self, "Presse-papiers", "Pas d'image dans le presse-papiers.")
            return
        if self._current is None:
            info_box(self, "Note", "Aucune note active.")
            return
        # Convertir en PNG bytes
        from PyQt5.QtCore import QBuffer, QByteArray, QIODevice
        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(QIODevice.WriteOnly)
        img.save(buf, "PNG")
        data = bytes(ba.data())
        caption, _ = QInputDialog.getText(self, "Caption", "Légende (facultative) :")
        try:
            path = self._nm.insert_screenshot(self._current.name, data, caption=caption)
            info_box(self, "OK", f"Capture ajoutée : {path}")
            # Recharger la note
            fresh = self._nm.get(self._current.name)
            if fresh:
                self._current = fresh
                self._editor.blockSignals(True)
                self._editor.setPlainText(fresh.content)
                self._editor.blockSignals(False)
                self._dirty = False
        except Exception as exc:
            error_box(self, "Erreur", str(exc))

    def _on_export_md(self) -> None:
        if self._current is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Exporter en Markdown", f"{self._current.name}.md",
            "Markdown (*.md)",
        )
        if not path:
            return
        try:
            self._nm.export_markdown(self._current.name, path)
            info_box(self, "Export", f"Exporté -> {path}")
        except Exception as exc:
            error_box(self, "Export", str(exc))

    def _on_export_pdf(self) -> None:
        if self._current is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Exporter en PDF", f"{self._current.name}.pdf",
            "PDF (*.pdf)",
        )
        if not path:
            return
        try:
            self._nm.export_pdf(self._current.name, path)
            info_box(self, "Export", f"Exporté -> {path}")
        except Exception as exc:
            error_box(self, "Export", str(exc))

    def _on_context_menu(self, point) -> None:
        item = self._list.itemAt(point)
        if item is None:
            return
        name = item.data(Qt.UserRole)
        menu = QMenu(self)
        rename_act = QAction("Renommer...", self)
        rename_act.triggered.connect(lambda: self._on_rename(name))
        menu.addAction(rename_act)
        delete_act = QAction("Supprimer", self)
        delete_act.triggered.connect(lambda: self._on_delete(name))
        menu.addAction(delete_act)
        menu.exec_(self._list.viewport().mapToGlobal(point))

    def _on_rename(self, name: str) -> None:
        new, ok = QInputDialog.getText(self, "Renommer note", "Nouveau nom :", text=name)
        if not ok or not new.strip() or new == name:
            return
        try:
            self._nm.rename(name, new.strip())
            self._refresh_list()
        except ValueError as exc:
            error_box(self, "Erreur", str(exc))

    def _on_delete(self, name: str) -> None:
        if confirm(self, "Supprimer", f"Supprimer la note '{name}' ?"):
            self._nm.delete(name)
            self._refresh_list()
