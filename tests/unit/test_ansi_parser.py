"""Tests pour le parser ANSI de terminal_tab.

On teste en isolation les regex (sans initier QApplication).
"""
import re


# Copie des regex exactes depuis terminal_tab.py
_ANSI_RE = re.compile(r'\x1B\[([0-9;?]*?)([A-Za-z])')
_STRIP_OSC_RE  = re.compile(r'\x1B\][^\x07\x1B]*(?:\x07|\x1B\\)')
_STRIP_SEQ_RE  = re.compile(r'\x1B[PX_^][^\x1B]*\x1B\\')
_STRIP_CTRL_RE = re.compile(r'[\x00-\x08\x0B\x0C\x0E-\x1A\x1C-\x1F]')


def _clean(text):
    t = _STRIP_OSC_RE.sub('', text)
    t = _STRIP_SEQ_RE.sub('', t)
    t = _STRIP_CTRL_RE.sub('', t)
    last = 0
    out = ""
    for m in _ANSI_RE.finditer(t):
        out += t[last:m.start()]
        last = m.end()
    out += t[last:]
    return out


def test_strip_bracketed_paste():
    raw = "\x1b[?2004h\x1b[?2004l"
    assert _clean(raw) == ""


def test_strip_osc_title():
    raw = "\x1b]0;window title\x07hello"
    assert _clean(raw) == "hello"


def test_preserve_cr():
    raw = "Scanning 50%\rScanning 100%\n"
    assert _clean(raw) == "Scanning 50%\rScanning 100%\n"


def test_strip_sgr_colors():
    raw = "\x1b[32mgreen\x1b[0m"
    assert _clean(raw) == "green"


def test_strip_cursor_move():
    raw = "\x1b[2J\x1b[Hhome"
    assert _clean(raw) == "home"


def test_escape_not_mangled_by_ctrl_strip():
    """Bug fixe : \\x1b (0x1b) ne doit PAS etre dans STRIP_CTRL_RE sinon
    les CSI orphelines laissent '[...' en clair."""
    raw = "\x1b[?2004h"
    out = _clean(raw)
    assert out == "", f"Expected empty, got {out!r}"


def test_real_bash_prompt():
    raw = "\x1b[?2004h\x1b]0;kali@kali: /tmp\x07\nkali@kali /tmp $ "
    out = _clean(raw)
    assert out == "\nkali@kali /tmp $ "


def test_bell_stripped():
    raw = "beep\x07end"
    assert _clean(raw) == "beepend"


def test_compact_progress_updates_keeps_last_carriage_return_state():
    from ui.terminal_tab import _compact_progress_updates

    raw = "Progress 1%\rProgress 50%\rProgress 100%\nfound /admin\n"

    assert _compact_progress_updates(raw) == "Progress 100%\nfound /admin\n"
