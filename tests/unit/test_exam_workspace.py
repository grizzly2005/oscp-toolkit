from core.exam_workspace import ExamWorkspaceManager


def test_exam_workspace_creates_expected_structure(tmp_config_dir, config_manager, tmp_path):
    (tmp_config_dir / "defaults" / "exam_workspace.default.json").write_text(
        '{"root_path": ""}',
        encoding="utf-8",
    )
    root = tmp_path / "oscp-exam"

    workspace = ExamWorkspaceManager(config_manager)
    workspace.set_root(root)

    for rel in [
        "scans/nmap",
        "scans/udp",
        "scans/services",
        "loot/interesting_files",
        "exploits",
        "screenshots",
        "notes",
        "tools",
        "web",
    ]:
        assert (root / rel).is_dir()
    for rel in ["loot/creds.txt", "loot/hashes.txt", "loot/users.txt"]:
        assert (root / rel).is_file()


def test_exam_workspace_exports_shell_paths(tmp_config_dir, config_manager, tmp_path):
    (tmp_config_dir / "defaults" / "exam_workspace.default.json").write_text(
        '{"root_path": ""}',
        encoding="utf-8",
    )
    workspace = ExamWorkspaceManager(config_manager)
    workspace.set_root(tmp_path / "oscp-exam")

    exports = workspace.env_exports()

    assert exports["OSCP_NMAP"].endswith("/scans/nmap")
    assert "\\" not in exports["OSCP_NMAP"]
