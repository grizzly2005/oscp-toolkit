"""Tests pour core.repositories.screenshot_repo."""
import pytest
from pathlib import Path

from core.repositories.screenshot_repo import ScreenshotRepository, ScreenshotMeta


def test_register_and_get(tmp_path):
    repo = ScreenshotRepository(tmp_path)
    fake_png = tmp_path / "proof_10.0.0.1_123.png"
    fake_png.write_bytes(b"\x89PNG\r\n\x1a\n")  # header PNG minimal
    key = repo.register(fake_png, ScreenshotMeta(
        path="", ip="10.0.0.1", tag="proof"
    ))
    meta = repo.get(key)
    assert meta is not None
    assert meta.ip == "10.0.0.1"
    assert meta.tag == "proof"
    assert meta.timestamp > 0


def test_by_ip(tmp_path):
    repo = ScreenshotRepository(tmp_path)
    for i, ip in enumerate(["1.1.1.1", "1.1.1.1", "2.2.2.2"]):
        p = tmp_path / f"s{i}.png"
        p.write_bytes(b"x")
        repo.register(p, ScreenshotMeta(path="", ip=ip))
    assert len(repo.by_ip("1.1.1.1")) == 2
    assert len(repo.by_ip("2.2.2.2")) == 1
    assert len(repo.by_ip("9.9.9.9")) == 0


def test_delete_without_file(tmp_path):
    repo = ScreenshotRepository(tmp_path)
    p = tmp_path / "a.png"
    p.write_bytes(b"x")
    key = repo.register(p, ScreenshotMeta(path="", ip="1.1.1.1"))
    assert repo.delete(key) is True
    assert repo.get(key) is None
    assert p.exists()   # fichier garde par defaut


def test_delete_with_file(tmp_path):
    repo = ScreenshotRepository(tmp_path)
    p = tmp_path / "b.png"
    p.write_bytes(b"x")
    key = repo.register(p, ScreenshotMeta(path="", ip="1.1.1.1"))
    assert repo.delete(key, remove_file=True) is True
    assert not p.exists()


def test_persistence(tmp_path):
    repo1 = ScreenshotRepository(tmp_path)
    p = tmp_path / "c.png"
    p.write_bytes(b"x")
    repo1.register(p, ScreenshotMeta(path="", ip="3.3.3.3", machine="ws01"))

    # Recharge
    repo2 = ScreenshotRepository(tmp_path)
    metas = repo2.all()
    assert len(metas) == 1
    assert metas[0].machine == "ws01"
