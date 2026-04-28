"""core - business logic layer of OSCP Toolkit.

Ce package contient toute la logique métier. Aucun import Qt ici sauf
pour les modules qui émettent des signaux (QObject). La règle :
- `core/*` : logique pure, isolée, testable.
- `ui/*` : affichage uniquement, consomme core via signaux/slots.
"""

__version__ = "1.0.0"
