# OSCP Toolkit

**An all-in-one PyQt5 desktop app for OSCP exam prep and pentest workflows.**

Built during 6 months of HTB/PG labs to solve one specific frustration: the constant context-switching between 12+ terminal windows, scattered notes, repeated IP retyping, and forgotten screenshots before machine reverts.


---

## Why this exists

During lab grinding I lost real time to:

- Retyping the same IPs across 40 different tools
- Hunting for notes scattered across Obsidian, `.txt` files and bash history
- Re-crafting `nmap`/`ffuf`/`crackmapexec` commands from scratch on every target
- Switching between 12 terminal windows for 4 active machines
- Forgetting to screenshot proof before a revert

So I built a unified GUI that orchestrates a full pentest session end-to-end, designed specifically around the OSCP workflow.

## What it does

| Feature | What it gives you |
|---|---|
| **Scope manager** | Targets + subnets in one view, drag&drop between `todo` / `in-progress` / `rooted` |
| **Tool launcher** | 80+ pre-configured tools with templates (`{{IP}}`, `{{LHOST}}`, `{{TARGET}}` auto-injected from scope) |
| **Embedded terminals** | Multi-tab with auto-dump, searchable history, hung-process detection |
| **Credential vault** | Discovered creds & hashes, reusable in tools with one click |
| **Reverse shell generator** | 20+ payload variants, base64/URL/PS encoding, paired listener + msfvenom |
| **Markdown notes** | Auto-injects launched commands with timestamps, full-text search |
| **HTTP / SMB file server** | One-click expose of a payload from `data/serving/` |
| **Ligolo, Responder, BloodHound** | Toggle buttons for pivot setup |
| **Exam timer** | 23h45 countdown, persisted across restarts |
| **Quick actions** | F2 = listener, F3 = HTTP server, F4 = Ligolo, F9 = proof screenshot |

## Stack

- **Python 3.10+** & **PyQt5**
- ~16,000 LOC across `core/` (business logic) and `ui/` (presentation)
- Decoupled architecture: `core/*` has zero Qt imports except for QObject signals
- JSON-backed persistence with atomic writes + corruption recovery
- 100% local, no cloud, no telemetry

## Tested on

- **Kali Linux** (native xterm/gnome-terminal/xfce4-terminal)
- **Windows 11 + WSL2 + WSLg** (auto-detected, MIT-SHM disabled, `xcb` forced)
- Ubuntu 22.04 (should work, less tested)

## Screenshots



<img width="1905" height="997" alt="image" src="https://github.com/user-attachments/assets/a098e808-a055-4ed3-bfec-70cabe77e7cd" />
<img width="623" height="399" alt="image" src="https://github.com/user-attachments/assets/a29acbe2-a133-4087-9543-09a890e27767" />
<img width="1903" height="997" alt="image" src="https://github.com/user-attachments/assets/8d1921dc-98a9-431e-9b58-9a11e5b3200e" />
<img width="1907" height="999" alt="image" src="https://github.com/user-attachments/assets/211912a0-76dc-4d1e-af36-8ba46b34e218" />
<img width="306" height="171" alt="image" src="https://github.com/user-attachments/assets/1789f36a-2ec9-4317-b492-f865179615e2" />
<img width="454" height="303" alt="image" src="https://github.com/user-attachments/assets/ae81f811-9b11-4649-8cba-54bad445aa00" />



## Installation

```bash
# Kali / Ubuntu
sudo apt install python3-pip python3-pyqt5
git clone https://github.com/<you>/oscp-toolkit.git
cd oscp-toolkit
pip install -r requirements.txt --break-system-packages

# Or in a venv
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Run
python3 main.py
```

### WSL2 + WSLg

The bootstrap auto-detects WSLg and applies the necessary workarounds:
- Forces `QT_QPA_PLATFORM=xcb` (wayland backend has known issues with Qt5 on WSLg)
- Disables MIT-SHM (`QT_X11_NO_MITSHM=1`) which causes freezes
- Sanitizes saved window positions across multi-monitor setups

No manual env vars needed.

### Troubleshooting

If the app freezes on launch:
```bash
OSCP_SAFE=1 python3 main.py
```
This skips loading `layout.json` and `last_session.json`, useful after a bad shutdown.

To reset the saved window position (e.g. if it spawns off-screen on a secondary monitor that's now disconnected):
```bash
rm config/layout.json
```

## Project structure

```
toolkit/
├── app/             # Bootstrap & service container
├── core/            # Business logic — pure Python, zero Qt UI
│   ├── repositories/  # Storage abstraction (JSON-backed FS for now)
│   ├── config_manager.py
│   ├── scope_manager.py
│   ├── tool_manager.py
│   ├── credential_vault.py
│   ├── terminal.py        # PTY worker (QThread)
│   └── ...
├── ui/              # Qt panels and dialogs
│   ├── main_window.py
│   ├── terminal_tab.py
│   ├── tool_panel.py
│   └── ...
├── config/          # JSON configs + defaults/
├── data/            # User data (notes, screenshots, sessions)
├── cheatsheets/     # Markdown crib sheets bundled in the app
└── tests/unit/      # Pytest suite
```

## Contributing

PRs welcome, especially for:
- New tool templates in `config/defaults/tools.default.json`
- Cheatsheets in `cheatsheets/`
- Bug reports with reproduction steps

Style: keep `core/` Qt-free. Panels in `ui/` consume `core` via signals only.

## What this is NOT

- ❌ Not an autopwn tool, no flag-finding automation
- ❌ Not a reporting tool — output is for your own use, no client deliverables
- ❌ Not an auto-recon orchestrator (use AutoRecon, Sniper, etc. for that — this is the GUI shell that *organizes* what those tools produce)

## License

MIT. Use at your own risk on systems you have authorization to test.

## Acknowledgments

Inspired by the pain of grinding 30+ HTB/PG boxes solo. Shoutouts to the OSCP community on Discord and the offsec subreddit for feedback during the build.

---

**Disclaimer**: this tool is for authorized security testing only (CTFs, labs, your own infrastructure, paid engagements). The author assumes no liability for misuse. Don't be that person.
