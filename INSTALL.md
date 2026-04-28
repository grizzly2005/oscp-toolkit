# OSCP Toolkit — Installation Guide

Hey, glad you're testing this! Here's the 5-min setup.

## Prerequisites

- **Kali Linux** (preferred) or **Ubuntu 22.04+** with a desktop environment
  - Works on **WSL2 + WSLg** too (auto-detected)
- **Python 3.10+**
- ~150 MB disk space for the toolkit + dependencies

## Step 1 — Drop the project somewhere

The toolkit expects this directory layout:

```
your_pentest_workspace/
├── toolkit/             ← unzip here
├── binaries/            ← optional: ligolo, responder, etc.
│   ├── linux/
│   └── windows/
├── wordlists/           ← optional: rockyou, SecLists, etc.
└── scripts/             ← optional: your custom scripts
```

The `binaries/`, `wordlists/`, `scripts/` siblings are **optional** but if present, the toolkit will auto-inject env vars (`$BIN_LIN`, `$BIN_WIN`, `$WORDLISTS`, `$SCRIPTS`) into every spawned terminal.

```bash
# Pick a workspace
mkdir -p ~/pentest && cd ~/pentest

# Drop the toolkit zip here and extract
unzip /path/to/toolkit.zip
# This creates ~/pentest/toolkit/

cd toolkit
```

## Step 2 — Install dependencies

```bash
# Kali / Ubuntu
sudo apt update
sudo apt install python3-pip python3-pyqt5

# Python deps
pip install -r requirements.txt --break-system-packages

# Or use a venv if you prefer
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

If `python3-pyqt5` from apt fails or is too old, install via pip:
```bash
pip install PyQt5 --break-system-packages
```

## Step 3 — Run it

```bash
python3 main.py
```

First launch will:
- Create `data/`, `logs/`, runtime dirs
- Generate default configs in `config/`
- Run a preflight check (lists missing tools — none are blocking)
- Open the main window

## Optional config

### Set your attacker IP for default LHOST

In the app: **right-click on the IP in the bottom status bar** → "Set IP manually" → enter your tun0 IP. The toolkit auto-detects `tun0` / `eth0` / `wlan0`, so usually you don't need this.

### Customize the path to ligolo / responder / bloodhound

Edit `config/services_overrides.json` (auto-created on first launch):
```json
{
  "ligolo-proxy": {
    "command": ["/your/path/to/ligolo_proxy_lin", "-selfcert"],
    "cwd": "/your/path/to/ligolo"
  }
}
```
The defaults expect `<workspace>/binaries/linux/network/ligolo/ligolo_proxy_lin`. If your binaries live elsewhere, the JSON above overrides them.

### Use Windows Terminal instead of xterm

If you're on WSL and want external terminals to spawn in Windows Terminal (`wt.exe`):
- The toolkit auto-detects `wt.exe` in `/mnt/c/Users/<your_user>/AppData/Local/Microsoft/WindowsApps/`
- Or set the env var: `export OSCP_WT_PATH=/path/to/wt.exe`

## Troubleshooting

### App freezes on launch

```bash
OSCP_SAFE=1 python3 main.py
```
This skips `layout.json` and `last_session.json` (useful after a hard crash).

### Window opens off-screen

Likely a multi-monitor saved position with one display disconnected:
```bash
rm config/layout.json
python3 main.py
```

### "QSocketNotifier: Can only be used with threads started with QThread"

This is a benign warning on WSLg, ignore it.

### Errors from chromium-snap pollute your terminal

If you click "Open revshells.com" and get spammed with `update.go`, `libpxbackend`, `dbus/UPower` errors, that's chromium-snap on Kali. The toolkit redirects browser stderr to /dev/null but if chromium is auto-launching from elsewhere, install it via apt instead:
```bash
sudo snap remove chromium
sudo apt install chromium
```

### Some tools missing from preflight

That's normal — the preflight just lists what's available. Missing tools won't block the toolkit, they'll just show a warning when you try to launch them.

## What to test (please ⚙️)

- **Run a few terminals in parallel** — open 3-4 tabs, run `nmap`, `ffuf`, etc. Try the 2x2 grid (`F6`).
- **Ctrl+T** in main window → opens a new terminal. Should not freeze, should not warn "Ambiguous shortcut" anymore.
- **Right-click on the IP in the status bar** → menu should appear (was crashing with `NameError: QMenu` in earlier builds).
- **Double-click a tool** in the tool panel → placeholder dialog → click on a target IP in the right panel → should auto-fill `{{IP}}` in the command.
- **Drag a file into the file server panel** → should be served on HTTP and the URL copied to clipboard.
- **Open and close the app a few times** with running terminals → should prompt "active terminals, really quit?" and clean up properly.
- **F2 / F3 / F4 / F9 shortcuts** → quick listener / HTTP / Ligolo / proof screenshot.

## Reporting bugs back

Logs are in `logs/app.log`. If something crashes, grab:
- The last 50 lines of `logs/app.log`
- The exact action that triggered it (e.g. "clicked X then Y")
- Output of `python3 --version` and `pip show PyQt5 | grep Version`

Send those to me on Discord/Signal and I'll have a fix the same evening.

Thanks for testing! 🙏