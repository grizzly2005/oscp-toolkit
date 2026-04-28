"""Proof Tracker — quand une machine devient 'rooted', rappel proof.

Responsabilité minimaliste : écoute `ScopeManager.machine_status_changed`,
quand status -> "rooted", émet `proof_reminder` avec la machine.
L'UI affiche alors un dialog proposant de :
- coller le contenu de proof.txt
- coller le contenu de user.txt
- cocher la checklist proof (screenshot, ipconfig, whoami)
- attacher des screenshots

Tout est stocké dans Machine.proof (ProofState).
"""

from __future__ import annotations

from typing import Optional

from PyQt5.QtCore import QObject, pyqtSignal

from .logger import get_logger
from .scope_manager import Machine, ScopeManager

log = get_logger(__name__)


class ProofTracker(QObject):
    proof_reminder = pyqtSignal(object)          # Machine
    proof_updated = pyqtSignal(object)           # Machine

    def __init__(self, scope_manager: ScopeManager, parent=None):
        super().__init__(parent)
        self._scope = scope_manager
        self._scope.machine_status_changed.connect(self._on_status_changed)

    # ----------------------------------------------------------

    def _on_status_changed(self, machine_id: str, new_status: str) -> None:
        if new_status != "rooted":
            return
        m = self._scope.machine(machine_id)
        if m is None:
            return
        log.info("Machine %s rooted - triggering proof reminder", m.hostname or m.ip)
        self.proof_reminder.emit(m)

    # ---------- update proof ----------

    def set_user_flag(self, machine_id: str, flag: str) -> None:
        m = self._scope.machine(machine_id)
        if m is None:
            return
        m.proof.user_flag = flag.strip()
        self._scope.update_machine(m)
        self.proof_updated.emit(m)

    def set_proof_flag(self, machine_id: str, flag: str) -> None:
        m = self._scope.machine(machine_id)
        if m is None:
            return
        m.proof.proof_flag = flag.strip()
        self._scope.update_machine(m)
        self.proof_updated.emit(m)

    def set_checklist(self, machine_id: str, key: str, value: bool) -> None:
        m = self._scope.machine(machine_id)
        if m is None:
            return
        m.proof.checklist[key] = bool(value)
        self._scope.update_machine(m)
        self.proof_updated.emit(m)

    def add_screenshot(self, machine_id: str, path: str) -> None:
        m = self._scope.machine(machine_id)
        if m is None:
            return
        if path not in m.proof.screenshots:
            m.proof.screenshots.append(path)
            self._scope.update_machine(m)
            self.proof_updated.emit(m)

    def is_complete(self, machine_id: str) -> bool:
        m = self._scope.machine(machine_id)
        if m is None:
            return False
        return m.proof.is_complete()
