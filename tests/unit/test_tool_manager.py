from core.tool_manager import ToolManager


def test_tool_manager_infers_transfer_assets_from_legacy_description(
    tmp_config_dir,
    config_manager,
):
    (tmp_config_dir / "defaults" / "tools.default.json").write_text(
        """
        {
          "tools": [
            {
              "name": "linpeas",
              "category": "PrivEsc",
              "path": "$BIN_LIN/privesc/linpeas.sh",
              "description": "Linux privesc enum (Transfer)",
              "templates": []
            }
          ]
        }
        """,
        encoding="utf-8",
    )

    tm = ToolManager(config_manager)

    assert tm.get("linpeas").transfer_asset is True


def test_tool_manager_merges_new_default_nmap_templates(
    tmp_config_dir,
    config_manager,
):
    defaults = tmp_config_dir / "defaults" / "tools.default.json"
    defaults.write_text(
        """
        {
          "tools": [
            {
              "name": "nmap",
              "category": "Enumeration",
              "path": "/usr/bin/nmap",
              "templates": [
                "nmap -sC -sV {{IP}}",
                "nmap -A {{IP}} -oN nmap_advanced_{{IP}}.txt {{IP}}"
              ]
            }
          ]
        }
        """,
        encoding="utf-8",
    )
    (tmp_config_dir / "tools.json").write_text(
        """
        {
          "tools": [
            {
              "name": "nmap",
              "category": "Enumeration",
              "path": "/usr/bin/nmap",
              "templates": ["nmap -sC -sV {{IP}}"]
            }
          ]
        }
        """,
        encoding="utf-8",
    )

    tm = ToolManager(config_manager)

    assert (
        "nmap -A {{IP}} -oN nmap_advanced_{{IP}}.txt {{IP}}"
        in tm.get("nmap").templates
    )
