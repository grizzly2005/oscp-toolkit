"""Terminal Tab v2.0 — ANSI + CR + scrollback infini + Ctrl+F + push.

Ameliorations vs v1.2 :
  - Scrollback infini (setMaximumBlockCount(0)) + dump auto si > 100k lignes
  - FindBar (Ctrl+F) comme dans un navigateur
  - Push selection vers note (clic droit)
  - Push selection vers autre terminal via signal (batch 6)
"""
from __future__ import annotations

import re
from collections import deque
from pathlib import Path
from typing import Deque, List, Optional

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import (
    QColor, QFont, QKeySequence, QPalette,
    QTextCharFormat, QTextCursor,
)
from PyQt5.QtWidgets import (
    QAction, QHBoxLayout, QLabel, QLineEdit, QMenu, QPlainTextEdit,
    QPushButton, QShortcut, QVBoxLayout, QWidget,
)

from core.terminal import TerminalWorker
from .widgets import SafeButton
from .find_bar import FindBar

# -- ANSI parser -------------------------------------------------------------

_ANSI_RE = re.compile(r'\x1B\[([0-9;?]*?)([A-Za-z])')

# Sequences a supprimer SILENCIEUSEMENT du flux (pas affichees, pas parsees) :
#   - OSC  \x1b]...\x07 ou \x1b]...\x1b\\  (titre fenetre, hyperlinks, etc.)
#   - DCS  \x1bP...\x1b\\
#   - APC  \x1b_...\x1b\\
#   - PM   \x1b^...\x1b\\
# Le bracketed-paste (\x1b[?2004h / \x1b[?2004l) est gere par _ANSI_RE
# (accepte le ? grace au [0-9;?]) puis ignore par le dispatcher.
_STRIP_OSC_RE  = re.compile(r'\x1B\][^\x07\x1B]*(?:\x07|\x1B\\)')
_STRIP_SEQ_RE  = re.compile(r'\x1B[PX_^][^\x1B]*\x1B\\')
# Ignorer aussi les caracteres de controle non-imprimables SAUF \n, \r, \t, \b
_STRIP_CTRL_RE = re.compile(r'[\x00-\x08\x0B\x0C\x0E-\x1A\x1C-\x1F]')

# Fallback : OSC sans terminator (cas rare ou le BEL/ST a ete strippe par erreur,
# ou quand bash envoie une OSC sur plusieurs chunks et que le tail buffer rate
# la jonction). On stripe agressivement jusqu'au prochain \n ou \r, qui
# delimitent toujours un OSC orphelin dans une PS1 typique. Sans ca, l'user
# voit "]0;user@host:dir" dans son prompt a chaque commande.
_STRIP_OSC_ORPHAN_RE = re.compile(r'\x1B\][^\n\r]*')
# Encore plus agressif : un ] suivi de "0;" ou "2;" ou "7;" + texte SANS
# terminator. Pour eviter les faux positifs sur du code legitime (ex:
# "array[0]; var=5" ou "func()][0;1]"), on exige que le contenu apres ];
# RESSEMBLE A UN TITRE DE TERMINAL : majoritairement texte/path, pas de
# point-virgule de C/JS/Python. Heuristique : on accepte alpha/digit/space/
# slash/tilde/colon/dot/dash/underscore/at sign uniquement.
_STRIP_BARE_OSC_RE = re.compile(
    r'\][027];[\w /~:.\-@\t]{0,200}(?:\x07)?'
)

_FG_MAP: dict = {
    30: '#555753', 31: '#cc0000', 32: '#4e9a06', 33: '#c4a000',
    34: '#3465a4', 35: '#75507b', 36: '#06989a', 37: '#d3d7cf',
    90: '#888a85', 91: '#ef2929', 92: '#8ae234', 93: '#fce94f',
    94: '#729fcf', 95: '#ad7fa8', 96: '#34e2e2', 97: '#eeeeec',
}
_BG_MAP: dict = {
    40: '#2e2e2e', 41: '#5c0000', 42: '#1e3a00', 43: '#3e3000',
    44: '#1a2c4e', 45: '#3a1a4e', 46: '#003e42', 47: '#4a4a4a',
    100: '#444', 101: '#8b0000', 102: '#1a6b00', 103: '#7a6000',
    104: '#2a5090', 105: '#6a3090', 106: '#007a7a', 107: '#6e6e6e',
}
_DEFAULT_FG = QColor('#d4d4d4')


