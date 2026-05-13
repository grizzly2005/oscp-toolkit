"""Main Window — orchestrateur central.

Responsabilités :
- Créer et posséder les *managers* métier (tool, notes, scope, vault,
  clipboard, history, terminals, network, services).
- Construire la UI : dock left (tools + scope), center (terminaux),
  dock right (notes + docs tabbed + credentials + clipboard),
  status bar.
- Câbler tous les signaux/slots inter-composants.
- Gérer raccourcis clavier globaux.
- Serialize/restore session.

Règles architecturales :
- JAMAIS de logique métier ici : seulement du wiring.
- Tous les managers sont QObject, injectés dans les panels.
- Un slot qui fait plus de 3-5 lignes doit être extrait dans un manager.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PyQt5.QtCore import Qt, QTimer, QByteArray
from PyQt5.QtGui import QKeySequence, QColor
from PyQt5.QtWidgets import (
    QAction, QApplication, QDockWidget, QFileDialog,
    QInputDialog, QMainWindow, QMenu, QMessageBox, QShortcut, QStatusBar,
    QTabWidget, QToolBar, QWidget, QVBoxLayout, QLabel, QTabBar,
    QPushButton,
)

from core.config_manager import ConfigManager
from core.process_tracker import ProcessTracker
from core.session import SessionManager, SessionState, TerminalSession, NoteSession
from core.preflight import PreflightReport
from core.logger import get_logger

from core.tool_manager import ToolManager, Tool
from core.notes import NotesManager, Note
from core.scope_manager import ScopeManager
from core.credential_vault import CredentialVault
from core.clipboard_manager import ClipboardManager
from core.command_history import CommandHistory
from core.network_info import NetworkInfo
from core.terminal import TerminalManager, TerminalWorker
from core.listener_manager import ListenerManager
from core.file_server import FileServerManager
from core.tunnel_manager import TunnelManager
from core.docker_bridge import DockerBridge
from core.revshell_generator import RevshellGenerator
from core.wordlist_manager import WordlistManager
from core.autogrep import run_all  # returns Dict[str, List[Finding]]
from core.proof_tracker import ProofTracker
from core.env_manager import EnvManager
from core.external_terminal import ExternalTerminal

from ui.tool_panel import ToolPanel
from ui.notes_panel import NotesPanel
from ui.doc_panel import DocPanel
from ui.scope_panel import ScopePanel
from ui.status_bar import StatusBar
from ui.terminal_tab import TerminalTab
from ui.credential_panel import CredentialPanel
from ui.clipboard_panel import ClipboardPanel
from ui.history_panel import HistoryPanel
from ui.wordlist_panel import WordlistPanel
from ui.target_board import TargetBoard
from ui.revshell_dialog import RevshellDialog
from ui.encoder_dialog import EncoderDialog
from ui.hash_dialog import HashDialog
from ui.transfer_dialog import TransferDialog
from ui.dialogs import PlaceholderDialog, confirm, info_box, error_box
from ui.env_dialog import EnvDialog
from ui.exam_timer import ExamTimer
from ui.find_bar import FindBar
from ui.central_stack import CentralStack
from ui.file_server_panel import FileServerPanel
from ui.command_palette import CommandPalette, PaletteAction
from core.tool_setup_registry import ToolSetupRegistry
from core.screenshot import capture_active_window

log = get_logger(__name__)


def _open_url_silent(url: str) -> None:
    """Ouvre une URL ou un fichier dans le programme par defaut, en
    silencieux : stdout/stderr du process enfant rediriges vers DEVNULL.

    Pourquoi : sur Kali Linux avec chromium-snap, QDesktopServices.openUrl
    herite la stderr du toolkit. Le launcher snap deverse une dizaine de
    warnings (mount namespace, libpxbackend, dbus, ibus...) qui polluent
    notre log et le terminal d'ou main.py a ete lance.

    Strategie :
      1. xdg-open  -> standard linux desktop
      2. open      -> macOS
      3. fallback Qt QDesktopServices (qui pollue mais marche partout)
    """
    import subprocess
    import shutil as _sh
    for opener in ("xdg-open", "open"):
        path = _sh.which(opener)
        if path:
            try:
                subprocess.Popen(
                    [path, url],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                    close_fds=True,
                )
                return
            except OSError:
                continue
    # Fallback Qt — pollue mais au moins l'URL s'ouvre
    try:
        from PyQt5.QtCore import QUrl
        from PyQt5.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl(url))
    except Exception:
        log.warning("Cannot open URL: %s", url)


# Couleurs par catégorie de terminal (décoration)
_CATEGORY_COLOR = {
    "enum":     "#64b5f6",
    "exploit":  "#ef5350",
    "privesc":  "#81c784",
    "ad":       "#ba68c8",
    "default":  "#9e9e9e",
}


class MainWindow(QMainWindow):
    """Fenêtre principale. Unique source de vérité pour la navigation."""

    def __init__(
        self,
        config: ConfigManager,
        tracker: ProcessTracker,
        session: SessionManager,
        preflight_report: PreflightReport,
    ):
        super().__init__()
        self._cfg = config
        self._pt = tracker
        self._session = session
        self._preflight = preflight_report

        self.setWindowTitle("OSCP Toolkit")
        self.setObjectName("OSCPToolkitMain")
        self.setDockOptions(
            QMainWindow.AnimatedDocks
            | QMainWindow.AllowNestedDocks
            | QMainWindow.AllowTabbedDocks
        )

        # --- Managers métier (ordre = graphe de dépendance) ---
        self._tools      = ToolManager(config, self)
        self._notes      = NotesManager(parent=self)
        self._scope      = ScopeManager(config, self)
        self._vault      = CredentialVault(config, self)
        self._clipboard  = ClipboardManager(config, parent=self)
        self._history    = CommandHistory(parent=self)
        self._network    = NetworkInfo(parent=self)
        self._terminals  = TerminalManager(tracker, self)
        self._listeners  = ListenerManager(tracker, self)
        self._fileservs  = FileServerManager(tracker, self)
        self._tunnels    = TunnelManager(tracker, scope_manager=self._scope, parent=self)
        self._docker     = DockerBridge(parent=self)
        self._revshells  = RevshellGenerator(config)
        self._wordlists  = WordlistManager(config, parent=self)
        self._proof      = ProofTracker(self._scope, self)
        self._env        = EnvManager(config, self)
        self._ext_term   = ExternalTerminal(self._env, self)
        self._tool_setup = ToolSetupRegistry(tracker, self)

        # Charger les overrides de commande persistes (config/services_overrides.json).
        # Permet a l'utilisateur de modifier la commande de Ligolo & co via
        # le menu contextuel sur le bouton, et que ca survive au reboot.
        self._apply_service_overrides()

        # --- UI ---
        self._build_central()
        self._build_docks()
        self._build_toolbar()
        self._build_menu()
        self._build_status_bar()

        # --- Wiring global ---
        self._wire_signals()

        # --- Shortcuts globaux ---
        self._install_shortcuts()

        # --- Géométrie initiale ---
        self._apply_layout_from_config()

        # --- Lancer les timers ---
        self._network.start()

        # --- Vérification intégrité des outils (async) ---
        QTimer.singleShot(500, self._tools.check_integrity_async)

        # --- Auto-save session 30s (resilience aux crashes) ---
        # Si Qt crashe ou si on kill le process, la session sauvee a t-30s
        # sera restoree au prochain boot.
        self._session_autosave_timer = QTimer(self)
        self._session_autosave_timer.setInterval(30_000)
        self._session_autosave_timer.timeout.connect(self._auto_save_session)
        self._session_autosave_timer.start()

        log.info("MainWindow ready")

    def _auto_save_session(self) -> None:
        """Auto-save discrete : echec silencieux mais loggue."""
        try:
            state = self.serialize_state()
            self._session.save(state)
        except Exception:
            log.exception("Auto-save session failed")

    # ==============================================================
    # UI construction
    # ==============================================================

    def _build_central(self) -> None:
        """Zone centrale : CentralStack (tabs ou grille 2x2)."""
        self._central = CentralStack(self)
        self._tabs = self._central.tab_widget()   # alias retro-compat
        self._central.tab_close_requested.connect(self._on_tab_close_requested)
        self._central.tab_rename_requested.connect(self._on_tab_rename)
        self._central.new_terminal_requested.connect(lambda: self.spawn_terminal())
        self._central.new_terminal_in_slot_requested.connect(
            self._on_new_terminal_in_slot
        )

        # Placeholder accueil
        self._central.set_placeholder(self._make_welcome_widget())

        self.setCentralWidget(self._central)

    def _make_welcome_widget(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setAlignment(Qt.AlignCenter)
        title = QLabel("OSCP Toolkit")
        f = title.font(); f.setPointSize(24); f.setBold(True); title.setFont(f)
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)
        subtitle = QLabel(
            "<p style='color:#9e9e9e;'>Ctrl+T nouveau terminal &nbsp;·&nbsp; "
            "Ctrl+N nouvelle note &nbsp;·&nbsp; Ctrl+R reverse shell "
            "&nbsp;·&nbsp; Ctrl+E encoder &nbsp;·&nbsp; F1 docs</p>"
            "<p style='color:#ffb74d;'>[!] Metasploit : 1 usage autorisé sur l'examen OSCP</p>"
        )
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setTextFormat(Qt.RichText)
        layout.addWidget(subtitle)
        return w

    def _build_docks(self) -> None:
        """Crée tous les dock widgets.

        Visibilite par defaut : Outils, Scope, Notes, Credentials.
        Le reste (Docs, Clipboard, Historique, Targets, Wordlists, FileServer)
        est masque et accessible via le menu Affichage ou la palette.
        """
        # --- Dock gauche : outils (haut) + scope (bas) ---
        self._tool_panel = ToolPanel(self._tools)
        self._dock_tools = self._make_dock("Outils", self._tool_panel, "tools")
        self.addDockWidget(Qt.LeftDockWidgetArea, self._dock_tools)

        self._scope_panel = ScopePanel(self._scope)
        self._dock_scope = self._make_dock("Scope", self._scope_panel, "scope")
        self.addDockWidget(Qt.LeftDockWidgetArea, self._dock_scope)
        self.splitDockWidget(self._dock_tools, self._dock_scope, Qt.Vertical)

        # --- Dock droit : Notes (haut), Credentials (sous) + Docs/Clipboard tabbed ---
        self._notes_panel = NotesPanel(self._notes)
        self._dock_notes = self._make_dock("Notes", self._notes_panel, "notes")
        self.addDockWidget(Qt.RightDockWidgetArea, self._dock_notes)

        self._cred_panel = CredentialPanel(self._vault)
        self._dock_creds = self._make_dock("Credentials", self._cred_panel, "creds")
        self.addDockWidget(Qt.RightDockWidgetArea, self._dock_creds)
        self.splitDockWidget(self._dock_notes, self._dock_creds, Qt.Vertical)

        # Docs et Clipboard : tabifies avec Credentials, MASQUES par defaut
        self._doc_panel = DocPanel("cheatsheets")
        self._dock_docs = self._make_dock("Docs", self._doc_panel, "docs")
        self.addDockWidget(Qt.RightDockWidgetArea, self._dock_docs)
        self.tabifyDockWidget(self._dock_creds, self._dock_docs)

        self._clip_panel = ClipboardPanel(self._clipboard)
        self._dock_clip = self._make_dock("Clipboard", self._clip_panel, "clipboard")
        self.addDockWidget(Qt.RightDockWidgetArea, self._dock_clip)
        self.tabifyDockWidget(self._dock_creds, self._dock_clip)

        # --- Dock bas : history + target board + wordlists + file server (tabbed) ---
        self._history_panel = HistoryPanel(self._history)
        self._dock_history = self._make_dock("Historique", self._history_panel, "history")
        self.addDockWidget(Qt.BottomDockWidgetArea, self._dock_history)

        self._target_board = TargetBoard(self._scope)
        self._dock_targets = self._make_dock("Targets", self._target_board, "targets")
        self.addDockWidget(Qt.BottomDockWidgetArea, self._dock_targets)
        self.tabifyDockWidget(self._dock_history, self._dock_targets)

        self._wordlist_panel = WordlistPanel(self._wordlists)
        self._dock_wordlists = self._make_dock(
            "Wordlists", self._wordlist_panel, "wordlists"
        )
        self.addDockWidget(Qt.BottomDockWidgetArea, self._dock_wordlists)
        self.tabifyDockWidget(self._dock_targets, self._dock_wordlists)

        # File server panel (FIX : etait du code mort apres un return)
        self._file_server_panel = FileServerPanel(
            file_servers=self._fileservs,
            attacker_ip_getter=lambda: self._network.attacker_ip(),
            parent=self,
        )
        self._dock_fs = self._make_dock(
            "File Server", self._file_server_panel, "file_server"
        )
        self.addDockWidget(Qt.BottomDockWidgetArea, self._dock_fs)
        self.tabifyDockWidget(self._dock_wordlists, self._dock_fs)

        # --- Visibilite par defaut : Notes, Scope, Outils, Credentials ---
        self._dock_docs.hide()
        self._dock_clip.hide()
        self._dock_history.hide()
        self._dock_targets.hide()
        self._dock_wordlists.hide()
        self._dock_fs.hide()
        self._dock_creds.raise_()

        # --- Persistance auto du layout sur deplacement/redimension d'un dock ---
        # On debounce 1s : pendant un drag, les signaux feu plusieurs fois/sec.
        self._layout_save_timer = QTimer(self)
        self._layout_save_timer.setSingleShot(True)
        self._layout_save_timer.setInterval(1000)
        self._layout_save_timer.timeout.connect(self._persist_layout)
        # Signaux par dock : float/unfloat, change de zone, masquage/affichage
        for dock in [
            self._dock_tools, self._dock_scope, self._dock_notes,
            self._dock_creds, self._dock_docs, self._dock_clip,
            self._dock_history, self._dock_targets, self._dock_wordlists,
            self._dock_fs,
        ]:
            dock.topLevelChanged.connect(
                lambda *_: self._layout_save_timer.start()
            )
            dock.visibilityChanged.connect(
                lambda *_: self._layout_save_timer.start()
            )
            dock.dockLocationChanged.connect(
                lambda *_: self._layout_save_timer.start()
            )

    def _make_dock(self, title: str, widget: QWidget, object_name: str) -> QDockWidget:
        dock = QDockWidget(title, self)
        dock.setObjectName(f"dock_{object_name}")
        dock.setAllowedAreas(Qt.AllDockWidgetAreas)
        dock.setFeatures(
            QDockWidget.DockWidgetMovable
            | QDockWidget.DockWidgetFloatable
            | QDockWidget.DockWidgetClosable
        )
        dock.setWidget(widget)
        return dock

    def _build_toolbar(self) -> None:
        from PyQt5.QtWidgets import QToolButton

        tb = QToolBar("Actions rapides")
        tb.setObjectName("main_toolbar")
        tb.setMovable(False)
        # Texte seul : pas de placeholder d'icone (-> plus de petit rectangle).
        tb.setToolButtonStyle(Qt.ToolButtonTextOnly)

        # Helper : ajoute une QAction et renvoie son QToolButton pour
        # pouvoir lui mettre un objectName (cible CSS).
        def add_action(action: QAction, role: str = "") -> "QToolButton":
            tb.addAction(action)
            btn = tb.widgetForAction(action)
            if btn is not None and role:
                btn.setObjectName(f"toolbar_{role}")
            return btn

        # ----- PRIMAIRES (bleu) : actions de creation principales -----
        act_term = QAction("Terminal", self)
        act_term.setShortcut(QKeySequence("Ctrl+T"))
        act_term.triggered.connect(lambda: self.spawn_terminal())
        add_action(act_term, "primary")

        act_note = QAction("Nouvelle note", self)
        act_note.setShortcut(QKeySequence("Ctrl+N"))
        act_note.triggered.connect(self._on_new_note)
        add_action(act_note, "primary")

        tb.addSeparator()

        act_rev = QAction("RevShell", self)
        act_rev.setShortcut(QKeySequence("Ctrl+R"))
        act_rev.setToolTip("Ouvre revshells.com dans le navigateur")
        act_rev.triggered.connect(self._open_revshells_web)
        add_action(act_rev, "primary")

        # ----- UTILITAIRES (gris) : Env / Ext.Terminal -----
        act_env = QAction("Env", self)
        act_env.setShortcut(QKeySequence("Ctrl+Shift+E"))
        act_env.setToolTip("Variables d'environnement session (LHOST, TARGET...)")
        act_env.triggered.connect(self._open_env_dialog)
        add_action(act_env, "util")

        act_ext_term = QAction("Ext. Terminal", self)
        act_ext_term.setShortcut(QKeySequence("Ctrl+Shift+T"))
        act_ext_term.setToolTip("Terminal externe avec env OSCP (wt.exe / xterm)")
        act_ext_term.triggered.connect(self._spawn_external_terminal)
        add_action(act_ext_term, "util")

        tb.addSeparator()

        # ----- SERVICES (orange) : Listener / HTTP / Ligolo -----
        # Ces 3 boutons demarrent un process en arriere-plan.
        # Ligolo est en mode "toggle" : clic 1 = start, clic 2 = stop.
        # Clic droit sur Ligolo = configurer la commande.
        self._btn_listener = QToolButton(self)
        self._btn_listener.setObjectName("service_listener")
        self._btn_listener.setText("Listener (F2)")
        self._btn_listener.setToolTip("Lance nc -lvnp sur LPORT dans un terminal integre")
        self._btn_listener.clicked.connect(self._quick_listener)
        tb.addWidget(self._btn_listener)

        self._btn_http = QToolButton(self)
        self._btn_http.setObjectName("service_http")
        self._btn_http.setText("HTTP (F3)")
        self._btn_http.setToolTip("Demarre le serveur HTTP du panel File Server")
        self._btn_http.clicked.connect(self._quick_http_server)
        tb.addWidget(self._btn_http)

        # Ligolo en checkable : visualise l'etat ON/OFF
        self._btn_ligolo = QToolButton(self)
        self._btn_ligolo.setObjectName("service_ligolo")
        self._btn_ligolo.setText("Ligolo (F4)")
        self._btn_ligolo.setCheckable(True)
        self._btn_ligolo.setToolTip(
            "Clic = toggle Ligolo-ng proxy ON/OFF\nClic droit = configurer la commande"
        )
        # On utilise clicked (pas toggled) car on veut intercepter et decider :
        # Qt aura deja switche le checked-state, on le restaure si echec.
        self._btn_ligolo.clicked.connect(self._on_ligolo_clicked)
        self._btn_ligolo.setContextMenuPolicy(Qt.CustomContextMenu)
        self._btn_ligolo.customContextMenuRequested.connect(self._on_ligolo_context_menu)
        tb.addWidget(self._btn_ligolo)
        # Sync initiale + signal : si Ligolo demarre/s'arrete par un autre
        # chemin, le bouton suit.
        self._sync_ligolo_button()
        self._tool_setup.started.connect(self._on_tool_setup_changed)
        self._tool_setup.stopped.connect(self._on_tool_setup_changed)

        tb.addSeparator()

        # ----- UTILITAIRES (gris) : suite -----
        act_proof = QAction("Proof (F9)", self)
        act_proof.setShortcut(QKeySequence("F9"))
        act_proof.setToolTip("Screenshot de la fenetre active comme proof")
        act_proof.triggered.connect(self._quick_screenshot_proof)
        add_action(act_proof, "util")

        act_split = QAction("Split 2x2 (F6)", self)
        act_split.setShortcut(QKeySequence("F6"))
        act_split.setCheckable(True)
        act_split.setToolTip("Bascule entre onglets et grille 2x2")
        act_split.toggled.connect(self._toggle_split_mode)
        add_action(act_split, "util")
        self._act_split = act_split

        act_palette = QAction("Palette (Ctrl+P)", self)
        act_palette.setShortcut(QKeySequence("Ctrl+P"))
        act_palette.setToolTip("Palette de commandes globale")
        act_palette.triggered.connect(self._open_command_palette)
        add_action(act_palette, "util")

        act_enc = QAction("Encoder", self)
        act_enc.setShortcut(QKeySequence("Ctrl+E"))
        act_enc.triggered.connect(self._open_encoder_dialog)
        add_action(act_enc, "util")

        act_hash = QAction("Hash ID", self)
        act_hash.triggered.connect(self._open_hash_dialog)
        add_action(act_hash, "util")

        act_transfer = QAction("Transfer", self)
        act_transfer.triggered.connect(self._open_transfer_dialog)
        add_action(act_transfer, "util")

        tb.addSeparator()

        act_search = QAction("Recherche", self)
        act_search.setShortcut(QKeySequence("Ctrl+F"))
        act_search.triggered.connect(self._on_global_search)
        add_action(act_search, "util")

        self.addToolBar(tb)

    def _build_menu(self) -> None:
        mb = self.menuBar()

        m_file = mb.addMenu("&Fichier")

        # ----- Session -----
        act_new_session = QAction("Nouvelle session vierge", self)
        act_new_session.setShortcut(QKeySequence("Ctrl+Shift+N"))
        act_new_session.setToolTip("Ferme les terminaux, vide le scope et remet les variables de cible a zero")
        act_new_session.triggered.connect(self._on_new_session)
        m_file.addAction(act_new_session)

        act_reset_window = QAction("Reinitialiser fenetre + session", self)
        act_reset_window.setToolTip("Restaure la disposition et vide IP, subnets, machines et variables de cible")
        act_reset_window.triggered.connect(self._on_reset_window)
        m_file.addAction(act_reset_window)

        act_clear_saved = QAction("Effacer la session sauvegardee", self)
        act_clear_saved.setToolTip("Supprime data/runtime/sessions/last_session.json -- au prochain demarrage on partira vierge")
        act_clear_saved.triggered.connect(self._on_clear_saved_session)
        m_file.addAction(act_clear_saved)

        m_file.addSeparator()

        # ----- Notes -----
        # Note: pas de setShortcut ici (Ambiguous shortcut overload Ctrl+N).
        # La toolbar action act_note a deja le shortcut.
        act_new_note = QAction("Nouvelle note... (Ctrl+N)", self)
        act_new_note.triggered.connect(self._on_new_note)
        m_file.addAction(act_new_note)

        act_open_note = QAction("Ouvrir une note...", self)
        act_open_note.setShortcut(QKeySequence("Ctrl+O"))
        act_open_note.triggered.connect(self._on_open_note_dialog)
        m_file.addAction(act_open_note)

        act_import_note = QAction("Importer une note...", self)
        act_import_note.triggered.connect(self._on_import_note)
        m_file.addAction(act_import_note)

        act_export_note = QAction("Exporter la note active...", self)
        act_export_note.triggered.connect(self._on_export_note)
        m_file.addAction(act_export_note)

        m_file.addSeparator()

        # ----- Terminal -----
        # Note: pas de setShortcut ici pour eviter "Ambiguous shortcut overload:
        # Ctrl+T" -- la toolbar action act_term a deja le meme shortcut, et
        # Qt ne sait pas lequel declencher. Le shortcut continue de marcher
        # via la version toolbar.
        act_new_term = QAction("Nouveau terminal (Ctrl+T)", self)
        act_new_term.triggered.connect(lambda: self.spawn_terminal())
        m_file.addAction(act_new_term)

        m_file.addSeparator()
        act_quit = QAction("Quitter", self)
        act_quit.setShortcut(QKeySequence.Quit)
        act_quit.triggered.connect(self.close)
        m_file.addAction(act_quit)

        m_view = mb.addMenu("Affichage")
        # Toggle de chaque dock
        for dock in [
            self._dock_tools, self._dock_scope, self._dock_notes,
            self._dock_docs, self._dock_creds, self._dock_clip,
            self._dock_history, self._dock_targets, self._dock_wordlists,
        ]:
            act = dock.toggleViewAction()
            m_view.addAction(act)

        m_tools = mb.addMenu("&Outils")
        m_tools.addAction(QAction("Vérifier l'intégrité des outils", self,
                                   triggered=lambda: self._tools.check_integrity_async(force=True)))
        m_tools.addAction(QAction("AutoGrep sur le presse-papier", self,
                                   triggered=self._on_autogrep_clipboard))
        m_tools.addSeparator()
        m_tools.addAction(QAction("BloodHound : démarrer Docker", self,
                                   triggered=self._on_bloodhound_start))
        m_tools.addAction(QAction("BloodHound : arrêter Docker", self,
                                   triggered=self._on_bloodhound_stop))

        m_help = mb.addMenu("Aide")
        m_help.addAction(QAction("Documentation (F1)", self,
                                  shortcut=QKeySequence("F1"),
                                  triggered=lambda: self._dock_docs.raise_()))
        m_help.addAction(QAction("À propos...", self,
                                  triggered=self._on_about))

    def _build_status_bar(self) -> None:
        self._status = StatusBar(
            network=self._network,
            terminals=self._terminals,
            listeners=self._listeners,
            file_servers=self._fileservs,
            tunnels=self._tunnels,
        )
        # Timer d'examen OSCP (23h45 par defaut)
        self._exam_timer = ExamTimer(self._cfg, parent=self)
        self._exam_timer.expired.connect(self._on_exam_expired)
        sb = QStatusBar(self)
        sb.addWidget(self._status, 1)
        # Timer EN BAS-A-DROITE (addPermanentWidget) pour ne pas cacher le menu bar.
        # L'ordre d'ajout = ordre d'affichage droite vers gauche.
        sb.addPermanentWidget(self._exam_timer)
        self.setStatusBar(sb)
        # Menu contextuel clic droit sur status bar (IP, actions rapides)
        self._status.setContextMenuPolicy(Qt.CustomContextMenu)
        self._status.customContextMenuRequested.connect(self._on_status_context_menu)

    def _install_shortcuts(self) -> None:
        QShortcut(QKeySequence("Ctrl+K"), self, lambda: self._dock_clip.raise_())
        QShortcut(QKeySequence("Ctrl+H"), self, lambda: self._dock_history.raise_())
        QShortcut(QKeySequence("Ctrl+W"), self, self._on_close_current_tab)
        QShortcut(QKeySequence("F5"), self, lambda: self._tools.check_integrity_async(force=True))
        # F2/F3/F4 pour les boutons services (Listener/HTTP/Ligolo).
        # On utilise QShortcut plutot que QToolButton.setShortcut qui peut
        # freezer la fenetre sur WSLg/xcb (grab clavier corrompu).
        QShortcut(QKeySequence("F2"), self, self._quick_listener)
        QShortcut(QKeySequence("F3"), self, self._quick_http_server)
        QShortcut(QKeySequence("F4"), self, self._quick_ligolo)

    # ==============================================================
    # Wiring des signaux
    # ==============================================================

    def _wire_signals(self) -> None:
        # Tools -> launch
        self._tool_panel.launch_requested.connect(self._on_launch_tool)
        self._tool_panel.doc_requested.connect(self._doc_panel.load_doc)

        # Scope -> status bar (machine active)
        self._scope_panel.machine_selected.connect(self._on_machine_selected)

        # Notes -> status bar update si la note change
        self._notes_panel.note_switched.connect(self._on_note_switched)
        # Auto-pull LHOST quand le reseau change (non-intrusif : ne remplace pas si deja set)
        self._network.refreshed.connect(self._on_network_refreshed)

        # Clipboard : sélection dans un terminal → envoyer vers la note active
        self._terminals.terminal_created.connect(self._wire_terminal_worker_signals)

        # Status bar : override IP manuelle (signal str "" = retour auto)
        self._status.ip_override_requested.connect(
            lambda ip: self._network.set_manual_ip(ip.strip() or None)
        )

        # Proof tracker : popup quand une machine passe "Rooted"
        self._proof.proof_reminder.connect(self._on_proof_reminder)

        # Docker : update status bar ?
        # (on laisse pour plus tard — docker status visible dans son panel)

    def _wire_terminal_worker_signals(self, worker: TerminalWorker) -> None:
        """Nothing needed here at worker level — la plupart du wiring se fait
        dans TerminalTab (qui est créé dans _add_terminal_tab)."""
        pass

    # ==============================================================
    # Terminaux
    # ==============================================================

    def spawn_terminal(
        self,
        command: Optional[List[str]] = None,
        title: str = "Terminal",
        cwd: Optional[str] = None,
        category: str = "default",
        tool_name: str = "",
    ) -> TerminalTab:
        """Crée un nouveau terminal embarqué."""
        worker = self._terminals.spawn(
            command=command,
            cwd=cwd,
            terminal_name=title,
        )
        tab = TerminalTab(
            worker=worker,
            title=title,
            category=category,
            color=_CATEGORY_COLOR.get(category),
        )
        tab.command_entered.connect(
            lambda cmd: self._on_command_entered(cmd, title, tool_name)
        )
        tab.output_selected.connect(self._on_output_pushed_to_note)
        tab.closed_requested.connect(lambda: self._close_tab(tab))

        # Enregistre dans le CentralStack
        idx = self._central.add_terminal(tab, title)
        self._tabs.setCurrentIndex(idx)
        color = _CATEGORY_COLOR.get(category)
        if color:
            self._tabs.tabBar().setTabTextColor(idx, QColor(color))
        # Push selection -> autre terminal (signal propage par terminal_tab v2)
        if hasattr(tab, "output_send_to_terminal"):
            tab.output_send_to_terminal.connect(self._on_send_to_other_terminal)
        # Indicateur visuel quand le process se termine : grise + suffixe.
        # On stocke la fonction slot sur le tab pour pouvoir la deconnecter
        # explicitement dans _close_tab : sinon le worker (QThread qui survit
        # au tab) pourrait emettre finished_signal apres deletion -> RuntimeError.
        def _finished_slot(code, _tab=tab):
            self._mark_tab_finished(_tab, code)
        worker.finished_signal.connect(_finished_slot)
        tab._finished_slot = _finished_slot   # type: ignore[attr-defined]
        tab.focus_input()
        return tab

    def _mark_tab_finished(self, tab: TerminalTab, exit_code: int) -> None:
        """Grise l'onglet d'un terminal dont le process est termine.

        IMPORTANT : le worker QThread peut emettre finished_signal APRES
        que l'utilisateur ait ferme l'onglet -- le widget C++ TerminalTab
        est alors detruit, mais le wrapper Python existe encore. On doit
        donc tester l'existence avant tout acces, sinon RuntimeError.
        """
        try:
            from sip import isdeleted
        except ImportError:
            try:
                from PyQt5.sip import isdeleted
            except ImportError:
                isdeleted = lambda _: False  # fallback: best effort
        if isdeleted(tab):
            return
        try:
            idx = self._tabs.indexOf(tab)
        except RuntimeError:
            # Widget detruit entre le check isdeleted et l'acces : on abandonne
            return
        if idx < 0:
            return
        bar = self._tabs.tabBar()
        bar.setTabTextColor(idx, QColor("#666666"))
        current_text = bar.tabText(idx)
        # Eviter d'ajouter le suffixe deux fois si l'utilisateur reste dessus
        if "(termine)" not in current_text:
            bar.setTabText(idx, f"{current_text} (termine)")

    def _on_tab_close_requested(self, idx: int) -> None:
        w = self._tabs.widget(idx)
        if not isinstance(w, TerminalTab):
            return
        self._close_tab(w)

    def _close_tab(self, tab: TerminalTab) -> None:
        worker = tab.worker()
        # Deconnecter le slot finished avant la destruction du tab :
        # le worker QThread peut survivre encore quelques ms et emettre
        # finished_signal sur un widget detruit -> RuntimeError.
        slot = getattr(tab, "_finished_slot", None)
        if slot is not None:
            try:
                worker.finished_signal.disconnect(slot)
            except (TypeError, RuntimeError):
                pass
        # Idem pour les 5 signaux que TerminalTab connecte lui-meme
        # vers ses propres slots. La methode se charge des try/except.
        try:
            tab.disconnect_worker_signals()
        except Exception:
            log.exception("disconnect_worker_signals failed")
        worker.request_stop(graceful=True)
        self._central.remove_terminal(tab)
        tab.deleteLater()

    def _on_tab_rename(self, idx: int) -> None:
        if idx <= 0:        # onglet accueil
            return
        current = self._tabs.tabText(idx).strip()
        new, ok = QInputDialog.getText(self, "Renommer l'onglet", "Nom :", text=current)
        if ok and new.strip():
            self._tabs.setTabText(idx, new.strip())

    def _on_close_current_tab(self) -> None:
        idx = self._tabs.currentIndex()
        if idx == 0:
            return
        self._on_tab_close_requested(idx)

    def _on_command_entered(self, command: str, terminal_name: str, tool_name: str) -> None:
        """Log toute commande tapée dans un terminal."""
        active_note = self._notes.active()
        machine = active_note.name if active_note else ""
        self._history.record(
            command=command,
            tool=tool_name,
            terminal=terminal_name,
            machine=machine,
            workspace="Default",
        )
        # Appending dans la note active (optionnel — silencieux si pas de note)
        if active_note:
            try:
                self._notes.append_command(active_note.name, command)
            except Exception:
                log.exception("Failed to append command to note")

    def _on_output_pushed_to_note(self, text: str) -> None:
        active = self._notes.active()
        if not active:
            info_box(self, "Aucune note active",
                     "Crée ou sélectionne une note avant de pousser du contenu.")
            return
        try:
            self._notes.append_section(active.name, "Output", f"```\n{text}\n```")
        except Exception as exc:
            error_box(self, "Erreur", f"Impossible d'ajouter à la note : {exc}")

        # AutoGrep en parallèle : on détecte creds / hashes / IPs et on propose
        try:
            findings_by_kind = run_all(text)
            total = sum(len(v) for v in findings_by_kind.values())
            if total:
                # Flatten
                flat = [f for lst in findings_by_kind.values() for f in lst]
                self._on_autogrep_findings(flat)
        except Exception:
            log.exception("AutoGrep failed")

    def _on_autogrep_findings(self, findings) -> None:
        """Traite les résultats AutoGrep : propose ajout creds/hash au vault."""
        # findings est une liste de Finding. On les montre en info simple.
        n = len(findings)
        if n == 0:
            return
        # Offre seulement une notification pour l'instant.
        self._status.set_target_machine(f"+{n} finding(s) AutoGrep")

    def _on_autogrep_clipboard(self) -> None:
        """Pris la dernière entrée du clipboard, autogrep dessus."""
        items = self._clipboard.all()
        if not items:
            info_box(self, "Presse-papier vide", "Rien à analyser.")
            return
        last = items[0]
        try:
            findings_by_kind = run_all(last.text)
        except Exception as exc:
            error_box(self, "AutoGrep échoué", str(exc))
            return
        flat = [f for lst in findings_by_kind.values() for f in lst]
        if not flat:
            info_box(self, "AutoGrep", "Aucun finding détecté.")
            return
        msg = "\n".join(f"{f.kind}: {f.value}" for f in flat[:30])
        info_box(self, f"AutoGrep - {len(flat)} finding(s)", msg)

    # ==============================================================
    # Tools → terminaux
    # ==============================================================

    def _on_launch_tool(self, tool: Tool, template_index: int) -> None:
        """Lancer un outil : résoudre placeholders -> spawn terminal."""
        if tool.transfer_asset:
            self._add_tool_to_file_server(tool)
            return

        # Choix du template
        if not tool.templates:
            # Pas de template : juste le path
            cmd = tool.path or tool.name
            self.spawn_terminal(
                command=[cmd] if cmd else None,
                title=f"Terminal - {tool.name}",
                category=self._category_from_tool(tool),
                tool_name=tool.name,
            )
            self._tools.record_usage(tool.name, cmd)
            return

        if template_index < 0 or template_index >= len(tool.templates):
            # Prompt : demander quel template
            items = [f"[{i+1}] {t}" for i, t in enumerate(tool.templates)]
            choice, ok = QInputDialog.getItem(
                self, f"Template - {tool.name}",
                "Choisir un template :", items, 0, False,
            )
            if not ok:
                return
            template_index = items.index(choice)

        template = tool.templates[template_index]
        placeholders = tool.extract_placeholders(template)

        # Pré-remplissage avec creds du vault et IP attaquante
        defaults: Dict[str, str] = {}
        attacker_ip = self._network.attacker_ip()
        if attacker_ip:
            defaults["LHOST"] = attacker_ip
            defaults["ATTACKER_IP"] = attacker_ip
        # Machine active
        active_machine = self._current_active_machine_ip()
        if active_machine:
            defaults["IP"] = active_machine
            defaults["RHOST"] = active_machine
            defaults["TARGET"] = active_machine
        # CRED:user / CRED:pass / CRED:hash
        defaults.update(self._cred_defaults_for(placeholders))

        if placeholders:
            # Construit les suggestions de cibles depuis le scope
            # (machines + subnets) : permet a l'utilisateur de selectionner
            # une IP au lieu de la taper.
            scope_suggestions = self._build_scope_suggestions()
            sugg_per_placeholder: Dict[str, List[Tuple[str, str]]] = {}
            for key, sub in placeholders:
                full_key = f"{key}:{sub}" if sub else key
                # On propose des suggestions sur les cles classiques de cible
                if key.upper() in PlaceholderDialog.TARGET_KEYS:
                    if key.upper() in ("RANGE", "SUBNET", "CIDR"):
                        sugg_per_placeholder[full_key] = scope_suggestions["subnets"]
                    else:
                        sugg_per_placeholder[full_key] = scope_suggestions["machines"]

            dlg = PlaceholderDialog(
                template, placeholders, defaults,
                parent=self, suggestions=sugg_per_placeholder,
                # Volet lateral "Cibles enregistrees" -- toujours dispo
                # si le scope contient des entrees, peu importe le placeholder.
                scope_machines=scope_suggestions["machines"],
                scope_subnets=scope_suggestions["subnets"],
            )
            if dlg.exec_() != dlg.Accepted:
                return
            final_cmd = dlg.resolved_command()
        else:
            final_cmd = template

        # Lancer en shell (pour accepter les pipes, &&, etc.)
        self.spawn_terminal(
            command=["/bin/bash", "-lc", final_cmd],
            title=f"Terminal - {tool.name}",
            category=self._category_from_tool(tool),
            tool_name=tool.name,
        )
        self._tools.record_usage(tool.name, final_cmd)
        self._history.record(command=final_cmd, tool=tool.name, terminal=tool.name)

    def _add_tool_to_file_server(self, tool: Tool) -> None:
        """Stage a local binary/script in the File Server transfer list."""
        path = self._resolve_tool_asset_path(tool.path)
        if path is None:
            error_box(
                self,
                "Fichier introuvable",
                f"Impossible de trouver le fichier local pour '{tool.name}'.\n\n"
                f"Chemin configure : {tool.path or '(vide)'}",
            )
            return

        self._dock_fs.show()
        self._dock_fs.raise_()
        ok = self._file_server_panel.add_transfer_file(str(path), start_server=True)
        if not ok:
            return
        url = self._file_server_panel.current_base_url() + path.name
        self._tools.record_usage(tool.name, f"transfer:{path}")
        self._history.record(command=f"# transfer {tool.name}: {url}", tool=tool.name, terminal="file-server")
        self.statusBar().showMessage(
            f"{tool.name} ajoute au File Server : {url}",
            5000,
        )

    def _resolve_tool_asset_path(self, raw_path: str) -> Optional[Path]:
        if not raw_path:
            return None
        expanded = self._env.expand_value(raw_path)
        candidates = [expanded]
        if expanded.startswith("/mnt/") and len(expanded) > 6:
            drive = expanded[5]
            rest = expanded[7:].replace("/", "\\")
            candidates.append(f"{drive.upper()}:\\{rest}")
        for candidate in candidates:
            p = Path(candidate)
            if p.is_file():
                return p
        return None

    def _build_scope_suggestions(self) -> Dict[str, List[Tuple[str, str]]]:
        """Construit les listes de suggestions a partir du scope.

        Retourne :
          {
             "machines": [(label, value), ...],   # IPs des machines
             "subnets":  [(label, value), ...],   # CIDRs des subnets
          }
        Le label est ce qui s'affiche dans la combobox (ex: "DC01 (10.10.10.5)").
        La value est ce qui est injecte dans la commande (juste l'IP).
        """
        machines: List[Tuple[str, str]] = []
        for m in self._scope.machines():
            if not m.ip:
                continue
            label_parts = [m.ip]
            if m.hostname:
                label_parts.append(f"({m.hostname})")
            if m.os:
                label_parts.append(f"[{m.os}]")
            if m.status and m.status != "todo":
                label_parts.append(f"<{m.status}>")
            label = " ".join(label_parts)
            machines.append((label, m.ip))
        # Tri par status (rooted en bas) puis par hostname
        machines.sort(key=lambda lv: lv[1])

        # Cible active en premier si dispo
        active_ip = self._current_active_machine_ip()
        if active_ip:
            machines.sort(key=lambda lv: 0 if lv[1] == active_ip else 1)

        subnets: List[Tuple[str, str]] = []
        for s in self._scope.subnets():
            label = f"{s.cidr}" + (f" ({s.label})" if s.label else "")
            subnets.append((label, s.cidr))

        return {"machines": machines, "subnets": subnets}

    def _cred_defaults_for(self, placeholders) -> Dict[str, str]:
        """Remplit CRED:user / CRED:pass / CRED:hash depuis la première cred dispo."""
        out: Dict[str, str] = {}
        needs_cred = any(k == "CRED" for k, _ in placeholders)
        if not needs_cred:
            return out
        creds = self._vault.all()
        if not creds:
            return out
        c = creds[0]
        for k, sub in placeholders:
            if k != "CRED" or sub is None:
                continue
            sub_l = sub.lower()
            if sub_l in ("user", "username"):
                out[f"CRED:{sub}"] = c.username
            elif sub_l in ("pass", "password"):
                out[f"CRED:{sub}"] = c.password
            elif sub_l == "hash":
                out[f"CRED:{sub}"] = c.hash
            elif sub_l == "domain":
                out[f"CRED:{sub}"] = c.domain
        return out

    def _current_active_machine_ip(self) -> str:
        # Si la note active a un nom matchant une machine du scope, on prend son IP
        active_note = self._notes.active()
        if not active_note:
            return ""
        for m in self._scope.machines():
            if m.hostname == active_note.name or m.ip == active_note.name:
                return m.ip
        return ""

    @staticmethod
    def _category_from_tool(tool: Tool) -> str:
        c = tool.category.lower()
        if "exploit" in c: return "exploit"
        if "enum" in c:    return "enum"
        if "privesc" in c or "priv esc" in c: return "privesc"
        if "active" in c or "directory" in c or "ad" in c.split(): return "ad"
        return "default"

    # ==============================================================
    # Notes
    # ==============================================================

    # ==============================================================
    # Session : new / open / reset
    # ==============================================================

    def _on_new_session(self) -> None:
        """Ferme les terminaux et repart sur un scope propre."""
        from ui.dialogs import confirm
        active = [w for w in self._terminals.all() if w.isRunning()]
        msg = "Demarrer une nouvelle session vierge ?"
        if active:
            msg += f"\n\n{len(active)} terminal(s) actif(s) seront termines."
        msg += "\n\nLe scope sera vide : IP, machines, subnets et pivots."
        msg += "\nLes variables TARGET/DOMAIN/USER/PASS/HASH seront remises a zero."
        msg += "\nLa session sauvegardee sera effacee."
        msg += "\nLes notes sur disque sont conservees."
        if not confirm(self, "Nouvelle session", msg):
            return

        # Stop tous les terminaux
        try:
            self._terminals.stop_all()
        except Exception:
            log.exception("stop_all failed")

        # Vider l'UI : retire tous les terminaux du CentralStack.
        # On ferme onglet par onglet pour laisser le CentralStack faire le menage.
        # Range descendant pour eviter les decalages d'index.
        try:
            n = self._tabs.count()
            for idx in range(n - 1, -1, -1):
                w = self._tabs.widget(idx)
                # On ne ferme pas l'eventuel onglet "Accueil" si present
                if w is not None and hasattr(w, "worker"):
                    self._on_tab_close_requested(idx)
        except Exception:
            log.exception("Cannot clear tabs")

        # Pas de note active
        try:
            self._notes.set_active(None)
        except Exception:
            pass
        self._reset_session_data()
        self.statusBar().showMessage("Nouvelle session vierge demarree", 3000)

    def _reset_session_data(self) -> None:
        """Vide les donnees qui definissent la session de travail courante."""
        try:
            self._scope.clear()
        except Exception:
            log.exception("Cannot clear scope")
        try:
            self._env.reset_to_defaults()
        except Exception:
            log.exception("Cannot reset env vars")
        try:
            self._network.set_manual_ip(None)
        except Exception:
            log.exception("Cannot reset manual IP")
        try:
            self._session.clear()
        except Exception:
            log.exception("Cannot clear saved session")

    def _on_reset_window(self) -> None:
        """Restaure la disposition par defaut et vide la session de travail.

        Efface layout.json, invalide le cache du ConfigManager,
        re-applique la geometrie par defaut (centree sur ecran primaire),
        et masque les docks non-essentiels.

        Pas besoin de redemarrer.
        """
        from ui.dialogs import confirm
        if not confirm(
            self, "Reinitialiser la fenetre",
            "Effacer la disposition sauvegardee, remettre la fenetre\n"
            "en taille/position par defaut et vider IP/subnets/machines ?\n\n"
            "Les notes sur disque sont conservees.",
        ):
            return
        try:
            # 1. Effacer le fichier sur disque
            layout_path = self._cfg.config_dir / "layout.json"
            if layout_path.exists():
                layout_path.unlink()
                log.info("layout.json supprime")

            # 2. Invalider le cache du ConfigManager
            self._cfg.invalidate("layout")

            # 3. Pour eviter que _persist_layout reecrive l'ancien layout
            # via le timer debounce qui pourrait etre arme, on stoppe le
            # timer puis on le redemarre apres reset.
            if hasattr(self, "_layout_save_timer"):
                self._layout_save_timer.stop()

            # 4. Sortir du mode maximise pour que move/resize aient effet
            if self.isMaximized():
                self.showNormal()

            # 5. Re-appliquer geometrie par defaut (centree sur ecran primaire)
            self._apply_default_geometry()

            # 6. Re-appliquer la visibilite par defaut des docks
            #    (4 visibles : Outils/Scope/Notes/Credentials)
            for dock in [self._dock_docs, self._dock_clip, self._dock_history,
                         self._dock_targets, self._dock_wordlists, self._dock_fs]:
                dock.setFloating(False)
                dock.hide()
            for dock in [self._dock_tools, self._dock_scope, self._dock_notes,
                         self._dock_creds]:
                dock.setFloating(False)
                dock.show()
            self._dock_creds.raise_()
            self._reset_session_data()

            self.statusBar().showMessage(
                "Fenetre et session reinitialisees", 3000
            )
        except Exception as exc:
            log.exception("Reset window failed")
            error_box(self, "Erreur", f"Impossible de reinitialiser : {exc}")

    def _on_clear_saved_session(self) -> None:
        """Supprime la session sauvegardee sur disque."""
        from ui.dialogs import confirm
        if not self._session.has_previous():
            self.statusBar().showMessage("Aucune session sauvegardee", 3000)
            return
        if not confirm(
            self, "Effacer la session sauvegardee",
            "Supprimer la session sauvegardee sur disque ?\n\n"
            "Au prochain demarrage, le toolkit demarrera vierge.",
        ):
            return
        try:
            self._session.clear()
            self.statusBar().showMessage("Session sauvegardee effacee", 3000)
        except Exception as exc:
            error_box(self, "Erreur", f"Impossible d'effacer la session : {exc}")

    def _on_open_note_dialog(self) -> None:
        """Dialog 'Ouvrir une note existante'.

        Liste toutes les notes du NotesManager et permet d'en activer une.
        """
        from PyQt5.QtWidgets import QInputDialog
        notes = self._notes.all()
        if not notes:
            self.statusBar().showMessage(
                "Aucune note encore. Ctrl+N pour en creer une.", 3000,
            )
            return
        names = sorted(n.name for n in notes)
        # active courante en preselection si elle existe
        cur = self._notes.active()
        cur_idx = names.index(cur.name) if cur and cur.name in names else 0
        choice, ok = QInputDialog.getItem(
            self, "Ouvrir une note", "Note :", names, cur_idx, editable=False,
        )
        if not ok or not choice:
            return
        self._notes.set_active(choice)
        self._dock_notes.show()
        self._dock_notes.raise_()

    # ==============================================================
    # Notes (existing)
    # ==============================================================

    def _on_new_note(self) -> None:
        name, ok = QInputDialog.getText(self, "Nouvelle note", "Nom (machine / cible) :")
        if not ok or not name.strip():
            return
        ip, _ = QInputDialog.getText(self, "IP (optionnel)",
                                      f"IP de {name} :")
        try:
            note = self._notes.create(name.strip(), ip=ip.strip())
        except ValueError as exc:
            error_box(self, "Erreur", str(exc))
            return
        self._notes.set_active(note.name)
        self._dock_notes.raise_()

    def _on_note_switched(self, note: Optional[Note]) -> None:
        if note is None:
            self._status.set_target_machine("Cible : -")
        else:
            self._status.set_target_machine(f"Cible : {note.name}")

    def _on_machine_selected(self, machine) -> None:
        if machine is None:
            self._status.set_target_machine("Cible : -")
            return
        self._status.set_target_machine(f"Cible : {machine.hostname or machine.ip}")
        # Si une note homonyme existe, on l'active
        existing = self._notes.get(machine.hostname or machine.ip)
        if existing:
            self._notes.set_active(existing.name)

    def _on_import_note(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Importer une note",
                                               str(Path.home()),
                                               "Markdown (*.md);;Tous (*)")
        if not path:
            return
        try:
            note = self._notes.import_file(path)
            self._notes.set_active(note.name)
        except Exception as exc:
            error_box(self, "Import échoué", str(exc))

    def _on_export_note(self) -> None:
        active = self._notes.active()
        if not active:
            info_box(self, "Rien à exporter", "Sélectionne d'abord une note.")
            return
        path, selected = QFileDialog.getSaveFileName(
            self, "Exporter la note", f"{active.name}.md",
            "Markdown (*.md);;PDF (*.pdf)",
        )
        if not path:
            return
        try:
            if path.lower().endswith(".pdf"):
                self._notes.export_pdf(active.name, path)
            else:
                self._notes.export_markdown(active.name, path)
            info_box(self, "Export OK", f"Exporté vers :\n{path}")
        except Exception as exc:
            error_box(self, "Export échoué", str(exc))

    # ==============================================================
    # Dialogs "Quick actions"
    # ==============================================================

    # ==============================================================
    # Batch 1 : env manager + terminal externe + revshells web + timer
    # ==============================================================


    # ==============================================================
    # Batch 2 : split 2x2 / quad mode
    # ==============================================================

    def _toggle_split_mode(self, checked: bool) -> None:
        """Bascule entre tabs et quad."""
        mode = "quad" if checked else "tabs"
        try:
            self._central.set_mode(mode)
            self.statusBar().showMessage(
                "Mode grille 2x2" if checked else "Mode onglets"
            , 3000)
        except Exception:
            log.exception("set_mode failed")

    def _on_new_terminal_in_slot(self, slot_idx: int) -> None:
        """Appele par CentralStack quand l'utilisateur clique '+' dans un slot."""
        tab = self.spawn_terminal(title=f"Slot {slot_idx + 1}")
        # Mount dans le slot demande
        self._central.mount_terminal_in_slot(slot_idx, tab)

    def _on_send_to_other_terminal(self, text: str) -> None:
        """Envoie une selection vers un autre terminal (dialogue)."""
        terms = [t for t in self._central.all_terminals() if t is not self.sender()]
        if not terms:
            info_box(self, "Aucun autre terminal", "Ouvre un autre terminal d'abord.")
            return
        items = [t.title() for t in terms]
        chosen, ok = QInputDialog.getItem(
            self, "Envoyer vers terminal", "Cible :", items, 0, False,
        )
        if not ok:
            return
        idx = items.index(chosen)
        target = terms[idx]
        target.send_command(text.strip())
        self.statusBar().showMessage(f"Envoye vers {chosen}", 3000)

    # ==============================================================
    # Batch 4 : Quick actions F2-F4 + status bar menu
    # ==============================================================

    def _quick_listener(self) -> None:
        """F2 : demarre un nc listener dans un terminal integre."""
        lport = self._env.get("LPORT") or "4444"
        cmd = f"rlwrap nc -lvnp {lport}"
        tab = self.spawn_terminal(title=f"Listener :{lport}", category="exploit")
        # Injecte la commande dans le shell PTY
        if hasattr(tab, "send_command"):
            tab.send_command(cmd)

    def _quick_http_server(self) -> None:
        """F3 : demarre le serveur HTTP du panel File Server.
        Si le panel n'est pas dispo, fallback : lance python3 -m http.server
        dans un terminal integre.
        """
        # Voie 1 : panel File Server
        if hasattr(self, "_file_server_panel") and hasattr(self, "_dock_fs"):
            try:
                self._dock_fs.show()
                self._dock_fs.raise_()
                # Verifie qu'un serveur n'est pas deja actif
                if self._file_server_panel._current_share is not None:
                    self.statusBar().showMessage("Serveur HTTP deja actif", 3000)
                    return
                self._file_server_panel._start_server()
                # _start_server a deja affiche un messagebox si erreur
                if self._file_server_panel._current_share is not None:
                    port = self._file_server_panel._current_share.port
                    self.statusBar().showMessage(f"Serveur HTTP demarre sur :{port}", 3000)
                    return
            except Exception as exc:
                log.exception("F3 voie 1 (panel) failed")
                # On continue vers le fallback

        # Voie 2 : fallback terminal integre
        try:
            tab = self.spawn_terminal(title="HTTP server", category="network")
            if hasattr(tab, "send_command"):
                tab.send_command("python3 -m http.server 8000")
                self.statusBar().showMessage("Serveur HTTP lance dans un terminal", 3000)
            else:
                error_box(self, "HTTP server", "Impossible de demarrer le serveur.")
        except Exception as exc:
            log.exception("F3 voie 2 (terminal) failed")
            error_box(self, "HTTP server", f"Echec : {exc}")

    def _quick_ligolo(self) -> None:
        """F4 (shortcut) : declenche un click sur le bouton ligolo (toggle)."""
        # Le bouton est checkable : on inverse l'etat puis on appelle le handler.
        self._btn_ligolo.setChecked(not self._btn_ligolo.isChecked())
        self._on_ligolo_clicked()

    def _on_ligolo_clicked(self) -> None:
        """Toggle Ligolo : start si OFF, stop si ON. Met le bouton en coherence
        avec l'etat reel apres l'action.
        """
        # Etat _avant_ qu'on agisse : Qt a deja flippe le checked-state.
        # On regarde donc l'etat reel du process pour decider.
        try:
            running = self._tool_setup.is_running("ligolo-proxy")
        except Exception as exc:
            error_box(self, "Erreur Ligolo", str(exc))
            self._sync_ligolo_button()
            return

        if running:
            # Stop
            try:
                self._tool_setup.stop("ligolo-proxy")
                self.statusBar().showMessage("Ligolo arrete", 3000)
            except Exception as exc:
                error_box(self, "Erreur Ligolo (stop)", str(exc))
        else:
            # Start
            try:
                pid = self._tool_setup.start("ligolo-proxy")
                self.statusBar().showMessage(
                    f"Ligolo proxy demarre (pid {pid})", 3000
                )
            except Exception as exc:
                error_box(self, "Erreur Ligolo (start)", str(exc))

        # Resync pour refleter la verite (au cas ou start/stop a echoue)
        self._sync_ligolo_button()

    def _sync_ligolo_button(self) -> None:
        """Met le visuel du bouton en accord avec l'etat reel du proxy."""
        if not hasattr(self, "_btn_ligolo"):
            return
        try:
            running = self._tool_setup.is_running("ligolo-proxy")
        except Exception:
            running = False
        self._btn_ligolo.blockSignals(True)
        self._btn_ligolo.setChecked(running)
        self._btn_ligolo.setText("Ligolo: ON (F4)" if running else "Ligolo (F4)")
        self._btn_ligolo.blockSignals(False)

    def _on_tool_setup_changed(self, key: str) -> None:
        """Slot generique : si Ligolo a ete demarre/arrete par un autre
        chemin (palette, dialog), on resync le bouton.
        """
        if key == "ligolo-proxy":
            self._sync_ligolo_button()

    def _on_ligolo_context_menu(self, point) -> None:
        """Menu clic droit : configurer la commande Ligolo."""
        from PyQt5.QtWidgets import QMenu
        menu = QMenu(self)
        menu.addAction("Configurer la commande...", self._configure_ligolo_command)
        menu.addSeparator()
        if self._tool_setup.is_running("ligolo-proxy"):
            menu.addAction("Arreter le service", lambda: self._tool_setup.stop("ligolo-proxy"))
        else:
            menu.addAction("Demarrer le service", self._on_ligolo_clicked)
        menu.exec_(self._btn_ligolo.mapToGlobal(point))

    def _configure_ligolo_command(self) -> None:
        """Dialog d'edition de la commande de demarrage Ligolo.
        La modification est persistee dans le ToolSetupRegistry.
        """
        from PyQt5.QtWidgets import (
            QDialog, QDialogButtonBox, QFormLayout, QLineEdit, QLabel,
            QVBoxLayout,
        )

        action = self._tool_setup._actions.get("ligolo-proxy")
        if action is None:
            error_box(self, "Ligolo", "Action 'ligolo-proxy' introuvable.")
            return

        dlg = QDialog(self)
        dlg.setWindowTitle("Configurer la commande Ligolo")
        dlg.setMinimumWidth(640)

        v = QVBoxLayout(dlg)
        v.addWidget(QLabel(
            "Commande lancee au clic sur le bouton Ligolo.\n"
            "Format : argv separe par des espaces (un argument par token)."
        ))

        form = QFormLayout()
        # shlex.join met des guillemets autour des args contenant des espaces,
        # de sorte que shlex.split au save reconstruit la liste exacte.
        import shlex
        cmd_edit = QLineEdit(shlex.join(action.command))
        cwd_edit = QLineEdit(action.cwd or "")
        form.addRow("Commande :", cmd_edit)
        form.addRow("CWD (optionnel) :", cwd_edit)
        v.addLayout(form)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        v.addWidget(bb)

        if dlg.exec_() != QDialog.Accepted:
            return

        # Parse propre : shlex.split gere les guillemets et les arguments
        # multi-mots ("bash -c 'echo hello world'") sans casser. Un simple
        # .split(" ") aurait deparse "echo hello world" en 3 args.
        import shlex
        new_cmd_str = cmd_edit.text().strip()
        if not new_cmd_str:
            error_box(self, "Ligolo", "Commande vide refusee.")
            return
        try:
            new_cmd = shlex.split(new_cmd_str)
        except ValueError as exc:
            # shlex peut lever sur des guillemets non-fermes
            error_box(self, "Ligolo", f"Commande mal formee : {exc}")
            return
        if not new_cmd:
            error_box(self, "Ligolo", "Commande vide apres parsing.")
            return
        new_cwd = cwd_edit.text().strip() or None

        # Mutation in-place dans le registry. Un mecanisme de persistance
        # via le config_manager pourrait etre ajoute ici.
        action.command = new_cmd
        action.cwd = new_cwd

        # Persiste dans config/services_overrides.json pour survivre au reboot.
        try:
            overrides = self._cfg.load("services_overrides", use_cache=False)
        except Exception:
            overrides = {}
        if not isinstance(overrides, dict):
            overrides = {}
        overrides["ligolo-proxy"] = {"command": new_cmd, "cwd": new_cwd}
        try:
            self._cfg.save("services_overrides", overrides)
        except Exception:
            log.exception("Cannot persist services_overrides")
            self.statusBar().showMessage(
                "Commande modifiee (session uniquement, persistence en echec)", 5000
            )
            return

        self.statusBar().showMessage("Commande Ligolo modifiee et persistee", 3000)

    def _apply_service_overrides(self) -> None:
        """Applique au demarrage les overrides de commande persistes
        dans config/services_overrides.json (s'il existe).
        """
        try:
            overrides = self._cfg.load("services_overrides", use_cache=False)
        except Exception:
            # Le fichier n'existe pas + pas de defaults : c'est OK, on ignore.
            return
        if not isinstance(overrides, dict):
            return
        for key, ov in overrides.items():
            action = self._tool_setup._actions.get(key)
            if action is None:
                continue
            if isinstance(ov, dict):
                cmd = ov.get("command")
                cwd = ov.get("cwd")
                if isinstance(cmd, list) and cmd:
                    action.command = list(cmd)
                if cwd is not None:
                    action.cwd = cwd or None
                log.info("Applied service override for '%s'", key)

    def _quick_screenshot_proof(self) -> None:
        """F9 : screenshot fenetre active, naming auto."""
        active_note = self._notes.active()
        # Note dataclass n'a pas .ip — on resout via le scope
        ip = self._current_active_machine_ip() or None
        path = capture_active_window(parent=self, ip=ip)
        if path:
            self.statusBar().showMessage(f"Proof saved: {path.name}", 3000)
            # Copie le chemin dans le clipboard
            from PyQt5.QtWidgets import QApplication
            QApplication.clipboard().setText(str(path))
            # Si une note est active, appendre un lien dedans
            if active_note:
                try:
                    self._notes.append_section(
                        active_note.name,
                        "Proof",
                        f"![proof]({path})\n\n*Screenshot {path.name}*",
                    )
                except Exception:
                    log.exception("append_section proof failed")
        else:
            error_box(self, "Screenshot", "Impossible de capturer la fenetre active.")

    def _on_status_context_menu(self, point) -> None:
        """Menu contextuel sur la status bar : actions rapides sur IP."""
        menu = QMenu(self)
        ip = self._network.attacker_ip() or ""

        if ip:
            act_copy = menu.addAction(f"Copier IP attaquante ({ip})")
            act_set_lhost = menu.addAction(f"Definir LHOST = {ip}")
            menu.addSeparator()

        act_set_manual = menu.addAction("Definir IP manuellement...")
        menu.addSeparator()
        act_env = menu.addAction("Env variables...")
        act_palette = menu.addAction("Command Palette (Ctrl+P)")

        chosen = menu.exec_(self._status.mapToGlobal(point))
        if not chosen:
            return

        from PyQt5.QtWidgets import QApplication
        if ip and chosen.text().startswith("Copier IP"):
            QApplication.clipboard().setText(ip)
        elif ip and chosen.text().startswith("Definir LHOST"):
            self._env.import_from_network(ip)
            self.statusBar().showMessage(f"LHOST = {ip}", 3000)
        elif chosen.text().startswith("Definir IP"):
            text, ok = QInputDialog.getText(
                self, "IP manuelle", "IP attaquante (ex: 10.10.14.5) :",
                text=self._network.attacker_ip() or "",
            )
            if ok:
                self._network.set_manual_ip(text.strip() or None)
        elif chosen.text().startswith("Env variables"):
            self._open_env_dialog()
        elif chosen.text().startswith("Command Palette"):
            self._open_command_palette()

    # ==============================================================
    # Batch 5 : Command palette
    # ==============================================================

    def _open_command_palette(self) -> None:
        """Ctrl+P : ouvre la palette de commandes."""
        if not hasattr(self, "_palette"):
            self._palette = CommandPalette(self)

        actions: list = []

        # Actions systeme
        actions += [
            PaletteAction("Nouveau terminal integre", "Action",
                           lambda: self.spawn_terminal(),
                           keywords="shell bash new",
                           subtitle="Ctrl+T"),
            PaletteAction("Nouveau terminal externe (wt.exe/xterm)", "Action",
                           self._spawn_external_terminal,
                           keywords="external wt xterm",
                           subtitle="Ctrl+Shift+T"),
            PaletteAction("Variables d'environnement", "Action",
                           self._open_env_dialog,
                           keywords="env lhost target domain",
                           subtitle="Ctrl+Shift+E"),
            PaletteAction("Revshells.com", "Action",
                           self._open_revshells_web,
                           keywords="reverse shell payload",
                           subtitle="Ctrl+R"),
            PaletteAction("Listener nc (F2)", "Action",
                           self._quick_listener,
                           keywords="netcat lvnp reverse"),
            PaletteAction("HTTP server (F3)", "Action",
                           self._quick_http_server,
                           keywords="python http transfer"),
            PaletteAction("Ligolo proxy (F4)", "Action",
                           self._quick_ligolo,
                           keywords="pivot tunnel"),
            PaletteAction("Screenshot proof (F9)", "Action",
                           self._quick_screenshot_proof,
                           keywords="capture proof png"),
            PaletteAction("Bascule split 2x2 (F6)", "Action",
                           lambda: self._act_split.toggle(),
                           keywords="quad grid layout"),
            PaletteAction("Encoder", "Action",
                           self._open_encoder_dialog,
                           keywords="base64 url encode",
                           subtitle="Ctrl+E"),
        ]

        # Outils (via ToolManager)
        try:
            for tool in self._tools.all():
                actions.append(PaletteAction(
                    label=tool.name,
                    category="Outil",
                    callback=lambda t=tool: self._on_launch_tool(t, 0),
                    keywords=" ".join(tool.tags) + " " + tool.category,
                    subtitle=tool.description[:60] if tool.description else "",
                ))
        except Exception:
            log.exception("palette: enum tools failed")

        # Notes
        try:
            for note in self._notes.all():
                actions.append(PaletteAction(
                    label=f"Note : {note.name}",
                    category="Note",
                    callback=lambda n=note: self._notes.set_active(n.name),
                    keywords=getattr(note, "ip", ""),
                    subtitle=getattr(note, "ip", ""),
                ))
        except Exception:
            log.exception("palette: enum notes failed")

        # Machines scope
        try:
            for m in self._scope.machines():
                label = f"{m.ip} ({m.hostname})" if m.hostname else m.ip
                actions.append(PaletteAction(
                    label=f"Machine : {label}",
                    category="Machine",
                    callback=lambda mm=m: self._focus_machine(mm),
                    keywords=(m.hostname or "") + " " + m.os,
                    subtitle=m.os or "",
                ))
        except Exception:
            log.exception("palette: enum machines failed")

        self._palette.set_actions(actions)
        self._palette.open()

    def _focus_machine(self, machine) -> None:
        """Focus sur une machine : ouvre la note ou en cree une."""
        existing = self._notes.get(machine.hostname or machine.ip)
        if existing:
            self._notes.set_active(existing.name)
        else:
            try:
                note = self._notes.create(
                    machine.hostname or machine.ip,
                    ip=machine.ip,
                )
                self._notes.set_active(note.name)
            except Exception:
                log.exception("create note for machine failed")
        self._dock_notes.raise_()

    def _open_revshells_web(self) -> None:
        """Ouvre revshells.com dans le navigateur par defaut.

        On utilise un subprocess detache avec stdout/stderr=DEVNULL au lieu de
        QDesktopServices.openUrl, qui herite la stderr du toolkit. Si le
        navigateur est chromium-snap, il deverse une dizaine de warnings
        (snapd mount, libpxbackend, dbus/UPower, ibus, etc.) dans notre log
        pour rien.
        """
        _open_url_silent("https://www.revshells.com")
        self.statusBar().showMessage("Ouverture de revshells.com...", 3000)

    def _open_env_dialog(self) -> None:
        """Dialog d'edition des variables d'env de session."""
        lhost = self._network.attacker_ip() or ""
        target = self._current_active_machine_ip() or ""
        dlg = EnvDialog(
            self._env,
            suggested_lhost=lhost,
            suggested_target=target,
            parent=self,
        )
        dlg.exec_()

    def _spawn_external_terminal(self) -> None:
        """Lance un terminal externe (wt.exe / xterm) avec env OSCP."""
        available = self._ext_term.available_backends()
        if not available:
            error_box(
                self, "Terminal externe",
                "Aucun terminal detecte.\n\n"
                "- wt.exe (Windows Terminal) introuvable\n"
                "- xterm/gnome-terminal/konsole introuvables\n\n"
                "Installe l'un d'eux ou utilise le terminal integre."
            )
            return

        # Pull LHOST auto seulement si vide (non-intrusif)
        if not self._env.get("LHOST"):
            detected = self._network.attacker_ip() or ""
            if detected:
                self._env.import_from_network(detected)

        title = "OSCP"
        active_note = self._notes.active()
        if active_note:
            title = f"OSCP - {active_note.name}"

        self._ext_term.launch(title=title, backend="auto")
        self.statusBar().showMessage(f"Terminal externe lance ({available[0]})", 3000)

    def _on_exam_expired(self) -> None:
        """Appele quand le timer d'exam arrive a zero."""
        QMessageBox.warning(
            self, "Timer OSCP",
            "Le timer d'examen est ecoule !\n\n"
            "Passe a la redaction du rapport."
        )

    def _on_network_refreshed(self, snapshot) -> None:
        """Propage l'IP detectee vers EnvManager si LHOST vide."""
        ip = self._network.attacker_ip() or ""
        if ip and not self._env.get("LHOST"):
            self._env.import_from_network(ip)

    def _open_revshell_dialog(self) -> None:
        ip = self._network.attacker_ip() or ""
        dlg = RevshellDialog(self._revshells, lhost_default=ip, parent=self)
        dlg.copy_to_clipboard_requested.connect(self._clipboard.capture)
        dlg.exec_()

    def _open_encoder_dialog(self) -> None:
        dlg = EncoderDialog(parent=self)
        dlg.copy_to_clipboard_requested.connect(self._clipboard.capture)
        dlg.exec_()

    def _open_hash_dialog(self) -> None:
        dlg = HashDialog(parent=self)
        dlg.send_to_vault_requested.connect(self._on_hash_to_vault)
        dlg.copy_to_clipboard_requested.connect(self._clipboard.capture)
        dlg.exec_()

    def _open_transfer_dialog(self) -> None:
        ip = self._network.attacker_ip() or ""
        dlg = TransferDialog(
            attacker_ip=ip,
            file_server_manager=self._fileservs,
            parent=self,
        )
        dlg.copy_to_clipboard_requested.connect(self._clipboard.capture)
        dlg.exec_()

    def _on_hash_to_vault(self, hash_value: str, hash_type: str) -> None:
        try:
            self._vault.add_simple(hash_=hash_value, hash_type=hash_type,
                                    source="hash_identifier")
            info_box(self, "Vault", f"Hash ajouté ({hash_type})")
            self._dock_creds.raise_()
        except Exception as exc:
            error_box(self, "Erreur vault", str(exc))

    # ==============================================================
    # Proof tracker
    # ==============================================================

    def _on_proof_reminder(self, machine) -> None:
        """Popup rappel checklist proof quand une machine devient Rooted."""
        target = machine.hostname or machine.ip or machine.id
        missing = [k for k, v in machine.proof.checklist.items() if not v]
        msg_lines = [
            f"[OK] {target} marquée comme Rooted !",
            "",
            "Checklist proof OSCP :",
        ]
        for k, v in machine.proof.checklist.items():
            icon = "OK" if v else "[ ]"
            label = {
                "screenshot_proof_txt": "Screenshot de proof.txt",
                "ifconfig_visible": "ipconfig / ifconfig visible",
                "whoami_visible": "whoami visible",
            }.get(k, k)
            msg_lines.append(f"{icon} {label}")
        if not machine.proof.proof_flag:
            msg_lines.append("\n[!] Flag proof.txt non renseigné")
        if missing:
            msg_lines.append("\n-> Ouvre la note de la machine pour compléter.")
        info_box(self, " Machine Rooted - rappel proof", "\n".join(msg_lines))
        # Active la note de la machine si elle existe
        existing = self._notes.get(target)
        if existing:
            self._notes.set_active(existing.name)
            self._dock_notes.raise_()

    # ==============================================================
    # Services
    # ==============================================================

    def _on_bloodhound_start(self) -> None:
        try:
            ok = self._docker.start_stack()
            if ok:
                info_box(self, "BloodHound", "Docker-compose lancé. L'interface "
                          "sera accessible sur http://localhost:8080 (défaut).")
            else:
                error_box(self, "BloodHound",
                          "Impossible de démarrer. Vérifier Docker daemon.")
        except Exception as exc:
            error_box(self, "BloodHound", f"Échec : {exc}")

    def _on_bloodhound_stop(self) -> None:
        try:
            self._docker.stop_stack()
            info_box(self, "BloodHound", "Containers arrêtés.")
        except Exception as exc:
            error_box(self, "BloodHound", f"Échec : {exc}")

    # ==============================================================
    # Recherche globale
    # ==============================================================

    def _on_global_search(self) -> None:
        query, ok = QInputDialog.getText(self, "Recherche globale",
                                          "Terme à chercher :")
        if not ok or not query.strip():
            return
        q = query.strip()
        note_hits = self._notes.search(q)
        tool_hits = self._tools.search(q)
        hist_hits = []
        try:
            hist_hits = self._history.search(query=q)[:20]
        except Exception:
            log.exception("history search failed")

        lines = [f"Resultats pour \"{q}\"", ""]
        lines.append(f"Notes ({len(note_hits)}) :")
        for h in note_hits[:10]:
            lines.append(f"- {h['name']}")
            for s in h["snippets"][:2]:
                lines.append(f"L{s['line']}: {s['text']}")
        lines.append("")
        lines.append(f"Outils ({len(tool_hits)}) :")
        for t in tool_hits[:20]:
            lines.append(f"- {t.name} ({t.category})")
        lines.append("")
        lines.append(f"Historique commandes ({len(hist_hits)}) :")
        for h in list(hist_hits)[:10]:
            lines.append(f"- {h.command}")

        info_box(self, f"Recherche : {q}", "\n".join(lines))

    # ==============================================================
    # About / Misc
    # ==============================================================

    def _on_about(self) -> None:
        info_box(self, "OSCP Toolkit",
                 "OSCP Toolkit v1.0.0\n\n"
                 "Centralisateur offline pour la préparation et le passage de l'OSCP.\n\n"
                 "Stack : Python 3 + PyQt5\n"
                 "Toutes les données restent locales.\n\n"
                 "[!] Metasploit : 1 usage autorisé sur l'examen (hors AD).\n"
                 "[!] Aucune automatisation de recherche de flags.")

    def prompt_manual_ip(self) -> None:
        text, ok = QInputDialog.getText(
            self, "IP attaquante manuelle",
            "Forcer l'IP (ex: 10.10.14.5) - vide pour auto-détection :")
        if ok:
            self._network.set_manual_ip(text.strip() or None)

    # ==============================================================
    # Layout / session
    # ==============================================================

    def _apply_layout_from_config(self) -> None:
        """Applique la geometrie depuis layout.json.

        Robustesse : un layout.json corrompu peut faire apparaitre des docks
        detaches a des coords hors-ecran (typique sur WSLg apres un freeze
        de l'app). On wrappe restoreState dans des verifications + on offre
        un mode "safe boot" via la variable OSCP_SAFE=1.
        """
        # Mode safe boot : OSCP_SAFE=1 python3 main.py
        # -> ignore completement le layout sauvegarde
        if os.environ.get("OSCP_SAFE", "").lower() in ("1", "true", "yes"):
            log.info("OSCP_SAFE=1 -> skipping layout restore")
            self._apply_default_geometry()
            return

        try:
            # use_cache=False : si on vient de supprimer layout.json (reset),
            # le cache du ConfigManager doit etre re-lu depuis disque.
            layout = self._cfg.load("layout", use_cache=False)
        except Exception:
            log.exception("Cannot load layout.json -- using defaults")
            self._apply_default_geometry()
            return
        win = layout.get("window", {})
        w = int(win.get("width", 1600))
        h = int(win.get("height", 900))

        # Sanity sur la taille : refuse les valeurs aberrantes (ex: 0x0,
        # taille negative, taille gigantesque qui depasse l'ecran).
        if w < 400 or h < 300 or w > 8000 or h > 6000:
            log.warning("Layout width/height aberrants (%dx%d) -- defaults", w, h)
            self._apply_default_geometry()
            return

        self.resize(w, h)

        # Position : si sauvegardee on l'utilise mais avec sanity check,
        # sinon on centre sur l'ecran primaire.
        x = win.get("x")
        y = win.get("y")
        if x is not None and y is not None and self._is_position_on_screen(int(x), int(y), w, h):
            self.move(int(x), int(y))
        else:
            self._center_on_primary_screen(w, h)

        if win.get("maximized", True):
            self.showMaximized()

        # Etat Qt (toolbars / docks) si precedemment sauve
        state_b64 = win.get("qt_state", "")
        if state_b64:
            try:
                import base64
                ok = self.restoreState(QByteArray(base64.b64decode(state_b64)))
                if not ok:
                    log.warning("restoreState retourne False -- layout ignore")
                    return
                # Sanity post-restore : si un dock flottant est positionne
                # hors-ecran, on annule tout et on reset.
                self._sanitize_floating_docks()
            except Exception:
                log.exception("Cannot restoreState -- ignored")

    def _apply_default_geometry(self) -> None:
        """Geometrie par defaut : 1600x900 centree sur l'ecran primaire."""
        w, h = 1600, 900
        self.resize(w, h)
        self._center_on_primary_screen(w, h)

    def _center_on_primary_screen(self, w: int, h: int) -> None:
        """Centre la fenetre sur l'ecran primaire (le plus grand par defaut).

        Evite que la fenetre apparaisse a cheval sur deux ecrans en
        environnement multi-moniteur (probleme typique apres un crash
        ou si layout.json contenait des coordonnees inter-ecrans).
        """
        try:
            screen = QApplication.primaryScreen()
            if screen is None:
                return
            geo = screen.availableGeometry()
            x = geo.x() + (geo.width() - w) // 2
            y = geo.y() + (geo.height() - h) // 2
            self.move(max(geo.x(), x), max(geo.y(), y))
        except Exception:
            log.exception("Cannot center on primary screen")

    def _is_position_on_screen(self, x: int, y: int, w: int, h: int) -> bool:
        """Verifie qu'au moins 50% de la fenetre est sur un ecran.

        Refuse explicitement les positions qui seraient a cheval entre
        deux ecrans (la fenetre devient inaccessible -- typiquement
        apparaissant entre deux moniteurs).
        """
        try:
            from PyQt5.QtCore import QRect
            screens = QApplication.screens()
            if not screens:
                return False
            wnd_rect = QRect(x, y, w, h)
            wnd_area = w * h
            for s in screens:
                geo = s.availableGeometry()
                inter = geo.intersected(wnd_rect)
                inter_area = inter.width() * inter.height()
                if inter_area >= wnd_area * 0.5:
                    return True
            return False
        except Exception:
            return False

    def _sanitize_floating_docks(self) -> None:
        """Verifie qu'aucun dock floating n'est positionne hors-ecran.

        Sur WSLg, un layout.json corrompu peut retrouver un dock detache a
        des coords aberrantes (negatif, ou tres lointain) -- la fenetre
        devient un fantome qui se mele aux autres apps. On detecte et on
        re-attache au layout principal.
        """
        try:
            screens = QApplication.screens()
            screen_rects = [s.geometry() for s in screens]
        except Exception:
            return
        if not screen_rects:
            return

        all_docks = [
            self._dock_tools, self._dock_scope, self._dock_notes,
            self._dock_creds, self._dock_docs, self._dock_clip,
            self._dock_history, self._dock_targets, self._dock_wordlists,
        ]
        if hasattr(self, "_dock_fs"):
            all_docks.append(self._dock_fs)

        for dock in all_docks:
            if not dock.isFloating():
                continue
            geom = dock.geometry()
            # Verifie que le dock est au moins partiellement sur un ecran
            on_screen = any(s.intersects(geom) for s in screen_rects)
            if not on_screen:
                log.warning(
                    "Dock '%s' floating hors-ecran (%s) -- re-ancrage",
                    dock.objectName(), geom,
                )
                dock.setFloating(False)
                # Si il avait ete masque par defaut, on le remasque
                if dock in (self._dock_docs, self._dock_clip, self._dock_history,
                            self._dock_targets, self._dock_wordlists,
                            getattr(self, "_dock_fs", None)):
                    dock.hide()

    def _persist_layout(self) -> None:
        try:
            layout = self._cfg.load("layout", use_cache=False)
        except Exception:
            layout = {"window": {}}
        import base64
        win = layout.setdefault("window", {})
        # Position de la fenetre (frame compris) -- necessaire pour eviter
        # qu'elle reapparaisse a cheval entre deux ecrans en multi-moniteur.
        # On sauve uniquement si pas maximisee (sinon les coords ne veulent
        # rien dire car Qt restaure d'apres le state).
        if not self.isMaximized():
            pos = self.pos()
            win["x"] = pos.x()
            win["y"] = pos.y()
            win["width"] = self.width()
            win["height"] = self.height()
        win["maximized"] = self.isMaximized()
        win["qt_state"] = base64.b64encode(bytes(self.saveState())).decode("ascii")
        try:
            self._cfg.save("layout", layout)
        except Exception:
            log.exception("Cannot persist layout")

    # ---------- SessionState ----------

    def _session_docks(self) -> List[QDockWidget]:
        docks = [
            self._dock_tools, self._dock_scope, self._dock_notes,
            self._dock_docs, self._dock_creds, self._dock_clip,
            self._dock_history, self._dock_targets, self._dock_wordlists,
        ]
        if hasattr(self, "_dock_fs"):
            docks.append(self._dock_fs)
        return docks

    def _restore_open_panels(self, open_panels: List[str]) -> None:
        if not open_panels:
            return
        visible = set(open_panels)
        for dock in self._session_docks():
            dock.setVisible(dock.objectName() in visible)

    def serialize_state(self) -> SessionState:
        """Rend un SessionState pour SessionManager.save()."""
        terms: List[TerminalSession] = []
        # On parcourt TOUS les onglets (range(0, count)) au lieu de skip
        # l'index 0. Le filtre isinstance(w, TerminalTab) suffit pour ne pas
        # serialiser le widget welcome (qui n'est pas un TerminalTab).
        # Ancien code : range(1, count) skippait le tab 0 -> si welcome avait
        # ete remplace par un terminal reel, ce terminal etait perdu au save.
        for i in range(self._tabs.count()):
            w = self._tabs.widget(i)
            if isinstance(w, TerminalTab):
                terms.append(TerminalSession(
                    title=self._tabs.tabText(i),
                    command="",        # on ne sauvegarde pas la commande live
                    cwd="",
                    category=getattr(w, "_category", "default"),
                    tool_name="",
                ))
        notes: List[NoteSession] = []
        for n in self._notes.all():
            notes.append(NoteSession(path=str(n.path), cursor_pos=0))
        active = self._notes.active()
        return SessionState(
            workspace="Default",
            terminals=terms,
            notes=notes,
            active_note=active.name if active else None,
            active_tab_index=self._tabs.currentIndex(),
            open_panels=[
                d.objectName() for d in self._session_docks() if d.isVisible()
            ],
        )

    def restore_session(self) -> None:
        """Restore la dernière session (si autorisé par l'utilisateur)."""
        state = self._session.load()
        if state is None:
            return
        # Restore des notes : ouvrir la note active
        if state.active_note:
            note = self._notes.get(state.active_note)
            if note:
                self._notes.set_active(note.name)
        self._restore_open_panels(state.open_panels)
        # Restore des terminaux : on NE relance PAS automatiquement les commandes
        # (sécurité : on ne veut pas relancer un scan à l'insu de l'user).
        # On recrée des shells vides avec le bon titre.
        for t in state.terminals:
            self.spawn_terminal(title=t.title or "Terminal", category=t.category)

        # Restore l'onglet actif (clamp pour pas crasher si l'index a change)
        if state.active_tab_index >= 0:
            idx = min(state.active_tab_index, self._tabs.count() - 1)
            if idx >= 0:
                self._tabs.setCurrentIndex(idx)

        log.info("Session restored : %d terminals, %d notes, active_tab=%d",
                 len(state.terminals), len(state.notes), state.active_tab_index)

    # ==============================================================
    # Events
    # ==============================================================

    def closeEvent(self, event) -> None:
        """Shutdown propre."""
        # Confirmation si terminaux actifs (un nmap qui tourne, un listener,
        # un script en cours...) -- evite de tuer un travail en cours.
        try:
            active_terms = [
                w for w in self._terminals.all() if w.isRunning()
            ]
        except Exception:
            active_terms = []
        if active_terms:
            n = len(active_terms)
            from ui.dialogs import confirm
            if not confirm(
                self,
                "Terminaux actifs",
                f"{n} terminal(s) actif(s) seront termines. Fermer quand meme ?",
            ):
                event.ignore()
                return
        # Persister le layout
        try:
            self._persist_layout()
        except Exception:
            log.exception("Layout persistence failed")
        # Kill les terminaux
        try:
            self._terminals.stop_all()
        except Exception:
            log.exception("Terminal shutdown failed")
        # Stop timers
        try:
            self._network.stop()
        except Exception:
            pass
        # Shutdown les services en arriere-plan : sinon les threads/process
        # restent vivants apres la fermeture de la fenetre, parfois meme
        # apres exit() (zombies).
        try:
            self._fileservs.shutdown()
        except Exception:
            log.exception("FileServer shutdown failed")
        try:
            if hasattr(self, "_listeners"):
                self._listeners.stop_all()
        except Exception:
            log.exception("Listener shutdown failed")
        try:
            if hasattr(self, "_tunnels"):
                self._tunnels.stop_all()
        except Exception:
            log.exception("Tunnel shutdown failed")
        try:
            if hasattr(self, "_tool_setup"):
                self._tool_setup.shutdown()
        except Exception:
            log.exception("ToolSetup shutdown failed")
        try:
            self._scope.flush_pending()
        except Exception:
            log.exception("Scope flush failed")
        event.accept()
