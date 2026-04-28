"""Central Stack — tabs OU grille 2x2 de terminaux.

Remplace le QTabWidget central par un QStackedWidget qui switch entre :
  - page 0 : mode "tabs" (QTabWidget classique)
  - page 1 : mode "quad"  (grille 2x2 avec QSplitter imbrique)

En mode quad, les 4 slots ont chacun un header avec :
  - dropdown pour choisir quel terminal afficher (parmi les tabs existants)
  - bouton "+" pour creer un nouveau terminal dans ce slot
  - bouton "X" pour libere le slot

Un terminal peut etre affiche dans plusieurs slots simultanement car
on partage le meme TerminalWorker — mais visuellement un seul widget
doit etre rattache a un parent a la fois. Donc on reparent dynamiquement.

API publique :
  - add_terminal(tab) : enregistre un nouveau terminal
  - remove_terminal(tab) : le retire proprement
  - set_mode("tabs" | "quad") : switch de mode
  - active_terminal() : retourne le TerminalTab actif (tab en focus,
    ou slot en focus en mode quad)
"""
from __future__ import annotations

from typing import Dict, List, Optional

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QPushButton, QSplitter,
    QStackedWidget, QTabBar, QTabWidget, QVBoxLayout, QWidget,
)


class _QuadSlot(QWidget):
    """Un des 4 slots du mode quad. Contient un header + un terminal."""

    request_new = pyqtSignal(object)     # self
    request_clear = pyqtSignal(object)   # self
    terminal_changed = pyqtSignal(object, object)  # self, new_tab_or_None

    def __init__(self, slot_id: int, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._slot_id = slot_id
        self._current_tab = None  # TerminalTab or None

        root = QVBoxLayout(self)
        root.setContentsMargins(2, 2, 2, 2)
        root.setSpacing(2)

        # Header
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(4)

        label = QLabel(f"Slot {slot_id + 1}")
        label.setStyleSheet("color:#9e9e9e; font-weight:bold; padding-right:6px;")
        header.addWidget(label)

        self._selector = QComboBox()
        self._selector.setMinimumWidth(140)
        self._selector.currentIndexChanged.connect(self._on_selector_changed)
        header.addWidget(self._selector, 1)

        btn_new = QPushButton("+")
        btn_new.setFixedSize(22, 22)
        btn_new.setToolTip("Nouveau terminal dans ce slot")
        btn_new.clicked.connect(lambda: self.request_new.emit(self))
        header.addWidget(btn_new)

        btn_clear = QPushButton("x")
        btn_clear.setFixedSize(22, 22)
        btn_clear.setToolTip("Vider ce slot")
        btn_clear.clicked.connect(lambda: self.request_clear.emit(self))
        header.addWidget(btn_clear)

        root.addLayout(header)

        # Zone terminal
        self._host = QWidget()
        self._host_layout = QVBoxLayout(self._host)
        self._host_layout.setContentsMargins(0, 0, 0, 0)
        self._host_layout.setSpacing(0)
        root.addWidget(self._host, 1)

        # Placeholder
        self._placeholder = QLabel(
            f"<center><span style='color:#555;font-size:14pt;'>"
            f"Slot {slot_id + 1} vide<br>"
            f"<span style='font-size:9pt;'>Choisis un terminal ou clique +</span>"
            f"</span></center>"
        )
        self._placeholder.setAlignment(Qt.AlignCenter)
        self._host_layout.addWidget(self._placeholder)

    # -- Selector ------------------------------------------------------------

    def refresh_selector(self, tabs: List["TerminalTab"]) -> None:  # noqa: F821
        """Met a jour la dropdown avec la liste actuelle des terminaux."""
        self._selector.blockSignals(True)
        self._selector.clear()
        self._selector.addItem("(vide)", None)
        current_idx = 0
        for i, tab in enumerate(tabs, start=1):
            self._selector.addItem(tab.title(), tab)
            if tab is self._current_tab:
                current_idx = i
        self._selector.setCurrentIndex(current_idx)
        self._selector.blockSignals(False)

    def _on_selector_changed(self, idx: int) -> None:
        tab = self._selector.itemData(idx)
        self._mount_tab(tab)
        self.terminal_changed.emit(self, tab)

    # -- Mount / Unmount -----------------------------------------------------

    def _mount_tab(self, tab) -> None:
        """Attache ce TerminalTab au slot (en le detachant de son parent actuel)."""
        # Retire l'ancien
        if self._current_tab is not None:
            self._host_layout.removeWidget(self._current_tab)
            self._current_tab.setParent(None)   # detach propre
        else:
            # Retire le placeholder si present
            self._host_layout.removeWidget(self._placeholder)
            self._placeholder.setParent(None)

        self._current_tab = tab

        if tab is None:
            # Replace placeholder
            self._host_layout.addWidget(self._placeholder)
            self._placeholder.show()
        else:
            tab.setParent(self._host)
            self._host_layout.addWidget(tab)
            tab.show()

    def current_tab(self):
        return self._current_tab

    def clear(self) -> None:
        self._mount_tab(None)
        self._selector.blockSignals(True)
        self._selector.setCurrentIndex(0)
        self._selector.blockSignals(False)


class CentralStack(QStackedWidget):
    """Stack entre mode tabs et mode quad (grille 2x2)."""

    # Signaux propages
    tab_close_requested = pyqtSignal(int)      # idx
    tab_rename_requested = pyqtSignal(int)     # idx via double-clic
    new_terminal_requested = pyqtSignal()      # pour creer un nouveau term
    new_terminal_in_slot_requested = pyqtSignal(int)  # slot id -> le parent decide

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)

        # Page 0 : tabs
        self._tabs = QTabWidget()
        self._tabs.setTabsClosable(True)
        self._tabs.setMovable(True)
        self._tabs.setDocumentMode(True)
        self._tabs.tabCloseRequested.connect(self.tab_close_requested.emit)
        self._tabs.tabBarDoubleClicked.connect(self.tab_rename_requested.emit)

        btn_new = QPushButton("+")
        btn_new.setFixedSize(24, 24)
        btn_new.setToolTip("Nouveau terminal (Ctrl+T)")
        btn_new.clicked.connect(self.new_terminal_requested.emit)
        self._tabs.setCornerWidget(btn_new, Qt.TopRightCorner)

        self.addWidget(self._tabs)

        # Page 1 : quad
        self._quad_root = QWidget()
        quad_layout = QVBoxLayout(self._quad_root)
        quad_layout.setContentsMargins(0, 0, 0, 0)

        # Un splitter vertical contenant 2 splitters horizontaux
        v = QSplitter(Qt.Vertical, self._quad_root)
        top = QSplitter(Qt.Horizontal, v)
        bot = QSplitter(Qt.Horizontal, v)
        v.addWidget(top)
        v.addWidget(bot)

        self._slots: List[_QuadSlot] = []
        for i in range(4):
            slot = _QuadSlot(i)
            slot.request_new.connect(self._on_slot_new)
            slot.request_clear.connect(self._on_slot_clear)
            slot.terminal_changed.connect(self._on_slot_terminal_changed)
            self._slots.append(slot)

        top.addWidget(self._slots[0])
        top.addWidget(self._slots[1])
        bot.addWidget(self._slots[2])
        bot.addWidget(self._slots[3])

        top.setSizes([1, 1])
        bot.setSizes([1, 1])
        v.setSizes([1, 1])

        quad_layout.addWidget(v)
        self.addWidget(self._quad_root)

        self._current_mode = "tabs"
        self._active_slot: Optional[_QuadSlot] = None
        # Registre des terminaux enregistres
        self._terminals: List = []
        # Track placeholder
        self._placeholder_widget: Optional[QWidget] = None

    # -- Mode ----------------------------------------------------------------

    def current_mode(self) -> str:
        return self._current_mode

    def set_mode(self, mode: str) -> None:
        if mode not in ("tabs", "quad"):
            raise ValueError(mode)
        if mode == self._current_mode:
            return

        if mode == "quad":
            # On re-mount rien : les slots sont vides par defaut, l'utilisateur
            # choisit ses terminaux dans les dropdowns.
            self._refresh_all_selectors()
            self.setCurrentIndex(1)
        else:
            # Remount tous les terminaux dans l'ordre des tabs
            # D'abord detach les slots
            for slot in self._slots:
                if slot.current_tab() is not None:
                    slot._mount_tab(None)
            # Puis re-ajoute en tabs
            # (les terminaux sont deja dans _terminals, mais il faut les re-attacher
            # au QTabWidget)
            for tab in self._terminals:
                if tab.parent() is not self._tabs:
                    idx = self._find_tab_index(tab)
                    if idx < 0:
                        self._tabs.addTab(tab, tab.title())
            self.setCurrentIndex(0)

        self._current_mode = mode

    # -- Terminal registry ---------------------------------------------------

    def add_terminal(self, tab, title: str) -> int:
        """Enregistre un terminal. Retourne l'index dans le tab widget."""
        self._terminals.append(tab)
        idx = self._tabs.addTab(tab, title)
        self._refresh_all_selectors()
        return idx

    def remove_terminal(self, tab) -> None:
        if tab in self._terminals:
            self._terminals.remove(tab)
        # Detach de tous les slots
        for slot in self._slots:
            if slot.current_tab() is tab:
                slot.clear()
        # Retire du tab widget
        idx = self._find_tab_index(tab)
        if idx >= 0:
            self._tabs.removeTab(idx)
        self._refresh_all_selectors()

    def tab_widget(self) -> QTabWidget:
        """Accesseur pour le QTabWidget sous-jacent (pour API existante)."""
        return self._tabs

    def all_terminals(self) -> List:
        return list(self._terminals)

    def active_terminal(self):
        if self._current_mode == "quad":
            if self._active_slot and self._active_slot.current_tab():
                return self._active_slot.current_tab()
            # Fallback : premier slot non vide
            for slot in self._slots:
                if slot.current_tab():
                    return slot.current_tab()
            return None
        # Mode tabs
        w = self._tabs.currentWidget()
        return w if w in self._terminals else None

    def set_active_terminal(self, tab) -> None:
        if tab not in self._terminals:
            return
        if self._current_mode == "tabs":
            idx = self._find_tab_index(tab)
            if idx >= 0:
                self._tabs.setCurrentIndex(idx)
        # En quad, on ne force pas — l'utilisateur pilote les slots

    def set_placeholder(self, widget: QWidget) -> None:
        """Affiche le widget d'accueil dans la page tabs quand il n'y a
        aucun terminal. Appele une fois par l'init."""
        self._placeholder_widget = widget
        self._tabs.addTab(widget, "  Accueil  ")
        self._tabs.tabBar().setTabButton(0, QTabBar.RightSide, None)

    # -- Internal ------------------------------------------------------------

    def _find_tab_index(self, tab) -> int:
        for i in range(self._tabs.count()):
            if self._tabs.widget(i) is tab:
                return i
        return -1

    def _refresh_all_selectors(self) -> None:
        for slot in self._slots:
            slot.refresh_selector(self._terminals)

    def _on_slot_new(self, slot: _QuadSlot) -> None:
        self._active_slot = slot
        self.new_terminal_in_slot_requested.emit(slot._slot_id)

    def _on_slot_clear(self, slot: _QuadSlot) -> None:
        slot.clear()
        self._refresh_all_selectors()

    def _on_slot_terminal_changed(self, slot: _QuadSlot, tab) -> None:
        if tab is not None:
            self._active_slot = slot
        # Rafraichit les AUTRES selectors (pour afficher l'etat)
        self._refresh_all_selectors()

    def mount_terminal_in_slot(self, slot_idx: int, tab) -> None:
        """Helper : monte un tab dans un slot specifique (apres creation)."""
        if 0 <= slot_idx < len(self._slots):
            self._slots[slot_idx]._mount_tab(tab)
            self._slots[slot_idx].refresh_selector(self._terminals)
