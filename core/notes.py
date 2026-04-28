"""Notes manager — une note Markdown par machine.

Responsabilités :
- CRUD notes (fichiers .md dans data/notes/<workspace>/)
- Template auto à la création
- Auto-save toutes les 30 secondes (coordonné avec l'UI)
- Insertion de screenshots (compression PNG -> WebP si Pillow dispo)
- Append commandes lancées / output sélectionné
- Recherche globale
- Import .md externe
- Export .md/.pdf (PDF via pandoc si dispo, sinon via Qt QTextDocument)
"""

from __future__ import annotations

import base64
import os
import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional

from PyQt5.QtCore import QObject, pyqtSignal

from .logger import get_logger

log = get_logger(__name__)


NOTE_TEMPLATE = """# {machine_name}

## Info
- IP: {ip}
- OS: 
- Difficulty: 
- Date: {date}

## Enumeration Checklist
- [ ] Nmap TCP full
- [ ] Nmap UDP top 100
- [ ] SMB anonymous
- [ ] HTTP directories
- [ ] DNS zone transfer
- [ ] SNMP community strings
- [ ] Default credentials

## Enumeration
### Ports
### Services

## Exploitation

## Privilege Escalation

## Credentials Found
<!-- auto-sync depuis Credential Vault -->

## Flags
- user.txt: 
- proof.txt: 

## Proof Checklist
- [ ] Screenshot proof.txt
- [ ] ipconfig/ifconfig visible
- [ ] whoami visible

## Commandes utilisées

## Screenshots
"""


@dataclass
class Note:
    name: str
    path: Path
    content: str = ""


