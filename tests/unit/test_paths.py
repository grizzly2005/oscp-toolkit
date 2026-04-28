"""Tests pour core.paths."""
from core.paths import ToolkitPaths


def test_ensure_all(tmp_path):
    paths = ToolkitPaths(project_root=tmp_path)
    paths.ensure_all()
    assert paths.notes_dir.is_dir()
    assert paths.screenshots_dir.is_dir()
    assert paths.runtime_dir.is_dir()
    assert paths.cache_dir.is_dir()


def test_migrate_legacy_notes_before_ensure(tmp_path):
    """Migration pure (sans ensure_all avant)."""
    old = tmp_path / "data" / "notes" / "default"
    old.mkdir(parents=True)
    (old / "test.md").write_text("hello")

    paths = ToolkitPaths(project_root=tmp_path)
    moved = paths.migrate_legacy_layout()
    assert moved >= 1

    new_path = tmp_path / "data" / "user" / "notes" / "default" / "test.md"
    assert new_path.exists()


def test_migrate_after_ensure_works(tmp_path):
    """Meme si ensure_all() a cree des dossiers cibles vides,
    la migration fusionne correctement."""
    paths = ToolkitPaths(project_root=tmp_path)
    paths.ensure_all()    # cree data/user/notes/ (vide)

    old = tmp_path / "data" / "notes" / "default"
    old.mkdir(parents=True)
    (old / "test.md").write_text("hello")

    moved = paths.migrate_legacy_layout()
    assert moved >= 1
    assert (tmp_path / "data" / "user" / "notes" / "default" / "test.md").exists()


def test_migrate_idempotent(tmp_path):
    paths = ToolkitPaths(project_root=tmp_path)
    paths.ensure_all()
    m1 = paths.migrate_legacy_layout()
    m2 = paths.migrate_legacy_layout()
    assert m2 == 0


def test_migrate_conflict_skips(tmp_path):
    """Si un fichier existe deja au target, on skip sans erreur."""
    paths = ToolkitPaths(project_root=tmp_path)
    paths.ensure_all()

    # Nouveau fichier dans la cible
    (paths.notes_dir / "existing.md").write_text("new")

    # Meme nom dans l'ancien
    old = tmp_path / "data" / "notes"
    old.mkdir(exist_ok=True)
    (old / "existing.md").write_text("old")
    (old / "other.md").write_text("other")

    paths.migrate_legacy_layout()
    # Le nouveau est preserve
    assert (paths.notes_dir / "existing.md").read_text() == "new"
    # L'autre est migre
    assert (paths.notes_dir / "other.md").exists()
