"""Repository layer — abstraction pour la persistence.

Les repositories cachent les details de stockage (FS, JSON, SQLite...)
aux managers metier. Avantages :
  - Tests : on peut mocker le stockage
  - Changement de backend : on change juste le repo
  - Logique metier decouplee du disque

Pour l'instant, les implementations sont FS-based (JSON + PNG).
Plus tard, on pourra migrer vers SQLite sans toucher aux managers.
"""
from .base import Repository, JsonRepository
from .screenshot_repo import ScreenshotRepository

__all__ = ["Repository", "JsonRepository", "ScreenshotRepository"]
