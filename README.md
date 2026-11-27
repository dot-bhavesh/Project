# Gyan Yantra — 11th-Grade NCERT Doubt Solver & Formula Finder

![Platform](https://shields.io)
![Python](https://shields.io)
![Offline](https://shields.io)

**Gyan Yantra** is an offline-first CLI workbench for Class 11 NCERT textbooks. It combines instant formula/topic search, doubt solving, and direct PDF page jumping via `zathura`—designed for keyboard-driven workflows like `i3wm`.

## Demo Video

https://github.com/user-attachments/assets/e7e6bb47-f06e-4f31-8c75-cd8203654db1

## Key Features

* **Interactive NCERT Doubt Solver:** Ask natural language questions (e.g., *"what is the formula of time of flight"*, *"what is dimension of velocity"*) to get instant summaries and key equations.
* **Direct PDF Page Jumping:** Automatically launches `zathura` right to the exact NCERT chapter and page where the formula or concept appears.
* **Chapter Browser:** Quickly navigate across Physics, Chemistry, and Mathematics chapters straight from the terminal.
* **Keyboard-First TUI:** Built with clean terminal navigation (`k`/`j` or `Up/Down` arrows, `/` to jump search, `Enter` to open, `q` to quit).

## Quick Start (GNU/Linux)

### Option 1: Clone via Git (Recommended)

```bash
sudo apt update
sudo apt install -y git python3 python3-venv zathura zathura-pdf-poppler
git clone https://github.com/dot-bhavesh/Project.git
cd <repo-name>
python3 -m venv venv
chmod +x run.sh
./run.sh
```

### Option 2: Download ZIP

If you downloaded the repository ZIP to your `Downloads` folder:

```bash
sudo apt update
sudo apt install -y python3 python3-venv unzip zathura zathura-pdf-poppler
cd ~/Downloads
unzip -q Project-main.zip
cd Project-main
python3 -m venv venv
chmod +x run.sh
./run.sh
```

## Controls

| Key | Action |
| :--- | :--- |
| `k` / `j` | Move selection |
| `/` | Jump search |
| `Enter` | Open selected chapter or PDF page |
| `q` / `Esc` | Go back or exit |
