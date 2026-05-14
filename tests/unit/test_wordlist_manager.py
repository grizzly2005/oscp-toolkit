from core.wordlist_manager import WordlistManager


def test_wordlist_manager_merges_new_default_entries(tmp_config_dir, config_manager):
    (tmp_config_dir / "defaults" / "wordlists.default.json").write_text(
        """
        {
          "wordlists": [
            {
              "name": "existing",
              "path": "/usr/share/wordlists/existing.txt",
              "category": "misc",
              "description": "",
              "size_bytes": 0,
              "lines": 0
            },
            {
              "name": "new-web",
              "path": "/usr/share/seclists/Discovery/Web-Content/list.txt",
              "category": "web-directories",
              "description": "",
              "size_bytes": 0,
              "lines": 0
            }
          ],
          "custom": []
        }
        """,
        encoding="utf-8",
    )
    (tmp_config_dir / "wordlists.json").write_text(
        """
        {
          "wordlists": [
            {
              "name": "existing",
              "path": "/usr/share/wordlists/existing.txt",
              "category": "misc",
              "description": "",
              "size_bytes": 0,
              "lines": 0
            }
          ],
          "custom": []
        }
        """,
        encoding="utf-8",
    )

    manager = WordlistManager(config_manager, custom_dir=tmp_config_dir / "custom")
    paths = {entry.path for entry in manager.all()}

    assert "/usr/share/wordlists/existing.txt" in paths
    assert "/usr/share/seclists/Discovery/Web-Content/list.txt" in paths


def test_wordlist_manager_adds_common_opt_seclists_entries(tmp_config_dir, config_manager):
    (tmp_config_dir / "defaults" / "wordlists.default.json").write_text(
        '{"wordlists": [], "custom": []}',
        encoding="utf-8",
    )
    (tmp_config_dir / "wordlists.json").write_text(
        '{"wordlists": [], "custom": []}',
        encoding="utf-8",
    )

    manager = WordlistManager(config_manager, custom_dir=tmp_config_dir / "custom")
    paths = {entry.path for entry in manager.all()}

    assert "/opt/SecLists/Discovery/Web-Content/common.txt" in paths
    assert "/opt/SecLists/Discovery/DNS/subdomains-top1million-5000.txt" in paths
    assert (
        "/opt/SecLists/Passwords/Common-Credentials/xato-net-10-million-passwords-1000.txt"
        in paths
    )
