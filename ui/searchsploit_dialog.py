"""SearchSploit batch dialog."""

from __future__ import annotations

from typing import Dict, List, Optional

from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QColor, QFont
from PyQt5.QtWidgets import (
    QApplication, QCheckBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel,
    QPlainTextEdit, QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
    QWidget,
)

from core.searchsploit_runner import (
    SearchSploitResult, build_commands, build_queries, parse_service_line,
    run_searchsploit,
)
from .widgets import frozen_updates


class _SearchSploitWorker(QThread):
    result_ready = pyqtSignal(object)
    message = pyqtSignal(str)

    def __init__(
        self,
        lines: List[str],
        include_broad: bool = False,
        stop_on_hit: bool = True,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._lines = lines
        self._include_broad = include_broad
        self._stop_on_hit = stop_on_hit

    def run(self) -> None:
        for line in self._lines:
            if self.isInterruptionRequested():
                break
            service = parse_service_line(line)
            if service is None:
                self.message.emit(f"Non parse: {line}")
                continue

            queries = build_queries(service, include_broad=self._include_broad)
            for query in queries:
                if self.isInterruptionRequested():
                    break
                try:
                    result = run_searchsploit(query)
                except Exception as exc:
                    result = SearchSploitResult(
                        source=line,
                        query=query,
                        command=f"searchsploit {query}",
                        output="",
                        has_results=False,
                        returncode=1,
                        error=str(exc),
                    )
                result.source = line
                self.result_ready.emit(result)
                if result.returncode == 127 and result.error:
                    return
                if result.has_results and self._stop_on_hit:
                    break


class SearchSploitDialog(QDialog):
    _detached_workers: List[_SearchSploitWorker] = []

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("SearchSploit batch")
        self.setMinimumSize(900, 680)
        self._worker: Optional[_SearchSploitWorker] = None
        self._results: Dict[int, SearchSploitResult] = {}

        root = QVBoxLayout(self)

        root.addWidget(QLabel("Services / versions :"))
        self._input = QPlainTextEdit()
        self._input.setFont(QFont("Monospace", 10))
        self._input.setPlaceholderText(
            "vsftpd 3.0.3\n"
            "OpenSSH 7.6p1\n"
            "Exim smtpd 4.90_1\n"
            "21/tcp open ftp vsftpd 3.0.3"
        )
        root.addWidget(self._input, 1)

        options = QHBoxLayout()
        self._stop_on_hit = QCheckBox("Stop au premier hit par service")
        self._stop_on_hit.setChecked(True)
        options.addWidget(self._stop_on_hit)
        self._include_broad = QCheckBox("Fallback produit seul")
        self._include_broad.setToolTip("Ajoute une recherche large si aucune version ne matche")
        options.addWidget(self._include_broad)
        options.addStretch(1)
        root.addLayout(options)

        controls = QHBoxLayout()
        self._run_btn = QPushButton("Lancer SearchSploit")
        self._run_btn.clicked.connect(self._on_run)
        controls.addWidget(self._run_btn)

        self._stop_btn = QPushButton("Stop")
        self._stop_btn.setEnabled(False)
        self._stop_btn.clicked.connect(self._on_stop)
        controls.addWidget(self._stop_btn)

        self._copy_btn = QPushButton("Copier commandes")
        self._copy_btn.clicked.connect(self._copy_commands)
        controls.addWidget(self._copy_btn)
        controls.addStretch(1)
        root.addLayout(controls)

        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["Service", "Query", "Hit", "Code"])
        self._tree.setRootIsDecorated(False)
        self._tree.setAlternatingRowColors(True)
        self._tree.setUniformRowHeights(True)
        self._tree.currentItemChanged.connect(self._on_selection_changed)
        root.addWidget(self._tree, 2)

        root.addWidget(QLabel("Sortie :"))
        self._output = QPlainTextEdit()
        self._output.setReadOnly(True)
        self._output.setFont(QFont("Monospace", 10))
        root.addWidget(self._output, 2)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _lines(self) -> List[str]:
        return [
            line.strip()
            for line in self._input.toPlainText().splitlines()
            if line.strip()
        ]

    def _on_run(self) -> None:
        lines = self._lines()
        if not lines:
            self._output.setPlainText("# Rien a verifier.")
            return
        with frozen_updates(self._tree):
            self._tree.clear()
            self._results.clear()
        self._output.clear()
        self._run_btn.setEnabled(False)
        self._stop_btn.setEnabled(True)

        self._worker = _SearchSploitWorker(
            lines,
            include_broad=self._include_broad.isChecked(),
            stop_on_hit=self._stop_on_hit.isChecked(),
            parent=self,
        )
        self._worker.result_ready.connect(self._add_result)
        self._worker.message.connect(self._add_message)
        self._worker.finished.connect(self._on_finished)
        self._worker.start()

    def _add_result(self, result: SearchSploitResult) -> None:
        row = self._tree.topLevelItemCount()
        item = QTreeWidgetItem([
            result.source,
            result.query,
            "oui" if result.has_results else "non",
            str(result.returncode),
        ])
        color = QColor("#81c784") if result.has_results else QColor("#ffb74d")
        if result.error:
            color = QColor("#ef5350")
        for col in range(4):
            item.setForeground(col, color)
        item.setData(0, Qt.UserRole, row)
        self._results[row] = result
        self._tree.addTopLevelItem(item)
        if result.has_results or result.error:
            self._tree.setCurrentItem(item)

    def _add_message(self, message: str) -> None:
        row = self._tree.topLevelItemCount()
        item = QTreeWidgetItem([message, "-", "-", "-"])
        item.setForeground(0, QColor("#ef5350"))
        item.setData(0, Qt.UserRole, row)
        self._results[row] = SearchSploitResult(
            source=message,
            query="",
            command="",
            output=message,
            has_results=False,
            returncode=1,
            error=message,
        )
        self._tree.addTopLevelItem(item)

    def _on_selection_changed(self, current: QTreeWidgetItem, _previous) -> None:
        if current is None:
            return
        row = current.data(0, Qt.UserRole)
        result = self._results.get(row)
        if result is None:
            return
        if result.error:
            self._output.setPlainText(f"$ {result.command}\n\n{result.error}")
        else:
            self._output.setPlainText(f"$ {result.command}\n\n{result.output}")

    def _on_finished(self) -> None:
        self._run_btn.setEnabled(True)
        self._stop_btn.setEnabled(False)
        self._worker = None
        if self._tree.topLevelItemCount() < 120:
            for col in range(4):
                self._tree.resizeColumnToContents(col)

    def _on_stop(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            self._worker.requestInterruption()
            self._output.setPlainText(self._output.toPlainText() + "\n\n# Arret demande.")

    def _copy_commands(self) -> None:
        commands = build_commands(
            self._lines(),
            include_broad=self._include_broad.isChecked(),
        )
        QApplication.clipboard().setText("\n".join(commands))

    def reject(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            worker = self._worker
            worker.requestInterruption()
            for sig, slot in [
                (worker.result_ready, self._add_result),
                (worker.message, self._add_message),
                (worker.finished, self._on_finished),
            ]:
                try:
                    sig.disconnect(slot)
                except (TypeError, RuntimeError):
                    pass
            self._worker = None
            self._detached_workers.append(worker)
            worker.finished.connect(lambda w=worker: self._forget_detached_worker(w))
            worker.finished.connect(worker.deleteLater)
        super().reject()

    @classmethod
    def _forget_detached_worker(cls, worker: _SearchSploitWorker) -> None:
        try:
            cls._detached_workers.remove(worker)
        except ValueError:
            pass
