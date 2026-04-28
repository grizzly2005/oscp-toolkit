"""Dialogs utilitaires.

Dialogues generiques reutilises par tous les panneaux :
- PlaceholderDialog : demande la valeur des {{PLACEHOLDERS}} d'un template
- ListEditDialog    : edite une liste simple (ajouter/enlever/deplacer)
- ConfirmDialog     : confirmation avec 2 boutons et details
- MultilineInput    : saisie multiline avec preview
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
    QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton, QVBoxLayout,
    QWidget,
)


# --------------------------------------------------------------
# Placeholder dialog
# --------------------------------------------------------------

class PlaceholderDialog(QDialog):
    """Demande les valeurs des placeholders d'un template.

    `placeholders` est une liste [(key, subkey_or_None), ...].
    `defaults` : dict des valeurs pre-remplies par cle.
    `suggestions` : dict { placeholder_key: [(label, value), ...] } qui
       fait apparaitre une combobox editable au lieu d'un simple QLineEdit.
       Utile pour proposer les IPs des cibles enregistrees dans le scope.

    Retourne un dict { "KEY" : "value", "KEY:sub" : "value", ... } via
    `values()`.
    """

    # Cles de placeholder qui beneficient de suggestions de "cibles"
    # (IPs et hostnames du scope). Ces cles sont les noms typiquement
    # utilises dans les templates d'outils.
    TARGET_KEYS = ("IP", "RHOST", "TARGET", "HOST", "HOSTS", "RANGE", "SUBNET", "CIDR")

    def __init__(
        self,
        template: str,
        placeholders: List[Tuple[str, Optional[str]]],
        defaults: Optional[Dict[str, str]] = None,
        parent: Optional[QWidget] = None,
        suggestions: Optional[Dict[str, List[Tuple[str, str]]]] = None,
        scope_machines: Optional[List[Tuple[str, str]]] = None,
        scope_subnets: Optional[List[Tuple[str, str]]] = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Parametres du template")
        self.setMinimumWidth(820)
        self._fields: Dict[str, QWidget] = {}    # peut etre QLineEdit OU QComboBox
        self._template = template
        defaults = defaults or {}
        suggestions = suggestions or {}
        scope_machines = scope_machines or []
        scope_subnets = scope_subnets or []

        # ============= Layout principal en 2 colonnes =============
        # Gauche  : template + form + preview
        # Droite  : panneau "Cibles" (machines + subnets du scope)
        outer = QHBoxLayout(self)

        left_widget = QWidget()
        layout = QVBoxLayout(left_widget)
        layout.setContentsMargins(0, 0, 0, 0)

        # Affichage template (read-only)
        layout.addWidget(QLabel("Template :"))
        preview = QPlainTextEdit(template)
        preview.setReadOnly(True)
        preview.setMaximumHeight(90)
        f = QFont("Monospace")
        preview.setFont(f)
        layout.addWidget(preview)

        # Form
        form = QFormLayout()
        for key, sub in placeholders:
            full_key = f"{key}:{sub}" if sub else key
            default = defaults.get(full_key) or defaults.get(key) or ""

            # Suggestions disponibles ? -> QComboBox editable
            sugg = suggestions.get(full_key) or suggestions.get(key) or []
            if sugg:
                combo = QComboBox()
                combo.setEditable(True)
                combo.lineEdit().setPlaceholderText(full_key)
                seen_values = set()
                for label, value in sugg:
                    if value in seen_values:
                        continue
                    combo.addItem(label, value)
                    seen_values.add(value)
                if default and default in seen_values:
                    for i in range(combo.count()):
                        if combo.itemData(i) == default:
                            combo.setCurrentIndex(i)
                            combo.setEditText(default)
                            break
                elif default:
                    combo.setEditText(default)
                else:
                    combo.setEditText("")

                def _on_activated(index, c=combo):
                    data = c.itemData(index)
                    if data is not None:
                        c.setEditText(data)
                combo.activated.connect(_on_activated)

                self._fields[full_key] = combo
                form.addRow(f"{{{{{full_key}}}}}", combo)
            else:
                edit = QLineEdit()
                edit.setPlaceholderText(full_key)
                edit.setText(default)
                self._fields[full_key] = edit
                form.addRow(f"{{{{{full_key}}}}}", edit)
        layout.addLayout(form)

        # Preview live
        self._live_preview = QPlainTextEdit()
        self._live_preview.setReadOnly(True)
        self._live_preview.setMaximumHeight(110)
        self._live_preview.setFont(f)
        layout.addWidget(QLabel("Resultat :"))
        layout.addWidget(self._live_preview)

        # Wire signals
        for w in self._fields.values():
            if isinstance(w, QComboBox):
                w.editTextChanged.connect(self._update_preview)
            else:
                w.textChanged.connect(self._update_preview)
        self._update_preview()

        # Buttons
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        outer.addWidget(left_widget, 3)

        # ============= Panneau "Cibles" a droite =============
        # Liste des machines + subnets du scope. Double-clic = insere
        # la valeur dans le dernier champ de placeholder qui avait le focus.
        if scope_machines or scope_subnets:
            right_widget = QWidget()
            right_widget.setMinimumWidth(240)
            right_widget.setMaximumWidth(320)
            right_layout = QVBoxLayout(right_widget)
            right_layout.setContentsMargins(0, 0, 0, 0)

            right_layout.addWidget(QLabel("<b>Cibles enregistrees</b>"))
            right_layout.addWidget(QLabel(
                "<small>Double-clic pour inserer\ndans le champ actif</small>"
            ))

            self._target_list = QListWidget()
            self._target_list.setAlternatingRowColors(True)

            if scope_machines:
                hdr = QListWidgetItem("Machines :")
                hdr.setFlags(Qt.NoItemFlags)
                font_b = hdr.font(); font_b.setBold(True); hdr.setFont(font_b)
                self._target_list.addItem(hdr)
                for label, value in scope_machines:
                    item = QListWidgetItem(label)
                    item.setData(Qt.UserRole, value)
                    item.setToolTip(f"Inserer : {value}")
                    self._target_list.addItem(item)

            if scope_subnets:
                hdr = QListWidgetItem("Subnets :")
                hdr.setFlags(Qt.NoItemFlags)
                font_b = hdr.font(); font_b.setBold(True); hdr.setFont(font_b)
                self._target_list.addItem(hdr)
                for label, value in scope_subnets:
                    item = QListWidgetItem(label)
                    item.setData(Qt.UserRole, value)
                    item.setToolTip(f"Inserer : {value}")
                    self._target_list.addItem(item)

            self._target_list.itemDoubleClicked.connect(self._on_target_picked)
            right_layout.addWidget(self._target_list, 1)

            # Track quel champ a le focus pour savoir ou inserer.
            # On utilise QApplication.focusChanged signal -- bien plus
            # robuste que de reecrire focusInEvent (qui peut casser
            # la main loop sur WSLg/xcb).
            self._last_focused_field: Optional[QWidget] = None
            # On garde une liste des widgets cibles pour lookup rapide
            self._tracked_widgets = set()
            for w in self._fields.values():
                self._tracked_widgets.add(w)
                if isinstance(w, QComboBox):
                    self._tracked_widgets.add(w.lineEdit())
            from PyQt5.QtWidgets import QApplication as _QApp
            _QApp.instance().focusChanged.connect(self._on_focus_changed)
            # Initialiser au premier champ
            if self._fields:
                self._last_focused_field = next(iter(self._fields.values()))

            outer.addWidget(right_widget, 1)
        else:
            self._target_list = None
            self._last_focused_field = None

    def _on_focus_changed(self, old: QWidget, now: QWidget) -> None:
        """Slot global de QApplication.focusChanged.

        On regarde si le nouveau focus est sur un de nos champs (ou son
        lineEdit interne pour une QComboBox). Si oui on memorise.
        """
        if now is None:
            return
        # Pour une QComboBox editable, le focus va sur son QLineEdit interne :
        # on remonte au parent QComboBox si c'est le cas.
        target = now
        for w in self._fields.values():
            if isinstance(w, QComboBox) and w.lineEdit() is now:
                target = w
                break
        if target in self._fields.values():
            self._last_focused_field = target

    def _on_target_picked(self, item: "QListWidgetItem") -> None:
        """Double-clic sur une cible -> inserer dans le dernier champ focus."""
        value = item.data(Qt.UserRole)
        if not value or self._last_focused_field is None:
            return
        w = self._last_focused_field
        if isinstance(w, QComboBox):
            w.setEditText(value)
        elif isinstance(w, QLineEdit):
            w.setText(value)

    def closeEvent(self, event) -> None:
        """Disconnect le focusChanged pour eviter une ref dangling apres
        la fermeture du dialog (sinon QApplication garde un slot vers
        un objet detruit -> crash au prochain changement de focus)."""
        if getattr(self, '_target_list', None) is not None:
            try:
                from PyQt5.QtWidgets import QApplication as _QApp
                _QApp.instance().focusChanged.disconnect(self._on_focus_changed)
            except (TypeError, RuntimeError):
                pass
        super().closeEvent(event)

    def done(self, code) -> None:
        """Idem pour les fermetures via accept()/reject() qui ne passent
        pas forcement par closeEvent."""
        if getattr(self, '_target_list', None) is not None:
            try:
                from PyQt5.QtWidgets import QApplication as _QApp
                _QApp.instance().focusChanged.disconnect(self._on_focus_changed)
            except (TypeError, RuntimeError):
                pass
        super().done(code)

    @staticmethod
    def _value_of(widget: QWidget) -> str:
        if isinstance(widget, QComboBox):
            return widget.currentText()
        return widget.text() if isinstance(widget, QLineEdit) else ""

    def _update_preview(self) -> None:
        result = self._template
        for full_key, widget in self._fields.items():
            value = self._value_of(widget)
            placeholder_exact = "{{" + full_key + "}}"
            result = result.replace(placeholder_exact, value)
        self._live_preview.setPlainText(result)

    def values(self) -> Dict[str, str]:
        return {k: self._value_of(w) for k, w in self._fields.items()}

    def resolved_command(self) -> str:
        return self._live_preview.toPlainText()


# --------------------------------------------------------------
# List edit dialog
# --------------------------------------------------------------

class ListEditDialog(QDialog):
    """Édite une liste de strings avec add/remove/up/down."""

    def __init__(
        self,
        title: str,
        items: List[str],
        add_prompt: str = "Nouvel élément",
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumSize(460, 320)

        self._list = QListWidget()
        self._list.setSelectionMode(QAbstractItemView.SingleSelection)
        for it in items:
            self._list.addItem(QListWidgetItem(it))
        self._add_prompt = add_prompt

        btn_add = QPushButton("Ajouter")
        btn_rm = QPushButton("Supprimer")
        btn_up = QPushButton("^")
        btn_down = QPushButton("v")
        btn_add.clicked.connect(self._on_add)
        btn_rm.clicked.connect(self._on_remove)
        btn_up.clicked.connect(lambda: self._move(-1))
        btn_down.clicked.connect(lambda: self._move(1))

        btns_row = QVBoxLayout()
        btns_row.addWidget(btn_add)
        btns_row.addWidget(btn_rm)
        btns_row.addWidget(btn_up)
        btns_row.addWidget(btn_down)
        btns_row.addStretch()

        row = QHBoxLayout()
        row.addWidget(self._list, 1)
        row.addLayout(btns_row)

        layout = QVBoxLayout(self)
        layout.addLayout(row)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_add(self) -> None:
        text, ok = QInputDialog.getText(self, self.windowTitle(), self._add_prompt)
        if ok and text.strip():
            self._list.addItem(QListWidgetItem(text.strip()))

    def _on_remove(self) -> None:
        row = self._list.currentRow()
        if row >= 0:
            self._list.takeItem(row)

    def _move(self, delta: int) -> None:
        row = self._list.currentRow()
        new_row = row + delta
        if row < 0 or new_row < 0 or new_row >= self._list.count():
            return
        item = self._list.takeItem(row)
        self._list.insertItem(new_row, item)
        self._list.setCurrentRow(new_row)

    def items(self) -> List[str]:
        return [self._list.item(i).text() for i in range(self._list.count())]


# --------------------------------------------------------------
# Confirm avec détails
# --------------------------------------------------------------

def confirm(
    parent: Optional[QWidget],
    title: str,
    question: str,
    details: str = "",
) -> bool:
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setText(question)
    if details:
        box.setDetailedText(details)
    box.setIcon(QMessageBox.Question)
    box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
    box.setDefaultButton(QMessageBox.No)
    return box.exec_() == QMessageBox.Yes


def error_box(parent: Optional[QWidget], title: str, message: str, details: str = "") -> None:
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setText(message)
    box.setIcon(QMessageBox.Critical)
    if details:
        box.setDetailedText(details)
    box.exec_()


def info_box(parent: Optional[QWidget], title: str, message: str, details: str = "") -> None:
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setText(message)
    box.setIcon(QMessageBox.Information)
    if details:
        box.setDetailedText(details)
    box.exec_()


# --------------------------------------------------------------
# Multiline input
# --------------------------------------------------------------

class MultilineInput(QDialog):
    def __init__(self, title: str, prompt: str = "", initial: str = "", parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumSize(520, 320)
        layout = QVBoxLayout(self)
        if prompt:
            layout.addWidget(QLabel(prompt))
        self._edit = QPlainTextEdit()
        self._edit.setPlainText(initial)
        f = QFont("Monospace")
        self._edit.setFont(f)
        layout.addWidget(self._edit)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def text(self) -> str:
        return self._edit.toPlainText()