class NotesManager(QObject):
    note_created = pyqtSignal(object)
    note_changed = pyqtSignal(object)
    note_deleted = pyqtSignal(str)
    active_note_changed = pyqtSignal(object)      # Optional[Note]

    def __init__(
        self,
        notes_dir: Path | str = "data/notes/default",
        screenshots_dir: Path | str = "data/screenshots",
        parent: Optional[QObject] = None,
    ):
        super().__init__(parent)
        self.notes_dir = Path(notes_dir)
        self.screenshots_dir = Path(screenshots_dir)
        self.notes_dir.mkdir(parents=True, exist_ok=True)
        self.screenshots_dir.mkdir(parents=True, exist_ok=True)

        self._notes: Dict[str, Note] = {}
        self._active: Optional[str] = None
        self._refresh_from_disk()

    # ----------------------------------------------------------

    def set_notes_dir(self, path: Path | str) -> None:
        """Change de dossier (ex : switch de workspace)."""
        self.notes_dir = Path(path)
        self.notes_dir.mkdir(parents=True, exist_ok=True)
        self._notes.clear()
        self._active = None
        self._refresh_from_disk()

    def _refresh_from_disk(self) -> None:
        for p in sorted(self.notes_dir.glob("*.md")):
            try:
                content = p.read_text(encoding="utf-8")
            except OSError as exc:
                log.warning("Cannot read %s: %s", p, exc)
                continue
            n = Note(name=p.stem, path=p, content=content)
            self._notes[n.name] = n

    # ---------- lecture ----------

    def all(self) -> List[Note]:
        return sorted(self._notes.values(), key=lambda n: n.name.lower())

    def get(self, name: str) -> Optional[Note]:
        return self._notes.get(name)

    def active(self) -> Optional[Note]:
        return self._notes.get(self._active) if self._active else None

    def set_active(self, name: Optional[str]) -> None:
        if name and name not in self._notes:
            log.warning("Tried to activate unknown note %s", name)
            return
        self._active = name
        self.active_note_changed.emit(self.active())

    # ---------- création ----------

    def create(
        self,
        name: str,
        ip: str = "",
        content: Optional[str] = None,
    ) -> Note:
        if name in self._notes:
            raise ValueError(f"Note '{name}' already exists")
        path = self.notes_dir / f"{self._safe_filename(name)}.md"
        if content is None:
            content = NOTE_TEMPLATE.format(
                machine_name=name,
                ip=ip,
                date=time.strftime("%Y-%m-%d"),
            )
        path.write_text(content, encoding="utf-8")
        n = Note(name=name, path=path, content=content)
        self._notes[name] = n
        self.note_created.emit(n)
        log.info("Created note %s", path)
        return n

    def save(self, name: str, content: str) -> None:
        n = self._notes.get(name)
        if n is None:
            raise KeyError(name)
        n.content = content
        tmp = n.path.with_suffix(".md.tmp")
        try:
            tmp.write_text(content, encoding="utf-8")
            os.replace(tmp, n.path)
        except OSError as exc:
            log.error("Save note %s failed: %s", name, exc)
            raise
        self.note_changed.emit(n)

    def delete(self, name: str) -> None:
        n = self._notes.pop(name, None)
        if n is None:
            return
        try:
            n.path.unlink()
        except OSError as exc:
            log.warning("Delete note %s: %s", name, exc)
        if self._active == name:
            self._active = None
        self.note_deleted.emit(name)

    def rename(self, old: str, new: str) -> Note:
        if new in self._notes:
            raise ValueError(f"'{new}' already exists")
        new_path = self.notes_dir / f"{self._safe_filename(new)}.md"
        # Le dict est verifie, mais le fichier sur disque peut exister
        # sans etre dans _notes (l'utilisateur a edite manuellement
        # le dossier). On refuse pour ne pas ecraser silencieusement.
        if new_path.exists():
            raise ValueError(f"File already exists at {new_path}")
        n = self._notes.pop(old)
        n.path.replace(new_path)
        n.path = new_path
        n.name = new
        self._notes[new] = n
        if self._active == old:
            self._active = new
        self.note_changed.emit(n)
        return n

    def import_file(self, source: Path | str) -> Note:
        source = Path(source)
        if not source.exists():
            raise FileNotFoundError(source)
        name = source.stem
        target = self.notes_dir / f"{self._safe_filename(name)}.md"
        if target.exists():
            name = f"{name}_{int(time.time())}"
            target = self.notes_dir / f"{self._safe_filename(name)}.md"
        shutil.copy2(source, target)
        content = target.read_text(encoding="utf-8", errors="replace")
        n = Note(name=name, path=target, content=content)
        self._notes[name] = n
        self.note_created.emit(n)
        return n

    # ---------- contenu ----------

    def append_command(self, name: str, command: str, output: str = "") -> None:
        """Injecte une commande (et optionnellement son output) à la fin."""
        n = self._notes.get(name)
        if n is None:
            return
        ts = time.strftime("%H:%M:%S")
        block = f"\n```bash\n# {ts}\n{command}\n```\n"
        if output:
            # tronquer à 5000 chars pour pas polluer la note
            snippet = output[:5000]
            if len(output) > 5000:
                snippet += "\n[...tronqué...]"
            block += f"\n```\n{snippet}\n```\n"
        self.save(name, n.content + block)

    def append_section(self, name: str, heading: str, body: str) -> None:
        n = self._notes.get(name)
        if n is None:
            return
        self.save(name, n.content + f"\n## {heading}\n{body}\n")

    def insert_screenshot(
        self,
        note_name: str,
        image_bytes: bytes,
        caption: str = "",
        suffix: str = ".png",
    ) -> Path:
        """Sauvegarde l'image (avec compression si dispo) et l'insère."""
        path = self._save_screenshot(note_name, image_bytes, suffix)
        # Insertion markdown relative
        rel = os.path.relpath(path, self.notes_dir)
        n = self._notes.get(note_name)
        if n is None:
            raise KeyError(note_name)
        md_block = f"\n![{caption}]({rel})\n"
        self.save(note_name, n.content + md_block)
        return path

    def _save_screenshot(
        self,
        note_name: str,
        image_bytes: bytes,
        suffix: str,
    ) -> Path:
        safe = self._safe_filename(note_name)
        target_dir = self.screenshots_dir / safe
        target_dir.mkdir(parents=True, exist_ok=True)
        ts = int(time.time() * 1000)
        fname = f"shot_{ts}{suffix}"
        target = target_dir / fname

        # Tentative compression WebP avec Pillow
        try:
            from PIL import Image  # type: ignore
            import io
            img = Image.open(io.BytesIO(image_bytes))
            webp = target.with_suffix(".webp")
            img.save(webp, "WEBP", quality=85, method=4)
            log.debug("Screenshot compressed: %s (%d -> %d bytes)",
                      webp, len(image_bytes), webp.stat().st_size)
            return webp
        except ImportError:
            log.debug("Pillow absent, saving raw screenshot")
        except Exception as exc:  # si l'image est corrompue
            log.warning("Pillow compression failed (%s), falling back to raw", exc)

        target.write_bytes(image_bytes)
        return target

    # ---------- recherche ----------

    def search(self, query: str) -> List[Dict]:
        """Recherche plein-texte dans toutes les notes."""
        q = query.lower().strip()
        results = []
        if not q:
            return results
        for n in self._notes.values():
            lowered = n.content.lower()
            if q not in lowered and q not in n.name.lower():
                continue
            # Capture quelques snippets de contexte
            snippets = []
            for line_no, line in enumerate(n.content.splitlines(), start=1):
                if q in line.lower():
                    snippets.append({"line": line_no, "text": line.strip()[:200]})
                    if len(snippets) >= 5:
                        break
            results.append({
                "name": n.name,
                "path": str(n.path),
                "snippets": snippets,
            })
        return results

    # ---------- export ----------

    def export_markdown(self, name: str, destination: Path | str) -> Path:
        n = self._notes.get(name)
        if n is None:
            raise KeyError(name)
        dst = Path(destination)
        shutil.copy2(n.path, dst)
        return dst

    def export_pdf(self, name: str, destination: Path | str) -> Path:
        """Export PDF via pandoc si dispo, sinon via Qt QTextDocument."""
        n = self._notes.get(name)
        if n is None:
            raise KeyError(name)
        dst = Path(destination)

        if shutil.which("pandoc"):
            import subprocess
            res = subprocess.run(
                ["pandoc", str(n.path), "-o", str(dst),
                 "--standalone", "--pdf-engine=xelatex"],
                capture_output=True, text=True, timeout=60,
            )
            if res.returncode == 0:
                log.info("PDF export via pandoc: %s", dst)
                return dst
            log.warning("pandoc failed: %s", res.stderr.strip())

        # Fallback Qt
        try:
            from PyQt5.QtGui import QTextDocument
            from PyQt5.QtPrintSupport import QPrinter
            import markdown  # type: ignore
        except ImportError:
            raise RuntimeError(
                "PDF export requires pandoc OR the 'markdown' python package"
            )
        html = markdown.markdown(n.content, extensions=["fenced_code", "tables"])
        doc = QTextDocument()
        doc.setHtml(html)
        printer = QPrinter(QPrinter.HighResolution)
        printer.setOutputFormat(QPrinter.PdfFormat)
        printer.setOutputFileName(str(dst))
        doc.print_(printer)
        log.info("PDF export via Qt: %s", dst)
        return dst

    # ---------- utils ----------

    @staticmethod
    def _safe_filename(name: str) -> str:
        # autorise lettres/chiffres/_-. et espaces (convertis en _)
        clean = re.sub(r"[^\w\-. ]+", "_", name)
        clean = clean.replace(" ", "_").strip("_.")
        return clean or "note"
