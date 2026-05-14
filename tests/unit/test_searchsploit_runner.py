from core.searchsploit_runner import (
    build_commands,
    build_queries,
    clean_searchsploit_output,
    has_searchsploit_results,
    parse_service_line,
)


def test_parse_simple_service_version():
    service = parse_service_line("OpenSSH 7.6p1")

    assert service.product == "openssh"
    assert service.version == "7.6p1"
    assert "7.6" in service.version_candidates


def test_parse_nmap_service_row():
    service = parse_service_line("21/tcp open ftp vsftpd 3.0.3")

    assert service.product == "vsftpd"
    assert service.version == "3.0.3"


def test_exim_queries_include_short_version_and_product():
    service = parse_service_line("Exim smtpd 4.90_1")

    queries = build_queries(service)

    assert "exim smtpd 4.90_1" in queries
    assert "exim 4.90" in queries
    assert "exim" not in queries


def test_build_commands_can_include_broad_fallback():
    commands = build_commands(["OpenSSH 7.6p1"], include_broad=True)

    assert "searchsploit openssh 7.6p1" in commands
    assert "searchsploit openssh" in commands


def test_has_searchsploit_results_detects_no_results():
    assert has_searchsploit_results("Exploits: No Results") is False


def test_has_searchsploit_results_detects_table_row():
    output = """
Exploit Title | Path
------------- | ----
OpenSSH 7.2p2 - User Enumeration | linux/remote/40136.py
"""

    assert has_searchsploit_results(output) is True


def test_has_searchsploit_results_ignores_shellcodes_no_results():
    output = """
Exploit Title | Path
------------- | ----
MySQL / MariaDB / PerconaDB 5.5.x/5.6.x/5.7.x - Privilege Escalation | linux/local/40678.c
Shellcodes: No Results
"""

    assert has_searchsploit_results(output) is True


def test_has_searchsploit_results_handles_ansi_highlights():
    output = """
Exploit Title | Path
------------- | ----
\x1b[01;31m\x1b[KMySQL\x1b[m\x1b[K < \x1b[01;31m\x1b[K5.7\x1b[m\x1b[K.17 - Integer Overflow | multiple/dos/41954.py
Shellcodes: No Results
"""

    assert has_searchsploit_results(output) is True
    assert "\x1b[" not in clean_searchsploit_output(output)


def test_mysql_patch_version_queries_fall_back_to_minor():
    service = parse_service_line("MySQL 5.7.40-0")
    queries = build_queries(service)

    assert "mysql 5.7.40-0" in queries
    assert "mysql 5.7" in queries


def test_httpd_queries_include_apache_alias():
    service = parse_service_line("httpd 2.4.29")
    queries = build_queries(service)

    assert "httpd 2.4.29" in queries
    assert "apache 2.4" in queries


def test_bare_smtpd_queries_include_exim_alias():
    service = parse_service_line("smtpd 4.90_1")
    queries = build_queries(service)

    assert "smtpd 4.90_1" in queries
    assert "exim 4.90" in queries
