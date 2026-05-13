from core.transfer_helper import generate


def test_linux_http_quotes_spaces_and_keeps_posix_destination():
    pairs = generate("/opt/tools/my tool.sh", "10.10.14.5", "linux", port_http=8080)
    wget = pairs[0]

    assert "my%20tool.sh" in wget.victim_command
    assert "'/tmp/my tool.sh'" in wget.victim_command
    assert "\\tmp" not in wget.victim_command
    assert "--directory /opt/tools" in wget.attacker_command


def test_windows_http_quotes_destination_and_url_encodes_name():
    pairs = generate(
        r"C:\Tools\my tool.ps1",
        "10.10.14.5",
        "windows",
        port_http=8080,
        dest_dir=r"C:\Windows\Temp",
    )
    certutil = pairs[0]

    assert "my%20tool.ps1" in certutil.victim_command
    assert '"C:\\Windows\\Temp\\my tool.ps1"' in certutil.victim_command
    assert certutil.recommended is True
