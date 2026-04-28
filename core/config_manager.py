"""Config Manager — Atomic Write + Validation + Defaults + File Locks.

Toute la config applicative est en JSON plat. Ce module est le SEUL
point d'entrée pour lire/écrire ces fichiers. Garanties :

- Écriture atomique : .tmp -> os.replace() (atomique sur Linux/NTFS)
- Lecture safe : si fichier absent/corrompu -> restore depuis defaults/
- File lock (fcntl.flock) : sérialise les accès concurrents
- Validation par schéma : fonction de validation par fichier
- Cache en mémoire : évite les relectures disque répétées
- Invalidation : sur write, le cache du fichier est purgé

Layout attendu :
    config/
        tools.json
        links.json
        ...
        defaults/
            tools.default.json
            links.default.json
            ...
"""

from __future__ import annotations

import json
import os
import shutil
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from .logger import get_logger

try:  # file locks : Unix-only (fcntl)
    import fcntl  # type: ignore
    _HAS_FCNTL = True
except ImportError:  # pragma: no cover - Windows fallback
    _HAS_FCNTL = False

log = get_logger(__name__)


class ConfigError(Exception):
    """Erreur de config non récupérable (même avec defaults)."""


class ConfigManager:
    """Gestionnaire de configs JSON avec defaults, atomic writes, cache.

    Pas de singleton global imposé : l'instance unique est créée dans
    main.py et injectée dans les modules qui en ont besoin.
    """

    def __init__(
        self,
        config_dir: Path | str = "config",
        defaults_dir: Path | str | None = None,
    ) -> None:
        self.config_dir = Path(config_dir)
        self.defaults_dir = (
            Path(defaults_dir) if defaults_dir else self.config_dir / "defaults"
        )
        self.config_dir.mkdir(parents=True, exist_ok=True)

        self._cache: Dict[str, Any] = {}
        self._cache_lock = threading.RLock()
        self._file_locks: Dict[str, threading.Lock] = {}
        self._file_locks_guard = threading.Lock()

        # Validateurs optionnels par nom de fichier (sans l'extension)
        self._validators: Dict[str, Callable[[Any], bool]] = {}

        # Migrations : {namespace: {(from, to): fn}}
        self._migrations: Dict[str, Dict[tuple, Callable[[Any], Any]]] = {}
        self._target_versions: Dict[str, int] = {}

        self.register_default_validators()

    # --------------------------------------------------------------
    # Validateurs
    # --------------------------------------------------------------

    def register_validator(self, name: str, fn: Callable[[Any], bool]) -> None:
        self._validators[name] = fn

    def register_default_validators(self) -> None:
        self.register_validator("tools", _validate_tools)
        self.register_validator("links", _validate_links)
        self.register_validator("workspaces", _validate_workspaces)
        self.register_validator("shortcuts", _validate_shortcuts)
        self.register_validator("layout", _validate_layout)
        self.register_validator("scope", _validate_scope)
        self.register_validator("credentials", _validate_credentials)
        self.register_validator("clipboard_pins", _validate_clipboard)
        self.register_validator("wordlists", _validate_wordlists)
        self.register_validator("revshells", _validate_revshells)

    # --------------------------------------------------------------
    # Migrations de schema
    # --------------------------------------------------------------

    def _load_versions(self) -> dict:
        """Charge config/version.json. Retourne {} si absent."""
        vpath = self.config_dir / "version.json"
        if not vpath.exists():
            return {}
        try:
            import json
            return json.loads(vpath.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save_versions(self, versions: dict) -> None:
        import json
        vpath = self.config_dir / "version.json"
        try:
            vpath.write_text(json.dumps(versions, indent=2), encoding="utf-8")
        except OSError as exc:
            log.warning("Cannot persist config version: %s", exc)

    def register_migration(
        self,
        name: str,
        from_version: int,
        to_version: int,
        fn: Callable[[Any], Any],
    ) -> None:
        """Enregistre une migration.

        fn(old_data) -> new_data. Les migrations sont appliquees dans l'ordre
        croissant jusqu'a atteindre target_version(name).

        Exemple :
          cm.register_migration("tools", 1, 2, migrate_tools_v1_to_v2)
        """
        self._migrations.setdefault(name, {})[(from_version, to_version)] = fn

    def target_version(self, name: str) -> int:
        """Version cible pour un namespace. Override si besoin."""
        return self._target_versions.get(name, 1)

    def set_target_version(self, name: str, version: int) -> None:
        self._target_versions[name] = version

    def _maybe_migrate(self, name: str, data: Any) -> Any:
        """Applique les migrations enregistrees si la version disk est < target."""
        versions = self._load_versions()
        current = versions.get(name, 1)
        target = self.target_version(name)
        if current >= target:
            return data

        chain = self._migrations.get(name, {})
        log.info("Migrating '%s' from v%d to v%d", name, current, target)
        while current < target:
            step = chain.get((current, current + 1))
            if step is None:
                log.warning("No migration step %d->%d for '%s', stopping",
                             current, current + 1, name)
                break
            try:
                data = step(data)
                current += 1
            except Exception:
                log.exception("Migration %d->%d for '%s' failed, aborting",
                               current, current + 1, name)
                break

        # Persiste la nouvelle version
        versions[name] = current
        self._save_versions(versions)
        # Ecrit aussi le data migre
        try:
            self._safe_write(self._path(name), data, name)
        except Exception:
            log.exception("Post-migration save failed for '%s'", name)
        return data


    # --------------------------------------------------------------
    # API publique
    # --------------------------------------------------------------

    def load(self, name: str, use_cache: bool = True) -> Any:
        """Charge `config/<name>.json`.

        - Si absent/corrompu : restore depuis defaults, retourne defaults.
        - Si defaults absent aussi : lève ConfigError.
        - Si validation échoue : restore defaults, warning, retourne defaults.
        """
        with self._cache_lock:
            if use_cache and name in self._cache:
                return self._cache[name]

        path = self._path(name)
        default_path = self._default_path(name)

        data = self._safe_read(path, default_path, name)
        # Applique les migrations enregistrees si necessaire
        data = self._maybe_migrate(name, data)

        validator = self._validators.get(name)
        if validator is not None:
            try:
                ok = validator(data)
            except Exception as exc:  # validateur buggué : on loggue mais on continue
                log.warning("Validator %s crashed: %s - keeping data as-is", name, exc)
                ok = True
            if not ok:
                log.warning(
                    "Validation failed for %s -- backing up + restoring from defaults",
                    name,
                )
                self._backup_corrupted(path, name, reason="validation_failed")
                data = self._restore_from_default(path, default_path, name)

        with self._cache_lock:
            self._cache[name] = data
        return data

    def save(self, name: str, data: Any) -> None:
        """Sauvegarde atomiquement `config/<name>.json`."""
        validator = self._validators.get(name)
        if validator is not None:
            if not validator(data):
                raise ConfigError(
                    f"Refuse to save invalid data for '{name}' "
                    f"(validation failed)"
                )

        path = self._path(name)
        self._safe_write(path, data, name)

        with self._cache_lock:
            self._cache[name] = data

    def reset(self, name: str) -> Any:
        """Force la restauration depuis defaults et retourne le résultat."""
        path = self._path(name)
        default_path = self._default_path(name)
        data = self._restore_from_default(path, default_path, name)
        with self._cache_lock:
            self._cache[name] = data
        return data

    def invalidate(self, name: Optional[str] = None) -> None:
        """Purge le cache (un fichier ou tout)."""
        with self._cache_lock:
            if name is None:
                self._cache.clear()
            else:
                self._cache.pop(name, None)

    def check_writable(self) -> bool:
        """Vérifie qu'on peut écrire dans config_dir. Pour le pre-flight."""
        probe = self.config_dir / ".write_probe"
        try:
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            return True
        except OSError as exc:
            log.error("Config directory not writable (%s): %s", self.config_dir, exc)
            return False

    # --------------------------------------------------------------
    # Internals
    # --------------------------------------------------------------

    def _path(self, name: str) -> Path:
        return self.config_dir / f"{name}.json"

    def _default_path(self, name: str) -> Path:
        return self.defaults_dir / f"{name}.default.json"

    def _get_lock(self, name: str) -> threading.Lock:
        with self._file_locks_guard:
            lock = self._file_locks.get(name)
            if lock is None:
                lock = threading.Lock()
                self._file_locks[name] = lock
            return lock

    def _safe_read(self, path: Path, default_path: Path, name: str) -> Any:
        lock = self._get_lock(name)
        with lock:
            if not path.exists():
                return self._restore_from_default(path, default_path, name)

            try:
                with open(path, "r", encoding="utf-8") as f:
                    if _HAS_FCNTL:
                        try:
                            fcntl.flock(f.fileno(), fcntl.LOCK_SH)
                        except OSError:
                            pass
                    raw = f.read()
                if not raw.strip():
                    log.warning("Config file '%s' is empty -- backing up + restoring defaults", name)
                    self._backup_corrupted(path, name, reason="empty")
                    return self._restore_from_default(path, default_path, name)
                return json.loads(raw)
            except (OSError, json.JSONDecodeError) as exc:
                log.warning(
                    "Failed to read '%s' (%s) -- backing up + restoring defaults", path, exc
                )
                self._backup_corrupted(path, name, reason=type(exc).__name__)
                return self._restore_from_default(path, default_path, name)

    def _backup_corrupted(self, path: Path, name: str, reason: str = "") -> None:
        """Renomme un fichier corrompu en `.broken_<ts>.json` au lieu de l'ecraser.

        L'utilisateur peut ainsi recuperer manuellement les donnees.
        Echec silencieux mais loggue : si on n'arrive pas a renommer,
        le restore_from_default ecrasera le fichier (comportement legacy).
        """
        if not path.exists():
            return
        ts = int(time.time())
        backup = path.with_name(f"{path.stem}.broken_{ts}{path.suffix}")
        try:
            os.replace(path, backup)
            log.warning(
                "Backed up corrupted config '%s' -> '%s' (reason: %s)",
                name, backup.name, reason or "unknown",
            )
        except OSError as exc:
            log.error(
                "Could not backup corrupted '%s' (%s); will be overwritten by defaults",
                path, exc,
            )

    def _safe_write(self, path: Path, data: Any, name: str) -> None:
        lock = self._get_lock(name)
        with lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + ".tmp")
            try:
                with open(tmp, "w", encoding="utf-8") as f:
                    if _HAS_FCNTL:
                        try:
                            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                        except OSError:
                            pass
                    json.dump(data, f, indent=2, ensure_ascii=False)
                    f.flush()
                    try:
                        os.fsync(f.fileno())
                    except OSError:
                        pass
                os.replace(tmp, path)
                log.debug("Saved config '%s' (%d bytes)", name, path.stat().st_size)
            except OSError as exc:
                log.error("Failed to write config '%s': %s", name, exc)
                try:
                    if tmp.exists():
                        tmp.unlink()
                except OSError:
                    pass
                raise ConfigError(f"Cannot write config '{name}': {exc}") from exc

    def _restore_from_default(
        self, path: Path, default_path: Path, name: str
    ) -> Any:
        if not default_path.exists():
            raise ConfigError(
                f"No default file for '{name}' (looked for {default_path}). "
                f"Application cannot bootstrap this config."
            )
        try:
            with open(default_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            raise ConfigError(
                f"Default file for '{name}' is corrupted: {exc}"
            ) from exc

        # Écrit une copie dans config/ pour que l'utilisateur puisse la modifier
        try:
            shutil.copy2(default_path, path)
            log.info("Restored '%s' from defaults", name)
        except OSError as exc:
            log.warning(
                "Could not copy default to %s (%s) - using in-memory only",
                path,
                exc,
            )
        return data


# --------------------------------------------------------------
# Validateurs
# --------------------------------------------------------------

def _is_dict(x: Any) -> bool:
    return isinstance(x, dict)


def _is_list(x: Any) -> bool:
    return isinstance(x, list)


def _validate_tools(data: Any) -> bool:
    if not _is_dict(data) or not _is_list(data.get("tools", None)):
        return False
    required = {"name", "category", "path"}
    for t in data["tools"]:
        if not _is_dict(t):
            return False
        if not required.issubset(t.keys()):
            return False
    return True


def _validate_links(data: Any) -> bool:
    if not _is_dict(data) or not _is_list(data.get("links", None)):
        return False
    for item in data["links"]:
        if not _is_dict(item) or "name" not in item or "url" not in item:
            return False
    return True


def _validate_workspaces(data: Any) -> bool:
    if not _is_dict(data):
        return False
    if not _is_list(data.get("workspaces", None)):
        return False
    if "active" not in data:
        return False
    for w in data["workspaces"]:
        if not _is_dict(w) or "name" not in w:
            return False
    return True


def _validate_shortcuts(data: Any) -> bool:
    return _is_dict(data) and _is_dict(data.get("shortcuts", None))


def _validate_layout(data: Any) -> bool:
    return _is_dict(data) and _is_dict(data.get("window", None))


def _validate_scope(data: Any) -> bool:
    return (
        _is_dict(data)
        and _is_list(data.get("subnets", None))
        and _is_list(data.get("machines", None))
    )


def _validate_credentials(data: Any) -> bool:
    return _is_dict(data) and _is_list(data.get("credentials", None))


def _validate_clipboard(data: Any) -> bool:
    return (
        _is_dict(data)
        and _is_list(data.get("items", None))
        and _is_list(data.get("pins", None))
    )


def _validate_wordlists(data: Any) -> bool:
    return _is_dict(data) and _is_list(data.get("wordlists", None))


def _validate_revshells(data: Any) -> bool:
    return _is_dict(data) and _is_dict(data.get("shells", None))
