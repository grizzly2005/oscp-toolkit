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


def test_tool_manager_replaces_legacy_nmap_templates(
    tmp_config_dir,
    config_manager,
):
    (tmp_config_dir / "defaults" / "tools.default.json").write_text(
        """
        {
          "tools": [
            {
              "name": "nmap",
              "category": "Enumeration",
              "path": "/usr/bin/nmap",
              "templates": [
                "nmap -sT -sC -sV -oN \\"$OSCP_NMAP/{{IP}}_tcp_connect.txt\\" {{IP}}",
                "sudo nmap -sU --top-ports 100 -oN \\"$OSCP_UDP/{{IP}}_udp_top100_root.txt\\" {{IP}}"
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
              "templates": [
                "nmap -sU --top-ports 100 -oN \\"$OSCP_UDP/{{IP}}_udp_top100.txt\\" {{IP}}",
                "nmap --script custom {{IP}}"
              ]
            }
          ]
        }
        """,
        encoding="utf-8",
    )

    tm = ToolManager(config_manager)
    templates = tm.get("nmap").templates

    assert (
        "nmap -sU --top-ports 100 -oN \"$OSCP_UDP/{{IP}}_udp_top100.txt\" {{IP}}"
        not in templates
    )
    assert (
        "sudo nmap -sU --top-ports 100 -oN \"$OSCP_UDP/{{IP}}_udp_top100_root.txt\" {{IP}}"
        in templates
    )
    assert "nmap --script custom {{IP}}" in templates


def test_tool_manager_replaces_legacy_ligolo_templates(
    tmp_config_dir,
    config_manager,
):
    (tmp_config_dir / "defaults" / "tools.default.json").write_text(
        """
        {
          "tools": [
            {
              "name": "ligolo-ng",
              "category": "Network",
              "path": "$BIN_LIN/network/ligolo/ligolo_proxy_lin",
              "doc_link": "cheatsheets/ligolo.md",
              "templates": [
                "sudo $BIN_LIN/network/ligolo/ligolo_proxy_lin -selfcert -laddr 0.0.0.0:{{LIGOLO_PORT}}",
                "sudo ip route add {{SUBNET}} dev {{LIGOLO_IFACE}} && ip route"
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
              "name": "ligolo-ng",
              "category": "Network",
              "path": "$BIN_LIN/network/ligolo/ligolo_proxy_lin",
              "templates": [
                "$BIN_LIN/network/ligolo/ligolo_proxy_lin -selfcert",
                "echo custom"
              ]
            }
          ]
        }
        """,
        encoding="utf-8",
    )

    tm = ToolManager(config_manager)
    tool = tm.get("ligolo-ng")

    assert "$BIN_LIN/network/ligolo/ligolo_proxy_lin -selfcert" not in tool.templates
    assert (
        "sudo $BIN_LIN/network/ligolo/ligolo_proxy_lin -selfcert -laddr 0.0.0.0:{{LIGOLO_PORT}}"
        in tool.templates
    )
    assert "echo custom" in tool.templates
    assert tool.doc_link == "cheatsheets/ligolo.md"


def test_tool_manager_replaces_legacy_gobuster_templates(
    tmp_config_dir,
    config_manager,
):
    (tmp_config_dir / "defaults" / "tools.default.json").write_text(
        """
        {
          "tools": [
            {
              "name": "gobuster",
              "category": "Enumeration",
              "path": "/usr/bin/gobuster",
              "templates": [
                "gobuster dir -u http://{{IP}} -w {{WEB_WORDLIST}} -t 50",
                "gobuster dns -d {{DOMAIN}} -w {{DNS_WORDLIST}} -t 50"
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
              "name": "gobuster",
              "category": "Enumeration",
              "path": "/usr/bin/gobuster",
              "templates": [
                "gobuster dir -u http://{{IP}} -w /usr/share/wordlists/dirb/common.txt",
                "gobuster dir -u http://{{IP}} -w {{WORDLIST}} -x php,html,txt -t 50",
                "gobuster dir -u http://{{IP}} -w custom.txt"
              ]
            }
          ]
        }
        """,
        encoding="utf-8",
    )

    tm = ToolManager(config_manager)
    templates = tm.get("gobuster").templates

    assert (
        "gobuster dir -u http://{{IP}} -w /usr/share/wordlists/dirb/common.txt"
        not in templates
    )
    assert "gobuster dir -u http://{{IP}} -w {{WEB_WORDLIST}} -t 50" in templates
    assert "gobuster dir -u http://{{IP}} -w custom.txt" in templates
