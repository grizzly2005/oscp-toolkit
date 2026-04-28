"""App State — source de verite unique pour tout l'etat applicatif.

Remplace progressivement l'eclatement actuel en multiples JSON.
L'API expose des NAMESPACES, chacun persiste dans son propre fichier JSON
pour rester retrocompatible, mais passe par ce point central.

Avantages :
  - Un seul endroit pour voir "qui lit quoi"
  - Signal 'changed(namespace)' centralise
  - Cache unifie, invalidation cohérente
  - Permet plus tard de migrer vers SQLite sans toucher aux clients
  - Transactions simples (save_all, atomic batch)

Namespaces geres :
  - env_vars      : LHOST, LPORT, TARGET, DOMAIN, etc.
  - exam_timer    : duration, remaining, state
  - layout        : geometrie dock widgets
  - scope         : machines, subnets (delegue a ScopeManager pour la logique)
  - workspaces    : profils d'utilisation
  - ui_prefs      : split mode, theme, etc.

Les managers existants continuent a fonctionner tels quels grace a leur
dependance sur ConfigManager. Le nouveau code doit utiliser AppState.

Migration progressive :
  1. Phase 1 (ce PR) : AppState existe, wrap ConfigManager, aucun code migre
  2. Phase 2 : Les nouveaux managers utilisent AppState directement
  3. Phase 3 : Les anciens managers migrent un par un
"""
from __future__ import annotations

from typing import Any, Callable, Dict, Optional, Set

from PyQt5.QtCore import QObject, pyqtSignal

from .config_manager import ConfigManager, ConfigError
from .logger import get_logger

log = get_logger(__name__)


class AppState(QObject):
    """Source de verite unique pour l'etat applicatif."""

    # Emis quand un namespace change (apres persistence)
    namespace_changed = pyqtSignal(str)      # namespace name

    # Emis quand l'etat est completement recharge (import, reset...)
    state_reloaded = pyqtSignal()

    def __init__(self, config_manager: ConfigManager, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._cm = config_manager
        self._observers: Dict[str, Set[Callable[[Any], None]]] = {}

    # -- API principale ------------------------------------------------------

    def get(self, namespace: str, default: Optional[Any] = None) -> Any:
        """Retourne l'etat d'un namespace. Aucune mutation possible ici."""
        try:
            return self._cm.load(namespace)
        except ConfigError as exc:
            if default is not None:
                log.warning("AppState.get('%s') -> fallback: %s", namespace, exc)
                return default
            raise

    def set(self, namespace: str, data: Any) -> None:
        """Ecrit l'etat d'un namespace + emit signal."""
        self._cm.save(namespace, data)
        log.debug("AppState.set('%s')", namespace)
        self.namespace_changed.emit(namespace)
        # Notifie les observers directs. Iterer sur une COPIE car un
        # callback peut appeler unsubscribe() ou subscribe() pendant
        # son execution -> mutation set pendant iteration -> RuntimeError.
        for cb in list(self._observers.get(namespace, set())):
            try:
                cb(data)
            except Exception:
                log.exception("AppState observer failed for '%s'", namespace)

    def update(self, namespace: str, patch: Dict[str, Any]) -> None:
        """Merge patch dans l'etat d'un namespace (shallow).
        Utile quand on ne veut changer qu'une cle.
        """
        current = self.get(namespace, default={})
        if not isinstance(current, dict):
            raise ValueError(
                f"update() requires dict state for '{namespace}', got {type(current).__name__}"
            )
        current = dict(current)
        current.update(patch)
        self.set(namespace, current)

    def reset(self, namespace: str) -> Any:
        """Restaure depuis defaults/."""
        data = self._cm.reset(namespace)
        self.namespace_changed.emit(namespace)
        return data

    def invalidate_cache(self, namespace: Optional[str] = None) -> None:
        """Purge le cache ConfigManager."""
        self._cm.invalidate(namespace)

    # -- Observer pattern (en plus du signal Qt) -----------------------------

    def subscribe(self, namespace: str, callback: Callable[[Any], None]) -> None:
        """Enregistre un callback appele quand le namespace change.
        Pour les modules qui ne sont pas des QObject.
        """
        self._observers.setdefault(namespace, set()).add(callback)

    def unsubscribe(self, namespace: str, callback: Callable[[Any], None]) -> None:
        if namespace in self._observers:
            self._observers[namespace].discard(callback)

    # -- Raccourcis typés (namespaces frequents) -----------------------------

    # Env vars
    def env(self) -> Dict[str, str]:
        data = self.get("env_vars", default={"vars": {}})
        return dict(data.get("vars", {}))

    def env_get(self, key: str, default: str = "") -> str:
        return self.env().get(key, default)

    def env_set(self, key: str, value: str) -> None:
        data = self.get("env_vars", default={"vars": {}})
        if not isinstance(data.get("vars"), dict):
            data["vars"] = {}
        data["vars"][key.upper()] = value
        self.set("env_vars", data)

    # Exam timer
    def exam_timer(self) -> Dict[str, Any]:
        return self.get("exam_timer", default={
            "duration": 85500, "remaining": 85500, "state": "idle"
        })

    # UI preferences (nouveau namespace)
    def ui_prefs(self) -> Dict[str, Any]:
        return self.get("ui_prefs", default={
            "central_mode": "tabs",     # tabs / quad
            "theme": "dark",
        })

    def ui_prefs_set(self, key: str, value: Any) -> None:
        prefs = dict(self.ui_prefs())
        prefs[key] = value
        self.set("ui_prefs", prefs)