class _AnsiState:
    def __init__(self) -> None:
        self._fg: Optional[QColor] = None
        self._bg: Optional[QColor] = None
        self._bold: bool = False

    def reset(self) -> None:
        self._fg = None
        self._bg = None
        self._bold = False

    def apply_sgr(self, params: str) -> None:
        codes_raw = params.split(';') if params else ['0']
        i = 0
        while i < len(codes_raw):
            try:
                c = int(codes_raw[i]) if codes_raw[i] else 0
            except ValueError:
                i += 1
                continue
            if c == 0:
                self.reset()
            elif c == 1:
                self._bold = True
            elif c in (2, 22):
                self._bold = False
            elif 30 <= c <= 37:
                key = (c + 60) if self._bold else c
                self._fg = QColor(_FG_MAP.get(key, _FG_MAP[c]))
            elif 90 <= c <= 97:
                self._fg = QColor(_FG_MAP.get(c, '#d4d4d4'))
            elif c == 39:
                self._fg = None
            elif 40 <= c <= 47 or 100 <= c <= 107:
                self._bg = QColor(_BG_MAP.get(c, '#1e1e1e'))
            elif c == 49:
                self._bg = None
            elif c in (38, 48):
                try:
                    mode = int(codes_raw[i + 1]) if i + 1 < len(codes_raw) else -1
                    if mode == 5:
                        i += 2
                    elif mode == 2:
                        i += 4
                except (ValueError, IndexError):
                    pass
            i += 1

    def make_format(self) -> QTextCharFormat:
        fmt = QTextCharFormat()
        fmt.setForeground(self._fg if self._fg is not None else _DEFAULT_FG)
        if self._bg is not None:
            fmt.setBackground(self._bg)
        if self._bold:
            fmt.setFontWeight(700)
        return fmt


def strip_ansi(text: str) -> str:
    text = _STRIP_OSC_RE.sub('', text)
    text = _STRIP_SEQ_RE.sub('', text)
    text = _STRIP_OSC_ORPHAN_RE.sub('', text)
    text = _STRIP_CTRL_RE.sub('', text)
    text = _STRIP_BARE_OSC_RE.sub('', text)
    return _ANSI_RE.sub('', text)


def _compact_progress_updates(text: str) -> str:
    """Keep only the latest carriage-return update per rendered line.

    Fuzzers often repaint progress with thousands of ``\r`` updates. Keeping
    every repaint makes the UI do a lot of invisible work, so in fast-render
    mode we preserve the final state for each line and all newline-delimited
    findings.
    """
    if '\r' not in text:
        return text
    out: List[str] = []
    for part in text.split('\n'):
        out.append(part.split('\r')[-1])
    return '\n'.join(out)


# -- TerminalTab -------------------------------------------------------------

# Seuil de dump auto legacy. Le widget est maintenant limite en blocks pour
# eviter que QPlainTextEdit ne fige sur des fuzzers tres verbeux.
_DUMP_THRESHOLD_LINES = 50_000
_KEEP_AFTER_DUMP = 25_000

_DISPLAY_MAX_BLOCKS = 12_000
_FLUSH_INTERVAL_MS = 80
_FLUSH_CONTINUE_MS = 12
_FLUSH_MAX_BYTES = 64 * 1024
_FAST_RENDER_THRESHOLD = 48 * 1024
_FAST_BADGE_HIDE_MS = 1200


