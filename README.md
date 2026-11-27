# 11th-Grade NCERT Doubt Solver & Formula/Page Finder

Offline-first CLI tool for Class 11 NCERT lookup, formula/page search, doubt solving, and direct PDF page viewing via `zathura` on Linux + `i3wm`.

## Demo Video


https://github.com/user-attachments/assets/e7e6bb47-f06e-4f31-8c75-cd8203654db1


This is the exact code for terminal to run it on any new device after downloading it to the Downloads folder:

sudo apt update
sudo apt install -y python3 python3-venv unzip zathura zathura-pdf-poppler
cd ~/Downloads
unzip -q Project-main.zip
cd Project-main
python3 -m venv venv
chmod +x run.sh
./run.sh