class TerminalTab(QWidget):
    command_entered  = pyqtSignal(str)
    closed_requested = pyqtSignal()
    output_selected  = pyqtSignal(str)
    output_send_to_terminal = pyqtSignal(str)   # batch 6 : push vers autre terminal

    def __init__(
        self,
        worker: TerminalWorker,
        title: str = "terminal",
        category: str = "default",
        color: Optional[str] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._worker   = worker
        self._title    = title
        self._category = category
        self._history:     List[str] = []
        self._history_idx: int = 0

        self._pending: Deque[str] = deque()
        self._pending_bytes: int = 0
        self._batch_timer = QTimer(self)
        self._batch_timer.setInterval(_FLUSH_INTERVAL_MS)
        self._batch_timer.timeout.connect(self._flush_pending)
        self._fast_badge_timer = QTimer(self)
        self._fast_badge_timer.setSingleShot(True)
        self._fast_badge_timer.timeout.connect(self._hide_fast_badge)

        self._ansi = _AnsiState()
        # Buffer pour les sequences ESC incompletes (split entre flushs)
        self._tail_buffer: str = ''

        # Dump path (utilisable quand on atteint le seuil)
        self._dump_path: Optional[Path] = None
        self._dump_file = None
        self._total_lines_written: int = 0

        # Layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # View
        self._view = QPlainTextEdit()
        self._view.setReadOnly(True)
        self._view.setUndoRedoEnabled(False)
        self._view.setLineWrapMode(QPlainTextEdit.NoWrap)

        font = QFont("Monospace")
        font.setStyleHint(QFont.TypeWriter)
        font.setPointSize(10)
        self._view.setFont(font)

        pal = self._view.palette()
        pal.setColor(QPalette.Base, QColor("#1e1e1e"))
        pal.setColor(QPalette.Text, _DEFAULT_FG)
        self._view.setPalette(pal)

        # Un scrollback illimite fige vite Qt avec ffuf/gobuster/feroxbuster.
        # Le process garde son output complet cote dumps, ici on garde surtout
        # une vue fluide des dernieres lignes utiles.
        self._view.setMaximumBlockCount(_DISPLAY_MAX_BLOCKS)
        self._view.setContextMenuPolicy(Qt.CustomContextMenu)
        self._view.customContextMenuRequested.connect(self._on_context_menu)
        layout.addWidget(self._view, 1)

        # FindBar (Ctrl+F)
        self._find_bar = FindBar(self._view, self)
        layout.addWidget(self._find_bar)

        # Input row
        input_row = QHBoxLayout()
        input_row.setContentsMargins(4, 2, 4, 4)
        input_row.setSpacing(4)

        self._prompt_label = QPushButton("$")
        self._prompt_label.setFlat(True)
        self._prompt_label.setFixedSize(22, 22)
        self._prompt_label.setFocusPolicy(Qt.NoFocus)
        input_row.addWidget(self._prompt_label)

        self._input = QLineEdit()
        self._input.setFont(font)
        self._input.setPlaceholderText("Commande...")
        self._input.returnPressed.connect(self._on_enter)
        self._input.installEventFilter(self)
        input_row.addWidget(self._input, 1)

        self._fast_badge = QLabel("FAST")
        self._fast_badge.setObjectName("terminalFastBadge")
        self._fast_badge.setAlignment(Qt.AlignCenter)
        self._fast_badge.setToolTip("Rendu rapide actif: sortie compacte pour garder l'UI fluide")
        self._fast_badge.setFixedSize(42, 22)
        self._fast_badge.hide()
        input_row.addWidget(self._fast_badge)

        self._send_btn = SafeButton("send")
        self._send_btn.setFixedSize(48, 26)
        self._send_btn.setFocusPolicy(Qt.NoFocus)
        self._send_btn.setToolTip("Envoyer (Entree)")
        self._send_btn.clicked.connect(self._on_enter)
        input_row.addWidget(self._send_btn)

        layout.addLayout(input_row)

        # Shortcuts
        QShortcut(QKeySequence("Ctrl+Shift+C"), self, self._copy_selection)
        QShortcut(QKeySequence("Ctrl+Shift+V"), self, self._paste_into_input)
        QShortcut(QKeySequence("Ctrl+L"),       self, self._clear_view)
        QShortcut(QKeySequence("Ctrl+F"),       self, self._find_bar.show_and_focus)

        # Worker signals
        worker.output_received.connect(self._on_output_raw)
        worker.finished_signal.connect(self._on_finished)
        worker.error_occurred.connect(self._on_error)
        worker.unresponsive.connect(self._on_unresponsive)
        worker.alive_again.connect(self._on_alive_again)

        if color:
            self._prompt_label.setStyleSheet(
                f"QPushButton {{ color: {color}; font-weight: bold; }}"
            )

    # -- Public --------------------------------------------------------------

    def title(self) -> str:
        return self._title

    def worker(self) -> TerminalWorker:
        return self._worker

    def focus_input(self) -> None:
        self._input.setFocus(Qt.OtherFocusReason)

    def send_text(self, text: str) -> None:
        """Envoie du texte au PTY (sans \\n automatique)."""
        self._worker.send_input(text)
        if hasattr(self._worker, 'notify_input_sent'):
            self._worker.notify_input_sent()

    def send_command(self, cmd: str) -> None:
        """Envoie une commande complete (ajoute \\n et notifie watchdog)."""
        self._worker.send_input(cmd.rstrip("\n") + "\n")
        if hasattr(self._worker, 'notify_input_sent'):
            self._worker.notify_input_sent()

    def dump_path(self) -> Optional[Path]:
        return self._dump_path

    # -- Input filter --------------------------------------------------------

    def eventFilter(self, obj, event):
        if obj is self._input and event.type() == event.KeyPress:
            key = event.key()
            if key == Qt.Key_Up:
                self._navigate_history(-1)
                return True
            if key == Qt.Key_Down:
                self._navigate_history(1)
                return True
            if key == Qt.Key_C and (event.modifiers() & Qt.ControlModifier):
                self._worker.send_input("\x03")
                self._input.clear()
                return True
        return super().eventFilter(obj, event)

    def _navigate_history(self, delta: int) -> None:
        if not self._history:
            return
        self._history_idx = max(0, min(len(self._history), self._history_idx + delta))
        if self._history_idx == len(self._history):
            self._input.clear()
        else:
            self._input.setText(self._history[self._history_idx])

    def _on_enter(self) -> None:
        text = self._input.text()
        self._input.clear()
        if not text.strip():
            self._worker.send_input("\n")
            return
        self._history.append(text)
        self._history_idx = len(self._history)
        self.command_entered.emit(text)
        if hasattr(self._worker, 'notify_input_sent'):
            self._worker.notify_input_sent()
        self._worker.send_input(text + "\n")

    # -- Output pipeline -----------------------------------------------------

    def _on_output_raw(self, chunk: str) -> None:
        self._pending.append(chunk)
        self._pending_bytes += len(chunk)
        if not self._batch_timer.isActive():
            self._batch_timer.start()

    def _flush_pending(self) -> None:
        if not self._pending:
            self._batch_timer.stop()
            return

        accumulated = self._take_pending_slice(_FLUSH_MAX_BYTES)
        self._render(accumulated)

        if self._pending:
            QTimer.singleShot(_FLUSH_CONTINUE_MS, self._flush_pending)
        else:
            self._batch_timer.stop()

        if self._view.blockCount() > _DUMP_THRESHOLD_LINES:
            self._dump_and_trim()

    def _take_pending_slice(self, max_bytes: int) -> str:
        chunks: List[str] = []
        taken = 0
        while self._pending and taken < max_bytes:
            chunk = self._pending.popleft()
            remaining = max_bytes - taken
            if len(chunk) > remaining:
                chunks.append(chunk[:remaining])
                self._pending.appendleft(chunk[remaining:])
                self._pending_bytes -= remaining
                break
            chunks.append(chunk)
            taken += len(chunk)
            self._pending_bytes -= len(chunk)
        return "".join(chunks)

    def _render(self, raw: str) -> None:
        raw = raw.replace('\r\n', '\n')
        fast_mode = len(raw) >= _FAST_RENDER_THRESHOLD or self._pending_bytes >= _FLUSH_MAX_BYTES
        if fast_mode:
            self._show_fast_badge()
            segments = [(self._ansi.make_format(), _compact_progress_updates(strip_ansi(raw)))]
        else:
            segments = self._parse_ansi(raw)
        if not segments:
            return

        scrollbar = self._view.verticalScrollBar()
        should_autoscroll = scrollbar.value() >= scrollbar.maximum() - 2
        cursor = self._view.textCursor()
        cursor.movePosition(QTextCursor.End)
        self._view.setUpdatesEnabled(False)
        try:
            for fmt, text in segments:
                if not text:
                    continue
                self._insert_with_cr(cursor, fmt, text)
        finally:
            self._view.setUpdatesEnabled(True)

        if should_autoscroll:
            self._view.setTextCursor(cursor)
            self._view.ensureCursorVisible()

    def _show_fast_badge(self) -> None:
        if not self._fast_badge.isVisible():
            self._fast_badge.show()
        self._fast_badge_timer.start(_FAST_BADGE_HIDE_MS)

    def _hide_fast_badge(self) -> None:
        if hasattr(self, "_fast_badge"):
            self._fast_badge.hide()

    def _parse_ansi(self, text: str) -> List[tuple]:
        # Etape 0 : prepend le buffer de la derniere fois (sequence coupee)
        if self._tail_buffer:
            text = self._tail_buffer + text
            self._tail_buffer = ''

        # Etape 0.5 : detecter si le chunk finit AU MILIEU d'une sequence ESC
        # (frequent avec les batches qui flushent toutes les 40ms).
        # Si oui, on stocke le tail incomplete pour le prochain flush.
        last_esc = text.rfind('\x1b')
        if last_esc >= 0:
            tail = text[last_esc:]
            incomplete = False
            if len(tail) == 1:
                incomplete = True       # juste \x1b seul
            elif tail[1] == '[':
                # CSI doit finir par une lettre [A-Za-z]
                if not _ANSI_RE.search(tail):
                    incomplete = True
            elif tail[1] == ']':
                # OSC doit contenir \x07 ou \x1b\\
                if '\x07' not in tail[2:] and '\x1b\\' not in tail[2:]:
                    incomplete = True
            elif tail[1] in 'PX_^':
                # DCS/APC/PM doit contenir \x1b\\
                if '\x1b\\' not in tail[2:]:
                    incomplete = True
            # Sequences a 2 caracteres (\x1b lettre) : completes implicitement.

            if incomplete:
                self._tail_buffer = tail
                text = text[:last_esc]

        # Nettoyage : on vire les sequences qui ne sont pas des SGR
        text = _STRIP_OSC_RE.sub('', text)
        text = _STRIP_SEQ_RE.sub('', text)
        # Fallback : OSC sans terminator (BEL ou ST manquant). Streame de
        # bash en plusieurs chunks, le BEL peut etre perdu dans la jointure.
        text = _STRIP_OSC_ORPHAN_RE.sub('', text)
        text = _STRIP_CTRL_RE.sub('', text)
        # Fallback ultime : OSC orpheline ayant perdu son ESC initial.
        text = _STRIP_BARE_OSC_RE.sub('', text)

        result: List[tuple] = []
        last = 0
        for m in _ANSI_RE.finditer(text):
            if m.start() > last:
                result.append((self._ansi.make_format(), text[last:m.start()]))
            params = m.group(1)
            cmd = m.group(2)
            # SGR (couleur / style)
            if cmd == 'm':
                # '?' non-SGR dans les parametres -> ignore (ex: [?2004h mal lu)
                if '?' not in params:
                    self._ansi.apply_sgr(params)
            # Tous les autres codes (curseur, effacement, DEC private, etc.)
            # sont ignores : on ne simule pas un vrai terminal, on affiche juste
            # le contenu textuel.
            last = m.end()
        if last < len(text):
            result.append((self._ansi.make_format(), text[last:]))
        return result

    def _insert_with_cr(
        self,
        cursor: QTextCursor,
        fmt: QTextCharFormat,
        text: str,
    ) -> None:
        cr_parts = text.split('\r')
        if cr_parts[0]:
            cursor.insertText(cr_parts[0], fmt)
        for part in cr_parts[1:]:
            if not part:
                cursor.movePosition(QTextCursor.StartOfLine)
                continue
            cursor.movePosition(QTextCursor.StartOfLine)
            nl_idx = part.find('\n')
            if nl_idx == -1:
                overwrite_part = part
                tail = ''
            else:
                overwrite_part = part[:nl_idx]
                tail = part[nl_idx:]
            if overwrite_part:
                # Calcul combien de caracteres on peut overwrite sur la ligne
                # courante sans deborder (pour respecter le \r style progress bar)
                block = cursor.block()
                block_pos = block.position()
                line_len = block.length() - 1   # -1 pour le newline implicite
                cursor_offset_in_line = cursor.position() - block_pos
                avail = max(0, line_len - cursor_offset_in_line)
                # On selectionne min(len(overwrite_part), avail) caracteres a remplacer
                to_select = min(len(overwrite_part), avail)
                if to_select > 0:
                    cursor.movePosition(
                        QTextCursor.NextCharacter,
                        QTextCursor.KeepAnchor,
                        to_select,
                    )
                cursor.insertText(overwrite_part, fmt)
            if tail:
                cursor.movePosition(QTextCursor.EndOfLine)
                cursor.insertText(tail, fmt)

    # -- Dump disque --------------------------------------------------------

    def _dump_and_trim(self) -> None:
        """Quand le buffer explose, ecrit le debut dans un fichier et garde la fin."""
        if self._dump_path is None:
            import tempfile, time
            dump_dir = Path(tempfile.gettempdir()) / "oscp_terminal_dumps"
            dump_dir.mkdir(exist_ok=True)
            ts = int(time.time())
            safe_title = re.sub(r'[^a-zA-Z0-9_-]', '_', self._title)
            self._dump_path = dump_dir / f"{safe_title}_{ts}.log"

        # Recupere toutes les lignes et ecrit au dump
        doc = self._view.document()
        total = doc.blockCount()
        to_dump = total - _KEEP_AFTER_DUMP
        if to_dump <= 0:
            return

        lines = []
        cursor = QTextCursor(doc)
        cursor.movePosition(QTextCursor.Start)
        for _ in range(to_dump):
            cursor.select(QTextCursor.LineUnderCursor)
            lines.append(cursor.selectedText().replace("\u2029", "\n"))
            cursor.movePosition(QTextCursor.Down)

        try:
            with self._dump_path.open("a", encoding="utf-8") as fp:
                fp.write("\n".join(lines))
                fp.write("\n")
            self._total_lines_written += to_dump
        except OSError:
            return

        # Supprime les lignes dumpees du widget
        cursor = QTextCursor(doc)
        cursor.movePosition(QTextCursor.Start)
        cursor.movePosition(QTextCursor.Down, QTextCursor.KeepAnchor, to_dump)
        cursor.removeSelectedText()

        # Message discret dans la vue
        self._append_system(
            f"\n[Scrollback : {to_dump} lignes dumpees -> {self._dump_path}]\n"
        )

    # -- Worker signals ------------------------------------------------------

    def _on_finished(self, code: int) -> None:
        self._flush_pending()
        self._append_system(f"\n[process termine, exit={code}]\n")
        self._send_btn.setEnabled(False)
        self._input.setPlaceholderText("(termine)")
        self._input.setReadOnly(True)

    def _on_error(self, msg: str) -> None:
        self._append_system(f"\n[ERREUR: {msg}]\n")

    def _on_unresponsive(self) -> None:
        self._append_system("\n[!] pas de reponse depuis 10s\n")

    def _on_alive_again(self) -> None:
        self._append_system("\n[OK] process a repris\n")

    def _append_system(self, text: str) -> None:
        cursor = self._view.textCursor()
        cursor.movePosition(QTextCursor.End)
        fmt = QTextCharFormat()
        fmt.setForeground(QColor("#ffb74d"))
        cursor.insertText(text, fmt)
        self._view.setTextCursor(cursor)
        self._view.ensureCursorVisible()

    # -- Actions -------------------------------------------------------------

    def _copy_selection(self) -> None:
        cursor = self._view.textCursor()
        if cursor.hasSelection():
            text = cursor.selectedText().replace("\u2029", "\n")
            from PyQt5.QtWidgets import QApplication
            QApplication.clipboard().setText(text)

    def _paste_into_input(self) -> None:
        from PyQt5.QtWidgets import QApplication
        self._input.insert(QApplication.clipboard().text())

    def _clear_view(self) -> None:
        self._view.clear()
        self._ansi.reset()

    def _on_context_menu(self, point) -> None:
        menu: QMenu = self._view.createStandardContextMenu()
        menu.addSeparator()
        sel = self._view.textCursor().selectedText().replace("\u2029", "\n")

        act_push_note = QAction("Pousser la selection -> note active", self)
        act_push_note.setEnabled(bool(sel))
        act_push_note.triggered.connect(lambda: self.output_selected.emit(sel))
        menu.addAction(act_push_note)

        act_push_term = QAction("Envoyer la selection -> autre terminal", self)
        act_push_term.setEnabled(bool(sel))
        act_push_term.triggered.connect(lambda: self.output_send_to_terminal.emit(sel))
        menu.addAction(act_push_term)

        act_find = QAction("Rechercher (Ctrl+F)", self)
        act_find.triggered.connect(self._find_bar.show_and_focus)
        menu.addAction(act_find)

        act_clear = QAction("Nettoyer (Ctrl+L)", self)
        act_clear.triggered.connect(self._clear_view)
        menu.addAction(act_clear)

        if self._dump_path and self._dump_path.exists():
            act_open_dump = QAction(f"Ouvrir le dump ({self._dump_path.name})", self)
            act_open_dump.triggered.connect(self._open_dump_file)
            menu.addAction(act_open_dump)

        menu.exec_(self._view.viewport().mapToGlobal(point))

    def _open_dump_file(self) -> None:
        if not self._dump_path:
            return
        # Subprocess detache pour eviter pollution stderr par chromium-snap & co
        import subprocess
        import shutil as _sh
        for opener in ("xdg-open", "open"):
            path = _sh.which(opener)
            if path:
                try:
                    subprocess.Popen(
                        [path, str(self._dump_path)],
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        start_new_session=True,
                        close_fds=True,
                    )
                    return
                except OSError:
                    continue
        from PyQt5.QtCore import QUrl
        from PyQt5.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._dump_path)))

    def disconnect_worker_signals(self) -> None:
        """Deconnecte tous les signaux du worker avant la destruction du tab.

        Le TerminalWorker (QThread) survit a la destruction du tab :
        il peut emettre output_received / finished_signal / etc. apres
        que le widget ait ete deleteLater(). Sans deconnexion, les slots
        accederaient a des objets C++ detruits -> RuntimeError.

        A appeler depuis _close_tab dans main_window AVANT deleteLater().
        """
        for sig, slot in [
            (self._worker.output_received,  self._on_output_raw),
            (self._worker.finished_signal,  self._on_finished),
            (self._worker.error_occurred,   self._on_error),
            (self._worker.unresponsive,     self._on_unresponsive),
            (self._worker.alive_again,      self._on_alive_again),
        ]:
            try:
                sig.disconnect(slot)
            except (TypeError, RuntimeError):
                pass
        # Stop le batch timer pour eviter qu'il fire avec un view detruit
        try:
            self._batch_timer.stop()
        except (RuntimeError, AttributeError):
            pass
        try:
            self._fast_badge_timer.stop()
        except (RuntimeError, AttributeError):
            pass

    def closeEvent(self, event) -> None:
        """Hook standard si le tab est ferme par voie 'close window'."""
        self.disconnect_worker_signals()
        super().closeEvent(event)
